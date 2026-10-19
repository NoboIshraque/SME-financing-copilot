"""Password hashing (argon2id) and password policy (WP-11 milestone 1).

Production uses argon2-cffi's RFC 9106 low-memory profile (argon2id, t=3, m=64 MiB, p=4),
above the OWASP minimum (m=19 MiB, t=2). Parameters live in each stored hash, so a hash made
with older parameters still verifies and is upgraded on the next sign-in (`needs_rehash`).

Policy follows NIST SP 800-63B: a length floor, a length ceiling (argon2 cost is per call, but
megabyte inputs are still refused), no composition rules, and a deny list of common passwords.
"""

from __future__ import annotations

from argon2 import Parameters, PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

MIN_LENGTH = 12
MAX_LENGTH = 128
PRODUCTION_PARAMETERS = RFC_9106_LOW_MEMORY

# The most common passwords of 12+ characters in public breach lists, plus local favourites.
COMMON_PASSWORDS = frozenset({
    "123456789012", "1234567890123", "12345678901234", "123456123456", "111111111111",
    "000000000000", "password1234", "password12345", "password123!", "passwordpassword",
    "qwertyuiop12", "qwertyuiopasdf", "1q2w3e4r5t6y", "iloveyou1234", "administrator",
    "letmein12345", "welcome12345", "changeme1234", "bangladesh123", "bangladesh1234",
    "dhaka1234567", "hishab123456",
})

_parameters = PRODUCTION_PARAMETERS
_hasher = PasswordHasher.from_parameters(_parameters)
_dummy_hash: str | None = None


def use_parameters(parameters: Parameters) -> Parameters:
    """Swap the hashing parameters (tests use argon2's CHEAPEST profile). Returns the old ones."""
    global _parameters, _hasher, _dummy_hash
    previous, _parameters = _parameters, parameters
    _hasher = PasswordHasher.from_parameters(parameters)
    _dummy_hash = None
    return previous


def parameters_in_use() -> Parameters:
    return _parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def burn_verify(password: str) -> None:
    """Spend the cost of one verification for an unknown email, so response time does not
    reveal whether an account exists."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("hishab-timing-equaliser")
    verify_password(_dummy_hash, password)


def policy_problems(password: str, *, email: str = "") -> list[str]:
    """i18n keys of every rule the password breaks (empty list = acceptable)."""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append("password.too_short")
    if len(password) > MAX_LENGTH:
        problems.append("password.too_long")
    lowered = password.casefold()
    if lowered in COMMON_PASSWORDS or len(set(lowered)) <= 2:
        problems.append("password.too_common")
    if email and lowered in {email.casefold(), email.casefold().split("@", 1)[0]}:
        problems.append("password.matches_email")
    return problems
