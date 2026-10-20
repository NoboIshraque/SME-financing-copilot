"""Cash API (WP-04 milestone 8; FEATURES Q1, Q3).

    GET  /api/cash/forecast?buffer=&seed=  -> CashForecast {band, figures}
    GET  /api/cash/gaps?buffer=&seed=      -> CashGaps {as_of, buffer, gaps, indicators, sweep}
    GET  /api/cash/alerts?buffer=&seed=    -> [Alert], highest tier first, fixes cheapest first
    POST /api/cash/whatif?buffer=&seed=    -> CashForecast for the shocked inputs
         {sales_change_pct, cost_change_pct, collection_delay_days, one_off_cost, one_off_day?}

Signed-in callers holding `ledger:read`, always for their own tenant (WP-11). The forecast
starts the day after the tenant's latest transaction and opens at the cash on hand at the close
of that latest day. That figure is WP-01's `opening_balance` fact for the forecast's first day
(initial balance + every transaction before that day), the anchor WP-07's analysis API uses too,
and every cash figure cites it as its input. It equals `closing_balance` of the latest day, but
`closing_balance` needs cash in and cash out on that day to have source rows, so a shop whose
last day held only payments (the garment shop's payroll) could not be forecast. `buffer` defaults
to the buffer target, `seed` to the engine's seed, so the same ledger always gives the same
answer. A what-if replays the same draws with its shocks (common random numbers): the
difference to the plain forecast is the shock, never luck. Percentages are percent ("-20").

Every number is a Figure recorded in the fact ledger with its formula, its input fact and its
parameters, so `/api/explain/{figure_id}` opens it (N13). With fewer than 8 weeks of
transactions, or no opening balance on record, the API abstains (422, an ApiError naming what
is missing) instead of guessing.

The WP-06 catalogue prices the standby facility and the early-pay check, with the tenant's
profile facts for eligibility. The liquidity mesh has no store yet (WP-08 milestone 8), so the
demo ring of the synthetic universe stands in, for synthetic tenants only.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.contracts import (
    ActionCard,
    Alert,
    ApiError,
    CashGap,
    Currency,
    DataMode,
    Fact,
    Figure,
    ForecastBand,
    Granularity,
    LeadingIndicator,
    MeshObligation,
    Money,
    Period,
    Principal,
    Provenance,
    Role,
)
from app.engines.cash.alerts import build_alerts
from app.engines.cash.baseline import Baseline, forecast_baseline
from app.engines.cash.buffer import headline_figures, sweep_lever, target_figure
from app.engines.cash.calendar import load_festivals
from app.engines.cash.figures import FORMULAS, Evidence
from app.engines.cash.gaps import Gap, Signal, find_gaps, leading_indicators
from app.engines.cash.levers import LeverContext, smoothing_levers
from app.engines.cash.simulate import BASE, SEED, Draws, Scenario, Simulation, draw, run
from app.engines.financing.catalogue import load_catalogue
from app.facts import FactStore, cite, fact_id, record_figure
from app.facts.provenance import compute
from app.facts.registry import NotComputable
from app.main import get_session
from app.security.approvals import issue_cards
from app.security.deps import require
from app.security.errors import ProblemRoute
from app.security.roles import Permission

router = APIRouter(prefix="/cash", tags=["cash"], route_class=ProblemRoute)
MIN_HISTORY_DAYS = 56  # 8 weeks (FEATURES N17)
TOP_FIXES = 3
CACHE_SIZE = 16
SEED_MAX = 2**32 - 1
NO_INITIAL_BALANCE = "the balance the ledger starts from (initial_balance)"


class CashForecast(BaseModel):
    band: ForecastBand
    figures: list[Figure]


class IndicatorView(BaseModel):
    indicator: LeadingIndicator
    figures: list[Figure]
    reference_id: str | None = None
    counterparty_token: str | None = None
    day: date | None = None


class CashGaps(BaseModel):
    as_of: date
    buffer: Money
    gaps: list[CashGap]
    indicators: list[IndicatorView]
    sweep: ActionCard | None = None
    data_mode: DataMode


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_change_pct: Decimal = Decimal(0)
    cost_change_pct: Decimal = Decimal(0)
    collection_delay_days: int = Field(default=0, ge=0, le=366)
    one_off_cost: Money = Field(default_factory=Money.zero)
    one_off_day: date | None = None  # default: the first day of the forecast


class Abstain(Exception):
    """The data cannot support a forecast: say exactly what is missing (FEATURES N17)."""

    def __init__(self, code: str, message_key: str, **detail: str) -> None:
        super().__init__(message_key)
        self.error = ApiError(code=code, message_key=message_key, detail=detail)

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=422, content=self.error.model_dump(mode="json"))


def _invalid(message: str) -> JSONResponse:
    error = ApiError(code="invalid_request", message_key="error.invalid_request",
                     detail={"reason": message[:200]})
    return JSONResponse(status_code=422, content=error.model_dump(mode="json"))


# ---------------------------------------------------------------- the ledger, analysed once


@dataclass(frozen=True)
class Analysis:
    """One tenant's forecast inputs and plain simulation, for one ledger revision and seed."""

    tenant_id: str
    as_of: date
    closing: Fact  # cash at the close of `as_of`: WP-01 opening_balance of the day after
    transactions: tuple
    invoices: tuple
    bills: tuple
    baseline: Baseline
    draws: Draws
    plain: Simulation

    @property
    def evidence(self) -> Evidence:
        return Evidence(input_fact_ids=(self.closing.id,))


# (database, tenant, ledger revision, seed) -> (the engine, kept so its id stays unique, analysis)
_cache: OrderedDict[tuple[int, str, int, int], tuple[object, Analysis]] = OrderedDict()
# (database, tenant, ledger revision, seed, buffer, shocks) -> (the engine, what-if forecast):
# a slider dragged back to a value already asked about is answered without a new simulation.
_whatif_cache: OrderedDict[tuple, tuple[object, CashForecast]] = OrderedDict()
WHATIF_CACHE_SIZE = 64
_lock = threading.Lock()


def analyse(store: FactStore, tenant_id: str, seed: int = SEED) -> Analysis:
    bind = store.session.get_bind()
    key = (id(bind), tenant_id, store.revision(tenant_id), seed)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key][1]
    txns = store.transactions(tenant_id)
    if not txns:
        raise Abstain("insufficient_data", "abstain.insufficient_data",
                      missing="at least 8 weeks of transactions")
    first, as_of = min(t.day for t in txns), max(t.day for t in txns)
    if (as_of - first).days + 1 < MIN_HISTORY_DAYS:
        raise Abstain("insufficient_data", "abstain.insufficient_data",
                      missing="at least 8 weeks of transactions",
                      history_days=str((as_of - first).days + 1))
    start = as_of + timedelta(days=1)
    try:
        closing = compute(store, tenant_id, "opening_balance",
                          Period(start=start, end=start, granularity=Granularity.day))
    except NotComputable as exc:
        missing = (NO_INITIAL_BALANCE if exc.reason_key == "facts.needs_initial_balance"
                   else f"the cash balance at the start of {start.isoformat()}")
        raise Abstain("insufficient_data", exc.reason_key, missing=missing) from exc
    invoices, bills = store.invoices(tenant_id), store.bills(tenant_id)
    baseline = forecast_baseline(tenant_id, as_of, closing.value, txns, invoices, bills,
                                 store.obligations(tenant_id), load_festivals())
    draws = draw(baseline, seed)
    analysis = Analysis(tenant_id=tenant_id, as_of=as_of, closing=closing,
                        transactions=tuple(txns), invoices=tuple(invoices), bills=tuple(bills),
                        baseline=baseline, draws=draws, plain=run(baseline, draws))
    with _lock:
        _cache[key] = (bind, analysis)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return analysis


def buffer_for(analysis: Analysis, buffer: Decimal | None) -> Decimal:
    if buffer is not None:
        return buffer
    return target_figure(analysis.plain).value


# ---------------------------------------------------------------- figures into the ledger


class Recorder:
    """Records engine figures as facts + figures, so `/api/explain` opens every number."""

    def __init__(self, store: FactStore, analysis: Analysis, now: datetime) -> None:
        self.store, self.analysis, self.now = store, analysis, now
        days = analysis.baseline.days
        self.period = Period(start=days[0], end=days[-1], granularity=Granularity.day)
        self.done: dict[str, Figure] = {}

    def figure(self, fig: Figure) -> Figure:
        formula = FORMULAS.get(fig.provenance.formula_id)
        if formula is None:
            return fig  # another engine's figure (e.g. WP-06 pricing), already explained
        if fig.id in self.done:
            return self.done[fig.id]
        self.store.put_formula(formula)
        closing = self.analysis.closing
        inputs = fig.provenance.input_fact_ids or (closing.id,)
        rows = fig.provenance.source_row_ids or (cite(closing),)
        params = dict(fig.provenance.parameters)
        digest = hashlib.sha256(json.dumps([fig.label_key, params],
                                           sort_keys=True).encode()).hexdigest()[:16]
        metric = formula.formula_id.replace(".", "_")
        tenant = self.analysis.tenant_id
        fact = Fact(
            id=fact_id(tenant, metric, self.period, None, formula.version,
                       f"{fig.value}#{digest}", rows),
            tenant_id=tenant, metric=metric, value=fig.value, unit=fig.unit,
            period=self.period, data_mode=fig.data_mode, computed_at=self.now,
            provenance=Provenance(formula_id=formula.formula_id,
                                  formula_version=formula.version, input_fact_ids=inputs,
                                  source_row_ids=rows, parameters=params))
        recorded = record_figure(self.store, self.store.put_fact(fact), fig.label_key)
        self.done[fig.id] = recorded
        return recorded

    def gap(self, gap: CashGap) -> CashGap:
        return gap.model_copy(update={"figures": tuple(self.figure(f) for f in gap.figures)})

    def card(self, card: ActionCard) -> ActionCard:
        issued = card.model_copy(update={
            "impact": self.figure(card.impact) if card.impact else None,
            "cost": self.figure(card.cost) if card.cost else None,
            "figures": tuple(self.figure(f) for f in card.figures)})
        issue_cards(self.store.session, self.analysis.tenant_id, (issued,), self.now)
        return issued

    def alert(self, alert: Alert) -> Alert:
        return alert.model_copy(update={
            "gap": self.gap(alert.gap) if alert.gap else None,
            "fixes": tuple(self.card(c) for c in alert.fixes)})

    def signal(self, signal: Signal) -> IndicatorView:
        return IndicatorView(indicator=signal.indicator,
                             figures=[self.figure(f) for f in signal.figures],
                             reference_id=signal.reference_id,
                             counterparty_token=signal.counterparty_token, day=signal.day)


# ---------------------------------------------------------------- shared pieces


def _rule_metrics() -> list[str]:
    return sorted({rule.metric for product in load_catalogue() for rule in product.rules})


def mesh_for(analysis: Analysis) -> tuple[MeshObligation, ...]:
    """Until WP-08 stores mesh obligations: the synthetic demo ring, for synthetic tenants."""
    if analysis.baseline.data_mode is not DataMode.synthetic:
        return ()
    from app.synthetic import load_universe

    universe = load_universe()
    if analysis.tenant_id not in universe.smes:
        return ()
    return universe.mesh_obligations


@dataclass(frozen=True)
class AlertRun:
    analysis: Analysis
    sim: Simulation
    gaps: tuple[Gap, ...]
    alerts: tuple[Alert, ...]  # engine figures, not yet recorded


def compute_alerts(store: FactStore, tenant_id: str, now: datetime,
                   buffer: Decimal | None = None, seed: int = SEED) -> AlertRun:
    """Alerts with their fixes for one tenant (the API and the daily scan share this)."""
    analysis = analyse(store, tenant_id, seed)
    level = buffer_for(analysis, buffer)
    sim, evidence = analysis.plain, analysis.evidence
    gaps = find_gaps(sim, level, evidence)
    signals = leading_indicators(sim, analysis.transactions, analysis.invoices, analysis.bills,
                                 load_festivals(), evidence)
    context = LeverContext(sim=sim, draws=analysis.draws, now=now, evidence=evidence,
                           products=load_catalogue(),
                           facts=store.snapshot(tenant_id, _rule_metrics(), analysis.as_of),
                           mesh=mesh_for(analysis))

    def fixes(gap: Gap) -> tuple[ActionCard, ...]:
        return tuple(lv.lever.action for lv in smoothing_levers(context, gap)[:TOP_FIXES])

    alerts = build_alerts(sim, gaps, signals, now, fixes)
    return AlertRun(analysis=analysis, sim=sim, gaps=gaps, alerts=alerts)


def _forecast(store: FactStore, analysis: Analysis, buffer: Decimal | None,
              scenario: Scenario, now: datetime) -> CashForecast:
    level = buffer_for(analysis, buffer)
    sim = analysis.plain if scenario is BASE else run(analysis.baseline, analysis.draws,
                                                      scenario)
    recorder = Recorder(store, analysis, now)
    evidence = analysis.evidence
    heads = {f.label_key: f for f in headline_figures(sim, level, evidence)}
    heads["cash.buffer_target"] = target_figure(analysis.plain, evidence)  # the plan's target
    figures = [record_figure(store, analysis.closing, "cash.closing_balance"),
               *(recorder.figure(heads[k]) for k in ("cash.buffer_target", "cash.runway_days",
                                                     "cash.lowest_likely_balance"))]
    return CashForecast(band=sim.band(level, now), figures=figures)


# ---------------------------------------------------------------- routes

_reader = require(Permission.ledger_read)
BufferQuery = Query(default=None, ge=0, description="Tk; default: the buffer target")
SeedQuery = Query(default=SEED, ge=0, le=SEED_MAX)


def _seed(seed: int = SeedQuery, principal: Principal = Depends(_reader)) -> int:
    """Only the owner may pick a seed: each new seed is a fresh 1,000-path simulation whose
    figures are recorded as facts (known risk R12). Everyone else gets the engine's seed."""
    return seed if principal.role is Role.owner else SEED


@router.get("/forecast", response_model=CashForecast)
def get_forecast(buffer: Decimal | None = BufferQuery, seed: int = Depends(_seed),
                 principal: Principal = Depends(_reader),
                 session: Session = Depends(get_session)) -> CashForecast | JSONResponse:
    store = FactStore(session)
    try:
        analysis = analyse(store, principal.tenant_id, seed)
        return _forecast(store, analysis, buffer, BASE, datetime.now(UTC))
    except Abstain as exc:
        return exc.response()


@router.get("/gaps", response_model=CashGaps)
def get_gaps(buffer: Decimal | None = BufferQuery, seed: int = Depends(_seed),
             principal: Principal = Depends(_reader),
             session: Session = Depends(get_session)) -> CashGaps | JSONResponse:
    store = FactStore(session)
    try:
        analysis = analyse(store, principal.tenant_id, seed)
    except Abstain as exc:
        return exc.response()
    level = buffer_for(analysis, buffer)
    sim, evidence = analysis.plain, analysis.evidence
    recorder = Recorder(store, analysis, datetime.now(UTC))
    gaps = find_gaps(sim, level, evidence)
    signals = leading_indicators(sim, analysis.transactions, analysis.invoices, analysis.bills,
                                 load_festivals(), evidence)
    sweep = sweep_lever(sim, level, evidence)
    return CashGaps(as_of=analysis.as_of, buffer=Money.of(level),
                    gaps=[recorder.gap(g.gap) for g in gaps],
                    indicators=[recorder.signal(s) for s in signals],
                    sweep=recorder.card(sweep.action) if sweep else None,
                    data_mode=analysis.baseline.data_mode)


@router.get("/alerts", response_model=list[Alert])
def get_alerts(buffer: Decimal | None = BufferQuery, seed: int = Depends(_seed),
               principal: Principal = Depends(_reader),
               session: Session = Depends(get_session)) -> list[Alert] | JSONResponse:
    store = FactStore(session)
    now = datetime.now(UTC)
    try:
        result = compute_alerts(store, principal.tenant_id, now, buffer, seed)
    except Abstain as exc:
        return exc.response()
    recorder = Recorder(store, result.analysis, now)
    return [recorder.alert(a) for a in result.alerts]


@router.post("/whatif", response_model=CashForecast)
def post_whatif(body: WhatIfRequest, buffer: Decimal | None = BufferQuery,
                seed: int = Depends(_seed), principal: Principal = Depends(_reader),
                session: Session = Depends(get_session)) -> CashForecast | JSONResponse:
    store = FactStore(session)
    try:
        analysis = analyse(store, principal.tenant_id, seed)
    except Abstain as exc:
        return exc.response()
    bind = store.session.get_bind()
    key = (id(bind), principal.tenant_id, store.revision(principal.tenant_id), seed,
           str(buffer), body.model_dump_json())
    with _lock:
        if key in _whatif_cache:
            _whatif_cache.move_to_end(key)
            return _whatif_cache[key][1]
    if body.one_off_cost.currency is not Currency.BDT:
        return _invalid("one_off_cost must be in BDT")
    if body.one_off_cost.amount < 0:
        return _invalid("one_off_cost must not be negative")
    days = analysis.baseline.days
    day = body.one_off_day or days[0]
    if not days[0] <= day <= days[-1]:
        return _invalid(f"one_off_day must be within {days[0]}..{days[-1]}")
    flows = ((day, -body.one_off_cost.amount),) if body.one_off_cost.amount > 0 else ()
    try:
        scenario = Scenario(name="what_if", sales_change_pct=body.sales_change_pct,
                            cost_change_pct=body.cost_change_pct,
                            collection_delay_days=body.collection_delay_days, flows=flows)
    except ValueError as exc:
        return _invalid(str(exc))
    result = _forecast(store, analysis, buffer, scenario, datetime.now(UTC))
    with _lock:
        _whatif_cache[key] = (bind, result)
        while len(_whatif_cache) > WHATIF_CACHE_SIZE:
            _whatif_cache.popitem(last=False)
    return result


def clear_cache() -> None:
    """Forget every cached analysis (tests; a new seed file)."""
    with _lock:
        _cache.clear()
        _whatif_cache.clear()
