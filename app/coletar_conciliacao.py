"""Read-only collection of Shopify catalog and CJ connections for reconciliation."""
import argparse
import getpass
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from cj_client import CJClient, CJError, NoRedirect
from consultar_cj import read_key
from reconciliar_cj_shopify import reconcile

PRODUCTS = '''query Products($first: Int!, $after: String) { shop { myshopifyDomain } products(first: $first, after: $after) { nodes { id title status variantsCount { count } } pageInfo { hasNextPage endCursor } } }'''
VARIANTS = '''query Variants($first: Int!, $after: String) { productVariants(first: $first, after: $after) { nodes { id sku product { id } } pageInfo { hasNextPage endCursor } } }'''


class CollectionError(ValueError):
    pass


class ShopifyReader:
    def __init__(self, domain, token, version='2026-10', transport=None):
        if not isinstance(domain, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com', domain):
            raise CollectionError('Domínio da loja inválido.')
        if not isinstance(version, str) or not re.fullmatch(r'20\d\d-(01|04|07|10)', version):
            raise CollectionError('Versão da API inválida.')
        if not isinstance(token, str) or not token or any(c.isspace() or ord(c) < 32 for c in token):
            raise CollectionError('Credencial da Shopify inválida.')
        self.domain, self.version, self._token = domain, version, token
        self._transport = transport or self._http

    def _http(self, query, variables):
        url = 'https://%s/admin/api/%s/graphql.json' % (self.domain, self.version)
        request = Request(url, data=json.dumps({'query': query, 'variables': variables}).encode(),
                          headers={'Content-Type': 'application/json', 'X-Shopify-Access-Token': self._token}, method='POST')
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise CollectionError('Resposta Shopify excedeu o limite.')
            result = json.loads(raw)
        except (HTTPError, URLError, OSError, ValueError):
            raise CollectionError('Consulta Shopify falhou. Verifique acesso e conexão.') from None
        if not isinstance(result, dict) or result.get('errors') or not isinstance(result.get('data'), dict):
            raise CollectionError('Shopify retornou erro ou dados incompletos.')
        return result['data']

    def pages(self, query, key, *, require_shop=False):
        cursor, seen_cursors, seen_ids, rows = None, set(), set(), []
        for _ in range(250):
            data = self._transport(query, {'first': 50, 'after': cursor})
            if not isinstance(data, dict):
                raise CollectionError('Resposta Shopify inválida.')
            if require_shop and (data.get('shop') or {}).get('myshopifyDomain') != self.domain:
                raise CollectionError('A loja consultada não corresponde ao domínio configurado.')
            block = data.get(key)
            if not isinstance(block, dict) or not isinstance(block.get('nodes'), list) or not isinstance(block.get('pageInfo'), dict):
                raise CollectionError('Página Shopify incompleta.')
            info = block['pageInfo']
            if type(info.get('hasNextPage')) is not bool:
                raise CollectionError('Paginação Shopify incompleta.')
            if info['hasNextPage'] and not block['nodes']:
                raise CollectionError('Página Shopify vazia antes do fim da lista.')
            for row in block['nodes']:
                if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in seen_ids:
                    raise CollectionError('Identificador duplicado ou inválido na Shopify.')
                seen_ids.add(row['id'])
                rows.append(row)
            if not info['hasNextPage']:
                return rows
            cursor = info.get('endCursor')
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise CollectionError('Cursor Shopify ausente ou repetido.')
            seen_cursors.add(cursor)
        raise CollectionError('Limite de páginas Shopify atingido; leitura incompleta.')


def collect(shopify, cj, shop_id):
    products = shopify.pages(PRODUCTS, 'products', require_shop=True)
    variants = shopify.pages(VARIANTS, 'productVariants')
    indexed = {}
    for product in products:
        count = (product.get('variantsCount') or {}).get('count')
        if type(count) is not int or count < 0:
            raise CollectionError('Contagem de variantes não confirmada.')
        indexed[product['id']] = {'id': product['id'], 'title': product.get('title'),
                                  'status': product.get('status'), 'variant_count': count, 'variants': []}
    for variant in variants:
        parent = (variant.get('product') or {}).get('id')
        if parent not in indexed:
            raise CollectionError('Variante sem produto no instantâneo; repetir leitura.')
        indexed[parent]['variants'].append({'id': variant['id'], 'sku': variant.get('sku')})
    if any(len(p['variants']) != p['variant_count'] for p in indexed.values()):
        raise CollectionError('Catálogo mudou ou variantes incompletas; repetir leitura.')
    connections, expected, seen_connections = [], None, set()
    for page in range(1, 251):
        data = cj.connections(shop_id, page=page, size=100)
        if not isinstance(data, dict) or type(data.get('total')) is not int or data['total'] < 0 or not isinstance(data.get('list'), list):
            raise CollectionError('Página de vínculos CJ inválida.')
        if expected is None:
            expected = data['total']
        if data['total'] != expected or len(connections) + len(data['list']) > expected:
            raise CollectionError('A lista de vínculos CJ mudou durante a leitura.')
        if data['total'] and not data['list']:
            raise CollectionError('Página CJ vazia antes do fim da lista.')
        for connection in data['list']:
            if not isinstance(connection, dict):
                raise CollectionError('Vínculo CJ inválido.')
            identity = (connection.get('shopId'), connection.get('platformProductId'),
                        connection.get('platformVariantId'), connection.get('cjVariantId'))
            if not all(isinstance(value, str) and value for value in identity) or identity in seen_connections:
                raise CollectionError('Vínculo CJ duplicado ou sem identificação.')
            seen_connections.add(identity)
        connections.extend(data['list'])
        if len(connections) == expected:
            break
    else:
        raise CollectionError('Limite de páginas CJ atingido; leitura incompleta.')
    report = reconcile(list(indexed.values()), connections, shop_id=shop_id,
                       expected_products=len(products), expected_connections=expected)
    if not report['complete']:
        raise CollectionError('Dados de vínculo ou catálogo incompletos.')
    report['observed_at'] = datetime.now(timezone.utc).isoformat()
    report['shop_domain'] = shopify.domain
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Coletar e conciliar Shopify e CJ, sem alterar dados.')
    parser.add_argument('--dominio', default='example.myshopify.com')
    parser.add_argument('--loja-cj', required=True)
    parser.add_argument('--saida', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.saida.exists():
            raise CollectionError('Arquivo de saída já existe.')
        token = os.environ.get('SHOPIFY_ADMIN_TOKEN') or getpass.getpass('Token Shopify (entrada oculta): ')
        key = os.environ.get('CJ_API_KEY') or read_key()
        report = collect(ShopifyReader(args.dominio, token), CJClient(key), args.loja_cj)
        with args.saida.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print('Relatório criado em %s. Nenhuma alteração realizada.' % args.saida)
        return 0
    except (CollectionError, CJError, OSError, EOFError):
        print('Coleta não concluída. Confirme acesso, permissões e disponibilidade das APIs.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
