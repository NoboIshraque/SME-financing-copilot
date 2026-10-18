"""Counterparty identifiers -> party tokens (WP-02; the token vault itself is WP-03).

Raw names and phone numbers never leave this module: a parser hands over what a row says about
its counterparty and gets back an opaque `PARTY_<10 hex>` token, a keyed HMAC of the tenant and
the normalised identifier. Without the key a token cannot be linked back to a person.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Sequence
from typing import Protocol

from app.ingest.normalise import ascii_digits, clean_text

_PHONE = re.compile(r"^(?:\+?880|0)?(1[3-9]\d{8})$")
_DIGIT_RUN = re.compile(r"\d[\d\s\-]{5,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def normalise_phone(text: str) -> str | None:
    """Bangladeshi mobile number in canonical form '+8801XXXXXXXXX', or None.

    Accepts 01XXXXXXXXX, 8801XXXXXXXXX, +880 1XXX-XXXXXX and Bangla digits.
    """
    digits = re.sub(r"[\s\-().]", "", ascii_digits(text))
    match = _PHONE.match(digits)
    return f"+880{match.group(1)}" if match else None


def normalise_name(text: str) -> str | None:
    name = clean_text(text).casefold()
    name = re.sub(r"[^\wঀ-৿ ]+", " ", name)
    name = " ".join(name.split())
    return name or None


def identifiers(name: str | None = None, phone: str | None = None) -> tuple[str, ...]:
    """Normalised identifiers for a counterparty, strongest first ('phone:...' then 'name:...').

    A 'name' that is really a phone number (bKash 'From/To' columns) counts as a phone.
    """
    found: list[str] = []
    for value in (phone, name):
        if value and (p := normalise_phone(value)) and f"phone:{p}" not in found:
            found.append(f"phone:{p}")
    if name and normalise_phone(name) is None and (n := normalise_name(name)):
        found.append(f"name:{n}")
    return tuple(found)


class PartyResolver(Protocol):
    def resolve(self, tenant_id: str, ids: Sequence[str]) -> str | None: ...


class HmacPartyResolver:
    """Token = keyed HMAC of the tenant and the strongest identifier."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 16:
            raise ValueError("party token key must be at least 16 bytes")
        self._key = key

    def token_for(self, tenant_id: str, identifier: str) -> str:
        digest = hmac.new(self._key, f"{tenant_id}|{identifier}".encode(), hashlib.sha256)
        return "PARTY_" + digest.hexdigest()[:10]

    def resolve(self, tenant_id: str, ids: Sequence[str]) -> str | None:
        return self.token_for(tenant_id, ids[0]) if ids else None


def mask_excerpt(text: str, limit: int = 200) -> str:
    """Stub of the WP-03 masker for unparsed-row excerpts: hides phone/account-like digit runs
    and e-mail addresses, then truncates."""
    masked = _EMAIL.sub("[email]", ascii_digits(text))
    masked = _DIGIT_RUN.sub(lambda m: "#" * len(m.group(0)), masked)
    return masked[:limit]
