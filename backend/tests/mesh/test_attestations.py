import pytest

from app.contracts import AttestationKind, Money
from app.engines.mesh.attestations import (
    AttestationError,
    apply_attestations,
    attest,
    is_peer_verified,
    obligation_digest,
)
from tests.mesh.helpers import NOW, ob

CONFIRM, DISPUTE = AttestationKind.confirm, AttestationKind.dispute
OB = ob("inv-7", "garment", "fabric", 450000)


def att(tenant, kind=CONFIRM, obligation=OB, n=1):
    return attest(obligation, tenant, kind, attestation_id=f"a{n}-{tenant}", now=NOW)


def test_only_the_two_parties_can_attest():
    with pytest.raises(AttestationError, match="not a party"):
        att("hardware")


def test_both_confirmations_make_the_record_peer_verified():
    assert is_peer_verified(OB, [att("garment"), att("fabric")])
    assert apply_attestations(OB, [att("garment"), att("fabric")]).attested


def test_one_confirmation_is_not_enough():
    assert not is_peer_verified(OB, [att("garment"), att("garment", n=2)])


def test_a_dispute_from_either_side_blocks_verification():
    assert not is_peer_verified(OB, [att("garment"), att("fabric"), att("fabric", DISPUTE, n=2)])


def test_a_confirmation_of_a_different_amount_does_not_count():
    altered = OB.model_copy(update={"amount": Money.of(400000)})
    assert not is_peer_verified(OB, [att("garment"), att("fabric", obligation=altered)])


def test_digest_ignores_status_flags_but_not_terms():
    assert obligation_digest(OB) == obligation_digest(OB.model_copy(update={"attested": True}))
    assert obligation_digest(OB) != obligation_digest(
        OB.model_copy(update={"due_date": OB.due_date.replace(day=OB.due_date.day + 1)}))
