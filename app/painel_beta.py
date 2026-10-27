"""Small Windows control panel for the isolated, read-only monitoring beta."""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from status_monitor import inspect


def main():
    if os.name != 'nt':
        print('Painel disponível somente no Windows.')
        return 1
    import tkinter as tk
    from tkinter import ttk, messagebox
    base = Path(__file__).resolve().parent.parent
    data = base / 'data'
    vault = data / 'credenciais.dat'
    app = Path(__file__).resolve().parent
    root = tk.Tk()
    root.title('TechMiner ONAX — Monitor beta')
    root.geometry('600x320')
    root.minsize(530, 280)
    frame = ttk.Frame(root, padding=22)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Monitor de vínculos ONAX', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Consulta de Shopify e CJ. A versão beta não altera a loja.', wraplength=550).pack(anchor='w', pady=(8, 15))
    state = tk.StringVar()
    ttk.Label(frame, textvariable=state, wraplength=550).pack(anchor='w', pady=8)
    labels = {'SEM_EXECUCAO': 'Ainda não houve verificação.', 'CONCLUIDO': 'Última verificação concluída.',
              'CONCLUIDO_COM_ALERTAS': 'Última verificação concluída com alertas.',
              'FALHOU': 'A última verificação falhou; o relatório anterior foi preservado.',
              'EM_ANDAMENTO': 'Verificação em andamento.',
              'POSSIVEL_INTERRUPCAO': 'A verificação pode ter sido interrompida.',
              'STATUS_INVALIDO': 'Não foi possível ler o estado da verificação.'}
    def refresh():
        result = inspect(data, now=datetime.now(timezone.utc))
        line = labels.get(result['current'], 'Estado não identificado.')
        friendly = {'VINCULO_ATIVO_PENDENTE': 'Variantes ativas com vínculo pendente',
                    'VINCULO_INATIVO_PENDENTE': 'Variantes inativas com vínculo pendente',
                    'SKUS_REPETIDOS': 'SKUs repetidos', 'ESTOQUE_DIVERGENTE': 'Estoques divergentes',
                    'ESTOQUE_NAO_CONFIRMADO': 'Estoques não confirmados', 'PEDIDO_EM_ESPERA': 'Pedidos em espera',
                    'PEDIDO_CJ_NAO_LOCALIZADO': 'Pedidos sem correspondência observada na CJ',
                    'PEDIDOS_NAO_CONFIRMADOS': 'Pedidos com dados incompletos',
                    'PAGAMENTO_CJ_PENDENTE': 'Pedidos com pagamento pendente na CJ',
                    'PEDIDO_CJ_CANCELADO': 'Pedidos cancelados na CJ',
                    'CONSULTA_PEDIDOS_INCOMPLETA': 'Consulta de pedidos incompleta'}
        for alert in result['alerts']:
            if alert.get('code') in friendly:
                line += '\n%s: %s' % (friendly[alert['code']], alert.get('count', '?'))
        if result['overdue'] is True:
            line += '\nA última verificação concluída está atrasada em relação ao limite de referência.'
        if result['last_success_at'] and not result['last_report_available']:
            line += '\nO relatório do último sucesso não está disponível.'
        state.set(line)
    def setup():
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        if not pythonw.is_file():
            messagebox.showerror('TechMiner', 'Não foi possível localizar o Python para abrir a configuração.', parent=root)
            return
        try:
            subprocess.Popen([str(pythonw), str(app / 'preparar_monitor.py'), '--dados', str(data),
                              '--cofre', str(vault), '--loja-cj', '123456789'], close_fds=True)
        except OSError:
            messagebox.showerror('TechMiner', 'Não foi possível abrir a configuração.', parent=root)
    def check_now():
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        if not vault.is_file() or not pythonw.is_file():
            messagebox.showwarning('TechMiner', 'Configure primeiro as credenciais do monitor.', parent=root)
            return
        try:
            subprocess.Popen([str(pythonw), str(app / 'job_monitor.py'), '--dados', str(data),
                              '--cofre', str(vault), '--loja-cj', '123456789', '--agora'], close_fds=True)
            messagebox.showinfo('TechMiner', 'Verificação iniciada. Aguarde e use Atualizar estado para consultar o resultado.', parent=root)
        except OSError:
            messagebox.showerror('TechMiner', 'Não foi possível iniciar a verificação.', parent=root)
    buttons = ttk.Frame(frame)
    buttons.pack(anchor='w', pady=12)
    ttk.Button(buttons, text='Configurar monitor', command=setup).pack(side='left', padx=(0, 8))
    ttk.Button(buttons, text='Verificar agora', command=check_now).pack(side='left', padx=(0, 8))
    ttk.Button(buttons, text='Atualizar estado', command=refresh).pack(side='left')
    ttk.Label(frame, text='A tarefa agendada e as conexões precisam ser validadas neste computador.', wraplength=550).pack(anchor='w', pady=8)
    refresh()
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
