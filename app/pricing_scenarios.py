"""Explicit pricing bases. Arithmetic only; no product approval or store writes."""
from decimal import Decimal, ROUND_CEILING
from core import Blocked, Costs, decimal, profitability, price_for


def price_for_revenue_margin(costs: Costs, target):
    target = decimal(target, 'target')
    if not Decimal('.30') <= target <= Decimal('.50'):
        raise Blocked('target must be 30% to 50% of sale revenue')
    fixed, rate = costs.amounts()
    denominator = 1 - rate - target
    if denominator <= 0:
        raise Blocked('no feasible price for this revenue margin')
    return (fixed / denominator).quantize(Decimal('.01'), rounding=ROUND_CEILING)


def compare_bases(costs: Costs, target):
    rows = []
    for basis, price in (('RETURN_ON_TOTAL_COST', price_for(costs, target)),
                         ('NET_MARGIN_ON_SALE', price_for_revenue_margin(costs, target))):
        metrics = profitability(costs, price)
        rows.append({'basis': basis, **{k: str(v) for k, v in metrics.items()},
                     'can_publish': False})
    return rows
