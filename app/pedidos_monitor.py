"""Read-only order observations; never creates, pays, cancels or fulfills an order."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from cj_client import CJError
from coletar_conciliacao import CollectionError


ORDERS = '''query Orders($first: Int!, $after: String) { orders(first: $first, after: $after, reverse: true) { nodes { id name createdAt displayFinancialStatus displayFulfillmentStatus tags test } pageInfo { hasNextPage endCursor } } }'''
STATUSES = ('CREATED', 'IN_CART', 'UNPAID', 'UNSHIPPED', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'OTHER')
PROTECT = {'ONAX-TESTE', 'NAO-ENVIAR', 'NAO-PAGAR-FORNECEDOR'}


def shopify_orders(reader, max_pages=4):
    rows, seen, cursors, cursor = [], set(), set(), None
    for _ in range(max_pages):
        data = reader._transport(ORDERS, {'first': 50, 'after': cursor})
        block = data.get('orders') if isinstance(data, dict) else None
        if not isinstance(block, dict) or not isinstance(block.get('nodes'), list) or not isinstance(block.get('pageInfo'), dict):
            raise CollectionError('Leitura de pedidos Shopify incompleta.')
        info = block['pageInfo']
        if type(info.get('hasNextPage')) is not bool:
            raise CollectionError('Paginação de pedidos Shopify incompleta.')
        if info['hasNextPage'] and not block['nodes']:
            raise CollectionError('Página de pedidos vazia antes do fim da lista.')
        for row in block['nodes']:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not isinstance(row.get('name'), str) or row['id'] in seen:
                raise CollectionError('Pedido Shopify inválido ou repetido.')
            seen.add(row['id'])
            rows.append(row)
        if not info['hasNextPage']:
            return rows, True
        cursor = info.get('endCursor')
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise CollectionError('Cursor de pedidos inválido.')
        cursors.add(cursor)
    return rows, False


def cj_orders(client, shop_id, *, pages_per_status=2):
    found, errors, incomplete, seen, conflicts = [], [], [], {}, set()
    for status in STATUSES:
        expected = None
        read = 0
        seen_in_filter = set()
        for page in range(1, pages_per_status + 1):
            try:
                data = client.orders(status, page=page, size=50)
            except CJError:
                errors.append(status)
                break
            if not isinstance(data, dict) or type(data.get('total')) is not int or data['total'] < 0 or not isinstance(data.get('list'), list):
                errors.append(status)
                break
            if expected is None:
                expected = data['total']
            if data['total'] != expected or read + len(data['list']) > expected or (read < expected and not data['list']):
                errors.append(status)
                break
            valid = True
            for item in data['list']:
                if (not isinstance(item, dict) or not isinstance(item.get('shopId'), str) or not item['shopId'] or
                        not isinstance(item.get('orderId'), str) or not item['orderId']):
                    valid = False
                    break
                if item['orderId'] in seen_in_filter:
                    if item['shopId'] == shop_id and isinstance(item.get('orderNum'), str):
                        conflicts.add(item['orderNum'])
                    valid = False
                    break
                seen_in_filter.add(item['orderId'])
                if item['shopId'] != shop_id:
                    continue
                if (not isinstance(item.get('orderNum'), str) or not item['orderNum'] or
                        not isinstance(item.get('orderStatus'), str) or not item['orderStatus']):
                    valid = False
                    break
                identity = item['orderId']
                observation = (item['orderNum'], item['orderStatus'])
                if identity in seen and seen[identity] != observation:
                    conflicts.update((seen[identity][0], observation[0]))
                    valid = False
                    break
                if identity not in seen:
                    seen[identity] = observation
                    # No shipping addresses, names, emails, phone numbers or prices in reports.
                    found.append({'name': item['orderNum'], 'status': item['orderStatus']})
            if not valid:
                errors.append(status)
                break
            read += len(data['list'])
            if read == expected:
                break
        else:
            incomplete.append(status)
    return found, {'queried_statuses': list(STATUSES), 'failed_statuses': errors,
                   'truncated_statuses': incomplete, 'conflicting_order_names': sorted(conflicts),
                   'all_filtered_pages_read': not errors and not incomplete}


def scan(shopify, cj, shop_id):
    result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'status': 'NAO_CONCLUSIVO',
              'orders': [], 'coverage': {}, 'write_allowed': False,
              'note': 'Somente pedidos acessíveis à API; leitura pontual e filtros CJ não comprovam ausência.'}
    try:
        orders, shopify_complete = shopify_orders(shopify)
    except CollectionError:
        result['reason'] = 'Consulta Shopify de pedidos indisponível ou incompleta.'
        return result
    links, coverage = cj_orders(cj, shop_id)
    by_name = defaultdict(list)
    for link in links:
        by_name[link['name']].append(link['status'])
    names = Counter(o['name'] for o in orders)
    for order in orders:
        tags = order.get('tags')
        if type(order.get('test')) is not bool or not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            result['orders'].append({'name': order['name'], 'status': 'DADOS_INCOMPLETOS'})
            continue
        protected = order['test'] or bool(PROTECT.intersection(t.upper() for t in tags))
        financial, fulfillment = order.get('displayFinancialStatus'), order.get('displayFulfillmentStatus')
        if protected:
            state = 'TESTE_OU_PROTEGIDO'
        elif not isinstance(financial, str) or not isinstance(fulfillment, str) or names[order['name']] != 1:
            state = 'DADOS_INCOMPLETOS'
        elif fulfillment == 'ON_HOLD':
            state = 'EM_ESPERA'
        elif len(by_name[order['name']]) > 1 or order['name'] in coverage['conflicting_order_names']:
            state = 'DADOS_INCOMPLETOS'
        elif financial == 'PAID' and fulfillment in ('UNFULFILLED', 'PARTIALLY_FULFILLED') and by_name[order['name']] == ['UNPAID']:
            state = 'PAGAMENTO_CJ_PENDENTE'
        elif financial == 'PAID' and fulfillment in ('UNFULFILLED', 'PARTIALLY_FULFILLED') and by_name[order['name']] == ['CANCELLED']:
            state = 'PEDIDO_CJ_CANCELADO'
        elif financial == 'PAID' and fulfillment in ('UNFULFILLED', 'PARTIALLY_FULFILLED') and not by_name[order['name']]:
            state = 'SEM_CORRESPONDENCIA_OBSERVADA' if coverage['all_filtered_pages_read'] else 'DADOS_INCOMPLETOS'
        else:
            state = 'OBSERVADO'
        result['orders'].append({'name': order['name'], 'status': state,
                                 'financial_status': financial, 'fulfillment_status': fulfillment,
                                 'cj_observed_statuses': by_name[order['name']]})
    result['coverage'] = {'shopify_accessible_pages_complete': shopify_complete, 'cj': coverage}
    counts = Counter(item['status'] for item in result['orders'])
    result['counts'] = dict(counts)
    result['status'] = 'CONSULTADO' if shopify_complete and coverage['all_filtered_pages_read'] else 'PARCIAL'
    return result
