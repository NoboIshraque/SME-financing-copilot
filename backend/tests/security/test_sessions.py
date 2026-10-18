from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.security.models import SessionRow
from app.security.sessions import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    PENDING_TIMEOUT,
    SessionStore,
    Stage,
    cookie_attributes,
    hash_token,
)
from app.settings import AppEnv, Settings

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_only_the_token_digest_is_stored(db):
    token, _row = SessionStore(db).issue("u-1", Stage.active, T0)
    stored = db.scalars(select(SessionRow)).one()
    assert stored.token_hash == hash_token(token) and token not in stored.token_hash
    assert len(token) >= 43  # 256 random bits, base64url


def test_session_ends_after_thirty_idle_minutes(db):
    store = SessionStore(db)
    token, _ = store.issue("u-1", Stage.active, T0)
    assert store.find(token, T0 + IDLE_TIMEOUT - timedelta(seconds=1)) is not None
    later = T0 + IDLE_TIMEOUT - timedelta(seconds=1) + IDLE_TIMEOUT
    assert store.find(token, later) is None


def test_activity_keeps_a_session_alive_only_until_the_absolute_limit(db):
    store = SessionStore(db)
    token, _ = store.issue("u-1", Stage.active, T0)
    now = T0
    while now + timedelta(minutes=20) < T0 + ABSOLUTE_TIMEOUT:
        now += timedelta(minutes=20)
        assert store.find(token, now) is not None
    assert store.find(token, T0 + ABSOLUTE_TIMEOUT) is None


def test_expired_sessions_are_marked_revoked(db):
    store = SessionStore(db)
    token, row = store.issue("u-1", Stage.active, T0)
    assert store.find(token, T0 + timedelta(hours=1)) is None
    assert row.revoked_at == T0 + timedelta(hours=1)


def test_a_pending_session_is_not_an_active_one_and_lasts_five_minutes(db):
    store = SessionStore(db)
    token, _ = store.issue("u-1", Stage.totp_pending, T0)
    assert store.find(token, T0) is None  # stage active by default
    assert store.find(token, T0 + timedelta(minutes=4), Stage.totp_pending) is not None
    assert store.find(token, T0 + PENDING_TIMEOUT, Stage.totp_pending) is None


def test_revoked_sessions_stay_revoked(db):
    store = SessionStore(db)
    token, _ = store.issue("u-1", Stage.active, T0)
    assert store.revoke(token, T0) is True
    assert store.find(token, T0) is None
    assert store.revoke(token, T0) is False


def test_revoke_user_ends_every_session_but_the_one_kept(db):
    store = SessionStore(db)
    keep, _ = store.issue("u-1", Stage.active, T0)
    other, _ = store.issue("u-1", Stage.active, T0)
    stranger, _ = store.issue("u-2", Stage.active, T0)
    assert store.revoke_user("u-1", T0, keep=keep) == 1
    assert store.find(keep, T0) is not None
    assert store.find(other, T0) is None
    assert store.find(stranger, T0) is not None


@pytest.mark.parametrize("token", [None, "", "x" * 129, "not-a-real-token"])
def test_missing_oversized_or_unknown_tokens_find_nothing(db, token):
    assert SessionStore(db).find(token, T0) is None


@pytest.mark.parametrize(("env", "secure"), [
    (AppEnv.development, False),
    (AppEnv.test, False),
    (AppEnv.demo, True),
    (AppEnv.production, True),
])
def test_cookie_is_httponly_strict_and_secure_when_deployed(env, secure):
    attributes = cookie_attributes(Settings.model_construct(app_env=env))
    assert attributes == {"httponly": True, "samesite": "strict", "secure": secure,
                          "path": "/api"}
