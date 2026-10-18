import pytest

from app.privacy.detectors import Kind, detect, kinds_in

POSITIVES = [
    ("Call 01712345678 today", Kind.PHONE, "01712345678"),
    ("bKash 017-1234-5678", Kind.PHONE, "017-1234-5678"),
    ("+880 1712-345678", Kind.PHONE, "+880 1712-345678"),
    ("8801812345678", Kind.PHONE, "8801812345678"),
    ("+88 01912 345678", Kind.PHONE, "+88 01912 345678"),
    ("নগদ ০১৭১২৩৪৫৬৭৮", Kind.PHONE, "০১৭১২৩৪৫৬৭৮"),
    ("NID 1987654321", Kind.NID, "1987654321"),
    ("National ID: 1990123456789", Kind.NID, "1990123456789"),
    ("জাতীয় পরিচয় ১৯৯০১২৩৪৫৬৭৮৯০১২৩", Kind.NID, "১৯৯০১২৩৪৫৬৭৮৯০১২৩"),
    ("card 4111 1111 1111 1111", Kind.CARD, "4111 1111 1111 1111"),
    ("A/C 2050112345678901", Kind.ACCOUNT, "2050112345678901"),
    ("mail rahim.store@example.com", Kind.EMAIL, "rahim.store@example.com"),
    ("House 12, Road 5", Kind.ADDRESS, "House 12"),
    ("shop in Mirpur 10", Kind.ADDRESS, "Mirpur"),
    ("দোকান মিরপুর ১০", Kind.ADDRESS, "মিরপুর"),
    ("বাড়ি ১২ রোড ৫", Kind.ADDRESS, "বাড়ি ১২"),
    ("Karim paid", Kind.PERSON, "Karim"),
    ("রহিম টাকা দিয়েছে", Kind.PERSON, "রহিম"),
    ("Rahim Hossain owes", Kind.PERSON, "Rahim Hossain"),
    ("Bismillah Store ordered", Kind.SHOP, "Bismillah Store"),
    ("Islampur Fabric House", Kind.SHOP, "Islampur Fabric House"),
]


@pytest.mark.parametrize(("text", "kind", "value"), POSITIVES, ids=[p[0] for p in POSITIVES])
def test_detects_pii(text, kind, value):
    assert (kind, value) in {(d.kind, d.value) for d in detect(text)}


NEGATIVES = [
    "Tk 45,000 due",
    "৳১,২০,০০০ বাকি",
    "invoice INV-00042",
    "2026-09-14",
    "14/09/2026",
    "rice 50kg at 58",
    "PARTY_0123456789 owes",
    "SHOP_c3cc76a3b4 and PHONE_0123456789",
    "SALE-260914",
    "12.5% interest a year",
    "order 123456789",
    "balance 12345678901.50",
    "TrxID 8N7A6B5C4D",
    "Customer 3 is late",
    "page 2 of 10",
    "sales grew 40% in Eid week",
]


@pytest.mark.parametrize("text", NEGATIVES)
def test_look_alikes_are_not_flagged(text):
    assert detect(text) == []


def test_tenant_party_names_are_detected():
    assert kinds_in("Shafiqul Alam called", party_names=["Shafiqul Alam"]) == {Kind.PERSON}


def test_tenant_shop_names_are_detected():
    assert kinds_in("order from Ma Bhai Corp", shop_names=["Ma Bhai Corp"]) == {Kind.SHOP}


def test_longest_match_wins_over_its_parts():
    dets = detect("Rahim Traders paid")
    assert [(d.kind, d.value) for d in dets] == [(Kind.SHOP, "Rahim Traders")]


def test_offsets_point_at_the_original_text_even_with_bangla_digits():
    text = "ফোন ০১৭১২৩৪৫৬৭৮ ঠিক"
    det = detect(text)[0]
    assert text[det.start:det.end] == "০১৭১২৩৪৫৬৭৮"


def test_any_long_number_is_treated_as_sensitive():
    assert detect("ref 98765432109876")[0].kind in {Kind.ACCOUNT, Kind.NID, Kind.CARD}
