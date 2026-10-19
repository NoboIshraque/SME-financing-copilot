"""Stakes of a recommendation, and what each level costs (WP-10 milestones 5-8; N9, N10, N17).

    low     information only (a forecast, ratios)
    medium  something to draft or agree with others (netting, a reminder, a what-if)
    high    borrowing or moving money (a loan, an advance, an early-pay discount)

Moving money is always a human decision (EXECUTE tier, WP-11); the stakes decide how much
checking happens *before* the owner is asked: the critic from medium up, model agreement and
its threshold, and how many stressed reruns the self-loop makes.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum

from app.contracts import ActionCard, ActionType

A = ActionType
HIGH_ACTIONS = frozenset({A.draft_loan_application, A.submit_loan_application, A.request_advance,
                          A.offer_early_pay_discount, A.retime_payable, A.move_money,
                          A.approve_netting_round, A.set_credit_limit, A.share_passport})
HIGH_INTENTS = frozenset({"find_financing"})
MEDIUM_INTENTS = frozenset({"settle_debts", "what_if", "negotiate", "draft_message",
                            "collect_receivables"})


class Stakes(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2}[self.value]

    @property
    def agreement_threshold(self) -> Decimal:
        """Share of votes that must agree: a majority, two in three, everyone."""
        return {"low": Decimal("0.5"), "medium": Decimal("0.66"), "high": Decimal(1)}[self.value]

    @property
    def needs_critic(self) -> bool:
        return self is not Stakes.low

    @property
    def needs_agreement(self) -> bool:
        return self is not Stakes.low

    @property
    def stress_runs(self) -> int:
        """Variations the self-loop runs (N10): none, a few, more."""
        return {"low": 0, "medium": 2, "high": 4}[self.value]


def assess(intents: Iterable[str], cards: Iterable[ActionCard]) -> Stakes:
    intents, cards = set(intents), list(cards)
    if intents & HIGH_INTENTS or any(c.action_type in HIGH_ACTIONS for c in cards):
        return Stakes.high
    if intents & MEDIUM_INTENTS or cards:
        return Stakes.medium
    return Stakes.low
