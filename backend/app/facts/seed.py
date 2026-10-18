"""Load synthetic SMEs into the fact ledger (dev, demo and tests).

Stores each SME's ledger records, one raw `initial_balance` fact (the total of the opening
balances in its profile, dated the first day of the ledger) and, given an as-of day, its
profile facts (business age, trade licence, e-TIN, staff) dated that day. Idempotent:
re-running stores nothing new and leaves the ledger revision unchanged.

    uv run python -m app.facts.seed        # every synthetic SME into the configured database
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.contracts import DataMode, Fact, Granularity, Period, Unit
from app.facts.store import FactStore, fact_id

if TYPE_CHECKING:
    from app.synthetic import SME

INITIAL_BALANCE = "initial_balance"
PROFILE_REF = "profile.json#opening_balances"
# fact metric -> profile.json key. Yes/no answers are stored as 1/0 (unit `count`).
PROFILE_FACTS = {
    "business_age_months": "business_age_months",
    "trade_licence": "trade_licence",
    "etin_registered": "etin",
    "staff_count": "staff",
}


def _raw(tenant_id: str, metric: str, value: Decimal, unit: Unit, day: date,
         ref: str) -> Fact:
    period = Period(start=day, end=day, granularity=Granularity.day)
    return Fact(id=fact_id(tenant_id, metric, period, None, 0, value, (ref,)),
                tenant_id=tenant_id, metric=metric, value=value, unit=unit, period=period,
                source_refs=(ref,), data_mode=DataMode.synthetic)


def load_sme_into(store: FactStore, sme: SME, start: date, as_of: date | None = None) -> Fact:
    """Store every ledger record of `sme`; return its `initial_balance` fact."""
    store.add_transactions(sme.transactions)
    store.add_invoices(sme.invoices)
    store.add_bills(sme.bills)
    store.add_obligations(sme.obligations)
    initial = store.put_fact(_raw(sme.id, INITIAL_BALANCE, sme.opening_total.amount, Unit.BDT,
                                  start, PROFILE_REF))
    if as_of is not None:
        for metric, key in PROFILE_FACTS.items():
            raw = sme.profile.get(key)
            if raw is None:
                continue
            value = Decimal(int(raw)) if isinstance(raw, bool) else Decimal(str(raw))
            store.put_fact(_raw(sme.id, metric, value, Unit.count, as_of, f"profile.json#{key}"))
    return initial


def main() -> int:
    from app.db import init_db, make_engine, session_factory
    from app.settings import get_settings
    from app.synthetic import load_universe

    engine = make_engine(get_settings().database_url)
    init_db(engine)
    universe = load_universe()
    with session_factory(engine)() as session:
        store = FactStore(session)
        for sme in universe.smes.values():
            load_sme_into(store, sme, universe.start, universe.as_of)
            session.commit()
            print(f"seeded {sme.id}: {len(sme.transactions)} transactions (synthetic)")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
