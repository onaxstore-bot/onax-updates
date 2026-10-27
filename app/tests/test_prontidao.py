import copy
import unittest
from datetime import datetime, timezone
from prontidao import assess, positive_price


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 3, 20, tzinfo=timezone.utc)
        self.snapshot = {'observed_at': '2026-10-07T03:15:00Z', 'data': {
            'shop': {'plan': {'publicDisplayName': 'Trial'}},
            'shopLocales': [{'locale': 'en', 'published': False}],
            'markets': {'nodes': [{'name': 'Estados Unidos', 'status': 'DRAFT'}], 'pageInfo': {'hasNextPage': False}},
            'deliveryProfiles': {'pageInfo': {'hasNextPage': False}},
            'products': {'nodes': [{'id': 'gid://shopify/Product/1', 'title': 'Item', 'status': 'DRAFT',
                                  'mediaCount': {'count': 0}, 'variants': {'nodes': [{'sku': None, 'price': '0.00', 'inventoryPolicy': 'DENY'}]}}],
                         'pageInfo': {'hasNextPage': False}}}}
        self.catalog = {'items': [{'shopify_product_id': '1', 'approved': False}]}

    def test_pending_product_cannot_launch_even_with_shipping_zones(self):
        result = assess(self.snapshot, self.catalog, now=self.now)
        self.assertFalse(result['can_launch'])
        reasons = result['products'][0]['blocks']
        self.assertIn('SKU ausente.', reasons)
        self.assertIn('Preço de venda ausente ou inválido.', reasons)
        self.assertIn('Estoque da variante não validado.', reasons)

    def test_nonfinite_and_inexact_prices_do_not_pass(self):
        for value in ('NaN', 'Infinity', '-1', '0', None, True, 12.0):
            self.assertFalse(positive_price(value))
        self.assertTrue(positive_price('12.30'))

    def test_old_future_and_unzoned_snapshots_are_blocked(self):
        for date in ('2026-10-05T03:15:00Z', '2026-10-08T03:15:00Z', '2026-10-07T03:15:00'):
            self.snapshot['observed_at'] = date
            self.assertTrue(any('Leitura da Shopify antiga' in x for x in assess(self.snapshot, self.catalog, now=self.now)['store_blocks']))

    def test_incomplete_snapshot_and_accidental_activation_are_reported(self):
        self.snapshot['data']['products']['pageInfo']['hasNextPage'] = True
        self.snapshot['data']['products']['nodes'][0]['status'] = 'ACTIVE'
        report = assess(self.snapshot, self.catalog, now=self.now)
        self.assertTrue(any('Leitura incompleta de products' in x for x in report['store_blocks']))
        self.assertTrue(any('fora de rascunho' in x for x in report['products'][0]['blocks']))

    def test_positive_catalog_flags_never_authorize_real_actions(self):
        candidate = self.catalog['items'][0]
        for key in ('approved', 'stock_confirmed', 'route_confirmed', 'profit_verified'):
            candidate[key] = True
        before = copy.deepcopy(self.snapshot)
        report = assess(self.snapshot, self.catalog, now=self.now)
        self.assertFalse(report['can_purchase'])
        self.assertFalse(report['products'][0]['can_publish'])
        self.assertEqual(self.snapshot, before)

    def test_incomplete_variant_pagination_is_explicit(self):
        product = self.snapshot['data']['products']['nodes'][0]
        for page in ({}, {'hasNextPage': True}):
            product['variants']['pageInfo'] = page
            blocks = assess(self.snapshot, self.catalog, now=self.now)['products'][0]['blocks']
            self.assertTrue(any('paginação' in reason for reason in blocks))
        product['variants']['pageInfo'] = {'hasNextPage': False}
        blocks = assess(self.snapshot, self.catalog, now=self.now)['products'][0]['blocks']
        self.assertFalse(any('paginação' in reason for reason in blocks))

    def test_duplicate_catalog_record_is_not_accepted(self):
        self.catalog['items'].append(dict(self.catalog['items'][0], approved=True,
                                          stock_confirmed=True, route_confirmed=True,
                                          profit_verified=True))
        blocks = assess(self.snapshot, self.catalog, now=self.now)['products'][0]['blocks']
        self.assertTrue(any('duplicada' in reason for reason in blocks))
        self.assertIn('Lucro após custos não validado.', blocks)

    def test_reference_time_requires_timezone(self):
        with self.assertRaises(ValueError):
            assess(self.snapshot, self.catalog, now=self.now.replace(tzinfo=None))
