"""Compare a Shopify catalog snapshot with CJ connections. Read-only."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def numeric_id(value, prefix):
    if not isinstance(value, str):
        return None
    if value.startswith(prefix):
        value = value[len(prefix):]
    return value if value.isascii() and value.isdigit() else None


def reconcile(products, connections, *, shop_id, expected_products, expected_connections):
    if not isinstance(products, list) or not isinstance(connections, list) or not isinstance(shop_id, str):
        raise ValueError('Dados de catálogo ou vínculos inválidos.')
    issues, by_sku, by_variant, rows = [], defaultdict(list), defaultdict(list), []
    complete = (type(expected_products) is int and expected_products == len(products) and
                type(expected_connections) is int and expected_connections == len(connections))
    if not complete:
        issues.append('Leitura de produtos ou vínculos incompleta.')
    for conn in connections:
        if not isinstance(conn, dict) or conn.get('shopId') != shop_id:
            complete = False
            issues.append('Vínculo de loja desconhecida ou inválido.')
            continue
        vid = numeric_id(conn.get('platformVariantId'), 'gid://shopify/ProductVariant/')
        if vid is None:
            complete = False
            issues.append('Vínculo sem identificador de variante válido.')
            continue
        by_variant[vid].append(conn)
    for product in products:
        if not isinstance(product, dict):
            complete = False
            issues.append('Produto inválido.')
            continue
        pid = numeric_id(product.get('id'), 'gid://shopify/Product/')
        variants = product.get('variants')
        expected_variants = product.get('variant_count')
        if not pid or not isinstance(variants, list) or type(expected_variants) is not int or len(variants) != expected_variants:
            complete = False
            issues.append('Produto sem ID ou com variantes incompletas.')
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                complete = False
                issues.append('Variante inválida.')
                continue
            vid = numeric_id(variant.get('id'), 'gid://shopify/ProductVariant/')
            sku = variant.get('sku')
            matches = by_variant.get(vid, []) if vid else []
            status = 'VINCULO_NAO_LOCALIZADO'
            if not vid or not isinstance(sku, str) or not sku.strip():
                status = 'IDENTIFICACAO_INCOMPLETA'
            elif len(matches) > 1:
                status = 'MULTIPLOS_VINCULOS'
            elif matches:
                conn = matches[0]
                if conn.get('platformProductId') != pid or conn.get('platformSku') != sku or conn.get('cjSku') != sku:
                    status = 'DIVERGENCIA_DE_IDENTIDADE'
                elif not conn.get('cjVariantId') or not conn.get('cjProductId'):
                    status = 'IDENTIFICACAO_CJ_INCOMPLETA'
                else:
                    status = 'VINCULO_IDENTIFICADO'
            row = {'product_id': pid, 'variant_id': vid, 'title': product.get('title'),
                   'product_status': product.get('status'), 'sku': sku, 'link_status': status}
            rows.append(row)
            if isinstance(sku, str) and sku.strip():
                by_sku[sku].append({'product_id': pid, 'product_status': product.get('status')})
    duplicates = [{'sku': sku, 'products': entries} for sku, entries in by_sku.items() if len(entries) > 1]
    if not complete:
        # An unobserved connection is not proof of a missing link in partial snapshots.
        for row in rows:
            if row['link_status'] == 'VINCULO_NAO_LOCALIZADO':
                row['link_status'] = 'NAO_CONCLUSIVO_LEITURA_INCOMPLETA'
    return {'mode': 'READ_ONLY', 'complete': complete, 'warnings': list(dict.fromkeys(issues)),
            'product_count': len(products), 'variant_count': len(rows),
            'connections_count': len(connections), 'link_counts': dict(Counter(r['link_status'] for r in rows)),
            'duplicate_skus': duplicates, 'variants': rows,
            'note': 'Vínculo identificado não comprova sincronização, estoque, margem ou processamento de pedido.',
            'write_allowed': False}


def main():
    parser = argparse.ArgumentParser(description='Conferência local entre catálogos e vínculos; somente leitura.')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        result = reconcile(data['products'], data['connections'], shop_id=data['shop_id'],
                           expected_products=data['expected_products'], expected_connections=data['expected_connections'])
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
        print('Conferência salva em', args.output)
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print('Não foi possível criar a conferência. Confira os arquivos e preserve relatórios anteriores.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
