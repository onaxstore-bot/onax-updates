"""Compare documented same-market delivered prices; no scraping or store writes."""
from datetime import datetime
from urllib.parse import urlsplit

from core import Blocked, decimal


def compare(evidence, *, pid, sku, country, currency, minimum_price, now):
    result = {'status': 'PENDENTE', 'offers': [], 'cheapest_delivered': None,
              'competitive_at_30_percent': None, 'publish_allowed': False}
    if now.tzinfo is None or now.utcoffset() is None:
        raise Blocked('Horário de referência sem fuso.')
    if not isinstance(evidence, list) or not evidence:
        result['reason'] = 'Nenhuma oferta documentada.'
        return result
    minimum = decimal(minimum_price, 'minimum_price')
    if minimum <= 0:
        raise Blocked('Preço mínimo inválido.')
    parsed = []
    try:
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError('Oferta inválida.')
            if (item.get('pid') != pid or item.get('sku') != sku or
                item.get('country') != country or item.get('currency') != currency or
                item.get('equivalent_verified') is not True or item.get('shipping_included') is not True):
                raise ValueError('Produto, país, moeda ou frete não confirmados.')
            url = urlsplit(item.get('url', ''))
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('Fonte da oferta inválida.')
            timestamp = datetime.fromisoformat(item.get('observed_at', '').replace('Z', '+00:00'))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError('Data sem fuso.')
            age = (now - timestamp).total_seconds()
            if age < 0 or age > 86400:
                raise ValueError('Oferta desatualizada ou futura.')
            value = decimal(item.get('delivered_price'), 'delivered_price')
            if value <= 0:
                raise ValueError('Preço inválido.')
            parsed.append({'url': item['url'], 'observed_at': item['observed_at'], 'delivered_price': str(value)})
    except (Blocked, ValueError, TypeError, AttributeError):
        result['reason'] = 'Há oferta incompleta, incompatível ou com mais de 24 horas; revisar fontes.'
        return result
    lowest = min(decimal(x['delivered_price'], 'price') for x in parsed)
    result.update(status='COMPARACAO_DOCUMENTADA', offers=parsed,
                  cheapest_delivered=str(lowest), competitive_at_30_percent=minimum <= lowest,
                  note='Comparação limitada às ofertas informadas; não representa o mercado inteiro.')
    return result
