"""Liquidity mesh (WP-08; FEATURES N14, Q4): obligations, netting, attestations, anchors."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, DataMode, Money


class ObligationStatus(StrEnum):
    open = "open"
    in_round = "in_round"
    settled = "settled"
    disputed = "disputed"


class MeshObligation(Contract):
    """`debtor_tenant` owes `creditor_tenant`. Both are DecisionGuard tenants that opted in."""

    id: str
    debtor_tenant: str
    creditor_tenant: str
    amount: Money
    due_date: date_type
    status: ObligationStatus = ObligationStatus.open
    invoice_ref: str | None = None
    attested: bool = False
    data_mode: DataMode

    @model_validator(mode="after")
    def _valid(self) -> MeshObligation:
        if self.debtor_tenant == self.creditor_tenant:
            raise ValueError("a tenant cannot owe itself")
        if self.amount.amount <= 0:
            raise ValueError("obligation amount must be positive")
        return self


class Settlement(Contract):
    payer_tenant: str
    payee_tenant: str
    amount: Money

    @model_validator(mode="after")
    def _valid(self) -> Settlement:
        if self.payer_tenant == self.payee_tenant:
            raise ValueError("payer and payee must differ")
        if self.amount.amount <= 0:
            raise ValueError("settlement amount must be positive")
        return self


class RoundStatus(StrEnum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    settled = "settled"


class AnchorChain(StrEnum):
    offline = "offline"
    sepolia = "sepolia"


class AnchorReceipt(Contract):
    """Proof that a digest was anchored. Only a SHA-256 hex digest ever goes on chain."""

    chain: AnchorChain
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tx_hash: str | None = Field(default=None, pattern=r"^0x[0-9a-f]{64}$")
    block_number: int | None = Field(default=None, ge=0)
    anchored_at: datetime
    explorer_url: str | None = None

    @model_validator(mode="after")
    def _chain_fields(self) -> AnchorReceipt:
        if self.chain is AnchorChain.sepolia and self.tx_hash is None:
            raise ValueError("a sepolia anchor needs a tx_hash")
        return self


class NettingRound(Contract):
    id: str
    obligation_ids: tuple[str, ...] = Field(min_length=2)
    participants: tuple[str, ...] = Field(min_length=2)
    settlements: tuple[Settlement, ...]
    gross_total: Money
    net_total: Money
    status: RoundStatus
    approvals: dict[str, bool] = Field(
        default_factory=dict, description="tenant -> approved?; missing = not answered yet"
    )
    created_at: datetime
    expires_at: datetime
    anchor: AnchorReceipt | None = None
    data_mode: DataMode

    @model_validator(mode="after")
    def _valid(self) -> NettingRound:
        if self.net_total > self.gross_total:
            raise ValueError("net total cannot exceed gross total")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        unknown = set(self.approvals) - set(self.participants)
        if unknown:
            raise ValueError(f"approvals from non-participants: {sorted(unknown)}")
        if self.status is RoundStatus.approved and not (
            set(self.approvals) == set(self.participants) and all(self.approvals.values())
        ):
            raise ValueError("an approved round needs every participant's approval")
        return self

    @property
    def cash_saved(self) -> Money:
        return self.gross_total - self.net_total


class AttestationKind(StrEnum):
    confirm = "confirm"
    dispute = "dispute"


class Attestation(Contract):
    id: str
    obligation_id: str
    attester_tenant: str
    kind: AttestationKind
    digest: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the attested record")
    created_at: datetime
