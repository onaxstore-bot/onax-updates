"""Local Windows checks; no live credentials, network, scheduler or store writes."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'app'))
from beta_setup import install_beta
from cofre_windows import load, save


@unittest.skipUnless(os.name == 'nt', 'Requires real Windows DPAPI and filesystem')
class WindowsIntegrationTests(unittest.TestCase):
    def test_real_dpapi_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'vault.dat'
            save(path, 'token-de-teste', 'chave-de-teste')
            encrypted = path.read_bytes()
            self.assertNotIn(b'token-de-teste', encrypted)
            self.assertNotIn(b'chave-de-teste', encrypted)
            self.assertEqual(load(path), {'shopify': 'token-de-teste', 'cj': 'chave-de-teste'})
            with self.assertRaises(ValueError):
                save(path, 'outra', 'outra')
            self.assertEqual(path.read_bytes(), encrypted)

    def test_actual_package_installs_in_separate_temporary_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'TechMiner Beta'
            self.assertTrue(Path(sys.executable).with_name('pythonw.exe').is_file(), 'Python grafico indisponivel')
            install_beta(ROOT / 'app', root)
            self.assertTrue((root / 'app' / 'painel_beta.py').is_file())
            self.assertTrue((root / 'data').is_dir())
            self.assertTrue((root / 'Abrir-TechMiner-Beta.cmd').is_file())


if __name__ == '__main__':
    unittest.main()
