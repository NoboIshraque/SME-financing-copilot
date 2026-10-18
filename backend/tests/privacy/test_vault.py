import logging

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.privacy.detectors import Kind
from app.privacy.vault import TokenVault, VaultError, normalise, tokenise

KEY = b"0123456789abcdef0123456789abcdef"
OWNER = object()


def vault(authorise=True, key=KEY):
    return TokenVault(key, authoriser=(lambda p: p is OWNER) if authorise else (lambda p: False))


def test_same_value_same_token_within_a_tenant_and_across_formats():
    v = vault()
    a = v.token_for("t1", Kind.PHONE, "+880 1712-345678")
    assert a == v.token_for("t1", Kind.PHONE, "01712345678")
    assert a == v.token_for("t1", Kind.PHONE, "০১৭১২৩৪৫৬৭৮")
    assert a.startswith("PHONE_") and len(a) == len("PHONE_") + 10


def test_tokens_differ_across_tenants_and_keys():
    assert vault().token_for("t1", Kind.PERSON, "Rahim") != vault().token_for(
        "t2", Kind.PERSON, "Rahim")
    other = vault(key=b"x" * 32)
    assert vault().token_for("t1", Kind.PERSON, "Rahim") != other.token_for(
        "t1", Kind.PERSON, "Rahim")


def test_names_normalise_case_and_spacing():
    assert normalise(Kind.PERSON, "  Rahim   HOSSAIN ") == normalise(Kind.PERSON, "rahim hossain")


def test_ciphertext_never_contains_the_plaintext():
    v = vault()
    token = v.put("t1", Kind.PERSON, "Rahim Hossain")
    blob = v.ciphertext("t1", token)
    assert b"Rahim" not in blob and b"Hossain" not in blob and len(blob) > 12 + 16


def test_authorised_restore_returns_the_original():
    v = vault()
    token = v.put("t1", Kind.EMAIL, "rahim@example.com")
    assert v.restore("t1", token, OWNER) == "rahim@example.com"


def test_restore_without_authorisation_fails_closed():
    v = vault(authorise=False)
    token = v.put("t1", Kind.PERSON, "Rahim")
    with pytest.raises(VaultError, match="not authorised"):
        v.restore("t1", token, OWNER)


def test_default_authoriser_refuses_everyone():
    v = TokenVault(KEY)
    token = v.put("t1", Kind.PERSON, "Rahim")
    with pytest.raises(VaultError):
        v.restore("t1", token, OWNER)


def test_a_ciphertext_moved_to_another_tenant_or_key_does_not_decrypt():
    v = vault()
    token = v.put("t1", Kind.PERSON, "Rahim")
    v.entries[("t2", token)] = v.entries[("t1", token)]  # copy across tenants
    with pytest.raises(VaultError):
        v.restore("t2", token, OWNER)
    stolen = vault(key=b"y" * 32)
    stolen.entries = dict(v.entries)
    with pytest.raises(VaultError):
        stolen.restore("t1", token, OWNER)


def test_short_keys_are_refused():
    with pytest.raises(VaultError):
        TokenVault(b"short")


def test_hex_vault_key_from_settings():
    v = TokenVault.from_setting("ab" * 32)
    assert v.secret == bytes.fromhex("ab" * 32)


def test_repr_hides_everything(caplog):
    v = vault()
    v.put("t1", Kind.PERSON, "Rahim Hossain")
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("x").info("vault %r", v)
    assert "Rahim" not in caplog.text and KEY.decode() not in repr(v)


def test_tokenise_replaces_every_detection():
    v = vault()
    out = tokenise(v, "t1", "Karim 01712345678 Mirpur")
    assert "Karim" not in out.text and "01712345678" not in out.text and "Mirpur" not in out.text
    assert out.kinds == (Kind.PERSON, Kind.PHONE, Kind.ADDRESS)


names = st.sampled_from(["Rahim", "Karim", "Salma", "Jamal", "Habib", "Kamal", "Farzana"])
phones = st.integers(10_000_000, 99_999_999).map(lambda n: f"0171{n}"[:11])


@pytest.mark.property
@given(names, phones)
def test_tokenise_then_restore_round_trips_every_value(name, phone):
    v = vault()
    out = tokenise(v, "t1", f"{name} paid via {phone}")
    restored = out.text
    for token in out.tokens:
        restored = restored.replace(token, v.restore("t1", token, OWNER))
    assert restored == f"{name} paid via {phone}"


def test_vault_entries_persist_in_the_database(settings):
    from app.db import init_db, make_engine, session_factory
    from app.privacy.models import VaultEntry
    from app.privacy.store import SqlVaultEntries

    engine = make_engine("sqlite://")
    init_db(engine)
    factory = session_factory(engine)
    with factory() as s:
        token = TokenVault(KEY, authoriser=lambda p: p is OWNER,
                           entries=SqlVaultEntries(s)).put("t1", Kind.PERSON, "Rahim")
        s.commit()
    with factory() as s:
        rows = s.query(VaultEntry).all()
        assert [(r.tenant_id, r.token) for r in rows] == [("t1", token)]
        assert b"Rahim" not in rows[0].ciphertext
        again = TokenVault(KEY, authoriser=lambda p: p is OWNER, entries=SqlVaultEntries(s))
        assert again.restore("t1", token, OWNER) == "Rahim"
