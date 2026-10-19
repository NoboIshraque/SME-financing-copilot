"""Ratios (WP-07 milestone 2): every ratio against a hand-computed quarter, and every reason
a ratio abstains."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.contracts import DocumentStatus, Granularity, TxCategory, Unit
from app.engines.analysis.ledger import calendar_period
from app.engines.analysis.ratios import NAMES, compute_ratios
from tests.analysis.helpers import (
    bill,
    emi,
    invoice,
    known,
    ledger,
    month,
    out,
    txn,
    universe_ledger,
)

D = Decimal
C = TxCategory
Q1 = calendar_period(date(2026, 1, 1), Granularity.quarter)  # 90 days
A, B, WALK_IN = "PARTY_custa00001", "PARTY_custb00001", "PARTY_walkin0001"


def _quarter():
    """Q1 2026 of a small shop, worked by hand in the comments below."""
    txns = [
        txn(date(2026, 1, 10), 6000, party=WALK_IN),  # till sales
        txn(date(2026, 2, 10), 3000, C.collection, party=A),
        txn(date(2026, 3, 1), 1000, C.collection, party=B),
        out(date(2026, 1, 15), 4000, C.supplier_payment),
        out(date(2026, 2, 5), 1000, C.rent),
        out(date(2026, 3, 5), 600, C.salary),
        out(date(2026, 3, 10), 500, C.loan_repayment),
        txn(date(2026, 3, 15), 2000, C.owner_topup),
        txn(date(2026, 3, 31), 1, C.transfer), out(date(2026, 3, 31), 1, C.transfer),
    ]
    invoices = [
        invoice("I-A", date(2026, 1, 5), date(2026, 2, 5), 4000, paid=3000, party=A),
        invoice("I-B", date(2026, 2, 1), date(2026, 3, 1), 1000, paid=1000,
                paid_date=date(2026, 3, 1), party=B),
    ]
    bills = [
        bill("S-1", date(2026, 1, 3), date(2026, 2, 3), 3000, paid=3000,
             paid_date=date(2026, 1, 15)),
        bill("S-2", date(2026, 3, 20), date(2026, 4, 20), 1500),
    ]
    facts = [known("stock_value", "2400", date(2026, 3, 31)),
             known("interest_expense", "150", date(2026, 1, 1), Granularity.quarter,
                   end=date(2026, 3, 31))]
    return ledger(txns, invoices, bills, [emi(500)], facts)


# revenue 10,000 = 6,000 till + 3,000 + 1,000 collections; purchases 4,000; opex 1,600;
# net profit 4,400. Cash on 31 Mar 15,900; receivables 1,000 (A); stock 2,400; payables
# 1,500 (S-2); EMIs due in the next 365 days 12 x 500 = 6,000 -> current liabilities 7,500.
# Credit sales 5,000; credit purchases 4,500; 90 days.
HAND = [
    ("gross_margin", "60.0", Unit.percent, None),  # 6,000 / 10,000
    ("net_margin", "44.0", Unit.percent, None),  # 4,400 / 10,000
    ("current_ratio", "2.57", Unit.ratio, "interpretation.covers_short_term"),  # 19,300 / 7,500
    ("quick_ratio", "2.25", Unit.ratio, "interpretation.covers_short_term"),  # 16,900 / 7,500
    ("dscr", "8.80", Unit.ratio, "interpretation.dscr.comfortable"),  # 4,400 / 500
    ("interest_cover", "29.33", Unit.ratio, None),  # 4,400 / 150
    ("dso", "18.0", Unit.days, None),  # 1,000 / 5,000 x 90
    ("dpo", "30.0", Unit.days, None),  # 1,500 / 4,500 x 90
    ("dio", "54.0", Unit.days, None),  # 2,400 / 4,000 x 90
    ("cash_conversion_cycle", "42.0", Unit.days, None),  # 18 + 54 - 30
    ("burn", "0.00", Unit.BDT, "interpretation.not_burning"),  # cash rose 5,900 > 2,000 new
    ("runway", None, Unit.days, "ratio.not_applicable.not_burning"),
    ("top_customer_share", "30.0", Unit.percent, "interpretation.concentrated"),  # A: 3,000
]


@pytest.fixture(scope="module")
def quarter():
    return compute_ratios(_quarter(), Q1)


@pytest.mark.scenario
@pytest.mark.parametrize(("name", "value", "unit", "interpretation"), HAND,
                         ids=[row[0] for row in HAND])
def test_ratio_by_hand(quarter, name, value, unit, interpretation):
    ratio = quarter.get(name)
    assert ratio.value == (D(value) if value is not None else None)
    assert ratio.unit is unit
    assert ratio.interpretation_key == interpretation
    assert ratio.period == Q1
    assert ratio.provenance.formula_id == f"analysis.ratio.{name}"


def test_every_ratio_is_reported_in_a_fixed_order(quarter):
    assert tuple(r.name for r in quarter.ratios) == NAMES
    assert quarter.get("dscr").benchmark == D("1.25")


def test_burn_and_a_short_runway():
    shop = ledger([txn(date(2026, 2, 1), 1000), out(date(2026, 2, 2), 3800, C.rent),
                   txn(date(2026, 2, 28), 1)])
    ratios = compute_ratios(shop, month(2026, 2))
    # net cash flow -2,799 over 28 days -> 2,799 x 30 / 28; cash 7,201
    assert ratios.get("burn").value == D("2998.93")
    assert ratios.get("burn").interpretation_key is None
    assert ratios.get("runway").value == D("72.0")  # 7,201 / 2,998.93 x 30
    assert ratios.get("runway").interpretation_key == "interpretation.runway_short"


def test_new_loan_money_does_not_hide_burn():
    shop = ledger([txn(date(2026, 2, 1), 20000, C.loan_disbursement),
                   out(date(2026, 2, 2), 2800, C.rent), txn(date(2026, 2, 28), 1)])
    ratios = compute_ratios(shop, month(2026, 2))
    # cash rose 17,201, but 20,000 of it was borrowed: (20,000 - 17,201) x 30 / 28, the same
    # burn as the shop without the loan
    assert ratios.get("burn").value == D("2998.93")


def _no_revenue():
    return ledger([out(date(2026, 1, 2), 100, C.rent), out(date(2026, 3, 31), 1, C.fee)])


def _emi_unpaid():
    return ledger([txn(date(2026, 1, 2), 100), txn(date(2026, 3, 31), 1)], obligations=[emi()])


def _repaid():
    return ledger([txn(date(2026, 1, 2), 100), out(date(2026, 3, 10), 50, C.loan_repayment)])


def _no_stock():
    shop = _quarter()
    return replace(shop, facts=tuple(f for f in shop.facts if f.metric != "stock_value"))


ABSTAIN = [
    ("gross_margin", _no_revenue, "ratio.not_applicable.no_revenue"),
    ("current_ratio", _no_stock, "ratio.missing.stock_value"),
    ("quick_ratio", _repaid, "ratio.not_applicable.no_current_liabilities"),
    ("dscr", _no_revenue, "interpretation.no_debt"),
    ("dscr", _emi_unpaid, "ratio.not_applicable.no_repayment_in_period"),
    ("interest_cover", _repaid, "ratio.missing.interest_expense"),
    ("interest_cover", _no_revenue, "interpretation.no_debt"),
    ("dso", _repaid, "ratio.not_applicable.no_credit_sales"),
    ("dpo", _repaid, "ratio.not_applicable.no_credit_purchases"),
    ("dio", _no_stock, "ratio.missing.stock_value"),
    ("cash_conversion_cycle", _no_stock, "ratio.missing.stock_value"),
    ("cash_conversion_cycle", _repaid, "ratio.not_applicable.no_credit_sales"),
    ("runway", _emi_unpaid, "ratio.not_applicable.not_burning"),
    ("top_customer_share", _repaid, "ratio.not_applicable.no_credit_customers"),
]


@pytest.mark.scenario
@pytest.mark.parametrize(("name", "build", "reason"), ABSTAIN,
                         ids=[f"{n}-{b.__name__.strip('_')}" for n, b, _r in ABSTAIN])
def test_a_ratio_abstains_and_says_why(name, build, reason):
    ratio = compute_ratios(build(), Q1).get(name)
    assert ratio.value is None
    assert ratio.interpretation_key == reason


@pytest.mark.scenario
@pytest.mark.parametrize(("profit", "reading"), [
    (900, "interpretation.dscr.cannot_cover"),
    (1100, "interpretation.dscr.below_lender_minimum"),
    (1250, "interpretation.dscr.comfortable"),  # exactly the lender minimum
])
def test_dscr_against_the_lender_minimum(profit, reading):
    shop = ledger([txn(date(2026, 2, 1), profit), out(date(2026, 2, 10), 1000, C.loan_repayment),
                   txn(date(2026, 2, 28), 1, C.transfer), out(date(2026, 2, 28), 1, C.transfer)])
    dscr = compute_ratios(shop, month(2026, 2)).get("dscr")
    assert dscr.value == D(profit) / 1000
    assert dscr.interpretation_key == reading


def test_walk_in_till_sales_are_never_one_customer():
    shop = ledger([txn(date(2026, 2, 1), 9000, party=WALK_IN),
                   txn(date(2026, 2, 2), 1000, C.collection, party=A),
                   txn(date(2026, 2, 28), 1, party=WALK_IN)],
                  [invoice("I-A", date(2026, 1, 20), date(2026, 2, 2), 1000, paid=1000,
                           paid_date=date(2026, 2, 2), party=A)])
    share = compute_ratios(shop, month(2026, 2)).get("top_customer_share")
    assert share.value == D("10.0")  # 1,000 of 10,001: A, not the walk-in token
    assert share.interpretation_key is None


def test_a_written_off_invoice_is_not_a_receivable_for_dso():
    shop = _quarter()
    written_off = invoice("I-W", date(2026, 3, 1), date(2026, 3, 10), 5000,
                          status=DocumentStatus.written_off, party=B)
    with_bad_debt = compute_ratios(replace(shop, invoices=(*shop.invoices, written_off)), Q1)
    # receivables stay 1,000; credit sales grow to 10,000 -> 1,000 / 10,000 x 90
    assert with_bad_debt.get("dso").value == D("9.0")


def test_ratio_provenance_points_at_recorded_inputs(quarter):
    shop = _quarter()
    facts = {f.id for f in shop.facts} | {shop.anchor.id}
    position = {f.id: n for n, f in enumerate(quarter.figures)}
    for ratio in quarter.ratios:
        for input_id in ratio.provenance.input_fact_ids:
            assert input_id in position or input_id in facts, (ratio.name, input_id)
    for n, figure in enumerate(quarter.figures):  # inputs come before what uses them
        for input_id in figure.provenance.input_fact_ids:
            assert input_id in facts or position[input_id] < n
    interest = quarter.get("interest_cover").provenance
    assert next(f.id for f in shop.facts if f.metric == "interest_expense") in \
        interest.input_fact_ids
    share = quarter.get("top_customer_share").provenance
    assert len([r for r in share.source_row_ids if r.startswith("txn:")]) == 3  # A + revenue


@pytest.mark.parametrize("sme_id", ["sme_garment", "sme_hardware"])
def test_dscr_of_the_shops_with_a_loan(universe, sme_id):
    sme = universe.smes[sme_id]
    q3 = calendar_period(date(2026, 9, 30), Granularity.quarter)
    ratios = compute_ratios(universe_ledger(universe, sme_id), q3)
    repaid = sum((t.amount.amount for t in sme.transactions
                  if t.category is C.loan_repayment and q3.contains(t.day)), D(0))
    net = ratios.statements.value("pnl", "net_profit")
    assert repaid > 0
    assert ratios.get("dscr").value == (net / repaid).quantize(D("0.01"), ROUND_HALF_UP)
    assert ratios.get("interest_cover").interpretation_key == "ratio.missing.interest_expense"
