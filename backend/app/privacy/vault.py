"""Token vault (WP-03 milestone 2; FEATURES N18).

`PERSON_xxxxxxxxxx` = HMAC-SHA256(tenant | kind | normalised value), truncated: the same value
always gets the same token inside a tenant and different tokens across tenants. Originals are
kept encrypted with AES-256-GCM (random 96-bit nonce, tenant and token as associated data), so
a ciphertext copied to another tenant or token fails to decrypt. Restoring an original is a
privileged act: it needs an authoriser that approves the caller (WP-11 plugs in the role check;
the default refuses everyone). Two keys are derived from VAULT_KEY with HKDF, one for HMAC and
one for encryption. Nothing in this module logs values.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.privacy.detectors import Detection, Kind, detect, to_ascii_digits

TOKEN_LEN = 10
TOKEN_RE = re.compile(r"\b(PERSON|SHOP|PHONE|ACCOUNT|EMAIL|ADDRESS|ORG|PARTY)_[0-9a-z]{5,16}\b")
_PREFIX = {
    Kind.PERSON: "PERSON", Kind.SHOP: "SHOP", Kind.PHONE: "PHONE", Kind.NID: "ACCOUNT",
    Kind.CARD: "ACCOUNT", Kind.ACCOUNT: "ACCOUNT", Kind.EMAIL: "EMAIL", Kind.ADDRESS: "ADDRESS",
}


class VaultError(RuntimeError):
    """Decryption or authorisation failed. The vault fails closed: no partial answers."""


Authoriser = Callable[[object], bool]


def deny_all(_principal: object) -> bool:
    return False


def _derive(secret: bytes, label: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"hishab-vault-v1",
                info=label).derive(secret)


def normalise(kind: Kind, value: str) -> str:
    """Canonical form so '+880 1712-345678' and '01712345678' share a token."""
    text = unicodedata.normalize("NFC", to_ascii_digits(value)).strip()
    if kind in (Kind.PHONE, Kind.NID, Kind.CARD, Kind.ACCOUNT):
        digits = re.sub(r"\D", "", text)
        if kind is Kind.PHONE:
            digits = digits[-11:] if len(digits) >= 11 else digits
        return digits
    return re.sub(r"\s+", " ", text).casefold()


@dataclass
class TokenVault:
    secret: bytes
    authoriser: Authoriser = deny_all
    entries: MutableMapping[tuple[str, str], tuple[bytes, bytes]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise VaultError("vault key must be at least 32 bytes")
        self._mac_key = _derive(self.secret, b"token-hmac")
        self._aead = AESGCM(_derive(self.secret, b"original-aes-gcm"))

    @classmethod
    def from_setting(cls, vault_key: str, authoriser: Authoriser = deny_all) -> TokenVault:
        """VAULT_KEY as 64+ hex characters (`openssl rand -hex 32`) or a 32+ byte string."""
        is_hex = re.fullmatch(r"[0-9a-fA-F]{64,}", vault_key) is not None
        raw = bytes.fromhex(vault_key) if is_hex else vault_key.encode()
        return cls(raw, authoriser)

    def token_for(self, tenant: str, kind: Kind, value: str) -> str:
        material = f"{tenant}|{kind.value}|{normalise(kind, value)}".encode()
        mac = hmac.new(self._mac_key, material, hashlib.sha256).hexdigest()
        return f"{_PREFIX[kind]}_{mac[:TOKEN_LEN]}"

    def put(self, tenant: str, kind: Kind, value: str) -> str:
        token = self.token_for(tenant, kind, value)
        if (tenant, token) not in self.entries:
            nonce = os.urandom(12)
            cipher = self._aead.encrypt(nonce, value.encode(), f"{tenant}|{token}".encode())
            self.entries[(tenant, token)] = (nonce, cipher)
        return token

    def ciphertext(self, tenant: str, token: str) -> bytes:
        nonce, cipher = self.entries[(tenant, token)]
        return nonce + cipher

    def restore(self, tenant: str, token: str, principal: object) -> str:
        if not self.authoriser(principal):
            raise VaultError("not authorised to reveal originals")
        try:
            nonce, cipher = self.entries[(tenant, token)]
            return self._aead.decrypt(nonce, cipher, f"{tenant}|{token}".encode()).decode()
        except (KeyError, InvalidTag) as exc:
            raise VaultError("cannot restore this token") from exc

    def __repr__(self) -> str:  # never show keys or entries
        return f"TokenVault(entries={len(self.entries)})"


@dataclass(frozen=True)
class Tokenised:
    text: str
    tokens: tuple[str, ...]
    kinds: tuple[Kind, ...]


def tokenise(vault: TokenVault, tenant: str, text: str, *, party_names=(), shop_names=()
             ) -> Tokenised:
    """Replace every detection in `text` with its vault token (originals go into the vault)."""
    detections: list[Detection] = detect(text, party_names=party_names, shop_names=shop_names)
    out, last, tokens, kinds = [], 0, [], []
    for det in detections:
        token = vault.put(tenant, det.kind, det.value)
        out += [text[last:det.start], token]
        last = det.end
        tokens.append(token)
        kinds.append(det.kind)
    out.append(text[last:])
    return Tokenised("".join(out), tuple(tokens), tuple(kinds))
