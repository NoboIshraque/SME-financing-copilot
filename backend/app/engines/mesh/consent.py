"""Consent workflow for netting rounds (WP-08 milestone 3).

Approving a round is an EXECUTE-tier action: it changes who pays whom. Every participant must
approve with a verified step-up code; one rejection voids the round; rounds expire after 48 h.
Functions return a new round (contracts are immutable).
"""

from __future__ import annotations

from datetime import datetime

from app.contracts import NettingRound, RoundStatus, Tier

APPROVAL_TIER = Tier.EXECUTE


class ConsentError(ValueError):
    """The requested consent change is not allowed."""


def _check_open(round_: NettingRound, tenant: str, now: datetime) -> None:
    if tenant not in round_.participants:
        raise ConsentError(f"{tenant} is not a participant of {round_.id}")
    if round_.status is not RoundStatus.proposed:
        raise ConsentError(f"round {round_.id} is {round_.status.value}, not open for consent")
    if now >= round_.expires_at:
        raise ConsentError(f"round {round_.id} expired at {round_.expires_at.isoformat()}")


def expire_if_due(round_: NettingRound, now: datetime) -> NettingRound:
    if round_.status is RoundStatus.proposed and now >= round_.expires_at:
        return round_.model_copy(update={"status": RoundStatus.expired})
    return round_


def approve(
    round_: NettingRound, tenant: str, *, step_up_verified: bool, now: datetime
) -> NettingRound:
    """Record one participant's approval. A repeated approval is a no-op (idempotent)."""
    if not step_up_verified:
        raise ConsentError("approving a netting round needs a verified step-up code")
    _check_open(round_, tenant, now)
    if round_.approvals.get(tenant) is True:
        return round_
    approvals = {**round_.approvals, tenant: True}
    everyone = set(approvals) == set(round_.participants) and all(approvals.values())
    status = RoundStatus.approved if everyone else RoundStatus.proposed
    return NettingRound.model_validate(
        {**round_.model_dump(), "approvals": approvals, "status": status}
    )


def reject(round_: NettingRound, tenant: str, *, now: datetime) -> NettingRound:
    """Any participant can void the round (no step-up needed to say no)."""
    _check_open(round_, tenant, now)
    approvals = {**round_.approvals, tenant: False}
    return NettingRound.model_validate(
        {**round_.model_dump(), "approvals": approvals, "status": RoundStatus.rejected}
    )


def pending(round_: NettingRound) -> list[str]:
    return [t for t in round_.participants if t not in round_.approvals]
