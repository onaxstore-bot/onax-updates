import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from monitor_conciliacao import MonitorError, main, run_lock, run_once, summarize, previous_inventory_cursor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.report = {'complete': True, 'variant_count': 2, 'variants': [
            {'product_status': 'ACTIVE', 'link_status': 'VINCULO_IDENTIFICADO', 'variant_id': '123'},
            {'product_status': 'DRAFT', 'link_status': 'VINCULO_NAO_LOCALIZADO'}],
            'duplicate_skus': [{'sku': 'A'}]}

    def test_success_writes_report_and_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            status = run_once(directory, lambda: self.report)
            self.assertEqual(status['state'], 'CONCLUIDO_COM_ALERTAS')
            self.assertEqual({a['code'] for a in status['alerts']}, {'VINCULO_INATIVO_PENDENTE', 'SKUS_REPETIDOS'})
            self.assertTrue((Path(directory) / status['report_file']).is_file())

    def test_failed_collection_keeps_previous_success_and_redacts_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            before = run_once(directory, lambda: self.report)
            def failure():
                raise ValueError('private-token')
            failed = run_once(directory, failure)
            self.assertEqual(failed['state'], 'FALHOU')
            self.assertEqual(json.loads((Path(directory) / 'ultimo_sucesso.json').read_text())['run_id'], before['run_id'])
            self.assertNotIn('private-token', (Path(directory) / 'status.json').read_text())

    def test_inventory_cursor_advances_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            self.report['inventory_scan'] = {'active_variants': 1, 'next_after': '123', 'results': [{'status': 'COINCIDE', 'variant_id': '123'}]}
            run_once(directory, lambda: self.report)
            self.assertEqual(previous_inventory_cursor(directory), '123')
            run_once(directory, lambda: {'complete': False})
            self.assertEqual(previous_inventory_cursor(directory), '123')

    def test_two_runs_have_distinct_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            a = run_once(directory, lambda: self.report)
            b = run_once(directory, lambda: self.report)
            self.assertNotEqual(a['report_file'], b['report_file'])
            self.assertEqual(len(list((Path(directory) / 'execucoes').glob('*.json'))), 2)

    def test_invalid_incomplete_report_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_once(directory, lambda: {'complete': False})
            self.assertEqual(result['state'], 'FALHOU')
            self.assertFalse((Path(directory) / 'ultimo_sucesso.json').exists())

    def test_mismatched_variant_count_is_failure(self):
        self.report['variant_count'] = 3
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(run_once(directory, lambda: self.report)['state'], 'FALHOU')

    def test_missing_credentials_fail_without_interactive_prompt(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ', {'SHOPIFY_ADMIN_TOKEN': '', 'CJ_API_KEY': ''}):
            result = main(['--dados', directory, '--loja-cj', '12'])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads((Path(directory) / 'status.json').read_text())['state'], 'FALHOU')

    def test_active_missing_link_is_distinct_alert(self):
        self.report['variants'][0]['link_status'] = 'VINCULO_NAO_LOCALIZADO'
        self.assertIn('VINCULO_ATIVO_PENDENTE', {x['code'] for x in summarize(self.report)})

    def test_lock_prevents_simultaneous_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with run_lock(Path(directory)):
                with self.assertRaises(MonitorError):
                    run_once(directory, lambda: self.report)


if __name__ == '__main__':
    unittest.main()
