"""Counterparty attestations (WP-08 milestone 5; FEATURES Q4).

When debtor and creditor both confirm the same obligation, the record is peer-verified: far
stronger evidence for a lender than either side's word. A dispute from either side blocks it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.chain.digest import canonical, commit
from app.contracts import Attestation, AttestationKind, MeshObligation

KIND = "obligation"
# The attested facts: who owes whom, how much, by when. Status flags are not attested.
_NOT_ATTESTED = {"status", "attested", "data_mode"}
# Attestation digests are not secret commitments (both parties hold the record), so a fixed
# public salt is used: either side can recompute and compare.
PUBLIC_SALT = "0" * 64


class AttestationError(ValueError):
    pass


def obligation_digest(obligation: MeshObligation) -> str:
    return commit(KIND, PUBLIC_SALT, canonical(obligation, exclude=_NOT_ATTESTED))


def attest(
    obligation: MeshObligation,
    attester: str,
    kind: AttestationKind,
    *,
    attestation_id: str,
    now: datetime,
) -> Attestation:
    if attester not in (obligation.debtor_tenant, obligation.creditor_tenant):
        raise AttestationError(f"{attester} is not a party to {obligation.id}")
    return Attestation(
        id=attestation_id,
        obligation_id=obligation.id,
        attester_tenant=attester,
        kind=kind,
        digest=obligation_digest(obligation),
        created_at=now,
    )


def is_peer_verified(obligation: MeshObligation, attestations: Iterable[Attestation]) -> bool:
    """Both parties confirmed this exact record, and nobody disputes it."""
    digest = obligation_digest(obligation)
    relevant = [a for a in attestations if a.obligation_id == obligation.id]
    if any(a.kind is AttestationKind.dispute for a in relevant):
        return False
    confirmed = {a.attester_tenant for a in relevant
                 if a.kind is AttestationKind.confirm and a.digest == digest}
    return confirmed == {obligation.debtor_tenant, obligation.creditor_tenant}


def apply_attestations(
    obligation: MeshObligation, attestations: Iterable[Attestation]
) -> MeshObligation:
    return obligation.model_copy(update={"attested": is_peer_verified(obligation, attestations)})
