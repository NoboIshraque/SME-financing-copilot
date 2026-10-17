"""Agent outputs (WP-10): claims, checks, votes, abstentions, recommendations, action cards.

A Recommendation never contains a number that is not backed by a verified Claim or a Figure.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.contracts.analysis import StabilityReport
from app.contracts.common import Contract, DataMode, Probability, Tier
from app.contracts.facts import Figure, Unit


class Claim(Contract):
    id: str
    text: str
    value: Decimal | None = None
    unit: Unit | None = None
    formula_id: str | None = None
    input_fact_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _numeric_claims_need_formula(self) -> Claim:
        if self.value is not None and (self.formula_id is None or self.unit is None):
            raise ValueError("a numeric claim needs formula_id and unit so it can be checked")
        return self


class CheckStatus(StrEnum):
    verified = "verified"
    rejected = "rejected"
    unverifiable = "unverifiable"


class CheckResult(Contract):
    claim_id: str
    status: CheckStatus
    recomputed_value: Decimal | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _reason_when_not_verified(self) -> CheckResult:
        if self.status is not CheckStatus.verified and not self.reason:
            raise ValueError("rejected or unverifiable checks must give a reason")
        return self


class Vote(Contract):
    model: str = Field(description="Provider/model id, e.g. 'groq:gpt-oss-120b'")
    choice: str
    rationale: str | None = None


class AgreementReport(Contract):
    question: str
    votes: tuple[Vote, ...] = Field(min_length=1)
    winning_choice: str
    agreement_rate: Probability
    threshold: Probability
    stakes: str = Field(description="low | medium | high")

    @model_validator(mode="after")
    def _rate_matches_votes(self) -> AgreementReport:
        agreeing = sum(1 for vote in self.votes if vote.choice == self.winning_choice)
        expected = Decimal(agreeing) / Decimal(len(self.votes))
        if abs(expected - self.agreement_rate) > Decimal("0.0001"):
            raise ValueError("agreement_rate does not match the votes")
        return self

    @property
    def passed(self) -> bool:
        return self.agreement_rate >= self.threshold


class AbstentionReason(StrEnum):
    insufficient_data = "insufficient_data"
    low_agreement = "low_agreement"
    unverifiable = "unverifiable"
    out_of_scope = "out_of_scope"
    policy = "policy"
    budget_exhausted = "budget_exhausted"


class Abstention(Contract):
    reason: AbstentionReason
    missing: tuple[str, ...] = Field(
        default=(), description="Exactly what is missing, e.g. 'at least 90 days of sales'"
    )
    message_key: str
    detail: str | None = None

    @model_validator(mode="after")
    def _say_what_is_missing(self) -> Abstention:
        if self.reason is AbstentionReason.insufficient_data and not self.missing:
            raise ValueError("an insufficient-data abstention must name what is missing")
        return self


class ActionType(StrEnum):
    view = "view"
    send_reminder = "send_reminder"
    send_message = "send_message"
    draft_loan_application = "draft_loan_application"
    retime_payable = "retime_payable"
    request_advance = "request_advance"
    offer_early_pay_discount = "offer_early_pay_discount"
    propose_netting_round = "propose_netting_round"
    approve_netting_round = "approve_netting_round"
    share_passport = "share_passport"
    set_credit_limit = "set_credit_limit"
    record_dispute = "record_dispute"
    change_bank_details = "change_bank_details"
    add_payee = "add_payee"
    disable_audit = "disable_audit"
    export_raw_pii = "export_raw_pii"
    move_money = "move_money"


class ActionCard(Contract):
    id: str
    title_key: str
    action_type: ActionType
    tier: Tier
    payload: dict[str, Any] = Field(default_factory=dict)
    figures: tuple[Figure, ...] = ()
    impact: Figure | None = Field(default=None, description="Effect, e.g. gap reduced by Tk X")
    cost: Figure | None = None
    expires_at: datetime | None = None

    @property
    def requires_approval(self) -> bool:
        return self.tier.needs_owner_approval


class Recommendation(Contract):
    id: str
    tenant_id: str
    question: str
    answer_text: str | None = None
    claims: tuple[Claim, ...] = ()
    checks: tuple[CheckResult, ...] = ()
    action_cards: tuple[ActionCard, ...] = Field(default=(), max_length=3)
    figures: tuple[Figure, ...] = ()
    critic_objection: str | None = None
    agreement: AgreementReport | None = None
    stability: StabilityReport | None = None
    abstention: Abstention | None = None
    tools_used: tuple[str, ...] = ()
    data_mode: DataMode
    created_at: datetime

    @model_validator(mode="after")
    def _answer_xor_abstain(self) -> Recommendation:
        if self.abstention is None and not self.answer_text:
            raise ValueError("a recommendation must answer or abstain")
        if self.abstention is not None and self.action_cards:
            raise ValueError("an abstention cannot carry action cards")
        rejected = {c.claim_id for c in self.checks if c.status is CheckStatus.rejected}
        if rejected & {claim.id for claim in self.claims}:
            raise ValueError("rejected claims must be removed before the recommendation is built")
        return self
