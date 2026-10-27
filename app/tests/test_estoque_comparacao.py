import unittest
from datetime import datetime, timezone
from estoque_comparacao import compare_inventory


class InventoryComparisonTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        self.shop = [{'sku': 'A', 'location_name': 'cjdropshipping', 'available': 15, 'committed': 0}]
        self.cj = [{'countryCode': 'US', 'cjInventoryNum': 15, 'factoryInventoryNum': 100}]

    def check(self, **changes):
        args = dict(sku='A', country='US', shop_levels=self.shop, cj_rows=self.cj,
                    observed_at='2026-10-27T11:55:00Z', now=self.now)
        return compare_inventory(**(args | changes))

    def test_matching_sku_warehouse_and_origin(self):
        self.assertEqual(self.check()['status'], 'COINCIDE')
        self.assertFalse(self.check()['write_allowed'])

    def test_detects_difference_but_does_not_auto_correct(self):
        self.cj[0]['cjInventoryNum'] = 10
        self.assertEqual(self.check()['status'], 'DIFERENTE')
        self.assertFalse(self.check()['write_allowed'])

    def test_wrong_sku_or_ambiguous_location_is_inconclusive(self):
        self.assertEqual(self.check(sku='B')['status'], 'NAO_CONCLUSIVO')
        self.shop.append(dict(self.shop[0]))
        self.assertEqual(self.check()['status'], 'NAO_CONCLUSIVO')

    def test_committed_stock_and_stale_data_are_inconclusive(self):
        self.shop[0]['committed'] = 1
        self.assertEqual(self.check()['status'], 'NAO_CONCLUSIVO')
        self.shop[0]['committed'] = 0
        self.assertEqual(self.check(observed_at='2026-10-25T11:55:00Z')['status'], 'NAO_CONCLUSIVO')


if __name__ == '__main__':
    unittest.main()
