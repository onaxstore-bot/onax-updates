"""CJ read-only client. No order, payment or publishing operations."""
import json
import time
import threading
from decimal import Decimal, InvalidOperation
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError


class CJError(RuntimeError):
    pass


def diagnostic(path, result, http_status=None):
    """Expose only a bounded numeric code and local labels, never server text."""
    steps = {'authentication/getAccessToken': 'autenticacao', 'product/listV2': 'busca',
             'product/query': 'produto', 'product/stock/queryBySku': 'estoque',
             'logistic/freightCalculate': 'frete'}
    code = result.get('code') if isinstance(result, dict) else None
    safe_code = str(code) if type(code) is int and 0 <= code <= 999999999 else 'indisponivel'
    hints = {
        1600000: 'Servico CJ ocupado.',
        1600001: 'Chave ou token invalido. Confira se copiou API Key, nao MCP Token.',
        1600002: 'Token de acesso ausente.',
        1600004: 'Autorizacao da conta CJ nao confirmada.',
        1600005: 'API Key nao aceita. Confira a chave e a autorizacao da API.',
        1600006: 'Conta de desenvolvedor CJ nao encontrada.',
        1600008: 'Autorizacao da conta CJ nao confirmada.',
        1600100: 'Interface CJ desativada; revisar o conector.',
        1600101: 'Interface CJ nao encontrada; revisar o conector.',
        1600200: 'Limite de chamadas atingido. Nao repetir em sequencia.',
        1600201: 'Cota da conta CJ esgotada.',
        1600300: 'CJ rejeitou os parametros da consulta.',
        1600301: 'Tempo de resposta CJ excedido.',
        1601000: 'Usuario CJ nao encontrado para esta credencial.',
        1602000: 'Variante nao encontrada.',
        1602001: 'Produto nao encontrado.',
        1602002: 'Produto retirado do catalogo CJ.',
        1602003: 'Variante retirada do catalogo CJ.'}
    hint = hints.get(code, 'Causa ainda nao identificada; informar somente esta linha de diagnostico.') if type(code) is int else 'Resposta CJ sem codigo numerico valido.'
    status = ' | HTTP %s' % http_status if type(http_status) is int else ''
    return 'Etapa: %s | Codigo CJ: %s%s. %s Nenhuma compra enviada.' % (
        steps.get(path, 'consulta'), safe_code, status, hint)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CJClient:
    BASE = 'https://developers.cjdropshipping.com/api2.0/v1/'
    ALLOWED = {'authentication/getAccessToken', 'product/listV2',
               'product/query', 'product/stock/queryBySku', 'logistic/freightCalculate',
               'product/conn/connection', 'shopping/order/list'}

    def __init__(self, api_key, transport=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise CJError('Chave CJ ausente.')
        self._key = api_key.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in self._key):
            raise CJError('A colagem trouxe caracteres de controle. Use o campo de senha da janela; nenhuma consulta enviada.')
        if any(c.isspace() for c in self._key):
            raise CJError('A chave colada contem espacos internos. Copie pelo icone da CJ; nenhuma consulta enviada.')
        self._token = None
        self._transport = transport or self._http
        self._last_call = 0
        self._lock = threading.Lock()

    def _http(self, method, path, params, body, headers):
        url = self.BASE + path
        if params:
            url += '?' + urlencode(params)
        payload = json.dumps(body).encode() if body is not None else None
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise CJError('Resposta CJ excedeu o limite.')
            return json.loads(raw, parse_float=Decimal)
        except HTTPError as exc:
            try:
                raw = exc.read(65537)
                result = json.loads(raw) if len(raw) <= 65536 else None
            except (ValueError, UnicodeError, OSError):
                result = None
            raise CJError(diagnostic(path, result, exc.code)) from None
        except (URLError, TimeoutError, OSError):
            raise CJError('Falha de rede CJ; nenhuma compra foi enviada.') from None
        except (ValueError, UnicodeError):
            raise CJError('Resposta CJ inválida.') from None

    def _call(self, method, path, params=None, body=None, auth=True):
        if path not in self.ALLOWED:
            raise CJError('Operação não permitida neste conector de consulta.')
        if method != ('POST' if path in ('authentication/getAccessToken', 'logistic/freightCalculate') else 'GET'):
            raise CJError('Método não permitido neste conector de consulta.')
        if auth and not self._token:
            self.authenticate()
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['CJ-Access-Token'] = self._token
        with self._lock:
            pause = 1.05 - (time.monotonic() - self._last_call)
            if pause > 0:
                time.sleep(pause)
            self._last_call = time.monotonic()
            result = self._transport(method, path, params, body, headers)
        if not isinstance(result, dict) or result.get('result') is not True or result.get('code') != 200:
            raise CJError(diagnostic(path, result))
        return result.get('data')

    def authenticate(self):
        result = self._call('POST', 'authentication/getAccessToken',
                            body={'apiKey': self._key}, auth=False)
        if not isinstance(result, dict) or not isinstance(result.get('accessToken'), str) or not result['accessToken']:
            raise CJError('CJ não retornou um token válido.')
        self._token = result['accessToken']

    def search(self, keyword, page=1, size=20):
        if (not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 200 or
                type(page) is not int or not 1 <= page <= 1000 or
                type(size) is not int or not 1 <= size <= 100):
            raise CJError('Busca inválida.')
        return self._call('GET', 'product/listV2', params={'keyWord': keyword.strip(), 'page': page, 'size': size})

    def product(self, sku):
        if not sku:
            raise CJError('SKU obrigatório.')
        return self._call('GET', 'product/query', params={'variantSku': sku})

    def stock(self, sku):
        if not sku:
            raise CJError('SKU obrigatório.')
        return self._call('GET', 'product/stock/queryBySku', params={'sku': sku})

    def connections(self, shop_id, page=1, size=100):
        if not isinstance(shop_id, str) or not shop_id.isascii() or not shop_id.isdigit() or type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
            raise CJError('Loja ou página de vínculos inválida.')
        return self._call('GET', 'product/conn/connection', params={'shopId': shop_id, 'page': page, 'pageSize': size})

    def orders(self, status, page=1, size=50):
        allowed = {'CREATED', 'IN_CART', 'UNPAID', 'UNSHIPPED', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'OTHER'}
        if status not in allowed or type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 50:
            raise CJError('Filtro de pedidos inválido.')
        return self._call('GET', 'shopping/order/list', params={'status': status, 'pageNum': page, 'pageSize': size})

    def freight(self, vid, destination='US', origin='CN', quantity=1, zip_code=None):
        if not vid or type(quantity) is not int or quantity < 1:
            raise CJError('Variante e quantidade inválidas.')
        if any(len(c) != 2 or not c.isascii() or not c.isalpha() or c != c.upper() for c in [destination, origin]):
            raise CJError('País inválido.')
        body = {'startCountryCode': origin, 'endCountryCode': destination,
                'products': [{'vid': vid, 'quantity': quantity}]}
        if zip_code:
            body['zip'] = zip_code
        rows = self._call('POST', 'logistic/freightCalculate', body=body)
        if not isinstance(rows, list) or not rows:
            raise CJError('Nenhuma rota cotada. Frete desconhecido não é frete grátis.')
        quotes = []
        for row in rows:
            if not isinstance(row, dict):
                raise CJError('Cotação inválida.')
            if row.get('error') or row.get('errorEn'):
                continue
            try:
                price = Decimal(str(row['logisticPrice']))
                if not price.is_finite() or price < 0:
                    raise ValueError()
                name = row['logisticName']
                if not isinstance(name, str) or not name.strip():
                    raise ValueError()
            except (KeyError, InvalidOperation, ValueError):
                raise CJError('Cotação incompleta; publicação bloqueada.') from None
            total_value = row.get('totalPostageFee')
            total = None
            if total_value is not None:
                try:
                    total = Decimal(str(total_value))
                    if not total.is_finite() or total < price:
                        raise ValueError()
                except (InvalidOperation, ValueError):
                    raise CJError('Total de frete inválido ou inferior ao frete básico.') from None
            quotes.append({'method': name, 'shipping_usd': str(price),
                           'total_shipping_usd': str(total) if total is not None else None,
                           'transit_estimate': row.get('logisticAging'),
                           'origin': origin, 'destination': destination,
                           'zip': zip_code, 'quantity': quantity,
                           'vid': vid, 'preliminary': True})
        if not quotes:
            raise CJError('Nenhuma rota válida cotada. Frete não confirmado.')
        return sorted(quotes, key=lambda x: Decimal(x['total_shipping_usd'] or x['shipping_usd']))
