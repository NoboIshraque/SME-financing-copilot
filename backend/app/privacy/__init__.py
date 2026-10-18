"""Privacy: detectors, token vault, anonymiser, fail-closed gate (WP-03).

    from app.privacy import TokenVault, anonymise, assert_safe
"""

from app.privacy.anonymiser import Anonymised, anonymise
from app.privacy.detectors import Detection, Kind, detect
from app.privacy.gate import PrivacyViolation, assert_safe, is_safe
from app.privacy.vault import TokenVault, VaultError, tokenise

__all__ = ["Anonymised", "Detection", "Kind", "PrivacyViolation", "TokenVault", "VaultError",
           "anonymise", "assert_safe", "detect", "is_safe", "tokenise"]
