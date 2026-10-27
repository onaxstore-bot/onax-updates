import io
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout
from cj_client import CJError
import consultar_cj


class InputTests(unittest.TestCase):
    def test_windows_key_is_masked_and_window_destroyed(self):
        root = MagicMock()
        dialog = MagicMock(return_value='private-key')
        tk = SimpleNamespace(Tk=MagicMock(return_value=root), TclError=RuntimeError,
                             simpledialog=SimpleNamespace(askstring=dialog))
        with patch.object(consultar_cj.os, 'name', 'nt'), patch.dict('sys.modules', {'tkinter': tk}):
            self.assertEqual(consultar_cj.read_key(), 'private-key')
        self.assertEqual(dialog.call_args.kwargs['show'], '*')
        root.destroy.assert_called_once()

    def test_cancel_does_not_authenticate(self):
        root = MagicMock()
        tk = SimpleNamespace(Tk=MagicMock(return_value=root), TclError=RuntimeError,
                             simpledialog=SimpleNamespace(askstring=MagicMock(return_value=None)))
        with patch.object(consultar_cj.os, 'name', 'nt'), patch.dict('sys.modules', {'tkinter': tk}):
            with self.assertRaises(CJError):
                consultar_cj.read_key()
        root.destroy.assert_called_once()

    def test_auth_test_does_not_query_products_or_print_key(self):
        client = MagicMock()
        with patch.dict(consultar_cj.os.environ, {'CJ_API_KEY': 'private-key'}), \
             patch('sys.argv', ['consultar_cj.py', '--testar-acesso']), \
             patch.object(consultar_cj, 'CJClient', return_value=client), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(consultar_cj.main(), 0)
        client.authenticate.assert_called_once()
        client.product.assert_not_called()
        client.stock.assert_not_called()
        client.freight.assert_not_called()
        self.assertNotIn('private-key', output.getvalue())

    def test_malformed_variants_do_not_trigger_stock_or_freight(self):
        client = MagicMock()
        client.product.return_value = {'variants': [None]}
        with patch.dict(consultar_cj.os.environ, {'CJ_API_KEY': 'private-key'}), \
             patch('sys.argv', ['consultar_cj.py']), \
             patch.object(consultar_cj, 'CJClient', return_value=client), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(consultar_cj.main(), 1)
        client.stock.assert_not_called()
        client.freight.assert_not_called()

    def test_failed_report_replace_preserves_previous_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text('previous', encoding='utf-8')
            with patch.object(consultar_cj.os, 'replace', side_effect=OSError('failed')):
                with self.assertRaises(OSError):
                    consultar_cj.save_report(path, {'sku': 'test'})
            self.assertEqual(path.read_text(encoding='utf-8'), 'previous')
            self.assertEqual(list(path.parent.iterdir()), [path])
