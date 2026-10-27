"""Read-only CJ variant quote and provisional profitability calculation."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cj_client import CJClient, CJError
from consultar_cj import read_key
from core import Blocked, Costs, decimal
from pricing_scenarios import price_for_revenue_margin
from concorrencia import compare


def inventory_observation(data, origin):
    """Keep factory and CJ stock separate; counts alone do not authorize fulfillment."""
    observation = {'status': 'NAO_CONFIRMADO', 'origin': origin, 'warehouses': [],
                   'ready_stock_verified': False}
    if not isinstance(data, list):
        observation['reason'] = 'Formato de estoque não reconhecido.'
        return observation
    for row in data:
        if not isinstance(row, dict) or row.get('countryCode') != origin:
            continue
        cj, factory = row.get('cjInventoryNum'), row.get('factoryInventoryNum')
        if type(cj) is not int or cj < 0 or type(factory) is not int or factory < 0:
            observation['reason'] = 'Quantidade por origem incompleta.'
            return observation
        observation['warehouses'].append({'name': row.get('areaEn'), 'cj': cj, 'factory': factory})
    if not observation['warehouses']:
        observation['reason'] = 'Estoque da origem não localizado.'
    else:
        observation['reason'] = 'Quantidades consultadas; disponibilidade por rota ainda não validada.'
    return observation


def analyze(client, *, pid, sku, origin, destination, postal_code, method, assumptions, competition=None):
    product = client.product(sku)
    if not isinstance(product, dict) or product.get('pid') != pid:
        raise CJError('Produto não corresponde à pesquisa; análise interrompida.')
    variants = product.get('variants')
    if not isinstance(variants, list) or any(not isinstance(v, dict) for v in variants):
        raise CJError('Variantes inválidas ou ausentes.')
    selected = [v for v in variants if v.get('variantSku') == sku and v.get('pid') == pid]
    if len(selected) != 1 or not isinstance(selected[0].get('vid'), str) or not selected[0]['vid']:
        raise CJError('Variante sem correspondência única; análise interrompida.')
    variant = selected[0]
    price = variant.get('variantSellPrice')
    # CJ JSON numbers are parsed as Decimal by the HTTP client.
    try:
        product_price = decimal(price, 'preço da variante')
        if product_price <= 0:
            raise Blocked('preço da variante não positivo')
    except Blocked:
        raise CJError('Preço da variante ausente ou inválido.') from None
    quotes = client.freight(variant['vid'], destination, origin, zip_code=postal_code)
    try:
        inventory = inventory_observation(client.stock(sku), origin)
    except CJError:
        inventory = inventory_observation(None, origin)
    matches = [q for q in quotes if q.get('method') == method]
    report = {'mode': 'ESTIMATIVA_NAO_APROVADA', 'queried_at': datetime.now(timezone.utc).isoformat(),
              'pid': pid, 'sku': sku, 'variant_id': variant['vid'], 'currency': 'USD',
              'product_price_usd': str(product_price), 'origin': origin, 'destination': destination,
              'postal_code_provided': bool(postal_code), 'shipping_quotes': quotes,
              'selected_method': method, 'price_floors': None, 'assumptions': assumptions,
              'inventory': inventory, 'competition': None,
              'pending': ['estoque por variante e rota', 'validação do frete e destino',
                          'custos e impostos reais', 'comparação de concorrência'],
              'publish_allowed': False, 'purchase_allowed': False}
    if len(matches) != 1 or matches[0].get('total_shipping_usd') is None:
        report['pending'].append('método de frete único com valor total informado pela CJ')
        return report
    try:
        expected = {'fixed_fees', 'tax_and_fx', 'returns_reserve', 'overhead',
                    'proportional_fees', 'ads_rate', 'chatgpt_reserve'}
        if not isinstance(assumptions, dict) or set(assumptions) != expected:
            raise Blocked('custos incompletos')
        costs = Costs(product=str(product_price), freight=matches[0]['total_shipping_usd'], **assumptions)
        report['price_floors'] = {target: str(price_for_revenue_margin(costs, target)) for target in ('0.30', '0.50')}
        report['competition'] = compare(competition, pid=pid, sku=sku, country=destination,
                                        currency='USD', minimum_price=report['price_floors']['0.30'],
                                        now=datetime.now(timezone.utc))
    except (Blocked, TypeError):
        report['pending'].append('premissas de custos completas e válidas')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Cotação preliminar CJ por variante; somente leitura.')
    parser.add_argument('--pesquisa', type=Path, required=True)
    parser.add_argument('--produto', required=True, help='ID do produto CJ presente no relatório de busca')
    parser.add_argument('--sku', required=True, help='SKU da variante escolhida')
    parser.add_argument('--origem', default='CN')
    parser.add_argument('--destino', default='US')
    parser.add_argument('--cep')
    parser.add_argument('--metodo', required=True, help='Nome exato da modalidade CJ')
    parser.add_argument('--custos', type=Path, required=True, help='Arquivo JSON de premissas explícitas')
    parser.add_argument('--concorrencia', type=Path, help='Ofertas documentadas no país de destino')
    parser.add_argument('--saida', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.saida.exists():
            raise ValueError('Arquivo de saída já existe.')
        research = json.loads(args.pesquisa.read_text(encoding='utf-8'))
        assumptions = json.loads(args.custos.read_text(encoding='utf-8'))
        competition = json.loads(args.concorrencia.read_text(encoding='utf-8')) if args.concorrencia else None
        rows = research.get('results', []) if isinstance(research, dict) and research.get('mode') == 'CJ_RESEARCH_ONLY' else []
        if sum(isinstance(r, dict) and isinstance(r.get('product'), dict) and r['product'].get('pid') == args.produto for r in rows) != 1:
            raise ValueError('Produto não encontrado de forma única no relatório de busca.')
        client = CJClient(os.environ.get('CJ_API_KEY') or read_key())
        report = analyze(client, pid=args.produto, sku=args.sku, origin=args.origem,
                         destination=args.destino, postal_code=args.cep, method=args.metodo,
                         assumptions=assumptions, competition=competition)
        with args.saida.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
        print('Estimativa salva em %s; nenhuma publicação ou compra foi realizada.' % args.saida)
        return 0
    except (CJError, ValueError, OSError) as exc:
        print('Análise não concluída: %s' % exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
