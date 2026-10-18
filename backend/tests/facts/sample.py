"""A small hand-checked ledger for September 2026 (tenant_a).

Every expected value below was computed by hand from these rows; see the comments.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.contracts import Granularity, Period, TxCategory
from app.facts.store import FactStore
from tests.facts.helpers import SEP, bill, invoice, raw_fact, txn

INITIAL_DAY = Period(start=date(2026, 8, 1), end=date(2026, 8, 1), granularity=Granularity.day)

TRANSACTIONS = (
    txn(1, date(2026, 9, 2), 1000),                                   # cash sale
    txn(2, date(2026, 9, 5), 500, category=TxCategory.collection),    # baki collected
    txn(3, date(2026, 9, 7), 300, "outflow", TxCategory.purchase),
    txn(4, date(2026, 9, 10), 200, "outflow", TxCategory.rent),
    txn(5, date(2026, 9, 11), 100, "outflow", TxCategory.salary),
    txn(6, date(2026, 9, 12), 50, "outflow", TxCategory.owner_draw),
    txn(7, date(2026, 8, 20), 400),                                   # before the period
    txn(8, date(2026, 10, 1), 999),                                   # after the period
)
INVOICES = (
    invoice(1, date(2026, 9, 3), 2000, paid=500),                       # 1500 open
    invoice(2, date(2026, 8, 15), 1000, paid=1000, paid_date=date(2026, 10, 5)),  # open at 30/9
    invoice(3, date(2026, 8, 1), 600, paid=600, paid_date=date(2026, 8, 20)),     # settled
)
BILLS = (
    bill(1, date(2026, 9, 4), 1200),                                    # 1200 open
    bill(2, date(2026, 7, 1), 800, paid=800, paid_date=date(2026, 7, 30)),        # settled
)
INITIAL = raw_fact("initial_balance", "10000.00", period=INITIAL_DAY, refs=("profile.json#L1",))

EXPECTED_SEP = {
    "cash_in": Decimal("1500.00"),             # 1000 + 500
    "cash_out": Decimal("650.00"),             # 300 + 200 + 100 + 50
    "cash_sales": Decimal("1000.00"),
    "credit_sales": Decimal("2000.00"),        # INV-1
    "purchases": Decimal("1500.00"),           # 300 cash + 1200 billed
    "operating_expenses": Decimal("300.00"),   # rent 200 + salary 100
    "receivables": Decimal("2500.00"),         # 1500 (INV-1) + 1000 (INV-2 paid in Oct)
    "payables": Decimal("1200.00"),            # BIL-1
    "opening_balance": Decimal("10400.00"),    # 10000 + 400 on 20 Aug
    "net_sales": Decimal("3000.00"),           # 1000 + 2000
    "net_cash_flow": Decimal("850.00"),        # 1500 - 650
    "closing_balance": Decimal("11250.00"),    # 10400 + 1500 - 650
    "gross_profit": Decimal("1500.00"),        # 3000 - 1500
    "gross_margin": Decimal("0.5000"),         # 1500 / 3000
    "dso": Decimal("25.0"),                    # 2500 / 3000 * 30
    "dpo": Decimal("24.0"),                    # 1200 / 1500 * 30
}


def load_sample(store: FactStore) -> Period:
    store.add_transactions(TRANSACTIONS)
    store.add_invoices(INVOICES)
    store.add_bills(BILLS)
    store.put_fact(INITIAL)
    return SEP
