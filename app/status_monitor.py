"""Read monitoring status without modifying any report or store."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def age_seconds(value, now):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None or now.tzinfo is None or now.utcoffset() is None:
            return None
        seconds = (now - parsed).total_seconds()
        return seconds if seconds >= 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def inspect(directory, *, now, max_age_hours=26, max_running_minutes=30):
    if not 0 < max_age_hours <= 24 * 365 or not 0 < max_running_minutes <= 24 * 60:
        raise ValueError('Limite de tempo inválido.')
    root = Path(directory)
    status_path = root / 'status.json'
    status, success = read_json(status_path), read_json(root / 'ultimo_sucesso.json')
    result = {'current': 'SEM_EXECUCAO', 'last_success_at': None, 'last_success_state': None,
              'last_success_age_hours': None, 'overdue': None, 'last_report_available': False, 'alerts': [],
              'note': 'Verificação local de status; não comprova execução agendada ou funcionamento das integrações.'}
    state = status.get('state') if status else None
    if not status:
        if status_path.exists():
            result['current'] = 'STATUS_INVALIDO'
    elif state not in ('EM_ANDAMENTO', 'CONCLUIDO', 'CONCLUIDO_COM_ALERTAS', 'FALHOU'):
        result['current'] = 'STATUS_INVALIDO'
    else:
        event_age = age_seconds(status.get('started_at') if state == 'EM_ANDAMENTO' else status.get('finished_at'), now)
        if event_age is None:
            result['current'] = 'STATUS_INVALIDO'
        elif state == 'EM_ANDAMENTO' and event_age > max_running_minutes * 60:
            result['current'] = 'POSSIVEL_INTERRUPCAO'
        else:
            result['current'] = state
    alerts = status.get('alerts', []) if status else []
    if isinstance(alerts, list):
        result['alerts'] = [a for a in alerts if isinstance(a, dict) and
                            a.get('code') in {'VINCULO_ATIVO_PENDENTE', 'VINCULO_INATIVO_PENDENTE',
                                              'SKUS_REPETIDOS', 'ESTOQUE_DIVERGENTE', 'ESTOQUE_NAO_CONFIRMADO',
                                              'PEDIDO_EM_ESPERA', 'PEDIDO_CJ_NAO_LOCALIZADO',
                                              'PEDIDOS_NAO_CONFIRMADOS', 'CONSULTA_PEDIDOS_INCOMPLETA', 'PAGAMENTO_CJ_PENDENTE', 'PEDIDO_CJ_CANCELADO',
                                              'COLETA_OU_GRAVACAO_FALHOU'} and
                            ('count' not in a or type(a['count']) is int and a['count'] >= 0)]
    if success and success.get('state') in ('CONCLUIDO', 'CONCLUIDO_COM_ALERTAS'):
        age = age_seconds(success.get('finished_at'), now)
        if age is not None:
            filename = success.get('report_file')
            if isinstance(filename, str) and re.fullmatch(r'execucoes/[0-9A-Za-z-]+\.json', filename):
                path = root / filename
                if not (root / 'execucoes').is_symlink() and not path.is_symlink():
                    report = read_json(path)
                    result['last_report_available'] = bool(report and report.get('complete') is True)
            result.update(last_success_at=success['finished_at'], last_success_state=success['state'],
                          last_success_age_hours=round(age / 3600, 2), overdue=age > max_age_hours * 3600)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Consultar status local, sem alterar dados.')
    parser.add_argument('--dados', type=Path, required=True)
    parser.add_argument('--limite-horas', type=float, default=26)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.dados, now=datetime.now(timezone.utc), max_age_hours=args.limite_horas)
    except ValueError:
        print('Limite de tempo inválido.')
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['current'] in ('CONCLUIDO', 'CONCLUIDO_COM_ALERTAS') and result['overdue'] is False and result['last_report_available'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
