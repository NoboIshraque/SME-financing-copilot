"""Liquidity mesh API (WP-08 milestone 8; FEATURES N14, Q4, on-chain bonus).

    GET  /api/mesh/obligations             -> MeshGraph {obligations, labels}
    GET  /api/mesh/rounds                  -> [NettingRound]   (rounds the caller is in)
    POST /api/mesh/rounds/propose          -> NettingRound     (DRAFT: owner, accountant)
    POST /api/mesh/rounds/{id}/approve     -> NettingRound     (EXECUTE: owner + X-Step-Up-Code)
    POST /api/mesh/rounds/{id}/reject      -> NettingRound     (owner; no code needed to say no)
    GET  /api/mesh/rounds/{id}/verify      -> RoundVerification

Shapes follow `web/src/api/types.ts` (MeshGraph, RoundVerification). The caller is the signed-in
principal (WP-11) with `ledger:read`; the tenant always comes from the principal.

Visibility: a business sees its own obligations plus the obligations inside its netting group
(the opted-in businesses whose debts form a cycle with it), which is what a round shows its
participants anyway. Rounds are visible to their participants only; any other id answers 404.

When the last participant approves, the round settles (its obligations are discharged and
receipts issued) and its salted digest is anchored: on Sepolia when `chain_mode=sepolia` and
keys are set, otherwise in the offline anchor table, labelled `offline`. Only the digest ever
leaves the server; the salt never does. Until an opt-in flow exists, the only obligations are
the synthetic demo ring, seeded on first use by a synthetic tenant and labelled `synthetic`.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.chain.anchor import Anchorer, SepoliaAnchorer
from app.chain.digest import new_salt
from app.chain.store import StoredOfflineAnchorer
from app.contracts import (
    ActionType,
    AnchorChain,
    AnchorReceipt,
    ApiError,
    DataMode,
    MeshObligation,
    NettingRound,
    Principal,
    RoundStatus,
    Tier,
)
from app.engines.mesh import consent
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import propose_rounds
from app.engines.mesh.settlement import seal_and_anchor, settle, verify
from app.engines.mesh.store import MeshStore
from app.main import get_session
from app.security import policy
from app.security.audit import AuditLog
from app.security.clock import Clock
from app.security.deps import StepUp, get_clock, require, step_up
from app.security.errors import ProblemRoute
from app.security.models import TenantRow
from app.security.roles import Permission
from app.settings import ChainMode
from app.synthetic.universe import SME_IDS

router = APIRouter(prefix="/mesh", tags=["mesh"], route_class=ProblemRoute)


class MeshGraph(BaseModel):
    obligations: list[MeshObligation]
    labels: dict[str, str]


class RoundVerification(BaseModel):
    round_id: str
    valid: bool
    recomputed_digest: str
    anchor: AnchorReceipt | None
    reason: str


@dataclass
class Anchors:
    """Where new anchors go, and how to read an anchor back for each chain."""

    write: Anchorer
    readers: dict[AnchorChain, Anchorer] = field(default_factory=dict)


def get_anchors(request: Request, session: Session = Depends(get_session)) -> Anchors:
    offline = StoredOfflineAnchorer(session)
    settings = request.app.state.settings
    rpc = settings.sepolia_rpc_url.get_secret_value()
    key = settings.sepolia_private_key.get_secret_value()
    if settings.chain_mode is ChainMode.sepolia and rpc and key:
        sepolia = SepoliaAnchorer.from_settings(rpc, key)
        return Anchors(sepolia, {AnchorChain.offline: offline, AnchorChain.sepolia: sepolia})
    return Anchors(offline, {AnchorChain.offline: offline})


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _not_found(round_id: str) -> JSONResponse:
    return _error(404, "round_not_found", "error.round_not_found", round_id=round_id[:80])


def _store(session: Session, principal: Principal) -> MeshStore:
    store = MeshStore(session)
    if principal.tenant_id in SME_IDS:
        store.ensure_demo_ring()
    return store


def _visible(obligations: list[MeshObligation], tenant: str) -> list[MeshObligation]:
    graph = build_graph(obligations)
    group = next((set(g) for g in graph.nettable_groups() if tenant in g), {tenant})
    return [o for o in obligations
            if tenant in (o.debtor_tenant, o.creditor_tenant)
            or {o.debtor_tenant, o.creditor_tenant} <= group]


def _labels(session: Session, tenants: set[str]) -> dict[str, str]:
    labels = {}
    for tenant in sorted(tenants):
        row = session.get(TenantRow, tenant)
        labels[tenant] = row.business_name if row is not None else tenant
    return labels


def _audit(session: Session, principal: Principal, action: str, round_: NettingRound,
           clock: Clock, tier: Tier) -> None:
    AuditLog(session).append(principal.tenant_id, actor=principal.user_id, action=action,
                             now=clock(), tier=tier, target=round_.id)


@router.get("/obligations", response_model=MeshGraph)
def obligations(principal: Principal = Depends(require(Permission.ledger_read)),
                session: Session = Depends(get_session)) -> MeshGraph:
    visible = _visible(_store(session, principal).obligations(), principal.tenant_id)
    parties = {t for o in visible for t in (o.debtor_tenant, o.creditor_tenant)}
    return MeshGraph(obligations=visible, labels=_labels(session, parties))


@router.get("/rounds", response_model=list[NettingRound])
def rounds(principal: Principal = Depends(require(Permission.ledger_read)),
           clock: Clock = Depends(get_clock),
           session: Session = Depends(get_session)) -> list[NettingRound]:
    return _store(session, principal).rounds_for(principal.tenant_id, clock())


@router.post("/rounds/propose", response_model=NettingRound)
def propose(principal: Principal = Depends(require(Permission.ledger_read)),
            clock: Clock = Depends(get_clock),
            session: Session = Depends(get_session)) -> NettingRound | JSONResponse:
    if not policy.decide(principal.role, ActionType.propose_netting_round).allowed:
        return _error(403, "forbidden", "error.forbidden", reason="tier")
    now = clock()
    store = _store(session, principal)
    graph = build_graph(store.obligations())
    group = next((g for g in graph.nettable_groups() if principal.tenant_id in g), None)
    if group is None:
        return _error(409, "nothing_to_net", "error.nothing_to_net")
    modes = {graph.obligations[oid].data_mode for _, _, d in graph.graph.subgraph(group)
             .edges(data=True) for oid in d["obligation_ids"]}
    mode = DataMode.synthetic if DataMode.synthetic in modes else next(iter(modes))
    proposed = next(r for r in propose_rounds(graph, now=now, data_mode=mode,
                                              round_id_prefix=f"round-{secrets.token_hex(3)}")
                    if principal.tenant_id in r.participants)
    existing = store.open_round_with(proposed.obligation_ids, now)
    if existing is not None:
        return existing
    store.save_round(proposed, new_salt())
    _audit(session, principal, "mesh.round_proposed", proposed, clock, Tier.DRAFT)
    return proposed


@router.post("/rounds/{round_id}/approve", response_model=NettingRound)
def approve(round_id: str,
            principal: Principal = Depends(require(Permission.approvals_decide)),
            step: StepUp = Depends(step_up),
            clock: Clock = Depends(get_clock),
            session: Session = Depends(get_session),
            anchors: Anchors = Depends(get_anchors)) -> NettingRound | JSONResponse:
    store = _store(session, principal)
    now = clock()
    stored = store.get_round(round_id, now)
    if stored is None or principal.tenant_id not in stored.round.participants:
        return _not_found(round_id)
    decision = policy.decide(principal.role, ActionType.approve_netting_round,
                             consent.APPROVAL_TIER)
    if not decision.allowed:
        return _error(403, "forbidden", "error.forbidden", reason=decision.reason)
    if step.problem is not None:
        return step.problem.response()
    try:
        round_ = consent.approve(stored.round, principal.tenant_id, step_up_verified=True, now=now)
    except consent.ConsentError:
        return _error(409, "round_not_open", "error.round_not_open",
                      round_status=stored.round.status.value)
    _audit(session, principal, "mesh.round_approved", round_, clock, Tier.EXECUTE)
    if round_.status is RoundStatus.approved:
        current = {o.id: o for o in store.obligations()}
        round_, discharged, _ = settle(round_, current, now=now)
        store.put_obligations(discharged)
        round_ = seal_and_anchor(round_, stored.salt, anchors.write, now=now)
        _audit(session, principal, "mesh.round_settled", round_, clock, Tier.EXECUTE)
    store.save_round(round_)
    return round_


@router.post("/rounds/{round_id}/reject", response_model=NettingRound)
def reject(round_id: str,
           principal: Principal = Depends(require(Permission.approvals_decide)),
           clock: Clock = Depends(get_clock),
           session: Session = Depends(get_session)) -> NettingRound | JSONResponse:
    store = _store(session, principal)
    stored = store.get_round(round_id, clock())
    if stored is None or principal.tenant_id not in stored.round.participants:
        return _not_found(round_id)
    try:
        round_ = consent.reject(stored.round, principal.tenant_id, now=clock())
    except consent.ConsentError:
        return _error(409, "round_not_open", "error.round_not_open",
                      round_status=stored.round.status.value)
    store.save_round(round_)
    _audit(session, principal, "mesh.round_rejected", round_, clock, Tier.DRAFT)
    return round_


@router.get("/rounds/{round_id}/verify", response_model=RoundVerification)
def verify_round(round_id: str,
                 principal: Principal = Depends(require(Permission.ledger_read)),
                 clock: Clock = Depends(get_clock),
                 session: Session = Depends(get_session),
                 anchors: Anchors = Depends(get_anchors)) -> RoundVerification | JSONResponse:
    stored = _store(session, principal).get_round(round_id, clock())
    if stored is None or principal.tenant_id not in stored.round.participants:
        return _not_found(round_id)
    receipt = stored.round.anchor
    if receipt is None:
        return _error(404, "not_anchored", "error.not_anchored", round_id=round_id[:80])
    reader = anchors.readers.get(receipt.chain)
    if reader is None:
        return _error(503, "chain_unavailable", "error.chain_unavailable",
                      chain=receipt.chain.value)
    result = verify(stored.round, stored.salt, reader)
    return RoundVerification(round_id=stored.round.id, valid=result.valid,
                             recomputed_digest=result.recomputed, anchor=receipt,
                             reason=result.reason)
