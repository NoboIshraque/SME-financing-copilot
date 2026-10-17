"""Load a synthetic SME into the fact ledger (dev and test convenience).

Stores the SME's ledger records and one raw `initial_balance` fact: the total of the opening
balances in its profile, dated the first day of the ledger.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.contracts import DataMode, Fact, Granularity, Period, Unit
from app.facts.store import FactStore, fact_id

if TYPE_CHECKING:
    from app.synthetic import SME

INITIAL_BALANCE = "initial_balance"
PROFILE_REF = "profile.json#opening_balances"


def load_sme_into(store: FactStore, sme: SME, start: date) -> Fact:
    """Store every ledger record of `sme`; return its `initial_balance` fact."""
    store.add_transactions(sme.transactions)
    store.add_invoices(sme.invoices)
    store.add_bills(sme.bills)
    store.add_obligations(sme.obligations)
    period = Period(start=start, end=start, granularity=Granularity.day)
    value = sme.opening_total.amount
    initial = Fact(
        id=fact_id(sme.id, INITIAL_BALANCE, period, None, 0, value, (PROFILE_REF,)),
        tenant_id=sme.id,
        metric=INITIAL_BALANCE,
        value=value,
        unit=Unit.BDT,
        period=period,
        source_refs=(PROFILE_REF,),
        data_mode=DataMode.synthetic,
    )
    return store.put_fact(initial)
