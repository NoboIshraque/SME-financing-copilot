"""Provenance graph (WP-01 milestone 3).

`compute()` evaluates a registered metric and stores the result as a `Fact` whose provenance
names the formula version, the input facts and every source row underneath them (the closure,
not just the direct inputs). `explain()` walks that graph back for a figure or fact id.

    fact = compute(store, "sme_grocery", "dso", period)
    figure = record_figure(store, fact, "receivables.dso")
    explain(store, figure.id, Role.owner)     # formula, inputs with values, source rows
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime

from app.contracts import (
    DataMode,
    ExplainedInput,
    Explanation,
    Fact,
    Figure,
    FormulaRef,
    Period,
    Provenance,
    Role,
)
from app.facts.masking import SourceRowMasker, get_masker
from app.facts.registry import (
    REGISTRY,
    LedgerInputs,
    MetricDefinition,
    MetricRegistry,
    NotComputable,
)
from app.facts.seed import INITIAL_BALANCE
from app.facts.store import FactNotFound, FactStore, fact_id

RAW_FORMULA = FormulaRef(formula_id="raw.source_row", version=1,
                         expression="value read directly from its source row")
# Most cautious first: a figure built from any synthetic input is labelled synthetic.
_MODE_PRIORITY = (DataMode.synthetic, DataMode.real_anonymised, DataMode.public, DataMode.live)


def combined_data_mode(modes: Iterable[DataMode]) -> DataMode:
    present = set(modes)
    for mode in _MODE_PRIORITY:
        if mode in present:
            return mode
    raise NotComputable("no inputs to take a data mode from")


def _dedupe(rows: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(rows))


def _source_rows(fact: Fact) -> tuple[str, ...]:
    return fact.provenance.source_row_ids if fact.provenance is not None else fact.source_refs


def _initial_balance(store: FactStore, tenant_id: str, period: Period) -> Fact | None:
    known = [f for f in store.facts(tenant_id, INITIAL_BALANCE) if f.period.start <= period.start]
    return known[-1] if known else None


def _ledger_inputs(store: FactStore, tenant_id: str, period: Period,
                   entity_token: str | None) -> LedgerInputs:
    txns = store.transactions(tenant_id, end=period.end)
    invoices = store.invoices(tenant_id, issued_by=period.end)
    bills = store.bills(tenant_id, issued_by=period.end)
    if entity_token is not None:
        txns = [t for t in txns if t.counterparty_token == entity_token]
        invoices = [i for i in invoices if i.counterparty_token == entity_token]
        bills = [b for b in bills if b.counterparty_token == entity_token]
    return LedgerInputs(period=period, transactions=tuple(txns), invoices=tuple(invoices),
                        bills=tuple(bills),
                        initial_balance=_initial_balance(store, tenant_id, period))


def compute(
    store: FactStore,
    tenant_id: str,
    metric: str,
    period: Period,
    entity_token: str | None = None,
    *,
    version: int | None = None,
    registry: MetricRegistry = REGISTRY,
    now: datetime | None = None,
) -> Fact:
    """Compute `metric` from the ledger, store it with full provenance and return it.

    Raises `NotComputable` instead of guessing when the data cannot support a figure (no
    source rows, a zero denominator, a metric that has no meaning per entity).
    """
    definition = registry.get(metric, version)
    now = now or datetime.now(UTC)
    if entity_token is not None and not definition.entity_scoped:
        raise NotComputable(f"{metric} is not defined per counterparty")
    store.put_formula(definition.formula)

    if definition.from_ledger is not None:
        data = _ledger_inputs(store, tenant_id, period, entity_token)
        result = definition.compute_ledger(data)
        value, inputs = result.value, result.input_facts
        rows = _dedupe(result.source_refs)
        used = set(rows)
        modes = [t.data_mode for t in data.transactions if t.source_ref in used]
        modes += [d.data_mode for d in (*data.invoices, *data.bills) if d.source_ref in used]
        modes += [f.data_mode for f in inputs]
    else:
        inputs = tuple(
            compute(store, tenant_id, name, period, entity_token, registry=registry, now=now)
            for name in definition.inputs
        )
        value = definition.compute_derived({f.metric: f.value for f in inputs}, period)
        rows = _dedupe(row for f in inputs for row in _source_rows(f))
        modes = [f.data_mode for f in inputs]

    if not rows:
        raise NotComputable(f"{metric}: no source rows for {period.start}..{period.end}")
    return _store_fact(store, definition, tenant_id, period, entity_token, value, inputs, rows,
                       combined_data_mode(modes), now)


def _store_fact(store: FactStore, definition: MetricDefinition, tenant_id: str, period: Period,
                entity_token: str | None, value, inputs: tuple[Fact, ...],
                rows: tuple[str, ...], mode: DataMode, now: datetime) -> Fact:
    fid = fact_id(tenant_id, definition.metric, period, entity_token, definition.version,
                  value, rows)
    try:
        return store.get_fact(fid)  # content-addressed: same id means same figure
    except FactNotFound:
        pass
    provenance = Provenance(formula_id=definition.formula_id, formula_version=definition.version,
                            input_fact_ids=tuple(f.id for f in inputs), source_row_ids=rows)
    return store.put_fact(
        Fact(id=fid, tenant_id=tenant_id, metric=definition.metric, value=value,
             unit=definition.unit, period=period, entity_token=entity_token,
             provenance=provenance, source_refs=rows, data_mode=mode, computed_at=now)
    )


def record_figure(store: FactStore, fact: Fact, label_key: str) -> Figure:
    """Turn a fact into a user-facing figure (what a screen shows and a click explains)."""
    if fact.provenance is None:
        provenance = Provenance(formula_id=RAW_FORMULA.formula_id,
                                formula_version=RAW_FORMULA.version,
                                input_fact_ids=(fact.id,), source_row_ids=fact.source_refs)
        store.put_formula(RAW_FORMULA)
    else:
        provenance = fact.provenance
    digest = hashlib.sha256(f"{fact.id}|{label_key}".encode()).hexdigest()[:24]
    figure = Figure(id=f"fig_{digest}", label_key=label_key, value=fact.value, unit=fact.unit,
                    provenance=provenance, data_mode=fact.data_mode)
    return store.put_figure(fact.tenant_id, figure)


def explain(
    store: FactStore,
    figure_id: str,
    role: Role,
    masker: SourceRowMasker | None = None,
) -> Explanation:
    """Formula, inputs with their values, and the (masked per role) source rows of a figure.

    `figure_id` may name a stored `Figure` or a `Fact`. The masking hook is called on every
    explanation, for every role.
    """
    try:
        tenant_id, figure = store.get_figure(figure_id)
        value, unit, provenance = figure.value, figure.unit, figure.provenance
    except FactNotFound:
        fact = store.get_fact(figure_id)
        tenant_id, value, unit = fact.tenant_id, fact.value, fact.unit
        provenance = fact.provenance
        if provenance is None:
            store.put_formula(RAW_FORMULA)
            provenance = Provenance(formula_id=RAW_FORMULA.formula_id,
                                    formula_version=RAW_FORMULA.version,
                                    source_row_ids=fact.source_refs)

    formula = store.formula(provenance.formula_id, provenance.formula_version)
    inputs = []
    for input_id in provenance.input_fact_ids:
        source = store.get_fact(input_id)
        if source.tenant_id != tenant_id:
            raise FactNotFound(f"input {input_id} belongs to another tenant")
        inputs.append(ExplainedInput(fact_id=source.id, metric=source.metric,
                                     value=source.value, unit=source.unit))
    rows, masked = (masker or get_masker())(tenant_id, provenance.source_row_ids, role)
    return Explanation(figure_id=figure_id, formula=formula, value=value, unit=unit,
                       inputs=tuple(inputs), source_rows=rows, masked=masked)
