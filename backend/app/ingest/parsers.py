"""Parse an uploaded statement or ledger into typed ledger records (WP-02 milestone 1).

    result = parse_file(data, IngestOptions(tenant_id="sme_grocery", filename="bkash.csv"),
                        resolver)

The format is detected from the header row (or given as an explicit column mapping for generic
ledgers). Every data row becomes a `Transaction`, `Invoice` or `Bill`, or an `UnparsedRow` with
an i18n reason key; nothing is silently dropped except blank lines. Transaction ids are
deterministic (the source's own transaction id when it has one, otherwise a hash of the row's
content and its occurrence number), so re-reading a file yields the same ids.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from app.contracts import (
    Bill,
    Channel,
    DataMode,
    Direction,
    DocumentStatus,
    Invoice,
    Money,
    SourceFormat,
    Transaction,
    TxCategory,
    UnparsedRow,
)
from app.ingest import categorise as cat
from app.ingest.formats import BKASH_TYPES, LEDGER, NAGAD_TYPES, Detection, detect, with_mapping
from app.ingest.normalise import (
    NormaliseError,
    When,
    clean_text,
    header_key,
    infer_day_first,
    parse_amount,
    parse_when,
    split_drcr,
)
from app.ingest.parties import PartyResolver, identifiers, mask_excerpt
from app.ingest.tabular import Row, TableError, is_xlsx, read_sheets

INFLOW, OUTFLOW = Direction.inflow, Direction.outflow
CENT = Decimal("0.01")

SUMMARY_WORDS = tuple(header_key(w) for w in (
    "total", "grand total", "sub total", "subtotal", "opening balance", "closing balance",
    "balance b f", "balance c f", "brought forward", "carried forward", "balance forward",
    "generated on", "printed on", "page", "this is a computer generated", "statement period",
    "মোট", "সর্বমোট", "প্রারম্ভিক জের", "সমাপনী জের", "পূর্বের জের",
))

DIRECTION_WORDS: dict[str, Direction] = {header_key(k): v for k, v in {
    "in": INFLOW, "inflow": INFLOW, "credit": INFLOW, "cr": INFLOW, "receipt": INFLOW,
    "received": INFLOW, "deposit": INFLOW, "জমা": INFLOW, "আয়": INFLOW, "joma": INFLOW,
    "out": OUTFLOW, "outflow": OUTFLOW, "debit": OUTFLOW, "dr": OUTFLOW, "payment": OUTFLOW,
    "paid": OUTFLOW, "withdrawal": OUTFLOW, "খরচ": OUTFLOW, "ব্যয়": OUTFLOW,
    "khoroch": OUTFLOW,
}.items()}

CHANNEL_WORDS: dict[str, Channel] = {header_key(k): v for k, v in {
    **{c.value: c for c in Channel},
    "বিকাশ": Channel.bkash, "রকেট": Channel.rocket, "ব্যাংক": Channel.bank,
    "ক্যাশ": Channel.cash, "নগদ টাকা": Channel.cash, "কার্ড": Channel.card,
    # "নগদ" means cash in a ledger; the Nagad wallet is written in Latin script there.
    "নগদ": Channel.cash, "hand cash": Channel.cash, "cheque": Channel.bank,
}.items()}

STATUS_WORDS: dict[str, DocumentStatus] = {header_key(k): v for k, v in {
    **{s.value: s for s in DocumentStatus},
    "unpaid": DocumentStatus.open, "due": DocumentStatus.open, "outstanding": DocumentStatus.open,
    "বাকি": DocumentStatus.open, "partial": DocumentStatus.partially_paid,
    "partially paid": DocumentStatus.partially_paid, "আংশিক": DocumentStatus.partially_paid,
    "settled": DocumentStatus.paid, "closed": DocumentStatus.paid,
    "পরিশোধিত": DocumentStatus.paid, "dispute": DocumentStatus.disputed,
    "written off": DocumentStatus.written_off, "bad debt": DocumentStatus.written_off,
}.items()}


@dataclass(frozen=True)
class IngestOptions:
    tenant_id: str
    filename: str
    data_mode: DataMode = DataMode.live
    mapping: Mapping[str, str] | None = None  # generic ledger: canonical field -> header text
    document_kind: str | None = None  # registers: "invoice" or "bill"
    default_channel: Channel = Channel.cash  # generic ledgers without a channel column
    day_first: bool | None = None  # None: infer per file, Bangladeshi day-first by default


@dataclass
class ParseResult:
    source_format: SourceFormat
    default_mode: DataMode
    transactions: list[Transaction] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    bills: list[Bill] = field(default_factory=list)
    unparsed: list[UnparsedRow] = field(default_factory=list)
    duplicates_skipped: int = 0
    modes: set[DataMode] = field(default_factory=set)

    @property
    def data_mode(self) -> DataMode:
        """Synthetic if any row is synthetic (synthetic data is always labelled)."""
        if DataMode.synthetic in self.modes:
            return DataMode.synthetic
        return self.default_mode

    def reject(self, row: Row, reason_key: str) -> None:
        self.unparsed.append(UnparsedRow(row_ref=row.ref, reason_key=reason_key,
                                         raw_excerpt=mask_excerpt(",".join(row.cells))))


def _failed(opts: IngestOptions, reason_key: str) -> ParseResult:
    result = ParseResult(source_format=SourceFormat.unknown, default_mode=opts.data_mode)
    result.unparsed.append(UnparsedRow(row_ref=opts.filename, reason_key=reason_key,
                                       raw_excerpt=""))
    return result


def parse_file(data: bytes, opts: IngestOptions, resolver: PartyResolver) -> ParseResult:
    try:
        sheets = read_sheets(data, opts.filename)
    except TableError as exc:
        return _failed(opts, exc.reason_key)
    if opts.mapping:
        detection = with_mapping(sheets, LEDGER, opts.mapping)
        if detection is None:
            return _failed(opts, "ingest.mapping.headers_not_found")
    else:
        detection = detect(sheets, opts.filename)
        if detection is None:
            return _failed(opts, "ingest.format.unknown")
    xlsx = is_xlsx(data)
    result = ParseResult(source_format=detection.spec.format_for(xlsx),
                         default_mode=opts.data_mode)
    if detection.spec.name == "register":
        _parse_register(detection, opts, resolver, result)
    else:
        _parse_transactions(detection, opts, resolver, result)
    return result


# ---------------------------------------------------------------- shared row handling


Get = Callable[[str], str]


def _data_rows(detection: Detection, result: ParseResult) -> Iterator[tuple[Row, Get]]:
    """Non-blank data rows with a getter by canonical field; summary rows and rows with more
    filled cells than the header are rejected with a reason."""
    width = len(detection.header.cells)
    mapping = detection.mapping
    for row in detection.data_rows:
        if row.blank:
            continue
        if any(cell.strip() for cell in row.cells[width:]):
            result.reject(row, "ingest.row.column_mismatch")
            continue
        cells = row.cells + ("",) * max(0, width - len(row.cells))

        def get(name: str, cells: tuple[str, ...] = cells) -> str:
            return cells[mapping[name]].strip() if name in mapping else ""

        if _is_summary(row, get):
            result.reject(row, "ingest.row.summary")
            continue
        yield row, get


def _summary_word(text: str) -> bool:
    key = header_key(text)
    return bool(key) and any(key == w or key.startswith(w + " ") for w in SUMMARY_WORDS)


def _is_summary(row: Row, get: Get) -> bool:
    """Totals, opening/closing balance and footer lines. A counterparty that merely starts
    with such a word ('Total Gas Ltd') is not enough: the row must lead with it, or name it
    in the description/type while carrying no amount."""
    if _summary_word(next((c for c in row.cells if c.strip()), "")):
        return True
    no_amount = not (get("amount") or get("debit") or get("credit"))
    return no_amount and (_summary_word(get("description")) or _summary_word(get("type")))


def _row_mode(get: Get, result: ParseResult) -> DataMode:
    raw = get("data_mode").strip().lower()
    try:
        mode = DataMode(raw) if raw else result.default_mode
    except ValueError:
        mode = result.default_mode
    result.modes.add(mode)
    return mode


def _money(text: str) -> Decimal:
    value = parse_amount(text)
    if value != value.quantize(CENT):
        raise NormaliseError("ingest.amount.precision", text)
    return value


def _optional_money(text: str) -> Decimal | None:
    return _money(text) if text.strip() else None


def _when(get: Get, day_first: bool) -> When:
    text = get("when")
    if (clock := get("time")) and ":" in clock and ":" not in text:
        text = f"{text} {clock}"
    return parse_when(text, day_first=day_first)


def _day_first(detection: Detection, opts: IngestOptions, field_: str = "when") -> bool:
    if opts.day_first is not None:
        return opts.day_first
    index = detection.mapping.get(field_)
    if index is None:
        return True
    values = [r.cells[index] for r in detection.data_rows if index < len(r.cells)]
    return infer_day_first(values)


# ---------------------------------------------------------------- transactions


class _Builder:
    def __init__(self, spec: str, opts: IngestOptions, resolver: PartyResolver,
                 result: ParseResult) -> None:
        self.spec, self.opts, self.resolver, self.result = spec, opts, resolver, result
        self.seen: set[str] = set()
        self.occurrences: Counter[str] = Counter()

    def add(self, row: Row, *, when: When, amount: Decimal, direction: Direction,
            channel: Channel, category: TxCategory, reference: str | None,
            party_ids: tuple[str, ...], external_id: str | None, mode: DataMode,
            fee: Decimal | None = None, content: str = "") -> None:
        if amount == 0:
            raise NormaliseError("ingest.amount.zero")
        tenant = self.opts.tenant_id
        if external_id:
            tx_id = f"{tenant}:{self.spec}:{external_id}"
            if tx_id in self.seen:
                self.result.duplicates_skipped += 1
                return
        else:
            key = "|".join([when.at.isoformat(), str(amount), direction.value, channel.value,
                            reference or "", content, *party_ids])
            number = self.occurrences[key]
            self.occurrences[key] += 1
            digest = hashlib.sha256(f"{key}|{number}".encode()).hexdigest()[:16]
            tx_id = f"{tenant}:{self.spec}:{digest}"
        self.seen.add(tx_id)
        token = self.resolver.resolve(tenant, party_ids)
        invoice_id = (f"{tenant}:{reference}"
                      if category is TxCategory.collection and reference else None)
        txn = Transaction(
            id=tx_id, tenant_id=tenant, occurred_at=when.aware(), amount=Money.of(amount),
            direction=direction, channel=channel, category=category, counterparty_token=token,
            reference=reference or None, invoice_id=invoice_id, source_ref=row.ref,
            data_mode=mode,
        )
        self.result.transactions.append(txn)
        if fee is not None and fee > 0:
            self.result.transactions.append(txn.model_copy(update={
                "id": f"{tx_id}:fee", "amount": Money.of(fee), "direction": OUTFLOW,
                "category": TxCategory.fee, "counterparty_token": None, "invoice_id": None,
            }))


def _parse_transactions(detection: Detection, opts: IngestOptions, resolver: PartyResolver,
                        result: ParseResult) -> None:
    spec = detection.spec.name
    builder = _Builder(spec, opts, resolver, result)
    day_first = _day_first(detection, opts)
    handler = {"bkash": _wallet_row, "nagad": _wallet_row, "bank": _bank_row,
               "ledger": _ledger_row}[spec]
    for row, get in _data_rows(detection, result):
        try:
            handler(spec, row, get, day_first, builder)
        except NormaliseError as exc:
            result.reject(row, exc.reason_key)
        except ValidationError:
            result.reject(row, "ingest.row.invalid")


def _wallet_row(spec: str, row: Row, get: Get, day_first: bool, builder: _Builder) -> None:
    """bKash / Nagad statement row."""
    labels, channel = (BKASH_TYPES, Channel.bkash) if spec == "bkash" else \
        (NAGAD_TYPES, Channel.nagad)
    when = _when(get, day_first)
    amount = _money(get("amount"))
    label = labels.get(header_key(get("type")))
    if label is not None:
        direction, base, strong = label
    elif amount < 0:
        direction, base, strong = OUTFLOW, None, False
    else:
        raise NormaliseError("ingest.type.unknown", get("type"))
    counterparty, reference = get("counterparty"), get("reference")
    category = cat.categorise(direction, label=base, label_is_strong=strong,
                              reference=reference, text=counterparty)
    builder.add(row, when=when, amount=abs(amount), direction=direction, channel=channel,
                category=category, reference=reference, party_ids=identifiers(counterparty),
                external_id=get("external_id"), mode=_row_mode(get, builder.result),
                fee=_optional_money(get("fee")))


def _signed_amount(get: Get) -> tuple[Decimal, Direction]:
    """Direction and size from Debit/Credit columns, or from Amount with a Dr/Cr marker."""
    debit, credit = _optional_money(get("debit")), _optional_money(get("credit"))
    if debit or credit:
        if debit and credit:
            raise NormaliseError("ingest.row.both_debit_and_credit")
        value, direction = (debit, OUTFLOW) if debit else (credit, INFLOW)
        if value is None or value < 0:
            raise NormaliseError("ingest.amount.negative")
        return value, direction
    text, marker = split_drcr(get("amount"))
    marker = marker or header_key(get("drcr")) or None
    if not text.strip():
        raise NormaliseError("ingest.amount.missing")
    value = _money(text)
    if marker is not None:
        direction = DIRECTION_WORDS.get(header_key(marker))
        if direction is None:
            raise NormaliseError("ingest.direction.unknown", marker)
        return abs(value), direction
    return abs(value), (OUTFLOW if value < 0 else INFLOW)


def _bank_row(spec: str, row: Row, get: Get, day_first: bool, builder: _Builder) -> None:
    when = _when(get, day_first)
    amount, direction = _signed_amount(get)
    description, reference = clean_text(get("description")), get("reference")
    category = cat.categorise(direction, reference=reference, text=description)
    counterparty = description
    span = cat.keyword_span(description)
    if span is not None and span[0] == 0:
        counterparty = description[span[1]:].strip(" -/:")
    builder.add(row, when=when, amount=amount, direction=direction, channel=Channel.bank,
                category=category, reference=reference, party_ids=identifiers(counterparty),
                external_id=None, mode=_row_mode(get, builder.result),
                content=description)


def _ledger_row(spec: str, row: Row, get: Get, day_first: bool, builder: _Builder) -> None:
    when = _when(get, day_first)
    if get("direction") or get("amount"):
        value = _money(get("amount"))
        word = header_key(get("direction"))
        direction = DIRECTION_WORDS.get(word) if word else (OUTFLOW if value < 0 else INFLOW)
        if direction is None:
            raise NormaliseError("ingest.direction.unknown", get("direction"))
        amount = abs(value)
    else:
        amount, direction = _signed_amount(get)
    channel = builder.opts.default_channel
    if raw := get("channel"):
        channel = CHANNEL_WORDS.get(header_key(raw)) or _unknown_channel(raw)
    description, reference = clean_text(get("description")), get("reference")
    counterparty = get("counterparty")
    category = cat.categorise(direction, column=get("category"), reference=reference,
                              text=" ".join(t for t in (description, counterparty) if t))
    builder.add(row, when=when, amount=amount, direction=direction, channel=channel,
                category=category, reference=reference,
                party_ids=identifiers(counterparty, get("phone")),
                external_id=get("external_id"), mode=_row_mode(get, builder.result),
                content=description)


def _unknown_channel(raw: str) -> Channel:
    raise NormaliseError("ingest.channel.unknown", raw)


# ---------------------------------------------------------------- invoice / bill registers


_INVOICE_HINTS = ("baki", "invoice", "receivable", "customer", "sales")
_BILL_HINTS = ("bill", "payable", "supplier", "purchase")


def _document_kind(detection: Detection, opts: IngestOptions) -> str | None:
    if opts.document_kind in ("invoice", "bill"):
        return opts.document_kind
    name = opts.filename.casefold()
    if any(h in name for h in _INVOICE_HINTS):
        return "invoice"
    if any(h in name for h in _BILL_HINTS):
        return "bill"
    index = detection.mapping["number"]
    numbers = [r.cells[index].upper() for r in detection.data_rows[:50] if index < len(r.cells)]
    if numbers and all("INV" in n for n in numbers if n):
        return "invoice"
    if numbers and all("BILL" in n for n in numbers if n):
        return "bill"
    return None


def _parse_register(detection: Detection, opts: IngestOptions, resolver: PartyResolver,
                    result: ParseResult) -> None:
    kind = _document_kind(detection, opts)
    if kind is None:
        result.unparsed.append(UnparsedRow(row_ref=opts.filename,
                                           reason_key="ingest.document.kind_required",
                                           raw_excerpt=""))
        return
    cls: type[Invoice] | type[Bill] = Invoice if kind == "invoice" else Bill
    target = result.invoices if kind == "invoice" else result.bills
    issue_first = _day_first(detection, opts, "issue_date")
    seen: set[str] = set()
    for row, get in _data_rows(detection, result):
        try:
            doc = _document(cls, row, get, opts, resolver, issue_first, result)
        except NormaliseError as exc:
            result.reject(row, exc.reason_key)
            continue
        except ValidationError:
            result.reject(row, "ingest.document.invalid")
            continue
        if doc.id in seen:
            result.duplicates_skipped += 1
            continue
        seen.add(doc.id)
        target.append(doc)


def _date(text: str, day_first: bool) -> date:
    return parse_when(text, day_first=day_first).at.date()


def _document(cls: type[Invoice] | type[Bill], row: Row, get: Get, opts: IngestOptions,
              resolver: PartyResolver, day_first: bool, result: ParseResult) -> Invoice | Bill:
    number = clean_text(get("number"))
    if not number:
        raise NormaliseError("ingest.document.number_missing")
    issue = _date(get("issue_date"), day_first)
    # A register without a due date means "payable on demand": due the day it was issued.
    due = _date(get("due_date"), day_first) if get("due_date") else issue
    amount = _money(get("amount"))
    paid = _optional_money(get("amount_paid")) or Decimal(0)
    if amount <= 0 or paid < 0:
        raise NormaliseError("ingest.amount.negative")
    paid_date = _date(get("paid_date"), day_first) if get("paid_date") else None
    raw_status = header_key(get("status"))
    if raw_status:
        status = STATUS_WORDS.get(raw_status)
        if status is None:
            raise NormaliseError("ingest.document.status_unknown", get("status"))
    elif paid == 0:
        status = DocumentStatus.open
    elif paid < amount:
        status = DocumentStatus.partially_paid
    else:
        status = DocumentStatus.paid
    party_ids = identifiers(get("counterparty"), get("phone"))
    token = resolver.resolve(opts.tenant_id, party_ids)
    if token is None:
        raise NormaliseError("ingest.document.party_missing")
    return cls(
        id=f"{opts.tenant_id}:{number}", tenant_id=opts.tenant_id, counterparty_token=token,
        issue_date=issue, due_date=due, amount=Money.of(amount), amount_paid=Money.of(paid),
        status=status, paid_date=paid_date, source_ref=row.ref,
        data_mode=_row_mode(get, result),
    )
