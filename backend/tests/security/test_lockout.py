import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.security.lockout import LOCK_FOR, MAX_FAILURES, WINDOW, Lockout, minutes_left
from app.security.models import LoginFailureRow

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
KEY = b"k" * 32


def fail(lockout, times, start=T0, every=timedelta(seconds=10)):
    results = []
    for i in range(times):
        results.append(lockout.record_failure("owner@shop.test", start + every * i))
    return results


def test_the_fifth_failure_locks_for_fifteen_minutes(db):
    lockout = Lockout(db, KEY)
    results = fail(lockout, MAX_FAILURES)
    assert results[:-1] == [None] * (MAX_FAILURES - 1)
    assert results[-1] == LOCK_FOR
    locked_at = T0 + timedelta(seconds=10) * (MAX_FAILURES - 1)
    assert lockout.locked_for("owner@shop.test", locked_at) == LOCK_FOR
    assert lockout.locked_for("owner@shop.test", locked_at + LOCK_FOR) is None


def test_failures_spread_wider_than_the_window_never_lock(db):
    lockout = Lockout(db, KEY)
    results = fail(lockout, 3 * MAX_FAILURES, every=WINDOW / (MAX_FAILURES - 1))
    assert results == [None] * (3 * MAX_FAILURES)


def test_a_successful_sign_in_clears_the_counter(db):
    lockout = Lockout(db, KEY)
    fail(lockout, MAX_FAILURES - 1)
    lockout.clear("owner@shop.test")
    assert fail(lockout, MAX_FAILURES - 1, start=T0 + timedelta(minutes=1)) == [None] * 4


def test_emails_are_stored_only_as_keyed_digests(db):
    lockout = Lockout(db, KEY)
    lockout.record_failure("owner@shop.test", T0)
    row = db.scalars(select(LoginFailureRow)).one()
    assert "owner" not in row.email_key
    assert row.email_key != hashlib.sha256(b"owner@shop.test").hexdigest()
    assert row.email_key != Lockout(db, b"j" * 32).email_key("owner@shop.test")


def test_retry_after_is_rounded_up_to_whole_minutes():
    assert minutes_left(timedelta(minutes=14, seconds=1)) == 15
    assert minutes_left(timedelta(seconds=5)) == 1
    assert minutes_left(timedelta(minutes=15)) == 15
