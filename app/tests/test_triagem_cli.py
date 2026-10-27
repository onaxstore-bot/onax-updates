import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TriageCliTests(unittest.TestCase):
    def test_invalid_entry_is_reported_without_losing_other_offers(self):
        script = Path(__file__).resolve().parents[1] / 'mineracao.py'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            output = Path(directory) / 'report.json'
            source.write_text(json.dumps({'offers': [None, {'id': 'ok'}]}), encoding='utf-8')
            result = subprocess.run([sys.executable, str(script), '--input', str(source), '--output', str(output)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = json.loads(output.read_text(encoding='utf-8'))['results']
            self.assertEqual(len(rows), 2)
            self.assertIn('identificacao_ou_registro_invalido', rows[0]['reasons'])
            self.assertEqual(rows[1]['id'], 'ok')
            again = subprocess.run([sys.executable, str(script), '--input', str(source), '--output', str(output)],
                                   capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(len(json.loads(output.read_text(encoding='utf-8'))['results']), 2)

    def test_input_cannot_be_overwritten(self):
        script = Path(__file__).resolve().parents[1] / 'mineracao.py'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            content = '{"offers": []}'
            source.write_text(content, encoding='utf-8')
            result = subprocess.run([sys.executable, str(script), '--input', str(source), '--output', str(source)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_text(encoding='utf-8'), content)
