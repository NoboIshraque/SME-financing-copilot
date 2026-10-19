from datetime import UTC, datetime, timedelta

import pytest

from app.security import totp
from app.security.keys import SealError, SecretBox, derive_key

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
NOW = datetime(2026, 10, 1, 9, 0, 7, tzinfo=UTC)


def code(offset_steps: int) -> str:
    return totp.code_at(SECRET, NOW + timedelta(seconds=30 * offset_steps))


@pytest.mark.parametrize(("offset", "accepted"), [
    (-2, False), (-1, True), (0, True), (1, True), (2, False),
])
def test_codes_are_accepted_within_one_step_of_drift(offset, accepted):
    step = totp.verify(SECRET, code(offset), NOW, last_step=None)
    assert (step == totp.step_at(NOW) + offset) if accepted else step is None


def test_a_code_is_accepted_once():
    step = totp.verify(SECRET, code(0), NOW, last_step=None)
    assert step is not None
    assert totp.verify(SECRET, code(0), NOW, last_step=step) is None


def test_an_older_code_is_refused_after_a_newer_one_was_used():
    newer = totp.verify(SECRET, code(1), NOW, last_step=None)
    assert totp.verify(SECRET, code(-1), NOW, last_step=newer) is None
    assert totp.verify(SECRET, code(0), NOW, last_step=newer) is None


def test_bangla_digits_spaces_and_hyphens_are_accepted():
    plain = code(0)
    bangla = plain.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
    assert totp.verify(SECRET, f"{bangla[:3]} {bangla[3:]}", NOW, None) is not None
    assert totp.normalise_code(f"{plain[:3]}-{plain[3:]}") == plain


@pytest.mark.parametrize("raw", ["12345", "1234567", "12a456", "", "١٢٣٤٥٦", "12 34 5"])
def test_malformed_codes_are_refused_before_any_comparison(raw):
    assert totp.normalise_code(raw) is None
    assert totp.verify(SECRET, raw, NOW, None) is None


def test_a_code_for_another_secret_is_refused():
    other = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.verify(other, code(0), NOW, None) is None


def test_new_secrets_are_160_bit_base32_and_unique():
    secrets = {totp.new_secret() for _ in range(50)}
    assert len(secrets) == 50
    assert all(len(s) == 32 and set(s) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for s in secrets)


def test_provisioning_uri_names_the_issuer_and_the_account():
    uri = totp.provisioning_uri(SECRET, "owner@shop.test")
    assert uri.startswith("otpauth://totp/DecisionGuard:owner%40shop.test?")
    assert f"secret={SECRET}" in uri and "issuer=DecisionGuard" in uri


def test_sealed_secret_opens_only_for_its_owner_and_key():
    box = SecretBox(derive_key("k" * 32, "totp"))
    nonce, sealed = box.seal(SECRET, owner="u-1")
    assert SECRET.encode() not in sealed
    assert box.open(nonce, sealed, owner="u-1") == SECRET
    with pytest.raises(SealError):
        box.open(nonce, sealed, owner="u-2")  # copied to another user's row
    with pytest.raises(SealError):
        SecretBox(derive_key("other" * 8, "totp")).open(nonce, sealed, owner="u-1")
    with pytest.raises(SealError):
        box.open(nonce, sealed[:-1] + bytes([sealed[-1] ^ 1]), owner="u-1")


def test_each_purpose_gets_its_own_key():
    assert derive_key("k" * 32, "totp") != derive_key("k" * 32, "lockout")
    assert len(derive_key("k" * 32, "totp")) == 32
