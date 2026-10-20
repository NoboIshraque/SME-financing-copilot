"""Trust Passport (WP-13 milestone 2; FEATURES Q4).

A passport version bundles the SME's verifiable evidence (statements, licences, the lender
report), counterparty attestations from the mesh, and DecisionGuard's own reliability record
(abstention rate, audit-drill catch rate). Each version is sealed with a salted SHA-256
commitment and the digest is anchored (WP-08). The SME gives a lender the passport document
plus its salt; the lender recomputes the digest and compares it with the chain, trusting
neither the SME nor DecisionGuard.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from app.chain.anchor import Anchorer
from app.chain.digest import canonical, commit
from app.contracts import (
    Attestation,
    AttestationKind,
    DataMode,
    EvidenceItem,
    PassportVersion,
)

KIND = "trust_passport"
_UNSEALED = {"anchor", "digest"}


class PassportError(ValueError):
    pass


def passport_digest(passport: PassportVersion, salt: str) -> str:
    return commit(KIND, salt, canonical(passport, exclude=_UNSEALED))


def build_passport(
    *,
    tenant_id: str,
    previous: PassportVersion | None,
    evidence: Sequence[EvidenceItem],
    attestations: Iterable[Attestation],
    abstention_rate: Decimal | None,
    audit_drill_catch_rate: Decimal | None,
    salt: str,
    now: datetime,
    data_mode: DataMode,
) -> PassportVersion:
    if not evidence:
        raise PassportError("a passport needs at least one piece of evidence")
    if previous is not None and previous.tenant_id != tenant_id:
        raise PassportError("previous version belongs to another tenant")
    pairs = [(e.kind, e.digest) for e in evidence]
    if len(pairs) != len(set(pairs)):
        raise PassportError("duplicate evidence item")
    atts = list(attestations)
    version = 1 if previous is None else previous.version + 1
    draft = PassportVersion(
        # Derived from the secret salt, so the public verify page reveals neither which shops
        # exist nor how many versions they issued (pp-<tenant>-v<n> could be guessed).
        id="pp-" + hashlib.sha256(f"{salt}:{tenant_id}:{version}".encode()).hexdigest()[:20],
        tenant_id=tenant_id,
        version=version,
        issued_at=now,
        evidence=tuple(sorted(evidence, key=lambda e: (e.kind.value, e.digest))),
        attestations_confirmed=sum(1 for a in atts if a.kind is AttestationKind.confirm),
        attestations_disputed=sum(1 for a in atts if a.kind is AttestationKind.dispute),
        abstention_rate=abstention_rate,
        audit_drill_catch_rate=audit_drill_catch_rate,
        digest="0" * 64,
        data_mode=data_mode,
    )
    return draft.model_copy(update={"digest": passport_digest(draft, salt)})


def anchor_passport(passport: PassportVersion, anchorer: Anchorer, *,
                    now: datetime) -> PassportVersion:
    return passport.model_copy(update={"anchor": anchorer.anchor(passport.digest, now)})


def verified_share(passport: PassportVersion) -> Decimal:
    """Share of evidence items checked against their source (not self-declared)."""
    checked = sum(1 for e in passport.evidence if e.verified)
    return Decimal(checked) / Decimal(len(passport.evidence))
