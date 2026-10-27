import json
import unittest
from unittest.mock import MagicMock
from cj_client import CJClient, CJError
from coletar_conciliacao import CollectionError
from monitor_conciliacao import summarize
from pedidos_monitor import scan


class OrderMonitorTests(unittest.TestCase):
    def setUp(self):
        self.shop = MagicMock()
        self.order = {'id': 'gid://shopify/Order/1', 'name': '#9001', 'createdAt': '2026-10-22T22:24:36Z',
                      'displayFinancialStatus': 'PAID', 'displayFulfillmentStatus': 'ON_HOLD',
                      'tags': ['NAO-ENVIAR', 'ONAX-TESTE'], 'test': True}
        self.shop._transport.return_value = {'orders': {'nodes': [self.order],
                                                       'pageInfo': {'hasNextPage': False, 'endCursor': None}}}
        self.cj = MagicMock()
        self.cj.orders.return_value = {'total': 0, 'list': []}

    def test_test_order_never_generates_hold_or_missing_alert(self):
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['orders'][0]['status'], 'TESTE_OU_PROTEGIDO')
        self.assertFalse(result['write_allowed'])

    def test_paid_hold_order_is_alerted_without_actions(self):
        self.order.update(test=False, tags=[])
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['orders'][0]['status'], 'EM_ESPERA')
        report = {'complete': True, 'variant_count': 0, 'variants': [], 'duplicate_skus': [], 'orders_scan': result}
        self.assertIn('PEDIDO_EM_ESPERA', [a['code'] for a in summarize(report)])

    def test_failed_cj_read_is_explicitly_partial(self):
        self.cj.orders.side_effect = CJError('sensitive')
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'PARCIAL')
        self.assertEqual(len(result['coverage']['cj']['failed_statuses']), 8)
        self.assertNotIn('sensitive', json.dumps(result))

    def test_null_cj_filter_is_not_assumed_empty(self):
        self.cj.orders.side_effect = lambda status, page, size: None if status == 'OTHER' else {'total': 0, 'list': []}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'PARCIAL')
        self.assertEqual(result['coverage']['cj']['failed_statuses'], ['OTHER'])

    def test_partial_cj_coverage_never_confirms_a_missing_match(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        self.cj.orders.side_effect = lambda status, page, size: None if status == 'OTHER' else {'total': 0, 'list': []}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['orders'][0]['status'], 'DADOS_INCOMPLETOS')

    def test_missing_shopify_permission_marks_inconclusive(self):
        self.shop._transport.side_effect = CollectionError('no access')
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'NAO_CONCLUSIVO')
        self.cj.orders.assert_not_called()

    def test_empty_intermediate_shopify_order_page_is_inconclusive(self):
        self.shop._transport.return_value = {'orders': {'nodes': [],
            'pageInfo': {'hasNextPage': True, 'endCursor': 'next'}}}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'NAO_CONCLUSIVO')
        self.cj.orders.assert_not_called()

    def test_foreign_shop_and_addresses_do_not_enter_report(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        self.cj.orders.side_effect = lambda status, page, size: {'total': 1, 'list': [
            {'shopId': 'other', 'orderId': 'x', 'orderNum': '#9001', 'orderStatus': 'UNPAID',
             'shippingAddress': 'private address'}]}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['orders'][0]['status'], 'SEM_CORRESPONDENCIA_OBSERVADA')
        self.assertNotIn('private address', json.dumps(result))

    def test_paid_shopify_order_with_unpaid_cj_order_is_flagged(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        self.cj.orders.side_effect = lambda status, page, size: {'total': 1, 'list': [
            {'shopId': 'store', 'orderId': 'cj1', 'orderNum': '#9001', 'orderStatus': 'UNPAID'}]}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['orders'][0]['status'], 'PAGAMENTO_CJ_PENDENTE')
        self.assertEqual(result['orders'][0]['cj_observed_statuses'], ['UNPAID'])
        self.assertFalse(result['write_allowed'])

    def test_cancelled_cj_order_is_flagged(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        self.cj.orders.return_value = {'total': 1, 'list': [
            {'shopId': 'store', 'orderId': 'cj1', 'orderNum': '#9001', 'orderStatus': 'CANCELLED'}]}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['orders'][0]['status'], 'PEDIDO_CJ_CANCELADO')
        report = {'complete': True, 'variant_count': 0, 'variants': [], 'duplicate_skus': [], 'orders_scan': result}
        self.assertIn('PEDIDO_CJ_CANCELADO', [a['code'] for a in summarize(report)])

    def test_multiple_cj_matches_are_inconclusive(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        self.cj.orders.return_value = {'total': 2, 'list': [
            {'shopId': 'store', 'orderId': 'cj1', 'orderNum': '#9001', 'orderStatus': 'UNPAID'},
            {'shopId': 'store', 'orderId': 'cj2', 'orderNum': '#9001', 'orderStatus': 'UNPAID'}]}
        self.assertEqual(scan(self.shop, self.cj, 'store')['orders'][0]['status'], 'DADOS_INCOMPLETOS')

    def test_conflicting_cj_observations_make_coverage_partial(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        self.cj.orders.side_effect = lambda status, page, size: {'total': 1, 'list': [
            {'shopId': 'store', 'orderId': 'cj1', 'orderNum': '#9001', 'orderStatus': status}]}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'PARCIAL')
        self.assertIn('UNPAID', result['coverage']['cj']['failed_statuses'])
        self.assertEqual(result['orders'][0]['status'], 'DADOS_INCOMPLETOS')

    def test_duplicate_order_in_same_filter_makes_coverage_partial(self):
        self.order.update(test=False, tags=[], displayFulfillmentStatus='UNFULFILLED')
        row = {'shopId': 'store', 'orderId': 'cj1', 'orderNum': '#9001', 'orderStatus': 'UNPAID'}
        self.cj.orders.side_effect = lambda status, page, size: (
            {'total': 2, 'list': [row]} if status == 'UNPAID' else {'total': 0, 'list': []})
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'PARCIAL')
        self.assertIn('UNPAID', result['coverage']['cj']['failed_statuses'])
        self.assertEqual(result['orders'][0]['status'], 'DADOS_INCOMPLETOS')

    def test_empty_cj_identity_does_not_confirm_coverage(self):
        self.cj.orders.return_value = {'total': 1, 'list': [
            {'shopId': 'store', 'orderId': '', 'orderNum': '#9001', 'orderStatus': 'UNPAID'}]}
        result = scan(self.shop, self.cj, 'store')
        self.assertEqual(result['status'], 'PARCIAL')

    def test_cj_order_endpoint_cannot_be_used_to_write(self):
        client = CJClient('key', lambda *args: self.fail('network call'))
        with self.assertRaises(CJError):
            client._call('POST', 'shopping/order/list')


if __name__ == '__main__':
    unittest.main()
