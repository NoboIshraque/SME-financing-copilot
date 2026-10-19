from decimal import Decimal

import pytest

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.agents.agreement import Judgement
from app.agents.selfloop import Decider, self_loop, stability
from app.agents.stakes import Stakes
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.contracts import VariationKind
from tests.agents.helpers import NOW, seeded_store

FIX = Judgement("fix", "q", ({"id": "a", "summary": "a"}, {"id": "b", "summary": "b"}), "a")
OPTION = Judgement("financing_option", "q", FIX.options, "a")


@pytest.fixture(scope="module")
def hardware(universe):
    cash_api.clear_cache()
    checker_cache.clear_cache()
    selfloop.clear_cache()
    engine, session, store = seeded_store(universe, shops=("sme_hardware",))
    ctx = ToolContext(store, "sme_hardware", NOW)
    REGISTRY.run("cash.gaps", ctx)
    yield ctx
    session.close()
    engine.dispose()
    cash_api.clear_cache()
    checker_cache.clear_cache()
    selfloop.clear_cache()


def test_the_first_fix_holds_except_when_customers_pay_a_week_later(hardware):
    report = self_loop(hardware, FIX, Stakes.high, hardware.results, "rec_1")
    assert report.baseline_choice.startswith("advance:sme_hardware:")
    choices = {r.name: (r.kind, r.held) for r in report.results}
    assert choices == {"sales_minus_10": (VariationKind.stress, True),
                       "customers_7_days_late": (VariationKind.stress, False),
                       "seed_changed": (VariationKind.noise, True),
                       "tiny_expense": (VariationKind.noise, True)}
    assert report.what_would_flip == ("customers_7_days_late",)
    assert report.score == Decimal("0.75") and not report.unreliable


def test_the_financing_choice_holds_under_every_variation(hardware):
    report = self_loop(hardware, OPTION, Stakes.high, hardware.results, "rec_2")
    assert report.baseline_choice == "bd-bb-startup-fund"
    assert report.score == 1 and report.what_would_flip == ()


@pytest.mark.parametrize(("stakes", "names"), [
    (Stakes.medium, ["sales_minus_10", "seed_changed"]),
    (Stakes.high, ["sales_minus_10", "customers_7_days_late", "seed_changed", "tiny_expense"]),
])
def test_more_variations_at_higher_stakes(hardware, stakes, names):
    report = self_loop(hardware, OPTION, stakes, hardware.results, "rec_3")
    assert [r.name for r in report.results] == names
    assert {r.kind for r in report.results} == {VariationKind.stress, VariationKind.noise}


@pytest.mark.parametrize(("judgement", "stakes"), [
    (None, Stakes.high),
    (Judgement("intent", "q", FIX.options, "a"), Stakes.high),  # not an engine decision
    (FIX, Stakes.low),
])
def test_no_loop_when_there_is_nothing_to_stress(hardware, judgement, stakes):
    assert self_loop(hardware, judgement, stakes, hardware.results, "rec_4") is None


def test_results_are_cached_per_ledger_revision(hardware, monkeypatch):
    self_loop(hardware, FIX, Stakes.medium, hardware.results, "rec_5")
    calls = []
    monkeypatch.setattr(selfloop, "run", lambda *a, **k: calls.append(a) or None)
    again = self_loop(hardware, FIX, Stakes.medium, hardware.results, "rec_6")
    assert calls == [] and again.recommendation_id == "rec_6"


class Jittery(Decider):
    """A decision that changes with the Monte Carlo seed: noise flips it."""

    def choice(self, variation=None):
        return "other" if variation is not None and variation.name == "seed_changed" else "a"


def test_a_decision_that_flips_on_noise_is_unreliable(hardware):
    decider = Jittery(hardware, "fix", 20261020, hardware.results["cash.gaps"].payload["buffer"])
    report = stability(decider, Stakes.medium, "rec_7")
    assert report.unreliable and report.noise_flips == 1
    assert report.what_would_flip == ()  # noise is not a reason the decision may change
