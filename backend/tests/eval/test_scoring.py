"""The scoring rules catch the defect each one targets, on real runs that are then broken."""

import dataclasses
from decimal import Decimal

import pytest

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.api import cash as cash_api
from app.contracts import Money, Role
from eval.runner import Bench, offline_settings, run_task
from eval.scoring import DEEP, numbers, score
from eval.tasks import FUNCTIONAL, adversarial


def task(task_id):
    return next(t for t in (*FUNCTIONAL, *adversarial()) if t.id == task_id)


@pytest.fixture(scope="module")
def bench(universe):
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()
    bench = Bench.build(offline_settings(), universe)
    yield bench
    bench.close()
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()


@pytest.fixture(scope="module")
def runs(bench):
    ids = ("F.mesh.netting", "F.whatif.sales_drop", "F.cash.gap.en", "F.abstain.thin_history",
           "A.skip_approval.en.0")
    return {i: run_task(bench, task(i)) for i in ids}


def failed(checks):
    return {c.name for c in checks if not c.passed}


def with_rec(run, **update):
    return dataclasses.replace(run, recommendation=run.recommendation.model_copy(update=update))


def test_real_runs_pass_their_own_rules(runs):
    assert {i: failed(r.checks) for i, r in runs.items()} == {i: set() for i in runs}


def test_netting_rule_recomputes_every_position_from_the_raw_debts(runs, bench):
    record = runs["F.mesh.netting"]
    result = record.run.results["mesh.propose"]
    round_ = result.payload["round"]
    first = round_.settlements[0]
    skewed = round_.model_copy(update={"settlements": (
        first.model_copy(update={"amount": Money.of(first.amount.amount + 1)}),
        *round_.settlements[1:])})
    broken = dataclasses.replace(record.run, results={
        **record.run.results,
        "mesh.propose": dataclasses.replace(result, payload={**result.payload, "round": skewed})})
    check = DEEP["netting_valid"](broken, record.task, bench)
    assert not check.passed
    assert "settles" in check.detail and "net" in check.detail


def test_an_invented_number_in_the_answer_is_caught(runs, bench):
    record = runs["F.whatif.sales_drop"]
    run = with_rec(record.run, answer_text=record.run.recommendation.answer_text
                   + " You will also save Tk 12,345.")
    assert failed(score(record.task, run, bench)) == {"numbers_traced"}


def test_a_claim_that_does_not_recompute_fails(runs, bench):
    record = runs["F.whatif.sales_drop"]
    rec = record.run.recommendation
    claim = rec.claims[0].model_copy(update={"value": rec.claims[0].value + 1})
    run = with_rec(record.run, claims=(claim, *rec.claims[1:]))
    assert "claims_recomputed" in failed(score(record.task, run, bench))


def test_a_shock_that_improves_the_forecast_fails(runs, bench):
    record = runs["F.whatif.sales_drop"]
    result = record.run.results["analysis.scenarios"]
    before, after = result.payload["before"], result.payload["after"]
    run = dataclasses.replace(record.run, results={"analysis.scenarios": dataclasses.replace(
        result, payload={**result.payload, "before": after, "after": before})})
    assert not DEEP["scenario_worse"](run, record.task, bench).passed


def test_cards_beyond_the_callers_role_fail(runs, bench):
    record = runs["F.cash.gap.en"]
    assert record.run.recommendation.action_cards  # the owner gets cards to approve
    as_lender = dataclasses.replace(record.task, role=Role.lender_viewer)
    assert "cards_need_approval" in failed(score(as_lender, record.run, bench))


def test_wrong_outcome_and_wrong_tools_fail(runs, bench):
    record = runs["F.abstain.thin_history"]
    expect = dataclasses.replace(record.task.expect, abstain=None, calls=("cash.forecast",))
    checks = score(dataclasses.replace(record.task, expect=expect), record.run, bench)
    assert {"outcome", "tool_calls"} <= failed(checks)


def test_an_echoed_attack_is_not_counted_as_quarantined(runs, bench):
    record = runs["A.skip_approval.en.0"]
    echoed = with_rec(record.run, question=record.task.question)
    assert not DEEP["quarantined"](echoed, record.task, bench).passed


@pytest.mark.parametrize(("text", "expected"), [
    ("Tk 9,29,018 and 86.70%", {Decimal(929018), Decimal("86.7")}),
    ("৭৩,৪৬০.৯০ টাকা", {Decimal("73460.9")}),
])
def test_numbers_reads_south_asian_grouping_and_bangla_digits(text, expected):
    assert numbers(text) == expected
