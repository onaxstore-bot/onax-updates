"""Windows checks using temporary test files and a uniquely named temporary task."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'app'))
from beta_setup import install_beta
from cofre_windows import load, save
from agendar_windows import NS, build_xml, current_sid


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

    def test_tk_graphics_can_create_and_close_a_window(self):
        import tkinter as tk
        root = tk.Tk()
        try:
            root.withdraw()
            root.update_idletasks()
        finally:
            root.destroy()

    def test_panel_opens_with_expected_controls(self):
        import tkinter as tk
        import painel_beta
        texts = []
        def check_and_close(window):
            def visit(widget):
                if widget.winfo_class() == 'TButton':
                    texts.append(widget.cget('text'))
                for child in widget.winfo_children():
                    visit(child)
            try:
                window.update_idletasks()
                visit(window)
            finally:
                window.destroy()
        with patch.object(tk.Tk, 'mainloop', check_and_close):
            self.assertEqual(painel_beta.main(), 0)
        self.assertTrue({'Configurar monitor', 'Verificar agora', 'Atualizar estado'}.issubset(texts))

    def test_temporary_scheduled_task_can_run_and_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / 'ran.txt'
            script = root / 'test_job.py'
            script.write_text('from pathlib import Path\nPath(%r).write_text("ok")\n' % str(marker), encoding='utf-8')
            name = 'TechMiner-Test-' + uuid.uuid4().hex
            xml = build_xml(sid=current_sid(), executable=Path(sys.executable).with_name('pythonw.exe'),
                            job=script, directory=root, vault=root / 'dummy.dat',
                            cj_shop='123', domain='example.myshopify.com')
            tree = ET.fromstring(xml)
            for trigger in tree.find('{%s}Triggers' % NS):
                trigger.find('{%s}Enabled' % NS).text = 'false'
            taskfile = root / 'task.xml'
            taskfile.write_bytes(ET.tostring(tree, encoding='utf-16', xml_declaration=True))
            create = subprocess.run(['schtasks.exe', '/Create', '/TN', name, '/XML', str(taskfile)],
                                    capture_output=True, timeout=20)
            self.assertEqual(create.returncode, 0, 'Falha ao criar tarefa temporária: ' + repr(create.stderr))
            try:
                run = subprocess.run(['schtasks.exe', '/Run', '/TN', name], capture_output=True, timeout=20)
                self.assertEqual(run.returncode, 0, 'Falha ao executar tarefa temporária: ' + repr(run.stderr))
                deadline = time.monotonic() + 20
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.2)
                self.assertTrue(marker.is_file(), 'Tarefa não criou o arquivo esperado.')
                self.assertEqual(marker.read_text(), 'ok')
            finally:
                deleted = subprocess.run(['schtasks.exe', '/Delete', '/TN', name, '/F'], capture_output=True, timeout=20)
                self.assertEqual(deleted.returncode, 0, 'Tarefa temporária não foi removida.')


if __name__ == '__main__':
    unittest.main()
