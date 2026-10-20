"""Approvals for EXECUTE actions (WP-11 milestone 3).

    approvals = Approvals(db)
    a = approvals.request(principal, card, idempotency_key, now)    # pending, expires in 24 h
    a = approvals.approve(owner, a.id, step_up_verified=True, now)  # owner + fresh TOTP
    out = approvals.execute(principal, a.id, execution_key, now)    # runs once, re-checks policy

The approved card is stored with its SHA-256; execution refuses a card that changed, an
approval past 24 hours, an approver who is no longer an active owner, and any action the
policy no longer allows. Repeating a request or an execution with the same idempotency key
returns the first result instead of acting twice. No executor here moves money: by default an
executed action is recorded only, and other work packages register real executors.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionCard, ActionType, Approval, ApprovalStatus, Principal, Role, Tier
from app.security import policy
from app.security.models import ApprovalRow, IssuedCardRow, UserRow
from app.security.roles import Permission, has_permission

APPROVAL_LIFETIME = timedelta(hours=24)
MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 128

Executor = Callable[[ActionCard, Approval], dict[str, str]]


class ApprovalProblem(ValueError):
    def __init__(self, status: int, code: str, **detail: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail


def record_only(card: ActionCard, approval: Approval) -> dict[str, str]:
    return {"status": "recorded", "action_type": card.action_type.value,
            "note": "no external system is connected; the approved action is recorded only"}


_EXECUTORS: dict[ActionType, Executor] = {}


def register_executor(action_type: ActionType, executor: Executor) -> None:
    if action_type in policy.DENY_LIST:
        raise ValueError(f"{action_type.value} is on the DENY list")
    _EXECUTORS[action_type] = executor


def executor_for(action_type: ActionType) -> Executor:
    return _EXECUTORS.get(action_type, record_only)


def card_digest(card: ActionCard) -> str:
    canonical = json.dumps(card.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def issue_cards(db: Session, tenant_id: str, cards: Iterable[ActionCard], now: datetime) -> None:
    """Record the EXECUTE-tier cards an engine route is about to return (known risk R3)."""
    for card in cards:
        if policy.card_tier(card) is not Tier.EXECUTE:
            continue
        digest = card_digest(card)
        if db.get(IssuedCardRow, (tenant_id, digest)) is None:
            db.add(IssuedCardRow(tenant_id=tenant_id, card_digest=digest, issued_at=now))
    db.flush()


def check_key(key: str | None) -> str:
    if key is None or not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH or not key.isprintable():
        raise ApprovalProblem(400, "idempotency_key_required",
                              min_length=str(MIN_KEY_LENGTH))
    return key


@dataclass(frozen=True)
class Execution:
    approval: Approval
    result: dict[str, str]
    replayed: bool


def to_contract(row: ApprovalRow) -> Approval:
    return Approval(id=row.id, tenant_id=row.tenant_id, action_card_id=row.action_card_id,
                    tier=Tier(row.tier), requested_by=row.requested_by,
                    decided_by=row.decided_by, status=ApprovalStatus(row.status),
                    step_up_verified=row.step_up_verified,
                    idempotency_key=row.idempotency_key, created_at=row.created_at,
                    expires_at=row.expires_at)


def stored_card(row: ApprovalRow) -> ActionCard:
    return ActionCard.model_validate_json(row.card_json)


class Approvals:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _load(self, principal: Principal, approval_id: str, now: datetime) -> ApprovalRow:
        row = self.db.get(ApprovalRow, approval_id)
        if row is None or row.tenant_id != principal.tenant_id:
            raise ApprovalProblem(404, "not_found")
        self._expire(row, now)
        return row

    def _expire(self, row: ApprovalRow, now: datetime) -> None:
        live = (ApprovalStatus.pending.value, ApprovalStatus.approved.value)
        if row.status in live and now >= row.expires_at:
            row.status = ApprovalStatus.expired.value
            self.db.flush()

    def get(self, principal: Principal, approval_id: str, now: datetime) -> ApprovalRow:
        return self._load(principal, approval_id, now)

    def list(self, principal: Principal, now: datetime,
             status: ApprovalStatus | None = None) -> list[ApprovalRow]:
        rows = list(self.db.scalars(select(ApprovalRow)
                                    .where(ApprovalRow.tenant_id == principal.tenant_id)
                                    .order_by(ApprovalRow.created_at, ApprovalRow.id)))
        for row in rows:
            self._expire(row, now)
        return [row for row in rows if status is None or row.status == status.value]

    def request(self, principal: Principal, card: ActionCard, idempotency_key: str | None,
                now: datetime) -> tuple[ApprovalRow, bool]:
        """Returns (approval, replayed)."""
        key = check_key(idempotency_key)
        tier = policy.card_tier(card)
        if tier is Tier.DENY:
            raise ApprovalProblem(403, "action_denied", action_type=card.action_type.value)
        if tier is not Tier.EXECUTE:
            raise ApprovalProblem(422, "approval_not_needed", tier=tier.value)
        if not (has_permission(principal, Permission.approvals_request, now)
                and policy.may_request(principal.role, card.action_type)):
            raise ApprovalProblem(403, "forbidden", reason="tier")
        digest = card_digest(card)
        if self.db.get(IssuedCardRow, (principal.tenant_id, digest)) is None:
            raise ApprovalProblem(422, "card_not_issued")
        existing = self.db.scalar(select(ApprovalRow).where(
            ApprovalRow.tenant_id == principal.tenant_id, ApprovalRow.idempotency_key == key))
        if existing is not None:
            if existing.card_digest != digest:
                raise ApprovalProblem(409, "idempotency_key_reused")
            self._expire(existing, now)
            return existing, True
        row = ApprovalRow(id="ap-" + secrets.token_hex(8), tenant_id=principal.tenant_id,
                          action_card_id=card.id, action_type=card.action_type.value,
                          tier=tier.value, card_json=card.model_dump_json(), card_digest=digest,
                          requested_by=principal.user_id, status=ApprovalStatus.pending.value,
                          idempotency_key=key, created_at=now,
                          expires_at=now + APPROVAL_LIFETIME)
        self.db.add(row)
        self.db.flush()
        return row, False

    def _require_approver(self, principal: Principal, row: ApprovalRow, now: datetime) -> None:
        decision = policy.decide(principal.role, ActionType(row.action_type), Tier(row.tier))
        if not (decision.allowed and has_permission(principal, Permission.approvals_decide, now)):
            raise ApprovalProblem(403, "forbidden", reason=decision.reason)

    def approve(self, principal: Principal, approval_id: str, *, step_up_verified: bool,
                now: datetime) -> ApprovalRow:
        row = self._load(principal, approval_id, now)
        self._require_approver(principal, row, now)
        if row.status != ApprovalStatus.pending.value:
            raise ApprovalProblem(409, f"approval_{row.status}")
        if Tier(row.tier) is Tier.EXECUTE and not step_up_verified:
            raise ApprovalProblem(401, "step_up_required")
        row.status = ApprovalStatus.approved.value
        row.decided_by, row.decided_at = principal.user_id, now
        row.step_up_verified = step_up_verified
        self.db.flush()
        return row

    def reject(self, principal: Principal, approval_id: str, now: datetime) -> ApprovalRow:
        row = self._load(principal, approval_id, now)
        self._require_approver(principal, row, now)
        if row.status != ApprovalStatus.pending.value:
            raise ApprovalProblem(409, f"approval_{row.status}")
        row.status = ApprovalStatus.rejected.value
        row.decided_by, row.decided_at = principal.user_id, now
        self.db.flush()
        return row

    def execute(self, principal: Principal, approval_id: str, execution_key: str | None,
                now: datetime) -> Execution:
        key = check_key(execution_key)
        row = self._load(principal, approval_id, now)
        if row.status == ApprovalStatus.executed.value:
            if row.execution_key == key:
                return Execution(to_contract(row), json.loads(row.result_json or "{}"), True)
            raise ApprovalProblem(409, "approval_executed")
        if principal.user_id not in (row.requested_by, row.decided_by) \
                and principal.role is not Role.owner:
            raise ApprovalProblem(403, "forbidden", reason="not_party")
        if row.status != ApprovalStatus.approved.value:
            raise ApprovalProblem(409, f"approval_{row.status}")
        card = stored_card(row)
        if card_digest(card) != row.card_digest:
            raise ApprovalProblem(409, "card_changed")
        self._recheck(row, card, now)
        result = executor_for(card.action_type)(card, to_contract(row))
        row.status = ApprovalStatus.executed.value
        row.executed_at, row.execution_key = now, key
        row.result_json = json.dumps(result, sort_keys=True)
        self.db.flush()
        return Execution(to_contract(row), result, False)

    def _recheck(self, row: ApprovalRow, card: ActionCard, now: datetime) -> None:
        """Policy is evaluated again at execution time: anything that changed since the
        approval (policy table, the approver's role or status) stops the action."""
        approver = self.db.get(UserRow, row.decided_by) if row.decided_by else None
        if approver is None or not approver.active or approver.tenant_id != row.tenant_id:
            raise ApprovalProblem(409, "approver_inactive")
        if (approver.expires_at is not None and approver.expires_at <= now) \
                or not row.step_up_verified:
            raise ApprovalProblem(409, "approver_inactive")
        decision = policy.decide(Role(approver.role), card.action_type, card.tier)
        if not decision.allowed or decision.required is not Tier(row.tier):
            raise ApprovalProblem(403, "policy_changed", reason=decision.reason)
