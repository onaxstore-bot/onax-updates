import unittest
from datetime import datetime, timezone
from mineracao import assess, cost_ceiling
from core import Blocked


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 15, 30, tzinfo=timezone.utc)
        self.offer = {'id': 'test', 'observed_at': '2026-10-07T15:00:00Z',
                      'minimum_order': 1, 'cost_currency': 'USD', 'sale_currency': 'USD'}

    def test_unknown_costs_never_generate_prices(self):
        result = assess(self.offer, now=self.now)
        self.assertIsNone(result['price_floors'])
        self.assertFalse(result['purchase_allowed'])

    def test_moq_requires_inventory_rejected(self):
        self.offer['minimum_order'] = 300
        self.assertEqual(assess(self.offer, now=self.now)['status'], 'DESCARTAR_OFERTA')

    def test_factory_stock_does_not_pass_ready_stock(self):
        self.offer.update(factory_stock=12829, cj_stock=0)
        self.assertIn('ready_stock_verified', assess(self.offer, now=self.now)['reasons'])

    def test_currency_conversion_required(self):
        self.offer['sale_currency'] = 'BRL'
        self.assertIn('moedas_nao_conciliadas', assess(self.offer, now=self.now)['reasons'])

    def test_old_or_future_evidence_blocks(self):
        for date in ('2026-10-01T00:00:00Z', '2026-10-08T00:00:00Z'):
            self.offer['observed_at'] = date
            self.assertIn('evidencia_antiga_ou_data_invalida', assess(self.offer, now=self.now)['reasons'])

    def test_contradictory_moq_blocks(self):
        self.offer['moq_conflict'] = True
        self.assertIn('quantidade_minima_contraditoria', assess(self.offer, now=self.now)['reasons'])

    def test_ceiling_rounds_down(self):
        self.assertEqual(str(cost_ceiling('3.99', '.30', '0')), '2.51')
        self.assertEqual(str(cost_ceiling('3.99', '.50', '0')), '1.71')
        with self.assertRaises(Blocked):
            cost_ceiling('3.99', '.30', None)

    def test_competitive_price_and_complete_evidence(self):
        for flag in ('variant_verified', 'pack_verified', 'price_revalidated',
                     'direct_fulfillment_verified', 'route_verified',
                     'ready_stock_verified', 'demand_verified', 'costs_verified', 'comparison_verified'):
            self.offer[flag] = True
        self.offer['costs'] = dict(product='3', freight='5', fixed_fees='1', tax_and_fx='1',
                                   returns_reserve='1', overhead='1', proportional_fees='.03', ads_rate='.05')
        self.offer['competitive_sale_price'] = '10'
        result = assess(self.offer, now=self.now)
        self.assertEqual(result['status'], 'DESCARTAR_OFERTA')
        self.offer['competitive_sale_price'] = '30'
        result = assess(self.offer, now=self.now)
        self.assertEqual(result['status'], 'PRONTO_PARA_REVISAO')
        self.assertFalse(result['publish_allowed'])


if __name__ == '__main__':
    unittest.main()
