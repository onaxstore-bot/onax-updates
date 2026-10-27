import unittest
from datetime import datetime, timezone
from analisar_variante import inventory_observation
from concorrencia import compare


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        self.offer = {'pid': 'p', 'sku': 's', 'country': 'US', 'currency': 'USD',
                      'equivalent_verified': True, 'shipping_included': True,
                      'url': 'https://example.com/product', 'observed_at': '2026-10-27T11:30:00Z',
                      'delivered_price': '22.00'}

    def evaluate(self, evidence):
        return compare(evidence, pid='p', sku='s', country='US', currency='USD',
                       minimum_price='20.10', now=self.now)

    def test_factory_inventory_is_not_ready_stock(self):
        result = inventory_observation([{'countryCode': 'CN', 'areaEn': 'China Warehouse',
                                          'cjInventoryNum': 0, 'factoryInventoryNum': 40000}], 'CN')
        self.assertEqual(result['warehouses'][0]['cj'], 0)
        self.assertEqual(result['warehouses'][0]['factory'], 40000)
        self.assertFalse(result['ready_stock_verified'])

    def test_wrong_origin_or_missing_numbers_remain_unknown(self):
        for rows in (None, [{'countryCode': 'US', 'cjInventoryNum': 50, 'factoryInventoryNum': 0}],
                     [{'countryCode': 'CN', 'cjInventoryNum': None, 'factoryInventoryNum': 4}]):
            self.assertEqual(inventory_observation(rows, 'CN')['status'], 'NAO_CONFIRMADO')

    def test_comparison_uses_delivered_price_and_is_never_publication_permission(self):
        result = self.evaluate([self.offer, self.offer | {'delivered_price': '19.00'}])
        self.assertEqual(result['cheapest_delivered'], '19.00')
        self.assertFalse(result['competitive_at_30_percent'])
        self.assertFalse(result['publish_allowed'])

    def test_stale_different_currency_or_unverified_is_pending(self):
        for change in ({'observed_at': '2026-10-20T12:00:00Z'}, {'currency': 'BRL'},
                       {'equivalent_verified': False}, {'shipping_included': False},
                       {'country': 'BR'}, {'delivered_price': None}, {'url': 'http://example.com'}):
            with self.subTest(change=change):
                self.assertEqual(self.evaluate([self.offer | change])['status'], 'PENDENTE')

    def test_one_invalid_offer_prevents_false_market_comparison(self):
        self.assertEqual(self.evaluate([self.offer, self.offer | {'sku': 'other'}])['status'], 'PENDENTE')


if __name__ == '__main__':
    unittest.main()
