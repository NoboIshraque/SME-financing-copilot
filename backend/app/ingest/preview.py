"""Preview -> commit (WP-02 milestone 4).

    service = IngestService(session, secret=settings.secret_key.get_secret_value())
    preview = service.preview(data, IngestOptions(tenant_id=..., filename=...), reference=today)
    ... the owner reviews it, confirming drafts row by row ...
    service.commit(tenant_id, preview.preview_id, preview.file_digest, confirm=[...])

The preview is stored server side with a keyed digest of the uploaded bytes (HMAC-SHA256 with
a key derived from the server secret, bound to the tenant). The commit must name the same
digest, so what is committed is exactly what was previewed; a mismatch is refused. Drafts (OCR
lines, rows whose dates stayed ambiguous) are committed only when the owner confirms them by
`row_ref`; nothing is committed on its own. Duplicates are checked against the ledger at
preview time and again at commit time, in case another upload landed in between. A preview
keeps the ids its source pinned (`strong_ids`); once committed, those mark which ledger rows
match by id only, and every other ledger row may also match an upload on the weak key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Bill, DataMode, DraftRow, IngestPreview, Invoice, Money, Transaction
from app.facts import FactStore
from app.ingest.dedupe import dedupe
from app.ingest.models import IngestPreviewRow, PartyAliasRow
from app.ingest.normalise import NormaliseError, parse_amount
from app.ingest.ocr import OcrEngine, drafts_from_photo
from app.ingest.parsers import IngestOptions, parse_file
from app.ingest.parties import ClusteringPartyResolver

PREVIEW_TTL = timedelta(hours=24)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")


class IngestError(ValueError):
    """A refused ingest step; `code` is the API error code, `status` its HTTP status."""

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class CommitResult:
    preview_id: str
    transactions: int
    invoices: int
    bills: int
    drafts_confirmed: int
    duplicates_skipped: int
    committed_at: datetime


@dataclass(frozen=True)
class HistoryEntry:
    preview_id: str
    filename: str
    source_format: str
    file_digest: str
    data_mode: DataMode
    committed_at: datetime
    transactions: int
    invoices: int
    bills: int
    drafts_confirmed: int
    duplicates_skipped: int
    unparsed: int


def derive_key(secret: str, label: str) -> bytes:
    return hmac.new(secret.encode(), label.encode(), hashlib.sha256).digest()


def keyed_digest(key: bytes, tenant_id: str, data: bytes) -> str:
    """HMAC-SHA256 of the file bytes, bound to the tenant. Without the server key nobody can
    compute it, so a matching digest at commit means 'the file this server previewed'."""
    return hmac.new(key, tenant_id.encode() + b"\x00" + data, hashlib.sha256).hexdigest()


def is_image(data: bytes) -> bool:
    return data.startswith(_IMAGE_MAGIC) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class IngestService:
    def __init__(self, session: Session, secret: str,
                 now: Callable[[], datetime] | None = None) -> None:
        self.session = session
        self.store = FactStore(session)
        self._digest_key = derive_key(secret, "hishab/ingest/digest/v1")
        self._party_key = derive_key(secret, "hishab/ingest/party/v1")
        self._now = now or (lambda: datetime.now(UTC))

    # ----------------------------------------------------------------- preview

    def _resolver(self, tenant_id: str) -> ClusteringPartyResolver:
        query = select(PartyAliasRow).where(PartyAliasRow.tenant_id == tenant_id)
        known = {r.alias: r.token for r in self.session.scalars(query)}
        return ClusteringPartyResolver(self._party_key, known)

    def _ledger(self, tenant_id: str) -> tuple[list[Transaction], set[str]]:
        """The tenant's transactions, and those without a strong identity of their own: every
        one no committed upload pinned by its source id or running balance (seeded rows, rows
        typed in, rows from a source without ids). See `app/ingest/dedupe.py`."""
        ledger = self.store.transactions(tenant_id)
        pinned: set[str] = set()
        query = select(IngestPreviewRow.strong_ids).where(
            IngestPreviewRow.tenant_id == tenant_id, IngestPreviewRow.status == "committed")
        for ids in self.session.scalars(query):
            pinned.update(json.loads(ids))
        return ledger, {t.id for t in ledger if t.id not in pinned}

    def _new_documents(self, tenant_id: str, invoices: Collection[Invoice],
                       bills: Collection[Bill]) -> tuple[list[Invoice], list[Bill], int]:
        known_invoices = {i.id for i in self.store.invoices(tenant_id)}
        known_bills = {b.id for b in self.store.bills(tenant_id)}
        new_invoices = [i for i in invoices if i.id not in known_invoices]
        new_bills = [b for b in bills if b.id not in known_bills]
        return (new_invoices, new_bills,
                len(invoices) - len(new_invoices) + len(bills) - len(new_bills))

    def preview(self, data: bytes, opts: IngestOptions, *, reference: date,
                engine: OcrEngine | None = None) -> IngestPreview:
        """Parse (or OCR) an upload into a stored preview; nothing reaches the ledger."""
        if len(data) > MAX_UPLOAD_BYTES:
            raise IngestError("file_too_large", 413)
        resolver = self._resolver(opts.tenant_id)
        if is_image(data):
            if engine is None:
                raise IngestError("ocr_unavailable", 503)
            result = drafts_from_photo(data, opts, resolver, engine, reference)
        else:
            result = parse_file(data, opts, resolver)
        ledger, unpinned = self._ledger(opts.tenant_id)
        kept, duplicates = dedupe(result.transactions, ledger, result.strong_ids,
                                  unpinned_ledger_ids=unpinned)
        invoices, bills, known = self._new_documents(opts.tenant_id, result.invoices,
                                                     result.bills)
        preview = IngestPreview(
            preview_id=f"pv_{secrets.token_hex(10)}", tenant_id=opts.tenant_id,
            source_format=result.source_format,
            file_digest=keyed_digest(self._digest_key, opts.tenant_id, data),
            transactions=tuple(kept), invoices=tuple(invoices), bills=tuple(bills),
            drafts=tuple(result.drafts), unparsed=tuple(result.unparsed),
            duplicates_skipped=result.duplicates_skipped + duplicates + known,
            data_mode=result.data_mode,
        )
        strong = sorted(result.strong_ids & ({t.id for t in kept} |
                                             {d.transaction.id for d in result.drafts
                                              if d.transaction is not None}))
        self.session.add(IngestPreviewRow(
            preview_id=preview.preview_id, tenant_id=opts.tenant_id,
            file_digest=preview.file_digest, filename=opts.filename[:256],
            source_format=preview.source_format.value, status="pending",
            created_at=self._now(), payload=preview.model_dump_json(),
            strong_ids=json.dumps(strong), aliases=json.dumps(resolver.new_aliases),
        ))
        self.session.flush()
        return preview

    # ----------------------------------------------------------------- commit

    def commit(self, tenant_id: str, preview_id: str, file_digest: str,
               confirm: Collection[str] = (),
               amounts: Mapping[str, str] | None = None) -> CommitResult:
        """Commit a preview: its records, plus the drafts the owner confirmed by `row_ref`
        (optionally with a corrected amount). Refused when the digest does not match."""
        row = self.session.get(IngestPreviewRow, preview_id)
        if row is None or row.tenant_id != tenant_id:
            raise IngestError("preview_not_found", 404)
        if row.status == "committed":
            raise IngestError("already_committed", 409)
        if self._now() - _aware(row.created_at) > PREVIEW_TTL:
            raise IngestError("preview_expired", 410)
        if not hmac.compare_digest(row.file_digest, file_digest):
            raise IngestError("digest_mismatch", 409)
        preview = IngestPreview.model_validate_json(row.payload)
        drafts = {d.row_ref: d for d in preview.drafts}
        corrections = dict(amounts or {})
        if set(confirm) - drafts.keys() or set(corrections) - set(confirm):
            raise IngestError("unknown_draft", 422)
        confirmed = [_corrected(drafts[ref], corrections.get(ref))
                     for ref in dict.fromkeys(confirm)]
        txns = [*preview.transactions, *(d.transaction for d in confirmed if d.transaction)]
        invoices = [*preview.invoices, *(d.invoice for d in confirmed if d.invoice)]
        ledger, unpinned = self._ledger(tenant_id)
        kept, duplicates = dedupe(txns, ledger, set(json.loads(row.strong_ids)),
                                  unpinned_ledger_ids=unpinned)
        new_invoices, new_bills, known = self._new_documents(tenant_id, invoices, preview.bills)
        self.store.add_transactions(kept)
        self.store.add_invoices(new_invoices)
        self.store.add_bills(new_bills)
        for alias, token in json.loads(row.aliases).items():
            self.session.merge(PartyAliasRow(tenant_id=tenant_id, alias=alias, token=token))
        result = CommitResult(
            preview_id=preview_id, transactions=len(kept), invoices=len(new_invoices),
            bills=len(new_bills), drafts_confirmed=len(confirmed),
            duplicates_skipped=preview.duplicates_skipped + duplicates + known,
            committed_at=self._now(),
        )
        row.status, row.committed_at = "committed", result.committed_at
        row.summary = json.dumps({
            "transactions": result.transactions, "invoices": result.invoices,
            "bills": result.bills, "drafts_confirmed": result.drafts_confirmed,
            "duplicates_skipped": result.duplicates_skipped, "unparsed": len(preview.unparsed),
            "data_mode": preview.data_mode.value,
        })
        self.session.flush()
        return result

    # ----------------------------------------------------------------- history

    def history(self, tenant_id: str, limit: int = 50) -> list[HistoryEntry]:
        rows = self.session.scalars(
            select(IngestPreviewRow)
            .where(IngestPreviewRow.tenant_id == tenant_id, IngestPreviewRow.status == "committed")
            .order_by(IngestPreviewRow.committed_at.desc(), IngestPreviewRow.preview_id)
            .limit(limit))
        entries = []
        for row in rows:
            counts = json.loads(row.summary)
            entries.append(HistoryEntry(
                preview_id=row.preview_id, filename=row.filename, source_format=row.source_format,
                file_digest=row.file_digest, data_mode=DataMode(counts["data_mode"]),
                committed_at=_aware(row.committed_at or row.created_at),
                transactions=counts["transactions"], invoices=counts["invoices"],
                bills=counts["bills"], drafts_confirmed=counts["drafts_confirmed"],
                duplicates_skipped=counts["duplicates_skipped"], unparsed=counts["unparsed"]))
        return entries


def _corrected(draft: DraftRow, amount_text: str | None) -> DraftRow:
    """The confirmed draft, with the owner's corrected amount when one was given."""
    if amount_text is None:
        return draft
    try:
        amount = parse_amount(amount_text)
    except NormaliseError as exc:
        raise IngestError("invalid_amount", 422) from exc
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise IngestError("invalid_amount", 422)
    money = Money.of(amount)
    if draft.transaction is not None:
        record: Transaction = draft.transaction.model_copy(update={"amount": money})
        return draft.model_copy(update={"transaction": record})
    invoice: Invoice = draft.invoice.model_copy(update={"amount": money})  # type: ignore[union-attr]
    return draft.model_copy(update={"invoice": invoice})
