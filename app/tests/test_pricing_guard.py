import unittest
from decimal import Decimal
from core import Costs, Blocked
from pricing_guard import evaluate

class PricingGuardTests(unittest.TestCase):
    def setUp(self):
        self.costs = Costs(product='10', freight='5', fixed_fees='1', tax_and_fx='2',
                           returns_reserve='1', overhead='1', proportional_fees='.03', ads_rate='.05')
    def test_blocks_unverified(self):
        self.assertEqual(evaluate(self.costs, '50')['status'], 'BLOCKED')
    def test_rejects_uncompetitive(self):
        self.assertEqual(evaluate(self.costs, '25', comparison_verified=True, costs_verified=True)['status'], 'UNCOMPETITIVE')
    def test_margin_and_manual_review(self):
        result = evaluate(self.costs, '60', comparison_verified=True, costs_verified=True)
        self.assertEqual(result['status'], 'REVIEW')
        self.assertGreaterEqual(Decimal(result['net_margin']), Decimal('.30'))
        self.assertFalse(result['publish_allowed'])
    def test_missing_cost_blocks(self):
        with self.assertRaises(Blocked):
            evaluate(Costs(**{**self.costs.__dict__, 'freight': None}), '60', comparison_verified=True, costs_verified=True)
    def test_invalid_competitor_blocks(self):
        with self.assertRaises(Blocked):
            evaluate(self.costs, '0', comparison_verified=True, costs_verified=True)
