"""Read-only stock checks for explicitly linked active variants."""
from collections import Counter
from datetime import datetime, timezone
from cj_client import CJError
from coletar_conciliacao import CollectionError
from estoque_comparacao import compare_inventory


QUERY = '''query VariantInventory($id: ID!, $after: String) { productVariant(id: $id) { id sku inventoryItem { inventoryLevels(first: 50, after: $after) { nodes { location { id name } quantities(names: ["available", "committed"]) { name quantity } } pageInfo { hasNextPage endCursor } } } } }'''


def shopify_levels(reader, variant_id, sku):
    cursor, cursors, locations, seen_locations = None, set(), [], set()
    for _ in range(20):
        data = reader._transport(QUERY, {'id': variant_id, 'after': cursor})
        variant = data.get('productVariant') if isinstance(data, dict) else None
        if not isinstance(variant, dict) or variant.get('id') != variant_id or variant.get('sku') != sku:
            raise CollectionError('Variante Shopify divergente.')
        block = (variant.get('inventoryItem') or {}).get('inventoryLevels')
        if not isinstance(block, dict) or not isinstance(block.get('nodes'), list) or not isinstance(block.get('pageInfo'), dict):
            raise CollectionError('Estoque Shopify incompleto.')
        info = block['pageInfo']
        if type(info.get('hasNextPage')) is not bool:
            raise CollectionError('Paginação do estoque inválida.')
        if info['hasNextPage'] and not block['nodes']:
            raise CollectionError('Página de estoque vazia antes do fim da lista.')
        for item in block['nodes']:
            if not isinstance(item, dict) or not isinstance(item.get('location'), dict) or not isinstance(item.get('quantities'), list):
                raise CollectionError('Localização de estoque inválida.')
            loc = item['location']
            if not isinstance(loc.get('id'), str) or not loc['id'] or loc['id'] in seen_locations or not isinstance(loc.get('name'), str):
                raise CollectionError('Localização repetida ou inválida.')
            seen_locations.add(loc['id'])
            quantities = item['quantities']
            if any(not isinstance(q, dict) for q in quantities):
                raise CollectionError('Quantidade inválida.')
            available = [q.get('quantity') for q in quantities if q.get('name') == 'available']
            committed = [q.get('quantity') for q in quantities if q.get('name') == 'committed']
            if len(available) != 1 or len(committed) != 1:
                raise CollectionError('Quantidades não confirmadas.')
            locations.append({'sku': sku, 'location_name': loc['name'],
                              'available': available[0], 'committed': committed[0]})
        if not info['hasNextPage']:
            return locations
        cursor = info.get('endCursor')
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise CollectionError('Cursor de estoque inválido.')
        cursors.add(cursor)
    raise CollectionError('Limite de páginas de estoque excedido.')


def scan(report, shopify, cj, *, origin='US', limit=50, start_after=None):
    if report.get('complete') is not True or not isinstance(report.get('variants'), list):
        raise CollectionError('Conciliação incompleta.')
    if not isinstance(origin, str) or len(origin) != 2 or not origin.isascii() or not origin.isalpha() or not origin.isupper():
        raise CollectionError('País de origem inválido.')
    if type(limit) is not int or not 1 <= limit <= 50:
        raise CollectionError('Limite de estoque inválido.')
    if start_after is not None and (not isinstance(start_after, str) or not start_after.isascii() or not start_after.isdigit()):
        raise CollectionError('Marcador de estoque inválido.')
    active = [r for r in report['variants'] if r.get('product_status') == 'ACTIVE']
    sku_counts = Counter(r.get('sku') for r in active if isinstance(r.get('sku'), str) and r['sku'])
    id_counts = Counter(r.get('variant_id') for r in active if isinstance(r.get('variant_id'), str))
    eligible = sorted(r['variant_id'] for r in active if r.get('link_status') == 'VINCULO_IDENTIFICADO'
                      and isinstance(r.get('sku'), str) and r['sku'] and sku_counts[r['sku']] == 1
                      and isinstance(r.get('variant_id'), str) and r['variant_id'].isascii()
                      and r['variant_id'].isdigit() and id_counts[r['variant_id']] == 1)
    rotated = ([v for v in eligible if start_after is None or v > start_after] +
               [v for v in eligible if start_after is not None and v <= start_after])
    chosen = rotated[:limit]
    selected = set(chosen)
    rows, attempted = [], 0
    for row in active:
        sku, variant = row.get('sku'), row.get('variant_id')
        item = {'sku': sku, 'variant_id': variant, 'country': origin, 'status': 'NAO_CONCLUSIVO', 'write_allowed': False}
        if row.get('link_status') != 'VINCULO_IDENTIFICADO' or not isinstance(sku, str) or not sku or sku_counts[sku] != 1:
            item['reason'] = 'Vínculo ou SKU não confirmado de forma única.'
        elif not isinstance(variant, str) or not variant.isascii() or not variant.isdigit() or id_counts[variant] != 1:
            item['reason'] = 'Identificador de variante inválido.'
        elif variant not in selected:
            item['reason'] = 'Limite de consultas atingido; verificação pendente.'
        else:
            attempted += 1
            try:
                levels = shopify_levels(shopify, 'gid://shopify/ProductVariant/' + variant, sku)
                cj_stock = cj.stock(sku)
                now = datetime.now(timezone.utc)
                item = compare_inventory(sku=sku, country=origin, shop_levels=levels, cj_rows=cj_stock,
                                         observed_at=now.isoformat(), now=now)
                item['variant_id'] = variant
                item['observed_at'] = now.isoformat()
            except (CJError, CollectionError):
                item['reason'] = 'Consulta incompleta; verifique acesso ou disponibilidade.'
        rows.append(item)
    counts = dict(Counter(x['status'] for x in rows))
    return {'origin': origin, 'active_variants': len(active), 'attempted': attempted,
            'next_after': chosen[-1] if chosen else None,
            'counts': counts, 'results': rows,
            'note': 'Leitura pontual; diferenças exigem investigação e não são corrigidas automaticamente.',
            'write_allowed': False}
