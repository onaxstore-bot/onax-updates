import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cofre_windows import VaultError, _dpapi, load, save
from monitor_conciliacao import main


class VaultTests(unittest.TestCase):
    # Fake reversible encoding checks file/logic, not Windows DPAPI security.
    def protect(self, data):
        return bytes(x ^ 0xA5 for x in data)

    def unprotect(self, data):
        return bytes(x ^ 0xA5 for x in data)

    def test_no_plaintext_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.dat'
            save(path, 'shop-token', 'cj-token', protect=self.protect)
            self.assertNotIn(b'shop-token', path.read_bytes())
            self.assertEqual(load(path, unprotect=self.unprotect), {'shopify': 'shop-token', 'cj': 'cj-token'})
            before = path.read_bytes()
            with self.assertRaises(VaultError):
                save(path, 'changed', 'changed', protect=self.protect)
            self.assertEqual(path.read_bytes(), before)

    def test_rejects_cleartext_and_bad_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.dat'
            with self.assertRaises(VaultError):
                save(path, 'a', 'b', protect=lambda data: data)
            with self.assertRaises(VaultError):
                save(path, 'a b', 'c', protect=self.protect)
            self.assertFalse(path.exists())

    def test_corrupt_cofre_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault.dat'
            path.write_bytes(b'broken')
            with self.assertRaises(VaultError):
                load(path, unprotect=self.unprotect)

    def test_no_windows_dpapi_on_linux(self):
        if os.name != 'nt':
            with self.assertRaises(VaultError):
                _dpapi(b'secret')

    def test_monitor_reports_error_when_vault_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory) / 'missing'
            result = main(['--dados', directory, '--loja-cj', '12', '--cofre', str(vault)])
            self.assertEqual(result, 1)
            status = json.loads((Path(directory) / 'status.json').read_text())
            self.assertEqual(status['state'], 'FALHOU')


if __name__ == '__main__':
    unittest.main()
