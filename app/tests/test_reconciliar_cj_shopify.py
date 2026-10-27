import unittest
from reconciliar_cj_shopify import reconcile


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.products = [{'id': 'gid://shopify/Product/1', 'title': 'Item', 'status': 'ACTIVE',
                          'variant_count': 1, 'variants': [{'id': 'gid://shopify/ProductVariant/2', 'sku': 'SKU'}]}]
        self.connections = [{'shopId': 'shop', 'platformVariantId': '2', 'platformProductId': '1',
                             'platformSku': 'SKU', 'cjSku': 'SKU', 'cjVariantId': 'v', 'cjProductId': 'p'}]

    def run_report(self, **kwargs):
        return reconcile(kwargs.get('products', self.products), kwargs.get('connections', self.connections),
                         shop_id='shop', expected_products=kwargs.get('expected_products', 1),
                         expected_connections=kwargs.get('expected_connections', 1))

    def test_exact_ids_and_sku_are_required(self):
        self.assertEqual(self.run_report()['variants'][0]['link_status'], 'VINCULO_IDENTIFICADO')
        self.connections[0]['cjSku'] = 'different'
        self.assertEqual(self.run_report()['variants'][0]['link_status'], 'DIVERGENCIA_DE_IDENTIDADE')

    def test_missing_links_are_inconclusive_with_incomplete_catalog(self):
        result = self.run_report(connections=[], expected_connections=2)
        self.assertFalse(result['complete'])
        self.assertEqual(result['variants'][0]['link_status'], 'NAO_CONCLUSIVO_LEITURA_INCOMPLETA')

    def test_incomplete_variants_never_mark_catalog_complete(self):
        self.products[0]['variant_count'] = 2
        self.assertFalse(self.run_report()['complete'])

    def test_duplicate_sku_is_identified_across_status_without_modification(self):
        self.products.append({'id': 'gid://shopify/Product/3', 'title': 'Other', 'status': 'ARCHIVED',
                              'variant_count': 1, 'variants': [{'id': 'gid://shopify/ProductVariant/4', 'sku': 'SKU'}]})
        result = self.run_report(expected_products=2)
        self.assertEqual(result['duplicate_skus'][0]['sku'], 'SKU')
        self.assertFalse(result['write_allowed'])

    def test_foreign_shop_does_not_prove_missing_link(self):
        self.connections[0]['shopId'] = 'other'
        result = self.run_report()
        self.assertFalse(result['complete'])
        self.assertEqual(result['variants'][0]['link_status'], 'NAO_CONCLUSIVO_LEITURA_INCOMPLETA')


if __name__ == '__main__':
    unittest.main()
