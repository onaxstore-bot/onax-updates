"""One-time local configuration: verify connections, protect credentials, register task."""
import argparse
import os
from pathlib import Path
from agendar_windows import main as register_task
from cj_client import CJClient
from cofre_windows import save
from coletar_conciliacao import ShopifyReader, collect


def prepare(*, token, key, domain, shop_id, vault, directory,
            verify=None, save_credentials=None, register=None):
    vault, directory = Path(vault), Path(directory)
    if vault.exists():
        return 'COFRE_JA_EXISTE'
    verify = verify or (lambda: collect(ShopifyReader(domain, token), CJClient(key), shop_id))
    save_credentials = save_credentials or (lambda: save(vault, token, key))
    register = register or (lambda: register_task(['--dados', str(directory), '--cofre', str(vault),
                                                   '--loja-cj', shop_id, '--dominio', domain]))
    report = verify()
    if not isinstance(report, dict) or report.get('complete') is not True:
        return 'VALIDACAO_FALHOU'
    save_credentials()
    if register() != 0:
        return 'COFRE_SALVO_AGENDAMENTO_FALHOU'
    return 'TAREFA_CRIADA_TESTE_PENDENTE'


def retry_schedule(*, vault, directory, shop_id, domain, register=None):
    """Retry only scheduling; preserve the existing vault and all tasks."""
    vault, directory = Path(vault), Path(directory)
    if vault.is_symlink() or not vault.is_file():
        return 'COFRE_INDISPONIVEL'
    register = register or register_task
    result = register(['--dados', str(directory), '--cofre', str(vault),
                       '--loja-cj', shop_id, '--dominio', domain])
    return 'TAREFA_CRIADA_TESTE_PENDENTE' if result == 0 else 'AGENDAMENTO_FALHOU'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Configuração inicial do monitor TechMiner.')
    parser.add_argument('--dados', required=True, type=Path)
    parser.add_argument('--cofre', required=True, type=Path)
    parser.add_argument('--loja-cj', required=True)
    parser.add_argument('--dominio', default='example.myshopify.com')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        print('Configuração disponível somente no Windows.')
        return 1
    try:
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            if args.cofre.exists():
                if not messagebox.askyesno('TechMiner', 'Já existem credenciais protegidas. Deseja tentar criar novamente o agendamento? A tarefa existente não será substituída.', parent=root):
                    return 1
                state = retry_schedule(vault=args.cofre, directory=args.dados, shop_id=args.loja_cj, domain=args.dominio)
                if state == 'TAREFA_CRIADA_TESTE_PENDENTE':
                    messagebox.showinfo('TechMiner', 'Tarefa criada. Ainda é necessário confirmar a execução agendada.', parent=root)
                    return 0
                messagebox.showwarning('TechMiner', 'Agendamento não criado; pode já existir uma tarefa com esse nome. Credenciais preservadas.', parent=root)
                return 1
            token = simpledialog.askstring('TechMiner', 'Token Shopify com acesso de leitura a produtos, estoque e pedidos:', show='*', parent=root)
            if token is None:
                return 1
            key = simpledialog.askstring('TechMiner', 'Chave de API da CJ:', show='*', parent=root)
            if key is None:
                return 1
            state = prepare(token=token, key=key, domain=args.dominio, shop_id=args.loja_cj,
                            vault=args.cofre, directory=args.dados)
            if state == 'TAREFA_CRIADA_TESTE_PENDENTE':
                messagebox.showinfo('TechMiner', 'Conexões consultadas e tarefa criada. Ainda é necessário confirmar a execução agendada.', parent=root)
                return 0
            if state == 'COFRE_SALVO_AGENDAMENTO_FALHOU':
                messagebox.showwarning('TechMiner', 'Credenciais protegidas foram preservadas, mas o agendamento não foi criado.', parent=root)
            else:
                messagebox.showwarning('TechMiner', 'Configuração não concluída. Nenhuma alteração na loja foi feita.', parent=root)
            return 1
        finally:
            root.destroy()
    except Exception:
        # Never display raw exception strings that may include credentials.
        print('Configuração não concluída; nenhuma credencial foi exibida.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
