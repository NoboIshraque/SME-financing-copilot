"""Statements (WP-07 milestone 1; FEATURES N4): cash-basis P&L, balance-sheet-lite, cash flow.

Cash basis: income is money received, costs are money paid, in the period. Every transaction
falls in exactly one line (`line_of`), so the statements reconcile by construction:

    net_profit + loan flows + owner flows + transfers = cash_in - cash_out = net cash flow
    closing cash = opening cash + net cash flow
    total assets = total liabilities + net position

  P&L          cash_sales, collections -> revenue; purchases -> gross_profit; rent, salaries,
               utilities, fees, other_costs -> operating_expenses; + other_income ->
               operating_profit; - tax -> net_profit. A line counts its natural direction
               positive and the other one against it (a refund to a customer lowers sales).
               Loan repayments (principal and interest together), owner drawings and top-ups
               and transfers between the business's own accounts are not P&L lines.
  cash flow    opening cash, money in, money out, operating cash flow (the cash profit), loan
               flows, owner flows, transfers, net cash flow, closing cash.
  balance      at the last day of the period the ledger covers: cash, receivables, stock (only
               when a stock count is on record), payables, loans (a loan statement on record;
               0 when the ledger shows no loan at all), net position.

Detail lines with no transaction in the period are left out (their value is 0); subtotals
always appear. A figure that would need a fact that is not on record is left out and named
in `missing`. Pure: a `Ledger` in, `Statements` out.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.contracts import (
    DataMode,
    Direction,
    Fact,
    Figure,
    Period,
    Transaction,
    TxCategory,
    Unit,
)
from app.engines.analysis.figures import make_figure
from app.engines.analysis.ledger import Ledger, NotEnoughData, cite_all
from app.facts.registry import cite, outstanding_at

ZERO = Decimal(0)
IN, OUT = Direction.inflow, Direction.outflow
C = TxCategory

# (line, categories, natural direction). `other` is split by direction: other income and
# other costs. Every (category, direction) pair maps to exactly one line.
PNL_DETAIL: tuple[tuple[str, frozenset[TxCategory], Direction], ...] = (
    ("cash_sales", frozenset({C.sales}), IN),
    ("collections", frozenset({C.collection}), IN),
    ("purchases", frozenset({C.purchase, C.supplier_payment}), OUT),
    ("rent", frozenset({C.rent}), OUT),
    ("salaries", frozenset({C.salary}), OUT),
    ("utilities", frozenset({C.utility}), OUT),
    ("fees", frozenset({C.fee}), OUT),
    ("other_costs", frozenset({C.other}), OUT),
    ("other_income", frozenset({C.other}), IN),
    ("tax", frozenset({C.tax}), OUT),
)
CASH_DETAIL: tuple[tuple[str, frozenset[TxCategory], Direction], ...] = (
    ("loan_flows", frozenset({C.loan_disbursement, C.loan_repayment}), IN),
    ("owner_flows", frozenset({C.owner_topup, C.owner_draw}), IN),
    ("transfers", frozenset({C.transfer}), IN),
)
OPEX = ("rent", "salaries", "utilities", "fees", "other_costs")
_FORMULA = {**{line: f"analysis.pnl.{line}" for line, _c, _d in PNL_DETAIL},
            "loan_flows": "analysis.cf.loans", "owner_flows": "analysis.cf.owner",
            "transfers": "analysis.cf.transfers"}
_DIRECTION = {line: direction for line, _c, direction in (*PNL_DETAIL, *CASH_DETAIL)}


def line_of(category: TxCategory, direction: Direction) -> str:
    """The one statement line a transaction of this category and direction belongs to."""
    if category is C.other:
        return "other_income" if direction is IN else "other_costs"
    for line, categories, _natural in (*PNL_DETAIL, *CASH_DETAIL):
        if category in categories:
            return line
    raise ValueError(f"no statement line for {category}")  # pragma: no cover - exhaustive


def line_totals(transactions: Iterable[Transaction]
                ) -> dict[str, tuple[Decimal, list[Transaction]]]:
    """line -> (amount in its natural direction, the transactions behind it)."""
    amounts: dict[str, Decimal] = {}
    rows: dict[str, list[Transaction]] = {}
    for txn in transactions:
        line = line_of(txn.category, txn.direction)
        sign = 1 if txn.direction is _DIRECTION[line] else -1
        amounts[line] = amounts.get(line, ZERO) + sign * txn.amount.amount
        rows.setdefault(line, []).append(txn)
    return {line: (amounts[line], rows[line]) for line in amounts}


@dataclass(frozen=True)
class Line:
    key: str
    figure: Figure
    total: bool = False


@dataclass(frozen=True)
class Statements:
    tenant_id: str
    period: Period
    through: date  # the last day the statements cover (period end, or the ledger's last day)
    partial: bool  # the ledger ends before the period does
    pnl: tuple[Line, ...]
    cash_flow: tuple[Line, ...]
    balance_sheet: tuple[Line, ...]
    missing: tuple[str, ...]
    data_mode: DataMode

    def lines(self) -> tuple[Line, ...]:
        return (*self.pnl, *self.cash_flow, *self.balance_sheet)

    def figure(self, section: str, key: str) -> Figure | None:
        """A line's figure by section ('pnl', 'cash_flow', 'balance_sheet') and key."""
        for line in getattr(self, section):
            if line.key == key:
                return line.figure
        return None

    def value(self, section: str, key: str) -> Decimal:
        """A line's value; 0 for a detail line left out because nothing happened."""
        found = self.figure(section, key)
        return found.value if found is not None else ZERO


class _Builder:
    def __init__(self, ledger: Ledger, period: Period) -> None:
        self.ledger, self.period = ledger, period
        self.mode = ledger.data_mode

    def fig(self, formula_id: str, key: str, value: Decimal, *,
            inputs: Sequence[Figure | Fact] = (), rows: Sequence[str] = ()) -> Figure:
        if not inputs and not rows:  # nothing on record: the ledger since its anchor is the
            inputs = (self.ledger.anchor,)  # evidence that the amount is 0
        return make_figure(self.ledger.tenant_id, self.mode, formula_id, f"statement.{key}",
                           value, Unit.BDT, self.period, inputs=inputs, rows=rows)

    def total(self, formula_id: str, key: str, parts: Sequence[tuple[int, Figure | None]]
              ) -> Figure:
        present = [(sign, f) for sign, f in parts if f is not None]
        value = sum((sign * f.value for sign, f in present), ZERO)
        return self.fig(formula_id, key, value, inputs=[f for _s, f in present])


def build_statements(ledger: Ledger, period: Period) -> Statements:
    """The three statements for `period` (any length: a month, a quarter, a year)."""
    as_of = ledger.as_of
    if period.start > as_of:
        raise NotEnoughData(f"transactions in {period.start.isoformat()}"
                            f"..{period.end.isoformat()}")
    through = min(period.end, as_of)
    b = _Builder(ledger, period)
    txns = ledger.between(period.start, through)
    totals = line_totals(txns)
    detail: dict[str, Figure] = {}
    for line, (amount, rows) in totals.items():
        detail[line] = b.fig(_FORMULA[line], line, amount, rows=cite_all(rows))

    # ---- P&L
    revenue = b.total("analysis.pnl.revenue", "revenue",
                      [(1, detail.get("cash_sales")), (1, detail.get("collections"))])
    gross = b.total("analysis.pnl.gross_profit", "gross_profit",
                    [(1, revenue), (-1, detail.get("purchases"))])
    opex = b.total("analysis.pnl.operating_expenses", "operating_expenses",
                   [(1, detail.get(k)) for k in OPEX])
    operating = b.total("analysis.pnl.operating_profit", "operating_profit",
                        [(1, gross), (1, detail.get("other_income")), (-1, opex)])
    net = b.total("analysis.pnl.net_profit", "net_profit",
                  [(1, operating), (-1, detail.get("tax"))])

    def present(*keys: str) -> list[Line]:
        return [Line(k, detail[k]) for k in keys if k in detail]

    pnl = (*present("cash_sales", "collections"), Line("revenue", revenue, True),
           *present("purchases"), Line("gross_profit", gross, True), *present(*OPEX),
           Line("operating_expenses", opex, True), *present("other_income"),
           Line("operating_profit", operating, True), *present("tax"),
           Line("net_profit", net, True))

    # ---- cash flow
    opening_value, before = ledger.cash_at_start(period.start)
    opening = b.fig("analysis.cf.opening_cash", "opening_cash", opening_value,
                    inputs=(ledger.anchor,), rows=cite_all(before))
    ins = [t for t in txns if t.direction is IN]
    outs = [t for t in txns if t.direction is OUT]
    cash_in = b.fig("analysis.cf.cash_in", "cash_in",
                    sum((t.amount.amount for t in ins), ZERO), rows=cite_all(ins))
    cash_out = b.fig("analysis.cf.cash_out", "cash_out",
                     sum((t.amount.amount for t in outs), ZERO), rows=cite_all(outs))
    op_cash = b.fig("analysis.cf.operating", "operating_cash_flow", net.value, inputs=(net,))
    if "transfers" in detail and detail["transfers"].value == 0:
        del detail["transfers"]  # money moved between own accounts: no effect on the total
    net_flow = b.total("analysis.cf.net_cash_flow", "net_cash_flow",
                       [(1, op_cash), *((1, detail.get(k)) for k, _c, _d in CASH_DETAIL)])
    if net_flow.value != cash_in.value - cash_out.value:  # pragma: no cover - by construction
        raise AssertionError("statement lines do not reconcile with money in and out")
    closing = b.total("analysis.cf.closing_cash", "closing_cash",
                      [(1, opening), (1, net_flow)])
    cash_flow = (Line("opening_cash", opening), Line("cash_in", cash_in),
                 Line("cash_out", cash_out), Line("operating_cash_flow", op_cash),
                 *present("loan_flows", "owner_flows", "transfers"),
                 Line("net_cash_flow", net_flow, True), Line("closing_cash", closing, True))

    # ---- balance sheet lite, on `through`
    missing: list[str] = []
    cash = b.fig("analysis.bs.cash", "cash", closing.value, inputs=(closing,))
    receivables = _open(b, "analysis.bs.receivables", "receivables", ledger.invoices, through)
    payables = _open(b, "analysis.bs.payables", "payables", ledger.bills, through)
    stock = None
    if (counted := ledger.known("stock_value", through)) is not None:
        stock = b.fig("analysis.bs.stock", "stock", counted.value, inputs=(counted,))
    else:
        missing.append("stock_value")
    loans = None
    if (statement := ledger.known("loan_outstanding", through)) is not None:
        loans = b.fig("analysis.bs.loans", "loans", statement.value, inputs=(statement,))
    elif not ledger.has_loan_activity(through):
        loans = b.fig("analysis.bs.loans", "loans", ZERO, inputs=(ledger.anchor,))
    else:
        missing.append("loan_outstanding")
    assets = b.total("analysis.bs.total_assets", "total_assets",
                     [(1, cash), (1, receivables), (1, stock)])
    liabilities = b.total("analysis.bs.total_liabilities", "total_liabilities",
                          [(1, payables), (1, loans)])
    position = b.total("analysis.bs.net_position", "net_position",
                       [(1, assets), (-1, liabilities)])
    balance = (Line("cash", cash), Line("receivables", receivables),
               *([Line("stock", stock)] if stock else []), Line("total_assets", assets, True),
               Line("payables", payables), *([Line("loans", loans)] if loans else []),
               Line("total_liabilities", liabilities, True),
               Line("net_position", position, True))

    return Statements(tenant_id=ledger.tenant_id, period=period, through=through,
                      partial=period.end > as_of, pnl=pnl, cash_flow=cash_flow,
                      balance_sheet=balance, missing=tuple(missing), data_mode=b.mode)


def _open(b: _Builder, formula_id: str, key: str, documents: Sequence, day: date) -> Figure:
    """What is still owed on `day`. Cites the documents that contribute; when none does, every
    document issued by then is the evidence that nothing is open (as WP-01 does)."""
    issued = [d for d in documents if d.issue_date <= day]
    owed = [(d, outstanding_at(d, day)) for d in issued]
    contributing = [d for d, amount in owed if amount > 0]
    return b.fig(formula_id, key, sum((amount for _d, amount in owed), ZERO),
                 rows=tuple(cite(d) for d in (contributing or issued)))
