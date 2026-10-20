"""Copilot API (WP-10 milestone 9; FEATURES N7-N11, N17, P9, P13).

    POST /api/copilot/ask {question, language?, private?} -> Recommendation
    GET  /api/copilot/today                              -> Recommendation (the daily check)
    GET  /api/copilot/abstentions                        -> [{id, at, question, abstention}]
                                                            (also `audit:read`: compliance)

Signed-in callers holding `copilot:ask`, always for their own tenant (WP-11): the tenant comes
from the principal, never from the body. A recommendation answers with checked claims and at
most three action cards the caller's role may act on, or abstains naming what is missing.
A question the injection guard quarantines is refused with 422 `error.input_quarantined`
(and logged); an empty one with 422 `error.empty_question`. Approving a card goes through
`POST /api/approvals` (WP-11); nothing here moves money.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents import abstention as abstain
from app.agents.orchestrator import Orchestrator
from app.agents.tools import ToolContext
from app.contracts import Abstention, AbstentionReason, ApiError, Principal, Recommendation
from app.facts import FactStore
from app.llm import LLMGateway
from app.main import get_app_settings, get_session
from app.security.approvals import issue_cards
from app.security.clock import Clock
from app.security.deps import current_principal, get_clock, require
from app.security.errors import ProblemRoute, forbidden
from app.security.roles import Permission, has_permission
from app.settings import Settings

router = APIRouter(prefix="/copilot", tags=["copilot"], route_class=ProblemRoute)
MAX_QUESTION = 2000
# The daily check the Today screen shows: the cash outlook and the first thing to do about it.
TODAY_QUESTION = {
    "en": "Will I run out of cash in the next three months, and what should I do first?",
    "bn": "আগামী তিন মাসে কি নগদ ঘাটতি হবে, আর প্রথমে কী করা উচিত?",
    "zh": "未来三个月我的现金会不够吗？我应该先做什么？",
}


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a tenant_id in the body is refused

    question: str = Field(max_length=MAX_QUESTION)
    language: Literal["en", "bn", "zh"] | None = None
    private: bool = Field(default=False, description="Use only the local model (Ollama)")


class AbstentionEntry(BaseModel):
    id: str
    at: datetime
    question: str
    abstention: Abstention


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def get_orchestrator(request: Request,
                     settings: Settings = Depends(get_app_settings)) -> Orchestrator:
    """One orchestrator (and so one gateway, cache and usage meter) per app."""
    orchestrator = getattr(request.app.state, "copilot", None)
    if orchestrator is None:
        orchestrator = Orchestrator(LLMGateway(settings))
        request.app.state.copilot = orchestrator
    return orchestrator


_asker = require(Permission.copilot_ask)


def _abstention_reader(principal: Principal = Depends(current_principal),
                       clock: Clock = Depends(get_clock)) -> Principal:
    """The "I don't know" log is part of the trust record: whoever asks the copilot, and the
    compliance reviewer (`audit:read`), may read it."""
    now = clock()
    if not (has_permission(principal, Permission.copilot_ask, now)
            or has_permission(principal, Permission.audit_read, now)):
        raise forbidden(Permission.copilot_ask.value)
    return principal


def _run(question: str, principal: Principal, session: Session, clock: Clock,
         orchestrator: Orchestrator, language: str | None = None,
         private: bool = False) -> Recommendation:
    ctx = ToolContext(FactStore(session), principal.tenant_id, clock())
    rec = orchestrator.ask(ctx, question, language=language, role=principal.role,
                           actor=principal.user_id, private=private).recommendation
    issue_cards(session, principal.tenant_id, rec.action_cards, ctx.now)
    return rec


@router.post("/ask", response_model=Recommendation)
def ask(body: AskBody, principal: Principal = Depends(_asker),
        session: Session = Depends(get_session), clock: Clock = Depends(get_clock),
        orchestrator: Orchestrator = Depends(get_orchestrator)
        ) -> Recommendation | JSONResponse:
    question = body.question.strip()
    if not question:
        return _error(422, "empty_question", "error.empty_question")
    rec = _run(question, principal, session, clock, orchestrator, body.language, body.private)
    refused = rec.abstention
    if refused is not None and refused.reason is AbstentionReason.policy and \
            (refused.detail or "").startswith("quarantined:"):
        session.commit()  # keep the quarantine entry and the audit event
        return _error(422, "input_quarantined", "error.input_quarantined",
                      quarantine_id=refused.detail.removeprefix("quarantined:"))
    return rec


@router.get("/today", response_model=Recommendation)
def today(language: Literal["en", "bn", "zh"] = Query(default="en"),
          principal: Principal = Depends(_asker), session: Session = Depends(get_session),
          clock: Clock = Depends(get_clock),
          orchestrator: Orchestrator = Depends(get_orchestrator)) -> Recommendation:
    return _run(TODAY_QUESTION[language], principal, session, clock, orchestrator, language)


@router.get("/abstentions", response_model=list[AbstentionEntry])
def abstentions(limit: int = Query(default=100, ge=1, le=500),
                principal: Principal = Depends(_abstention_reader),
                session: Session = Depends(get_session)) -> list[AbstentionEntry]:
    return [AbstentionEntry(id=row.recommendation_id, at=row.created_at, question=row.question,
                            abstention=abstain.as_contract(row))
            for row in abstain.history(session, principal.tenant_id, limit)]
