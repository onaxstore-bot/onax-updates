"""Search CJ and create a conservative research report; no store writes or purchases."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cj_client import CJClient, CJError
from consultar_cj import read_key
from mineracao import assess


def normalize_page(data, keyword, *, now):
    if not isinstance(data, dict) or not isinstance(data.get('content'), list):
        raise CJError('Formato da busca CJ não reconhecido; nenhum resultado aprovado.')
    entries = []
    for group in data['content']:
        if not isinstance(group, dict) or not isinstance(group.get('productList'), list):
            raise CJError('Lista de produtos CJ incompleta; nenhum resultado aprovado.')
        entries.extend(group['productList'])
    results, seen = [], set()
    for product in entries:
        if not isinstance(product, dict):
            raise CJError('Produto CJ inválido; nenhum resultado aprovado.')
        pid, sku = product.get('id'), product.get('sku')
        if not isinstance(pid, str) or not pid.strip():
            raise CJError('Produto CJ sem identificação; nenhum resultado aprovado.')
        if pid in seen:
            continue
        seen.add(pid)
        offer = {'id': 'cj:' + pid, 'observed_at': now.isoformat(),
                 'minimum_order': product.get('directMinOrderNum')}
        result = assess(offer, now=now)
        # Product-level prices and inventory are indications, not verified variant costs.
        result['product'] = {'pid': pid, 'product_sku': sku if isinstance(sku, str) else None,
                             'name': product.get('nameEn'), 'price_hint_unverified': product.get('sellPrice'),
                             'currency_unverified': product.get('currency'),
                             'inventory_hint_unverified': product.get('warehouseInventoryNum'),
                             'url': product.get('productUrl')}
        results.append(result)
    return {'mode': 'CJ_RESEARCH_ONLY', 'searched_at': now.isoformat(), 'keyword': keyword,
            'page': data.get('pageNumber'), 'page_size': data.get('pageSize'),
            'total_records': data.get('totalRecords'), 'total_pages': data.get('totalPages'),
            'results': results,
            'notice': 'Preço, estoque, rota, custos e concorrência exigem confirmação por variante. Nenhuma publicação ou compra.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Buscar oportunidades na CJ; somente consulta.')
    parser.add_argument('keyword', help='Termo de busca em inglês ou SKU')
    parser.add_argument('--page', type=int, default=1)
    parser.add_argument('--size', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True, help='Novo relatório JSON; não sobrescreve arquivo existente')
    args = parser.parse_args(argv)
    # Validate locally before authentication to avoid spending a query on invalid input.
    if not args.keyword.strip() or len(args.keyword) > 200 or not 1 <= args.page <= 1000 or not 1 <= args.size <= 100:
        parser.error('Busca inválida: termo obrigatório; página 1–1000; tamanho 1–100.')
    if args.output.exists():
        parser.exit(1, 'O relatório já existe. Escolha outro nome para preservar seus dados.\n')
    try:
        client = CJClient(os.environ.get('CJ_API_KEY') or read_key())
        data = client.search(args.keyword, page=args.page, size=args.size)
        report = normalize_page(data, args.keyword.strip(), now=datetime.now(timezone.utc))
        content = json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n'
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(content)
        print('Busca concluída: %d produtos em triagem. Relatório: %s' % (len(report['results']), args.output))
        print('Nenhuma compra, publicação ou alteração na loja foi realizada.')
        return 0
    except CJError as exc:
        print(str(exc))
        return 1
    except OSError:
        print('Não foi possível salvar o relatório; verifique o caminho. Nenhuma compra foi enviada.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
