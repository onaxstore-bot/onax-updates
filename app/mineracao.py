"""Compare normalized research evidence offline. No crawler or store writes."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from core import Blocked, Costs, decimal
from pricing_scenarios import price_for_revenue_margin
from pricing_guard import evaluate


def cost_ceiling(sale_price, margin, fees_rate):
    """Maximum fixed costs after ads 5%, reserve 2% and verified fee rate."""
    price = decimal(sale_price, 'sale_price')
    target = decimal(margin, 'margin')
    fees = decimal(fees_rate, 'fees_rate')
    if price <= 0 or not Decimal('.30') <= target <= Decimal('.50'):
        raise Blocked('invalid sale price or margin')
    remaining = Decimal('.93') - target - fees
    if remaining <= 0:
        raise Blocked('no feasible cost ceiling')
    return (price * remaining).quantize(Decimal('.01'), rounding=ROUND_FLOOR)


def assess(offer, *, now):
    """Research triage only: even complete evidence never publishes or buys."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise Blocked('timezone required')
    reasons = []
    try:
        seen = datetime.fromisoformat(offer['observed_at'].replace('Z', '+00:00'))
        if seen.tzinfo is None or seen.utcoffset() is None:
            raise ValueError('timezone missing')
        age = (now - seen).total_seconds()
        if age < 0 or age > 86400:
            reasons.append('evidencia_antiga_ou_data_invalida')
    except (KeyError, ValueError, TypeError):
        reasons.append('data_nao_confirmada')
    moq = offer.get('minimum_order')
    reject = type(moq) is int and moq > 1
    if reject:
        reasons.append('exige_compra_em_lote')
    elif type(moq) is not int or moq != 1:
        reasons.append('pedido_unitario_nao_confirmado')
    for field in ('variant_verified', 'pack_verified', 'price_revalidated',
                  'direct_fulfillment_verified', 'route_verified',
                  'ready_stock_verified', 'demand_verified'):
        if offer.get(field) is not True:
            reasons.append(field)
    if offer.get('moq_conflict') is True:
        reasons.append('quantidade_minima_contraditoria')
    currencies_match = (isinstance(offer.get('cost_currency'), str) and
                        len(offer['cost_currency']) == 3 and
                        offer['cost_currency'].isalpha() and
                        offer['cost_currency'].isupper() and
                        offer['cost_currency'] == offer.get('sale_currency'))
    if not currencies_match:
        reasons.append('moedas_nao_conciliadas')
    floors = None
    try:
        if offer.get('costs_verified') is not True or not currencies_match:
            raise Blocked('custos_nao_verificados')
        costs = Costs(**offer['costs'])
        floors = {str(m): str(price_for_revenue_margin(costs, m)) for m in ('0.30', '0.50')}
    except (Blocked, TypeError, KeyError):
        reasons.append('custos_completos_pendentes')
    if floors:
        try:
            decision = evaluate(costs, offer.get('competitive_sale_price'),
                                costs_verified=offer.get('costs_verified'),
                                comparison_verified=offer.get('comparison_verified'))
            if decision['status'] == 'BLOCKED':
                raise Blocked('comparacao_nao_verificada')
            if decision['status'] == 'UNCOMPETITIVE':
                reject = True
                reasons.append('preco_competitivo_nao_comporta_margem_30')
        except Blocked:
            reasons.append('comparacao_de_mercado_pendente')
    return {'id': offer['id'], 'status': 'DESCARTAR_OFERTA' if reject else
            ('ANALISAR' if reasons else 'PRONTO_PARA_REVISAO'),
            'reasons': reasons, 'price_floors': floors,
            'publish_allowed': False, 'purchase_allowed': False}


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='Triagem de pesquisa já coletada, sem compras ou publicações.')
    parser.add_argument('--input', type=Path, default=root / 'pesquisa_multiplataforma.json')
    parser.add_argument('--output', type=Path, help='Caminho para salvar o relatório JSON; deve ser diferente da entrada.')
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() == args.input.resolve():
            raise ValueError('O relatório não pode substituir o arquivo de entrada.')
        evidence = json.loads(args.input.read_text(encoding='utf-8'))
        if not isinstance(evidence, dict) or not isinstance(evidence.get('offers'), list):
            raise ValueError('A entrada deve conter uma lista offers.')
        results = []
        for index, item in enumerate(evidence['offers']):
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
                results.append({'id': None, 'status': 'ANALISAR', 'reasons': ['identificacao_ou_registro_invalido'],
                                'record_index': index, 'price_floors': None,
                                'publish_allowed': False, 'purchase_allowed': False})
                continue
            results.append(assess(item, now=datetime.now(timezone.utc)))
        report = json.dumps({'mode': 'OFFLINE_RESEARCH_ONLY', 'results': results}, ensure_ascii=False, indent=2)
        if args.output:
            # Exclusive create prevents silently overwriting user data or a previous report.
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(report + '\n')
            print('Relatório salvo em', args.output)
        else:
            print(report)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, 'Não foi possível gerar a triagem: %s\n' % exc)
