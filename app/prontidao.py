"""Local readiness report from an authenticated Shopify snapshot; never publishes."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path


def positive_price(value):
    if not isinstance(value, str):
        return False
    try:
        number = Decimal(value)
        return number.is_finite() and number > 0
    except InvalidOperation:
        return False


def assess(snapshot, catalog, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('O horário de referência deve conter fuso horário.')
    blocks = []
    try:
        observed = datetime.fromisoformat(snapshot['observed_at'].replace('Z', '+00:00'))
        if observed.tzinfo is None or not timedelta(0) <= now - observed <= timedelta(hours=24):
            blocks.append('Leitura da Shopify antiga ou data inválida; atualizar antes de decidir.')
    except (KeyError, ValueError, TypeError):
        blocks.append('Data da leitura da Shopify ausente ou inválida.')
    data = snapshot.get('data') or {}
    shop = data.get('shop') or {}
    if (shop.get('plan') or {}).get('publicDisplayName', '').lower() in ('', 'trial'):
        blocks.append('Plano para vendas ainda não confirmado.')
    if not any(x.get('locale') == 'en' and x.get('published') is True for x in data.get('shopLocales', [])):
        blocks.append('Inglês ainda não publicado.')
    markets = data.get('markets') or {}
    if not any(x.get('name') == 'Estados Unidos' and x.get('status') == 'ACTIVE' for x in markets.get('nodes', [])):
        blocks.append('Mercado dos EUA ainda não ativo ou não confirmado.')
    for key in ('markets', 'deliveryProfiles', 'products'):
        if ((data.get(key) or {}).get('pageInfo') or {}).get('hasNextPage') is not False:
            blocks.append(f'Leitura incompleta de {key}; não assumir cobertura integral.')
    # These facts cannot be inferred from a shipping zone, stock counter or locale.
    for label in ('Gateway de pagamento e recebimento', 'Políticas comerciais e identidade do vendedor',
                  'Rotas e custos de frete da CJ', 'Credenciais e agente contínuo',
                  'Base de cálculo do lucro de 30–50%', 'Limites e saldo para compras reais'):
        blocks.append(label + ': validação operacional pendente.')
    prepared = {}
    duplicates = set()
    for item in catalog.get('items', []):
        key = str(item.get('shopify_product_id') or '').rsplit('/', 1)[-1]
        if not key:
            continue
        if key in prepared:
            duplicates.add(key)
        prepared[key] = item
    products = []
    for p in (data.get('products') or {}).get('nodes', []):
        reasons = []
        pid = p.get('id', '').rsplit('/', 1)[-1]
        item = prepared.get(pid) if pid and pid not in duplicates else None
        if pid in duplicates:
            reasons.append('Avaliação duplicada no catálogo; confirmar cadastro.')
        if not pid:
            reasons.append('Identificação do produto ausente.')
        if not item:
            reasons.append('Sem avaliação no catálogo de preparação.')
        if p.get('status') != 'DRAFT':
            reasons.append('Produto pendente fora de rascunho; requer revisão imediata.')
        if not isinstance((p.get('mediaCount') or {}).get('count'), int) or (p.get('mediaCount') or {}).get('count', 0) < 1:
            reasons.append('Sem fotos verificadas na Shopify.')
        variants = (p.get('variants') or {}).get('nodes', [])
        if ((p.get('variants') or {}).get('pageInfo') or {}).get('hasNextPage') is not False:
            reasons.append('Leitura incompleta das variantes; confirmar paginação.')
        if not variants:
            reasons.append('Sem variante confirmada.')
        for v in variants:
            if not isinstance(v.get('sku'), str) or not v['sku'].strip():
                reasons.append('SKU ausente.')
            if not positive_price(v.get('price')):
                reasons.append('Preço de venda ausente ou inválido.')
            if v.get('inventoryPolicy') != 'DENY':
                reasons.append('Venda sem estoque não está bloqueada na variante.')
        for flag, label in (('approved', 'Produto'), ('stock_confirmed', 'Estoque da variante'),
                            ('route_confirmed', 'Rota de entrega'), ('profit_verified', 'Lucro após custos')):
            if not item or item.get(flag) is not True:
                reasons.append(label + ' não validado.')
        products.append({'id': p.get('id'), 'name': p.get('title'), 'can_publish': False,
                         'blocks': list(dict.fromkeys(reasons))})
    if not products:
        blocks.append('Nenhum produto avaliado nesta leitura.')
    return {'mode': 'REPORT_ONLY', 'can_launch': False, 'can_purchase': False,
            'store_blocks': blocks, 'products': products,
            'note': 'Relatório local. Não configura pagamentos, publica produtos ou efetua compras.'}


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='Conferir pendências da ONAX sem alterar a loja.')
    parser.add_argument('--snapshot', type=Path, default=here / 'shopify_snapshot.json')
    parser.add_argument('--catalog', type=Path, default=here / 'pre_catalogo.json')
    parser.add_argument('--output', type=Path, default=here / 'prontidao_onax.json')
    args = parser.parse_args()
    report = assess(json.loads(args.snapshot.read_text(encoding='utf-8')),
                    json.loads(args.catalog.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('ONAX: vendas e compras permanecem bloqueadas.')
    for p in report['products']:
        print(f"{p['name']}: {len(p['blocks'])} pendências")
    print('Relatório:', args.output)


if __name__ == '__main__':
    main()
