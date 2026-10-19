"""TOTP (RFC 6238) for sign-in and step-up, with replay protection (WP-11 milestone 1).

Six digits, 30-second steps, one step of clock drift either way. A verified code returns its
time step; the caller stores it, and any code at or below the stored step is refused (RFC 6238
§5.2: a code is accepted once). Codes typed with Bangla digits are accepted.
"""

from __future__ import annotations

import hmac
from datetime import datetime

import pyotp

DIGITS = 6
STEP_SECONDS = 30
DRIFT_STEPS = 1
ISSUER = "Hishab"

_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_SEPARATORS = str.maketrans("", "", " - ")


def new_secret() -> str:
    """160-bit random secret, base32 (what authenticator apps expect)."""
    return pyotp.random_base32(length=32)


def normalise_code(raw: str) -> str | None:
    code = raw.translate(_BANGLA_DIGITS).translate(_SEPARATORS)
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    return code


def step_at(when: datetime) -> int:
    return int(when.timestamp()) // STEP_SECONDS


def _totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)


def code_at(secret: str, when: datetime) -> str:
    return _totp(secret).generate_otp(step_at(when))


def verify(secret: str, raw_code: str, when: datetime, last_step: int | None) -> int | None:
    """The matched time step, or None if the code is wrong, outside the window, or a replay."""
    code = normalise_code(raw_code)
    if code is None:
        return None
    totp = _totp(secret)
    now_step = step_at(when)
    matched: int | None = None
    for step in range(now_step - DRIFT_STEPS, now_step + DRIFT_STEPS + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret: str, email: str) -> str:
    """otpauth:// URI for the enrolment QR code."""
    return _totp(secret).provisioning_uri(name=email, issuer_name=ISSUER)
