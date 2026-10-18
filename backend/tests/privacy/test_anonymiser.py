import re
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.privacy.anonymiser import anonymise, new_scale
from app.privacy.detectors import Kind
from app.privacy.gate import is_safe
from app.privacy.vault import TokenVault

V = TokenVault(b"0123456789abcdef0123456789abcdef")
ANCHOR = date(2026, 10, 1)
RAW = ("Rahim Hossain (01712-345678) of Rahim Traders, House 12 Road 5 Mirpur owes Tk 45,000 "
       "since 2026-09-14; last paid 14/06/2026; NID 1987654321; mail rahim@example.com")


def anon(text=RAW, **kw):
    return anonymise(text, vault=V, tenant="sme_grocery", anchor=ANCHOR, **kw)


def test_output_passes_the_privacy_gate():
    assert not is_safe(RAW)
    assert is_safe(anon().text)


def test_people_and_shops_become_neutral_labels_in_order():
    out = anon("Karim and Salma; Karim again; Bismillah Store")
    assert out.text == "Person 1 and Person 2; Person 1 again; Firm A"


def test_roles_pick_customer_or_supplier_labels():
    token = V.token_for("sme_grocery", Kind.PERSON, "Karim")
    out = anon("Karim is late", roles={token: "customer"})
    assert out.text == "Customer 1 is late"


def test_dates_become_relative_to_the_anchor():
    out = anon("due 2026-09-14, paid 14/06/2026, next 2026-10-03")
    assert out.text == "due day t-17, paid month t-4, next day t+2"


def test_impossible_dates_are_masked_not_guessed():
    assert anon("on 2026-02-30").text == "on [date]"


def test_rare_terms_and_places_are_masked():
    out = anon("Sold Kashmiri saffron gold in Gulshan", rare_terms=["Kashmiri saffron gold"])
    assert out.text == "Sold [item] in Address 1"  # the area is caught as an address first


def test_amount_scaling_is_off_by_default():
    assert "Tk 45000" not in anon("owes Tk 45,000").text
    assert anon("owes Tk 45,000").text == "owes Tk 45,000"


def test_amount_scaling_multiplies_by_the_secret_factor():
    out = anon("owes Tk 45,000 and paid ৳1,000", scale_amounts=True, scale=Decimal("1.37"))
    assert out.text == "owes Tk 61650 and paid ৳ 1370"
    assert out.scale == Decimal("1.37")


def test_new_scale_stays_in_range():
    for _ in range(200):
        s = new_scale()
        assert Decimal("0.50") <= s < Decimal("2.00")


@pytest.mark.property
@given(st.integers(1_000, 900_000), st.integers(1_000, 900_000),
       st.integers(50, 199).map(lambda n: Decimal(n) / 100))
def test_scaling_preserves_ratios(a, b, scale):
    out = anon(f"sales Tk {a} costs Tk {b}", scale_amounts=True, scale=scale).text
    sa, sb = (Decimal(x) for x in re.findall(r"Tk (\d+)", out))
    ratio = Decimal(a) / Decimal(b)
    # Only rounding to whole taka (at most half a taka on each side) can move the ratio.
    assert abs(sa / sb - ratio) <= ratio * (Decimal("0.5") / sa + Decimal("0.5") / sb) * Decimal(
        "1.01")


def test_restore_maps_labels_back_to_tokens():
    out = anon("Karim owes Bismillah Store")
    restored = out.restore("Remind Person 1 and thank Firm A; Person 9 is unknown")
    assert restored.startswith("Remind PERSON_") and "SHOP_" in restored
    assert restored.endswith("Person 9 is unknown")


@pytest.mark.property
@given(st.lists(st.sampled_from(["Rahim", "Karim", "Salma", "Jamal", "Habib"]), min_size=1,
                max_size=6))
def test_restore_of_the_anonymised_text_gives_the_tokenised_text(people):
    from app.privacy.vault import tokenise

    text = " and ".join(people) + " paid"
    out = anon(text)
    assert out.restore(out.text) == tokenise(V, "sme_grocery", text).text
