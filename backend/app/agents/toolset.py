"""The tools agents may call, one adapter per engine API (WP-10 milestone 2).

Each adapter reads the tenant's ledger through `ctx.db()`, calls the owning engine exactly as
that engine's own API does (so the copilot shows the same numbers as the screens), records
the figures in the fact ledger so `/api/explain` opens them (N13), and returns them with the
input facts they cite.

    cash.forecast      WP-04  P10/P50/P90 balance band, runway, buffer target
    cash.gaps          WP-04  gaps (breach day, shortfall, drivers) and the cheapest fixes
    analysis.scenarios WP-04  the forecast replayed with shocks (what-if, same seeded draws)
    financing.match    WP-06  options ranked by true cost and fit, sized to the cash gap; asked
                              how big (or which loan is best), also the largest loan whose
                              repayments keep the cautious forecast above the buffer
    analysis.ratios    WP-01  ledger ratios from the metric registry (WP-07 adds more)
    mesh.propose       WP-08  a netting round over the circular debt the shop is part of
    payables.upcoming  ledger bills and recurring obligations due in the next 31 days
    receivables.plan   WP-05  what customers owe, overdue, and who to chase first

Tools whose engine has not landed are registered without a runner, so the planner knows them
and the agent abstains with the engine's name instead of improvising: analysis.stability
(WP-07), market.prices and market.negotiate (WP-09, cut from this version). Reminder drafts
(WP-12) are built from the receivables plan, so the drafting intent reads receivables.plan.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.agents import ledgerdue, loansize
from app.agents.tools import (
    InsufficientData,
    NoParams,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    most_cautious,
)
from app.api import cash as cash_api
from app.contracts import (
    ActionCard,
    ActionType,
    DataMode,
    EligibilityStatus,
    Fact,
    Figure,
    FinancingNeed,
    Granularity,
    Money,
    Period,
    Provenance,
    Tier,
    Unit,
)
from app.engines.cash.buffer import headline_figures, target_figure
from app.engines.cash.simulate import SEED, Scenario, run
from app.engines.financing.application import draft_application
from app.engines.financing.catalogue import load_catalogue
from app.engines.financing.eligibility import evaluate
from app.engines.financing.ranking import match as rank_options
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import FORMULA_ID as NETTING_FORMULA
from app.engines.mesh.netting import FORMULA_VERSION as NETTING_VERSION
from app.engines.mesh.netting import propose_rounds
from app.facts import NotComputable, compute, record_figure

CASH_HISTORY = cash_api.MIN_HISTORY_DAYS  # 8 weeks, as the cash API
CASH_HISTORY_LABEL = "at least 8 weeks of transactions"
RATIO_WINDOW_DAYS = 90
RATIO_METRICS = ("net_sales", "gross_profit", "gross_margin", "operating_expenses",
                 "net_cash_flow", "dso", "dpo")
TOP_OPTIONS = 3
TOP_FIXES = 3
TOP_DUE = 4  # upcoming payments named one by one (all of them are counted and totalled)
TOP_CUSTOMERS = 3
DEFAULT_TENOR_DAYS = 90
FINANCING_EXTRA_FACTS = ("collateral_available",)  # read by approval likelihood (WP-06 API)


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CashParams(_Params):
    buffer: Decimal | None = Field(default=None, ge=0, description="Tk; default: buffer target")
    seed: int = Field(default=SEED, ge=0, le=2**32 - 1)


class ScenarioParams(CashParams):
    sales_change_pct: Decimal = Field(default=Decimal(0), ge=-100, le=500)
    cost_change_pct: Decimal = Field(default=Decimal(0), ge=-100, le=500)
    collection_delay_days: int = Field(default=0, ge=0, le=366)


class FinancingParams(_Params):
    amount: Money | None = Field(default=None, description="default: the first gap's shortfall")
    needed_by: date | None = Field(default=None, description="default: the gap's first day")
    tenor_days: int = Field(default=DEFAULT_TENOR_DAYS, ge=1, le=3650)
    purpose_key: str = Field(default="working_capital", max_length=64)
    safe_size: bool = Field(default=False, description="also size the largest safe loan")


class DueParams(_Params):
    days: int = Field(default=ledgerdue.WINDOW_DAYS, ge=1, le=92)


class RatioParams(_Params):
    window_days: int = Field(default=RATIO_WINDOW_DAYS, ge=28, le=366)


# ---------------------------------------------------------------- WP-04 cash engine


def _cited(ctx: ToolContext, facts: tuple[Fact, ...]) -> tuple[Fact, ...]:
    """The facts plus the facts each one was computed from, so the checker can recompute."""
    found = {f.id: f for f in facts}
    with ctx.db() as store:
        for fact in facts:
            for fid in fact.provenance.input_fact_ids if fact.provenance else ():
                found.setdefault(fid, store.get_fact(fid, ctx.tenant_id))
    return tuple(found.values())


def _analysis(ctx: ToolContext, tool: str, seed: int) -> cash_api.Analysis:
    try:
        with ctx.db() as store:
            return cash_api.analyse(store, ctx.tenant_id, seed)
    except cash_api.Abstain as exc:
        missing = exc.error.detail.get("missing", exc.error.message_key)
        raise InsufficientData(tool, [missing], exc.error.message_key) from None


def cash_forecast(ctx: ToolContext, params: CashParams) -> ToolResult:
    analysis = _analysis(ctx, "cash.forecast", params.seed)
    level = cash_api.buffer_for(analysis, params.buffer)
    heads = {f.label_key: f for f in headline_figures(analysis.plain, level, analysis.evidence)}
    heads["cash.buffer_target"] = target_figure(analysis.plain, analysis.evidence)
    with ctx.db() as store:
        recorder = cash_api.Recorder(store, analysis, ctx.now)
        figures = (record_figure(store, analysis.closing, "cash.closing_balance"),
                   *(recorder.figure(heads[k]) for k in ("cash.buffer_target", "cash.runway_days",
                                                         "cash.lowest_likely_balance")))
    band = analysis.plain.band(level, ctx.now)
    return ToolResult("cash.forecast", figures=figures, facts=_cited(ctx, (analysis.closing,)),
                      payload={"band": band, "as_of": analysis.as_of, "buffer": level},
                      data_mode=analysis.baseline.data_mode)


def cash_gaps(ctx: ToolContext, params: CashParams) -> ToolResult:
    analysis = _analysis(ctx, "cash.gaps", params.seed)
    level = cash_api.buffer_for(analysis, params.buffer)
    with ctx.db() as store:
        alerts = cash_api.compute_alerts(store, ctx.tenant_id, ctx.now, level, params.seed)
        recorder = cash_api.Recorder(store, analysis, ctx.now)
        gaps = tuple(recorder.gap(g.gap) for g in alerts.gaps)
        recorded = tuple(recorder.alert(a) for a in alerts.alerts)
        # No gap: the buffer the forecast was checked against is the evidence for "none".
        target = recorder.figure(target_figure(analysis.plain, analysis.evidence))
    gap_alerts = [a for a in recorded if a.gap is not None]
    worst = max(gap_alerts, key=lambda a: a.tier.rank, default=None)
    cards = worst.fixes[:TOP_FIXES] if worst is not None else ()
    figures = tuple(f for gap in gaps for f in gap.figures) or (target,)
    notes = () if gaps else ("cash.no_gap",)
    return ToolResult("cash.gaps", figures=figures, facts=_cited(ctx, (analysis.closing,)),
                      cards=cards,
                      payload={"gaps": gaps, "alerts": recorded, "buffer": level,
                               "as_of": analysis.as_of,
                               "band": analysis.plain.band(level, ctx.now)},
                      notes=notes, data_mode=analysis.baseline.data_mode)


def scenarios(ctx: ToolContext, params: ScenarioParams) -> ToolResult:
    analysis = _analysis(ctx, "analysis.scenarios", params.seed)
    level = cash_api.buffer_for(analysis, params.buffer)
    scenario = Scenario(name="what_if", sales_change_pct=params.sales_change_pct,
                        cost_change_pct=params.cost_change_pct,
                        collection_delay_days=params.collection_delay_days)
    shocked = run(analysis.baseline, analysis.draws, scenario)
    with ctx.db() as store:
        recorder = cash_api.Recorder(store, analysis, ctx.now)
        before = tuple(recorder.figure(f) for f in
                       headline_figures(analysis.plain, level, analysis.evidence)[1:])
        after = tuple(recorder.figure(f) for f in
                      headline_figures(shocked, level, analysis.evidence)[1:])
    return ToolResult("analysis.scenarios", figures=(*before, *after),
                      facts=_cited(ctx, (analysis.closing,)),
                      payload={"scenario": scenario, "before": before, "after": after,
                               "band": shocked.band(level, ctx.now), "as_of": analysis.as_of,
                               "buffer": level},
                      data_mode=analysis.baseline.data_mode)


# ---------------------------------------------------------------- WP-06 financing engine


def _need(ctx: ToolContext, params: FinancingParams) -> FinancingNeed | None:
    if params.amount is not None:
        needed_by = params.needed_by or ctx.as_of + timedelta(days=1)
        return FinancingNeed(tenant_id=ctx.tenant_id, amount=params.amount,
                             needed_by=needed_by, tenor_days=params.tenor_days,
                             purpose_key=params.purpose_key)
    gaps = ctx.results.get("cash.gaps")
    if gaps is None:
        raise InsufficientData("financing.match", ["the amount and date the money is needed"])
    found = gaps.payload.get("gaps") or ()
    if not found:
        return None
    gap = found[0]
    return FinancingNeed(tenant_id=ctx.tenant_id, amount=gap.expected_shortfall,
                         needed_by=params.needed_by or gap.first_breach_day,
                         tenor_days=params.tenor_days, purpose_key=params.purpose_key)


def _financing_facts(ctx: ToolContext, products) -> tuple[dict[str, Decimal | None], list[Fact]]:
    metrics = sorted({r.metric for p in products for r in p.rules} | set(FINANCING_EXTRA_FACTS))
    facts: dict[str, Decimal | None] = {}
    cited: list[Fact] = []
    with ctx.db() as store:
        for metric in metrics:
            fact = store.latest(ctx.tenant_id, metric, ctx.as_of)
            facts[metric] = fact.value if fact is not None else None
            if fact is not None:
                cited.append(fact)
    return facts, cited


def safe_sizes(products, facts: dict[str, Decimal | None], start: date, band,
               tenor_days: int, purpose: str) -> list[loansize.SafeSize]:
    """Largest safe loan per product, fully eligible products first, then by size and cost."""
    found = [s for s in (loansize.safe_amount(p, tenor_days, start, band, facts, purpose)
                         for p in products) if s is not None]
    status = {s.product.id: evaluate(s.product, facts, Money.of(s.amount), tenor_days,
                                     purpose).status for s in found}
    return sorted(found, key=lambda s: (status[s.product.id] is not EligibilityStatus.pass_,
                                        -s.amount, s.product.nominal_rate_pa, s.product.id))


def _safe_figure(size: loansize.SafeSize, start: date, tenor_days: int, purpose: str,
                 mode: DataMode) -> Figure:
    return Figure(id=f"{size.product.id}:safe:{size.amount}", label_key="copilot.safe_loan",
                  value=size.amount, unit=Unit.BDT, data_mode=mode,
                  provenance=Provenance(formula_id=loansize.FORMULA_ID,
                                        formula_version=loansize.FORMULA_VERSION,
                                        parameters={"product_id": size.product.id,
                                                    "start": start.isoformat(),
                                                    "tenor_days": str(tenor_days),
                                                    "purpose_key": purpose,
                                                    "step": str(loansize.STEP)}))


def financing_match(ctx: ToolContext, params: FinancingParams) -> ToolResult:
    need = _need(ctx, params)
    source = ctx.results.get("cash.gaps") or ctx.results.get("cash.forecast")
    band = source.payload.get("band") if source is not None else None
    products = load_catalogue()
    facts, cited = _financing_facts(ctx, products)
    modes = [p.data_mode for p in products] + [f.data_mode for f in cited]
    if source is not None:
        modes.append(source.data_mode)
    mode = most_cautious(modes)
    safe: list[loansize.SafeSize] = []
    no_gap = need is None
    sizing = band is not None and params.safe_size
    if sizing:
        start = params.needed_by or ctx.as_of + timedelta(days=1)
        safe = safe_sizes(products, facts, start, band, params.tenor_days, params.purpose_key)
        if need is None and safe:  # no gap: price the loan the shop can safely repay
            need = FinancingNeed(tenant_id=ctx.tenant_id, amount=Money.of(safe[0].amount),
                                 needed_by=start, tenor_days=params.tenor_days,
                                 purpose_key=params.purpose_key)
    safe_figures = tuple(_safe_figure(s, need.needed_by if need else ctx.as_of, params.tenor_days,
                                      params.purpose_key, mode) for s in safe[:TOP_OPTIONS])
    safe_notes = () if safe or not sizing else ("financing.no_safe_amount",)
    if need is None:
        return ToolResult("financing.match", notes=("financing.no_gap", *safe_notes),
                          payload={"safe": (), "sized": sizing},
                          data_mode=ctx.results["cash.gaps"].data_mode)
    if safe and need.amount.amount == safe[0].amount:
        products = [safe[0].product]  # priced at its own safe size (others: safe size only)
    ranked = rank_options(need, products, facts, start=need.needed_by, band=band)
    usable = [c.option for c in ranked if c.option.eligibility.status is not EligibilityStatus.fail]
    top = usable[:TOP_OPTIONS]
    figures = (*safe_figures, *(f for option in top for f in option.figures))
    # No gap: the safe size answers the question asked, but no loan is pushed (no card).
    cards = (draft_application(top[0], need, facts, now=ctx.now),) if top and not no_gap else ()
    gap_note = ("financing.no_gap",) if no_gap else ()
    notes = gap_note + tuple(dict.fromkeys(k for o in top for k in o.reason_keys)) + safe_notes
    if not top:
        notes = (*gap_note, "financing.no_eligible_option", *safe_notes)
    return ToolResult("financing.match", figures=figures, facts=tuple(cited), cards=cards,
                      payload={"need": need, "options": tuple(top),
                               "safe": tuple(zip(safe[:TOP_OPTIONS], safe_figures, strict=True)),
                               "sized": sizing,
                               "facts_missing": tuple(sorted(m for m, v in facts.items()
                                                             if v is None))},
                      notes=notes, data_mode=mode)


# ---------------------------------------------------------------- WP-01 metric registry


def ratios(ctx: ToolContext, params: RatioParams) -> ToolResult:
    end = ctx.as_of
    period = Period(start=end - timedelta(days=params.window_days - 1), end=end,
                    granularity=Granularity.day)
    computed: list[Fact] = []
    notes: list[str] = []
    figures: list[Figure] = []
    with ctx.db() as store:
        for metric in RATIO_METRICS:
            try:
                fact = compute(store, ctx.tenant_id, metric, period, now=ctx.now)
            except NotComputable as exc:
                notes.append(f"{metric}:{exc.reason_key}")
                continue
            computed.append(fact)
            figures.append(record_figure(store, fact, f"analysis.{metric}"))
    facts = _cited(ctx, tuple(computed))
    return ToolResult("analysis.ratios", figures=tuple(figures), facts=facts,
                      payload={"period": period, "facts": tuple(computed)}, notes=tuple(notes),
                      data_mode=most_cautious(f.data_mode for f in computed)
                      if computed else DataMode.synthetic)


# ---------------------------------------------------------------- WP-08 liquidity mesh


def _mesh_figure(round_id: str, label: str, amount: Money, obligation_ids: tuple[str, ...],
                 mode: DataMode) -> Figure:
    return Figure(id=f"{round_id}:{label.rsplit('.', 1)[-1]}", label_key=label,
                  value=amount.amount, unit=Unit.BDT, data_mode=mode,
                  provenance=Provenance(formula_id=NETTING_FORMULA,
                                        formula_version=NETTING_VERSION,
                                        source_row_ids=tuple(f"obl:{o}" for o in obligation_ids),
                                        parameters={"round_id": round_id}))


def mesh_propose(ctx: ToolContext, params: NoParams) -> ToolResult:
    with ctx.db() as store:
        txns = store.transactions(ctx.tenant_id)
    mode = txns[0].data_mode if txns else DataMode.synthetic
    obligations = ()
    if mode is DataMode.synthetic:  # until WP-08 stores obligations: the demo ring (as WP-04)
        from app.synthetic import load_universe

        universe = load_universe()
        if ctx.tenant_id in universe.smes:
            obligations = universe.mesh_obligations
    rounds = [r for r in propose_rounds(build_graph(obligations), now=ctx.now, data_mode=mode)
              if ctx.tenant_id in r.participants]
    if not rounds:
        return ToolResult("mesh.propose", notes=("mesh.no_cycle",), data_mode=mode)
    round_ = rounds[0]
    saved = round_.gross_total - round_.net_total
    figures = tuple(_mesh_figure(round_.id, label, amount, round_.obligation_ids, mode)
                    for label, amount in (("mesh.gross_total", round_.gross_total),
                                          ("mesh.net_total", round_.net_total),
                                          ("mesh.cash_saved", saved)))
    card = ActionCard(id=f"netting:{round_.id}", title_key="action.propose_netting_round",
                      action_type=ActionType.propose_netting_round, tier=Tier.DRAFT,
                      payload={"round_id": round_.id, "participants": list(round_.participants),
                               "obligation_ids": list(round_.obligation_ids)},
                      figures=figures[:2], impact=figures[2], expires_at=round_.expires_at)
    return ToolResult("mesh.propose", figures=figures, cards=(card,),
                      payload={"round": round_}, data_mode=mode)


# ---------------------------------------------------------------- ledger: money due


def _due_figure(fig_id: str, label: str, value: Decimal, unit: Unit, formula: str,
                rows: tuple[str, ...], params: dict[str, str], mode: DataMode) -> Figure:
    return Figure(id=fig_id, label_key=label, value=value, unit=unit, data_mode=mode,
                  provenance=Provenance(formula_id=formula,
                                        formula_version=ledgerdue.FORMULA_VERSION,
                                        source_row_ids=rows, parameters=params))


def payables_upcoming(ctx: ToolContext, params: DueParams) -> ToolResult:
    with ctx.db() as store:
        bills = store.bills(ctx.tenant_id)
        obligations = store.obligations(ctx.tenant_id)
    as_of = ctx.as_of
    due = ledgerdue.upcoming(bills, obligations, as_of, params.days)
    mode = most_cautious([*(b.data_mode for b in bills), *(o.data_mode for o in obligations)]) \
        if bills or obligations else ctx.data_mode
    base = {"as_of": as_of.isoformat(), "days": str(params.days)}
    key = f"{ctx.tenant_id}:payables:{as_of.isoformat()}:{params.days}"
    rows = tuple(d.ref for d in due) or (f"ledger:{ctx.tenant_id}",)
    figures = [
        _due_figure(f"{key}:count", "copilot.payables_count", Decimal(len(due)), Unit.count,
                    ledgerdue.PAYABLES_FORMULA, rows, {**base, "part": "count"}, mode),
        _due_figure(f"{key}:total", "copilot.payables_total", sum((d.amount for d in due),
                                                                  Decimal(0)),
                    Unit.BDT, ledgerdue.PAYABLES_FORMULA, rows, {**base, "part": "total"}, mode)]
    for item in due[:TOP_DUE]:
        figures.append(_due_figure(f"{key}:{item.ref}", "copilot.payable_item", item.amount,
                                   Unit.BDT, ledgerdue.PAYABLES_FORMULA, (item.ref,),
                                   {**base, "part": "item", "ref": item.ref}, mode))
    suppliers = ledgerdue.labels((b.counterparty_token for b in bills), "Supplier")
    return ToolResult("payables.upcoming", figures=tuple(figures),
                      payload={"due": tuple(due), "as_of": as_of, "suppliers": suppliers},
                      notes=() if due else ("payables.none_due",), data_mode=mode)


def receivables_plan(ctx: ToolContext, params: NoParams) -> ToolResult:
    with ctx.db() as store:
        invoices = store.invoices(ctx.tenant_id)
    as_of = ctx.as_of
    found = ledgerdue.owed(invoices, as_of)
    mode = most_cautious(i.data_mode for i in invoices) if invoices else ctx.data_mode
    base = {"as_of": as_of.isoformat()}
    key = f"{ctx.tenant_id}:owed:{as_of.isoformat()}"
    whole = found.open_ids or (f"ledger:{ctx.tenant_id}",)
    figures = [
        _due_figure(f"{key}:open", "copilot.receivables_open", found.open_total, Unit.BDT,
                    ledgerdue.RECEIVABLES_FORMULA, whole, {**base, "part": "open"}, mode),
        _due_figure(f"{key}:overdue", "copilot.receivables_overdue", found.overdue_total,
                    Unit.BDT, ledgerdue.RECEIVABLES_FORMULA, found.overdue_ids or whole,
                    {**base, "part": "overdue"}, mode)]
    for customer in found.customers[:TOP_CUSTOMERS]:
        figures.append(_due_figure(
            f"{key}:{customer.token}", "copilot.customer_owes", customer.amount, Unit.BDT,
            ledgerdue.RECEIVABLES_FORMULA, customer.invoice_ids,
            {**base, "part": "customer", "token": customer.token}, mode))
    customers = ledgerdue.labels((i.counterparty_token for i in invoices), "Customer")
    return ToolResult("receivables.plan", figures=tuple(figures),
                      payload={"owed": found, "as_of": as_of, "customers": customers},
                      notes=() if found.open_ids else ("receivables.none_open",), data_mode=mode)


# ---------------------------------------------------------------- the registry


def build_registry() -> ToolRegistry:
    return ToolRegistry([
        Tool("cash.forecast", "Daily cash balance band (P10/P50/P90) for the next 91 days, "
             "runway and buffer target", "WP-04 cash engine", CashParams,
             min_history_days=CASH_HISTORY, history_label=CASH_HISTORY_LABEL, run=cash_forecast),
        Tool("cash.gaps", "Cash gaps ahead (first breach day, expected shortfall, drivers) "
             "and the cheapest fixes as action cards", "WP-04 cash engine", CashParams,
             min_history_days=CASH_HISTORY, history_label=CASH_HISTORY_LABEL, run=cash_gaps),
        Tool("analysis.scenarios", "The cash forecast replayed with a shock: sales change %, "
             "cost change %, customers paying later", "WP-04 cash engine (what-if)",
             ScenarioParams, min_history_days=CASH_HISTORY, history_label=CASH_HISTORY_LABEL,
             run=scenarios),
        Tool("financing.match", "Financing options ranked by true annual cost, fit with the "
             "forecast, speed and approval odds; sized to the cash gap by default",
             "WP-06 financing engine", FinancingParams, run=financing_match),
        Tool("analysis.ratios", "Sales, gross profit and margin, operating expenses, net cash "
             "flow, days sales outstanding and days payables outstanding",
             "WP-01 metric registry", RatioParams, min_history_days=28,
             history_label="at least 4 weeks of transactions", run=ratios),
        Tool("mesh.propose", "A netting round that settles circular debt with the least cash",
             "WP-08 liquidity mesh", tier=Tier.DRAFT, run=mesh_propose),
        Tool("payables.upcoming", "Bills and regular payments (rent, salaries, utilities, "
             "loan instalments) due in the next 31 days, soonest first, and overdue bills",
             "ledger bills and obligations", DueParams, run=payables_upcoming),
        Tool("receivables.plan", "What customers owe, how much is overdue, and who to chase "
             "first", "WP-05 receivables engine", run=receivables_plan),
        Tool("analysis.stability", "Whether a recommendation holds under stressed inputs",
             "WP-07 analysis engine"),
        Tool("market.prices", "Wholesale prices and cheaper vendors", "WP-09 market engine"),
        Tool("market.negotiate", "A negotiation script with the numbers behind each step",
             "WP-09 market engine"),
    ])


REGISTRY = build_registry()
