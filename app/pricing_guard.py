"""Fail-closed, read-only pricing decision; never updates Shopify."""
from decimal import Decimal
from core import Blocked, Costs, decimal, profitability
from pricing_scenarios import price_for_revenue_margin


def evaluate(costs: Costs, competitor_price, *, target='0.30', comparison_verified=False, costs_verified=False):
    """Require verified, same-currency, delivered competitor price and complete costs."""
    if costs_verified is not True or comparison_verified is not True:
        return {'status': 'BLOCKED', 'reason': 'unverified costs or competition', 'publish_allowed': False}
    floor = price_for_revenue_margin(costs, target)
    cap = decimal(competitor_price, 'competitor_price')
    if cap <= 0:
        raise Blocked('competitor price must be positive')
    if floor > cap:
        return {'status': 'UNCOMPETITIVE', 'minimum_price': str(floor), 'competitor_price': str(cap), 'publish_allowed': False}
    metrics = profitability(costs, floor)
    return {'status': 'REVIEW', 'minimum_price': str(floor), 'competitor_price': str(cap),
            'net_margin': str(metrics['revenue_margin']), 'publish_allowed': False}
