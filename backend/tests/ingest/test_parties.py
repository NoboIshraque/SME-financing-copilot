import pytest

from app.ingest.parties import (
    ClusteringPartyResolver,
    HmacPartyResolver,
    identifiers,
    mask_excerpt,
    normalise_name,
    normalise_phone,
)
from tests.ingest.helpers import KEY


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("01711000001", "+8801711000001"),
        ("8801711000001", "+8801711000001"),
        ("+880 1711-000001", "+8801711000001"),
        ("০১৭১১০০০০০১", "+8801711000001"),
        ("(+880) 1711 000 001", "+8801711000001"),
        ("0171100000", None),
        ("01211000001", None),
        ("02-9123456", None),
        ("Rahim", None),
    ],
    ids=["local", "country-code", "plus-and-dashes", "bangla-digits", "brackets", "too-short",
         "not-a-mobile-prefix", "landline", "name"],
)
def test_bangladeshi_mobile_numbers_normalise(text, expected):
    assert normalise_phone(text) == expected


def test_names_normalise_case_punctuation_and_spacing():
    assert normalise_name("  Bhai-Bhai   Corporation. ") == "bhai bhai corporation"
    assert normalise_name("মায়ের দোয়া এন্টারপ্রাইজ") == "মায়ের দোয়া এন্টারপ্রাইজ"


def test_identifiers_put_the_phone_first_and_spot_phones_in_name_columns():
    assert identifiers("Green Traders", "01830296422") == (
        "phone:+8801830296422", "name:green traders")
    assert identifiers("01830296422") == ("phone:+8801830296422",)
    assert identifiers("", None) == ()


def test_tokens_are_keyed_tenant_scoped_and_stable():
    resolver = HmacPartyResolver(KEY)
    ids = identifiers("Green Traders", "01830296422")
    token = resolver.resolve("tenant_a", ids)
    assert token == resolver.resolve("tenant_a", ids)
    assert token.startswith("PARTY_") and len(token) == 16
    assert token != resolver.resolve("tenant_b", ids)
    assert token != HmacPartyResolver(b"another-key-0123456789").resolve("tenant_a", ids)
    assert resolver.resolve("tenant_a", ()) is None


def test_short_keys_are_refused():
    with pytest.raises(ValueError, match="16 bytes"):
        HmacPartyResolver(b"short")


def test_excerpt_masking_hides_phones_and_emails_but_keeps_amounts():
    masked = mask_excerpt("A1,01711000001,rahim@example.com,2479.00,01/04/2025")
    assert "01711000001" not in masked and "rahim@example.com" not in masked
    assert "2479.00" in masked and "01/04/2025" in masked
    assert len(mask_excerpt("x" * 500)) == 200


# ---------------------------------------------------------------- clustering (WP-03 hook)

REGISTER_ROW = identifiers("Green Traders", "01830296422")
WALLET_ROW = identifiers("01830296422")
BANK_ROW = identifiers("GREEN TRADERS")


def test_identifiers_seen_together_become_one_counterparty():
    resolver = ClusteringPartyResolver(KEY)
    tokens = resolver.resolve_many("tenant_a", [WALLET_ROW, BANK_ROW, REGISTER_ROW])
    assert len(set(tokens)) == 1
    assert tokens[0] == HmacPartyResolver(KEY).resolve("tenant_a", WALLET_ROW)


def test_without_a_linking_row_name_and_phone_stay_apart():
    tokens = ClusteringPartyResolver(KEY).resolve_many("tenant_a", [WALLET_ROW, BANK_ROW])
    assert tokens[0] != tokens[1]


def test_links_from_an_earlier_upload_carry_over():
    first = ClusteringPartyResolver(KEY)
    (linked,) = first.resolve_many("tenant_a", [REGISTER_ROW])
    later = ClusteringPartyResolver(KEY, known=first.new_aliases)
    assert later.resolve_many("tenant_a", [BANK_ROW]) == [linked]
    assert later.new_aliases == {}


def test_merging_two_known_counterparties_keeps_one_token_deterministically():
    by_phone = ClusteringPartyResolver(KEY)
    by_phone.resolve_many("tenant_a", [WALLET_ROW])
    by_name = ClusteringPartyResolver(KEY)
    by_name.resolve_many("tenant_a", [BANK_ROW])
    known = {**by_phone.new_aliases, **by_name.new_aliases}
    resolver = ClusteringPartyResolver(KEY, known=known)
    (merged,) = resolver.resolve_many("tenant_a", [REGISTER_ROW])
    assert merged == min(set(known.values()))
    assert set(resolver.new_aliases.values()) == {merged}


def test_alias_table_stores_only_keyed_digests():
    resolver = ClusteringPartyResolver(KEY)
    resolver.resolve_many("tenant_a", [REGISTER_ROW])
    stored = " ".join([*resolver.new_aliases, *resolver.new_aliases.values()])
    assert "1830296422" not in stored and "green" not in stored.lower()
    assert all(len(k) == 32 and int(k, 16) >= 0 for k in resolver.new_aliases)


def test_plain_resolver_resolves_each_group_on_its_own():
    resolver = HmacPartyResolver(KEY)
    assert resolver.resolve_many("tenant_a", [WALLET_ROW, BANK_ROW, ()]) == [
        resolver.resolve("tenant_a", WALLET_ROW), resolver.resolve("tenant_a", BANK_ROW), None]
