"""Ingest preview/commit (WP-02; FEATURES P4)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.contracts.common import Contract, DataMode, Probability
from app.contracts.ledger import Bill, Invoice, Transaction


class SourceFormat(StrEnum):
    bkash_statement = "bkash_statement"
    nagad_statement = "nagad_statement"
    bank_csv = "bank_csv"
    ledger_csv = "ledger_csv"
    ledger_xlsx = "ledger_xlsx"
    ledger_photo = "ledger_photo"
    unknown = "unknown"


class UnparsedRow(Contract):
    row_ref: str
    reason_key: str
    raw_excerpt: str = Field(max_length=200, description="Masked by WP-03 before storage")


class DraftRow(Contract):
    """An OCR'd or uncertain row the owner must confirm before it is committed."""

    row_ref: str
    confidence: Probability
    invoice: Invoice | None = None
    transaction: Transaction | None = None
    flagged: bool


class IngestPreview(Contract):
    preview_id: str
    tenant_id: str
    source_format: SourceFormat
    file_digest: str = Field(pattern=r"^[0-9a-f]{64}$", description="Keyed digest of the file")
    transactions: tuple[Transaction, ...] = ()
    invoices: tuple[Invoice, ...] = ()
    bills: tuple[Bill, ...] = ()
    drafts: tuple[DraftRow, ...] = ()
    unparsed: tuple[UnparsedRow, ...] = ()
    duplicates_skipped: int = Field(default=0, ge=0)
    data_mode: DataMode
