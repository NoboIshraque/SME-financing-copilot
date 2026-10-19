"""Statements (WP-07 milestone 1): cash-basis P&L, balance-sheet-lite, cash flow."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import DataMode, Direction, DocumentStatus, Granularity, TxCategory
from app.engines.analysis.figures import FORMULAS
from app.engines.analysis.ledger import NotEnoughData, calendar_period
from app.engines.analysis.statements import build_statements, line_of
from app.synthetic.universe import SME_IDS
from tests.analysis.helpers import (
    START,
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
FEB = month(2026, 2)


def _shop():
    """January and February of a small shop, every kind of line at least once in February."""
    return [
        txn(date(2026, 1, 20), 500),  # January: only moves the opening cash
        out(date(2026, 1, 25), 200, C.rent),
        txn(date(2026, 2, 2), 1000),
        txn(date(2026, 2, 3), 1500),
        out(date(2026, 2, 4), 100, C.sales),  # a refund to a customer
        txn(date(2026, 2, 5), 400, C.collection),
        out(date(2026, 2, 6), 900, C.supplier_payment),
        out(date(2026, 2, 6), 300, C.purchase),
        txn(date(2026, 2, 7), 50, C.supplier_payment),  # a supplier refund
        out(date(2026, 2, 8), 250, C.rent),
        out(date(2026, 2, 9), 120, C.salary),
        out(date(2026, 2, 10), 30, C.utility),
        out(date(2026, 2, 11), 10, C.fee),
        out(date(2026, 2, 12), 15, C.other),
        txn(date(2026, 2, 13), 25, C.other),
        out(date(2026, 2, 14), 40, C.tax),
        txn(date(2026, 2, 15), 2000, C.loan_disbursement),
        out(date(2026, 2, 16), 300, C.loan_repayment),
        out(date(2026, 2, 17), 60, C.owner_draw),
        txn(date(2026, 2, 18), 70, C.owner_topup),
        out(date(2026, 2, 19), 80, C.transfer),
        txn(date(2026, 2, 19), 80, C.transfer),
    ]


def _february():
    """A sale on 2 February and the ledger running to the month's end."""
    return [txn(date(2026, 2, 2), 999), txn(date(2026, 2, 28), 1)]


def test_profit_and_loss_lines_by_hand():
    stmt = build_statements(ledger(_shop()), FEB)
    expected = {
        "cash_sales": D("2400.00"), "collections": D("400.00"), "revenue": D("2800.00"),
        "purchases": D("1150.00"), "gross_profit": D("1650.00"), "rent": D("250.00"),
        "salaries": D("120.00"), "utilities": D("30.00"), "fees": D("10.00"),
        "other_costs": D("15.00"), "operating_expenses": D("425.00"),
        "other_income": D("25.00"), "operating_profit": D("1250.00"), "tax": D("40.00"),
        "net_profit": D("1210.00"),
    }
    assert {line.key: line.figure.value for line in stmt.pnl} == expected
    assert [line.key for line in stmt.pnl if line.total] == [
        "revenue", "gross_profit", "operating_expenses", "operating_profit", "net_profit"]


def test_cash_flow_lines_by_hand():
    stmt = build_statements(ledger(_shop(), opening="10000"), FEB)
    values = {line.key: line.figure.value for line in stmt.cash_flow}
    assert values == {
        "opening_cash": D("10300.00"),  # 10,000 + January's 500 sale - 200 rent
        "cash_in": D("5125.00"), "cash_out": D("2205.00"),
        "operating_cash_flow": D("1210.00"), "loan_flows": D("1700.00"),
        "owner_flows": D("10.00"), "net_cash_flow": D("2920.00"),
        "closing_cash": D("13220.00"),
    }  # transfers between own accounts net to 0 and are left out


def test_a_transfer_to_an_account_not_on_record_shows_as_a_leak():
    stmt = build_statements(ledger([txn(date(2026, 2, 2), 1000),
                                    out(date(2026, 2, 3), 300, C.transfer)]), FEB)
    assert stmt.value("cash_flow", "transfers") == D("-300.00")
    assert stmt.value("cash_flow", "net_cash_flow") == D("700.00")


def test_every_category_and_direction_has_exactly_one_line():
    expected = {
        C.sales: "cash_sales", C.collection: "collections", C.purchase: "purchases",
        C.supplier_payment: "purchases", C.rent: "rent", C.salary: "salaries",
        C.utility: "utilities", C.fee: "fees", C.tax: "tax", C.loan_repayment: "loan_flows",
        C.loan_disbursement: "loan_flows", C.owner_draw: "owner_flows",
        C.owner_topup: "owner_flows", C.transfer: "transfers",
    }
    for category in TxCategory:
        for direction in Direction:
            want = expected.get(category) or ("other_income" if direction is Direction.inflow
                                              else "other_costs")
            assert line_of(category, direction) == want, (category, direction)


def test_detail_lines_without_transactions_are_left_out_but_totals_stay():
    stmt = build_statements(ledger([txn(date(2026, 2, 2), 1000)]), FEB)
    assert [line.key for line in stmt.pnl] == [
        "cash_sales", "revenue", "gross_profit", "operating_expenses", "operating_profit",
        "net_profit"]
    assert stmt.value("pnl", "operating_expenses") == 0
    # a total with nothing behind it still cites its evidence: the ledger's anchor
    opex = stmt.figure("pnl", "operating_expenses")
    assert opex.provenance.input_fact_ids == (ledger().anchor.id,)


def test_balance_sheet_lite_on_the_period_end():
    invoices = [
        invoice("I-1", date(2026, 2, 1), date(2026, 2, 15), 800, paid=300,
                paid_date=date(2026, 2, 10)),  # 500 still owed
        invoice("I-2", date(2026, 2, 5), date(2026, 2, 20), 700, paid=700,
                paid_date=date(2026, 3, 3)),  # settled after February: owed in full on 28 Feb
        invoice("I-3", date(2026, 2, 6), date(2026, 2, 20), 999,
                status=DocumentStatus.written_off),
        invoice("I-4", date(2026, 3, 1), date(2026, 3, 9), 400),  # issued after the day
    ]
    bills = [bill("B-1", date(2026, 2, 3), date(2026, 3, 3), 650)]
    facts = [known("stock_value", "4200", date(2026, 2, 20))]
    stmt = build_statements(ledger(_february(), invoices, bills, facts=facts), FEB)
    values = {line.key: line.figure.value for line in stmt.balance_sheet}
    assert values == {"cash": D("11000.00"), "receivables": D("1200.00"),
                      "stock": D("4200.00"), "total_assets": D("16400.00"),
                      "payables": D("650.00"), "loans": D("0.00"),
                      "total_liabilities": D("650.00"), "net_position": D("15750.00")}
    assert stmt.missing == ()


def test_a_stale_stock_count_is_not_known():
    facts = [known("stock_value", "4200", date(2026, 1, 20))]  # 39 days before 28 Feb
    stmt = build_statements(ledger(_february(), facts=facts), FEB)
    assert stmt.figure("balance_sheet", "stock") is None
    assert stmt.missing == ("stock_value",)
    assert stmt.value("balance_sheet", "total_assets") == D("11000.00")


def test_loans_are_missing_when_the_ledger_shows_a_loan_without_a_statement():
    stmt = build_statements(ledger([txn(date(2026, 2, 2), 1000)], obligations=[emi()]), FEB)
    assert stmt.figure("balance_sheet", "loans") is None
    assert stmt.missing == ("stock_value", "loan_outstanding")


def test_a_loan_statement_on_record_is_a_liability():
    facts = [known("loan_outstanding", "250000", date(2026, 2, 10))]
    stmt = build_statements(ledger([out(date(2026, 2, 10), 9000, C.loan_repayment)],
                                   facts=facts), FEB)
    loans = stmt.figure("balance_sheet", "loans")
    assert loans.value == D("250000.00")
    assert loans.provenance.input_fact_ids == (facts[0].id,)
    assert stmt.value("balance_sheet", "net_position") == D("1000.00") - D("250000.00")


def test_a_period_the_ledger_has_not_finished_is_partial():
    stmt = build_statements(ledger([txn(date(2026, 2, 2), 1000), txn(date(2026, 2, 14), 1)]),
                            FEB)
    assert stmt.partial and stmt.through == date(2026, 2, 14)
    quarter = build_statements(ledger([txn(date(2026, 3, 31), 5)]),
                               calendar_period(date(2026, 2, 1), Granularity.quarter))
    assert not quarter.partial and quarter.through == date(2026, 3, 31)


def test_no_statement_before_the_anchor_or_after_the_ledger():
    shop = ledger([txn(date(2026, 2, 2), 1000)], day=date(2026, 2, 1))
    with pytest.raises(NotEnoughData, match="cash balance on or before 2026-01-01"):
        build_statements(shop, month(2026, 1))
    with pytest.raises(NotEnoughData, match="transactions in 2026-03-01"):
        build_statements(shop, month(2026, 3))


def test_provenance_of_every_line():
    stmt = build_statements(ledger(_shop()), FEB)
    by_id = {line.figure.id: line.figure for line in stmt.lines()}
    for line in stmt.lines():
        prov = line.figure.provenance
        assert FORMULAS[prov.formula_id].version == prov.formula_version
        assert prov.source_row_ids, line.key
        assert prov.parameters["start"] == "2026-02-01" and prov.parameters["end"] == \
            "2026-02-28"
        for input_id in prov.input_fact_ids:  # another line of the statement, or the anchor
            assert input_id in by_id or input_id == ledger().anchor.id
    revenue = stmt.figure("pnl", "revenue").provenance
    parts = [stmt.figure("pnl", k) for k in ("cash_sales", "collections")]
    assert revenue.input_fact_ids == tuple(p.id for p in parts)
    assert set(revenue.source_row_ids) == {r for p in parts for r in p.provenance.source_row_ids}
    assert len(stmt.figure("pnl", "cash_sales").provenance.source_row_ids) == 3


def test_figure_ids_are_content_hashes():
    shop = _shop()
    first = build_statements(ledger(shop), FEB)
    again = build_statements(ledger(shop[::-1]), FEB)  # same rows, other order
    assert [line.figure.id for line in again.lines()] == \
        [line.figure.id for line in first.lines()]
    changed = build_statements(ledger([*shop, out(date(2026, 2, 20), 1, C.rent)]), FEB)
    assert changed.figure("pnl", "rent").id != first.figure("pnl", "rent").id
    assert changed.figure("pnl", "cash_sales").id == first.figure("pnl", "cash_sales").id


@pytest.mark.parametrize("sme_id", SME_IDS)
def test_closing_cash_matches_the_universe_balance(universe, sme_id):
    shop = universe_ledger(universe, sme_id)
    stmt = build_statements(shop, month(2026, 9))
    assert stmt.value("cash_flow", "closing_cash") == \
        universe.smes[sme_id].balance_on(date(2026, 9, 30)).amount
    assert stmt.data_mode is DataMode.synthetic
    assert all(line.figure.data_mode is DataMode.synthetic for line in stmt.lines())


_CATEGORIES = st.sampled_from(list(TxCategory))


@st.composite
def _ledgers(draw):
    rows = draw(st.lists(st.tuples(st.integers(0, 89), st.integers(1, 10**7), _CATEGORIES,
                                   st.booleans()), max_size=40))
    txns = [txn(START + timedelta(days=d), D(paisa) / 100, cat,
                "inflow" if inflow else "outflow") for d, paisa, cat, inflow in rows]
    docs = draw(st.lists(st.tuples(st.integers(0, 89), st.integers(1, 30), st.integers(1, 10**6),
                                   st.integers(0, 100), st.booleans()), max_size=8))
    invoices, bills = [], []
    for n, (d, term, amount, share, is_bill) in enumerate(docs):
        issue = START + timedelta(days=d)
        paid = D(amount) * share // 100
        maker = bill if is_bill else invoice
        (bills if is_bill else invoices).append(
            maker(f"D-{n}", issue, issue + timedelta(days=term), amount, paid=paid,
                  paid_date=issue + timedelta(days=term) if paid == amount else None))
    opening = draw(st.integers(-10**6, 10**8))
    return ledger(txns + [txn(START, 1)], invoices, bills, opening=str(opening))


@pytest.mark.property
@given(shop=_ledgers(), granularity=st.sampled_from([Granularity.month, Granularity.quarter]))
def test_statements_always_reconcile(shop, granularity):
    period = calendar_period(START, granularity)
    stmt = build_statements(shop, period)
    v = stmt.value
    assert v("pnl", "net_profit") + v("cash_flow", "loan_flows") + \
        v("cash_flow", "owner_flows") + v("cash_flow", "transfers") == \
        v("cash_flow", "cash_in") - v("cash_flow", "cash_out") == v("cash_flow", "net_cash_flow")
    assert v("cash_flow", "closing_cash") == v("cash_flow", "opening_cash") + \
        v("cash_flow", "net_cash_flow")
    signed = sum((t.signed_amount.amount for t in shop.transactions if t.day <= stmt.through),
                 D(0))
    assert v("cash_flow", "closing_cash") == shop.anchor.value + signed
    assert v("balance_sheet", "total_assets") == v("balance_sheet", "total_liabilities") + \
        v("balance_sheet", "net_position")
    assert v("balance_sheet", "cash") == v("cash_flow", "closing_cash")
