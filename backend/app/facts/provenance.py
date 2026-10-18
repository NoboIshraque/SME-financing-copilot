"""Provenance graph (WP-01 milestone 3).

`compute()` evaluates a registered metric and stores the result as a `Fact` whose provenance
names the formula version, the input facts and every record underneath them (the closure,
cited as 'txn:<id>', 'inv:<id>', 'bill:<id>' or 'fact:<id>'). `explain()` walks that graph back
for a figure or fact id, for one caller; `explain_rows()` pages through the records themselves.

    fact = compute(store, "sme_grocery", "dso", period)
    figure = record_figure(store, fact, "receivables.dso")
    explain(store, figure.id, caller)     # formula, inputs with values, masked source rows

Engines outside WP-01 record their own figures with `record_computed()`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from app.contracts import (
    Bill,
    DataMode,
    ExplainedInput,
    Explanation,
    Fact,
    Figure,
    FormulaRef,
    Invoice,
    Period,
    Principal,
    Provenance,
    Transaction,
    Unit,
)
from app.facts.masking import SourceRowMasker, get_masker, mask_record, sees_rows
from app.facts.registry import (
    REGISTRY,
    LedgerInputs,
    MetricDefinition,
    MetricRegistry,
    NotComputable,
    cite,
)
from app.facts.seed import INITIAL_BALANCE
from app.facts.store import FactNotFound, FactStore, fact_id

RAW_FORMULA = FormulaRef(formula_id="raw.source_row", version=1,
                         expression="value read directly from its source row")
# Most cautious first: a figure built from any synthetic input is labelled synthetic.
_MODE_PRIORITY = (DataMode.synthetic, DataMode.real_anonymised, DataMode.public, DataMode.live)


class ProvenanceIncomplete(ValueError):
    """A figure's formula or input facts are missing, or belong to another tenant."""


def combined_data_mode(modes: Iterable[DataMode]) -> DataMode:
    present = set(modes)
    for mode in _MODE_PRIORITY:
        if mode in present:
            return mode
    raise NotComputable("facts.no_inputs", "no inputs to take a data mode from")


def _dedupe(rows: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(rows))


def source_rows(fact: Fact) -> tuple[str, ...]:
    """Citations a fact resolves to: its provenance closure, or itself when it is raw."""
    return fact.provenance.source_row_ids if fact.provenance is not None else (cite(fact),)


# ---------------------------------------------------------------- compute


@dataclass
class _Context:
    """One top-level compute: the ledger is read once and shared by every input metric."""

    revision: int
    now: datetime
    ledger: dict[tuple[str | None, date], LedgerInputs]


def _initial_balance(store: FactStore, tenant_id: str, period: Period) -> Fact | None:
    known = [f for f in store.facts(tenant_id, INITIAL_BALANCE) if f.period.start <= period.start]
    return known[-1] if known else None


def _ledger_inputs(store: FactStore, tenant_id: str, period: Period, entity_token: str | None,
                   ctx: _Context) -> LedgerInputs:
    key = (entity_token, period.end)
    cached = ctx.ledger.get(key)
    if cached is None:
        txns = store.transactions(tenant_id, end=period.end)
        invoices = store.invoices(tenant_id, issued_by=period.end)
        bills = store.bills(tenant_id, issued_by=period.end)
        if entity_token is not None:
            txns = [t for t in txns if t.counterparty_token == entity_token]
            invoices = [i for i in invoices if i.counterparty_token == entity_token]
            bills = [b for b in bills if b.counterparty_token == entity_token]
        cached = LedgerInputs(period=period, transactions=tuple(txns), invoices=tuple(invoices),
                              bills=tuple(bills))
        ctx.ledger[key] = cached
    return LedgerInputs(period=period, transactions=cached.transactions,
                        invoices=cached.invoices, bills=cached.bills,
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
    """The current value of `metric`, computed from the ledger and stored with provenance.

    A fact already confirmed against the tenant's current ledger revision is returned as is;
    otherwise the metric is recomputed, so a figure never outlives the rows it was built on.
    Raises `NotComputable` instead of guessing when the data cannot support a figure (no
    source rows, a zero denominator, a metric that has no meaning per entity).
    """
    ctx = _Context(revision=store.revision(tenant_id), now=now or datetime.now(UTC), ledger={})
    return _compute(store, tenant_id, metric, period, entity_token, version, registry, ctx)


def _compute(store: FactStore, tenant_id: str, metric: str, period: Period,
             entity_token: str | None, version: int | None, registry: MetricRegistry,
             ctx: _Context) -> Fact:
    definition = registry.get(metric, version)
    if entity_token is not None and not definition.entity_scoped:
        raise NotComputable("facts.not_per_entity", f"{metric} is not defined per counterparty")
    try:
        return store.get_current(tenant_id, metric, period, entity_token, definition.version)
    except FactNotFound:
        pass
    store.put_formula(definition.formula)

    if definition.from_ledger is not None:
        data = _ledger_inputs(store, tenant_id, period, entity_token, ctx)
        result = definition.compute_ledger(data)
        value, inputs, rows = result.value, result.input_facts, _dedupe(result.rows)
        mode_of = {cite(r): r.data_mode for r in (*data.transactions, *data.invoices, *data.bills)}
        modes = [mode_of[r] for r in rows if r in mode_of] + [f.data_mode for f in inputs]
    else:
        inputs = tuple(
            _compute(store, tenant_id, name, period, entity_token, None, registry, ctx)
            for name in definition.inputs
        )
        value = definition.compute_derived({f.metric: f.value for f in inputs}, period)
        rows = _dedupe(row for f in inputs for row in source_rows(f))
        modes = [f.data_mode for f in inputs]

    if not rows:
        raise NotComputable("facts.no_source_rows",
                            f"{metric}: no source rows for {period.start}..{period.end}")
    return _store_fact(store, definition, tenant_id, period, entity_token, value, inputs, rows,
                       combined_data_mode(modes), ctx)


def _store_fact(store: FactStore, definition: MetricDefinition, tenant_id: str, period: Period,
                entity_token: str | None, value: Decimal, inputs: Sequence[Fact],
                rows: tuple[str, ...], mode: DataMode, ctx: _Context) -> Fact:
    fid = fact_id(tenant_id, definition.metric, period, entity_token, definition.version,
                  value, rows)
    try:
        existing = store.get_fact(fid)
    except FactNotFound:
        existing = None
    if existing is not None:  # content-addressed: same id, same figure; confirm it again
        store.touch(fid, ctx.revision)
        return existing
    provenance = Provenance(formula_id=definition.formula_id, formula_version=definition.version,
                            input_fact_ids=tuple(f.id for f in inputs), source_row_ids=rows)
    # The rows live once, in provenance; source_refs is for raw facts read from a source.
    return store.put_fact(
        Fact(id=fid, tenant_id=tenant_id, metric=definition.metric, value=value,
             unit=definition.unit, period=period, entity_token=entity_token,
             provenance=provenance, data_mode=mode, computed_at=ctx.now),
        revision=ctx.revision,
    )


# ---------------------------------------------------------------- figures


def _check_provenance(store: FactStore, tenant_id: str, provenance: Provenance) -> list[Fact]:
    if not store.has_formula(provenance.formula_id, provenance.formula_version):
        raise ProvenanceIncomplete(
            f"formula {provenance.formula_id} v{provenance.formula_version} is not recorded")
    inputs = []
    for input_id in provenance.input_fact_ids:
        try:
            inputs.append(store.get_fact(input_id, tenant_id=tenant_id))
        except FactNotFound as exc:
            raise ProvenanceIncomplete(f"input fact {input_id} is missing for {tenant_id}") from exc
    if not provenance.source_row_ids:
        raise ProvenanceIncomplete("a figure must resolve to at least one source row")
    return inputs


def record_figure(store: FactStore, fact: Fact, label_key: str) -> Figure:
    """Turn a stored fact into a user-facing figure (what a screen shows and a click explains)."""
    if fact.provenance is None:
        store.put_formula(RAW_FORMULA)
        provenance = Provenance(formula_id=RAW_FORMULA.formula_id,
                                formula_version=RAW_FORMULA.version,
                                input_fact_ids=(fact.id,), source_row_ids=(cite(fact),))
    else:
        provenance = fact.provenance
    _check_provenance(store, fact.tenant_id, provenance)
    digest = hashlib.sha256(f"{fact.id}|{label_key}".encode()).hexdigest()[:24]
    figure = Figure(id=f"fig_{digest}", label_key=label_key, value=fact.value, unit=fact.unit,
                    provenance=provenance, data_mode=fact.data_mode)
    return store.put_figure(fact.tenant_id, figure)


def record_computed(
    store: FactStore,
    *,
    tenant_id: str,
    metric: str,
    value: Decimal,
    unit: Unit,
    period: Period,
    formula: FormulaRef,
    inputs: Sequence[Fact],
    label_key: str,
    parameters: Mapping[str, str] | None = None,
    entity_token: str | None = None,
    data_mode: DataMode | None = None,
    now: datetime | None = None,
) -> Figure:
    """Record a figure another engine computed (forecast, score, ...) so `/explain` works.

    Checks that every input fact exists for this tenant, records the formula version, derives
    the source-row closure from the inputs, stores the fact and returns the figure. Raises
    `ProvenanceIncomplete` instead of storing a figure that could not be explained.
    """
    if not inputs:
        raise ProvenanceIncomplete("a computed figure needs at least one input fact")
    for item in inputs:
        try:
            stored = store.get_fact(item.id, tenant_id=tenant_id)
        except FactNotFound as exc:
            raise ProvenanceIncomplete(f"input fact {item.id} is not stored for {tenant_id}") \
                from exc
        if stored.value != item.value:
            raise ProvenanceIncomplete(f"input fact {item.id} differs from the stored one")
    store.put_formula(formula)
    rows = _dedupe(row for f in inputs for row in source_rows(f))
    mode = combined_data_mode([f.data_mode for f in inputs] + ([data_mode] if data_mode else []))
    fid = fact_id(tenant_id, metric, period, entity_token, formula.version, value, rows)
    provenance = Provenance(formula_id=formula.formula_id, formula_version=formula.version,
                            input_fact_ids=tuple(f.id for f in inputs), source_row_ids=rows,
                            parameters=dict(parameters or {}))
    fact = store.put_fact(Fact(id=fid, tenant_id=tenant_id, metric=metric, value=value,
                               unit=unit, period=period, entity_token=entity_token,
                               provenance=provenance, data_mode=mode,
                               computed_at=now or datetime.now(UTC)))
    return record_figure(store, fact, label_key)


# ---------------------------------------------------------------- explain


def _resolve(store: FactStore, figure_id: str, caller: Principal
             ) -> tuple[str, Decimal, Unit, Provenance]:
    """(tenant, value, unit, provenance) of a figure or fact the caller's tenant owns.
    Another tenant's id is reported exactly like an unknown one (no existence oracle)."""
    try:
        tenant_id, figure = store.get_figure(figure_id, tenant_id=caller.tenant_id)
        return tenant_id, figure.value, figure.unit, figure.provenance
    except FactNotFound:
        fact = store.get_fact(figure_id, tenant_id=caller.tenant_id)
    if fact.provenance is not None:
        return fact.tenant_id, fact.value, fact.unit, fact.provenance
    return fact.tenant_id, fact.value, fact.unit, Provenance(
        formula_id=RAW_FORMULA.formula_id, formula_version=RAW_FORMULA.version,
        source_row_ids=(cite(fact),))


def explain(
    store: FactStore,
    figure_id: str,
    caller: Principal,
    masker: SourceRowMasker | None = None,
) -> Explanation:
    """Formula, inputs with their values, and the source rows (masked for this caller).

    `figure_id` may name a stored `Figure` or a `Fact` of the caller's tenant. The masking
    hook is called on every explanation, for every caller.
    """
    tenant_id, value, unit, provenance = _resolve(store, figure_id, caller)
    if provenance.formula_id == RAW_FORMULA.formula_id:
        store.put_formula(RAW_FORMULA)
    try:
        formula = store.formula(provenance.formula_id, provenance.formula_version)
        inputs = [store.get_fact(i, tenant_id=tenant_id) for i in provenance.input_fact_ids]
    except FactNotFound as exc:
        raise ProvenanceIncomplete(str(exc)) from exc
    rows, masked = (masker or get_masker())(tenant_id, provenance.source_row_ids, caller)
    return Explanation(
        figure_id=figure_id, formula=formula, value=value, unit=unit,
        inputs=tuple(ExplainedInput(fact_id=f.id, metric=f.metric, value=f.value, unit=f.unit)
                     for f in inputs),
        source_rows=rows, masked=masked,
    )


@dataclass(frozen=True)
class ResolvedRow:
    ref: str  # the citation, masked for callers who may not see it
    kind: str  # "transaction", "invoice", "bill", "fact" or "unknown"
    record: Transaction | Invoice | Bill | Fact | None


@dataclass(frozen=True)
class RowsPage:
    figure_id: str
    total: int
    offset: int
    masked: bool
    rows: tuple[ResolvedRow, ...]


_KINDS = {"txn": "transaction", "inv": "invoice", "bill": "bill", "fact": "fact"}


def explain_rows(store: FactStore, figure_id: str, caller: Principal, offset: int = 0,
                 limit: int = 100, masker: SourceRowMasker | None = None) -> RowsPage:
    """One page of a figure's source rows resolved to the records themselves (the N13 drawer:
    the original transactions behind a number), masked for this caller."""
    tenant_id, _value, _unit, provenance = _resolve(store, figure_id, caller)
    cited = provenance.source_row_ids
    page = cited[offset:offset + limit]
    refs, masked = (masker or get_masker())(tenant_id, page, caller)
    by_kind: dict[str, list[str]] = {}
    for citation in page:
        prefix, _sep, record_id = citation.partition(":")
        by_kind.setdefault(prefix, []).append(record_id)
    found: dict[str, Transaction | Invoice | Bill | Fact] = {}
    for record_id, txn in store.transactions_by_id(tenant_id, by_kind.get("txn", [])).items():
        found[f"txn:{record_id}"] = txn
    for prefix, kind in (("inv", "invoice"), ("bill", "bill")):
        for record_id, doc in store.documents_by_id(tenant_id, kind,
                                                    by_kind.get(prefix, [])).items():
            found[f"{prefix}:{record_id}"] = doc
    for record_id in by_kind.get("fact", []):
        try:
            found[f"fact:{record_id}"] = store.get_fact(record_id, tenant_id=tenant_id)
        except FactNotFound:
            continue
    show_all = sees_rows(tenant_id, caller) and not masked
    rows = []
    for citation, ref in zip(page, refs, strict=True):
        record = found.get(citation)
        if record is not None and not show_all:
            record = mask_record(record, tenant_id)
        kind = _KINDS.get(citation.partition(":")[0], "unknown") if record else "unknown"
        rows.append(ResolvedRow(ref=ref, kind=kind, record=record))
    return RowsPage(figure_id=figure_id, total=len(cited), offset=offset, masked=masked,
                    rows=tuple(rows))
