from decimal import Decimal

import pytest

from app.agents import abstention as abstain
from app.agents.agreement import AgreementOutcome, Judgement
from app.agents.stakes import Stakes
from app.contracts import (
    AbstentionReason,
    AgreementReport,
    CheckResult,
    CheckStatus,
    StabilityReport,
    VariationKind,
    VariationResult,
    Vote,
)
from app.security.audit import AuditLog
from tests.agents.helpers import NOW, seeded_store

OK = CheckResult(claim_id="c1", status=CheckStatus.verified, recomputed_value=Decimal(1))
BAD = CheckResult(claim_id="c2", status=CheckStatus.rejected, recomputed_value=Decimal(2),
                  reason="recomputation gives a different value")
UNSURE = CheckResult(claim_id="c3", status=CheckStatus.unverifiable, reason="no path")
JUDGEMENT = Judgement("fix", "q", ({"id": "a", "summary": "a"}, {"id": "b", "summary": "b"}), "a")


def agreement(choices, stakes):
    votes = tuple(Vote(model=f"m{i}", choice=c) for i, c in enumerate(choices))
    winner = max(set(choices), key=lambda c: (choices.count(c), c == "a"))
    rate = Decimal(choices.count(winner)) / Decimal(len(choices))
    return AgreementOutcome(AgreementReport(
        question="q", votes=votes, winning_choice=winner, agreement_rate=rate,
        threshold=stakes.agreement_threshold, stakes=stakes.value), JUDGEMENT)


def stability(noise_held=True, stress_held=True):
    results = (VariationResult(name="sales_minus_10", kind=VariationKind.stress,
                               choice="a" if stress_held else "b", held=stress_held),
               VariationResult(name="seed_changed", kind=VariationKind.noise,
                               choice="a" if noise_held else "b", held=noise_held))
    held = sum(r.held for r in results)
    return StabilityReport(recommendation_id="r", baseline_choice="a", results=results,
                           score=Decimal(held) / 2)


@pytest.mark.parametrize(("stakes", "checks", "agreed", "stable", "reason"), [
    (Stakes.high, (OK,), None, None, None),
    (Stakes.low, (UNSURE,), None, None, AbstentionReason.unverifiable),  # nothing verified
    (Stakes.low, (OK, BAD), None, None, None),  # removed, the rest stands
    (Stakes.medium, (OK, BAD), None, None, None),
    (Stakes.high, (OK, BAD), None, None, AbstentionReason.unverifiable),  # nothing shown
    (Stakes.high, (OK, UNSURE), None, None, None),  # unverifiable is removed, not fatal
    (Stakes.medium, (OK,), ("a", "a", "b"), None, None),
    (Stakes.high, (OK,), ("a", "a", "b"), None, AbstentionReason.low_agreement),
    (Stakes.medium, (OK,), ("a", "b", "b"), None, AbstentionReason.low_agreement),  # outvoted
    (Stakes.high, (OK,), ("a", "a", "a"), (True, False), None),  # stress may flip it
    (Stakes.high, (OK,), ("a", "a", "a"), (False, True), AbstentionReason.unverifiable),
])
def test_abstention_triggers(stakes, checks, agreed, stable, reason):
    outcome = agreement(list(agreed), stakes) if agreed else None
    report = stability(*stable) if stable else None
    decided = abstain.after_checks(stakes, checks, outcome, report)
    assert (decided.reason if decided else None) is reason


def test_a_low_agreement_abstention_says_who_won_and_what_was_needed():
    decided = abstain.after_checks(Stakes.high, (OK,), agreement(["a", "b", "b"], Stakes.high),
                                   None)
    assert decided.message_key == "abstain.low_agreement"
    assert decided.detail == "b won 2 of 3 votes; high stakes need 1 for code's choice a"


def test_an_unreliable_decision_names_the_noise_that_flipped_it():
    decided = abstain.after_checks(Stakes.medium, (OK,), None, stability(noise_held=False))
    assert decided.detail.endswith("seed_changed")


@pytest.mark.parametrize(("build", "reason", "missing"), [
    (lambda: abstain.insufficient_data(["at least 8 weeks of transactions"] * 2),
     AbstentionReason.insufficient_data, ("at least 8 weeks of transactions",)),
    (lambda: abstain.out_of_scope(["WP-05 receivables engine"]), AbstentionReason.out_of_scope,
     ("WP-05 receivables engine",)),
    (lambda: abstain.budget_exhausted(["cash.gaps"]), AbstentionReason.budget_exhausted,
     ("cash.gaps",)),
    (lambda: abstain.policy("quarantined:q1"), AbstentionReason.policy, ()),
])
def test_every_abstention_uses_the_web_message_key_and_names_what_is_missing(build, reason,
                                                                              missing):
    made = build()
    assert (made.reason, made.missing, made.message_key) == (reason, missing,
                                                             f"abstain.{reason.value}")


def test_insufficient_data_must_name_what_is_missing():
    with pytest.raises(ValueError, match="must name what is missing"):
        abstain.insufficient_data([])


def test_every_abstention_is_logged_and_audited(universe):
    engine, session, _store = seeded_store(universe, shops=())
    made = abstain.insufficient_data(["at least 8 weeks of transactions"])
    abstain.record(session, tenant_id="short_shop", recommendation_id="rec_1",
                   question="Will I run out of cash?", abstention=made, stakes=Stakes.low,
                   actor="u-owner", now=NOW)
    session.flush()
    [row] = abstain.history(session, "short_shop")
    assert (row.question, row.stakes) == ("Will I run out of cash?", "low")
    assert abstain.as_contract(row) == made
    assert abstain.history(session, "someone_else") == []
    [event] = AuditLog(session).events("short_shop")
    assert (event.action, event.target, event.actor) == ("copilot.abstain", "rec_1", "u-owner")
    session.close()
    engine.dispose()
