"""Party names and row order never change what the cash engine does (FEATURES N16).

Every tie between two parties breaks on a record id, never on the party's token: renaming a
customer must not hand it another customer's lateness draw, alert or message.
"""

import hashlib
import random
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts import LeverKind, TxCategory
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.gaps import _top_customers, find_gaps
from app.engines.cash.levers import LeverContext, smoothing_levers
from app.engines.cash.simulate import draw, run
from tests.cash.helpers import AS_OF, T, bill, daily, invoice, obligation, paid_invoice, txn

D = Decimal
DRAWN = ("sales_ratio", "invoice_day", "new_invoice", "new_invoice_delay", "new_bill",
         "new_bill_delay", "purchase", "running")
A, B = "PARTY_aaaa000001", "PARTY_bbbb000001"


def _renamer(salt: int, keep_order: bool | None = None):
    """A consistent new token for every party. With `keep_order` set, A and B are renamed so
    that their tokens sort the same way (True) or the other way round (False)."""
    def new(token: str | None) -> str | None:
        if token is None:
            return None
        if keep_order is not None and token in (A, B):
            first, second = ("PARTY_m000000001", "PARTY_z000000001")
            if token == A:
                return first if keep_order else second
            return second if keep_order else first
        return "PARTY_" + hashlib.sha256(f"{salt}|{token}".encode()).hexdigest()[:10]
    return new


def _renamed(items, new):
    return [i.model_copy(update={"counterparty_token": new(i.counterparty_token)}) for i in items]


def _draws(txns, invoices, bills=(), seed=5, paths=200):
    base = forecast_baseline(T, AS_OF, D(50000), list(txns), list(invoices), list(bills), [],
                             [], horizon=30)
    return draw(base, seed, paths)


def _same(left, right) -> bool:
    return all(np.array_equal(getattr(left, a), getattr(right, a)) for a in DRAWN)


def _history():
    """Ten settled invoices, 0 to 10 days late: several possible payment days for anyone."""
    return [paid_invoice(f"H{n}", date(2026, 8, 1) + timedelta(days=n), n * 7 % 11,
                         party="PARTY_hist000001") for n in range(10)]


def test_two_customers_owing_the_same_keep_their_own_lateness_under_any_names():
    tied = [invoice("IA", date(2026, 9, 20), date(2026, 10, 5), 30000, party=A),
            invoice("IB", date(2026, 9, 20), date(2026, 10, 25), 30000, party=B)]
    sales = daily(date(2026, 7, 1), 92, lambda d: 1000)
    plain = _draws(sales, _history() + tied)
    for keep_order in (True, False):  # the old token tie-break swapped draws on the second
        renamed = _draws(sales, _renamed(_history() + tied, _renamer(0, keep_order)))
        assert _same(renamed, plain), keep_order


@st.composite
def _ledgers(draw_):
    sales = daily(date(2026, 7, 1), 92, lambda d: draw_(st.sampled_from([0, 900, 2500])))
    parties = [f"PARTY_cust{n:06d}" for n in range(3)]
    docs = draw_(st.lists(st.tuples(
        st.integers(0, 2), st.sampled_from([60, 75, 80]),  # shared issue days make ties
        st.sampled_from([10, 20]), st.sampled_from([4000, 9000]),
        st.one_of(st.none(), st.integers(-2, 12)), st.booleans()), max_size=10))
    invoices, bills = list(_history()), []
    for n, (who, day, term, amount, delay, is_bill) in enumerate(docs):
        issue = date(2026, 7, 1) + timedelta(days=day)
        paid_on = issue + timedelta(days=term + delay) if delay is not None else None
        kw = {"paid": amount, "paid_date": paid_on} if paid_on and paid_on <= AS_OF else {}
        if is_bill:
            bills.append(bill(f"B{n}", issue, issue + timedelta(days=term), amount,
                              party=f"PARTY_supp{who:06d}", **kw))
        else:
            invoices.append(invoice(f"I{n}", issue, issue + timedelta(days=term), amount,
                                    party=parties[who], **kw))
    return sales, invoices, bills


@pytest.mark.property
@settings(max_examples=40, deadline=None)
@given(ledger=_ledgers(), salt=st.integers(0, 10**6))
def test_renaming_parties_and_shuffling_rows_never_change_a_draw(ledger, salt):
    sales, invoices, bills = ledger
    plain = _draws(sales, invoices, bills)
    new = _renamer(salt)
    noisy = [_renamed(group, new) for group in (sales, invoices, bills)]
    for group in noisy:
        random.Random(salt).shuffle(group)
    assert _same(_draws(*noisy), plain)
    assert [new(t) for t in _top_customers(invoices, AS_OF)] == \
        _top_customers(noisy[1], AS_OF)


def test_equal_top_customers_are_chosen_by_their_first_invoice_not_their_name():
    # four customers, the last two tied: only three are watched for slowing down
    invoices = [invoice("I1", date(2026, 9, 1), date(2026, 9, 10), 9000, party="PARTY_big000001"),
                invoice("I2", date(2026, 9, 2), date(2026, 9, 11), 8000, party="PARTY_mid000001"),
                invoice("I3", date(2026, 9, 3), date(2026, 9, 12), 5000, party=A),
                invoice("I4", date(2026, 9, 3), date(2026, 9, 12), 5000, party=B)]
    for keep_order in (True, False):
        new = _renamer(0, keep_order)
        assert _top_customers(_renamed(invoices, new), AS_OF)[-1] == new(A)  # I3 < I4


def test_a_staggered_purchase_goes_to_the_same_supplier_under_any_names():
    """Two suppliers owed the same: the message goes to the one with the first open bill."""
    flat = daily(date(2026, 3, 1), 214, lambda d: 1000)
    buys = [txn(AS_OF - timedelta(days=n), 1000, "outflow", TxCategory.purchase)
            for n in range(91)]
    steady = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), 3) for n in range(3)]
    customer = invoice("I1", date(2026, 6, 30), date(2026, 10, 11), 5000)
    # both due after the 20-day horizon: they name the suppliers without moving the gap
    owed = [bill("B1", date(2026, 9, 1), date(2026, 10, 28), 4000, party=A),
            bill("B2", date(2026, 9, 1), date(2026, 10, 29), 4000, party=B)]
    for keep_order in (True, False):
        new = _renamer(0, keep_order)
        base = forecast_baseline(T, AS_OF, D(20000), flat + buys, [*steady, customer],
                                 _renamed(owed, new), [obligation(amount=12000, day=10)], [],
                                 horizon=20)
        draws = draw(base, 5, 40)
        ctx = LeverContext(sim=run(base, draws), draws=draws)
        gap = find_gaps(ctx.sim, D(10000))[0]
        (lever,) = [lv for lv in smoothing_levers(ctx, gap)
                    if lv.lever.kind is LeverKind.stagger_purchase]
        assert lever.lever.action.payload["counterparty_token"] == new(A), keep_order
