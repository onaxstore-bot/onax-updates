import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from agendar_windows import NS, build_xml
from job_monitor import run
from monitor_conciliacao import run_once


class ScheduleTests(unittest.TestCase):
    def xml(self, **overrides):
        args = dict(sid='S-1-5-21-100', executable=r'C:\Python\pythonw.exe',
                    job=r'C:\App & Co\job_monitor.py', directory=r'C:\ONAX\data',
                    vault=r'C:\ONAX\vault.bin', cj_shop='123', domain='abc.myshopify.com')
        return build_xml(**(args | overrides))

    def test_xml_contains_daily_and_logon_without_credentials(self):
        data = self.xml()
        root = ET.fromstring(data)
        ns = {'t': NS}
        self.assertIsNotNone(root.find('t:Triggers/t:CalendarTrigger/t:ScheduleByDay', ns))
        self.assertIsNotNone(root.find('t:Triggers/t:LogonTrigger', ns))
        self.assertEqual(root.findtext('t:Principals/t:Principal/t:LogonType', namespaces=ns), 'InteractiveToken')
        self.assertIn('App & Co', root.findtext('t:Actions/t:Exec/t:Arguments', namespaces=ns))
        self.assertNotIn('SHOPIFY_ADMIN_TOKEN', data.decode('utf-16'))

    def test_invalid_inputs_rejected(self):
        for value in ({'sid': 'invalid'}, {'cj_shop': 'abc'}, {'domain': 'evil.com'}, {'vault': 'bad"name'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.xml(**value)

    def test_recent_success_avoids_duplicate_run(self):
        with tempfile.TemporaryDirectory() as directory:
            report = {'complete': True, 'variant_count': 0, 'variants': [], 'duplicate_skus': []}
            run_once(directory, lambda: report)
            with patch('job_monitor.monitor_main') as invoke:
                self.assertEqual(run(['--dados', directory, '--cofre', 'missing', '--loja-cj', '12']), 0)
                invoke.assert_not_called()

    def test_missing_credentials_causes_failure_and_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            seen = []
            status = run(['--dados', directory, '--cofre', str(Path(directory) / 'missing'), '--loja-cj', '12'], notify=seen.append)
            self.assertEqual(status, 1)
            self.assertEqual(seen, [Path(directory)])

    def test_manual_check_runs_even_after_recent_success(self):
        with tempfile.TemporaryDirectory() as directory:
            report = {'complete': True, 'variant_count': 0, 'variants': [], 'duplicate_skus': []}
            run_once(directory, lambda: report)
            with patch('job_monitor.monitor_main', return_value=0) as invoke:
                self.assertEqual(run(['--dados', directory, '--cofre', 'vault', '--loja-cj', '12', '--agora']), 0)
                invoke.assert_called_once()


if __name__ == '__main__':
    unittest.main()
