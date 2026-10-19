"""Self-loops: push each recommendation to its limits before it is shown (WP-10 milestone 7;
FEATURES N10, N16).

The decision a recommendation rests on (which financing option, or which fix comes first) is
re-made by the same engines under variations of its inputs:

    stress  an economic change that may legitimately change the decision
            (sales -10% / -20%, costs +10%, customers paying a week later)
    noise   a change that must not change it (another Monte Carlo seed, a Tk 1 expense)

The result is a `StabilityReport`: the share of variations where the choice held, what
stress would flip it, and whether it flipped on noise (then it cannot be trusted, N16).
Stakes decide how many variations run (none for information, two at medium, four at high);
results are cached per ledger revision, so asking again costs nothing.

WP-07 owns the analysis engine and its `analysis.stability` tool; until it lands, this loop
re-makes the decision with the WP-04 simulation and levers and the WP-06 ranking directly.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.agents.agreement import Judgement
from app.agents.stakes import Stakes
from app.agents.tools import ToolContext
from app.api import cash as cash_api
from app.contracts import (
    EligibilityStatus,
    FinancingNeed,
    StabilityReport,
    VariationKind,
    VariationResult,
)
from app.engines.cash.gaps import Gap, find_gaps
from app.engines.cash.levers import LeverContext, smoothing_levers
from app.engines.cash.simulate import BASE, SEED, Draws, Scenario, Simulation, draw, run
from app.engines.financing.catalogue import load_catalogue
from app.engines.financing.ranking import match as rank_options

DEFAULT_TENOR_DAYS = 90
NO_GAP = "no_gap"
NO_CHOICE = "no_choice"
CACHE_SIZE = 64


@dataclass(frozen=True)
class Variation:
    name: str
    kind: VariationKind
    scenario: Scenario
    seed_offset: int = 0


def _tiny_expense(as_of_next: object) -> Scenario:
    return Scenario(name="noise:tiny_expense", flows=((as_of_next, Decimal(-1)),))


STRESS = (
    Variation("sales_minus_10", VariationKind.stress,
              Scenario(name="stress:sales_minus_10", sales_change_pct=Decimal(-10))),
    Variation("customers_7_days_late", VariationKind.stress,
              Scenario(name="stress:customers_7_days_late", collection_delay_days=7)),
    Variation("costs_plus_10", VariationKind.stress,
              Scenario(name="stress:costs_plus_10", cost_change_pct=Decimal(10))),
    Variation("sales_minus_20", VariationKind.stress,
              Scenario(name="stress:sales_minus_20", sales_change_pct=Decimal(-20))),
)
SEED_CHANGED = Variation("seed_changed", VariationKind.noise, BASE, seed_offset=1)
# name -> variations, by stakes: a stress and a noise check at medium; more of each at high.
PLAN: dict[Stakes, tuple[str, ...]] = {
    Stakes.low: (),
    Stakes.medium: ("sales_minus_10", "seed_changed"),
    Stakes.high: ("sales_minus_10", "customers_7_days_late", "seed_changed", "tiny_expense"),
}

_cache: OrderedDict[tuple, tuple[object, str]] = OrderedDict()
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


class Decider:
    """Re-makes one kind of decision for the tenant under a variation."""

    def __init__(self, ctx: ToolContext, kind: str, seed: int, buffer: Decimal) -> None:
        self.ctx, self.kind, self.seed, self.buffer = ctx, kind, seed, buffer
        with ctx.db() as store:
            self.analysis = cash_api.analyse(store, ctx.tenant_id, seed)
            self.revision = store.revision(ctx.tenant_id)
            self.bind = store.session.get_bind()
            products = load_catalogue()
            metrics = sorted({r.metric for p in products for r in p.rules})
            self.facts = store.snapshot(ctx.tenant_id, metrics, self.analysis.as_of)
        self.products = products

    def variation(self, name: str) -> Variation:
        if name == "seed_changed":
            return SEED_CHANGED
        if name == "tiny_expense":
            first = self.analysis.as_of + timedelta(days=1)
            return Variation(name, VariationKind.noise, _tiny_expense(first))
        return next(v for v in STRESS if v.name == name)

    def choice(self, variation: Variation | None = None) -> str:
        variation = variation or Variation("baseline", VariationKind.noise, BASE)
        key = (id(self.bind), self.ctx.tenant_id, self.revision, self.kind, self.seed,
               str(self.buffer), variation.name)
        with _lock:
            if key in _cache:
                _cache.move_to_end(key)
                return _cache[key][1]
        seed = self.seed + variation.seed_offset
        baseline = self.analysis.baseline
        draws = self.analysis.draws if variation.seed_offset == 0 else draw(baseline, seed)
        sim = run(baseline, draws, variation.scenario)
        gaps = find_gaps(sim, self.buffer, self.analysis.evidence)
        if not gaps:
            made = NO_GAP
        elif self.kind == "financing_option":
            made = self._financing(sim, gaps[0])
        else:
            made = self._fix(sim, draws, gaps[0])
        with _lock:
            _cache[key] = (self.bind, made)
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
        return made

    def _financing(self, sim: Simulation, gap: Gap) -> str:
        need = FinancingNeed(tenant_id=self.ctx.tenant_id, amount=gap.gap.expected_shortfall,
                             needed_by=gap.gap.first_breach_day, tenor_days=DEFAULT_TENOR_DAYS)
        ranked = rank_options(need, self.products, self.facts, start=need.needed_by,
                              band=sim.band(self.buffer, self.ctx.now))
        usable = [c for c in ranked if c.option.eligibility.status is not EligibilityStatus.fail]
        return usable[0].option.product.id if usable else NO_CHOICE

    def _fix(self, sim: Simulation, draws: Draws, gap: Gap) -> str:
        context = LeverContext(sim=sim, draws=draws, now=self.ctx.now,
                               evidence=self.analysis.evidence, products=self.products,
                               facts=self.facts, mesh=cash_api.mesh_for(self.analysis))
        levers = smoothing_levers(context, gap)
        if not levers:
            return NO_CHOICE
        impact = levers[0].lever.action.impact
        return impact.provenance.parameters.get("lever", levers[0].lever.kind.value)


def stability(decider: Decider, stakes: Stakes, recommendation_id: str) -> StabilityReport | None:
    names = PLAN[stakes]
    if not names:
        return None
    baseline = decider.choice()
    results = []
    for name in names:
        variation = decider.variation(name)
        made = decider.choice(variation)
        results.append(VariationResult(name=name, kind=variation.kind, choice=made,
                                       held=made == baseline))
    held = sum(1 for r in results if r.held)
    return StabilityReport(
        recommendation_id=recommendation_id, baseline_choice=baseline, results=tuple(results),
        score=Decimal(held) / Decimal(len(results)),
        what_would_flip=tuple(r.name for r in results
                              if r.kind is VariationKind.stress and not r.held))


def self_loop(ctx: ToolContext, judgement: Judgement | None, stakes: Stakes,
              results: Mapping[str, object], recommendation_id: str,
              decider_factory: Callable[..., Decider] = Decider) -> StabilityReport | None:
    """The stability of the judgement the recommendation rests on, if it is one the engines
    can re-make (an option or a fix; an intent is not an engine decision)."""
    if judgement is None or judgement.kind not in ("financing_option", "fix"):
        return None
    source = results.get("cash.gaps")
    if source is None:
        return None
    seed = int(next((f.provenance.parameters["seed"] for f in source.figures
                     if "seed" in f.provenance.parameters), SEED))
    decider = decider_factory(ctx, judgement.kind, seed, source.payload["buffer"])
    return stability(decider, stakes, recommendation_id)
