import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from beta_setup import InstallError, install_beta


class BetaSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        (self.source / 'release_health.py').write_text('pass')
        (self.source / 'painel_beta.py').write_text('pass')
        self.root = self.base / 'ONAX-TechMiner-Beta'
        self.original = self.base / 'ONAX'
        self.original.mkdir()
        (self.original / 'important.txt').write_text('keep')

    def tearDown(self):
        self.temp.cleanup()

    def test_separate_install_preserves_original_and_creates_launcher(self):
        result = install_beta(self.source, self.root, probe=lambda app: None)
        self.assertEqual(result, self.root)
        self.assertTrue((self.root / 'app' / 'painel_beta.py').is_file())
        self.assertTrue((self.root / 'data').is_dir())
        self.assertTrue((self.root / 'Abrir-TechMiner-Beta.cmd').is_file())
        launcher = (self.root / 'Abrir-TechMiner-Beta.cmd').read_text()
        self.assertIn(str(Path(sys.executable).with_name('pythonw.exe')).replace('%', '%%'), launcher)
        self.assertEqual((self.original / 'important.txt').read_text(), 'keep')

    def test_existing_beta_is_not_overwritten(self):
        self.root.mkdir()
        (self.root / 'important.txt').write_text('keep')
        with self.assertRaises(InstallError):
            install_beta(self.source, self.root, probe=lambda app: None)
        self.assertEqual((self.root / 'important.txt').read_text(), 'keep')

    def test_failed_probe_creates_no_installation(self):
        def fail(app):
            raise InstallError('test failed')
        with self.assertRaises(InstallError):
            install_beta(self.source, self.root, probe=fail)
        self.assertFalse(self.root.exists())

    def test_missing_graphics_dependency_blocks_installation(self):
        with patch('beta_setup.subprocess.run', return_value=SimpleNamespace(returncode=1)) as run:
            with self.assertRaises(InstallError):
                install_beta(self.source, self.root)
            self.assertIn('import tkinter', run.call_args.args[0])
            self.assertFalse(self.root.exists())

    def test_destination_created_during_probe_is_not_replaced(self):
        def race(app):
            self.root.mkdir()
            (self.root / 'important.txt').write_text('keep')
        with self.assertRaises(InstallError):
            install_beta(self.source, self.root, probe=race)
        self.assertEqual((self.root / 'important.txt').read_text(), 'keep')

    def test_bad_package_and_nested_install_are_refused(self):
        (self.source / 'bad.exe').write_bytes(b'bad')
        with self.assertRaises(InstallError):
            install_beta(self.source, self.root, probe=lambda app: None)
        (self.source / 'bad.exe').unlink()
        with self.assertRaises(InstallError):
            install_beta(self.source, self.source / 'nested', probe=lambda app: None)


if __name__ == '__main__':
    unittest.main()
