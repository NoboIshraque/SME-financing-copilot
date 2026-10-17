from datetime import timedelta

import pytest

from app.chain.anchor import AnchorError, OfflineAnchorer, payload_for
from app.chain.digest import commit, new_salt
from app.contracts import Money, ObligationStatus, RoundStatus
from app.engines.mesh.consent import approve
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import propose_rounds
from app.engines.mesh.settlement import (
    SettlementError,
    round_digest,
    seal_and_anchor,
    settle,
    verify,
)
from tests.mesh.helpers import NOW, ring

LATER = NOW + timedelta(hours=2)
SALT = "1" * 64


@pytest.fixture
def world():
    obligations = ring(("garment", "fabric", 450000), ("hardware", "garment", 320000),
                       ("fabric", "hardware", 380000))
    graph = build_graph(obligations)
    r = propose_rounds(graph, now=NOW)[0]
    for tenant in r.participants:
        r = approve(r, tenant, step_up_verified=True, now=LATER)
    return r, graph.obligations


@pytest.fixture
def anchored(world):
    r, obligations = world
    settled, _, _ = settle(r, obligations, now=LATER)
    anchorer = OfflineAnchorer()
    return seal_and_anchor(settled, SALT, anchorer, now=LATER), anchorer


def test_settlement_discharges_every_obligation_and_balances(world):
    r, obligations = world
    settled, discharged, receipts = settle(r, obligations, now=LATER)
    assert settled.status is RoundStatus.settled
    assert {o.status for o in discharged} == {ObligationStatus.settled}
    assert sum((x.debts_cleared for x in receipts), Money.zero()) == r.gross_total
    assert sum((x.cash_out for x in receipts), Money.zero()) == r.net_total


def test_each_receipt_shows_what_that_firm_pays_and_saves(world):
    r, obligations = world
    _, _, receipts = settle(r, obligations, now=LATER)
    garment = next(x for x in receipts if x.tenant == "garment")
    assert garment.pays == (("fabric", Money.of(130000)),)
    assert garment.cash_saved == Money.of(320000)  # owed 4.5 lakh, pays 1.3 lakh
    assert set(garment.obligations_discharged) == {"o1", "o2"}


def test_only_approved_rounds_settle(world):
    r, obligations = world
    proposed = r.model_copy(update={"status": RoundStatus.proposed})
    with pytest.raises(SettlementError, match="approved"):
        settle(proposed, obligations, now=LATER)


def test_expired_rounds_do_not_settle(world):
    r, obligations = world
    with pytest.raises(SettlementError, match="expired"):
        settle(r, obligations, now=r.expires_at)


def test_settlement_refuses_unknown_or_closed_obligations(world):
    r, obligations = world
    with pytest.raises(SettlementError, match="unknown"):
        settle(r, {k: v for k, v in obligations.items() if k != "o1"}, now=LATER)
    closed = {**obligations, "o1": obligations["o1"].model_copy(
        update={"status": ObligationStatus.disputed})}
    with pytest.raises(SettlementError, match="no longer open"):
        settle(r, closed, now=LATER)


def test_digest_is_deterministic_and_salted(world):
    r, _ = world
    assert round_digest(r, SALT) == round_digest(r, SALT)
    assert round_digest(r, SALT) != round_digest(r, "2" * 64)


@pytest.mark.parametrize("bad", ["", "xyz", "A" * 64, "1" * 63])
def test_salt_must_be_32_bytes_of_lowercase_hex(bad):
    with pytest.raises(ValueError, match="salt"):
        commit("netting_round", bad, "{}")


def test_new_salts_are_unique_and_valid():
    salts = {new_salt() for _ in range(50)}
    assert len(salts) == 50
    for salt in salts:
        commit("x", salt, "{}")


def test_verify_accepts_an_untouched_record(anchored):
    r, anchorer = anchored
    result = verify(r, SALT, anchorer)
    assert result.valid and result.recomputed == r.anchor.digest


TAMPERS = {
    "settlement amount": lambda d: d["settlements"][0]["amount"].update(amount="1.00"),
    "payer": lambda d: d["settlements"][0].update(payer_tenant="garment"),
    "gross total": lambda d: d["gross_total"].update(amount="1150001.00"),
    "net total": lambda d: d["net_total"].update(amount="1.00"),
    "approvals": lambda d: d["approvals"].update(fabric=False),
    "created at": lambda d: d.update(created_at="2026-10-01T09:00:01Z"),
    "obligation ids": lambda d: d.update(obligation_ids=["o1", "o2", "o9"]),
    "participants": lambda d: d.update(participants=["fabric", "garment", "outsider"]),
}


@pytest.mark.parametrize("field", sorted(TAMPERS))
def test_verify_detects_any_edited_field(anchored, field):
    r, anchorer = anchored
    data = r.model_dump(mode="json")
    TAMPERS[field](data)
    data["approvals"] = {k: v for k, v in data["approvals"].items() if k in data["participants"]}
    edited = type(r).model_validate(data)
    result = verify(edited, SALT, anchorer)
    assert not result.valid and result.reason == "record was changed after anchoring"


def test_verify_with_the_wrong_salt_fails(anchored):
    r, anchorer = anchored
    assert not verify(r, "2" * 64, anchorer).valid


def test_verify_fails_when_not_anchored_or_anchor_unknown(world, anchored):
    r, anchorer = anchored
    assert verify(r.model_copy(update={"anchor": None}), SALT, anchorer).reason == (
        "round has not been anchored")
    assert verify(r, SALT, OfflineAnchorer()).reason == "anchor not found on chain"


def test_only_settled_rounds_are_anchored(world):
    r, _ = world
    with pytest.raises(SettlementError, match="settled"):
        seal_and_anchor(r, SALT, OfflineAnchorer(), now=LATER)


def test_the_on_chain_payload_is_only_the_32_byte_digest(anchored):
    r, _ = anchored
    payload = payload_for(r.anchor.digest)
    assert len(payload) == 32
    text = payload.decode("latin-1")
    for secret in ("garment", "fabric", "hardware", "450000", "130000", "o1"):
        assert secret not in text


@pytest.mark.parametrize("bad", ["ABC", "a" * 63, "g" * 64, "0x" + "a" * 64])
def test_anything_but_a_hex_digest_is_refused_for_anchoring(bad):
    with pytest.raises(AnchorError):
        payload_for(bad)
