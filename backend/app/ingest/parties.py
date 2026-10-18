"""Counterparty identifiers -> party tokens (WP-02; the token vault itself is WP-03).

Raw names and phone numbers never leave this module: a parser hands over what a row says about
its counterparty and gets back an opaque `PARTY_<10 hex>` token, a keyed HMAC of the tenant and
the normalised identifier. Without the key a token cannot be linked back to a person.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping, Sequence
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
    """The privacy hook WP-03's token vault implements: identifiers in, opaque tokens out."""

    def resolve_many(self, tenant_id: str, groups: Sequence[Sequence[str]]) -> list[str | None]:
        """One token per group of identifiers that describe the same counterparty."""
        ...


class HmacPartyResolver:
    """Token = keyed HMAC of the tenant and the strongest identifier (no clustering)."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 16:
            raise ValueError("party token key must be at least 16 bytes")
        self._key = key

    def token_for(self, tenant_id: str, identifier: str) -> str:
        digest = hmac.new(self._key, f"{tenant_id}|{identifier}".encode(), hashlib.sha256)
        return "PARTY_" + digest.hexdigest()[:10]

    def alias_digest(self, tenant_id: str, identifier: str) -> str:
        """What the alias table stores instead of the identifier itself."""
        message = f"alias|{tenant_id}|{identifier}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()[:32]

    def resolve(self, tenant_id: str, ids: Sequence[str]) -> str | None:
        return self.token_for(tenant_id, ids[0]) if ids else None

    def resolve_many(self, tenant_id: str, groups: Sequence[Sequence[str]]) -> list[str | None]:
        return [self.resolve(tenant_id, group) for group in groups]


def _canonical(members: Iterable[str]) -> str:
    """Strongest identifier of a cluster: the smallest phone, else the smallest name."""
    ordered = sorted(members, key=lambda m: (not m.startswith("phone:"), m))
    return ordered[0]


class ClusteringPartyResolver(HmacPartyResolver):
    """Identifiers seen together (a register row's name and phone) form one counterparty.

    Clusters are built with union-find over every group in an upload, then merged with what
    earlier uploads already linked (`known`: alias digest -> token), so a customer known by
    phone in the bKash statement and by name in the bank statement gets one token once a
    register row has tied the two. Matching is exact on normalised identifiers; nothing fuzzy.
    New links are collected in `new_aliases` for the caller to persist; only keyed digests are
    ever stored, never the names or numbers themselves.
    """

    def __init__(self, key: bytes, known: Mapping[str, str] | None = None) -> None:
        super().__init__(key)
        self._known: dict[str, str] = dict(known or {})
        self.new_aliases: dict[str, str] = {}

    def resolve_many(self, tenant_id: str, groups: Sequence[Sequence[str]]) -> list[str | None]:
        parent: dict[str, str] = {}

        def find(item: str) -> str:
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        for group in groups:
            for item in group:
                parent.setdefault(item, item)
            for item in group[1:]:
                parent[find(item)] = find(group[0])
        clusters: dict[str, list[str]] = {}
        for item in parent:
            clusters.setdefault(find(item), []).append(item)
        token_of: dict[str, str] = {}
        for root, members in clusters.items():
            digests = {m: self.alias_digest(tenant_id, m) for m in members}
            known = sorted({self._known[d] for d in digests.values() if d in self._known})
            token = known[0] if known else self.token_for(tenant_id, _canonical(members))
            token_of[root] = token
            for digest in digests.values():
                if self._known.get(digest) != token:
                    self._known[digest] = token
                    self.new_aliases[digest] = token
        return [token_of[find(group[0])] if group else None for group in groups]


def mask_excerpt(text: str, limit: int = 200) -> str:
    """Stub of the WP-03 masker for unparsed-row excerpts: hides phone/account-like digit runs
    and e-mail addresses, then truncates."""
    masked = _EMAIL.sub("[email]", ascii_digits(text))
    masked = _DIGIT_RUN.sub(lambda m: "#" * len(m.group(0)), masked)
    return masked[:limit]
