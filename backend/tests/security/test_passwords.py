import pytest
from argon2 import Type
from argon2.profiles import CHEAPEST, RFC_9106_LOW_MEMORY

from app.security import passwords


def test_hash_is_argon2id_salted_and_verifies_only_the_right_password():
    first = passwords.hash_password("correct horse battery staple")
    second = passwords.hash_password("correct horse battery staple")
    assert first.startswith("$argon2id$")
    assert first != second  # random salt per hash
    assert passwords.verify_password(first, "correct horse battery staple")
    assert not passwords.verify_password(first, "correct horse battery stapl")
    assert not passwords.verify_password(first, "Correct horse battery staple")


def test_production_parameters_are_argon2id_above_the_owasp_minimum():
    params = passwords.PRODUCTION_PARAMETERS
    assert params.type is Type.ID
    assert params.memory_cost >= 19 * 1024 and params.time_cost >= 2  # OWASP: m=19 MiB, t=2
    assert params == RFC_9106_LOW_MEMORY


def test_a_hash_made_with_old_parameters_still_verifies_and_is_flagged_for_rehash():
    old = passwords.hash_password("correct horse battery staple")  # CHEAPEST (conftest)
    passwords.use_parameters(RFC_9106_LOW_MEMORY)
    try:
        assert passwords.verify_password(old, "correct horse battery staple")
        assert passwords.needs_rehash(old)
        assert not passwords.needs_rehash(passwords.hash_password("x" * 12))
    finally:
        passwords.use_parameters(CHEAPEST)


@pytest.mark.parametrize("stored", [
    "",
    "not-a-hash",
    "$2b$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW",  # bcrypt, not argon2
    "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$AAAAAA",  # well-formed but wrong digest
])
def test_corrupt_or_foreign_hashes_never_verify(stored):
    assert passwords.verify_password(stored, "anything at all") is False


@pytest.mark.parametrize(("password", "email", "problems"), [
    ("short-pass1", "", ["password.too_short"]),
    ("Ab1-" * 33, "", ["password.too_long"]),
    ("Password1234", "", ["password.too_common"]),
    ("abababababababab", "", ["password.too_common"]),
    ("owner@shop.test", "owner@shop.test", ["password.matches_email"]),
    ("rahim.traders", "rahim.traders@shop.test", ["password.matches_email"]),
    ("correct horse battery staple", "owner@shop.test", []),
    ("কাঁচাবাজার-হিসাব-২০২৬", "", []),
])
def test_password_policy(password, email, problems):
    assert passwords.policy_problems(password, email=email) == problems


def test_unknown_emails_spend_one_verification(monkeypatch):
    calls = []
    real = passwords.verify_password
    monkeypatch.setattr(passwords, "verify_password",
                        lambda stored, pw: calls.append(pw) or real(stored, pw))
    passwords.burn_verify("guess")
    assert calls == ["guess"]
