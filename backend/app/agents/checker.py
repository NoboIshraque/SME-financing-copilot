"""The checker: every claim is recomputed before anyone sees it (WP-10 milestone 4; N8).

A claim passes only if (1) it matches its figure (value, unit, formula, cited facts) and its
text states that value as `claims.render` writes it, and (2) an independent recomputation
from the ledger gives exactly the claimed value:

    WP-01 metrics   derived: from the cited input facts, re-read from the ledger, through the
                    registry *and* through SymPy on the published expression (the code and the
                    formula a user reads must agree); ledger metrics: from the ledger rows
    WP-04 cash      a freshly drawn simulation with the figure's seed, buffer and scenario,
                    through the engine's own figure functions (levers: its alert pipeline)
    WP-06 costs     the catalogue product's cash flows for the figure's principal and tenor
    WP-08 netting   the netting round recomputed from the cited obligations
    money due       upcoming payments and money owed, re-read from the ledger's bills,
                    obligations and invoices (the cited rows must be exactly the ones found)
    safe loan size  the amount is re-checked: safe on the run's forecast, one step more is not
    WP-09 market    the TCB point re-read from the saved lists; the change re-derived from the
                    watchlist; negotiation prices re-made from that point and the financing
                    product's own effective APR for the deal

A mismatch is `rejected`; no recomputation path is `unverifiable`. Either way the claim is
removed from the answer and logged (`RejectedClaimRow`). The narration check then makes sure
a narrated answer contains no number that is not in a verified claim.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sympy

from app.agents import ledgerdue, loansize
from app.agents.claims import Statement, render
from app.agents.models import RejectedClaimRow
from app.agents.tools import ToolContext, ToolResult
from app.agents.toolset import TCB_PRICE
from app.api import cash as cash_api
from app.api import market as market_api
from app.contracts import CheckResult, CheckStatus, Claim, Fact, Figure, Money, Unit
from app.engines.cash.buffer import headline_figures, target_figure
from app.engines.cash.figures import FORMULAS as CASH_FORMULAS
from app.engines.cash.gaps import find_gaps
from app.engines.cash.simulate import BASE, Scenario, draw, run
from app.engines.financing import cost as cost_mod
from app.engines.financing import fit as fit_mod
from app.engines.financing.catalogue import load_catalogue
from app.engines.market import negotiate as negotiate_mod
from app.engines.market import tcb, watch
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import FORMULA_ID as NETTING_FORMULA
from app.engines.mesh.netting import propose_rounds
from app.facts import REGISTRY, cite
from app.facts.registry import LedgerInputs, MetricDefinition, NotComputable, quantize
from app.facts.seed import INITIAL_BALANCE
from app.synthetic import load_universe

log = logging.getLogger("app.agents.checker")

_COMMENT = re.compile(r"\(([^()]*)\)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Numbers written as words. A model can state a figure without a single digit ("fifty thousand",
# "পঞ্চাশ হাজার", "五万"), so the narration check reads those too. A lone "one" is not counted
# ("this one", "一些"), and Bangla "নয়" (nine, but also "is not") is left out.
_EN_SMALL = {word: value for value, word in enumerate((
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen"))}
_EN_SMALL.update({word: 10 * value for value, word in enumerate((
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"), start=2)})
_EN_SCALES = {"thousand": 10**3, "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5,
              "crore": 10**7, "crores": 10**7, "million": 10**6, "billion": 10**9}
_BN_SMALL = {unicodedata.normalize("NFC", word): value for word, value in {
    "শূন্য": 0, "এক": 1, "দুই": 2, "দু": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6,
    "সাত": 7, "আট": 8, "দশ": 10, "বিশ": 20, "কুড়ি": 20, "ত্রিশ": 30,
    "চল্লিশ": 40, "পঞ্চাশ": 50, "ষাট": 60, "সত্তর": 70, "আশি": 80, "নব্বই": 90}.items()}
_BN_SCALES = {unicodedata.normalize("NFC", word): value for word, value in {
    "হাজার": 10**3, "লাখ": 10**5, "লক্ষ": 10**5, "কোটি": 10**7}.items()}
_BN_HUNDRED = {"শ", "শত", "শো"}
_BN_SUFFIXES = tuple(unicodedata.normalize("NFC", s) for s in (
    "য়ের", "য়ের", "টি", "টা", "জন", "ের", "এর", "তে", "র", "ে"))
_WORD = re.compile(r"[A-Za-z]+|[\u0980-\u09FF]+")
_ZH_DIGITS = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9),
                      strict=True))
_ZH_UNITS = {"十": 10, "百": 100, "千": 1000}
_ZH_SECTIONS = {"万": 10**4, "亿": 10**8}
_ZH_RUN = re.compile("[" + "".join([*_ZH_DIGITS, *_ZH_UNITS, *_ZH_SECTIONS]) + "]+")
DAYS_SYMBOL = "days_in_period"
CACHE_SIZE = 32

# Recomputed cash figures per (database, tenant, ledger revision, seed, buffer, scenario): a
# new ledger revision recomputes, the same ledger is not re-simulated on every question.
# The value keeps the engine object alive so its id() cannot be reused by another database.
_cash_cache: OrderedDict[tuple, tuple[object, dict[tuple, Decimal]]] = OrderedDict()
_cash_lock = threading.Lock()


def clear_cache() -> None:
    with _cash_lock:
        _cash_cache.clear()


class Unverifiable(Exception):
    """No independent way to recompute this claim."""


class FormulaMismatch(Exception):
    """The registry's code and its published expression give different values."""


def _rejected(claim: Claim, reason: str, recomputed: Decimal | None = None) -> CheckResult:
    return CheckResult(claim_id=claim.id, status=CheckStatus.rejected,
                       recomputed_value=recomputed, reason=reason)


def formula_expression(definition: MetricDefinition) -> sympy.Expr | None:
    """The published expression as SymPy, without its prose comments; None if it is prose."""
    allowed = {*definition.inputs, DAYS_SYMBOL}

    def keep(match: re.Match[str]) -> str:
        names = set(_IDENT.findall(match.group(1)))
        return match.group(0) if names <= allowed else ""

    text = definition.expression
    while True:
        stripped = _COMMENT.sub(keep, text)
        if stripped == text:
            break
        text = stripped
    if not set(_IDENT.findall(text)) <= allowed:
        return None
    try:
        return sympy.sympify(text, locals={name: sympy.Symbol(name) for name in allowed})
    except (sympy.SympifyError, SyntaxError, TypeError):
        return None


def symbolic_value(definition: MetricDefinition, values: Mapping[str, Decimal],
                   days: int) -> Decimal | None:
    expr = formula_expression(definition)
    if expr is None:
        return None
    subs = {sympy.Symbol(k): sympy.Rational(str(v)) for k, v in values.items()}
    subs[sympy.Symbol(DAYS_SYMBOL)] = sympy.Integer(days)
    result = sympy.nsimplify(expr.subs(subs))
    if not result.is_Rational:
        return None
    exact = Decimal(int(result.p)) / Decimal(int(result.q))
    return quantize(exact, definition.unit)


class Checker:
    def __init__(self, ctx: ToolContext, results: Mapping[str, ToolResult]) -> None:
        self.ctx = ctx
        self.results = results
        self._facts: dict[str, Fact] = {f.id: f for r in results.values() for f in r.facts}
        self._by_formula = {d.formula_id: d for m in REGISTRY.metrics()
                            for d in (REGISTRY.get(m, v) for v in REGISTRY.versions(m))}

    # ------------------------------------------------------------------ entry points

    def check(self, claim: Claim, figure: Figure) -> CheckResult:
        if claim.value is None:
            return CheckResult(claim_id=claim.id, status=CheckStatus.unverifiable,
                               reason="an assertion without a value cannot be recomputed")
        prov = figure.provenance
        if (claim.value, claim.unit, claim.formula_id) != (figure.value, figure.unit,
                                                           prov.formula_id):
            return _rejected(claim, "the claim does not match its figure", figure.value)
        if tuple(claim.input_fact_ids) != prov.input_fact_ids:
            return _rejected(claim, "the claim cites other facts than its figure")
        if render(claim.value, claim.unit) not in claim.text:
            return _rejected(claim, "the text does not state the claimed value")
        try:
            recomputed = self.recompute(figure)
        except Unverifiable as exc:
            return CheckResult(claim_id=claim.id, status=CheckStatus.unverifiable,
                               reason=str(exc))
        except FormulaMismatch as exc:
            return _rejected(claim, str(exc))
        if recomputed != claim.value:
            return _rejected(claim, "recomputation gives a different value", recomputed)
        return CheckResult(claim_id=claim.id, status=CheckStatus.verified,
                           recomputed_value=recomputed)

    def check_statements(self, statements: Sequence[Statement]) -> list[CheckResult]:
        return [self.check(s.claim, s.figure) for s in statements]

    def check_figure(self, figure: Figure) -> CheckStatus:
        """A card figure has no claim of its own: check the figure as it would be stated."""
        claim = Claim(id=f"card:{figure.id}", text=render(figure.value, figure.unit),
                      value=figure.value, unit=figure.unit,
                      formula_id=figure.provenance.formula_id,
                      input_fact_ids=figure.provenance.input_fact_ids)
        return self.check(claim, figure).status

    def recompute(self, figure: Figure) -> Decimal:
        formula = figure.provenance.formula_id
        if formula in self._by_formula:
            return self._metric(figure, self._by_formula[formula])
        if formula in CASH_FORMULAS:
            return self._cash_value(figure)
        if formula in (cost_mod.FORMULA_ID, fit_mod.FORMULA_ID):
            return self._financing(figure)
        if formula == NETTING_FORMULA:
            return self._netting(figure)
        if formula == ledgerdue.PAYABLES_FORMULA:
            return self._payables(figure)
        if formula == ledgerdue.RECEIVABLES_FORMULA:
            return self._receivables(figure)
        if formula == ledgerdue.LOANS_FORMULA:
            with self.ctx.db() as store:
                obligations = store.obligations(self.ctx.tenant_id)
            return Decimal(sum(1 for o in obligations if o.kind.value == "emi"))
        if formula == loansize.FORMULA_ID:
            return self._safe_loan(figure)
        if formula == TCB_PRICE or formula in watch.EXPRESSIONS:
            return self._market(figure)
        if formula in negotiate_mod.EXPRESSIONS:
            return self._negotiation(figure)
        raise Unverifiable(f"no recomputation for formula {formula}")

    # ------------------------------------------------------------------ WP-01 metrics

    def _claimed_fact(self, figure: Figure) -> Fact:
        for fact in self._facts.values():
            if fact.provenance == figure.provenance:  # never by value: the value is on trial
                return fact
        raise Unverifiable("the fact behind the figure is not among the run's facts")

    def _metric(self, figure: Figure, definition: MetricDefinition) -> Decimal:
        fact = self._claimed_fact(figure)
        if definition.from_inputs is not None:
            with self.ctx.db() as store:
                inputs = [store.get_fact(fid, self.ctx.tenant_id)
                          for fid in figure.provenance.input_fact_ids]
            values = {f.metric: f.value for f in inputs}
            try:
                value = definition.compute_derived(values, fact.period)
            except NotComputable as exc:
                raise Unverifiable(f"inputs cannot recompute {fact.metric}") from exc
            symbolic = symbolic_value(definition, values, fact.period.days)
            if symbolic is not None and symbolic != value:
                raise FormulaMismatch(f"{definition.formula_id}: the code gives {value}, the "
                                      f"published formula {symbolic}")
            return value
        with self.ctx.db() as store:
            period = fact.period
            known = [f for f in store.facts(self.ctx.tenant_id, INITIAL_BALANCE)
                     if f.period.start <= period.start]
            data = LedgerInputs(
                period=period,
                transactions=tuple(store.transactions(self.ctx.tenant_id, end=period.end)),
                invoices=tuple(store.invoices(self.ctx.tenant_id, issued_by=period.end)),
                bills=tuple(store.bills(self.ctx.tenant_id, issued_by=period.end)),
                initial_balance=known[-1] if known else None)
        try:
            return definition.compute_ledger(data).value
        except NotComputable as exc:
            raise Unverifiable(f"the ledger cannot recompute {fact.metric}") from exc

    # ------------------------------------------------------------------ WP-04 cash

    def _scenario(self, name: str) -> Scenario:
        if name == BASE.name:
            return BASE
        result = self.results.get("analysis.scenarios")
        scenario = result.payload.get("scenario") if result is not None else None
        if scenario is None or scenario.name != name:
            raise Unverifiable(f"scenario {name} is not part of this run")
        return scenario

    def _buffer(self, figure: Figure) -> Decimal:
        if "buffer" in figure.provenance.parameters:
            return Decimal(figure.provenance.parameters["buffer"])
        for name in ("cash.forecast", "cash.gaps", "analysis.scenarios"):
            result = self.results.get(name)
            if result is not None and "buffer" in result.payload:
                return result.payload["buffer"]
        raise Unverifiable("no buffer on record for this figure")

    @staticmethod
    def _key(fig: Figure, closing: Fact) -> tuple:
        prov = fig.provenance
        rows = prov.source_row_ids or (cite(closing),)
        return (fig.label_key, prov.formula_id, tuple(sorted(prov.parameters.items())), rows)

    def _cash_figures(self, seed: int, buffer: Decimal, scenario: Scenario) -> dict[tuple, Decimal]:
        with self.ctx.db() as store:
            analysis = cash_api.analyse(store, self.ctx.tenant_id, seed)
            bind = store.session.get_bind()
            key = (id(bind), self.ctx.tenant_id,
                   store.revision(self.ctx.tenant_id), seed, str(buffer), scenario.name,
                   scenario.sales_change_pct, scenario.cost_change_pct,
                   scenario.collection_delay_days)
        with _cash_lock:
            if key in _cash_cache:
                _cash_cache.move_to_end(key)
                return _cash_cache[key][1]
        # Fresh draws from the seed: the simulation is recomputed, not read from a cache.
        sim = run(analysis.baseline, draw(analysis.baseline, seed), scenario)
        evidence = analysis.evidence
        figures: list[Figure] = [*headline_figures(sim, buffer, evidence),
                                 target_figure(sim, evidence)]
        figures += [f for gap in find_gaps(sim, buffer, evidence) for f in gap.gap.figures]
        if scenario is BASE:
            with self.ctx.db() as store:
                alerts = cash_api.compute_alerts(store, self.ctx.tenant_id, self.ctx.now,
                                                 buffer, seed)
            for alert in alerts.alerts:
                for card in alert.fixes:
                    figures += [f for f in (card.impact, card.cost, *card.figures)
                                if f is not None and f.provenance.formula_id in CASH_FORMULAS]
        values: dict[tuple, Decimal] = {}
        for fig in figures:
            values.setdefault(self._key(fig, analysis.closing), fig.value)
        with _cash_lock:
            _cash_cache[key] = (bind, values)
            while len(_cash_cache) > CACHE_SIZE:
                _cash_cache.popitem(last=False)
        return values

    def _cash_value(self, figure: Figure) -> Decimal:
        params = figure.provenance.parameters
        try:
            seed = int(params["seed"])
        except (KeyError, ValueError):
            raise Unverifiable("cash figure without a seed") from None
        scenario = self._scenario(params.get("scenario", BASE.name))
        values = self._cash_figures(seed, self._buffer(figure), scenario)
        with self.ctx.db() as store:
            closing = cash_api.analyse(store, self.ctx.tenant_id, seed).closing
        found = values.get(self._key(figure, closing))
        if found is None:
            raise Unverifiable("the engine does not produce this figure again")
        return found

    # ------------------------------------------------------------------ WP-06 financing

    def _financing(self, figure: Figure) -> Decimal:
        params = figure.provenance.parameters
        products = {p.id: p for p in load_catalogue()}
        product = products.get(params.get("product_id", ""))
        if product is None:
            raise Unverifiable("product not in the catalogue")
        result = cost_mod.true_cost(product, Money.of(params["principal"]),
                                    int(params["tenor_days"]))
        if figure.provenance.formula_id == cost_mod.FORMULA_ID:  # rate or cost, by unit
            if figure.unit is Unit.percent:
                return result.effective_annual_rate
            if figure.unit is Unit.BDT:
                return result.total_cost.amount
        if figure.provenance.formula_id == fit_mod.FORMULA_ID:
            match = self.results.get("financing.match")
            gaps = self.results.get("cash.gaps")
            need = match.payload.get("need") if match is not None else None
            band = gaps.payload.get("band") if gaps is not None else None
            if need is None or band is None or str(need.amount.amount) != params["principal"]:
                raise Unverifiable("the forecast this fit was measured on is not in the run")
            return fit_mod.breach_probability(result, need.needed_by, band)
        raise Unverifiable(f"no recomputation for {figure.label_key}")

    def _safe_loan(self, figure: Figure) -> Decimal:
        """Not re-searched: the claimed amount must be safe and one step more must not be."""
        params = figure.provenance.parameters
        product = {p.id: p for p in load_catalogue()}.get(params.get("product_id", ""))
        if product is None:
            raise Unverifiable("product not in the catalogue")
        match = self.results.get("financing.match")
        source = self.results.get("cash.gaps") or self.results.get("cash.forecast")
        band = source.payload.get("band") if source is not None else None
        if match is None or band is None:
            raise Unverifiable("the forecast this loan was sized on is not in the run")
        facts = {f.metric: f.value for f in match.facts}
        if not loansize.confirm(product, figure.value, int(params["tenor_days"]),
                                date.fromisoformat(params["start"]), band, facts,
                                params.get("purpose_key", "working_capital")):
            raise FormulaMismatch("the amount is not the largest safe loan on this forecast")
        return figure.value

    # ------------------------------------------------------------------ WP-09 market

    @staticmethod
    def _observation(ref: str) -> tcb.Observation:
        found = next((o for o in market_api.observations() if o.ref == ref), None)
        if found is None:
            raise Unverifiable("the TCB list this price was read from is not on record")
        return found

    def _market(self, figure: Figure) -> Decimal:
        latest = self._observation(figure.provenance.source_row_ids[0])
        point = latest.point
        if figure.provenance.formula_id == TCB_PRICE:
            return point.price.amount
        rows = watch.watchlist(market_api.observations(), point.observed_on)
        row = next((r for r in rows if r.commodity == point.commodity), None)
        change = watch.change_figure(row) if row is not None else None
        if change is None or change.provenance.formula_id != figure.provenance.formula_id:
            raise Unverifiable("no baseline for this price on record")
        return change.value

    def _negotiation(self, figure: Figure) -> Decimal:
        rows = figure.provenance.source_row_ids
        params = figure.provenance.parameters
        point = self._observation(rows[0]).point
        product = {p.id: p for p in load_catalogue()}.get(rows[1].removeprefix("financing:"))
        if product is None:
            raise Unverifiable("the financing product behind the cost of money is gone")
        offer, quantity = Decimal(params["offer"]), Decimal(params["quantity"])
        days = int(params["payment_days"])
        deal = Money.of((offer * quantity).quantize(Decimal("0.01")))
        apr = cost_mod.true_cost(product, deal, max(days, 30)).effective_annual_rate
        plan = negotiate_mod.plan(market=point, market_ref=rows[0], offer=offer,
                                  quantity=quantity, payment_days=days, apr_percent=apr,
                                  apr_ref=rows[1], data_mode=figure.data_mode)
        made = {f.provenance.formula_id: f.value for step in plan.steps for f in step.figures}
        made |= {plan.walk_away.provenance.formula_id: plan.walk_away.value,
                 plan.target.provenance.formula_id: plan.target.value}
        if figure.provenance.formula_id not in made:
            raise Unverifiable(f"no recomputation for {figure.label_key}")
        return made[figure.provenance.formula_id]

    # ------------------------------------------------------------------ ledger: money due

    def _rows(self, figure: Figure) -> tuple[date, dict[str, str]]:
        params = figure.provenance.parameters
        try:
            return date.fromisoformat(params["as_of"]), dict(params)
        except (KeyError, ValueError):
            raise Unverifiable("no as-of day on record for this figure") from None

    def _payables(self, figure: Figure) -> Decimal:
        as_of, params = self._rows(figure)
        with self.ctx.db() as store:
            due = ledgerdue.upcoming(store.bills(self.ctx.tenant_id),
                                     store.obligations(self.ctx.tenant_id), as_of,
                                     int(params.get("days", ledgerdue.WINDOW_DAYS)))
        part = params.get("part")
        if part == "item":
            item = next((d for d in due if d.ref == params.get("ref")), None)
            if item is None:
                raise Unverifiable("the payment is no longer due in the window")
            return item.amount
        if part in ("count", "total") and due and \
                set(figure.provenance.source_row_ids) != {d.ref for d in due}:
            raise Unverifiable("the cited payments are not the ones on record")
        if part == "count":
            return Decimal(len(due))
        if part == "total":
            return sum((d.amount for d in due), Decimal(0))
        raise Unverifiable(f"no recomputation for {figure.label_key}")

    def _receivables(self, figure: Figure) -> Decimal:
        as_of, params = self._rows(figure)
        with self.ctx.db() as store:
            found = ledgerdue.owed(store.invoices(self.ctx.tenant_id), as_of)
        part = params.get("part")
        cited = set(figure.provenance.source_row_ids)
        if part == "customer":
            customer = next((c for c in found.customers if c.token == params.get("token")), None)
            if customer is None or set(customer.invoice_ids) != cited:
                raise Unverifiable("the customer's open invoices are not the ones on record")
            return customer.amount
        if part == "open":
            if found.open_ids and set(found.open_ids) != cited:
                raise Unverifiable("the cited invoices are not the open ones on record")
            return found.open_total
        if part == "overdue":
            if found.overdue_ids and set(found.overdue_ids) != cited:
                raise Unverifiable("the cited invoices are not the overdue ones on record")
            return found.overdue_total
        raise Unverifiable(f"no recomputation for {figure.label_key}")

    # ------------------------------------------------------------------ WP-08 netting

    def _netting(self, figure: Figure) -> Decimal:
        ids = {row.removeprefix("obl:") for row in figure.provenance.source_row_ids}
        obligations = [o for o in load_universe().mesh_obligations if o.id in ids]
        if {o.id for o in obligations} != ids:
            raise Unverifiable("cited obligations are not on record")
        rounds = propose_rounds(build_graph(obligations), now=self.ctx.now)
        round_ = next((r for r in rounds if set(r.obligation_ids) == ids), None)
        if round_ is None:
            raise Unverifiable("the obligations no longer form a netting round")
        values = {"mesh.gross_total": round_.gross_total.amount,
                  "mesh.net_total": round_.net_total.amount,
                  "mesh.cash_saved": (round_.gross_total - round_.net_total).amount}
        if figure.label_key not in values:
            raise Unverifiable(f"no recomputation for {figure.label_key}")
        return values[figure.label_key]


# ---------------------------------------------------------------------- narration


def _word_part(word: str) -> tuple[str, int] | None:
    """A number word as ("n", value), ("h", 100) or ("s", scale); None otherwise."""
    lower = word.lower()
    if lower in _EN_SMALL:
        return "n", _EN_SMALL[lower]
    if lower == "hundred":
        return "h", 100
    if lower in _EN_SCALES:
        return "s", _EN_SCALES[lower]
    for stem in (word, *(word[:-len(x)] for x in _BN_SUFFIXES if word.endswith(x))):
        if stem in _BN_SMALL:
            return "n", _BN_SMALL[stem]
        if stem in _BN_HUNDRED:
            return "h", 100
        if stem in _BN_SCALES:
            return "s", _BN_SCALES[stem]
    return None


def _phrase_value(parts: list[tuple[str, int]]) -> int:
    total = current = 0
    for kind, value in parts:
        if kind == "n":
            current += value
        elif kind == "h":
            current = (current or 1) * value
        else:
            total += (current or 1) * value
            current = 0
    return total + current


def _zh_value(run: str) -> int:
    total = section = digit = 0
    for char in run:
        if char in _ZH_DIGITS:
            digit = _ZH_DIGITS[char]
        elif char in _ZH_UNITS:
            section += (digit or 1) * _ZH_UNITS[char]
            digit = 0
        else:
            total += ((section + digit) or 1) * _ZH_SECTIONS[char]
            section = digit = 0
    return total + section + digit


def spelled_numbers(text: str) -> set[Decimal]:
    """Values of the numbers written as words in English, Bangla or Chinese."""
    text = unicodedata.normalize("NFC", text)
    values: set[Decimal] = set()
    phrase: list[tuple[str, int]] = []
    words: list[str] = []

    def close() -> None:
        if phrase and words not in (["one"], ["এক"]):
            values.add(Decimal(_phrase_value(phrase)))
        phrase.clear()
        words.clear()

    for match in _WORD.finditer(text):
        word = match.group()
        part = _word_part(word)
        if part is not None:
            phrase.append(part)
            words.append(word.lower())
        elif not (phrase and word.lower() == "and"):
            close()
    close()
    values |= {Decimal(_zh_value(run)) for run in _ZH_RUN.findall(text) if run != "一"}
    return values


def numbers_in(text: str, names: Iterable[str] = ()) -> set[Decimal]:
    """Every number in a text (Bangla digits and numbers written as words too), with entity
    names taken out first."""
    for name in sorted(set(names), key=len, reverse=True):
        text = text.replace(name, " ")
    found = _NUMBER.findall(text.translate(_BANGLA_DIGITS))
    digits = {Decimal(n.replace(",", "").rstrip(".")).normalize() for n in found}
    return digits | {value.normalize() for value in spelled_numbers(text)}


def unverified_numbers(answer: str, verified: Sequence[Statement]) -> set[Decimal]:
    names = [n for s in verified for n in s.names]
    allowed = set().union(*(numbers_in(s.claim.text, s.names) for s in verified)) \
        if verified else set()
    return numbers_in(answer, names) - allowed


def log_rejections(checks: Iterable[CheckResult], claims: Mapping[str, Claim], *,
                   tenant_id: str, recommendation_id: str, now: datetime,
                   session: Any = None) -> int:
    """Log every claim that did not pass; persist it when a session is given."""
    count = 0
    for check in checks:
        if check.status is CheckStatus.verified:
            continue
        claim = claims[check.claim_id]
        log.warning("claim %s %s: %s", claim.id, check.status.value, check.reason)
        if session is not None:
            session.add(RejectedClaimRow(
                tenant_id=tenant_id, recommendation_id=recommendation_id, claim_id=claim.id,
                formula_id=claim.formula_id or "", status=check.status.value,
                claimed=str(claim.value) if claim.value is not None else None,
                recomputed=str(check.recomputed_value)
                if check.recomputed_value is not None else None,
                reason=check.reason or "", created_at=now))
        count += 1
    return count
