"""ONAX offline prototype. No network, credentials, or actual purchases."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING


class Blocked(ValueError):
    """A required business fact is missing or a gate failed."""


def decimal(value, label):
    if value is None or isinstance(value, (bool, float)):
        raise Blocked(f'{label}: missing or inexact value')
    try:
        number = Decimal(value)
    except Exception as exc:
        raise Blocked(f'{label}: invalid number') from exc
    if not number.is_finite() or number < 0:
        raise Blocked(f'{label}: invalid number')
    return number


def cents(value, label):
    number = decimal(value, label) * 100
    if number != number.to_integral_value():
        raise Blocked(f'{label}: more than two decimal places')
    return int(number)


@dataclass(frozen=True)
class Costs:
    product: str | None
    freight: str | None
    fixed_fees: str | None
    tax_and_fx: str | None
    returns_reserve: str | None
    overhead: str | None
    proportional_fees: str | None
    ads_rate: str | None
    chatgpt_reserve: str = '0.02'

    def amounts(self):
        fixed = sum((decimal(getattr(self, key), key) for key in (
            'product', 'freight', 'fixed_fees', 'tax_and_fx',
            'returns_reserve', 'overhead')), Decimal(0))
        ads = decimal(self.ads_rate, 'ads_rate')
        chatgpt = decimal(self.chatgpt_reserve, 'chatgpt_reserve')
        fees = decimal(self.proportional_fees, 'proportional_fees')
        if ads > Decimal('.05') or chatgpt != Decimal('.02'):
            raise Blocked('policy: ads exceed assumed cap or reserve is not 2%')
        rate = ads + chatgpt + fees
        if fixed <= 0 or rate >= 1:
            raise Blocked('cost structure is invalid')
        return fixed, rate


def price_for(costs: Costs, target='0.30'):
    target = decimal(target, 'target')
    if not Decimal('.30') <= target <= Decimal('.50'):
        raise Blocked('target must be 30% to 50% of total cost')
    fixed, rate = costs.amounts()
    denominator = 1 - (1 + target) * rate
    if denominator <= 0:
        raise Blocked('no feasible price for this cost structure')
    return ((1 + target) * fixed / denominator).quantize(
        Decimal('.01'), rounding=ROUND_CEILING)


def profitability(costs: Costs, selling_price):
    price = decimal(selling_price, 'selling_price')
    fixed, rate = costs.amounts()
    if price <= 0:
        raise Blocked('selling price must be positive')
    total = fixed + rate * price
    profit = price - total
    return {'price': price, 'cost': total, 'profit': profit,
            'return_on_cost': profit / total,
            'revenue_margin': profit / price if price else Decimal(0)}


def valid_webhook(body: bytes, signature: str, secret: bytes):
    """Verification utility only; this package exposes no HTTP endpoint."""
    if not secret or not signature:
        return False
    expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest())
    try:
        return hmac.compare_digest(expected, signature.encode('ascii'))
    except (UnicodeEncodeError, AttributeError):
        return False


class Ledger:
    """One simulated item/quote per order; latest snapshot required before reserve.

    SQLite reservations are atomic. Supplier operations are records only.
    This is NOT a production webhook receiver or supplier client.
    """
    def __init__(self, path, simulated_balance='0.00', *,
                 simulated_authorization=False, order_limit='0.00', buffer='0.00'):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.authorized = simulated_authorization
        self.limit = cents(order_limit, 'order_limit')
        self.buffer = cents(buffer, 'buffer')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS wallet(id INTEGER PRIMARY KEY CHECK(id=1), balance INTEGER NOT NULL CHECK(balance>=0));
        CREATE TABLE IF NOT EXISTS snapshots(order_key TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(event_key TEXT PRIMARY KEY, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intents(order_key TEXT PRIMARY KEY, state TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), supplier_id TEXT UNIQUE, quote_id TEXT NOT NULL);
        ''')
        self.db.execute('INSERT OR IGNORE INTO wallet VALUES(1,?)',
                        (cents(simulated_balance, 'balance'),))

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        else:
            self.db.execute('COMMIT')

    def close(self):
        self.db.close()

    def snapshot(self, event_key, order_key, revision, **data):
        if not event_key or not order_key or type(revision) is not int or revision < 0:
            raise Blocked('event/order identity or revision missing')
        payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(json.dumps([order_key, revision, payload]).encode()).hexdigest()
        with self.transaction():
            event = self.db.execute('SELECT digest FROM events WHERE event_key=?', (event_key,)).fetchone()
            if event:
                if event['digest'] != digest:
                    raise Blocked('event identity reused with different payload')
                return 'DUPLICATE'
            old = self.db.execute('SELECT * FROM snapshots WHERE order_key=?', (order_key,)).fetchone()
            if old and old['revision'] == revision and old['payload'] != payload:
                raise Blocked('conflicting snapshot at same revision')
            self.db.execute('INSERT INTO events VALUES(?,?)', (event_key, digest))
            if old and old['revision'] >= revision:
                return 'STALE'
            self.db.execute('INSERT INTO snapshots VALUES(?,?,?) ON CONFLICT(order_key) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',
                            (order_key, revision, payload))
            if any(data.get(flag) is True for flag in ('cancelled','refunded','disputed')):
                intent = self.db.execute('SELECT state FROM intents WHERE order_key=?', (order_key,)).fetchone()
                if intent:
                    new = 'CANCELLED' if intent['state'] == 'RESERVED' else (
                        'CANCELLED' if intent['state'] == 'CANCELLED' else 'CANCEL_REQUESTED')
                    self.db.execute('UPDATE intents SET state=? WHERE order_key=?', (new, order_key))
            return 'APPLIED'

    def available(self):
        balance = self.db.execute('SELECT balance FROM wallet WHERE id=1').fetchone()[0]
        reserved = self.db.execute("SELECT COALESCE(SUM(amount),0) FROM intents WHERE state IN ('RESERVED','PAYMENT_UNKNOWN','CANCEL_REQUESTED') AND supplier_id IS NULL").fetchone()[0]
        return max(0, balance - reserved - self.buffer)

    def reserve(self, order_key, quote, costs: Costs, *, now, expected_revision):
        with self.transaction():
            existing = self.db.execute('SELECT * FROM intents WHERE order_key=?', (order_key,)).fetchone()
            if existing:
                return dict(existing)  # never creates a second intent
            if not self.authorized:
                raise Blocked('simulated spending authorization is disabled')
            row = self.db.execute('SELECT * FROM snapshots WHERE order_key=?', (order_key,)).fetchone()
            if not row or row['revision'] != expected_revision:
                raise Blocked('latest order snapshot was not confirmed')
            order = json.loads(row['payload'])
            required = {'paid':True,'captured':True,'cancelled':False,
                        'refunded':False,'disputed':False,'risk_clear':True}
            if any(order.get(k) is not v for k,v in required.items()):
                raise Blocked('order is not eligible for supplier purchase')
            if order.get('currency') != 'BRL' or quote.get('currency') != 'BRL':
                raise Blocked('quote/order currency mismatch or unconverted cost')
            if (type(order.get('quantity')) is not int or type(quote.get('quantity')) is not int
                    or order['quantity'] != 1 or quote['quantity'] != 1
                    or quote.get('product_approved') is not True):
                raise Blocked('prototype requires one approved item with quantity one')
            if not quote.get('id') or not quote.get('variant') or quote.get('variant') != order.get('variant'):
                raise Blocked('quote does not match the ordered variant')
            if quote.get('stock_confirmed') is not True or quote.get('route_confirmed') is not True:
                raise Blocked('stock or destination route not confirmed')
            if type(now) is not int or type(quote.get('expires_at')) is not int or now >= quote['expires_at']:
                raise Blocked('quote expired or validity unknown')
            amount = cents(quote.get('immediate_cost'), 'supplier immediate cost')
            product_and_freight = decimal(costs.product,'product') + decimal(costs.freight,'freight')
            if Decimal(amount)/100 != product_and_freight:
                raise Blocked('supplier amount is inconsistent with cost projection')
            if cents(order.get('captured_amount'),'captured_amount') != cents(order.get('total'),'total'):
                raise Blocked('payment is not fully captured')
            metrics = profitability(costs, order.get('product_revenue'))
            if metrics['revenue_margin'] < Decimal('.30'):
                raise Blocked('profit is below the target after costs')
            if amount <= 0 or amount > self.limit or amount > self.available():
                raise Blocked('balance or per-order spending limit insufficient')
            self.db.execute('INSERT INTO intents VALUES(?,?,?,NULL,?)',
                            (order_key,'RESERVED',amount,quote['id']))
            return dict(self.db.execute('SELECT * FROM intents WHERE order_key=?',(order_key,)).fetchone())

    def payment_unknown(self, order_key):
        with self.transaction():
            changed = self.db.execute("UPDATE intents SET state='PAYMENT_UNKNOWN' WHERE order_key=? AND state='RESERVED'",(order_key,)).rowcount
            if not changed:
                raise Blocked('intent not reserved; reconcile before retrying')

    def record_supplier_confirmation(self, order_key, supplier_id):
        if not supplier_id:
            raise Blocked('supplier confirmation is required')
        with self.transaction():
            intent = self.db.execute('SELECT * FROM intents WHERE order_key=?',(order_key,)).fetchone()
            if not intent or intent['state'] == 'CANCELLED':
                raise Blocked('no eligible supplier intent')
            if intent['supplier_id']:
                if intent['supplier_id'] != supplier_id:
                    raise Blocked('a different supplier purchase already exists')
                return 'DUPLICATE'
            if intent['state'] not in ('RESERVED','PAYMENT_UNKNOWN','CANCEL_REQUESTED'):
                raise Blocked('invalid supplier state')
            new = 'CANCEL_REQUESTED' if intent['state']=='CANCEL_REQUESTED' else 'PLACED'
            self.db.execute('UPDATE intents SET supplier_id=?,state=? WHERE order_key=?',
                            (supplier_id,new,order_key))
            self.db.execute('UPDATE wallet SET balance=balance-? WHERE id=1',(intent['amount'],))
            return 'RECORDED'

    def reconcile_not_purchased(self, order_key):
        """Record a verified no-charge result. Never call on a mere timeout."""
        with self.transaction():
            intent = self.db.execute('SELECT * FROM intents WHERE order_key=?',(order_key,)).fetchone()
            if not intent or intent['supplier_id'] or intent['state'] not in ('PAYMENT_UNKNOWN','CANCEL_REQUESTED'):
                raise Blocked('reconciliation is not eligible')
            # Close uncertain attempts. Any new attempt needs a new reviewed process.
            self.db.execute("UPDATE intents SET state='CANCELLED' WHERE order_key=?",(order_key,))
