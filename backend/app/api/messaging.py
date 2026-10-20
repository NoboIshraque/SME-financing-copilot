"""Messages API (WP-12 milestones 1, 2, 3, 5 after the 19 Oct cut; FEATURES N2).

    GET  /api/messages/drafts?language=en|bn   -> [MessageDraft]   (newest first)
    POST /api/messages/{id}/approve            -> MessageDraft     (owner + X-Step-Up-Code)
    POST /api/messages/{id}/send               -> MessageDraft     (owner, once approved)

Drafts come from the WP-05 reminder plan: one per customer with open invoices, filled from typed
values only (`app.messaging.templates`). Sending channels were cut, so every draft uses the
`copy` channel: approving it sends nothing; the owner copies the approved text into their own
chat app, and `send` records that it went out (once; repeating it changes nothing). Approve and
send need `approvals:decide` (the owner); both are written to the tenant's audit chain.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import receivables as receivables_api
from app.contracts import (
    ApiError,
    DraftStatus,
    Language,
    MessageChannel,
    MessageDraft,
    MessagePurpose,
    Principal,
    Tier,
)
from app.engines.receivables import ladder
from app.main import get_session
from app.messaging.models import DraftRow
from app.messaging.templates import amount_text, render
from app.security.audit import AuditLog
from app.security.clock import Clock
from app.security.deps import StepUp, get_clock, require, step_up
from app.security.errors import ProblemRoute
from app.security.models import TenantRow
from app.security.roles import Permission

router = APIRouter(prefix="/messages", tags=["messages"], route_class=ProblemRoute)
PRE_DUE_STEPS = ("pre_due", "due")


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _shop(session: Session, tenant_id: str) -> str:
    row = session.get(TenantRow, tenant_id)
    return row.business_name if row is not None else tenant_id


def _refresh(session: Session, tenant_id: str, language: Language, clock: Clock) -> None:
    """Add a draft for every reminder in today's plan that has none yet (idempotent)."""
    found, as_of = receivables_api._ledger(session, tenant_id, clock)
    if found is None:
        return
    labels = receivables_api._labels(found.invoices)
    shop = _shop(session, tenant_id)
    now = clock()
    for card in ladder.plan(found.invoices, as_of, labels.__getitem__):
        draft_id = f"msg:{card.id}:{language.value}"
        if session.get(DraftRow, draft_id) is not None:
            continue
        token = card.id.split(":")[1]
        purpose = (MessagePurpose.pre_due_reminder if card.payload["step"] in PRE_DUE_STEPS
                   else MessagePurpose.overdue_reminder)
        variables = {"customer": card.payload["counterparty_label"],
                     "recipient_label": card.payload["counterparty_label"],
                     "amount": amount_text(card.impact.value), "due_date": card.payload["due_date"],
                     "invoices": card.payload["invoice_count"], "shop": shop}
        draft = MessageDraft(
            id=draft_id, tenant_id=tenant_id, template_id=f"{purpose.value}.{language.value}.v1",
            purpose=purpose, language=language, channel=MessageChannel.copy,
            recipient_token=token, body=render(purpose, language, variables),
            variables=variables, tier=Tier.EXECUTE, status=DraftStatus.draft, created_at=now,
            data_mode=card.impact.data_mode)
        session.add(DraftRow(id=draft_id, tenant_id=tenant_id, status=draft.status.value,
                             payload=draft.model_dump_json()))
    session.flush()


def _view(row: DraftRow) -> MessageDraft:
    draft = MessageDraft.model_validate_json(row.payload)
    return draft.model_copy(update={"status": DraftStatus(row.status)})


def _own(session: Session, principal: Principal, draft_id: str) -> DraftRow | None:
    row = session.get(DraftRow, draft_id)
    return row if row is not None and row.tenant_id == principal.tenant_id else None


@router.get("/drafts", response_model=list[MessageDraft])
def drafts(language: Language = Language.en,
           principal: Principal = Depends(require(Permission.ledger_read)),
           clock: Clock = Depends(get_clock),
           session: Session = Depends(get_session)) -> list[MessageDraft]:
    _refresh(session, principal.tenant_id, language, clock)
    rows = session.scalars(select(DraftRow).where(DraftRow.tenant_id == principal.tenant_id))
    views = [_view(row) for row in rows]
    return sorted(views, key=lambda d: (d.created_at, d.id), reverse=True)


def _decide(draft_id: str, principal: Principal, session: Session, now: datetime, *,
            want: DraftStatus, needs: DraftStatus, action: str) -> MessageDraft | JSONResponse:
    row = _own(session, principal, draft_id)
    if row is None:
        return _error(404, "draft_not_found", "error.draft_not_found", draft_id=draft_id[:160])
    if row.status == want.value:
        return _view(row)  # repeating it changes nothing
    if row.status != needs.value:
        return _error(409, "draft_not_open", "error.draft_not_open", draft_status=row.status)
    row.status = want.value
    row.decided_by = principal.user_id
    if want is DraftStatus.sent:
        row.sent_at = now
    AuditLog(session).append(principal.tenant_id, actor=principal.user_id, action=action,
                             now=now, tier=Tier.EXECUTE, target=draft_id)
    session.flush()
    return _view(row)


@router.post("/{draft_id}/approve", response_model=MessageDraft)
def approve(draft_id: str,
            principal: Principal = Depends(require(Permission.approvals_decide)),
            step: StepUp = Depends(step_up),
            clock: Clock = Depends(get_clock),
            session: Session = Depends(get_session)) -> MessageDraft | JSONResponse:
    if _own(session, principal, draft_id) is None:
        return _error(404, "draft_not_found", "error.draft_not_found", draft_id=draft_id[:160])
    if step.problem is not None:
        return step.problem.response()
    return _decide(draft_id, principal, session, clock(), want=DraftStatus.approved,
                   needs=DraftStatus.draft, action="message.approved")


@router.post("/{draft_id}/send", response_model=MessageDraft)
def send(draft_id: str,
         principal: Principal = Depends(require(Permission.approvals_decide)),
         clock: Clock = Depends(get_clock),
         session: Session = Depends(get_session)) -> MessageDraft | JSONResponse:
    return _decide(draft_id, principal, session, clock(), want=DraftStatus.sent,
                   needs=DraftStatus.approved, action="message.sent")
