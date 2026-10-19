"""Analysis API (WP-07 milestone 6; FEATURES N1, N4, N12, N16).

    GET  /api/analysis/statements?granularity=month|quarter|year&on=   -> Statements
    GET  /api/analysis/ratios?granularity=&on=                          -> [Ratio]
    GET  /api/analysis/variance?kind=weekly|quarterly                   -> VarianceReport
    POST /api/analysis/scenarios {decisions?, buffer?, seed?, assumptions?, question?}
                                                                       -> ScenarioComparison
    POST /api/analysis/stability {recommendation_id} or the same body as /scenarios
                                                                       -> StabilityReport

Signed-in callers holding `ledger:read`, always for their own tenant (WP-11). Statements and
ratios cover the calendar month, quarter or year containing `on` (default: the day of the
latest transaction). Their cash figures start from WP-01's `opening_balance` fact for the
period, so a click on any number opens its formula, its inputs and its transactions
(`/api/explain/{figure_id}`, N13): every engine figure is recorded in the fact ledger first.

Expected vs reality freezes the forecast snapshots that are due (one per week or quarter after
8 weeks of history; one frozen after its period began is marked `reconstructed`), checks the
last complete periods, and returns the latest check, the accuracy history and the correction
for the cash forecast (the same two percentages `/api/cash/whatif` takes). A stored snapshot
is never replaced.

Scenarios simulate the chosen decisions (default: the whole menu) on WP-04's seeded paths, the
buffer defaulting to WP-04's buffer target, and name the best risk-adjusted one. The request
is kept under its `recommendation_id`, so `/stability` can re-run it on the current ledger
under ten variations. Without enough data the API abstains (422, an ApiError naming what is
missing) instead of guessing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.contracts import (
    ApiError,
    DataMode,
    Fact,
    Figure,
    Granularity,
    MeshObligation,
    Money,
    Period,
    Principal,
    Provenance,
    Ratio,
    Scenario,
    Variance,
    VariationResult,
)
from app.engines.analysis.figures import FORMULAS
from app.engines.analysis.ledger import Ledger, NotEnoughData, calendar_period
from app.engines.analysis.ratios import compute_ratios
from app.engines.analysis.scenarios import MENU, Assumptions, compare_decisions, prepare
from app.engines.analysis.stability import EngineDecider, Request, engine_stability
from app.engines.analysis.statements import build_statements
from app.engines.analysis.store import (
    comparison_request,
    ensure_snapshots,
    latest_ledger,
    ledger_for,
    records,
    remember_comparison,
)
from app.engines.analysis.variance import (
    Snapshot,
    SnapshotKind,
    compare,
    correction,
    favourable,
)
from app.engines.cash.buffer import target_figure
from app.engines.cash.calendar import load_festivals
from app.engines.cash.simulate import SEED, run
from app.engines.financing.catalogue import load_catalogue
from app.facts import FactStore, fact_id, record_figure
from app.main import get_session
from app.security.clock import Clock
from app.security.deps import get_clock, require
from app.security.errors import ProblemRoute
from app.security.roles import Permission

router = APIRouter(prefix="/analysis", tags=["analysis"], route_class=ProblemRoute)
DHAKA = ZoneInfo("Asia/Dhaka")
SEED_MAX = 2**32 - 1
STATEMENT_PERIODS = (Granularity.month, Granularity.quarter, Granularity.year)


# ---------------------------------------------------------------- shapes


class StatementLine(BaseModel):
    label_key: str
    figure: Figure
    total: bool = False  # subtotals are drawn bold with a rule above


class Statements(BaseModel):
    period: Period
    through: date  # the last day covered (the period end, or the ledger's last day)
    partial: bool
    pnl: list[StatementLine]
    balance_sheet: list[StatementLine]
    cash_flow: list[StatementLine]
    missing: list[str]  # facts not on record, e.g. 'stock_value'
    data_mode: DataMode


class VarianceLine(BaseModel):
    expected: Figure
    actual: Figure
    favourable: bool


class SnapshotView(BaseModel):
    id: str
    kind: SnapshotKind
    as_of: date
    frozen_at: datetime
    reconstructed: bool


class Check(BaseModel):
    period: Period
    accuracy: Figure | None
    snapshot: SnapshotView


class CorrectionView(BaseModel):
    checks: int
    applied: bool
    sales_change_pct: Decimal  # send both to /api/cash/whatif to see the corrected forecast
    cost_change_pct: Decimal
    figures: list[Figure]


class VarianceReport(BaseModel):
    period: Period
    variances: list[Variance]
    accuracy: Figure | None
    lines: dict[str, VarianceLine]
    snapshot: SnapshotView
    history: list[Check]  # oldest first, the latest check last
    correction: CorrectionView
    data_mode: DataMode


class AssumptionsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_sd_pct: Decimal | None = None
    input_price_sd_pct: Decimal | None = None
    delay_days: list[int] | None = None
    delay_weights_pct: list[int] | None = None
    rate_pp_max: Decimal | None = None
    shock_probability_pct: Decimal | None = None
    shock_share_pct: Decimal | None = None

    def build(self) -> Assumptions:
        given = {k: tuple(v) if isinstance(v, list) else v
                 for k, v in self.model_dump(exclude_none=True).items()}
        return Assumptions(**given)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[str] = Field(default_factory=lambda: list(MENU), min_length=1,
                                 max_length=len(MENU))
    buffer: Decimal | None = Field(default=None, ge=0, description="Tk; default: buffer target")
    seed: int = Field(default=SEED, ge=0, le=SEED_MAX)
    assumptions: AssumptionsBody = Field(default_factory=AssumptionsBody)
    question: str | None = Field(default=None, max_length=500)

    def canonical(self) -> dict[str, Any]:
        return {"decisions": sorted(set(self.decisions)),
                "buffer": str(self.buffer) if self.buffer is not None else None,
                "seed": self.seed, "assumptions": self.assumptions.model_dump(
                    mode="json", exclude_none=True), "question": self.question}


class StabilityRequest(ScenarioRequest):
    recommendation_id: str | None = Field(default=None, max_length=40)


class Skipped(BaseModel):
    decision: str
    reason_key: str


class ScenarioComparison(BaseModel):
    scenarios: list[Scenario]
    recommended_id: str
    recommendation_id: str  # give it to /stability
    reason_keys: list[str]
    skipped: list[Skipped]
    figures: dict[str, list[Figure]]  # scenario id -> expected, worst 5%, P(breach), risk, cost
    details: dict[str, dict[str, str]]  # scenario id -> what exactly the decision does
    buffer: Money
    as_of: date
    data_mode: DataMode


class StabilityView(BaseModel):
    """`StabilityReport` with its score as a figure and the stresses that did not apply."""

    recommendation_id: str
    baseline_choice: str
    results: list[VariationResult]
    score: Decimal
    what_would_flip: list[str]
    unreliable: bool
    figure: Figure
    skipped: list[str]


# ---------------------------------------------------------------- errors


def _abstain(exc: NotEnoughData) -> JSONResponse:
    error = ApiError(code="insufficient_data", message_key=exc.reason_key,
                     detail={"missing": exc.missing[:200]})
    return JSONResponse(status_code=422, content=error.model_dump(mode="json"))


def _invalid(message: str) -> JSONResponse:
    error = ApiError(code="invalid_request", message_key="error.invalid_request",
                     detail={"reason": message[:200]})
    return JSONResponse(status_code=422, content=error.model_dump(mode="json"))


def _not_found() -> JSONResponse:
    error = ApiError(code="not_found", message_key="analysis.unknown_recommendation")
    return JSONResponse(status_code=404, content=error.model_dump(mode="json"))


# ---------------------------------------------------------------- figures into the ledger


class Recorder:
    """Records engine figures as facts + figures, inputs first, so `/api/explain` opens every
    number with the stored facts it was computed from."""

    def __init__(self, store: FactStore, tenant_id: str, now: datetime) -> None:
        self.store, self.tenant_id, self.now = store, tenant_id, now
        self.pool: dict[str, Figure] = {}
        self.facts: dict[str, Fact] = {}  # engine figure id -> its stored fact
        self.figures: dict[str, Figure] = {}  # engine figure id -> its stored figure

    def add(self, figures: Iterable[Figure]) -> None:
        for figure in figures:
            self.pool[figure.id] = figure

    def fact_id(self, input_id: str) -> str:
        """The stored fact behind an engine figure id (other ids are facts already)."""
        if input_id in self.pool:
            self.figure(self.pool[input_id])
            return self.facts[input_id].id
        return input_id

    def provenance(self, provenance: Provenance) -> Provenance:
        return provenance.model_copy(update={"input_fact_ids": tuple(
            self.fact_id(i) for i in provenance.input_fact_ids)})

    def figure(self, figure: Figure) -> Figure:
        if figure.id in self.figures:
            return self.figures[figure.id]
        formula = FORMULAS.get(figure.provenance.formula_id)
        if formula is None:
            return figure  # another engine's figure, explained there
        self.pool.setdefault(figure.id, figure)
        provenance = self.provenance(figure.provenance)
        params = dict(provenance.parameters)
        period = Period(start=date.fromisoformat(params["start"]),
                        end=date.fromisoformat(params["end"]),
                        granularity=Granularity(params["granularity"]))
        digest = hashlib.sha256(json.dumps(
            [figure.label_key, params, list(provenance.input_fact_ids), figure.data_mode.value],
            sort_keys=True).encode()).hexdigest()[:16]
        metric = formula.formula_id.replace(".", "_")
        self.store.put_formula(formula)
        fact = self.store.put_fact(Fact(
            id=fact_id(self.tenant_id, metric, period, None, formula.version,
                       f"{figure.value}#{digest}", provenance.source_row_ids),
            tenant_id=self.tenant_id, metric=metric, value=figure.value, unit=figure.unit,
            period=period, data_mode=figure.data_mode, computed_at=self.now,
            provenance=provenance))
        recorded = record_figure(self.store, fact, figure.label_key)
        self.facts[figure.id], self.figures[figure.id] = fact, recorded
        return recorded


# ---------------------------------------------------------------- shared pieces

_reader = require(Permission.ledger_read)


def _today(now: datetime) -> date:
    return now.astimezone(DHAKA).date()


def _rule_metrics() -> list[str]:
    return sorted({rule.metric for product in load_catalogue() for rule in product.rules})


def _mesh(ledger: Ledger) -> tuple[MeshObligation, ...]:
    """Until WP-08 stores mesh obligations: the synthetic demo ring, for synthetic tenants
    (as WP-04's cash API does)."""
    if ledger.data_mode is not DataMode.synthetic:
        return ()
    from app.synthetic import load_universe

    universe = load_universe()
    return universe.mesh_obligations if ledger.tenant_id in universe.smes else ()


def _statement_period(store: FactStore, tenant_id: str, granularity: Granularity,
                      on: date | None) -> Period:
    if granularity not in STATEMENT_PERIODS:
        raise ValueError("granularity must be month, quarter or year")
    return calendar_period(on or records(store, tenant_id).last_day, granularity)


def _lines(recorder: Recorder, lines: Sequence) -> list[StatementLine]:
    return [StatementLine(label_key=line.figure.label_key,
                          figure=recorder.figure(line.figure), total=line.total)
            for line in lines]


def _recommendation_id(tenant_id: str, request: Mapping[str, Any]) -> str:
    text = json.dumps([tenant_id, request], sort_keys=True)
    return "rec_" + hashlib.sha256(text.encode()).hexdigest()[:24]


class _Prepared:
    def __init__(self, store: FactStore, tenant_id: str, body: ScenarioRequest,
                 now: datetime) -> None:
        self.assumptions = body.assumptions.build()  # ValueError: bad assumptions
        self.ledger = latest_ledger(store, tenant_id)
        self.facts = store.snapshot(tenant_id, _rule_metrics(), self.ledger.as_of)
        self.products = load_catalogue()
        self.mesh = _mesh(self.ledger)
        inputs = prepare(self.ledger, load_festivals(), Decimal(0), now, body.seed,
                         products=self.products, facts=self.facts, mesh=self.mesh)
        buffer = body.buffer if body.buffer is not None else \
            target_figure(run(inputs.baseline, inputs.draws)).value
        self.inputs = replace(inputs, buffer=buffer)


# ---------------------------------------------------------------- routes


@router.get("/statements", response_model=Statements)
def get_statements(granularity: Granularity = Granularity.month, on: date | None = None,
                   principal: Principal = Depends(_reader),
                   session: Session = Depends(get_session),
                   clock: Clock = Depends(get_clock)) -> Statements | JSONResponse:
    store, tenant = FactStore(session), principal.tenant_id
    try:
        period = _statement_period(store, tenant, granularity, on)
        stmt = build_statements(ledger_for(store, tenant, period), period)
    except NotEnoughData as exc:
        return _abstain(exc)
    except ValueError as exc:
        return _invalid(str(exc))
    recorder = Recorder(store, tenant, clock())
    recorder.add(line.figure for line in stmt.lines())
    return Statements(period=stmt.period, through=stmt.through, partial=stmt.partial,
                      pnl=_lines(recorder, stmt.pnl),
                      balance_sheet=_lines(recorder, stmt.balance_sheet),
                      cash_flow=_lines(recorder, stmt.cash_flow), missing=list(stmt.missing),
                      data_mode=stmt.data_mode)


@router.get("/ratios", response_model=list[Ratio])
def get_ratios(granularity: Granularity = Granularity.month, on: date | None = None,
               principal: Principal = Depends(_reader),
               session: Session = Depends(get_session),
               clock: Clock = Depends(get_clock)) -> list[Ratio] | JSONResponse:
    store, tenant = FactStore(session), principal.tenant_id
    try:
        period = _statement_period(store, tenant, granularity, on)
        ratios = compute_ratios(ledger_for(store, tenant, period), period)
    except NotEnoughData as exc:
        return _abstain(exc)
    except ValueError as exc:
        return _invalid(str(exc))
    recorder = Recorder(store, tenant, clock())
    recorder.add(ratios.figures)
    for figure in ratios.figures:
        recorder.figure(figure)
    return [r.model_copy(update={"provenance": recorder.provenance(r.provenance)})
            for r in ratios.ratios]


def _snapshot_view(snapshot: Snapshot) -> SnapshotView:
    return SnapshotView(id=snapshot.id, kind=snapshot.kind, as_of=snapshot.as_of,
                        frozen_at=snapshot.frozen_at, reconstructed=snapshot.reconstructed)


@router.get("/variance", response_model=VarianceReport)
def get_variance(kind: SnapshotKind = SnapshotKind.weekly,
                 principal: Principal = Depends(_reader),
                 session: Session = Depends(get_session),
                 clock: Clock = Depends(get_clock)) -> VarianceReport | JSONResponse:
    store, tenant, now = FactStore(session), principal.tenant_id, clock()
    try:
        pairs = ensure_snapshots(session, store, tenant, kind, load_festivals(), now,
                                 _today(now))
        reports = [compare(s, ledger) for s, ledger in pairs if s.period.end <= ledger.as_of]
        if not reports:
            raise NotEnoughData(f"a {kind.granularity.value} that has ended after 8 weeks of "
                                "transactions")
    except NotEnoughData as exc:
        return _abstain(exc)
    fix = correction(reports)
    recorder = Recorder(store, tenant, now)
    for report in reports:
        recorder.add(f for pair in report.figures.values() for f in pair)
        recorder.add([report.accuracy] if report.accuracy else [])
    recorder.add(fix.figures)
    latest = reports[-1]
    lines = {metric: VarianceLine(expected=recorder.figure(expected),
                                  actual=recorder.figure(actual),
                                  favourable=favourable(metric, actual.value - expected.value))
             for metric, (expected, actual) in latest.figures.items()}
    history = [Check(period=r.period, snapshot=_snapshot_view(r.snapshot),
                     accuracy=recorder.figure(r.accuracy) if r.accuracy else None)
               for r in reports]
    return VarianceReport(
        period=latest.period, variances=list(latest.variances), lines=lines,
        accuracy=history[-1].accuracy, snapshot=_snapshot_view(latest.snapshot),
        history=history, data_mode=latest.snapshot.data_mode,
        correction=CorrectionView(checks=fix.checks, applied=fix.applied,
                                  sales_change_pct=fix.sales_change_pct,
                                  cost_change_pct=fix.cost_change_pct,
                                  figures=[recorder.figure(f) for f in fix.figures]))


@router.post("/scenarios", response_model=ScenarioComparison)
def post_scenarios(body: ScenarioRequest, principal: Principal = Depends(_reader),
                   session: Session = Depends(get_session),
                   clock: Clock = Depends(get_clock)) -> ScenarioComparison | JSONResponse:
    store, tenant, now = FactStore(session), principal.tenant_id, clock()
    try:
        prepared = _Prepared(store, tenant, body, now)
        result = compare_decisions(prepared.inputs, body.decisions, prepared.assumptions)
    except NotEnoughData as exc:
        return _abstain(exc)
    except ValueError as exc:
        return _invalid(str(exc))
    request = body.canonical()
    recommendation_id = _recommendation_id(tenant, request)
    remember_comparison(session, recommendation_id, tenant, request, now)
    recorder = Recorder(store, tenant, now)
    return ScenarioComparison(
        scenarios=list(result.scenarios), recommended_id=result.recommended_id,
        recommendation_id=recommendation_id, reason_keys=list(result.reason_keys),
        skipped=[Skipped(decision=n, reason_key=r) for n, r in result.skipped],
        figures={o.scenario.id: [recorder.figure(f) for f in o.figures]
                 for o in result.outcomes},
        details={o.scenario.id: dict(o.decision.details) for o in result.outcomes},
        buffer=Money.of(result.buffer), as_of=prepared.ledger.as_of,
        data_mode=prepared.inputs.baseline.data_mode)


@router.post("/stability", response_model=StabilityView)
def post_stability(body: StabilityRequest, principal: Principal = Depends(_reader),
                   session: Session = Depends(get_session),
                   clock: Clock = Depends(get_clock)) -> StabilityView | JSONResponse:
    store, tenant, now = FactStore(session), principal.tenant_id, clock()
    if body.recommendation_id is not None:
        if body.model_fields_set - {"recommendation_id"}:
            return _invalid("give either recommendation_id or the comparison, not both")
        stored = comparison_request(session, body.recommendation_id, tenant)
        if stored is None:
            return _not_found()
        request = ScenarioRequest.model_validate(stored)
        recommendation_id = body.recommendation_id
    else:
        request = ScenarioRequest.model_validate(body.model_dump(exclude={"recommendation_id"}))
        recommendation_id = _recommendation_id(tenant, request.canonical())
        remember_comparison(session, recommendation_id, tenant, request.canonical(), now)
    try:
        prepared = _Prepared(store, tenant, request, now)
        decider = EngineDecider(load_festivals(), prepared.inputs.buffer, now,
                                names=request.decisions, assumptions=prepared.assumptions,
                                seed=request.seed, products=prepared.products,
                                facts=prepared.facts, mesh=prepared.mesh)
        decider.remember(prepared.ledger, prepared.inputs)
        question = request.question or "Which should I do: " + ", ".join(request.decisions)
        result = engine_stability(recommendation_id, Request(prepared.ledger, question),
                                  decider)
    except NotEnoughData as exc:
        return _abstain(exc)
    except ValueError as exc:
        return _invalid(str(exc))
    report = result.report
    figure = Recorder(store, tenant, now).figure(result.figure)
    return StabilityView(recommendation_id=report.recommendation_id,
                         baseline_choice=report.baseline_choice, results=list(report.results),
                         score=report.score, what_would_flip=list(report.what_would_flip),
                         unreliable=report.unreliable, figure=figure,
                         skipped=list(result.skipped))
