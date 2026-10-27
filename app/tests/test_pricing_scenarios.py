import unittest
from decimal import Decimal
from core import Costs, Blocked, profitability
from pricing_scenarios import price_for_revenue_margin, compare_bases


class MarginTests(unittest.TestCase):
    def costs(self, **changes):
        values = dict(product='10', freight='5', fixed_fees='1', tax_and_fx='2',
                      returns_reserve='1', overhead='1', proportional_fees='.03', ads_rate='.05')
        values.update(changes)
        return Costs(**values)

    def test_revenue_margin_after_ads_and_reserve(self):
        for target in ('.30', '.40', '.50'):
            costs = self.costs()
            price = price_for_revenue_margin(costs, target)
            self.assertGreaterEqual(profitability(costs, price)['revenue_margin'], Decimal(target))
            self.assertLess(profitability(costs, price - Decimal('.01'))['revenue_margin'], Decimal(target))

    def test_different_bases_are_not_interchangeable(self):
        rows = compare_bases(self.costs(), '.30')
        self.assertGreater(Decimal(rows[1]['price']), Decimal(rows[0]['price']))
        self.assertLess(Decimal(rows[0]['revenue_margin']), Decimal('.30'))
        self.assertTrue(all(x['can_publish'] is False for x in rows))

    def test_missing_cost_and_infeasible_margin_block(self):
        with self.assertRaises(Blocked):
            price_for_revenue_margin(self.costs(tax_and_fx=None), '.30')
        with self.assertRaises(Blocked):
            price_for_revenue_margin(self.costs(proportional_fees='.50'), '.50')

    def test_out_of_range_target_blocks(self):
        for value in ('.29', '.51', 'NaN', None):
            with self.assertRaises(Blocked):
                price_for_revenue_margin(self.costs(), value)
