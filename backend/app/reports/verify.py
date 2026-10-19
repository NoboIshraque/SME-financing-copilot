"""Public verification of a Trust Passport (WP-13 milestone 4).

Anyone holding the passport document and its salt recomputes the digest and compares it with
the anchored one. No login, no trust in DecisionGuard or the SME.
"""

from __future__ import annotations

from datetime import date

from app.chain.anchor import Anchorer
from app.contracts import PassportVersion, VerifyResult
from app.reports.passport import passport_digest


def verify_passport(passport: PassportVersion, salt: str, anchorer: Anchorer, *,
                    today: date) -> VerifyResult:
    recomputed = passport_digest(passport, salt)
    anchored = anchorer.onchain_digest(passport.anchor) if passport.anchor else None
    valid = (anchored is not None and recomputed == anchored == passport.digest
             and passport.anchor.digest == anchored)
    return VerifyResult(passport_id=passport.id, recomputed_digest=recomputed,
                        anchored_digest=anchored, valid=valid, checked_on=today)
