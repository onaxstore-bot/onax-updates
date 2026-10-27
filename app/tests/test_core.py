import base64
import hashlib
import hmac
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal

from core import Blocked, Costs, Ledger, price_for, profitability, valid_webhook


COSTS = Costs('40','10','0','0','0','0','.04','.05')
ORDER = dict(paid=True,captured=True,cancelled=False,refunded=False,
             disputed=False,risk_clear=True,currency='BRL',variant='v1',
             total='100',captured_amount='100',product_revenue='100',quantity=1)
QUOTE = dict(id='q1',variant='v1',currency='BRL',stock_confirmed=True,
             route_confirmed=True,expires_at=200,immediate_cost='50',quantity=1,product_approved=True)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name,'ledger.sqlite')
        self.ledger = Ledger(self.path,'100',simulated_authorization=True,order_limit='60',buffer='0')
        self.ledger.snapshot('e1','shop/order1',1,**ORDER)

    def tearDown(self):
        self.ledger.close(); self.temp.cleanup()

    def reserve(self,**kwargs):
        return self.ledger.reserve('shop/order1',kwargs.pop('quote',QUOTE),
                    kwargs.pop('costs',COSTS),now=100,expected_revision=kwargs.pop('revision',1),**kwargs)

    def test_target_after_all_costs_and_rounding(self):
        for target in ['.30','.50']:
            p=price_for(COSTS,target)
            self.assertGreaterEqual(profitability(COSTS,str(p))['return_on_cost'],Decimal(target))
            self.assertLess(profitability(COSTS,str(p-Decimal('.01')))['return_on_cost'],Decimal(target))

    def test_unknown_and_invalid_costs_block(self):
        for value in [None,'NaN','Infinity','-1',0.1,True]:
            with self.subTest(value=value), self.assertRaises(Blocked):
                price_for(replace(COSTS,freight=value))

    def test_infeasible_cost_structure(self):
        with self.assertRaises(Blocked): price_for(replace(COSTS,proportional_fees='.75'))

    def test_ads_cap_and_chatgpt_reserve(self):
        for change in [dict(ads_rate='.051'),dict(chatgpt_reserve='.01')]:
            with self.assertRaises(Blocked): price_for(replace(COSTS,**change))

    def test_simulated_order_requires_margin_on_revenue(self):
        # At 75, profit / cost exceeds 30%, but profit / revenue is below 30%.
        self.ledger.snapshot('lower-revenue', 'shop/order1', 2,
                             **(ORDER | dict(total='75', captured_amount='75', product_revenue='75')))
        with self.assertRaises(Blocked):
            self.reserve(revision=2)

    def test_unpaid_and_incomplete_capture_block(self):
        for change in [dict(paid=False),dict(captured=False),dict(captured_amount='99'),dict(risk_clear=None)]:
            self.ledger.snapshot('e'+str(change),'shop/order1',2,**(ORDER|change))
            with self.assertRaises(Blocked): self.reserve(revision=2)
            self.ledger.snapshot('reset'+str(change),'shop/order1',3,**ORDER)
            # reset fixture database rather than reusing a synthetic revision
            self.ledger.db.execute('DELETE FROM snapshots')
            self.ledger.snapshot('reset1'+str(change),'shop/order1',1,**ORDER)

    def test_default_authorization_is_disabled(self):
        other=Ledger(os.path.join(self.temp.name,'disabled.sqlite'),'100')
        other.snapshot('e','o',1,**ORDER)
        with self.assertRaises(Blocked): other.reserve('o',QUOTE,COSTS,now=100,expected_revision=1)
        other.close()

    def test_duplicate_event_and_duplicate_intent(self):
        self.assertEqual(self.ledger.snapshot('e1','shop/order1',1,**ORDER),'DUPLICATE')
        self.reserve(); self.reserve()
        self.assertEqual(self.ledger.available(),5000)
        self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM intents').fetchone()[0],1)

    def test_changed_event_identity_block(self):
        with self.assertRaises(Blocked): self.ledger.snapshot('e1','shop/order1',2,**ORDER)

    def test_stale_paid_event_cannot_undo_cancel(self):
        self.ledger.snapshot('cancel','shop/order1',2,**(ORDER|dict(cancelled=True)))
        self.assertEqual(self.ledger.snapshot('stale','shop/order1',1,**ORDER),'STALE')
        with self.assertRaises(Blocked): self.reserve(revision=2)

    def test_cancel_before_purchase_releases_reservation(self):
        self.reserve()
        self.ledger.snapshot('cancel','shop/order1',2,**(ORDER|dict(cancelled=True)))
        self.assertEqual(self.ledger.available(),10000)
        with self.assertRaises(Blocked): self.ledger.record_supplier_confirmation('shop/order1','s1')

    def test_timeout_keeps_funds_and_confirmation_is_idempotent(self):
        self.reserve(); self.ledger.payment_unknown('shop/order1')
        self.assertEqual(self.ledger.available(),5000)
        self.reserve()
        self.ledger.record_supplier_confirmation('shop/order1','s1')
        self.assertEqual(self.ledger.record_supplier_confirmation('shop/order1','s1'),'DUPLICATE')
        self.assertEqual(self.ledger.available(),5000)

    def test_cancel_after_uncertain_purchase_keeps_funds(self):
        self.reserve(); self.ledger.payment_unknown('shop/order1')
        self.ledger.snapshot('cancel','shop/order1',2,**(ORDER|dict(cancelled=True)))
        self.assertEqual(self.ledger.available(),5000)
        self.ledger.record_supplier_confirmation('shop/order1','s1')
        self.assertEqual(self.ledger.available(),5000)

    def test_verified_no_purchase_releases_funds(self):
        self.reserve(); self.ledger.payment_unknown('shop/order1')
        self.ledger.reconcile_not_purchased('shop/order1')
        self.assertEqual(self.ledger.available(),10000)

    def test_quote_gates(self):
        for change in [dict(expires_at=100),dict(stock_confirmed=False),dict(route_confirmed=None),dict(variant='v2'),dict(currency='USD'),dict(immediate_cost='50.001'),dict(immediate_cost='51'),dict(product_approved=False),dict(quantity=2),dict(quantity=True),dict(quantity=1.0)]:
            with self.subTest(change=change), self.assertRaises(Blocked): self.reserve(quote=QUOTE|change)

    def test_below_target_is_blocked(self):
        self.ledger.snapshot('cheap','shop/order1',2,**(ORDER|dict(product_revenue='60')))
        with self.assertRaises(Blocked): self.reserve(revision=2)

    def test_two_workers_cannot_overspend(self):
        self.ledger.db.execute('UPDATE wallet SET balance=50*100')
        self.ledger.snapshot('e2','shop/order2',1,**ORDER)
        def worker(key):
            ledger=Ledger(self.path,simulated_authorization=True,order_limit='60')
            try:
                ledger.reserve(key,QUOTE,COSTS,now=100,expected_revision=1)
                return True
            except Blocked: return False
            finally: ledger.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(worker,['shop/order1','shop/order2']))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.ledger.available(),0)

    def test_signature_verifies_exact_bytes(self):
        body=b'{"order":1}'
        sig=base64.b64encode(hmac.new(b'test-only',body,hashlib.sha256).digest()).decode()
        self.assertTrue(valid_webhook(body,sig,b'test-only'))
        self.assertFalse(valid_webhook(body+b' ',sig,b'test-only'))
        self.assertFalse(valid_webhook(body,sig,b''))


if __name__=='__main__': unittest.main()
