import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from preparar_monitor import prepare, retry_schedule


class SetupTests(unittest.TestCase):
    def test_verify_before_storing_and_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            order = []
            result = prepare(token='s', key='c', domain='x.myshopify.com', shop_id='12',
                             vault=Path(directory) / 'vault', directory=directory,
                             verify=lambda: order.append('verify') or {'complete': True},
                             save_credentials=lambda: order.append('save'),
                             register=lambda: order.append('schedule') or 0)
            self.assertEqual(order, ['verify', 'save', 'schedule'])
            self.assertEqual(result, 'TAREFA_CRIADA_TESTE_PENDENTE')

    def test_failed_validation_does_not_store_or_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            store, register = MagicMock(), MagicMock()
            result = prepare(token='s', key='c', domain='x.myshopify.com', shop_id='12',
                             vault=Path(directory) / 'vault', directory=directory,
                             verify=lambda: {'complete': False}, save_credentials=store, register=register)
            self.assertEqual(result, 'VALIDACAO_FALHOU')
            store.assert_not_called()
            register.assert_not_called()

    def test_scheduling_failure_reports_partial_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            stored = MagicMock()
            result = prepare(token='s', key='c', domain='x.myshopify.com', shop_id='12',
                             vault=Path(directory) / 'vault', directory=directory,
                             verify=lambda: {'complete': True}, save_credentials=stored, register=lambda: 1)
            self.assertEqual(result, 'COFRE_SALVO_AGENDAMENTO_FALHOU')
            stored.assert_called_once()

    def test_existing_vault_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault'
            path.write_text('existing')
            verify = MagicMock()
            result = prepare(token='s', key='c', domain='x.myshopify.com', shop_id='12',
                             vault=path, directory=directory, verify=verify)
            self.assertEqual(result, 'COFRE_JA_EXISTE')
            self.assertEqual(path.read_text(), 'existing')
            verify.assert_not_called()

    def test_schedule_retry_preserves_vault_and_does_not_request_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vault'
            path.write_bytes(b'protected')
            register = MagicMock(return_value=0)
            state = retry_schedule(vault=path, directory=directory, shop_id='12', domain='x.myshopify.com', register=register)
            self.assertEqual(state, 'TAREFA_CRIADA_TESTE_PENDENTE')
            self.assertEqual(path.read_bytes(), b'protected')
            register.assert_called_once()

    def test_schedule_retry_requires_existing_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            register = MagicMock()
            state = retry_schedule(vault=Path(directory) / 'missing', directory=directory, shop_id='12', domain='x.myshopify.com', register=register)
            self.assertEqual(state, 'COFRE_INDISPONIVEL')
            register.assert_not_called()


if __name__ == '__main__':
    unittest.main()
