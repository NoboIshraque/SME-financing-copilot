"""Ratios with formulas and provenance (WP-07 milestone 2; FEATURES N4).

Each ratio is read from the period's statements (`statements.py`) and a few extra inputs, all
of them figures, so a lender can click from the ratio to the transactions behind it:

  gross_margin, net_margin    gross / net profit over revenue, percent (cash basis)
  current_ratio, quick_ratio  (cash + receivables [+ stock]) / current liabilities, where
                              current liabilities = payables + EMI instalments due in the next
                              365 days (the ledger has no split of loans by maturity)
  dscr                        net profit (cash available for debt service) / loan repayments
  interest_cover              operating profit / interest expense (an interest fact on record)
  dso, dpo, dio               receivables / credit sales, payables / credit purchases, stock /
                              purchases, each x days covered (credit basis, as WP-01 defines)
  cash_conversion_cycle       dso + dio - dpo
  burn, runway                net cash used per 30 days before new loans and owner money;
                              cash / burn x 30 days
  top_customer_share          receipts from the biggest credit customer / revenue, percent.
                              Walk-in till sales count in revenue, never as one customer.

A ratio that cannot be computed honestly (zero denominator, a fact not on record, no debt) has
value None and an `interpretation_key` saying why: 'ratio.missing.<fact>' or
'ratio.not_applicable.<reason>'. Interpretations of computed values come from named
thresholds below, never from a model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.contracts import (
    Direction,
    Fact,
    Figure,
    ObligationKind,
    Period,
    Ratio,
    TxCategory,
    Unit,
)
from app.engines.analysis.figures import make_figure, provenance_for
from app.engines.analysis.ledger import Ledger
from app.engines.analysis.statements import Statements, build_statements
from app.engines.cash.baseline import obligation_days
from app.facts.registry import cite

ZERO, HUNDRED, THIRTY = Decimal(0), Decimal(100), Decimal(30)
DSCR_LENDER_MINIMUM = Decimal("1.25")  # the usual floor in Bangladeshi bank loan covenants
CURRENT_COVER = Decimal(1)  # current assets at least equal to what falls due within a year
CONCENTRATED_PERCENT = Decimal(25)  # one customer paying a quarter of revenue or more
RUNWAY_SHORT_DAYS = Decimal(90)
NEXT_YEAR_DAYS = 365
CUSTOMER_CATEGORIES = frozenset({TxCategory.sales, TxCategory.collection})
NAMES = ("gross_margin", "net_margin", "current_ratio", "quick_ratio", "dscr", "interest_cover",
         "dso", "dpo", "dio", "cash_conversion_cycle", "burn", "runway", "top_customer_share")


@dataclass(frozen=True)
class RatioSet:
    period: Period
    ratios: tuple[Ratio, ...]  # in NAMES order
    figures: tuple[Figure, ...]  # every figure the ratios cite, inputs before what uses them
    statements: Statements

    def get(self, name: str) -> Ratio:
        return next(r for r in self.ratios if r.name == name)


class _Builder:
    def __init__(self, ledger: Ledger, stmt: Statements) -> None:
        self.ledger, self.stmt, self.period = ledger, stmt, stmt.period
        self.figures: dict[str, Figure] = {line.figure.id: line.figure for line in stmt.lines()}
        self.ratios: list[Ratio] = []
        self.by_name: dict[str, Figure] = {}  # the figure of each computed ratio

    def line(self, section: str, key: str) -> Figure | None:
        return self.stmt.figure(section, key)

    def fig(self, formula_id: str, label_key: str, value: Decimal, unit: Unit = Unit.BDT, *,
            inputs: Sequence[Figure | Fact] = (), rows: Sequence[str] = (),
            params: dict[str, object] | None = None) -> Figure:
        if not inputs and not rows:
            inputs = (self.ledger.anchor,)  # nothing on record since the anchor: 0
        figure = make_figure(self.ledger.tenant_id, self.stmt.data_mode, formula_id, label_key,
                             value, unit, self.period, inputs=inputs, rows=rows, params=params)
        self.figures[figure.id] = figure
        return figure

    def ratio(self, name: str, unit: Unit, value: Decimal | None,
              inputs: Sequence[Figure | Fact | None], interpretation: str | None,
              benchmark: Decimal | None = None) -> Ratio:
        used = [i for i in inputs if i is not None]
        formula_id = f"analysis.ratio.{name}"
        if value is None:
            provenance = provenance_for(formula_id, self.period, used)
        else:
            figure = self.fig(formula_id, f"ratio.{name}", value, unit, inputs=used)
            value, provenance = figure.value, figure.provenance
            self.by_name[name] = figure
        ratio = Ratio(name=name, value=value, unit=unit, period=self.period,
                      provenance=provenance, benchmark=benchmark,
                      interpretation_key=interpretation)
        self.ratios.append(ratio)
        return ratio


def _share(numerator: Decimal, denominator: Decimal) -> Decimal:
    return numerator / denominator * HUNDRED


def compute_ratios(ledger: Ledger, period: Period, stmt: Statements | None = None) -> RatioSet:
    """Every ratio for `period`, from its statements (built here unless given)."""
    stmt = stmt or build_statements(ledger, period)
    b = _Builder(ledger, stmt)
    start, through = period.start, stmt.through
    days = Decimal((through - start).days + 1)
    txns = ledger.between(start, through)
    v = stmt.value

    # ---- margins
    revenue, gross, net = (b.line("pnl", k) for k in ("revenue", "gross_profit", "net_profit"))
    no_revenue = "ratio.not_applicable.no_revenue"
    for name, profit in (("gross_margin", gross), ("net_margin", net)):
        if revenue.value <= 0:
            b.ratio(name, Unit.percent, None, [revenue, profit], no_revenue)
        else:
            value = _share(profit.value, revenue.value)
            b.ratio(name, Unit.percent, value, [profit, revenue],
                    "interpretation.loss_making" if value < 0 else None)

    # ---- liquidity
    cash, receivables, payables = (b.line("balance_sheet", k)
                                   for k in ("cash", "receivables", "payables"))
    stock = b.line("balance_sheet", "stock")
    emis = [o for o in ledger.obligations if o.kind is ObligationKind.emi]
    due = [(o, d) for o in emis for d in obligation_days(
        o, through + timedelta(days=1), through + timedelta(days=NEXT_YEAR_DAYS))]
    instalments = b.fig("analysis.input.instalments_next_year", "ratio.instalments_next_year",
                        sum((o.amount.amount for o, _d in due), ZERO),
                        rows=tuple(f"obl:{o.id}" for o in emis),
                        params={"through": through.isoformat()})
    current = b.fig("analysis.input.current_liabilities", "ratio.current_liabilities",
                    payables.value + instalments.value, inputs=(payables, instalments))
    quick_assets = cash.value + receivables.value
    if current.value <= 0:
        reason = "ratio.not_applicable.no_current_liabilities"
        b.ratio("current_ratio", Unit.ratio, None, [cash, receivables, stock, current], reason)
        b.ratio("quick_ratio", Unit.ratio, None, [cash, receivables, current], reason)
    else:
        if stock is None:
            b.ratio("current_ratio", Unit.ratio, None, [cash, receivables, current],
                    "ratio.missing.stock_value")
        else:
            value = (quick_assets + stock.value) / current.value
            b.ratio("current_ratio", Unit.ratio, value, [cash, receivables, stock, current],
                    _cover(value), CURRENT_COVER)
        value = quick_assets / current.value
        b.ratio("quick_ratio", Unit.ratio, value, [cash, receivables, current], _cover(value),
                CURRENT_COVER)

    # ---- debt
    repayments = [t for t in txns if t.category is TxCategory.loan_repayment
                  and t.direction is Direction.outflow]
    debt_service = b.fig("analysis.input.debt_service", "ratio.debt_service",
                         sum((t.amount.amount for t in repayments), ZERO),
                         rows=tuple(cite(t) for t in repayments))
    has_debt = ledger.has_loan_activity(through)
    if debt_service.value <= 0:
        reason = "interpretation.no_debt" if not has_debt else \
            "ratio.not_applicable.no_repayment_in_period"
        b.ratio("dscr", Unit.ratio, None, [net, debt_service], reason, DSCR_LENDER_MINIMUM)
    else:
        value = net.value / debt_service.value
        b.ratio("dscr", Unit.ratio, value, [net, debt_service], _dscr(value),
                DSCR_LENDER_MINIMUM)
    operating = b.line("pnl", "operating_profit")
    interest = ledger.in_period("interest_expense", period)
    if not has_debt:
        b.ratio("interest_cover", Unit.ratio, None, [operating], "interpretation.no_debt")
    elif interest is None:
        b.ratio("interest_cover", Unit.ratio, None, [operating],
                "ratio.missing.interest_expense")
    elif interest.value <= 0:
        b.ratio("interest_cover", Unit.ratio, None, [operating, interest],
                "ratio.not_applicable.no_interest")
    else:
        value = operating.value / interest.value
        b.ratio("interest_cover", Unit.ratio, value, [operating, interest],
                "interpretation.interest_not_covered" if value < 1 else None)

    # ---- working capital, credit basis
    invoices = [i for i in ledger.invoices if start <= i.issue_date <= through]
    bills = [x for x in ledger.bills if start <= x.issue_date <= through]
    credit_sales = b.fig("analysis.input.credit_sales", "ratio.credit_sales",
                         sum((i.amount.amount for i in invoices), ZERO),
                         rows=tuple(cite(i) for i in invoices))
    credit_purchases = b.fig("analysis.input.credit_purchases", "ratio.credit_purchases",
                             sum((x.amount.amount for x in bills), ZERO),
                             rows=tuple(cite(x) for x in bills))
    dso = _days(b, "dso", receivables, credit_sales, days, "ratio.not_applicable.no_credit_sales")
    dpo = _days(b, "dpo", payables, credit_purchases, days,
                "ratio.not_applicable.no_credit_purchases")
    purchases = b.line("pnl", "purchases")
    if stock is None:
        dio = b.ratio("dio", Unit.days, None, [purchases], "ratio.missing.stock_value")
    else:
        dio = _days(b, "dio", stock, purchases, days, "ratio.not_applicable.no_purchases")
    parts = (dso, dio, dpo)
    if all(p.value is not None for p in parts):
        b.ratio("cash_conversion_cycle", Unit.days, dso.value + dio.value - dpo.value,
                [b.by_name[p.name] for p in parts], None)
    else:
        first_missing = next(p for p in parts if p.value is None)
        b.ratio("cash_conversion_cycle", Unit.days, None,
                [b.by_name[p.name] for p in parts if p.value is not None],
                first_missing.interpretation_key)

    # ---- burn and runway
    funding = [t for t in txns if t.direction is Direction.inflow
               and t.category in (TxCategory.loan_disbursement, TxCategory.owner_topup)]
    new_money = b.fig("analysis.input.new_financing", "ratio.new_financing",
                      sum((t.amount.amount for t in funding), ZERO),
                      rows=tuple(cite(t) for t in funding))
    net_flow = b.line("cash_flow", "net_cash_flow")
    used_up = new_money.value - v("cash_flow", "net_cash_flow")
    burn = b.ratio("burn", Unit.BDT, max(used_up, ZERO) * THIRTY / days, [new_money, net_flow],
                   "interpretation.not_burning" if used_up <= 0 else None)
    if burn.value is not None and burn.value > 0:
        runway = cash.value / burn.value * THIRTY
        b.ratio("runway", Unit.days, runway, [cash, b.by_name["burn"]],
                "interpretation.runway_short" if runway < RUNWAY_SHORT_DAYS else None)
    else:
        b.ratio("runway", Unit.days, None, [cash, new_money, net_flow],
                "ratio.not_applicable.not_burning")

    # ---- concentration
    customers = {i.counterparty_token for i in ledger.invoices if i.issue_date <= through}
    receipts: dict[str, Decimal] = {}
    paid_by: dict[str, list] = {}
    for t in txns:
        if t.category in CUSTOMER_CATEGORIES and t.counterparty_token in customers:
            token = t.counterparty_token
            receipts[token] = receipts.get(token, ZERO) + t.signed_amount.amount
            paid_by.setdefault(token, []).append(t)
    if not customers:
        b.ratio("top_customer_share", Unit.percent, None, [revenue],
                "ratio.not_applicable.no_credit_customers")
    else:
        top = min(receipts, key=lambda k: (-receipts[k], k)) if receipts else None
        amount, rows = (receipts[top], paid_by[top]) if top else (ZERO, [])
        top_fig = b.fig("analysis.input.top_customer_receipts", "ratio.top_customer_receipts",
                        amount, rows=tuple(cite(t) for t in rows),
                        params={"counterparty_token": top or "none"})
        if revenue.value <= 0:
            b.ratio("top_customer_share", Unit.percent, None, [top_fig, revenue], no_revenue)
        else:
            value = _share(top_fig.value, revenue.value)
            b.ratio("top_customer_share", Unit.percent, value, [top_fig, revenue],
                    "interpretation.concentrated" if value >= CONCENTRATED_PERCENT else None)

    order = {name: n for n, name in enumerate(NAMES)}
    return RatioSet(period=period, ratios=tuple(sorted(b.ratios, key=lambda r: order[r.name])),
                    figures=tuple(b.figures.values()), statements=stmt)


def _days(b: _Builder, name: str, balance: Figure, flow: Figure | None, days: Decimal,
          reason: str) -> Ratio:
    if flow is None or flow.value <= 0:
        return b.ratio(name, Unit.days, None, [balance, flow], reason)
    return b.ratio(name, Unit.days, balance.value / flow.value * days, [balance, flow], None)


def _cover(value: Decimal) -> str:
    return "interpretation.covers_short_term" if value >= CURRENT_COVER \
        else "interpretation.short_of_current_cover"


def _dscr(value: Decimal) -> str:
    if value < 1:
        return "interpretation.dscr.cannot_cover"
    if value < DSCR_LENDER_MINIMUM:
        return "interpretation.dscr.below_lender_minimum"
    return "interpretation.dscr.comfortable"
