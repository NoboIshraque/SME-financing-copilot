"""Canonical, salted commitments.

digest = SHA-256("hishab:v1:" + kind + ":" + salt + ":" + canonical JSON)

The salt (32 random bytes, kept off-chain with the record) stops anyone from guessing small
amounts from a public hash. Canonical JSON: sorted keys, no spaces, decimals as strings.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from pydantic import BaseModel

PREFIX = "hishab:v1"


def new_salt() -> str:
    return secrets.token_hex(32)


def canonical(value: BaseModel | dict[str, Any], *, exclude: set[str] | None = None) -> str:
    data = value.model_dump(mode="json", exclude=exclude) if isinstance(value, BaseModel) else {
        k: v for k, v in value.items() if not exclude or k not in exclude
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def commit(kind: str, salt: str, payload: str) -> str:
    if len(salt) != 64 or any(ch not in "0123456789abcdef" for ch in salt):
        raise ValueError("salt must be 32 bytes as lowercase hex")
    material = f"{PREFIX}:{kind}:{salt}:{payload}".encode()
    return hashlib.sha256(material).hexdigest()
