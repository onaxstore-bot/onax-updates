"""Prompt locally for credentials and protect them with Windows DPAPI."""
import argparse
import os
from pathlib import Path
from cofre_windows import save, VaultError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Preparar credenciais protegidas para o monitor.')
    parser.add_argument('--cofre', type=Path, required=True)
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
                messagebox.showwarning('TechMiner', 'As credenciais já estão configuradas; o arquivo existente foi preservado.', parent=root)
                return 1
            token = simpledialog.askstring('TechMiner', 'Token de leitura da Shopify:', show='*', parent=root)
            if token is None:
                return 1
            key = simpledialog.askstring('TechMiner', 'Chave de API da CJ:', show='*', parent=root)
            if key is None:
                return 1
            save(args.cofre, token, key)
            messagebox.showinfo('TechMiner', 'Credenciais protegidas para este usuário do Windows. A conexão ainda precisa ser testada.', parent=root)
            return 0
        finally:
            root.destroy()
    except Exception:
        print('Configuração não concluída; nenhuma credencial foi exibida.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
