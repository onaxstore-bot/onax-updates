"""One read-only monitoring run. No scheduler, purchases, publication or store writes."""
import argparse
import json
import os
import tempfile
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cj_client import CJClient
from coletar_conciliacao import ShopifyReader, collect
from cofre_windows import load
from inventario_automatico import scan
from pedidos_monitor import scan as scan_orders


class MonitorError(ValueError):
    pass


@contextmanager
def run_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / 'monitor.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise MonitorError('Já existe execução em andamento.') from None
    try:
        yield
    finally:
        lock.close()


def atomic_json(path, value):
    fd, temp = tempfile.mkstemp(prefix='.monitor-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def summarize(report):
    if not isinstance(report, dict) or report.get('complete') is not True or not isinstance(report.get('variants'), list):
        raise MonitorError('Relatório incompleto.')
    rows = report['variants']
    if type(report.get('variant_count')) is not int or report['variant_count'] != len(rows):
        raise MonitorError('Contagem de variantes não confere.')
    known_links = {'VINCULO_IDENTIFICADO', 'VINCULO_NAO_LOCALIZADO', 'IDENTIFICACAO_INCOMPLETA',
                   'MULTIPLOS_VINCULOS', 'DIVERGENCIA_DE_IDENTIDADE', 'IDENTIFICACAO_CJ_INCOMPLETA'}
    if any(not isinstance(row, dict) or row.get('link_status') not in known_links or
           row.get('product_status') not in {'ACTIVE', 'DRAFT', 'ARCHIVED', 'UNLISTED'} for row in rows):
        raise MonitorError('Relatório inválido.')
    alerts = []
    active_issues = [r for r in rows if r.get('product_status') == 'ACTIVE' and r.get('link_status') != 'VINCULO_IDENTIFICADO']
    if active_issues:
        alerts.append({'code': 'VINCULO_ATIVO_PENDENTE', 'count': len(active_issues)})
    remaining = [r for r in rows if r.get('product_status') != 'ACTIVE' and r.get('link_status') != 'VINCULO_IDENTIFICADO']
    if remaining:
        alerts.append({'code': 'VINCULO_INATIVO_PENDENTE', 'count': len(remaining)})
    duplicates = report.get('duplicate_skus')
    if not isinstance(duplicates, list):
        raise MonitorError('Dados de duplicação ausentes.')
    if duplicates:
        alerts.append({'code': 'SKUS_REPETIDOS', 'count': len(duplicates)})
    if 'inventory_scan' in report:
        inventory = report['inventory_scan']
        entries = inventory.get('results') if isinstance(inventory, dict) else None
        if not isinstance(entries, list) or any(not isinstance(e, dict) or e.get('status') not in
                                                ('COINCIDE', 'DIFERENTE', 'NAO_CONCLUSIVO') for e in entries):
            raise MonitorError('Dados de estoque inválidos.')
        active_count = sum(r.get('product_status') == 'ACTIVE' for r in rows)
        if len(entries) != active_count or inventory.get('active_variants') != active_count:
            raise MonitorError('Verificação de estoque incompleta.')
        expected_ids = [r.get('variant_id') for r in rows if r.get('product_status') == 'ACTIVE']
        observed_ids = [e.get('variant_id') for e in entries]
        if (any(not isinstance(v, str) or not v.isascii() or not v.isdigit() for v in expected_ids + observed_ids)
                or len(set(expected_ids)) != len(expected_ids) or Counter(expected_ids) != Counter(observed_ids)):
            raise MonitorError('Identidades da verificação de estoque não conferem.')
        different = sum(e['status'] == 'DIFERENTE' for e in entries)
        unknown = sum(e['status'] == 'NAO_CONCLUSIVO' for e in entries)
        if different:
            alerts.append({'code': 'ESTOQUE_DIVERGENTE', 'count': different})
        if unknown:
            alerts.append({'code': 'ESTOQUE_NAO_CONFIRMADO', 'count': unknown})
    if 'orders_scan' in report:
        order_scan = report['orders_scan']
        if not isinstance(order_scan, dict) or order_scan.get('status') not in ('CONSULTADO', 'PARCIAL', 'NAO_CONCLUSIVO') or not isinstance(order_scan.get('orders'), list):
            raise MonitorError('Dados de pedidos inválidos.')
        allowed = {'TESTE_OU_PROTEGIDO', 'DADOS_INCOMPLETOS', 'EM_ESPERA', 'SEM_CORRESPONDENCIA_OBSERVADA', 'OBSERVADO', 'PAGAMENTO_CJ_PENDENTE', 'PEDIDO_CJ_CANCELADO'}
        orders = order_scan['orders']
        if any(not isinstance(o, dict) or o.get('status') not in allowed for o in orders):
            raise MonitorError('Estado de pedido inválido.')
        for state, code in [('EM_ESPERA', 'PEDIDO_EM_ESPERA'),
                            ('PAGAMENTO_CJ_PENDENTE', 'PAGAMENTO_CJ_PENDENTE'),
                            ('PEDIDO_CJ_CANCELADO', 'PEDIDO_CJ_CANCELADO'),
                            ('SEM_CORRESPONDENCIA_OBSERVADA', 'PEDIDO_CJ_NAO_LOCALIZADO'),
                            ('DADOS_INCOMPLETOS', 'PEDIDOS_NAO_CONFIRMADOS')]:
            count = sum(o['status'] == state for o in orders)
            if count:
                alerts.append({'code': code, 'count': count})
        if order_scan['status'] != 'CONSULTADO':
            alerts.append({'code': 'CONSULTA_PEDIDOS_INCOMPLETA'})
    return alerts


def run_once(directory, fetch):
    """Persist immutable run and latest status; failure preserves latest successful report."""
    directory = Path(directory)
    with run_lock(directory):
        runs = directory / 'execucoes'
        runs.mkdir(exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:12]
        started = datetime.now(timezone.utc).isoformat()
        status = {'run_id': run_id, 'started_at': started, 'state': 'EM_ANDAMENTO', 'write_allowed': False}
        atomic_json(directory / 'status.json', status)
        try:
            report = fetch()
            alerts = summarize(report)
            filename = run_id + '.json'
            atomic_json(runs / filename, report)
            if 'inventory_scan' in report:
                cursor = report['inventory_scan'].get('next_after')
                if cursor is not None and (not isinstance(cursor, str) or not cursor.isascii() or not cursor.isdigit()):
                    raise MonitorError('Marcador de estoque inválido.')
                status['inventory_cursor'] = cursor
            status.update(state='CONCLUIDO_COM_ALERTAS' if alerts else 'CONCLUIDO', alerts=alerts,
                          report_file='execucoes/' + filename, finished_at=datetime.now(timezone.utc).isoformat())
            atomic_json(directory / 'ultimo_sucesso.json', status)
            atomic_json(directory / 'status.json', status)
            return status
        except Exception:
            # Never persist exception text: it can contain credentials or private server data.
            status.update(state='FALHOU', alerts=[{'code': 'COLETA_OU_GRAVACAO_FALHOU'}],
                          finished_at=datetime.now(timezone.utc).isoformat())
            atomic_json(directory / 'status.json', status)
            return status


def previous_inventory_cursor(directory):
    try:
        status = json.loads((Path(directory) / 'ultimo_sucesso.json').read_text(encoding='utf-8'))
        cursor = status.get('inventory_cursor') if isinstance(status, dict) else None
        return cursor if isinstance(cursor, str) and cursor.isascii() and cursor.isdigit() else None
    except (OSError, ValueError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Executar uma verificação de conciliação somente leitura.')
    parser.add_argument('--dados', type=Path, required=True)
    parser.add_argument('--dominio', default='example.myshopify.com')
    parser.add_argument('--loja-cj', required=True)
    parser.add_argument('--origem-estoque', default='US', help='País de origem usado na comparação de estoque')
    parser.add_argument('--cofre', type=Path, help='Credenciais protegidas para o usuário atual do Windows')
    args = parser.parse_args(argv)
    def fetch():
        if args.cofre:
            saved = load(args.cofre)
            token, key = saved['shopify'], saved['cj']
        else:
            token, key = os.environ.get('SHOPIFY_ADMIN_TOKEN'), os.environ.get('CJ_API_KEY')
        if not token or not key:
            raise MonitorError('Credenciais indisponíveis para execução não interativa.')
        shopify, cj = ShopifyReader(args.dominio, token), CJClient(key)
        report = collect(shopify, cj, args.loja_cj)
        report['inventory_scan'] = scan(report, shopify, cj, origin=args.origem_estoque,
                                        start_after=previous_inventory_cursor(args.dados))
        report['orders_scan'] = scan_orders(shopify, cj, args.loja_cj)
        return report
    try:
        status = run_once(args.dados, fetch)
        print('Verificação:', status['state'])
        return 1 if status['state'] == 'FALHOU' else 0
    except (OSError, MonitorError):
        print('Verificação não iniciada: execução em andamento ou pasta indisponível.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
