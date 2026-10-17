"""Business rules enforced by the contracts themselves (one distinct rule per case)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts import (
    AbstentionReason,
    AlertTier,
    AnchorChain,
    ApprovalStatus,
    CheckResult,
    CheckStatus,
    DocumentStatus,
    EligibilityStatus,
    Money,
    RoundStatus,
    Tier,
)
from app.contracts.examples import examples

EX = examples()


def mutate(name: str, **changes):
    """Rebuild an example with changed fields, running every validator again."""
    data = EX[name].model_dump()
    data.update(changes)
    return type(EX[name]).model_validate(data)


CASES = [
    ("Transaction", {"amount": Money.of(0)}, "positive"),
    ("Invoice", {"due_date": EX["Invoice"].issue_date - timedelta(days=1)}, "before issue"),
    ("Invoice", {"amount_paid": Money.of(99999)}, "between 0 and amount"),
    ("Bill", {"paid_date": None}, "paid_date"),
    ("Invoice", {"status": DocumentStatus.paid}, "paid document"),
    ("RecurringObligation", {"frequency": "weekly", "day_of_period": 9}, "weekly"),
    ("ForecastPoint", {"p10": Money.of(500000)}, "p10 <= p50"),
    ("ForecastBand", {"horizon_days": 2}, "one forecast point"),
    ("ForecastBand", {"as_of": EX["ForecastBand"].points[0].day}, "day after as_of"),
    ("CashGap", {"expected_shortfall": Money.of(0)}, "positive expected shortfall"),
    ("CashGap", {"worst_day": EX["CashGap"].first_breach_day - timedelta(days=1)}, "worst day"),
    ("Alert", {"gap": None, "indicators": ()}, "needs a gap"),
    ("SmoothingLever", {"cost": Money.of(-1)}, "non-negative"),
    ("Claim", {"formula_id": None}, "formula_id"),
    ("CheckResult", {"status": CheckStatus.rejected, "reason": None}, "reason"),
    ("AgreementReport", {"agreement_rate": Decimal("0.5")}, "does not match"),
    ("Abstention", {"missing": ()}, "name what is missing"),
    ("Recommendation", {"answer_text": None, "abstention": None}, "answer or abstain"),
    ("StabilityReport", {"score": Decimal("0.5")}, "does not match"),
    ("Scenario", {"worst_5pct_outcome": Money.of(999999)}, "cannot exceed"),
    ("FinancingProduct", {"source_url": None}, "source_url"),
    ("FinancingProduct", {"min_amount": Money.of(9_000_000)}, "min_amount"),
    ("Eligibility", {"status": EligibilityStatus.fail}, "overall status"),
    ("EligibilityRule", {"threshold": None}, "threshold"),
    ("PricePoint", {"low": Money.of(70)}, "low price is above high"),
    ("MeshObligation", {"debtor_tenant": "sme_fabric"}, "cannot owe itself"),
    ("Settlement", {"payee_tenant": "sme_garment"}, "must differ"),
    ("NettingRound", {"net_total": Money.of(2_000_000)}, "net total"),
    ("NettingRound", {"status": RoundStatus.approved}, "every participant"),
    ("NettingRound", {"approvals": {"sme_outsider": True}}, "non-participants"),
    ("AnchorReceipt", {"chain": AnchorChain.sepolia}, "tx_hash"),
    ("Approval", {"step_up_verified": False}, "step-up"),
    ("Approval", {"tier": Tier.DENY}, "DENY"),
    ("Approval", {"decided_by": None}, "who approved"),
    ("Principal", {"role": "lender_viewer"}, "expiry"),
    ("ShareGrant", {"expires_at": EX["ShareGrant"].created_at}, "after created_at"),
    ("Party", {"token": "Rahim Hossain"}, "pattern"),
]


@pytest.mark.parametrize(("name", "changes", "message"), CASES,
                         ids=[f"{c[0]}-{c[2]}" for c in CASES])
def test_contract_rejects_invalid_state(name, changes, message):
    with pytest.raises(ValidationError, match=message):
        mutate(name, **changes)


def test_recommendation_cannot_abstain_and_act_at_once():
    with pytest.raises(ValidationError, match="abstention cannot carry action cards"):
        mutate("Recommendation", abstention=EX["Abstention"].model_dump())


def test_recommendation_cannot_keep_a_rejected_claim():
    rejected = CheckResult(claim_id="claim-1", status=CheckStatus.rejected, reason="mismatch")
    with pytest.raises(ValidationError, match="rejected claims"):
        mutate("Recommendation", checks=(rejected.model_dump(),))


def test_recommendation_allows_at_most_three_action_cards():
    card = EX["ActionCard"].model_dump()
    with pytest.raises(ValidationError):
        mutate("Recommendation", action_cards=(card, card, card, card))


def test_stability_report_flags_noise_flips_as_unreliable():
    report = mutate(
        "StabilityReport",
        results=(
            {"name": "sales_minus_20", "kind": "stress", "choice": "netting", "held": False},
            {"name": "rows_shuffled", "kind": "noise", "choice": "netting", "held": False},
            {"name": "renamed_parties", "kind": "noise", "choice": "retime_payable",
             "held": True},
        ),
        score=Decimal(1) / Decimal(3),
    )
    assert report.noise_flips == 1 and report.unreliable


def test_stability_report_rejects_held_flag_that_contradicts_choice():
    with pytest.raises(ValidationError, match="held flag"):
        mutate(
            "StabilityReport",
            results=({"name": "x", "kind": "stress", "choice": "netting", "held": True},),
            score=Decimal(1),
        )


def test_netting_example_conserves_cash_saving():
    rnd = EX["NettingRound"]
    assert rnd.cash_saved == Money.of(1_020_000)


def test_document_outstanding_and_alert_tier_order():
    assert EX["Invoice"].outstanding == Money.of(4200)
    assert AlertTier.watch.rank < AlertTier.warning.rank < AlertTier.critical.rank


def test_insufficient_data_is_the_only_reason_requiring_missing_list():
    for reason in AbstentionReason:
        if reason is AbstentionReason.insufficient_data:
            continue
        assert mutate("Abstention", reason=reason, missing=()).missing == ()


def test_approval_pending_needs_no_decider():
    pending = mutate("Approval", status=ApprovalStatus.pending, decided_by=None,
                     step_up_verified=False)
    assert pending.status is ApprovalStatus.pending
