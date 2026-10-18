"""Source formats and automatic detection (WP-02).

Each format declares, per canonical field, the header names it is known to use (English,
Bangla and Banglish), compared after `header_key()` normalisation. Matching is exact on that
canonical form; there is no fuzzy matching. Detection scans the first rows of every sheet for
the row that is a header of some format, so preamble lines above the table are skipped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.contracts import Direction, SourceFormat, TxCategory
from app.ingest.normalise import header_key
from app.ingest.tabular import Row, Sheet

HEADER_SCAN_ROWS = 30
LABEL_SAMPLE_ROWS = 50

# Transaction-type labels -> (direction, category, is the label alone decisive for category)
Label = tuple[Direction, TxCategory | None, bool]
_C = TxCategory
INFLOW, OUTFLOW = Direction.inflow, Direction.outflow
BKASH_TYPES: dict[str, Label] = {header_key(k): v for k, v in {
    "payment received": (INFLOW, _C.sales, False),
    "received payment": (INFLOW, _C.sales, False),
    "merchant payment received": (INFLOW, _C.sales, False),
    "money received": (INFLOW, None, False),
    "received money": (INFLOW, None, False),
    "receive money": (INFLOW, None, False),
    "cash in": (INFLOW, _C.transfer, True),
    "add money": (INFLOW, _C.transfer, True),
    "bank to bkash": (INFLOW, _C.transfer, True),
    "refund": (INFLOW, _C.other, True),
    "send money": (OUTFLOW, None, False),
    "cash out": (OUTFLOW, _C.transfer, True),
    "pay bill": (OUTFLOW, _C.utility, True),
    "paybill": (OUTFLOW, _C.utility, True),
    "bill payment": (OUTFLOW, _C.utility, True),
    "payment": (OUTFLOW, None, False),
    "make payment": (OUTFLOW, None, False),
    "merchant payment": (OUTFLOW, None, False),
    "bkash to bank": (OUTFLOW, _C.transfer, True),
    "transfer to bank": (OUTFLOW, _C.transfer, True),
    "mobile recharge": (OUTFLOW, _C.utility, True),
    "recharge": (OUTFLOW, _C.utility, True),
    "fee": (OUTFLOW, _C.fee, True),
    "charge": (OUTFLOW, _C.fee, True),
}.items()}
NAGAD_TYPES: dict[str, Label] = {header_key(k): v for k, v in {
    "received": (INFLOW, _C.sales, False),
    "receive money": (INFLOW, _C.sales, False),
    "payment received": (INFLOW, _C.sales, False),
    "cash in": (INFLOW, _C.transfer, True),
    "add money": (INFLOW, _C.transfer, True),
    "bank to nagad": (INFLOW, _C.transfer, True),
    "sent": (OUTFLOW, None, False),
    "send money": (OUTFLOW, None, False),
    "cash out": (OUTFLOW, _C.transfer, True),
    "bill pay": (OUTFLOW, _C.utility, True),
    "bill payment": (OUTFLOW, _C.utility, True),
    "payment": (OUTFLOW, None, False),
    "merchant pay": (OUTFLOW, None, False),
    "nagad to bank": (OUTFLOW, _C.transfer, True),
    "mobile recharge": (OUTFLOW, _C.utility, True),
}.items()}


def _keys(*names: str) -> tuple[str, ...]:
    return tuple(header_key(n) for n in names)


@dataclass(frozen=True)
class FormatSpec:
    name: str
    source_format: SourceFormat
    columns: Mapping[str, tuple[str, ...]]
    # Each entry is a set of alternatives; at least one field of every entry must be present.
    required: tuple[frozenset[str], ...]
    signature: frozenset[str] = frozenset()
    filename_hints: tuple[str, ...] = ()
    priority: int = 0
    xlsx_format: SourceFormat | None = None
    # Wallet formats: known transaction-type labels, used to break ties between look-alikes.
    type_labels: Mapping[str, Label] = field(default_factory=dict)
    # Institution exports with a fixed dd/mm date order (bKash, Nagad, Bangladeshi banks).
    known_day_first: bool = False

    def map_header(self, header: Sequence[str]) -> dict[str, int]:
        """canonical field -> column index, each column used at most once, first match wins."""
        keys = [header_key(h) for h in header]
        mapping: dict[str, int] = {}
        used: set[int] = set()
        for name, synonyms in self.columns.items():
            for synonym in synonyms:
                index = next((i for i, k in enumerate(keys) if k == synonym and i not in used),
                             None)
                if index is not None:
                    mapping[name] = index
                    used.add(index)
                    break
        return mapping

    def satisfied(self, mapping: Mapping[str, int]) -> bool:
        return all(any(f in mapping for f in group) for group in self.required)

    def score(self, header: Sequence[str], mapping: Mapping[str, int], filename: str,
              rows: Sequence[Row] = ()) -> int:
        keys = {header_key(h) for h in header}
        hint = any(h in filename.casefold() for h in self.filename_hints)
        return (len(mapping) + 3 * len(self.signature & keys) + 4 * hint + self.priority
                + self.label_votes(mapping, rows))

    def label_votes(self, mapping: Mapping[str, int], rows: Sequence[Row]) -> int:
        """0-3 points for how many sampled rows carry a transaction type this format knows."""
        index = mapping.get("type")
        if not self.type_labels or index is None:
            return 0
        labels = [header_key(r.cells[index]) for r in rows[:LABEL_SAMPLE_ROWS]
                  if index < len(r.cells) and r.cells[index].strip()]
        known = sum(1 for label in labels if label in self.type_labels)
        return 3 * known // max(1, len(labels))

    def format_for(self, xlsx: bool) -> SourceFormat:
        return self.xlsx_format if xlsx and self.xlsx_format else self.source_format


_DATA_MODE = _keys("data mode", "data_mode")

BKASH = FormatSpec(
    name="bkash",
    source_format=SourceFormat.bkash_statement,
    columns={
        "external_id": _keys("trxid", "trx id", "transaction id", "txn id", "txnid",
                             "transaction no", "trx no"),
        "when": _keys("date time", "datetime", "transaction date time", "date and time",
                      "transaction date", "date", "timestamp", "time stamp"),
        "time": _keys("time", "transaction time"),
        "type": _keys("transaction type", "trx type", "txn type", "type"),
        "counterparty": _keys("from to", "from/to", "to from", "counterparty", "account",
                              "wallet", "other party", "sender receiver", "customer"),
        "amount": _keys("amount bdt", "amount", "amount tk", "transaction amount"),
        "fee": _keys("fee", "fee bdt", "charge", "service charge"),
        "balance": _keys("balance", "balance bdt", "available balance"),
        "reference": _keys("reference", "ref", "remarks", "note"),
        "data_mode": _DATA_MODE,
    },
    required=(frozenset({"external_id"}), frozenset({"when"}), frozenset({"type"}),
              frozenset({"amount"})),
    signature=frozenset(_keys("trxid", "from to", "amount bdt")),
    filename_hints=("bkash", "বিকাশ"),
    priority=2,
    type_labels=BKASH_TYPES,
    known_day_first=True,
)

NAGAD = FormatSpec(
    name="nagad",
    source_format=SourceFormat.nagad_statement,
    columns={
        "external_id": _keys("txn id", "transaction id", "trx id", "txnid", "trxid"),
        "when": _keys("txn date", "transaction date", "date time", "datetime", "date"),
        "time": _keys("time", "txn time", "transaction time"),
        "type": _keys("txn type", "transaction type", "type"),
        "counterparty": _keys("counterpart", "counterparty", "from to", "to from", "account",
                              "customer"),
        "amount": _keys("amount", "txn amount", "transaction amount", "amount bdt"),
        "fee": _keys("charge", "fee", "service charge"),
        "balance": _keys("balance", "available balance"),
        "reference": _keys("reference", "ref", "remarks", "note"),
        "data_mode": _DATA_MODE,
    },
    required=(frozenset({"external_id"}), frozenset({"when"}), frozenset({"type"}),
              frozenset({"amount"})),
    signature=frozenset(_keys("txn id", "txn type", "counterpart", "txn date")),
    filename_hints=("nagad",),
    priority=2,
    type_labels=NAGAD_TYPES,
    known_day_first=True,
)

BANK = FormatSpec(
    name="bank",
    source_format=SourceFormat.bank_csv,
    columns={
        "when": _keys("date", "transaction date", "txn date", "tran date", "trans date",
                      "posting date", "value date"),
        "description": _keys("description", "particulars", "narration", "details",
                             "transaction details", "transaction particulars", "remarks"),
        "reference": _keys("cheque ref no", "cheque no", "chq no", "cheque number",
                           "ref no", "reference", "instrument no", "ref", "cheque"),
        "debit": _keys("debit", "withdrawal", "withdrawals", "debit amount",
                       "withdrawal amount", "dr amount", "withdraw"),
        "credit": _keys("credit", "deposit", "deposits", "credit amount", "deposit amount",
                        "cr amount"),
        "amount": _keys("amount", "transaction amount"),
        "drcr": _keys("dr cr", "drcr", "cr dr", "debit credit", "type"),
        "balance": _keys("balance", "running balance", "available balance", "balance bdt"),
        "data_mode": _DATA_MODE,
    },
    required=(frozenset({"when"}), frozenset({"description", "reference"}),
              frozenset({"debit", "amount"}), frozenset({"credit", "amount"})),
    signature=frozenset(_keys("debit", "credit", "particulars", "narration", "withdrawal",
                              "deposit", "cheque ref no", "value date")),
    filename_hints=("bank", "dbbl", "brac", "ebl", "ibbl", "sonali", "city"),
    priority=1,
    known_day_first=True,
)

LEDGER = FormatSpec(
    name="ledger",
    source_format=SourceFormat.ledger_csv,
    xlsx_format=SourceFormat.ledger_xlsx,
    columns={
        "external_id": _keys("id", "entry id", "voucher no", "voucher"),
        "when": _keys("occurred at", "date time", "datetime", "date", "transaction date",
                      "entry date", "তারিখ", "tarikh"),
        "time": _keys("time", "সময়"),
        "direction": _keys("direction", "type", "in out", "flow", "dr cr", "ধরন"),
        "amount": _keys("amount", "amount bdt", "amount tk", "taka", "টাকা", "পরিমাণ",
                        "টাকার পরিমাণ"),
        "credit": _keys("credit", "in", "income", "জমা", "আয়", "joma"),
        "debit": _keys("debit", "out", "expense", "খরচ", "ব্যয়", "khoroch"),
        "counterparty": _keys("counterparty", "party", "name", "customer", "supplier",
                              "নাম", "পার্টি"),
        "phone": _keys("phone", "mobile", "mobile no", "phone no", "ফোন", "মোবাইল"),
        "category": _keys("category", "head", "account head", "খাত"),
        "channel": _keys("channel", "mode", "payment mode", "method", "payment method",
                         "মাধ্যম"),
        "reference": _keys("reference", "ref", "memo", "memo no", "রেফারেন্স"),
        "description": _keys("description", "particulars", "details", "remarks", "note",
                             "বিবরণ"),
        "balance": _keys("balance", "ব্যালেন্স"),
        "data_mode": _DATA_MODE,
    },
    required=(frozenset({"when"}), frozenset({"amount", "credit"}),
              frozenset({"direction", "debit"})),
)

REGISTER = FormatSpec(
    name="register",
    source_format=SourceFormat.ledger_csv,
    xlsx_format=SourceFormat.ledger_xlsx,
    columns={
        "number": _keys("number", "invoice no", "invoice number", "bill no", "bill number",
                        "memo no", "no", "নং"),
        "counterparty": _keys("party", "customer", "supplier", "name", "নাম"),
        "phone": _keys("phone", "mobile", "mobile no", "ফোন", "মোবাইল"),
        "issue_date": _keys("issue date", "invoice date", "bill date", "date", "তারিখ"),
        "due_date": _keys("due date", "due", "পরিশোধের তারিখ"),
        "amount": _keys("amount", "total", "invoice amount", "bill amount", "টাকা"),
        "amount_paid": _keys("amount paid", "paid", "paid amount", "জমা"),
        "paid_date": _keys("paid date", "payment date"),
        "status": _keys("status", "অবস্থা"),
        "note": _keys("note", "remarks", "মন্তব্য"),
        "data_mode": _DATA_MODE,
    },
    required=(frozenset({"number"}), frozenset({"counterparty"}), frozenset({"issue_date"}),
              frozenset({"amount"}), frozenset({"due_date", "amount_paid", "status"})),
    signature=frozenset(_keys("amount paid", "due date", "issue date")),
    filename_hints=("baki", "register", "invoice", "bill", "khata"),
    priority=1,
)

FORMATS: tuple[FormatSpec, ...] = (BKASH, NAGAD, BANK, REGISTER, LEDGER)
BY_NAME = {spec.name: spec for spec in FORMATS}


@dataclass(frozen=True)
class Detection:
    spec: FormatSpec
    sheet: Sheet
    header_index: int
    mapping: dict[str, int] = field(default_factory=dict)

    @property
    def header(self) -> Row:
        return self.sheet.rows[self.header_index]

    @property
    def data_rows(self) -> tuple[Row, ...]:
        return self.sheet.rows[self.header_index + 1:]

    @property
    def preamble(self) -> tuple[Row, ...]:
        return self.sheet.rows[: self.header_index]


def detect(sheets: Sequence[Sheet], filename: str,
           formats: Sequence[FormatSpec] = FORMATS) -> Detection | None:
    """Best (format, header row) over all sheets, or None when no format's header is found."""
    best: tuple[int, Detection] | None = None
    for sheet in sheets:
        for index, row in enumerate(sheet.rows[:HEADER_SCAN_ROWS]):
            if row.blank:
                continue
            for spec in formats:
                mapping = spec.map_header(row.cells)
                if not spec.satisfied(mapping):
                    continue
                score = spec.score(row.cells, mapping, filename, sheet.rows[index + 1:])
                if best is None or score > best[0]:
                    best = (score, Detection(spec, sheet, index, mapping))
        if best is not None:
            break  # the first sheet with a recognisable table wins
    return best[1] if best else None


def with_mapping(sheets: Sequence[Sheet], spec: FormatSpec,
                 columns: Mapping[str, str]) -> Detection | None:
    """Detection from an explicit column mapping (the generic-ledger mapping step):
    `columns` maps canonical field -> the header text the owner picked."""
    wanted = {field_: header_key(text) for field_, text in columns.items()}
    for sheet in sheets:
        for index, row in enumerate(sheet.rows[:HEADER_SCAN_ROWS]):
            keys = [header_key(c) for c in row.cells]
            mapping = {f: keys.index(k) for f, k in wanted.items() if k in keys}
            if len(mapping) == len(wanted) and spec.satisfied(mapping):
                return Detection(spec, sheet, index, mapping)
    return None
