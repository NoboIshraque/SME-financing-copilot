"""Append-only, SHA-256 hash-chained audit log, one chain per tenant (WP-11 milestone 4).

    log = AuditLog(db)
    log.append("sme_grocery", actor="u-1", action="approval.approve", tier=Tier.EXECUTE,
               target="ap-1", details={"step_up": True}, now=now)
    report = log.verify("sme_grocery")        # valid? first bad seq? head?

hash_n = SHA-256(canonical JSON of seq, tenant_id, at, actor, action, tier, target,
                 details_digest, prev_hash = hash_(n-1)); the first link uses GENESIS_HASH.

The chain alone detects an edited, deleted or reordered row. Cutting off the newest rows
leaves a valid shorter chain; the daily anchor catches that: every day the heads of all
chains are committed to one digest that goes on chain (WP-08's `app.chain.anchor`), and
`verify` checks the current chains still contain every anchored head.

Details hold ids, counts and digests only, never names, emails or phone numbers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.chain.anchor import Anchorer
from app.contracts import GENESIS_HASH, AuditEvent, Tier
from app.security.models import AuditAnchorRow, AuditRow

SYSTEM_TENANT = "_system"  # events with no tenant, e.g. a failed sign-in for an unknown email
_APPEND_RETRIES = 5


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def link_hash(*, seq: int, tenant_id: str, at: datetime, actor: str, action: str,
              tier: str | None, target: str | None, details_digest: str, prev_hash: str) -> str:
    return sha256(canonical({
        "seq": seq, "tenant_id": tenant_id, "at": at.isoformat(timespec="microseconds"),
        "actor": actor, "action": action, "tier": tier, "target": target,
        "details_digest": details_digest, "prev_hash": prev_hash,
    }))


def to_event(row: AuditRow) -> AuditEvent:
    return AuditEvent(seq=row.seq, tenant_id=row.tenant_id, at=row.at, actor=row.actor,
                      action=row.action, tier=Tier(row.tier) if row.tier else None,
                      target=row.target, details_digest=row.details_digest,
                      prev_hash=row.prev_hash, hash=row.hash)


@dataclass(frozen=True)
class ChainReport:
    tenant_id: str
    valid: bool
    length: int
    head_hash: str
    first_bad_seq: int | None = None
    reason: str | None = None
    anchors_checked: int = 0


class AuditLog:
    def __init__(self, db: Session) -> None:
        self.db = db

    def head(self, tenant_id: str) -> AuditRow | None:
        return self.db.scalar(select(AuditRow).where(AuditRow.tenant_id == tenant_id)
                              .order_by(AuditRow.seq.desc()).limit(1))

    def append(self, tenant_id: str, *, actor: str, action: str, now: datetime,
               tier: Tier | None = None, target: str | None = None,
               details: dict[str, Any] | None = None) -> AuditEvent:
        details_json = canonical(details or {})
        for _attempt in range(_APPEND_RETRIES):
            head = self.head(tenant_id)
            seq = head.seq + 1 if head else 1
            prev = head.hash if head else GENESIS_HASH
            digest = sha256(details_json)
            row = AuditRow(tenant_id=tenant_id, seq=seq, at=now, actor=actor, action=action,
                           tier=tier.value if tier else None, target=target,
                           details=details_json, details_digest=digest, prev_hash=prev,
                           hash=link_hash(seq=seq, tenant_id=tenant_id, at=now, actor=actor,
                                          action=action, tier=tier.value if tier else None,
                                          target=target, details_digest=digest,
                                          prev_hash=prev))
            try:
                with self.db.begin_nested():
                    self.db.add(row)
            except IntegrityError:
                continue  # another request took this seq; chain onto the new head
            return to_event(row)
        raise RuntimeError("audit append kept colliding; giving up")

    def events(self, tenant_id: str, *, limit: int = 100,
               before_seq: int | None = None) -> list[AuditEvent]:
        query = select(AuditRow).where(AuditRow.tenant_id == tenant_id)
        if before_seq is not None:
            query = query.where(AuditRow.seq < before_seq)
        rows = self.db.scalars(query.order_by(AuditRow.seq.desc()).limit(limit))
        return [to_event(row) for row in rows]

    def verify(self, tenant_id: str) -> ChainReport:
        # populate_existing: verify what the database holds now, never a cached copy
        rows = list(self.db.scalars(select(AuditRow).where(AuditRow.tenant_id == tenant_id)
                                    .order_by(AuditRow.seq)
                                    .execution_options(populate_existing=True)))
        prev, expected_seq = GENESIS_HASH, 1
        hashes: dict[int, str] = {}
        for row in rows:
            problem = None
            if row.seq != expected_seq:
                problem = "missing_or_reordered"
            elif row.prev_hash != prev:
                problem = "broken_link"
            elif sha256(row.details) != row.details_digest:
                problem = "details_changed"
            elif row.hash != link_hash(seq=row.seq, tenant_id=row.tenant_id, at=row.at,
                                       actor=row.actor, action=row.action, tier=row.tier,
                                       target=row.target, details_digest=row.details_digest,
                                       prev_hash=row.prev_hash):
                problem = "row_changed"
            if problem:
                return ChainReport(tenant_id, False, len(rows), prev, first_bad_seq=expected_seq,
                                   reason=problem)
            hashes[row.seq] = row.hash
            prev, expected_seq = row.hash, expected_seq + 1
        checked = 0
        for anchor in self.db.scalars(select(AuditAnchorRow).order_by(AuditAnchorRow.day)):
            for anchored_tenant, seq, anchored_hash in json.loads(anchor.heads):
                if anchored_tenant != tenant_id:
                    continue
                checked += 1
                if hashes.get(seq) != anchored_hash:
                    return ChainReport(tenant_id, False, len(rows), prev, first_bad_seq=seq,
                                       reason="anchored_head_missing", anchors_checked=checked)
        return ChainReport(tenant_id, True, len(rows), prev, anchors_checked=checked)

    # ---------------------------------------------------------------- daily anchor

    def heads(self) -> list[tuple[str, int, str]]:
        latest = (select(AuditRow.tenant_id, func.max(AuditRow.seq).label("seq"))
                  .group_by(AuditRow.tenant_id).subquery())
        rows = self.db.execute(select(AuditRow.tenant_id, AuditRow.seq, AuditRow.hash).join(
            latest, (AuditRow.tenant_id == latest.c.tenant_id) & (AuditRow.seq == latest.c.seq)))
        return sorted((tenant, seq, digest) for tenant, seq, digest in rows)

    def anchor_day(self, day: date, anchorer: Anchorer, now: datetime) -> AuditAnchorRow | None:
        """Commit every chain's current head to one digest and anchor it. Idempotent per day;
        None when there is nothing to anchor."""
        existing = self.db.get(AuditAnchorRow, day)
        if existing is not None:
            return existing
        heads = self.heads()
        if not heads:
            return None
        digest = sha256("hishab:v1:audit_heads:" + day.isoformat() + ":" + canonical(heads))
        receipt = anchorer.anchor(digest, now)
        row = AuditAnchorRow(day=day, digest=digest, heads=canonical(heads),
                             chain=receipt.chain.value, tx_hash=receipt.tx_hash,
                             block_number=receipt.block_number,
                             explorer_url=receipt.explorer_url, anchored_at=now)
        self.db.add(row)
        self.db.flush()
        return row

    def anchors(self) -> list[AuditAnchorRow]:
        return list(self.db.scalars(select(AuditAnchorRow).order_by(AuditAnchorRow.day.desc())))


def anchor_digest_matches(row: AuditAnchorRow) -> bool:
    heads = json.loads(row.heads)
    expected = sha256("hishab:v1:audit_heads:" + row.day.isoformat() + ":" + canonical(heads))
    return expected == row.digest
