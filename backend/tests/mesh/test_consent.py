from datetime import timedelta

import pytest

from app.contracts import RoundStatus, Tier
from app.engines.mesh.consent import (
    APPROVAL_TIER,
    ConsentError,
    approve,
    expire_if_due,
    pending,
    reject,
)
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import propose_rounds
from tests.mesh.helpers import NOW, ring

LATER = NOW + timedelta(hours=1)


@pytest.fixture
def proposed():
    edges = ring(("a", "b", 100), ("b", "c", 80), ("c", "a", 60))
    return propose_rounds(build_graph(edges), now=NOW)[0]


def test_approving_is_an_execute_tier_action():
    assert APPROVAL_TIER is Tier.EXECUTE


def test_approval_without_step_up_is_refused(proposed):
    with pytest.raises(ConsentError, match="step-up"):
        approve(proposed, "a", step_up_verified=False, now=LATER)


def test_partial_approval_keeps_the_round_open(proposed):
    r = approve(proposed, "a", step_up_verified=True, now=LATER)
    assert r.status is RoundStatus.proposed
    assert pending(r) == ["b", "c"]


def test_everyone_approving_approves_the_round(proposed):
    r = proposed
    for tenant in ("c", "a", "b"):
        r = approve(r, tenant, step_up_verified=True, now=LATER)
    assert r.status is RoundStatus.approved and pending(r) == []


def test_double_approval_is_idempotent(proposed):
    once = approve(proposed, "a", step_up_verified=True, now=LATER)
    assert approve(once, "a", step_up_verified=True, now=LATER) == once


def test_one_rejection_voids_the_round(proposed):
    r = approve(proposed, "a", step_up_verified=True, now=LATER)
    r = reject(r, "b", now=LATER)
    assert r.status is RoundStatus.rejected and r.approvals == {"a": True, "b": False}


def test_no_approval_after_rejection(proposed):
    r = reject(proposed, "b", now=LATER)
    with pytest.raises(ConsentError, match="rejected"):
        approve(r, "a", step_up_verified=True, now=LATER)


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_outsiders_cannot_take_part(proposed, action):
    with pytest.raises(ConsentError, match="not a participant"):
        if action == "approve":
            approve(proposed, "mallory", step_up_verified=True, now=LATER)
        else:
            reject(proposed, "mallory", now=LATER)


def test_approval_after_expiry_is_refused(proposed):
    with pytest.raises(ConsentError, match="expired"):
        approve(proposed, "a", step_up_verified=True, now=proposed.expires_at)


def test_expire_if_due_only_expires_open_rounds(proposed):
    assert expire_if_due(proposed, LATER).status is RoundStatus.proposed
    assert expire_if_due(proposed, proposed.expires_at).status is RoundStatus.expired
    rejected = reject(proposed, "a", now=LATER)
    assert expire_if_due(rejected, proposed.expires_at).status is RoundStatus.rejected


def test_an_approved_round_cannot_be_rejected_afterwards(proposed):
    r = proposed
    for tenant in ("a", "b", "c"):
        r = approve(r, tenant, step_up_verified=True, now=LATER)
    with pytest.raises(ConsentError, match="approved"):
        reject(r, "a", now=LATER)
