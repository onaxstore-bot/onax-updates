import unittest
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from analisar_variante import analyze, main
from cj_client import CJClient, CJError


class VariantAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.product.return_value = {'pid': 'p', 'variants': [
            {'pid': 'p', 'vid': 'v', 'variantSku': 'sku', 'variantSellPrice': Decimal('2.10')}]}
        self.client.freight.return_value = [{'method': 'route', 'shipping_usd': '9.50',
                                            'total_shipping_usd': '9.96', 'vid': 'v'}]
        self.client.stock.return_value = [{'countryCode': 'CN', 'areaEn': 'China Warehouse',
                                           'cjInventoryNum': 0, 'factoryInventoryNum': 40000}]
        self.assumptions = {'fixed_fees': '0', 'tax_and_fx': '0', 'returns_reserve': '0',
                            'overhead': '0', 'proportional_fees': '.03', 'ads_rate': '.05',
                            'chatgpt_reserve': '.02'}

    def run_analysis(self, **kwargs):
        args = dict(pid='p', sku='sku', origin='CN', destination='US', postal_code=None,
                    method='route', assumptions=self.assumptions)
        args.update(kwargs)
        return analyze(self.client, **args)

    def test_total_freight_including_extra_fee_is_used(self):
        result = self.run_analysis()
        self.assertEqual(result['price_floors']['0.30'], '20.10')
        self.assertFalse(result['publish_allowed'])
        self.assertIn('custos e impostos reais', result['pending'])
        self.assertEqual(result['inventory']['warehouses'][0]['cj'], 0)
        self.assertEqual(result['inventory']['warehouses'][0]['factory'], 40000)
        self.assertEqual(result['competition']['status'], 'PENDENTE')
        self.client.freight.assert_called_once_with('v', 'US', 'CN', zip_code=None)
        self.client.stock.assert_called_once_with('sku')

    def test_missing_total_or_assumption_cannot_calculate(self):
        self.client.freight.return_value[0]['total_shipping_usd'] = None
        self.assertIsNone(self.run_analysis()['price_floors'])
        self.client.freight.return_value[0]['total_shipping_usd'] = '9.96'
        self.assertIsNone(self.run_analysis(assumptions={})['price_floors'])

    def test_wrong_or_duplicate_variant_is_refused_before_freight(self):
        self.client.product.return_value['pid'] = 'other'
        with self.assertRaises(CJError):
            self.run_analysis()
        self.client.freight.assert_not_called()

    def test_missing_or_duplicated_shipping_method_blocks_calculation(self):
        self.client.freight.return_value *= 2
        self.assertIsNone(self.run_analysis()['price_floors'])

    def test_search_to_variant_report_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            search, costs, output = root / 'search.json', root / 'costs.json', root / 'output.json'
            search.write_text(json.dumps({'mode': 'CJ_RESEARCH_ONLY', 'results': [{'product': {'pid': 'p'}}]}))
            costs.write_text(json.dumps(self.assumptions))
            with patch.dict('os.environ', {'CJ_API_KEY': 'test'}), patch('analisar_variante.CJClient', return_value=self.client):
                result = main(['--pesquisa', str(search), '--produto', 'p', '--sku', 'sku',
                               '--metodo', 'route', '--custos', str(costs), '--saida', str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.read_text())['price_floors']['0.30'], '20.10')

    @patch('cj_client.time.sleep')
    def test_total_postage_is_preserved_and_errors_excluded(self, _sleep):
        def transport(method, path, params, body, headers):
            if path == 'authentication/getAccessToken':
                return {'code': 200, 'result': True, 'data': {'accessToken': 't'}}
            return {'code': 200, 'result': True, 'data': [
                {'logisticName': 'route', 'logisticPrice': '9.50', 'totalPostageFee': '9.96'},
                {'logisticName': 'bad', 'logisticPrice': '0', 'error': 'unavailable'}]}
        result = CJClient('key', transport).freight('v')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['total_shipping_usd'], '9.96')

    @patch('cj_client.time.sleep')
    def test_inconsistent_total_fails_closed(self, _sleep):
        def transport(method, path, params, body, headers):
            if path == 'authentication/getAccessToken':
                return {'code': 200, 'result': True, 'data': {'accessToken': 't'}}
            return {'code': 200, 'result': True, 'data': [
                {'logisticName': 'route', 'logisticPrice': '9.50', 'totalPostageFee': '9.00'}]}
        with self.assertRaises(CJError):
            CJClient('key', transport).freight('v')


if __name__ == '__main__':
    unittest.main()
