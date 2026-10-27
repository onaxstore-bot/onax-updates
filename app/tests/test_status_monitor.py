import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from status_monitor import inspect
from monitor_conciliacao import run_once


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, payload):
        (self.root / name).write_text(json.dumps(payload), encoding='utf-8')

    def check(self):
        return inspect(self.root, now=self.now)

    def test_no_execution_and_corrupt_status(self):
        self.assertEqual(self.check()['current'], 'SEM_EXECUCAO')
        (self.root / 'status.json').write_text('{', encoding='utf-8')
        self.assertEqual(self.check()['current'], 'STATUS_INVALIDO')

    def test_success_old_is_overdue_without_claiming_a_schedule_exists(self):
        old = {'state': 'CONCLUIDO', 'finished_at': '2026-10-26T08:00:00Z'}
        self.write('status.json', old)
        self.write('ultimo_sucesso.json', old)
        result = self.check()
        self.assertEqual(result['current'], 'CONCLUIDO')
        self.assertTrue(result['overdue'])
        self.assertIn('não comprova execução agendada', result['note'])

    def test_failure_keeps_last_success(self):
        self.write('status.json', {'state': 'FALHOU', 'finished_at': '2026-10-27T11:50:00Z'})
        self.write('ultimo_sucesso.json', {'state': 'CONCLUIDO', 'finished_at': '2026-10-27T10:00:00Z'})
        self.assertEqual(self.check()['current'], 'FALHOU')
        self.assertFalse(self.check()['overdue'])

    def test_old_running_is_possible_not_confirmed_interruption(self):
        self.write('status.json', {'state': 'EM_ANDAMENTO', 'started_at': '2026-10-27T11:00:00Z'})
        self.assertEqual(self.check()['current'], 'POSSIVEL_INTERRUPCAO')
        self.write('status.json', {'state': 'EM_ANDAMENTO', 'started_at': '2026-10-27T11:50:00Z'})
        self.assertEqual(self.check()['current'], 'EM_ANDAMENTO')

    def test_future_or_unzoned_timestamp_invalid(self):
        for timestamp in ('2026-10-27T13:00:00Z', '2026-10-27T11:00:00'):
            self.write('status.json', {'state': 'CONCLUIDO', 'finished_at': timestamp})
            self.assertEqual(self.check()['current'], 'STATUS_INVALIDO')

    def test_stock_alert_remains_visible(self):
        self.write('status.json', {'state': 'CONCLUIDO_COM_ALERTAS', 'finished_at': '2026-10-27T11:50:00Z',
                                   'alerts': [{'code': 'ESTOQUE_DIVERGENTE', 'count': 2}]})
        self.assertEqual(self.check()['alerts'], [{'code': 'ESTOQUE_DIVERGENTE', 'count': 2}])

    def test_last_success_still_shown_when_status_corrupt(self):
        (self.root / 'status.json').write_text('{', encoding='utf-8')
        self.write('ultimo_sucesso.json', {'state': 'CONCLUIDO', 'finished_at': '2026-10-27T10:00:00Z'})
        result = self.check()
        self.assertEqual(result['current'], 'STATUS_INVALIDO')
        self.assertEqual(result['last_success_state'], 'CONCLUIDO')

    def test_missing_or_invalid_report_does_not_count_as_available(self):
        status = {'state': 'CONCLUIDO', 'finished_at': '2026-10-27T10:00:00Z',
                  'report_file': 'execucoes/run-123.json'}
        self.write('status.json', status)
        self.write('ultimo_sucesso.json', status)
        self.assertFalse(self.check()['last_report_available'])
        (self.root / 'execucoes').mkdir()
        self.write('execucoes/run-123.json', {'complete': True})
        self.assertTrue(self.check()['last_report_available'])
        status['report_file'] = '../outside.json'
        self.write('ultimo_sucesso.json', status)
        self.assertFalse(self.check()['last_report_available'])

    def test_real_monitor_result_can_be_read(self):
        report = {'complete': True, 'variant_count': 1, 'variants': [
            {'product_status': 'ACTIVE', 'link_status': 'VINCULO_IDENTIFICADO'}], 'duplicate_skus': []}
        run_once(self.root, lambda: report)
        result = inspect(self.root, now=datetime.now(timezone.utc))
        self.assertEqual(result['current'], 'CONCLUIDO')
        self.assertFalse(result['overdue'])
        self.assertTrue(result['last_report_available'])


if __name__ == '__main__':
    unittest.main()
