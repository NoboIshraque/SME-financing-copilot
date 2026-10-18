"""Auth, team, lender access and approvals API (WP-11). Auth shapes match
`web/src/api/types.ts`.

    POST /api/auth/login          {email, password} -> {status: "ok", session}
                                                     | {status: "totp_required"}
    POST /api/auth/login/totp     {code} -> Session          (second step, pending cookie)
    POST /api/auth/logout         -> 204
    GET  /api/auth/me             -> Session                 (401 when signed out)
    GET  /api/auth/demo-accounts  -> [DemoAccount]           (demo mode only, else 404)
    POST /api/auth/totp/enrol     -> {secret, otpauth_uri}   (signed in, not yet enrolled)
    POST /api/auth/totp/confirm   {code} -> Session
    POST /api/auth/password       {current_password, new_password} -> 204

Team and lender access (owner only; adding anyone needs a fresh TOTP in X-Step-Up-Code):

    GET  /api/auth/users                          -> [Member]
    POST /api/auth/users                          {email, display_name, role, password} -> Member
    POST /api/auth/users/{user_id}/deactivate     -> Member     (their sessions end at once)
    GET  /api/auth/lender-access                  -> [LenderGrant]
    POST /api/auth/lender-access                  {lender_email, lender_label, purpose, scopes,
                                                   days, consent} -> LenderGrant (+ one-time
                                                   initial_password)
    POST /api/auth/lender-access/{grant_id}/revoke -> LenderGrant

Approvals for EXECUTE actions (milestone 3; the policy table is app/security/policy.py):

    GET  /api/policy/tiers                    -> {action: {required, owner, accountant, ...}}
    POST /api/approvals          {card}       + X-Idempotency-Key -> ApprovalView (pending)
    GET  /api/approvals?status=pending        -> [ApprovalView]
    GET  /api/approvals/{id}                  -> ApprovalView
    POST /api/approvals/{id}/approve          + X-Step-Up-Code (owner) -> ApprovalView
    POST /api/approvals/{id}/reject           (owner) -> ApprovalView
    POST /api/approvals/{id}/execute          + X-Idempotency-Key -> ApprovalView with result

Audit chain (milestone 4; every outcome above is appended to the tenant's chain):

    GET  /api/audit/events?limit=&before_seq= (audit:read)   -> [AuditEvent], newest first
    GET  /api/audit/verify                    (audit:verify) -> chain report incl. anchors
    POST /api/audit/anchor                    (audit:verify) -> today's anchor (idempotent)
    GET  /api/audit/anchors                   (audit:read)   -> [anchor]

Errors are ApiError bodies: 401 error.invalid_credentials, 401 error.invalid_totp,
423 error.account_locked (detail.retry_after_minutes), 401 error.not_authenticated,
422 error.weak_password (detail.problems). A failed attempt is written before the error is
returned (not raised), so the lockout counter survives the request.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts import ActionType, ApprovalStatus, AuditEvent, Principal, Role, Tier
from app.main import get_session
from app.security import policy, totp
from app.security.accounts import AccountProblem, Accounts, SignIn
from app.security.approvals import (
    ApprovalProblem,
    Approvals,
    card_digest,
    stored_card,
    to_contract,
)
from app.security.audit import SYSTEM_TENANT, AuditLog, ChainReport
from app.security.clock import Clock
from app.security.demo import demo_enabled, demo_listing, ensure_demo_accounts
from app.security.deps import (
    Authenticated,
    StepUp,
    authenticated,
    current_principal,
    get_clock,
    require,
    step_up,
)
from app.security.errors import ProblemRoute, SecurityProblem, forbidden, not_authenticated
from app.security.jobs import anchorer_for
from app.security.models import ApprovalRow, AuditAnchorRow, LenderGrantRow, UserRow
from app.security.roles import Permission, has_permission
from app.security.schemas import (
    AnchorView,
    ApprovalRequestBody,
    ApprovalView,
    ChainReportView,
    CodeBody,
    DemoAccountView,
    LenderGrantBody,
    LenderGrantView,
    LoginBody,
    LoginOk,
    LoginTotpRequired,
    MemberView,
    NewMemberBody,
    PasswordChangeBody,
    SessionView,
    TotpEnrolment,
)
from app.security.sessions import COOKIE_NAME, SessionStore, Stage, cookie_attributes, lifetime
from app.security.team import Team, grant_scopes
from app.settings import Settings

auth_router = APIRouter(prefix="/auth", tags=["auth"], route_class=ProblemRoute)

NO_STORE = {"Cache-Control": "no-store"}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _ensure_demo(request: Request, db: Session, now: datetime) -> None:
    state = request.app.state
    if not getattr(state, "security_demo_seeded", False):
        ensure_demo_accounts(db, state.settings, now)
        state.security_demo_seeded = True


def _set_cookie(response: Response, token: str, stage: Stage, settings: Settings) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=int(lifetime(stage).total_seconds()),
                        **cookie_attributes(settings))  # type: ignore[arg-type]
    response.headers.update(NO_STORE)


def _clear_cookie(response: Response, settings: Settings) -> None:
    attributes = cookie_attributes(settings)
    response.delete_cookie(COOKIE_NAME, path=str(attributes["path"]),
                           secure=bool(attributes["secure"]), httponly=True, samesite="strict")


def _audit(db: Session, tenant_id: str, actor: str, action: str, now: datetime, *,
           tier: Tier | None = None, target: str | None = None, **details: object) -> None:
    AuditLog(db).append(tenant_id, actor=actor, action=action, now=now, tier=tier,
                        target=target, details=details)


def _refusal(result: SignIn, invalid_code: str = "invalid_credentials") -> JSONResponse:
    if result.status == "locked":
        return SecurityProblem(423, "account_locked", "error.account_locked",
                               retry_after_minutes=result.retry_after_minutes).response()
    return SecurityProblem(401, invalid_code, f"error.{invalid_code}").response()


@auth_router.post("/login", response_model=LoginOk | LoginTotpRequired)
def login(body: LoginBody, request: Request, response: Response,
          db: Session = Depends(get_session), clock: Clock = Depends(get_clock)
          ) -> LoginOk | LoginTotpRequired | JSONResponse:
    now = clock()
    settings = _settings(request)
    _ensure_demo(request, db, now)
    accounts = Accounts(db, settings)
    result = accounts.sign_in(body.email, body.password, now)
    if result.user is None:
        known = accounts.by_email(body.email)
        _audit(db, known.tenant_id if known else SYSTEM_TENANT, known.id if known else "anonymous",
               "auth.locked" if result.status == "locked" else "auth.login_failed", now,
               email_key=accounts.lockout.email_key(body.email.strip().lower()))
        return _refusal(result)
    store = SessionStore(db)
    store.revoke(request.cookies.get(COOKIE_NAME), now)  # a sign-in never reuses a session
    stage = Stage.totp_pending if result.status == "totp_required" else Stage.active
    token, _row = store.issue(result.user.id, stage, now)
    _set_cookie(response, token, stage, settings)
    if stage is Stage.totp_pending:
        _audit(db, result.user.tenant_id, result.user.id, "auth.password_ok", now)
        return LoginTotpRequired()
    _audit(db, result.user.tenant_id, result.user.id, "auth.login", now, factors=1)
    return LoginOk(session=accounts.session_view(result.user))


@auth_router.post("/login/totp", response_model=SessionView)
def login_totp(body: CodeBody, request: Request, response: Response,
               db: Session = Depends(get_session), clock: Clock = Depends(get_clock)
               ) -> SessionView | JSONResponse:
    now = clock()
    settings = _settings(request)
    store = SessionStore(db)
    token = request.cookies.get(COOKIE_NAME)
    pending = store.find(token, now, Stage.totp_pending)
    accounts = Accounts(db, settings)
    user = accounts.get(pending.user_id) if pending is not None else None
    if user is None:
        return not_authenticated().response()
    result = accounts.check_totp(user, body.code, now)
    if result.status != "ok":
        if result.status == "locked":
            store.revoke(token, now)  # after a lock the password is needed again
        _audit(db, user.tenant_id, user.id,
               "auth.locked" if result.status == "locked" else "auth.totp_failed", now)
        return _refusal(result, "invalid_totp")
    store.revoke(token, now)
    new_token, _row = store.issue(user.id, Stage.active, now)
    _audit(db, user.tenant_id, user.id, "auth.login", now, factors=2)
    _set_cookie(response, new_token, Stage.active, settings)
    return accounts.session_view(user)


@auth_router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_session),
           clock: Clock = Depends(get_clock)) -> Response:
    now = clock()
    store = SessionStore(db)
    token = request.cookies.get(COOKIE_NAME)
    row = store.find(token, now)
    if row is not None and store.revoke(token, now):
        user = Accounts(db, _settings(request)).get(row.user_id)
        if user is not None:
            _audit(db, user.tenant_id, user.id, "auth.logout", now)
    response = Response(status_code=204)
    _clear_cookie(response, _settings(request))
    return response


@auth_router.get("/me", response_model=SessionView)
def me(request: Request, response: Response, auth: Authenticated = Depends(authenticated),
       db: Session = Depends(get_session)) -> SessionView:
    response.headers.update(NO_STORE)
    return Accounts(db, _settings(request)).session_view(auth.user)


@auth_router.get("/demo-accounts", response_model=list[DemoAccountView])
def demo_accounts(request: Request, response: Response, db: Session = Depends(get_session),
                  clock: Clock = Depends(get_clock)) -> list[DemoAccountView] | JSONResponse:
    settings = _settings(request)
    if not demo_enabled(settings):
        return SecurityProblem(404, "not_found", "error.not_found").response()
    now = clock()
    _ensure_demo(request, db, now)
    response.headers.update(NO_STORE)
    return demo_listing(settings, now)


@auth_router.post("/totp/enrol", response_model=TotpEnrolment)
def totp_enrol(request: Request, response: Response,
               auth: Authenticated = Depends(authenticated),
               db: Session = Depends(get_session)) -> TotpEnrolment | JSONResponse:
    try:
        secret = Accounts(db, _settings(request)).start_totp_enrolment(auth.user)
    except AccountProblem as problem:
        return SecurityProblem(409, problem.code, problem.message_key).response()
    response.headers.update(NO_STORE)
    return TotpEnrolment(secret=secret, otpauth_uri=totp.provisioning_uri(secret, auth.user.email))


@auth_router.post("/totp/confirm", response_model=SessionView)
def totp_confirm(body: CodeBody, request: Request,
                 auth: Authenticated = Depends(authenticated),
                 db: Session = Depends(get_session),
                 clock: Clock = Depends(get_clock)) -> SessionView | JSONResponse:
    accounts = Accounts(db, _settings(request))
    now = clock()
    if not accounts.confirm_totp_enrolment(auth.user, body.code, now):
        return SecurityProblem(401, "invalid_totp", "error.invalid_totp").response()
    _audit(db, auth.user.tenant_id, auth.user.id, "auth.totp_enrolled", now)
    return accounts.session_view(auth.user)


@auth_router.post("/password", status_code=204)
def change_password(body: PasswordChangeBody, request: Request,
                    auth: Authenticated = Depends(authenticated),
                    db: Session = Depends(get_session),
                    clock: Clock = Depends(get_clock)) -> Response:
    now = clock()
    accounts = Accounts(db, _settings(request))
    try:
        result = accounts.change_password(auth.user, body.current_password, body.new_password,
                                          now)
    except AccountProblem as problem:
        return SecurityProblem(422, problem.code, problem.message_key, **problem.detail).response()
    if result.status != "ok":
        _audit(db, auth.user.tenant_id, auth.user.id, "auth.password_change_failed", now)
        return _refusal(result)
    ended = SessionStore(db).revoke_user(auth.user.id, now, keep=auth.token)
    _audit(db, auth.user.tenant_id, auth.user.id, "auth.password_changed", now,
           other_sessions_ended=ended)
    return Response(status_code=204)


# ---------------------------------------------------------------------- team and lender access


def _member(user: UserRow) -> MemberView:
    return MemberView(user_id=user.id, email=user.email, role=Role(user.role),
                      display_name=user.display_name, active=user.active,
                      totp_enrolled=user.totp_enrolled, expires_at=user.expires_at,
                      scopes=list(json.loads(user.scopes)))


def _grant(grant: LenderGrantRow, team: Team, initial_password: str | None = None
           ) -> LenderGrantView:
    lender = team.accounts.get(grant.user_id)
    return LenderGrantView(id=grant.id, lender_email=lender.email if lender else "",
                           lender_label=grant.lender_label, purpose=grant.purpose,
                           scopes=grant_scopes(grant), consented_by=grant.consented_by,
                           consented_at=grant.consented_at, expires_at=grant.expires_at,
                           revoked_at=grant.revoked_at, initial_password=initial_password)


def _account_problem(problem: AccountProblem) -> JSONResponse:
    status = {"not_found": 404, "email_taken": 409}.get(problem.code, 422)
    return SecurityProblem(status, problem.code, problem.message_key, **problem.detail).response()


@auth_router.get("/users", response_model=list[MemberView])
def list_members(request: Request, response: Response,
                 owner: Principal = Depends(require(Permission.team_manage)),
                 db: Session = Depends(get_session)) -> list[MemberView]:
    response.headers.update(NO_STORE)
    return [_member(user) for user in Team(db, _settings(request)).members(owner.tenant_id)]


@auth_router.post("/users", response_model=MemberView, status_code=201)
def add_member(body: NewMemberBody, request: Request,
               owner: Principal = Depends(require(Permission.team_manage)),
               step: StepUp = Depends(step_up), db: Session = Depends(get_session),
               clock: Clock = Depends(get_clock)) -> MemberView | JSONResponse:
    if step.problem:
        return step.problem.response()
    now = clock()
    try:
        user = Team(db, _settings(request)).add_member(
            owner, email=body.email, display_name=body.display_name, role=body.role,
            password=body.password, now=now)
    except AccountProblem as problem:
        return _account_problem(problem)
    _audit(db, owner.tenant_id, owner.user_id, "team.member_added", now, target=user.id,
           role=user.role, step_up=True)
    return _member(user)


@auth_router.post("/users/{user_id}/deactivate", response_model=MemberView)
def deactivate_member(user_id: str, request: Request,
                      owner: Principal = Depends(require(Permission.team_manage)),
                      db: Session = Depends(get_session),
                      clock: Clock = Depends(get_clock)) -> MemberView | JSONResponse:
    now = clock()
    try:
        user = Team(db, _settings(request)).deactivate(owner, user_id, now)
    except AccountProblem as problem:
        return _account_problem(problem)
    _audit(db, owner.tenant_id, owner.user_id, "team.member_deactivated", now, target=user.id)
    return _member(user)


@auth_router.get("/lender-access", response_model=list[LenderGrantView])
def list_lender_access(request: Request, response: Response,
                       owner: Principal = Depends(require(Permission.lender_access_grant)),
                       db: Session = Depends(get_session)) -> list[LenderGrantView]:
    response.headers.update(NO_STORE)
    team = Team(db, _settings(request))
    return [_grant(grant, team) for grant in team.grants(owner.tenant_id)]


@auth_router.post("/lender-access", response_model=LenderGrantView, status_code=201)
def grant_lender_access(body: LenderGrantBody, request: Request, response: Response,
                        owner: Principal = Depends(require(Permission.lender_access_grant)),
                        step: StepUp = Depends(step_up), db: Session = Depends(get_session),
                        clock: Clock = Depends(get_clock)) -> LenderGrantView | JSONResponse:
    if step.problem:
        return step.problem.response()
    team = Team(db, _settings(request))
    now = clock()
    try:
        grant, initial_password = team.grant_lender(
            owner, lender_email=body.lender_email, lender_label=body.lender_label,
            purpose=body.purpose, scopes=tuple(body.scopes), days=body.days,
            consent=body.consent, now=now)
    except AccountProblem as problem:
        return _account_problem(problem)
    _audit(db, owner.tenant_id, owner.user_id, "lender_access.granted", now, tier=Tier.EXECUTE,
           target=grant.id, scopes=",".join(grant_scopes(grant)), days=body.days, consent=True,
           step_up=True)
    response.headers.update(NO_STORE)
    return _grant(grant, team, initial_password)


@auth_router.post("/lender-access/{grant_id}/revoke", response_model=LenderGrantView)
def revoke_lender_access(grant_id: str, request: Request,
                         owner: Principal = Depends(require(Permission.lender_access_grant)),
                         db: Session = Depends(get_session),
                         clock: Clock = Depends(get_clock)) -> LenderGrantView | JSONResponse:
    team = Team(db, _settings(request))
    now = clock()
    try:
        grant = team.revoke_lender(owner, grant_id, now)
    except AccountProblem as problem:
        return _account_problem(problem)
    _audit(db, owner.tenant_id, owner.user_id, "lender_access.revoked", now, target=grant.id)
    return _grant(grant, team)


# ---------------------------------------------------------------------- approvals and policy

approvals_router = APIRouter(prefix="/approvals", tags=["approvals"], route_class=ProblemRoute)
policy_router = APIRouter(prefix="/policy", tags=["approvals"], route_class=ProblemRoute)
IDEMPOTENCY_HEADER = "X-Idempotency-Key"
_APPROVAL_READERS = (Permission.approvals_request, Permission.approvals_decide,
                     Permission.audit_read)


def _approval_view(row: ApprovalRow, result: dict[str, str] | None = None,
                   replayed: bool = False) -> ApprovalView:
    return ApprovalView(approval=to_contract(row), action_type=ActionType(row.action_type),
                        card=stored_card(row), result=result, replayed=replayed)


def _approval_problem(problem: ApprovalProblem) -> JSONResponse:
    return SecurityProblem(problem.status, problem.code, f"error.{problem.code}",
                           **problem.detail).response()


def _may_read_approvals(principal: Principal, now: datetime) -> bool:
    return any(has_permission(principal, permission, now) for permission in _APPROVAL_READERS)


@policy_router.get("/tiers")
def policy_tiers(_principal: Principal = Depends(current_principal)
                 ) -> dict[str, dict[str, str]]:
    return policy.table()


@approvals_router.post("", response_model=ApprovalView, status_code=201)
def request_approval(body: ApprovalRequestBody, request: Request,
                     principal: Principal = Depends(current_principal),
                     db: Session = Depends(get_session),
                     clock: Clock = Depends(get_clock)) -> ApprovalView | JSONResponse:
    now = clock()
    try:
        row, replayed = Approvals(db).request(principal, body.card,
                                              request.headers.get(IDEMPOTENCY_HEADER), now)
    except ApprovalProblem as problem:
        if problem.code in ("action_denied", "forbidden"):
            _audit(db, principal.tenant_id, principal.user_id, "approval.refused", now,
                   tier=Tier.DENY if problem.code == "action_denied" else None,
                   target=body.card.id, action_type=body.card.action_type.value,
                   reason=problem.code)
        return _approval_problem(problem)
    if not replayed:
        _audit(db, principal.tenant_id, principal.user_id, "approval.requested", now,
               tier=Tier(row.tier), target=row.id, action_type=row.action_type,
               card_digest=card_digest(body.card))
    view = _approval_view(row, replayed=replayed)
    if replayed:
        return JSONResponse(status_code=200, content=view.model_dump(mode="json"))
    return view


@approvals_router.get("", response_model=list[ApprovalView])
def list_approvals(status: ApprovalStatus | None = None,
                   principal: Principal = Depends(current_principal),
                   db: Session = Depends(get_session),
                   clock: Clock = Depends(get_clock)) -> list[ApprovalView] | JSONResponse:
    now = clock()
    if not _may_read_approvals(principal, now):
        return forbidden("approvals").response()
    return [_approval_view(row) for row in Approvals(db).list(principal, now, status)]


@approvals_router.get("/{approval_id}", response_model=ApprovalView)
def get_approval(approval_id: str, principal: Principal = Depends(current_principal),
                 db: Session = Depends(get_session),
                 clock: Clock = Depends(get_clock)) -> ApprovalView | JSONResponse:
    now = clock()
    if not _may_read_approvals(principal, now):
        return forbidden("approvals").response()
    try:
        return _approval_view(Approvals(db).get(principal, approval_id, now))
    except ApprovalProblem as problem:
        return _approval_problem(problem)


@approvals_router.post("/{approval_id}/approve", response_model=ApprovalView)
def approve(approval_id: str,
            principal: Principal = Depends(require(Permission.approvals_decide)),
            step: StepUp = Depends(step_up), db: Session = Depends(get_session),
            clock: Clock = Depends(get_clock)) -> ApprovalView | JSONResponse:
    if step.problem:
        return step.problem.response()
    now = clock()
    try:
        row = Approvals(db).approve(principal, approval_id, step_up_verified=step.verified,
                                    now=now)
    except ApprovalProblem as problem:
        return _approval_problem(problem)
    _audit(db, principal.tenant_id, principal.user_id, "approval.approved", now,
           tier=Tier(row.tier), target=row.id, action_type=row.action_type, step_up=True)
    return _approval_view(row)


@approvals_router.post("/{approval_id}/reject", response_model=ApprovalView)
def reject(approval_id: str,
           principal: Principal = Depends(require(Permission.approvals_decide)),
           db: Session = Depends(get_session),
           clock: Clock = Depends(get_clock)) -> ApprovalView | JSONResponse:
    now = clock()
    try:
        row = Approvals(db).reject(principal, approval_id, now)
    except ApprovalProblem as problem:
        return _approval_problem(problem)
    _audit(db, principal.tenant_id, principal.user_id, "approval.rejected", now,
           tier=Tier(row.tier), target=row.id, action_type=row.action_type)
    return _approval_view(row)


@approvals_router.post("/{approval_id}/execute", response_model=ApprovalView)
def execute(approval_id: str, request: Request,
            principal: Principal = Depends(current_principal),
            db: Session = Depends(get_session),
            clock: Clock = Depends(get_clock)) -> ApprovalView | JSONResponse:
    approvals = Approvals(db)
    now = clock()
    try:
        done = approvals.execute(principal, approval_id,
                                 request.headers.get(IDEMPOTENCY_HEADER), now)
        row = approvals.get(principal, approval_id, now)
    except ApprovalProblem as problem:
        if problem.code not in ("not_found", "idempotency_key_required"):
            _audit(db, principal.tenant_id, principal.user_id, "approval.execution_refused",
                   now, target=approval_id, reason=problem.code)
        return _approval_problem(problem)
    if not done.replayed:
        _audit(db, principal.tenant_id, principal.user_id, "approval.executed", now,
               tier=Tier(row.tier), target=row.id, action_type=row.action_type,
               result_status=done.result.get("status", ""))
    return _approval_view(row, result=done.result, replayed=done.replayed)


# ---------------------------------------------------------------------- audit chain

audit_router = APIRouter(prefix="/audit", tags=["audit"], route_class=ProblemRoute)


@audit_router.get("/events", response_model=list[AuditEvent])
def audit_events(limit: int = 50, before_seq: int | None = None,
                 principal: Principal = Depends(require(Permission.audit_read)),
                 db: Session = Depends(get_session)) -> list[AuditEvent]:
    return AuditLog(db).events(principal.tenant_id, limit=max(1, min(limit, 500)),
                               before_seq=before_seq)


@audit_router.get("/verify", response_model=ChainReportView)
def audit_verify(principal: Principal = Depends(require(Permission.audit_verify)),
                 db: Session = Depends(get_session)) -> ChainReportView:
    report: ChainReport = AuditLog(db).verify(principal.tenant_id)
    return ChainReportView(**report.__dict__)


@audit_router.post("/anchor", response_model=AnchorView | None)
def audit_anchor(request: Request,
                 principal: Principal = Depends(require(Permission.audit_verify)),
                 db: Session = Depends(get_session),
                 clock: Clock = Depends(get_clock)) -> AnchorView | None:
    settings = _settings(request)
    now = clock()
    day = now.astimezone(ZoneInfo(settings.timezone)).date()
    row = AuditLog(db).anchor_day(day, anchorer_for(settings), now)
    return _anchor(row) if row else None


@audit_router.get("/anchors", response_model=list[AnchorView])
def audit_anchors(_principal: Principal = Depends(require(Permission.audit_read)),
                  db: Session = Depends(get_session)) -> list[AnchorView]:
    return [_anchor(row) for row in AuditLog(db).anchors()]


def _anchor(row: AuditAnchorRow) -> AnchorView:
    return AnchorView(day=row.day, digest=row.digest, chain=row.chain, tx_hash=row.tx_hash,
                      block_number=row.block_number, explorer_url=row.explorer_url,
                      anchored_at=row.anchored_at, heads=len(json.loads(row.heads)))


router = APIRouter()
for _sub in (auth_router, approvals_router, policy_router, audit_router):
    router.include_router(_sub)
