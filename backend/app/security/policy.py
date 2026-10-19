"""Permission tiers: the one policy table (WP-11 milestone 3; FEATURES P2).

Two questions, both answered here and nowhere else:

1. What does an action *need*? (`REQUIRED`) READ to look, DRAFT to prepare something that
   stays inside Hishab, EXECUTE for anything that leaves it (a message, a payment, data shared
   with a lender), DENY for what no one may do through Hishab at all.
2. How far may a role take it? (`POLICY`) A role holding less than the action needs may still
   suggest or draft it for someone who holds more.

EXECUTE always means: an owner approved this exact action card with a fresh TOTP code, the
approval is under 24 hours old, and the policy still allows it at the moment it runs.
An action card's own `tier` can raise the requirement, never lower it, so a card written by
the language model cannot talk its way down a tier.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts import ActionCard, ActionType, Role, Tier

A = ActionType
R, S, D, E, X = Tier.READ, Tier.SUGGEST, Tier.DRAFT, Tier.EXECUTE, Tier.DENY

DENY_LIST = frozenset({A.change_bank_details, A.add_payee, A.disable_audit, A.export_raw_pii})

REQUIRED: dict[ActionType, Tier] = {
    A.view: R,
    A.record_dispute: D,
    A.draft_loan_application: D,
    A.submit_loan_application: E,
    A.propose_netting_round: D,
    A.send_reminder: E,
    A.send_message: E,
    A.retime_payable: E,
    A.request_advance: E,
    A.offer_early_pay_discount: E,
    A.approve_netting_round: E,
    A.share_passport: E,
    A.set_credit_limit: E,
    A.move_money: E,
    **{action: X for action in DENY_LIST},
}

ROLES = (Role.owner, Role.accountant, Role.staff, Role.lender_viewer, Role.compliance)

# Highest tier each role holds per action.  owner accountant staff lender compliance
POLICY: dict[ActionType, tuple[Tier, Tier, Tier, Tier, Tier]] = {
    A.view:                     (R, R, R, R, R),
    A.record_dispute:           (D, D, D, X, X),
    A.draft_loan_application:   (D, D, X, X, X),
    A.submit_loan_application:  (E, D, X, X, X),
    A.propose_netting_round:    (D, D, X, X, X),
    A.send_reminder:            (E, D, D, X, X),
    A.send_message:             (E, D, D, X, X),
    A.retime_payable:           (E, D, S, X, X),
    A.request_advance:          (E, D, X, X, X),
    A.offer_early_pay_discount: (E, D, S, X, X),
    A.approve_netting_round:    (E, S, X, X, X),
    A.share_passport:           (E, D, X, X, X),
    A.set_credit_limit:         (E, D, S, X, X),
    A.move_money:               (E, D, X, X, X),
    A.change_bank_details:      (X, X, X, X, X),
    A.add_payee:                (X, X, X, X, X),
    A.disable_audit:            (X, X, X, X, X),
    A.export_raw_pii:           (X, X, X, X, X),
}

_RANK = {R: 0, S: 1, D: 2, E: 3}


def rank(tier: Tier) -> int:
    """Order of the allowed tiers; DENY is above everything (nothing reaches it)."""
    return _RANK.get(tier, 99)


def role_tier(role: Role, action: ActionType) -> Tier:
    return POLICY[action][ROLES.index(role)]


def required_tier(action: ActionType, card_tier: Tier | None = None) -> Tier:
    """What the action needs; a card may only raise it."""
    needed = REQUIRED[action]
    if card_tier is not None and rank(card_tier) > rank(needed):
        return card_tier
    return needed


def card_tier(card: ActionCard) -> Tier:
    return required_tier(card.action_type, card.tier)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    held: Tier  # the role's tier for this action
    required: Tier  # what the action needs
    reason: str  # i18n key

    @property
    def needs_approval(self) -> bool:
        return self.allowed and self.required is Tier.EXECUTE


def decide(role: Role, action: ActionType, card_tier: Tier | None = None) -> Decision:
    required = required_tier(action, card_tier)
    held = role_tier(role, action)
    if required is Tier.DENY or held is Tier.DENY:
        return Decision(False, held, required, "policy.denied")
    if rank(held) < rank(required):
        return Decision(False, held, required, "policy.tier_too_low")
    return Decision(True, held, required, "policy.allowed")


def may_request(role: Role, action: ActionType) -> bool:
    """A role may ask for an EXECUTE action if it can at least draft it."""
    held = role_tier(role, action)
    return held is not Tier.DENY and rank(held) >= rank(Tier.DRAFT)


def table() -> dict[str, dict[str, str]]:
    """The policy as plain data: for the web's tier labels and the self-assessment."""
    return {action.value: {"required": REQUIRED[action].value,
                           **{role.value: role_tier(role, action).value for role in ROLES}}
            for action in ActionType}
