"""Metric registry (WP-01 milestone 2).

Every metric the product shows is a named, versioned definition: a `formula_id`, a
human-readable expression, a unit and a pure function. There are two kinds:

- ledger metrics read typed ledger records (`LedgerInputs`) and return the value together with
  the source rows it used;
- derived metrics combine other metrics' values (`inputs`) and never see raw rows.

A definition, once released, never changes: a new rule is a new `version`, so figures computed
under the old version keep explaining themselves with the old expression.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import (
    Bill,
    Direction,
    DocumentStatus,
    Fact,
    FormulaRef,
    Invoice,
    Period,
    Transaction,
    TxCategory,
    Unit,
)

ZERO = Decimal(0)
OPERATING_EXPENSE_CATEGORIES = frozenset(
    {TxCategory.rent, TxCategory.salary, TxCategory.utility, TxCategory.fee}
)
_QUANTUM = {
    Unit.BDT: Decimal("0.01"),
    Unit.USD: Decimal("0.01"),
    Unit.CNY: Decimal("0.01"),
    Unit.ratio: Decimal("0.0001"),
    Unit.percent: Decimal("0.01"),
    Unit.days: Decimal("0.1"),
    Unit.count: Decimal("1"),
    Unit.probability: Decimal("0.0001"),
    Unit.score: Decimal("0.1"),
}


class NotComputable(ValueError):
    """The metric cannot be computed honestly from the data available (abstain, don't guess)."""


class UnknownMetric(KeyError):
    """No definition with exactly this metric name (and version)."""


def quantize(value: Decimal, unit: Unit) -> Decimal:
    return value.quantize(_QUANTUM[unit], rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LedgerInputs:
    """Typed records a ledger metric may read. Records are already scoped to the tenant (and
    entity, if any) and to everything on or before `period.end`."""

    period: Period
    transactions: tuple[Transaction, ...] = ()
    invoices: tuple[Invoice, ...] = ()
    bills: tuple[Bill, ...] = ()
    initial_balance: Fact | None = None


@dataclass(frozen=True)
class LedgerResult:
    value: Decimal
    source_refs: tuple[str, ...]
    input_facts: tuple[Fact, ...] = ()


LedgerFn = Callable[[LedgerInputs], LedgerResult]
DerivedFn = Callable[[Mapping[str, Decimal], Period], Decimal]


@dataclass(frozen=True)
class MetricDefinition:
    metric: str
    formula_id: str
    version: int
    expression: str
    unit: Unit
    from_ledger: LedgerFn | None = None
    from_inputs: DerivedFn | None = None
    inputs: tuple[str, ...] = ()
    entity_scoped: bool = True

    def __post_init__(self) -> None:
        if (self.from_ledger is None) == (self.from_inputs is None):
            raise ValueError(f"{self.metric}: define exactly one of from_ledger / from_inputs")
        if self.from_inputs is not None and not self.inputs:
            raise ValueError(f"{self.metric}: a derived metric needs input metrics")
        if self.from_ledger is not None and self.inputs:
            raise ValueError(f"{self.metric}: a ledger metric reads records, not input metrics")
        FormulaRef(formula_id=self.formula_id, version=self.version, expression=self.expression)

    @property
    def formula(self) -> FormulaRef:
        return FormulaRef(formula_id=self.formula_id, version=self.version,
                          expression=self.expression)

    def compute_ledger(self, data: LedgerInputs) -> LedgerResult:
        if self.from_ledger is None:
            raise TypeError(f"{self.metric} is a derived metric")
        result = self.from_ledger(data)
        return LedgerResult(quantize(result.value, self.unit), result.source_refs,
                            result.input_facts)

    def compute_derived(self, values: Mapping[str, Decimal], period: Period) -> Decimal:
        if self.from_inputs is None:
            raise TypeError(f"{self.metric} is a ledger metric")
        missing = [name for name in self.inputs if name not in values]
        if missing:
            raise NotComputable(f"{self.metric}: missing inputs {missing}")
        return quantize(self.from_inputs({k: values[k] for k in self.inputs}, period), self.unit)


@dataclass
class MetricRegistry:
    _definitions: dict[tuple[str, int], MetricDefinition] = field(default_factory=dict)

    def register(self, definition: MetricDefinition) -> MetricDefinition:
        key = (definition.metric, definition.version)
        if key in self._definitions:
            raise ValueError(f"{definition.metric} v{definition.version} is already registered")
        for other in self._definitions.values():
            if other.formula_id == definition.formula_id and other.metric != definition.metric:
                raise ValueError(f"formula_id {definition.formula_id} belongs to {other.metric}")
            if other.metric == definition.metric and other.formula_id != definition.formula_id:
                raise ValueError(f"{definition.metric} already uses formula_id {other.formula_id}")
        for name in definition.inputs:
            if name not in self.metrics():
                raise ValueError(f"{definition.metric}: input {name!r} is not registered")
        self._definitions[key] = definition
        return definition

    def metrics(self) -> list[str]:
        return sorted({metric for metric, _ in self._definitions})

    def versions(self, metric: str) -> list[int]:
        return sorted(v for m, v in self._definitions if m == metric)

    def get(self, metric: str, version: int | None = None) -> MetricDefinition:
        """Exact lookup; without `version`, the latest one."""
        versions = self.versions(metric)
        if not versions:
            raise UnknownMetric(metric)
        chosen = versions[-1] if version is None else version
        try:
            return self._definitions[(metric, chosen)]
        except KeyError:
            raise UnknownMetric(f"{metric} v{version}") from None

    def copy(self) -> MetricRegistry:
        return MetricRegistry(dict(self._definitions))


# ---------------------------------------------------------------- ledger metric functions


def _in_period(txns: Iterable[Transaction], period: Period) -> list[Transaction]:
    return [t for t in txns if period.contains(t.day)]


def _sum_txns(txns: list[Transaction]) -> LedgerResult:
    return LedgerResult(sum((t.amount.amount for t in txns), ZERO),
                        tuple(t.source_ref for t in txns))


def _flow(direction: Direction, categories: frozenset[TxCategory] | None = None) -> LedgerFn:
    def compute(data: LedgerInputs) -> LedgerResult:
        rows = [t for t in _in_period(data.transactions, data.period)
                if t.direction is direction and (categories is None or t.category in categories)]
        return _sum_txns(rows)

    return compute


def _credit_sales(data: LedgerInputs) -> LedgerResult:
    docs = [i for i in data.invoices if data.period.contains(i.issue_date)]
    return LedgerResult(sum((i.amount.amount for i in docs), ZERO),
                        tuple(i.source_ref for i in docs))


def _purchases(data: LedgerInputs) -> LedgerResult:
    cash = [t for t in _in_period(data.transactions, data.period)
            if t.direction is Direction.outflow and t.category is TxCategory.purchase]
    billed = [b for b in data.bills if data.period.contains(b.issue_date)]
    value = sum((t.amount.amount for t in cash), ZERO) + sum((b.amount.amount for b in billed),
                                                             ZERO)
    return LedgerResult(value, tuple(t.source_ref for t in cash) +
                        tuple(b.source_ref for b in billed))


def outstanding_at(doc: Invoice | Bill, day: date) -> Decimal:
    """What was still owed on a document at the end of `day` (0 if issued later).

    A document settled after `day` counts in full; payments without a date are taken as
    already made, the only reading the register supports.
    """
    if doc.issue_date > day or doc.status is DocumentStatus.written_off:
        return ZERO
    if doc.paid_date is not None and doc.paid_date > day:
        return doc.amount.amount
    return doc.outstanding.amount


def _open_documents(attr: str) -> LedgerFn:
    def compute(data: LedgerInputs) -> LedgerResult:
        docs = [d for d in getattr(data, attr) if d.issue_date <= data.period.end]
        return LedgerResult(sum((outstanding_at(d, data.period.end) for d in docs), ZERO),
                            tuple(d.source_ref for d in docs))

    return compute


def _opening_balance(data: LedgerInputs) -> LedgerResult:
    initial = data.initial_balance
    if initial is None:
        raise NotComputable("opening_balance needs an initial_balance fact")
    since = initial.period.start
    if data.period.start < since:
        raise NotComputable("period starts before the initial balance is known")
    before = [t for t in data.transactions if since <= t.day < data.period.start]
    value = initial.value + sum((t.signed_amount.amount for t in before), ZERO)
    return LedgerResult(value, tuple(initial.source_refs) + tuple(t.source_ref for t in before),
                        (initial,))


# ---------------------------------------------------------------- derived metric functions


def _ratio(numerator: Decimal, denominator: Decimal, what: str) -> Decimal:
    if denominator == 0:
        raise NotComputable(f"{what}: denominator is zero")
    return numerator / denominator


def _gross_margin(v: Mapping[str, Decimal], _p: Period) -> Decimal:
    return _ratio(v["net_sales"] - v["purchases"], v["net_sales"], "gross_margin")


def _dso(v: Mapping[str, Decimal], p: Period) -> Decimal:
    return _ratio(v["receivables"], v["net_sales"], "dso") * p.days


def _dpo(v: Mapping[str, Decimal], p: Period) -> Decimal:
    return _ratio(v["payables"], v["purchases"], "dpo") * p.days


def build_default_registry() -> MetricRegistry:
    reg = MetricRegistry()
    bdt = Unit.BDT
    for d in (
        MetricDefinition("cash_in", "cash.cash_in", 1,
                         "sum(amount of inflow transactions in period)", bdt,
                         from_ledger=_flow(Direction.inflow)),
        MetricDefinition("cash_out", "cash.cash_out", 1,
                         "sum(amount of outflow transactions in period)", bdt,
                         from_ledger=_flow(Direction.outflow)),
        MetricDefinition("cash_sales", "sales.cash_sales", 1,
                         "sum(amount of inflow transactions with category 'sales' in period)",
                         bdt, from_ledger=_flow(Direction.inflow,
                                                frozenset({TxCategory.sales}))),
        MetricDefinition("credit_sales", "sales.credit_sales", 1,
                         "sum(amount of invoices issued in period)", bdt,
                         from_ledger=_credit_sales),
        MetricDefinition("purchases", "costs.purchases", 1,
                         "sum(outflow transactions with category 'purchase' in period) "
                         "+ sum(amount of bills issued in period)", bdt,
                         from_ledger=_purchases),
        MetricDefinition("operating_expenses", "costs.operating_expenses", 1,
                         "sum(outflow transactions with category rent, salary, utility or fee "
                         "in period)", bdt,
                         from_ledger=_flow(Direction.outflow, OPERATING_EXPENSE_CATEGORIES)),
        MetricDefinition("receivables", "receivables.open", 1,
                         "sum(invoice.amount - invoice.amount_paid) over invoices issued by "
                         "period end; an invoice settled after period end counts in full", bdt,
                         from_ledger=_open_documents("invoices")),
        MetricDefinition("payables", "payables.open", 1,
                         "sum(bill.amount - bill.amount_paid) over bills issued by period end; "
                         "a bill settled after period end counts in full", bdt,
                         from_ledger=_open_documents("bills")),
        MetricDefinition("opening_balance", "cash.opening_balance", 1,
                         "initial_balance + sum(signed transactions before period start)", bdt,
                         from_ledger=_opening_balance, entity_scoped=False),
        MetricDefinition("net_sales", "sales.net_sales", 1,
                         "cash_sales + credit_sales (no returns or discounts are recorded)", bdt,
                         inputs=("cash_sales", "credit_sales"),
                         from_inputs=lambda v, _p: v["cash_sales"] + v["credit_sales"]),
        MetricDefinition("net_cash_flow", "cash.net_cash_flow", 1, "cash_in - cash_out", bdt,
                         inputs=("cash_in", "cash_out"),
                         from_inputs=lambda v, _p: v["cash_in"] - v["cash_out"]),
        MetricDefinition("closing_balance", "cash.closing_balance", 1,
                         "opening_balance + cash_in - cash_out", bdt,
                         inputs=("opening_balance", "cash_in", "cash_out"),
                         from_inputs=lambda v, _p: v["opening_balance"] + v["cash_in"]
                         - v["cash_out"]),
        MetricDefinition("gross_profit", "analysis.gross_profit", 1, "net_sales - purchases",
                         bdt, inputs=("net_sales", "purchases"),
                         from_inputs=lambda v, _p: v["net_sales"] - v["purchases"]),
        MetricDefinition("gross_margin", "analysis.gross_margin", 1,
                         "(net_sales - purchases) / net_sales", Unit.ratio,
                         inputs=("net_sales", "purchases"), from_inputs=_gross_margin),
        MetricDefinition("dso", "receivables.dso", 1, "receivables / net_sales * days_in_period",
                         Unit.days, inputs=("receivables", "net_sales"), from_inputs=_dso),
        MetricDefinition("dpo", "payables.dpo", 1, "payables / purchases * days_in_period",
                         Unit.days, inputs=("payables", "purchases"), from_inputs=_dpo),
    ):
        reg.register(d)
    return reg


REGISTRY = build_default_registry()
