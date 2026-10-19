"""Trust Passport API (WP-13 milestones 2-4; FEATURES Q4).

    GET  /api/reports/passport                 -> [PassportVersion]  (newest first)
    POST /api/reports/passport                 -> PassportVersion    (owner: issue a new version)
    GET  /api/reports/shares                   -> [ShareGrant]
    POST /api/reports/passport/{id}/share      -> ShareGrant  {lender_label, scopes, days}
                                                  (owner + X-Step-Up-Code: data leaves the app)
    POST /api/reports/shares/{id}/revoke       -> ShareGrant  (owner)
    GET  /api/verify/{passport_id}             -> VerifyResult (public, no sign-in)

Shapes follow `web/src/api/types.ts`. Reads need `passport:read` (an owner, accountant,
compliance reviewer, or a lender viewer the owner consented to). A passport bundles evidence
found on the tenant's own ledger: a digest over its recorded transactions (statement evidence)
and the trade-licence and e-TIN facts when on record. Nothing is marked `verified`: the ledger
says what was recorded, not that a third party checked it. Mesh attestations are counted when
stored (none yet), the abstention rate is left out until the copilot logs every question, and
the audit-drill rate was cut. Each version gets a fresh salt kept on the server; its salted
digest is anchored like a netting round (offline or Sepolia). Public verification recomputes
the digest and compares it with the anchor.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.mesh import Anchors, get_anchors
from app.chain.digest import canonical, new_salt
from app.contracts import (
    ActionType,
    ApiError,
    DataMode,
    EvidenceItem,
    EvidenceKind,
    Granularity,
    PassportVersion,
    Period,
    Principal,
    ShareGrant,
    Tier,
    VerifyResult,
)
from app.engines.analysis.ledger import NotEnoughData
from app.engines.analysis.store import records
from app.facts import FactStore
from app.main import get_session
from app.reports.models import PassportRow, ShareRow
from app.reports.passport import PassportError, anchor_passport, build_passport
from app.reports.sharing import ShareLedger, SharingError
from app.reports.verify import verify_passport
from app.security import policy
from app.security.audit import AuditLog
from app.security.clock import Clock
from app.security.deps import StepUp, get_clock, require, step_up
from app.security.errors import ProblemRoute
from app.security.roles import Permission

router = APIRouter(tags=["reports"], route_class=ProblemRoute)
PROFILE_EVIDENCE = (("trade_licence", EvidenceKind.trade_licence),
                    ("etin_registered", EvidenceKind.etin))


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lender_label: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1)
    days: int = Field(ge=1, le=30)


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence(session: Session, tenant_id: str, today: date) -> list[EvidenceItem]:
    store = FactStore(session)
    items = []
    try:
        found = records(store, tenant_id)
    except NotEnoughData:
        found = None
    if found is not None and found.transactions:
        rows = sorted(found.transactions, key=lambda t: t.id)
        digest = _sha(canonical({"transactions": [[t.id, str(t.amount.amount), t.day.isoformat()]
                                                  for t in rows]}))
        items.append(EvidenceItem(kind=EvidenceKind.mobile_money_statement, digest=digest,
                                  period=Period(start=found.first_day, end=found.last_day,
                                                granularity=Granularity.day),
                                  verified=False))
    for metric, kind in PROFILE_EVIDENCE:
        fact = store.latest(tenant_id, metric, today)
        if fact is not None and fact.value > 0:
            items.append(EvidenceItem(kind=kind, digest=_sha(fact.id), verified=False))
    return items


def _passports(session: Session, tenant_id: str) -> list[PassportRow]:
    return list(session.scalars(select(PassportRow).where(PassportRow.tenant_id == tenant_id)
                                .order_by(PassportRow.version.desc())))


def _audit(session: Session, principal: Principal, action: str, target: str, now: datetime,
           tier: Tier) -> None:
    AuditLog(session).append(principal.tenant_id, actor=principal.user_id, action=action,
                             now=now, tier=tier, target=target)


@router.get("/reports/passport", response_model=list[PassportVersion])
def passports(principal: Principal = Depends(require(Permission.passport_read)),
              session: Session = Depends(get_session)) -> list[PassportVersion]:
    return [PassportVersion.model_validate_json(r.payload)
            for r in _passports(session, principal.tenant_id)]


@router.post("/reports/passport", response_model=PassportVersion, status_code=201)
def issue(principal: Principal = Depends(require(Permission.approvals_decide)),
          clock: Clock = Depends(get_clock),
          session: Session = Depends(get_session),
          anchors: Anchors = Depends(get_anchors)) -> PassportVersion | JSONResponse:
    now = clock()
    evidence = _evidence(session, principal.tenant_id, now.date())
    existing = _passports(session, principal.tenant_id)
    previous = PassportVersion.model_validate_json(existing[0].payload) if existing else None
    modes = {DataMode.synthetic} if principal.tenant_id.startswith("sme_") else {DataMode.live}
    salt = new_salt()
    try:
        passport = build_passport(tenant_id=principal.tenant_id, previous=previous,
                                  evidence=evidence, attestations=(), abstention_rate=None,
                                  audit_drill_catch_rate=None, salt=salt, now=now,
                                  data_mode=modes.pop())
    except PassportError:
        return _error(422, "not_enough_evidence", "error.not_enough_evidence")
    passport = anchor_passport(passport, anchors.write, now=now)
    session.add(PassportRow(id=passport.id, tenant_id=passport.tenant_id,
                            version=passport.version, salt=salt, issued_at=now,
                            payload=passport.model_dump_json()))
    _audit(session, principal, "passport.issued", passport.id, now, Tier.DRAFT)
    return passport


@router.get("/reports/shares", response_model=list[ShareGrant])
def shares(principal: Principal = Depends(require(Permission.passport_read)),
           session: Session = Depends(get_session)) -> list[ShareGrant]:
    rows = session.scalars(select(ShareRow).where(ShareRow.tenant_id == principal.tenant_id))
    grants = [ShareGrant.model_validate_json(r.payload) for r in rows]
    return sorted(grants, key=lambda g: (g.created_at, g.id), reverse=True)


@router.post("/reports/passport/{passport_id}/share", response_model=ShareGrant, status_code=201)
def share(passport_id: str, body: ShareRequest,
          principal: Principal = Depends(require(Permission.approvals_decide)),
          step: StepUp = Depends(step_up),
          clock: Clock = Depends(get_clock),
          session: Session = Depends(get_session)) -> ShareGrant | JSONResponse:
    if not policy.decide(principal.role, ActionType.share_passport, Tier.EXECUTE).allowed:
        return _error(403, "forbidden", "error.forbidden", reason="tier")
    row = session.get(PassportRow, passport_id)
    if row is None or row.tenant_id != principal.tenant_id:
        return _error(404, "passport_not_found", "error.passport_not_found")
    if step.problem is not None:
        return step.problem.response()
    now = clock()
    try:
        grant, token = ShareLedger().grant(tenant_id=principal.tenant_id, passport_id=passport_id,
                                           lender_label=body.lender_label,
                                           scopes=tuple(body.scopes),
                                           ttl=timedelta(days=body.days), now=now)
    except SharingError:
        return _error(422, "invalid_share", "error.invalid_share")
    session.add(ShareRow(id=grant.id, tenant_id=grant.tenant_id, token_hash=_sha(token),
                         payload=grant.model_dump_json()))
    _audit(session, principal, "passport.shared", grant.id, now, Tier.EXECUTE)
    return grant


@router.post("/reports/shares/{grant_id}/revoke", response_model=ShareGrant)
def revoke(grant_id: str,
           principal: Principal = Depends(require(Permission.approvals_decide)),
           clock: Clock = Depends(get_clock),
           session: Session = Depends(get_session)) -> ShareGrant | JSONResponse:
    row = session.get(ShareRow, grant_id)
    if row is None or row.tenant_id != principal.tenant_id:
        return _error(404, "share_not_found", "error.share_not_found")
    grant = ShareGrant.model_validate_json(row.payload).model_copy(update={"revoked": True})
    row.payload = grant.model_dump_json()
    _audit(session, principal, "passport.share_revoked", grant_id, clock(), Tier.DRAFT)
    return grant


@router.get("/verify/{passport_id}", response_model=VerifyResult)
def verify(passport_id: str,
           clock: Clock = Depends(get_clock),
           session: Session = Depends(get_session),
           anchors: Anchors = Depends(get_anchors)) -> VerifyResult | JSONResponse:
    row = session.get(PassportRow, passport_id)
    if row is None:
        return _error(404, "passport_not_found", "error.passport_not_found")
    passport = PassportVersion.model_validate_json(row.payload)
    reader = anchors.readers.get(passport.anchor.chain) if passport.anchor else anchors.write
    return verify_passport(passport, row.salt, reader or anchors.write, today=clock().date())
