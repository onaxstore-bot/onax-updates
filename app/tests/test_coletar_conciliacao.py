import unittest
from unittest.mock import MagicMock
from coletar_conciliacao import ShopifyReader, CollectionError, collect, PRODUCTS, VARIANTS
from cj_client import CJClient, CJError


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.domain = 'test.myshopify.com'
        self.calls = []
        def transport(query, variables):
            self.calls.append((query, variables))
            if query == PRODUCTS:
                return {'shop': {'myshopifyDomain': self.domain}, 'products': {
                    'nodes': [{'id': 'gid://shopify/Product/1', 'title': 'Test', 'status': 'ACTIVE',
                               'variantsCount': {'count': 2}}],
                    'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
            if variables['after'] is None:
                return {'productVariants': {'nodes': [{'id': 'gid://shopify/ProductVariant/2', 'sku': 'A',
                         'product': {'id': 'gid://shopify/Product/1'}}],
                         'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}}}
            return {'productVariants': {'nodes': [{'id': 'gid://shopify/ProductVariant/3', 'sku': 'B',
                     'product': {'id': 'gid://shopify/Product/1'}}],
                     'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        self.reader = ShopifyReader(self.domain, 'token', transport=transport)
        self.cj = MagicMock()
        self.cj.connections.return_value = {'total': 1, 'list': [{'shopId': '12', 'platformProductId': '1',
            'platformVariantId': '2', 'platformSku': 'A', 'cjSku': 'A', 'cjVariantId': 'v', 'cjProductId': 'p'}]}

    def test_paginated_data_produces_complete_reconciliation(self):
        result = collect(self.reader, self.cj, '12')
        self.assertTrue(result['complete'])
        self.assertEqual(result['variant_count'], 2)
        self.assertEqual(result['link_counts']['VINCULO_NAO_LOCALIZADO'], 1)
        self.assertFalse(result['write_allowed'])

    def test_changed_catalog_fails_without_a_report(self):
        original = self.reader._transport
        def bad(query, variables):
            result = original(query, variables)
            if query == PRODUCTS:
                result['products']['nodes'][0]['variantsCount']['count'] = 3
            return result
        self.reader._transport = bad
        with self.assertRaises(CollectionError):
            collect(self.reader, self.cj, '12')

    def test_incomplete_cj_pages_are_not_misread_as_no_links(self):
        self.cj.connections.return_value = {'total': 2, 'list': []}
        with self.assertRaises(CollectionError):
            collect(self.reader, self.cj, '12')

    def test_duplicate_cj_page_is_not_considered_complete(self):
        connection = self.cj.connections.return_value['list'][0]
        self.cj.connections.return_value = {'total': 2, 'list': [connection, connection]}
        with self.assertRaises(CollectionError):
            collect(self.reader, self.cj, '12')

    def test_wrong_shop_is_refused(self):
        self.reader.domain = 'other.myshopify.com'
        with self.assertRaises(CollectionError):
            collect(self.reader, self.cj, '12')

    def test_empty_intermediate_shopify_page_is_rejected(self):
        self.reader._transport = lambda query, variables: {'products': {'nodes': [],
            'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}}}
        with self.assertRaises(CollectionError):
            self.reader.pages(PRODUCTS, 'products')

    def test_cj_connection_endpoint_cannot_be_used_for_delete(self):
        client = CJClient('key', lambda *args: self.fail('write attempted'))
        with self.assertRaises(CJError):
            client._call('DELETE', 'product/conn/connection')

    def test_shopify_domain_and_token_checked(self):
        for domain, token in [('attacker.example', 'token'), ('test.myshopify.com', 'bad\ntoken')]:
            with self.assertRaises(CollectionError):
                ShopifyReader(domain, token)


if __name__ == '__main__':
    unittest.main()
