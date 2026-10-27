import unittest
from unittest.mock import MagicMock
from cj_client import CJError
from coletar_conciliacao import CollectionError
from inventario_automatico import scan, shopify_levels
from monitor_conciliacao import summarize


class AutomaticInventoryTests(unittest.TestCase):
    def setUp(self):
        self.row = {'product_status': 'ACTIVE', 'link_status': 'VINCULO_IDENTIFICADO',
                    'sku': 'SKU', 'variant_id': '123'}
        self.report = {'complete': True, 'variants': [self.row], 'variant_count': 1, 'duplicate_skus': []}
        self.shop = MagicMock()
        self.shop._transport.return_value = {'productVariant': {'id': 'gid://shopify/ProductVariant/123', 'sku': 'SKU',
            'inventoryItem': {'inventoryLevels': {'nodes': [{'location': {'id': 'loc', 'name': 'cjdropshipping'},
                'quantities': [{'name': 'available', 'quantity': 286}, {'name': 'committed', 'quantity': 0}]}],
                'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}
        self.cj = MagicMock()
        self.cj.stock.return_value = [{'countryCode': 'US', 'cjInventoryNum': 286, 'factoryInventoryNum': 0}]

    def test_matching_live_shape_and_origin(self):
        result = scan(self.report, self.shop, self.cj)
        self.assertEqual(result['results'][0]['status'], 'COINCIDE')
        self.cj.stock.assert_called_once_with('SKU')
        self.assertFalse(result['write_allowed'])

    def test_difference_generates_monitor_alert(self):
        self.cj.stock.return_value[0]['cjInventoryNum'] = 200
        self.report['inventory_scan'] = scan(self.report, self.shop, self.cj)
        self.assertEqual(self.report['inventory_scan']['results'][0]['status'], 'DIFERENTE')
        self.assertIn('ESTOQUE_DIVERGENTE', [x['code'] for x in summarize(self.report)])

    def test_cj_failure_is_pending_and_not_zero(self):
        self.cj.stock.side_effect = CJError('unavailable')
        self.report['inventory_scan'] = scan(self.report, self.shop, self.cj)
        result = self.report['inventory_scan']['results'][0]
        self.assertEqual(result['status'], 'NAO_CONCLUSIVO')
        self.assertNotIn('cj_inventory', result)
        self.assertIn('ESTOQUE_NAO_CONFIRMADO', [x['code'] for x in summarize(self.report)])

    def test_wrong_variant_is_rejected_without_querying_cj(self):
        self.shop._transport.return_value['productVariant']['sku'] = 'other'
        self.assertEqual(scan(self.report, self.shop, self.cj)['results'][0]['status'], 'NAO_CONCLUSIVO')
        self.cj.stock.assert_not_called()

    def test_duplicate_active_sku_is_not_guessed(self):
        self.report['variants'].append(dict(self.row, variant_id='456'))
        self.assertEqual(scan(self.report, self.shop, self.cj)['counts'], {'NAO_CONCLUSIVO': 2})
        self.cj.stock.assert_not_called()

    def test_limit_does_not_silently_ignore_variant(self):
        self.report['variants'].append(dict(self.row, sku='OTHER', variant_id='456'))
        result = scan(self.report, self.shop, self.cj, limit=1)
        self.assertEqual(result['attempted'], 1)
        self.assertEqual(result['results'][1]['status'], 'NAO_CONCLUSIVO')
        self.assertIn('Limite', result['results'][1]['reason'])

    def test_limit_rotates_and_wraps_between_runs(self):
        self.report['variants'] = [dict(self.row, sku='SKU'+str(i), variant_id=str(i)) for i in range(51)]
        first = scan(self.report, self.shop, self.cj)
        second = scan(self.report, self.shop, self.cj, start_after=first['next_after'])
        first_checked = {r['variant_id'] for r in first['results'] if 'Limite' not in r.get('reason', '')}
        second_checked = {r['variant_id'] for r in second['results'] if 'Limite' not in r.get('reason', '')}
        self.assertEqual(len(first_checked), 50)
        self.assertEqual(first_checked | second_checked, {str(i) for i in range(51)})

    def test_duplicate_variant_id_is_not_queried(self):
        self.report['variants'].append(dict(self.row, sku='OTHER'))
        result = scan(self.report, self.shop, self.cj)
        self.assertEqual(result['attempted'], 0)
        self.cj.stock.assert_not_called()

    def test_missing_page_info_never_confirms_inventory(self):
        del self.shop._transport.return_value['productVariant']['inventoryItem']['inventoryLevels']['pageInfo']
        with self.assertRaises(CollectionError):
            shopify_levels(self.shop, 'gid://shopify/ProductVariant/123', 'SKU')

    def test_monitor_rejects_partial_inventory_list(self):
        self.report['inventory_scan'] = {'active_variants': 1, 'results': []}
        with self.assertRaises(ValueError):
            summarize(self.report)

    def test_monitor_rejects_wrong_inventory_variant_even_when_counts_match(self):
        self.report['inventory_scan'] = {'active_variants': 1, 'results': [{'status': 'COINCIDE', 'variant_id': '999'}]}
        with self.assertRaises(ValueError):
            summarize(self.report)

    def test_empty_stock_page_with_next_page_is_rejected(self):
        levels = self.shop._transport.return_value['productVariant']['inventoryItem']['inventoryLevels']
        levels['nodes'] = []
        levels['pageInfo'] = {'hasNextPage': True, 'endCursor': 'next'}
        with self.assertRaises(CollectionError):
            shopify_levels(self.shop, 'gid://shopify/ProductVariant/123', 'SKU')


if __name__ == '__main__':
    unittest.main()
