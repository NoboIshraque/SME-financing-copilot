"""Every number the analysis engine shows, as a `Figure` with its formula and provenance (WP-07).

A figure carries the formula id and version (`FORMULAS`), its inputs (other figures of this
engine, or stored facts such as the opening-balance anchor) and the records it read
('txn:<id>', 'inv:<id>', 'bill:<id>', 'obl:<id>', 'fact:<id>'). A figure's source rows are its
own records plus the rows of its input figures; a stored fact is cited as one row, because its
own explanation already lists its records. The period and any other parameters travel in
`provenance.parameters`, so the API can record each figure as a fact for `/explain`.
Figure ids are content hashes: the same inputs, in any order, always give the same id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import DataMode, Fact, Figure, FormulaRef, Period, Provenance, Unit
from app.facts.registry import cite

ZERO = Decimal(0)
_QUANTUM = {Unit.BDT: Decimal("0.01"), Unit.USD: Decimal("0.01"), Unit.CNY: Decimal("0.01"),
            Unit.probability: Decimal("0.0001"), Unit.ratio: Decimal("0.01"),
            Unit.percent: Decimal("0.1"), Unit.days: Decimal("0.1"), Unit.count: Decimal(1),
            Unit.score: Decimal("0.1")}


def quantize(value: Decimal, unit: Unit) -> Decimal:
    return value.quantize(_QUANTUM[unit], rounding=ROUND_HALF_UP)


_CUSTOMER = "inflows with category sales or collection (outflows of those categories, refunds, " \
            "count against them)"
_EXPRESSIONS = {
    # ---- profit and loss, cash basis (statements.py)
    "analysis.pnl.cash_sales": "sum(inflow - outflow transactions with category 'sales' in "
                               "period): money taken at the till",
    "analysis.pnl.collections": "sum(inflow - outflow transactions with category 'collection' "
                                "in period): customers paying what they owed (baki)",
    "analysis.pnl.revenue": "cash_sales + collections",
    "analysis.pnl.purchases": "sum(outflow - inflow transactions with category 'purchase' or "
                              "'supplier_payment' in period): money paid for stock",
    "analysis.pnl.gross_profit": "revenue - purchases",
    "analysis.pnl.rent": "sum(outflow - inflow transactions with category 'rent' in period)",
    "analysis.pnl.salaries": "sum(outflow - inflow transactions with category 'salary' in "
                             "period)",
    "analysis.pnl.utilities": "sum(outflow - inflow transactions with category 'utility' in "
                              "period)",
    "analysis.pnl.fees": "sum(outflow - inflow transactions with category 'fee' in period)",
    "analysis.pnl.other_costs": "sum(outflow transactions with category 'other' in period)",
    "analysis.pnl.operating_expenses": "rent + salaries + utilities + fees + other_costs",
    "analysis.pnl.other_income": "sum(inflow transactions with category 'other' in period)",
    "analysis.pnl.operating_profit": "gross_profit + other_income - operating_expenses",
    "analysis.pnl.tax": "sum(outflow - inflow transactions with category 'tax' in period)",
    "analysis.pnl.net_profit": "operating_profit - tax. Before loan interest: the ledger records "
                               "interest inside loan repayments, which are financing flows",
    # ---- cash flow (statements.py)
    "analysis.cf.opening_cash": "anchor balance + sum(signed transactions from the anchor day "
                                "to the day before the period starts)",
    "analysis.cf.cash_in": "sum(inflow transactions in period), transfers between own "
                           "accounts included",
    "analysis.cf.cash_out": "sum(outflow transactions in period), transfers between own "
                            "accounts included",
    "analysis.cf.operating": "net_profit: on a cash basis, operating cash flow is the profit",
    "analysis.cf.loans": "sum(inflow - outflow transactions with category 'loan_disbursement' "
                         "or 'loan_repayment' in period)",
    "analysis.cf.owner": "sum(inflow - outflow transactions with category 'owner_topup' or "
                         "'owner_draw' in period)",
    "analysis.cf.transfers": "sum(inflow - outflow transactions with category 'transfer' in "
                             "period); 0 when every account of the business is on record",
    "analysis.cf.net_cash_flow": "operating + loans + owner + transfers (= cash_in - cash_out)",
    "analysis.cf.closing_cash": "opening_cash + net_cash_flow",
    # ---- balance sheet lite (statements.py)
    "analysis.bs.cash": "cash, bank and mobile-money balance at the end of the day "
                        "(closing_cash of the period)",
    "analysis.bs.receivables": "sum(invoice.amount - invoice.amount_paid) over invoices issued "
                               "by the day and not written off; an invoice settled later "
                               "counts in full",
    "analysis.bs.stock": "stock_value fact counted within 31 days before the day",
    "analysis.bs.total_assets": "cash + receivables + stock (stock only when on record)",
    "analysis.bs.payables": "sum(bill.amount - bill.amount_paid) over bills issued by the day; "
                            "a bill settled later counts in full",
    "analysis.bs.loans": "loan_outstanding fact within 31 days before the day; 0 when the "
                         "ledger shows no loan disbursement, loan repayment or EMI obligation",
    "analysis.bs.total_liabilities": "payables + loans (loans only when known)",
    "analysis.bs.net_position": "total_assets - total_liabilities",
}
FORMULAS: dict[str, FormulaRef] = {
    formula_id: FormulaRef(formula_id=formula_id, version=1, expression=expression)
    for formula_id, expression in _EXPRESSIONS.items()
}


def period_params(period: Period) -> dict[str, str]:
    return {"start": period.start.isoformat(), "end": period.end.isoformat(),
            "granularity": period.granularity.value}


def rows_of(item: Figure | Fact) -> tuple[str, ...]:
    """What citing `item` adds to a figure's source rows."""
    if isinstance(item, Figure):
        return item.provenance.source_row_ids
    return (cite(item),)


def make_figure(tenant_id: str, data_mode: DataMode, formula_id: str, label_key: str,
                value: Decimal, unit: Unit, period: Period, *,
                inputs: Iterable[Figure | Fact] = (), rows: Iterable[str] = (),
                params: Mapping[str, object] | None = None) -> Figure:
    formula = FORMULAS[formula_id]
    used = tuple(inputs)
    source_rows = tuple(sorted({*rows, *(r for item in used for r in rows_of(item))}))
    parameters = {**period_params(period), **{k: str(v) for k, v in (params or {}).items()}}
    input_ids = tuple(dict.fromkeys(item.id for item in used))
    value = quantize(value, unit)
    key = json.dumps([tenant_id, formula_id, formula.version, label_key, str(value), unit.value,
                      parameters, list(input_ids), list(source_rows)], sort_keys=True)
    return Figure(
        id="an_" + hashlib.sha256(key.encode()).hexdigest()[:24], label_key=label_key,
        value=value, unit=unit, data_mode=data_mode,
        provenance=Provenance(formula_id=formula_id, formula_version=formula.version,
                              input_fact_ids=input_ids, source_row_ids=source_rows,
                              parameters=parameters))
