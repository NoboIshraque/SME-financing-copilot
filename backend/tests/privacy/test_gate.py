import logging

import pytest

from app.privacy.detectors import Kind
from app.privacy.gate import PrivacyViolation, assert_safe, is_safe

EVERY_CLASS = {
    Kind.PHONE: "call 01712345678",
    Kind.NID: "NID 1987654321",
    Kind.CARD: "card 4111111111111111",
    Kind.ACCOUNT: "A/C 2050112345678901",
    Kind.EMAIL: "x@example.com",
    Kind.ADDRESS: "House 12",
    Kind.PERSON: "Karim",
    Kind.SHOP: "Bismillah Store",
}


@pytest.mark.parametrize("kind", list(EVERY_CLASS), ids=lambda k: k.value)
def test_gate_blocks_every_detector_class(kind):
    with pytest.raises(PrivacyViolation) as info:
        assert_safe({"messages": [{"role": "user", "content": EVERY_CLASS[kind]}]})
    assert kind in info.value.kinds


def test_gate_passes_clean_anonymised_payloads():
    content = "Customer 1 owes Tk 61650 since day t-17"
    assert_safe({"messages": [{"role": "user", "content": content}]})


def test_violation_message_names_kinds_never_values(caplog):
    with caplog.at_level(logging.WARNING):
        try:
            assert_safe("Karim 01712345678")
        except PrivacyViolation as exc:
            logging.getLogger("hishab.llm").warning("blocked: %s", exc)
    assert "Karim" not in caplog.text and "01712345678" not in caplog.text
    assert "PERSON x1" in caplog.text and "PHONE x1" in caplog.text


def test_nested_structures_and_non_strings_are_scanned():
    assert not is_safe({"a": [{"b": ("tuple", "01712345678")}], "n": 5})


def test_tenant_names_extend_the_gate():
    assert is_safe("Shafiqul called")
    assert not is_safe("Shafiqul called", party_names=["Shafiqul"])
