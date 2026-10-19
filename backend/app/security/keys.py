"""Key derivation and authenticated encryption for security data at rest.

Each purpose gets its own subkey, derived from `settings.secret_key` with HKDF-SHA256, so a
key leaked from one feature cannot decrypt or forge another. Secrets are sealed with
AES-256-GCM; the associated data binds a ciphertext to its owner (a TOTP secret copied to
another user's row does not decrypt).
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12


class SealError(ValueError):
    """A sealed value failed to open (wrong key, wrong owner, or tampered ciphertext)."""


def derive_key(secret: str, purpose: str, length: int = 32) -> bytes:
    if not secret:
        raise ValueError("secret_key is empty")
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=None,
                info=f"hishab:security:{purpose}:v1".encode())
    return hkdf.derive(secret.encode())


def keyed_digest(key: bytes, value: str) -> str:
    """HMAC-SHA256 hex digest: a lookup key that cannot be reversed by guessing values."""
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


class SecretBox:
    """AES-256-GCM with a fresh random nonce per seal."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("SecretBox needs a 32-byte key")
        self._aead = AESGCM(key)

    def seal(self, plaintext: str, owner: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(NONCE_BYTES)
        return nonce, self._aead.encrypt(nonce, plaintext.encode(), owner.encode())

    def open(self, nonce: bytes, ciphertext: bytes, owner: str) -> str:
        try:
            return self._aead.decrypt(nonce, ciphertext, owner.encode()).decode()
        except InvalidTag as exc:
            raise SealError("sealed value does not open with this key and owner") from exc
