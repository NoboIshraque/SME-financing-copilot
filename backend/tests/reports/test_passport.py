from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.chain.anchor import OfflineAnchorer
from app.contracts import (
    Attestation,
    AttestationKind,
    DataMode,
    EvidenceItem,
    EvidenceKind,
    Period,
)
from app.reports.passport import (
    PassportError,
    anchor_passport,
    build_passport,
    passport_digest,
    verified_share,
)
from app.reports.verify import verify_passport

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)
SALT = "3" * 64
SEPT = Period(start=date(2026, 9, 1), end=date(2026, 9, 30))
EVIDENCE = [
    EvidenceItem(kind=EvidenceKind.bank_statement, digest="a" * 64, period=SEPT, verified=True),
    EvidenceItem(kind=EvidenceKind.mobile_money_statement, digest="b" * 64, period=SEPT,
                 verified=True),
    EvidenceItem(kind=EvidenceKind.trade_licence, digest="c" * 64, verified=False),
]


def att(n, kind=AttestationKind.confirm):
    return Attestation(id=f"att{n}", obligation_id=f"o{n}", attester_tenant="sme_garment",
                       kind=kind, digest="d" * 64, created_at=NOW)


def build(previous=None, evidence=EVIDENCE, atts=(att(1), att(2), att(3, AttestationKind.dispute))):
    return build_passport(tenant_id="sme_fabric", previous=previous, evidence=evidence,
                          attestations=atts, abstention_rate=Decimal("0.08"),
                          audit_drill_catch_rate=Decimal("0.93"), salt=SALT, now=NOW,
                          data_mode=DataMode.synthetic)


def test_passport_counts_attestations_and_versions():
    v1 = build()
    assert (v1.version, v1.attestations_confirmed, v1.attestations_disputed) == (1, 2, 1)
    v2 = build(previous=v1)
    assert v2.version == 2


def test_passport_ids_cannot_be_guessed_from_the_shop_or_version():
    v1 = build()
    v2 = build(previous=v1)
    assert v1.id != v2.id
    for passport in (v1, v2):
        assert passport.tenant_id not in passport.id
        assert not passport.id.endswith(f"v{passport.version}")
        assert len(passport.id) >= 16


def test_digest_is_salted_and_matches_the_sealed_content():
    p = build()
    assert p.digest == passport_digest(p, SALT)
    assert p.digest != passport_digest(p, "4" * 64)


def test_evidence_order_does_not_change_the_digest():
    assert build().digest == build(evidence=list(reversed(EVIDENCE))).digest


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"evidence": []}, "at least one"),
    ({"evidence": [EVIDENCE[0], EVIDENCE[0]]}, "duplicate"),
])
def test_invalid_passports_are_refused(kwargs, message):
    with pytest.raises(PassportError, match=message):
        build(**kwargs)


def test_previous_version_must_belong_to_the_same_tenant():
    other = build().model_copy(update={"tenant_id": "sme_grocery"})
    with pytest.raises(PassportError, match="another tenant"):
        build(previous=other)


def test_verified_share_counts_only_source_checked_documents():
    assert verified_share(build()) == Decimal(2) / Decimal(3)


@pytest.fixture
def anchored():
    anchorer = OfflineAnchorer()
    return anchor_passport(build(), anchorer, now=NOW), anchorer


def test_anchored_passport_verifies(anchored):
    p, anchorer = anchored
    result = verify_passport(p, SALT, anchorer, today=date(2026, 10, 18))
    assert result.valid and result.anchored_digest == p.digest


@pytest.mark.parametrize("edit", [
    {"attestations_confirmed": 9},
    {"abstention_rate": Decimal("0.01")},
    {"audit_drill_catch_rate": Decimal("1")},
    {"version": 7},
])
def test_any_edited_passport_fails_verification(anchored, edit):
    p, anchorer = anchored
    assert not verify_passport(p.model_copy(update=edit), SALT, anchorer,
                               today=date(2026, 10, 18)).valid


def test_a_passport_whose_evidence_was_swapped_fails(anchored):
    p, anchorer = anchored
    swapped = p.model_copy(update={"evidence": (EVIDENCE[0].model_copy(
        update={"digest": "e" * 64}), *p.evidence[1:])})
    assert not verify_passport(swapped, SALT, anchorer, today=date(2026, 10, 18)).valid


def test_unanchored_or_unknown_anchor_fails(anchored):
    p, _ = anchored
    assert not verify_passport(build(), SALT, OfflineAnchorer(), today=date(2026, 10, 18)).valid
    assert not verify_passport(p, SALT, OfflineAnchorer(), today=date(2026, 10, 18)).valid


def test_wrong_salt_fails(anchored):
    p, anchorer = anchored
    assert not verify_passport(p, "5" * 64, anchorer, today=date(2026, 10, 18)).valid


def test_build_time_is_part_of_the_seal():
    later = build_passport(tenant_id="sme_fabric", previous=None, evidence=EVIDENCE,
                           attestations=(), abstention_rate=None, audit_drill_catch_rate=None,
                           salt=SALT, now=NOW + timedelta(seconds=1),
                           data_mode=DataMode.synthetic)
    same = build_passport(tenant_id="sme_fabric", previous=None, evidence=EVIDENCE,
                          attestations=(), abstention_rate=None, audit_drill_catch_rate=None,
                          salt=SALT, now=NOW, data_mode=DataMode.synthetic)
    assert later.digest != same.digest
