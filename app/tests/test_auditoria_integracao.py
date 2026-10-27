import unittest
from datetime import datetime, timezone
from decimal import Decimal
from core import Blocked, Costs, profitability
from mineracao import assess
from pricing_guard import evaluate


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 15, 30, tzinfo=timezone.utc)
        self.costs = dict(product='10', freight='5', fixed_fees='1', tax_and_fx='2',
                          returns_reserve='1', overhead='1', proportional_fees='.03', ads_rate='.05')
        self.offer = dict(id='x', observed_at='2026-10-07T15:00:00Z', minimum_order=1,
                          cost_currency='USD', sale_currency='USD', costs=self.costs,
                          competitive_sale_price='60')
        for flag in ('variant_verified', 'pack_verified', 'price_revalidated',
                     'direct_fulfillment_verified', 'route_verified', 'ready_stock_verified',
                     'demand_verified', 'costs_verified', 'comparison_verified'):
            self.offer[flag] = True

    def test_invalid_or_zero_competitor_does_not_approve(self):
        for value in ('0', '-1', None, 'NaN'):
            self.offer['competitive_sale_price'] = value
            self.assertIn('comparacao_de_mercado_pendente', assess(self.offer, now=self.now)['reasons'])
            self.assertNotEqual('PRONTO_PARA_REVISAO', assess(self.offer, now=self.now)['status'])

    def test_naive_evidence_does_not_crash_or_approve(self):
        self.offer['observed_at'] = '2026-10-07T15:00:00'
        self.assertIn('data_nao_confirmada', assess(self.offer, now=self.now)['reasons'])

    def test_currency_mismatch_prevents_price_floor(self):
        self.offer['sale_currency'] = 'BRL'
        self.assertIsNone(assess(self.offer, now=self.now)['price_floors'])

    def test_truthy_non_boolean_is_not_verified(self):
        result = evaluate(Costs(**self.costs), '60', costs_verified='yes', comparison_verified=True)
        self.assertEqual('BLOCKED', result['status'])

    def test_zero_price_is_rejected(self):
        with self.assertRaises(Blocked):
            profitability(Costs(**self.costs), '0')

    def test_margin_is_on_revenue(self):
        result = assess(self.offer, now=self.now)
        price = result['price_floors']['0.30']
        self.assertGreaterEqual(profitability(Costs(**self.costs), price)['revenue_margin'], Decimal('.30'))
        self.assertFalse(result['publish_allowed'])


if __name__ == '__main__':
    unittest.main()
