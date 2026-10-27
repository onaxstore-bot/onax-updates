"""Desktop alert from local status; does not transmit any data."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from status_monitor import inspect


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dados', required=True, type=Path)
    args = parser.parse_args(argv)
    result = inspect(args.dados, now=datetime.now(timezone.utc))
    if result['current'] == 'FALHOU':
        message = 'A verificação da ONAX falhou. O último relatório concluído foi preservado.'
    elif result['current'] in ('STATUS_INVALIDO', 'POSSIVEL_INTERRUPCAO'):
        message = 'Não foi possível confirmar o estado da verificação da ONAX. Consulte o monitor.'
    elif any(a.get('code') in ('VINCULO_ATIVO_PENDENTE', 'ESTOQUE_DIVERGENTE', 'ESTOQUE_NAO_CONFIRMADO',
                                'PEDIDO_EM_ESPERA', 'PEDIDO_CJ_NAO_LOCALIZADO', 'PEDIDOS_NAO_CONFIRMADOS',
                                'CONSULTA_PEDIDOS_INCOMPLETA', 'PAGAMENTO_CJ_PENDENTE', 'PEDIDO_CJ_CANCELADO') for a in result['alerts']):
        message = 'Há vínculos, estoques ou pedidos que precisam de atenção. Consulte o relatório.'
    else:
        return 0
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            messagebox.showwarning('TechMiner ONAX', message, parent=root)
        finally:
            root.destroy()
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
