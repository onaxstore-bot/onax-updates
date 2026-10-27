"""Single scheduled monitor run; read-only and non-interactive."""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from monitor_conciliacao import main as monitor_main
from status_monitor import inspect


def run(argv=None, *, notify=None):
    parser = argparse.ArgumentParser(description='Verificação diária do TechMiner.')
    parser.add_argument('--dados', type=Path, required=True)
    parser.add_argument('--cofre', type=Path, required=True)
    parser.add_argument('--loja-cj', required=True)
    parser.add_argument('--dominio', default='example.myshopify.com')
    parser.add_argument('--agora', action='store_true', help='Executar mesmo após verificação recente')
    args = parser.parse_args(argv)
    previous = inspect(args.dados, now=datetime.now(timezone.utc))
    if (not args.agora and previous['current'] in ('CONCLUIDO', 'CONCLUIDO_COM_ALERTAS') and
            previous['last_report_available'] and previous['last_success_age_hours'] is not None and
            previous['last_success_age_hours'] < 20):
        return 0
    result = monitor_main(['--dados', str(args.dados), '--cofre', str(args.cofre),
                           '--loja-cj', args.loja_cj, '--dominio', args.dominio])
    current = inspect(args.dados, now=datetime.now(timezone.utc))
    important = current['current'] in ('FALHOU', 'STATUS_INVALIDO', 'POSSIVEL_INTERRUPCAO') or any(
        alert.get('code') in ('VINCULO_ATIVO_PENDENTE', 'ESTOQUE_DIVERGENTE', 'ESTOQUE_NAO_CONFIRMADO',
                              'PEDIDO_EM_ESPERA', 'PEDIDO_CJ_NAO_LOCALIZADO', 'PEDIDOS_NAO_CONFIRMADOS',
                              'CONSULTA_PEDIDOS_INCOMPLETA', 'PAGAMENTO_CJ_PENDENTE', 'PEDIDO_CJ_CANCELADO')
        for alert in current['alerts'])
    if important and notify:
        notify(args.dados)
    return result


def notify_windows(directory):
    if os.name != 'nt':
        return
    executable = Path(sys.executable).with_name('pythonw.exe')
    if not executable.is_file():
        return
    try:
        subprocess.Popen([str(executable), str(Path(__file__).with_name('avisar_monitor.py')),
                          '--dados', str(directory)], close_fds=True)
    except OSError:
        pass  # The persisted status remains available even if desktop notification cannot start.


if __name__ == '__main__':
    raise SystemExit(run(notify=notify_windows))
