import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.chain.anchor import OfflineAnchorer
from app.contracts import GENESIS_HASH, ActionCard, Role, Tier
from app.db import init_db, make_engine, session_factory
from app.security import totp
from app.security.audit import AuditLog, anchor_digest_matches, link_hash
from app.security.jobs import anchor_audit_heads
from app.security.models import AppendOnlyViolation, AuditRow
from app.settings import Settings
from app.worker import discover_jobs
from tests.security.conftest import PASSWORD, sign_in

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def fill(db, n=5, tenant="t1"):
    log = AuditLog(db)
    for i in range(n):
        log.append(tenant, actor=f"u-{i}", action="test.event", now=T0 + timedelta(minutes=i),
                   tier=Tier.READ if i % 2 else None, target=f"x-{i}", details={"n": i})
    db.commit()
    return log


def drop_triggers(db):
    """Simulate an attacker with direct database access (bypasses the append-only guards)."""
    db.execute(text("DROP TRIGGER security_audit_no_update"))
    db.execute(text("DROP TRIGGER security_audit_no_delete"))
    db.commit()


def test_links_chain_from_genesis_and_verify(db):
    log = fill(db)
    events = sorted(log.events("t1"), key=lambda e: e.seq)
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[0].prev_hash == GENESIS_HASH
    assert all(b.prev_hash == a.hash for a, b in zip(events, events[1:], strict=False))
    report = log.verify("t1")
    assert report.valid and report.length == 5 and report.head_hash == events[-1].hash


def test_the_hash_covers_every_field(db):
    event = fill(db, 1).events("t1")[0]
    base = {"seq": 1, "tenant_id": "t1", "at": T0, "actor": "u-0", "action": "test.event",
            "tier": None, "target": "x-0", "details_digest": event.details_digest,
            "prev_hash": GENESIS_HASH}
    assert link_hash(**base) == event.hash
    for field, value in [("seq", 2), ("tenant_id", "t2"), ("at", T0 + timedelta(seconds=1)),
                         ("actor", "u-9"), ("action", "other"), ("tier", "EXECUTE"),
                         ("target", "x-9"), ("details_digest", "0" * 64),
                         ("prev_hash", "1" * 64)]:
        assert link_hash(**{**base, field: value}) != event.hash, field


def test_chains_are_per_tenant(db):
    fill(db, 3, "t1")
    fill(db, 2, "t2")
    log = AuditLog(db)
    assert log.verify("t1").length == 3 and log.verify("t2").length == 2
    assert {e.tenant_id for e in log.events("t2")} == {"t2"}


def test_orm_updates_and_deletes_are_refused(db):
    fill(db, 2)
    row = db.get(AuditRow, ("t1", 1))
    row.actor = "someone-else"
    with pytest.raises(AppendOnlyViolation):
        db.flush()
    db.rollback()
    with pytest.raises(AppendOnlyViolation):
        db.delete(db.get(AuditRow, ("t1", 2)))
        db.flush()
    db.rollback()


@pytest.mark.parametrize("statement", [
    "UPDATE security_audit SET actor = 'x' WHERE seq = 1",
    "DELETE FROM security_audit WHERE seq = 2",
])
def test_database_triggers_refuse_raw_updates_and_deletes(db, statement):
    fill(db, 3)
    with pytest.raises(DatabaseError, match="append-only"):
        db.execute(text(statement))
    db.rollback()
    assert AuditLog(db).verify("t1").valid


@pytest.mark.parametrize(("statement", "first_bad", "reason"), [
    ("UPDATE security_audit SET details = replace(details, '2', '99') WHERE seq = 3", 3,
     "details_changed"),
    ("UPDATE security_audit SET actor = 'u-evil' WHERE seq = 2", 2, "row_changed"),
    ("UPDATE security_audit SET at = '2026-10-01 08:00:00.000000' WHERE seq = 4", 4,
     "row_changed"),
    ("DELETE FROM security_audit WHERE seq = 3", 3, "missing_or_reordered"),
    ("DELETE FROM security_audit WHERE seq = 1", 1, "missing_or_reordered"),
])
def test_tampering_is_detected(db, statement, first_bad, reason):
    fill(db)
    drop_triggers(db)
    db.execute(text(statement))
    db.commit()
    report = AuditLog(db).verify("t1")
    assert not report.valid
    assert (report.first_bad_seq, report.reason) == (first_bad, reason)


def test_reordering_rows_is_detected(db):
    fill(db)
    drop_triggers(db)
    db.execute(text("UPDATE security_audit SET seq = 100 WHERE seq = 2"))
    db.execute(text("UPDATE security_audit SET seq = 2 WHERE seq = 3"))
    db.execute(text("UPDATE security_audit SET seq = 3 WHERE seq = 100"))
    db.commit()
    report = AuditLog(db).verify("t1")
    assert not report.valid and report.first_bad_seq == 2


def test_a_recomputed_forgery_still_breaks_the_next_link(db):
    log = fill(db)
    drop_triggers(db)
    row = db.get(AuditRow, ("t1", 2))
    forged = link_hash(seq=2, tenant_id="t1", at=row.at, actor="u-evil", action=row.action,
                       tier=row.tier, target=row.target, details_digest=row.details_digest,
                       prev_hash=row.prev_hash)
    db.execute(text("UPDATE security_audit SET actor='u-evil', hash=:h WHERE seq=2"),
               {"h": forged})
    db.commit()
    report = log.verify("t1")
    assert not report.valid and (report.first_bad_seq, report.reason) == (3, "broken_link")


def test_cutting_the_tail_is_caught_only_once_the_head_is_anchored(db):
    log = fill(db)
    drop_triggers(db)
    db.execute(text("DELETE FROM security_audit WHERE seq = 5"))
    db.commit()
    assert log.verify("t1").valid  # an unanchored tail cut leaves a valid shorter chain
    fill(db, 1)  # chain grows back to seq 5 with a different event
    log.anchor_day(date(2026, 10, 1), OfflineAnchorer(), T0)
    db.commit()
    db.execute(text("DELETE FROM security_audit WHERE seq = 5"))
    db.commit()
    report = log.verify("t1")
    assert not report.valid and report.reason == "anchored_head_missing"
    assert report.first_bad_seq == 5


def test_daily_anchor_commits_all_heads_once_per_day(db):
    fill(db, 3, "t1")
    fill(db, 2, "t2")
    log = AuditLog(db)
    anchorer = OfflineAnchorer()
    first = log.anchor_day(date(2026, 10, 1), anchorer, T0)
    again = log.anchor_day(date(2026, 10, 1), anchorer, T0 + timedelta(hours=1))
    assert again.digest == first.digest and len(log.anchors()) == 1
    heads = json.loads(first.heads)
    assert [(h[0], h[1]) for h in heads] == [("t1", 3), ("t2", 2)]
    assert first.chain == "offline" and len(first.digest) == 64
    assert anchor_digest_matches(first)
    assert log.verify("t1").anchors_checked == 1


def test_nothing_to_anchor_on_an_empty_log(db):
    assert AuditLog(db).anchor_day(date(2026, 10, 1), OfflineAnchorer(), T0) is None


def test_the_worker_job_anchors_the_heads(tmp_path):
    url = f"sqlite:///{tmp_path / 'audit.db'}"
    engine = make_engine(url)
    init_db(engine)
    with session_factory(engine)() as db:
        fill(db, 2)
    engine.dispose()
    settings = Settings(_env_file=None, app_env="test", database_url=url, chain_mode="offline")
    digest = anchor_audit_heads(settings, T0)
    assert len(digest) == 64
    assert anchor_audit_heads(settings, T0 + timedelta(minutes=5)) == digest  # once a day
    assert "security.anchor_audit_heads" in {job.name for job in discover_jobs()}


# ------------------------------------------------------------------------------ API


def test_sign_ins_are_audited_without_personal_data(api, app, make_user):
    make_user()
    sign_in(api, password="wrong password!")
    sign_in(api, email="ghost@shop.test", password="wrong password!")
    sign_in(api)
    with app.state.session_factory() as db:
        rows = db.query(AuditRow).order_by(AuditRow.tenant_id, AuditRow.seq).all()
    actions = [(row.tenant_id, row.action) for row in rows]
    assert ("t1", "auth.login_failed") in actions and ("t1", "auth.login") in actions
    assert ("_system", "auth.login_failed") in actions  # unknown email: no tenant
    blob = json.dumps([[r.actor, r.details, r.target] for r in rows])
    assert "ghost" not in blob and "owner@shop.test" not in blob and PASSWORD not in blob


def test_the_approval_lifecycle_is_audited(api, app, make_user, clock, issue):
    make_user(totp_secret=SECRET)
    sign_in(api)
    api.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
    clock.advance(seconds=30)
    card = {"id": "act-1", "title_key": "t", "action_type": "move_money", "tier": "EXECUTE"}
    issue(ActionCard.model_validate(card))
    approval = api.post("/api/approvals", headers={"X-Idempotency-Key": "idem-0001"},
                        json={"card": card}).json()["approval"]
    api.post(f"/api/approvals/{approval['id']}/approve",
             headers={"X-Step-Up-Code": totp.code_at(SECRET, clock())})
    api.post(f"/api/approvals/{approval['id']}/execute",
             headers={"X-Idempotency-Key": "exec-0001"})
    denied = {"id": "act-2", "title_key": "t", "action_type": "add_payee", "tier": "DRAFT"}
    api.post("/api/approvals", headers={"X-Idempotency-Key": "idem-0002"}, json={"card": denied})
    events = api.get("/api/audit/events").json()
    actions = [e["action"] for e in reversed(events)]
    assert actions[-4:] == ["approval.requested", "approval.approved", "approval.executed",
                            "approval.refused"]
    assert events[0]["tier"] == "DENY"
    assert api.get("/api/audit/verify").json()["valid"] is True


def test_failed_step_ups_are_audited(api, make_user, clock):
    make_user(totp_secret=SECRET)
    sign_in(api)
    api.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
    api.post("/api/auth/lender-access", headers={"X-Step-Up-Code": "000000"}, json={
        "lender_email": "b@bank.test", "lender_label": "B", "purpose": "p",
        "scopes": ["passport:read"], "days": 3, "consent": True})
    assert api.get("/api/audit/events", params={"limit": 1}).json()[0]["action"] == \
        "auth.step_up_failed"


def test_compliance_verifies_and_anchors_the_chain(api, make_user):
    make_user()
    make_user("audit@shop.test", role=Role.compliance)
    sign_in(api)  # owner: one auth.login event
    sign_in(api, "audit@shop.test")
    report = api.get("/api/audit/verify").json()
    assert report["valid"] is True and report["length"] >= 2
    anchor = api.post("/api/audit/anchor").json()
    assert anchor["chain"] == "offline" and anchor["heads"] >= 1
    assert api.get("/api/audit/anchors").json()[0]["digest"] == anchor["digest"]
    assert api.get("/api/audit/verify").json()["anchors_checked"] == 1


@pytest.mark.parametrize(("role", "path", "status"), [
    (Role.staff, "/api/audit/events", 403),
    (Role.accountant, "/api/audit/verify", 403),
    (Role.compliance, "/api/audit/events", 200),
])
def test_audit_access_follows_permissions(api, make_user, role, path, status):
    make_user("member@shop.test", role=role)
    sign_in(api, "member@shop.test")
    assert api.get(path).status_code == status


def test_audit_events_page_backwards(api, make_user):
    make_user()
    for _ in range(4):
        sign_in(api)
    newest = api.get("/api/audit/events", params={"limit": 2}).json()
    older = api.get("/api/audit/events",
                    params={"limit": 2, "before_seq": newest[-1]["seq"]}).json()
    assert [e["seq"] for e in newest] == [4, 3] and [e["seq"] for e in older] == [2, 1]
