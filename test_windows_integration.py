"""Windows checks using temporary test files and a uniquely named temporary task."""
import os
import json
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'app'))
from beta_setup import install_beta
from cofre_windows import load, save
from agendar_windows import NS, build_xml, current_sid


def wait_for_window(title, timeout=15):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.1)
    raise AssertionError('Janela não encontrada: ' + title)


def close_window(hwnd):
    import ctypes
    from ctypes import wintypes
    post = ctypes.WinDLL('user32', use_last_error=True).PostMessageW
    post.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    post.restype = wintypes.BOOL
    if not post(hwnd, 0x0010, 0, 0):
        raise AssertionError('Não foi possível fechar a janela de teste.')


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

    def test_notification_path_shows_expected_warning(self):
        import avisar_monitor
        with tempfile.TemporaryDirectory() as temp, \
             patch('avisar_monitor.inspect', return_value={'current': 'FALHOU', 'alerts': []}), \
             patch('tkinter.messagebox.showwarning') as show:
            self.assertEqual(avisar_monitor.main(['--dados', temp]), 0)
            show.assert_called_once()
            self.assertIn('falhou', show.call_args.args[1])

    def test_real_warning_window_opens_and_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            (data / 'status.json').write_text(json.dumps({'state': 'FALHOU',
                'finished_at': datetime.now().astimezone().isoformat(), 'alerts': []}), encoding='utf-8')
            proc = subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),
                                     str(ROOT / 'app' / 'avisar_monitor.py'), '--dados', str(data)])
            try:
                hwnd = wait_for_window('TechMiner ONAX')
                close_window(hwnd)
                self.assertEqual(proc.wait(timeout=10), 0)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=10)

    def test_beta_installer_and_launcher_open_the_panel(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, LOCALAPPDATA=temp)
            result = subprocess.run([sys.executable, str(ROOT / 'beta_setup.py')], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
            self.assertEqual(result.returncode, 0, repr(result.stderr))
            hwnd = wait_for_window('TechMiner ONAX — Monitor beta')
            close_window(hwnd)
            deadline = time.monotonic() + 10
            import ctypes
            while ctypes.windll.user32.FindWindowW(None, 'TechMiner ONAX — Monitor beta') and time.monotonic() < deadline:
                time.sleep(0.1)
            launcher = Path(temp) / 'TechMiner-ONAX-Beta' / 'Abrir-TechMiner-Beta.cmd'
            self.assertTrue(launcher.is_file())
            result = subprocess.run(['cmd.exe', '/c', str(launcher)], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            self.assertEqual(result.returncode, 0, repr(result.stderr))
            hwnd = wait_for_window('TechMiner ONAX — Monitor beta')
            close_window(hwnd)
            deadline = time.monotonic() + 10
            while ctypes.windll.user32.FindWindowW(None, 'TechMiner ONAX — Monitor beta') and time.monotonic() < deadline:
                time.sleep(0.1)

    def test_monitor_full_flow_with_real_vault_and_simulated_services(self):
        from coletar_conciliacao import ShopifyReader, PRODUCTS, VARIANTS
        from inventario_automatico import QUERY
        from pedidos_monitor import ORDERS
        from monitor_conciliacao import main as monitor_main
        domain = 'example.myshopify.com'
        page = {'hasNextPage': False, 'endCursor': None}
        def transport(query, variables):
            if query == PRODUCTS:
                return {'shop': {'myshopifyDomain': domain}, 'products': {'nodes': [
                    {'id': 'gid://shopify/Product/1', 'title': 'Example', 'status': 'ACTIVE',
                     'variantsCount': {'count': 1}}], 'pageInfo': page}}
            if query == VARIANTS:
                return {'productVariants': {'nodes': [{'id': 'gid://shopify/ProductVariant/2', 'sku': 'TEST-SKU',
                    'product': {'id': 'gid://shopify/Product/1'}}], 'pageInfo': page}}
            if query == QUERY:
                return {'productVariant': {'id': 'gid://shopify/ProductVariant/2', 'sku': 'TEST-SKU',
                    'inventoryItem': {'inventoryLevels': {'nodes': [{'location': {'id': 'loc', 'name': 'cjdropshipping'},
                      'quantities': [{'name': 'available', 'quantity': 5}, {'name': 'committed', 'quantity': 0}]}],
                      'pageInfo': page}}}}
            if query == ORDERS:
                return {'orders': {'nodes': [{'id': 'gid://shopify/Order/1', 'name': '#9001', 'test': True,
                    'tags': ['ONAX-TESTE'], 'displayFinancialStatus': 'PAID', 'displayFulfillmentStatus': 'ON_HOLD'}],
                    'pageInfo': page}}
            raise AssertionError('Unexpected query')
        shopify = ShopifyReader(domain, 'fake-token', transport=transport)
        cj = MagicMock()
        cj.connections.return_value = {'total': 1, 'list': [{'shopId': '12', 'platformProductId': '1',
            'platformVariantId': '2', 'platformSku': 'TEST-SKU', 'cjSku': 'TEST-SKU',
            'cjVariantId': 'v', 'cjProductId': 'p'}]}
        cj.stock.return_value = [{'countryCode': 'US', 'cjInventoryNum': 5, 'factoryInventoryNum': 0}]
        cj.orders.return_value = {'total': 0, 'list': []}
        with tempfile.TemporaryDirectory() as temp:
            data, vault = Path(temp) / 'data', Path(temp) / 'vault'
            save(vault, 'fake-token', 'fake-key')
            with patch('monitor_conciliacao.ShopifyReader', return_value=shopify), \
                 patch('monitor_conciliacao.CJClient', return_value=cj):
                result = monitor_main(['--dados', str(data), '--cofre', str(vault), '--loja-cj', '12', '--dominio', domain])
            self.assertEqual(result, 0)
            status = json.loads((data / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['state'], 'CONCLUIDO')
            report = json.loads((data / status['report_file']).read_text(encoding='utf-8'))
            self.assertEqual(report['inventory_scan']['results'][0]['status'], 'COINCIDE')
            self.assertEqual(report['orders_scan']['orders'][0]['status'], 'TESTE_OU_PROTEGIDO')
            self.assertFalse(report['write_allowed'])

    def test_scheduled_time_fires_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / 'automatic.txt'
            script = root / 'automatic_job.py'
            script.write_text('from pathlib import Path\nPath(%r).write_text("ok")\n' % str(marker), encoding='utf-8')
            name = 'TechMiner-Test-Auto-' + uuid.uuid4().hex
            xml = build_xml(sid=current_sid(), executable=Path(sys.executable).with_name('pythonw.exe'),
                            job=script, directory=root, vault=root / 'dummy.dat',
                            cj_shop='123', domain='example.myshopify.com')
            tree = ET.fromstring(xml)
            triggers = tree.find('{%s}Triggers' % NS)
            calendar = triggers.find('{%s}CalendarTrigger' % NS)
            calendar.find('{%s}StartBoundary' % NS).text = (datetime.now() + timedelta(seconds=20)).strftime('%Y-%m-%dT%H:%M:%S')
            triggers.remove(triggers.find('{%s}LogonTrigger' % NS))
            taskfile = root / 'automatic.xml'
            taskfile.write_bytes(ET.tostring(tree, encoding='utf-16', xml_declaration=True))
            create = subprocess.run(['schtasks.exe', '/Create', '/TN', name, '/XML', str(taskfile)],
                                    capture_output=True, timeout=20)
            self.assertEqual(create.returncode, 0, 'Falha ao criar tarefa temporária: ' + repr(create.stderr))
            try:
                deadline = time.monotonic() + 50
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.2)
                self.assertTrue(marker.is_file(), 'Tarefa automática não foi iniciada no intervalo esperado.')
                self.assertEqual(marker.read_text(), 'ok')
            finally:
                deleted = subprocess.run(['schtasks.exe', '/Delete', '/TN', name, '/F'], capture_output=True, timeout=20)
                self.assertEqual(deleted.returncode, 0, 'Tarefa temporária não foi removida.')

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
