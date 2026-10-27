import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import build_beta


class BuildBetaTests(unittest.TestCase):
    def test_package_contains_installer_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'beta.zip'
            build_beta.build(output)
            with zipfile.ZipFile(output) as package:
                names = set(package.namelist())
                self.assertTrue({'INSTALAR-BETA.cmd', 'LEIA-ME.txt', 'beta_setup.py', 'app/painel_beta.py'} <= names)
                self.assertFalse(any('credenciais' in n.lower() or 'execucoes/' in n for n in names))
            with self.assertRaises(FileExistsError):
                build_beta.build(output)

    def test_nonempty_store_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'app'
            app.mkdir()
            for path in (root / 'beta_setup.py', app / 'release_health.py', app / 'painel_beta.py'):
                path.write_text('pass', encoding='utf-8')
            (app / 'shopify_snapshot.json').write_text(json.dumps({'data': {'secret': 'private'}}), encoding='utf-8')
            with patch.object(build_beta, 'ROOT', root), self.assertRaises(ValueError):
                build_beta.build(root / 'out.zip')


if __name__ == '__main__':
    unittest.main()
