"""Decision stability score (WP-07 milestone 5; FEATURES N10, N16).

A recommendation is re-made under ten variations of what it was made from:

  economic stress (the advice MAY change; a flip says where it breaks)
    late_payer          the customer who owes the most pays every open invoice 30 days later
                        than they usually do
    sales_minus_10      sales and credit sales 10% lower
    sales_minus_20      20% lower
    inputs_plus_8       purchases and running costs 8% dearer
    rates_plus_2pp      interest rates 2 points higher (reprices any loan it takes)
    surprise_bill       a bill of one month of fixed obligations (10% of a month's outflows
                        without any) due in 7 days
  irrelevant noise (the advice MUST NOT change; a flip makes it unreliable)
    rows_shuffled       every ledger record in another order
    parties_renamed     every counterparty token replaced, consistently
    question_reworded   the question asked in other words
    dates_shifted_format  dates in the question written another way

score = variations in which the choice held / variations run. A stress that does not apply
(no open invoice for late_payer, nothing to base a surprise bill on) is left out rather than
counted as held. `what_would_flip` names the stresses that changed the choice; any noise flip
marks the report unreliable (`StabilityReport.unreliable`).

`stability` takes any `decide(request, shift) -> choice`, so WP-10's agents can be scored the
same way; `EngineDecider` is the deterministic one: WP-07's scenario comparison. Every run uses
the same seed (common random numbers): a flip is the variation, never luck. Re-running the
engine for a variation that only rewords the question would repeat the same computation (the
engine never reads the question), so the decider answers those from its cache.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np

from app.contracts import (
    Figure,
    FinancingProduct,
    Granularity,
    LenderProfile,
    MeshObligation,
    Period,
    StabilityReport,
    Unit,
    VariationKind,
    VariationResult,
)
from app.engines.analysis.figures import make_figure
from app.engines.analysis.ledger import Ledger
from app.engines.analysis.scenarios import (
    MENU,
    NO_SHIFT,
    STATES,
    Assumptions,
    ScenarioInputs,
    Shift,
    compare_decisions,
    prepare,
    shock_size,
)
from app.engines.cash.calendar import Festival
from app.engines.cash.simulate import PATHS, SEED, InvoiceChange

ZERO = Decimal(0)
LATE_DAYS = 30
SURPRISE_IN_DAYS = 7
SCORE_QUANTUM = Decimal("0.0001")
STRESS = VariationKind.stress
NOISE = VariationKind.noise


@dataclass(frozen=True)
class Request:
    """What a decision is made from: the typed ledger and the question as asked."""

    ledger: Ledger
    question: str = ""


Decide = Callable[[Request, Shift], str]


# ---------------------------------------------------------------- stress


def stresses(inputs: ScenarioInputs) -> tuple[list[tuple[str, Shift]], list[str]]:
    """(the stress variations that apply, the names of those that do not)."""
    base = inputs.baseline
    found: list[tuple[str, Shift]] = []
    skipped: list[str] = []
    owed: dict[str, Decimal] = {}
    first: dict[str, date] = {}
    for inv, amount in base.open_invoices:
        owed[inv.counterparty_token] = owed.get(inv.counterparty_token, ZERO) + amount
        first[inv.counterparty_token] = min(first.get(inv.counterparty_token, inv.issue_date),
                                            inv.issue_date)
    changes: dict[str, InvoiceChange] = {}
    if owed:
        biggest = min(owed, key=lambda t: (-owed[t], first[t], t))
        for inv, amount in base.open_invoices:
            days = base.invoice_delays.possible_days(inv, base.as_of)
            if inv.counterparty_token == biggest and days:
                usual = sorted(days)[(len(days) - 1) // 2]
                changes[inv.id] = InvoiceChange(
                    receipts=((usual + timedelta(days=LATE_DAYS), amount),))
    if changes:
        found.append(("late_payer", Shift(name="late_payer", invoice_changes=changes)))
    else:
        skipped.append("late_payer")
    found += [("sales_minus_10", Shift(name="sales_minus_10", sales_change_pct=Decimal(-10))),
              ("sales_minus_20", Shift(name="sales_minus_20", sales_change_pct=Decimal(-20))),
              ("inputs_plus_8", Shift(name="inputs_plus_8", cost_change_pct=Decimal(8))),
              ("rates_plus_2pp", Shift(name="rates_plus_2pp", rate_pp=Decimal(2)))]
    bill = shock_size(inputs, Assumptions(shock_share_pct=Decimal(100)))
    if bill > 0:
        day = base.as_of + timedelta(days=SURPRISE_IN_DAYS)
        found.append(("surprise_bill", Shift(name="surprise_bill", flows=((day, -bill),))))
    else:
        skipped.append("surprise_bill")
    return found, skipped


# ---------------------------------------------------------------- noise


def _rng(seed: int, salt: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=(salt,))))


def shuffle_rows(ledger: Ledger, seed: int) -> Ledger:
    rng = _rng(seed, 8101)

    def mixed(items: tuple) -> tuple:
        return tuple(items[int(i)] for i in rng.permutation(len(items)))

    return replace(ledger, transactions=mixed(ledger.transactions),
                   invoices=mixed(ledger.invoices), bills=mixed(ledger.bills),
                   obligations=mixed(ledger.obligations), facts=mixed(ledger.facts))


def rename_parties(ledger: Ledger, seed: int) -> Ledger:
    """Every counterparty token replaced by another one, the same everywhere."""
    def new(token: str | None) -> str | None:
        if token is None:
            return None
        return "PARTY_" + hashlib.sha256(f"{seed}|{token}".encode()).hexdigest()[:10]

    def renamed(items: tuple) -> tuple:
        return tuple(item.model_copy(update={"counterparty_token": new(item.counterparty_token)})
                     for item in items)

    return replace(ledger, transactions=renamed(ledger.transactions),
                   invoices=renamed(ledger.invoices), bills=renamed(ledger.bills),
                   obligations=renamed(ledger.obligations))


_REWORDINGS = ("Could you look at this for me? {q}", "{q} What would you advise?",
               "Quick question about my shop: {q}")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def reword(question: str, seed: int) -> str:
    template = _REWORDINGS[int(_rng(seed, 8102).integers(len(_REWORDINGS)))]
    return template.format(q=question.strip() or "What should I do?")


def _written(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def reformat_dates(question: str, as_of: date) -> str:
    """ISO dates written as '30 Sep 2026'; a question without dates gets the books' date
    added in that form."""
    changed = _ISO.sub(lambda m: _written(date(*(int(g) for g in m.groups()))), question)
    if changed != question:
        return changed
    return f"{question} (books up to {_written(as_of)})".strip()


def noise(seed: int) -> list[tuple[str, Callable[[Request], Request]]]:
    return [
        ("rows_shuffled", lambda r: replace(r, ledger=shuffle_rows(r.ledger, seed))),
        ("parties_renamed", lambda r: replace(r, ledger=rename_parties(r.ledger, seed))),
        ("question_reworded", lambda r: replace(r, question=reword(r.question, seed))),
        ("dates_shifted_format",
         lambda r: replace(r, question=reformat_dates(r.question, r.ledger.as_of))),
    ]


# ---------------------------------------------------------------- the score


@dataclass(frozen=True)
class Stability:
    report: StabilityReport
    figure: Figure  # the score, for provenance
    skipped: tuple[str, ...]  # stresses that did not apply


def stability(recommendation_id: str, request: Request, decide: Decide,
              stress: Sequence[tuple[str, Shift]], seed: int = SEED,
              skipped: Sequence[str] = ()) -> Stability:
    """Re-make the decision under every stress and noise variation and score how it holds."""
    choice = decide(request, NO_SHIFT)
    results = [VariationResult(name=name, kind=STRESS, choice=(c := decide(request, shift)),
                               held=c == choice) for name, shift in stress]
    for name, vary in noise(seed):
        varied = decide(vary(request), NO_SHIFT)
        results.append(VariationResult(name=name, kind=NOISE, choice=varied,
                                       held=varied == choice))
    held = sum(1 for r in results if r.held)
    score = (Decimal(held) / Decimal(len(results))).quantize(SCORE_QUANTUM)
    report = StabilityReport(
        recommendation_id=recommendation_id, baseline_choice=choice, results=tuple(results),
        score=score,
        what_would_flip=tuple(r.name for r in results if r.kind is STRESS and not r.held))
    ledger = request.ledger
    day = ledger.as_of
    figure = make_figure(
        ledger.tenant_id, ledger.data_mode, "analysis.stability.score", "stability.label",
        score, Unit.probability, Period(start=day, end=day, granularity=Granularity.day),
        inputs=(ledger.anchor,),
        params={"recommendation_id": recommendation_id, "choice": choice, "seed": seed,
                "held": held, "variations": len(results),
                "flipped": ",".join(r.name for r in results if not r.held) or "none"})
    return Stability(report=report, figure=figure, skipped=tuple(skipped))


@dataclass
class EngineDecider:
    """The scenario comparison as a decision function, with the world fixed by its seed."""

    festivals: Sequence[Festival]
    buffer: Decimal
    now: datetime
    names: Sequence[str] = MENU
    assumptions: Assumptions = field(default_factory=Assumptions)
    seed: int = SEED
    paths: int = PATHS
    states: int = STATES
    products: Sequence[FinancingProduct] = ()
    facts: Mapping[str, Decimal | None] = field(default_factory=dict)
    lenders: Mapping[str, LenderProfile] = field(default_factory=dict)
    mesh: Sequence[MeshObligation] = ()
    _inputs: dict[int, tuple[Ledger, ScenarioInputs]] = field(default_factory=dict, repr=False)
    _choices: dict[tuple[int, str], str] = field(default_factory=dict, repr=False)

    def inputs(self, ledger: Ledger) -> ScenarioInputs:
        """The forecast for `ledger`, made once. The cache holds the ledger itself, so its id
        cannot be taken by another object while the entry lives."""
        cached = self._inputs.get(id(ledger))
        if cached is None or cached[0] is not ledger:
            prepared = prepare(ledger, self.festivals, self.buffer, self.now, self.seed,
                               self.paths, products=self.products, facts=self.facts,
                               lenders=self.lenders, mesh=self.mesh)
            cached = self._inputs[id(ledger)] = (ledger, prepared)
            self._choices = {k: v for k, v in self._choices.items() if k[0] != id(ledger)}
        return cached[1]

    def remember(self, ledger: Ledger, inputs: ScenarioInputs) -> None:
        """Use a forecast the caller already made for `ledger` (same seed and paths)."""
        if inputs.draws.seed != self.seed or inputs.draws.paths != self.paths or \
                inputs.buffer != self.buffer:
            raise ValueError("the forecast was made with another seed, paths or buffer")
        self._inputs[id(ledger)] = (ledger, inputs)
        self._choices = {k: v for k, v in self._choices.items() if k[0] != id(ledger)}

    def __call__(self, request: Request, shift: Shift = NO_SHIFT) -> str:
        """The recommended decision. Shifts are told apart by their name."""
        inputs = self.inputs(request.ledger)
        key = (id(request.ledger), shift.name)
        if key not in self._choices:
            self._choices[key] = compare_decisions(inputs, self.names, self.assumptions, shift,
                                                   self.states).choice
        return self._choices[key]


def engine_stability(recommendation_id: str, request: Request, decider: EngineDecider
                     ) -> Stability:
    """The stability of the scenario engine's own recommendation for `request`."""
    stress, skipped = stresses(decider.inputs(request.ledger))
    return stability(recommendation_id, request, decider, stress, decider.seed, skipped)
