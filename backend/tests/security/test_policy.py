import pytest

from app.contracts import ActionCard, ActionType, Role, Tier
from app.security import policy

# Written out independently of app.security.policy (columns: owner, accountant, staff,
# lender_viewer, compliance). R=READ S=SUGGEST D=DRAFT E=EXECUTE X=DENY.
EXPECTED = """
view                      R R R R R
record_dispute            D D D X X
draft_loan_application    D D X X X
submit_loan_application   E D X X X
propose_netting_round     D D X X X
send_reminder             E D D X X
send_message              E D D X X
retime_payable            E D S X X
request_advance           E D X X X
offer_early_pay_discount  E D S X X
approve_netting_round     E S X X X
share_passport            E D X X X
set_credit_limit          E D S X X
move_money                E D X X X
change_bank_details       X X X X X
add_payee                 X X X X X
disable_audit             X X X X X
export_raw_pii            X X X X X
"""
LETTER = {"R": Tier.READ, "S": Tier.SUGGEST, "D": Tier.DRAFT, "E": Tier.EXECUTE, "X": Tier.DENY}
ROLES = [Role.owner, Role.accountant, Role.staff, Role.lender_viewer, Role.compliance]
TABLE = {
    ActionType(line.split()[0]): dict(zip(ROLES, (LETTER[c] for c in line.split()[1:]),
                                          strict=True))
    for line in EXPECTED.strip().splitlines()
}


def test_the_expected_table_covers_every_action_type():
    assert set(TABLE) == set(ActionType)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("action", list(ActionType))
def test_tier_matrix(role, action):
    assert policy.role_tier(role, action) is TABLE[action][role]


@pytest.mark.parametrize("action", ["change_bank_details", "add_payee", "disable_audit",
                                    "export_raw_pii"])
def test_deny_list_is_denied_for_every_role_even_the_owner(action):
    for role in ROLES:
        decision = policy.decide(role, ActionType(action))
        assert not decision.allowed and decision.reason == "policy.denied"


@pytest.mark.parametrize(("role", "action", "allowed", "needs_approval", "reason"), [
    (Role.owner, ActionType.move_money, True, True, "policy.allowed"),
    (Role.accountant, ActionType.move_money, False, False, "policy.tier_too_low"),
    (Role.owner, ActionType.draft_loan_application, True, False, "policy.allowed"),
    (Role.staff, ActionType.record_dispute, True, False, "policy.allowed"),
    (Role.staff, ActionType.retime_payable, False, False, "policy.tier_too_low"),
    (Role.lender_viewer, ActionType.view, True, False, "policy.allowed"),
    (Role.compliance, ActionType.send_reminder, False, False, "policy.denied"),
])
def test_decisions(role, action, allowed, needs_approval, reason):
    decision = policy.decide(role, action)
    assert (decision.allowed, decision.needs_approval, decision.reason) == \
        (allowed, needs_approval, reason)


def test_a_card_can_raise_its_tier_but_never_lower_it():
    lowered = ActionCard(id="c1", title_key="t", action_type=ActionType.move_money,
                         tier=Tier.READ)
    raised = ActionCard(id="c2", title_key="t", action_type=ActionType.record_dispute,
                        tier=Tier.EXECUTE)
    denied = ActionCard(id="c3", title_key="t", action_type=ActionType.view, tier=Tier.DENY)
    assert policy.card_tier(lowered) is Tier.EXECUTE
    assert policy.card_tier(raised) is Tier.EXECUTE
    assert policy.card_tier(denied) is Tier.DENY
    assert not policy.decide(Role.staff, ActionType.record_dispute, Tier.EXECUTE).allowed


@pytest.mark.parametrize(("role", "action", "may"), [
    (Role.accountant, ActionType.move_money, True),  # drafts it for the owner
    (Role.staff, ActionType.send_reminder, True),
    (Role.staff, ActionType.retime_payable, False),  # may only suggest
    (Role.compliance, ActionType.share_passport, False),
    (Role.owner, ActionType.add_payee, False),
])
def test_who_may_request_an_execute_action(role, action, may):
    assert policy.may_request(role, action) is may


def test_policy_table_export_matches_the_policy():
    exported = policy.table()
    assert exported["move_money"] == {"required": "EXECUTE", "owner": "EXECUTE",
                                      "accountant": "DRAFT", "staff": "DENY",
                                      "lender_viewer": "DENY", "compliance": "DENY"}
    assert set(exported) == {action.value for action in ActionType}
