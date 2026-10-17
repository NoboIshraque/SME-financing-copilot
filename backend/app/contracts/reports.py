"""Lender report and Trust Passport (WP-13; FEATURES N4, Q4)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, DataMode, Period, Probability
from app.contracts.mesh import AnchorReceipt


class EvidenceKind(StrEnum):
    mobile_money_statement = "mobile_money_statement"
    bank_statement = "bank_statement"
    trade_licence = "trade_licence"
    etin = "etin"
    bin_vat = "bin_vat"
    utility_bill = "utility_bill"
    lender_report = "lender_report"


class EvidenceItem(Contract):
    kind: EvidenceKind
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    period: Period | None = None
    verified: bool = Field(description="True when checked against its source, not self-declared")


class PassportVersion(Contract):
    id: str
    tenant_id: str
    version: int = Field(ge=1)
    issued_at: datetime
    evidence: tuple[EvidenceItem, ...]
    attestations_confirmed: int = Field(ge=0)
    attestations_disputed: int = Field(ge=0)
    abstention_rate: Probability | None = None
    audit_drill_catch_rate: Probability | None = None
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchor: AnchorReceipt | None = None
    data_mode: DataMode


class ShareGrant(Contract):
    """Consented, scoped, expiring access for one lender."""

    id: str
    tenant_id: str
    passport_id: str
    lender_label: str
    scopes: tuple[str, ...] = Field(min_length=1)
    created_at: datetime
    expires_at: datetime
    revoked: bool = False

    @model_validator(mode="after")
    def _expiry(self) -> ShareGrant:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class VerifyResult(Contract):
    passport_id: str
    recomputed_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchored_digest: str | None = None
    valid: bool
    checked_on: date
