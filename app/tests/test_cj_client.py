import unittest
from unittest.mock import patch
from cj_client import CJClient, CJError, diagnostic


class CJTests(unittest.TestCase):
    def client(self, result):
        calls = []
        def transport(method, path, params, body, headers):
            calls.append((method, path, params, body, headers))
            if path == 'authentication/getAccessToken':
                return {'code': 200, 'result': True, 'data': {'accessToken': 'test-token'}}
            return result
        return CJClient('test-key', transport), calls

    @patch('cj_client.time.sleep')
    def test_exact_variant_and_no_writes(self, sleep):
        c, calls = self.client({'code': 200, 'result': True, 'data': {}})
        c.product('Black-SKU')
        self.assertEqual(calls[1][2], {'variantSku': 'Black-SKU'})
        self.assertNotIn('test-key', str(c))
        with self.assertRaises(CJError):
            c._call('POST', 'shopping/pay/payBalance')
        self.assertEqual(len(calls), 2)

    @patch('cj_client.time.sleep')
    def test_unknown_freight_blocked(self, sleep):
        for data in [[], None, [{'logisticName': 'test'}], [{'logisticName': 'test', 'logisticPrice': 'NaN'}]]:
            c, _ = self.client({'code': 200, 'result': True, 'data': data})
            with self.assertRaises(CJError):
                c.freight('vid')

    @patch('cj_client.time.sleep')
    def test_quote_sorted_and_destination_preserved(self, sleep):
        c, calls = self.client({'code': 200, 'result': True, 'data': [
            {'logisticName': 'A', 'logisticPrice': '24.62', 'logisticAging': '4-17'},
            {'logisticName': 'B', 'logisticPrice': '9.10', 'logisticAging': '10-20'}]})
        quotes = c.freight('vid', zip_code='10001')
        self.assertEqual(quotes[0]['shipping_usd'], '9.10')
        self.assertTrue(quotes[0]['preliminary'])
        self.assertEqual(calls[-1][3]['zip'], '10001')
        self.assertEqual(calls[-1][3]['products'], [{'vid': 'vid', 'quantity': 1}])

    @patch('cj_client.time.sleep')
    def test_api_error_not_converted_to_zero(self, sleep):
        c, _ = self.client({'code': 1600100, 'result': False, 'data': None, 'message': 'secret'})
        with self.assertRaises(CJError) as cm:
            c.stock('sku')
        self.assertNotIn('secret', str(cm.exception))

    def test_bad_quantity_before_network(self):
        c, calls = self.client({})
        for qty in [True, 0, -1, 1.5]:
            with self.assertRaises(CJError):
                c.freight('vid', quantity=qty)
        self.assertEqual(calls, [])

    def test_invalid_paste_never_reaches_cj(self):
        for value in ('\x16', 'key\x03value', 'key value', 'key\nvalue'):
            calls = []
            with self.assertRaises(CJError):
                CJClient(value, lambda *args: calls.append(args))
            self.assertEqual(calls, [])

    def test_diagnostic_never_echoes_credentials_or_server_message(self):
        for code in ('secret-api-key', True, {'token': 'secret-token'}, 9999999999):
            message = diagnostic('authentication/getAccessToken',
                                 {'code': code, 'message': 'secret-api-key', 'data': {'accessToken': 'secret-token'}})
            self.assertNotIn('secret', message)
            self.assertIn('Codigo CJ: indisponivel', message)

    def test_authentication_failure_identifies_phase_without_followup(self):
        calls = []
        def transport(*args):
            calls.append(args)
            return {'code': 1600005, 'result': False, 'message': 'sensitive-key'}
        c = CJClient('sensitive-key', transport)
        with self.assertRaises(CJError) as cm:
            c.product('sku')
        self.assertIn('Etapa: autenticacao | Codigo CJ: 1600005', str(cm.exception))
        self.assertNotIn('sensitive-key', str(cm.exception))
        self.assertEqual(len(calls), 1)

    @patch('cj_client.time.sleep')
    def test_product_failure_is_distinct_from_key_failure(self, sleep):
        c, calls = self.client({'code': 1602000, 'result': False, 'message': 'secret'})
        with self.assertRaises(CJError) as cm:
            c.product('sku')
        self.assertIn('Etapa: produto | Codigo CJ: 1602000', str(cm.exception))
        self.assertEqual(len(calls), 2)
