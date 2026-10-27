"""Compare same-variant inventory snapshots without changing either platform."""
from datetime import datetime


def compare_inventory(*, sku, country, shop_levels, cj_rows, observed_at, now):
    result = {'sku': sku, 'country': country, 'status': 'NAO_CONCLUSIVO',
              'shopify_available': None, 'cj_inventory': None, 'write_allowed': False}
    try:
        when = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
        if now.tzinfo is None or when.tzinfo is None or not 0 <= (now - when).total_seconds() <= 3600:
            raise ValueError('dados antigos ou sem fuso')
        shop = [x for x in shop_levels if isinstance(x, dict) and x.get('sku') == sku and
                x.get('location_name') == 'cjdropshipping']
        cj = [x for x in cj_rows if isinstance(x, dict) and x.get('countryCode') == country]
        if len(shop) != 1 or len(cj) != 1:
            raise ValueError('localização ou origem ausente ou ambígua')
        available, committed, supplier = shop[0].get('available'), shop[0].get('committed'), cj[0].get('cjInventoryNum')
        if any(type(x) is not int or x < 0 for x in (available, committed, supplier)):
            raise ValueError('quantidade inválida')
        result.update(shopify_available=available, cj_inventory=supplier)
        if committed:
            result['reason'] = 'Há unidades comprometidas; diferenças não são comparáveis diretamente.'
        else:
            result['status'] = 'COINCIDE' if available == supplier else 'DIFERENTE'
            result['reason'] = 'Comparação pontual; não comprova sincronização automática ou estoque futuro.'
    except (ValueError, TypeError, AttributeError):
        result['reason'] = 'Dados incompletos, antigos ou com localização ambígua.'
    return result
