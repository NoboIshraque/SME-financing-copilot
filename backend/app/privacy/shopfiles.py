"""Anonymise a folder of real shop files before they enter the repo (WP-03 tooling for WP-20).

    cd backend
    uv run python -m app.privacy.shopfiles "<folder with the raw files>" --shop shop01-grocery

Input: CSV and XLSX exports (bKash/Nagad/bank statements, a typed-up baki register, ...).
Output: `data/real_anonymised/<shop>/fileNN.csv` (one CSV per sheet) plus `REPORT.json`, which
holds counts by kind and column roles, never values.

How each cell is treated, by its column header (English or Bangla):
- name / party / customer / supplier columns: the whole cell becomes a PERSON or SHOP token,
  even for names no detector knows (a phone number in such a column becomes a PHONE token);
- phone / account / card / NID columns: PHONE or ACCOUNT token;
- transaction-ID columns: a keyed pseudonym (TRX_xxxxxxxxxx), stable within the shop;
- columns whose every value is a date, a time or an amount are kept as they are (backtests need
  them);
- everything else is free text: every detector runs, plus every name seen in a name column of
  any file of this shop and the names listed in an optional `known_names.txt` in the input
  folder (owner, shop, staff; one per line).

Fail closed: after tokenising, every output cell is scanned again; a file with anything left
is not written and the report says which kinds were found. Rows above the header row (statement
preambles with the account holder's name and number) are dropped. XLSX properties (author,
company) never reach the output because only CSV is written. Output files get generic names,
because raw file names often contain the shop's or a person's name; the console (never a file)
shows which input became which output.

Tokens come from the WP-03 vault, so the same phone or name gets the same token in every file
of a shop (files stay joinable). The vault (encrypted originals) and its key live in
`~/.hishab/`, outside git; keep that folder off the repo and off shared drives.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.privacy.detectors import SHOP_SUFFIX, Kind, detect, to_ascii_digits
from app.privacy.models import VaultEntry
from app.privacy.store import SqlVaultEntries
from app.privacy.vault import TOKEN_RE, TokenVault, tokenise

TOOL_VERSION = "1"
DATA_MODE = "real_anonymised"
DHAKA = ZoneInfo("Asia/Dhaka")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")
SPREADSHEETS = {".csv", ".xlsx", ".xlsm"}
IMAGES = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".pdf"}
TRX_RE = re.compile(r"\bTRX_[0-9a-f]{10}\b")
_PHONE_CELL = re.compile(r"(?:\+?88[\s-]?)?01[3-9](?:[\s-]?\d){8}")


class Role(StrEnum):
    NAME = "name"
    PHONE = "phone"
    ACCOUNT = "account"
    TXN_ID = "transaction_id"
    KEPT = "kept"  # every value is a date, time or amount
    FREE = "free_text"


# Header keywords (case-insensitive substring match), checked in this order.
_ROLE_WORDS: tuple[tuple[Role, tuple[str, ...]], ...] = (
    (Role.TXN_ID, ("trxid", "trx id", "txnid", "txn id", "transaction id", "transaction no",
                   "trans id", "ট্রানজেকশন আইডি", "লেনদেন নং")),
    (Role.ACCOUNT, ("account", "a/c", "acc no", "card", "nid", "national id", "iban", "routing",
                    "হিসাব নং", "অ্যাকাউন্ট", "একাউন্ট", "কার্ড", "জাতীয় পরিচয়")),
    (Role.PHONE, ("phone", "mobile", "cell", "contact", "msisdn", "wallet", "from/to",
                  "sender no", "receiver no", "মোবাইল", "ফোন", "নম্বর")),
    (Role.NAME, ("name", "party", "customer", "client", "supplier", "vendor", "payee", "payer",
                 "sender", "receiver", "recipient", "counterparty", "counterpart", "owner",
                 "merchant", "buyer",
                 "নাম", "গ্রাহক", "ক্রেতা", "পার্টি", "সরবরাহকারী", "দোকান", "মালিক")),
)
_HEADER_HINTS = ("date", "amount", "time", "balance", "type", "status", "description", "debit",
                 "credit", "paid", "due", "particulars", "narration", "remarks", "reference",
                 "fee", "তারিখ", "টাকা", "পরিমাণ", "বিবরণ", "বাকি", "জমা")
# Columns about goods, not people: never treated as name columns (detectors still run).
_GOODS_WORDS = ("item", "product", "goods", "commodity", "article", "পণ্য", "মালের")
# Generic values seen in name columns that must not become "names" to mask everywhere.
_NOT_NAMES = {"cash", "bank", "self", "walk-in", "walk in", "customer", "others", "other",
              "misc", "n/a", "na", "none", "unknown", "নগদ", "ব্যাংক", "নিজ", "অন্যান্য"}
# Name parts that are titles or shop-type words: masking them everywhere would only destroy
# ordinary text ("General", "Traders"). Every other part of a name is masked on its own too,
# so "ask Motaleb's son" is caught when the name column said "Abdul Motaleb".
# A name-column value made only of these words is a label ("Walk-in customer", "Own bank
# account"), not a name: it is kept (detectors still run) and never masked elsewhere.
_GENERIC_WORDS = _NOT_NAMES | {
    "walk", "in", "own", "account", "personal", "owner", "staff", "salary", "rent", "supplier",
    "suppliers", "various", "sundry", "retail", "wholesale", "counter", "sale", "sales", "misc",
    "customers", "a/c", "wallet", "drawer", "petty", "office", "shop", "store", "home", "family",
    # public utilities and billers are not personal data
    "utility", "utilities", "bill", "bills", "electricity", "gas", "water", "internet", "desco",
    "dpdc", "titas", "wasa", "nesco", "reb", "palli", "bidyut", "btcl",
}
_NAME_PART_STOP = _GENERIC_WORDS | {
    "md", "mohammad", "mohammed", "muhammad", "mst", "mosammat", "mrs", "mr", "miss", "the",
    "and", "stores", "traders", "trading", "enterprise", "enterprises", "general",
    "bhandar", "agency", "corporation", "house", "pharmacy", "telecom", "fashion", "textile",
    "textiles", "hardware", "mart", "brothers", "son", "sons", "co", "ltd", "limited",
    "dhaka", "bangladesh", "bd", "new", "bhai",
    "মোঃ", "মোছাঃ", "স্টোর", "ট্রেডার্স", "এন্টারপ্রাইজ", "ভান্ডার", "জেনারেল",
}
_SPLIT = re.compile(r"[\s.,'’()\-/&]+")


def is_generic_label(value: str) -> bool:
    words = [w for w in _SPLIT.split(value.casefold()) if w]
    return bool(words) and all(w in _GENERIC_WORDS for w in words)


def name_and_parts(name: str) -> set[str]:
    parts = {p for p in _SPLIT.split(name) if len(p) >= 3 and p.casefold() not in _NAME_PART_STOP}
    return {name.strip(), *parts}

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%y",
                 "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%d-%b-%y")
_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p")
_AMOUNT_RE = re.compile(r"[-+(]?(?:৳|tk\.?|bdt)?\s*\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?\)?"
                        r"|[-+(]?(?:৳|tk\.?|bdt)?\s*\d{1,9}(?:\.\d{1,2})?\)?", re.I)


class ShopfilesError(RuntimeError):
    """A refusal: bad input, unsafe paths or a file that failed the final privacy scan."""


# ---------------------------------------------------------------- reading


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, float):
        number = Decimal(repr(value))
        return format(number.normalize(), "f") if number == number.to_integral() else str(number)
    return str(value).strip()


def read_tables(path: Path) -> list[tuple[str, list[list[str]]]]:
    """[(sheet name, rows)] for a CSV (one table) or an XLSX (one table per non-empty sheet)."""
    if path.suffix.lower() == ".csv":
        text = _decode(path.read_bytes())
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [[_cell_text(c) for c in row] for row in csv.reader(io.StringIO(text), dialect)]
        return [("", rows)]
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    tables = []
    for sheet in workbook.worksheets:
        rows = [[_cell_text(c) for c in row] for row in sheet.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if rows:
            tables.append((sheet.title, rows))
    workbook.close()
    return tables


def _header_score(row: Sequence[str]) -> int:
    cells = [re.sub(r"\s+", " ", c.casefold()).strip() for c in row if c]
    return sum(1 for c in cells if column_role_from_header(c) is not Role.FREE
               or any(_has_word(c, h) for h in _HEADER_HINTS))


def find_header(rows: Sequence[Sequence[str]]) -> int:
    """Index of the header row: among the first 30 rows, the one naming the most known columns
    (at least 2; the earliest wins a tie). A preamble line such as "Account Number | 017..."
    names one. Falls back to the first row with 2+ non-empty cells. Rows above it are dropped.
    """
    scores = [_header_score(row) for row in rows[:30]]
    if scores and max(scores) >= 2:
        return scores.index(max(scores))
    for i, row in enumerate(rows):
        if sum(1 for c in row if c) >= 2:
            return i
    return 0


# ---------------------------------------------------------------- column roles


def _has_word(header: str, word: str) -> bool:
    if word.isascii():  # whole words, optional plural: "cancelled" is not "cell"
        return re.search(rf"(?<![a-z]){re.escape(word)}s?(?![a-z])", header) is not None
    return word in header


def column_role_from_header(header: str) -> Role:
    h = re.sub(r"\s+", " ", header.casefold()).strip()
    goods = any(_has_word(h, w) for w in _GOODS_WORDS)
    for role, words in _ROLE_WORDS:
        if role is Role.NAME and goods:
            continue
        if any(_has_word(h, w) for w in words):
            return role
    return Role.FREE


_DATETIME_FORMATS = (*_DATE_FORMATS, *_TIME_FORMATS,
                     *(f"{d}{sep}{t}" for d in _DATE_FORMATS for sep in (" ", "T")
                       for t in _TIME_FORMATS))


def _is_date_time_or_amount(value: str) -> bool:
    """Strict: an amount (at most 9 integer digits), a date, a time or a date with a time."""
    v = re.sub(r"\s+", " ", to_ascii_digits(value)).strip()
    if not v or _AMOUNT_RE.fullmatch(v):
        return True
    for fmt in _DATETIME_FORMATS:
        try:
            time.strptime(v, fmt)
        except ValueError:
            continue
        return True
    return False


def column_role(header: str, values: Iterable[str]) -> Role:
    role = column_role_from_header(header)
    if role is not Role.FREE:
        return role
    values = list(values)
    if any(values) and all(_is_date_time_or_amount(v) for v in values):
        return Role.KEPT
    return Role.FREE


# ---------------------------------------------------------------- tokenising


@dataclass
class ShopTokeniser:
    vault: TokenVault
    tenant: str
    trx_key: bytes
    party_names: set[str] = field(default_factory=set)
    shop_names: set[str] = field(default_factory=set)

    def name_cell(self, value: str, counts: Counter[str]) -> str:
        if not value:
            return value
        if is_generic_label(value):
            return self.free_cell(value, counts)
        digits = re.sub(r"\D", "", to_ascii_digits(value))
        if _PHONE_CELL.fullmatch(to_ascii_digits(value).strip()):
            kind = Kind.PHONE
        elif len(digits) >= 10 and len(digits) >= len(value.replace(" ", "")) - 2:
            kind = Kind.ACCOUNT
        elif SHOP_SUFFIX.search(value) or value.casefold() in {s.casefold()
                                                                for s in self.shop_names}:
            kind = Kind.SHOP
        else:
            kind = Kind.PERSON
        counts[kind.value] += 1
        return self.vault.put(self.tenant, kind, value)

    def number_cell(self, value: str, kind: Kind, counts: Counter[str]) -> str:
        if not value:
            return value
        if kind is Kind.PHONE and not _PHONE_CELL.fullmatch(to_ascii_digits(value).strip()):
            # bKash "From/To" can hold a contact's name or a biller instead of a number.
            return self.name_cell(value, counts)
        counts[kind.value] += 1
        return self.vault.put(self.tenant, kind, value)

    def trx_cell(self, value: str, counts: Counter[str]) -> str:
        if not value:
            return value
        counts["TRANSACTION_ID"] += 1
        material = f"{self.tenant}|trx|{value.strip()}".encode()
        return "TRX_" + hmac.new(self.trx_key, material, hashlib.sha256).hexdigest()[:10]

    def free_cell(self, value: str, counts: Counter[str]) -> str:
        if not value:
            return value
        result = tokenise(self.vault, self.tenant, value, party_names=self.party_names,
                          shop_names=self.shop_names)
        counts.update(k.value for k in result.kinds)
        return result.text

    def cell(self, role: Role, value: str, counts: Counter[str]) -> str:
        if role is Role.NAME:
            return self.name_cell(value, counts)
        if role is Role.PHONE:
            return self.number_cell(value, Kind.PHONE, counts)
        if role is Role.ACCOUNT:
            return self.number_cell(value, Kind.ACCOUNT, counts)
        if role is Role.TXN_ID:
            return self.trx_cell(value, counts)
        if role is Role.KEPT:
            return value
        return self.free_cell(value, counts)


_REVIEW_WORD = re.compile(r"(?<![\w])(?:[A-Z][a-z]{2,}|[ঀ-৿]{2,})(?![\w])")
_REVIEW_SKIP = {w.casefold() for w in (
    "Payment", "Received", "Cash", "Out", "Send", "Money", "Transfer", "Bank", "Merchant", "Fee",
    "Charge", "Refund", "Bill", "Pay", "Paid", "Total", "Balance", "Opening", "Closing", "Due",
    "Sale", "Sales", "Purchase", "Return", "Rent", "Salary", "Advance", "Loan", "Deposit",
    "Withdrawal", "Mobile", "Recharge", "Add", "From", "The", "And", "For", "Eid", "Friday",
    "Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "January", "February",
    "March", "April", "May", "June", "July", "August", "September", "October", "November",
    "December", "Online", "Credit", "Debit", "Interest", "Charges", "Settlement", "Reversal",
)}


def review_words(cells: Iterable[str]) -> Counter[str]:
    """Words a human should look at: capitalised Latin words and Bangla words left in free text."""
    words: Counter[str] = Counter()
    for cell in cells:
        stripped = TRX_RE.sub(" ", TOKEN_RE.sub(" ", cell))
        words.update(w for w in _REVIEW_WORD.findall(stripped)
                     if w.casefold() not in _REVIEW_SKIP)
    return words


def residual_kinds(cells: Iterable[str], *, party_names: Iterable[str] = (),
                   shop_names: Iterable[str] = ()) -> Counter[str]:
    """Kinds still detectable after tokenising (tokens themselves are ignored). Empty = safe."""
    names, shops = tuple(party_names), tuple(shop_names)
    found: Counter[str] = Counter()
    for cell in cells:
        stripped = TRX_RE.sub(" ", TOKEN_RE.sub(" ", cell))
        found.update(d.kind.value for d in detect(stripped, party_names=names, shop_names=shops))
    return found


# ---------------------------------------------------------------- the run


@dataclass(frozen=True)
class Table:
    source: Path
    sheet: str
    header: list[str]
    body: list[list[str]]
    preamble_rows: int


def _load(path: Path) -> list[Table]:
    tables = []
    for sheet, rows in read_tables(path):
        h = find_header(rows)
        width = max((len(r) for r in rows), default=0)
        padded = [list(r) + [""] * (width - len(r)) for r in rows]
        body = [r for r in padded[h + 1:] if any(r)]
        tables.append(Table(path, sheet, padded[h] if padded else [], body, h))
    return tables


def _inside_git_repo(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def _load_or_create_key(home: Path) -> bytes:
    key_file = home / "shopfiles.key"
    if key_file.exists():
        return bytes.fromhex(key_file.read_text(encoding="ascii").strip())
    home.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(key.hex())
    return key


def run(input_dir: Path, shop: str, out_root: Path, home: Path,
        echo: Callable[[str], object] = print) -> dict[str, object]:
    """Anonymise every spreadsheet in `input_dir` into `out_root/<shop>/`; return the report."""
    input_dir, out_root, home = input_dir.resolve(), out_root.resolve(), home.resolve()
    if not SLUG_RE.fullmatch(shop):
        raise ShopfilesError("--shop must be 3-40 characters of a-z, 0-9 and '-', "
                             "with no real names (e.g. shop01-grocery)")
    if not input_dir.is_dir():
        raise ShopfilesError(f"not a folder: {input_dir}")
    if _inside_git_repo(input_dir):
        raise ShopfilesError("the raw files are inside a git repository; keep them in the "
                             "private Drive folder and point this tool there")
    if _inside_git_repo(home) or home == out_root or out_root in home.parents:
        raise ShopfilesError("the vault folder must be outside the repository")

    key = _load_or_create_key(home)
    engine = create_engine(f"sqlite:///{home / 'shopfiles_vault.sqlite'}")
    VaultEntry.metadata.create_all(engine, tables=[VaultEntry.__table__])

    files = sorted(p for p in input_dir.iterdir() if p.is_file())
    sheets = [p for p in files if p.suffix.lower() in SPREADSHEETS]
    skipped = Counter("image" if p.suffix.lower() in IMAGES else "other"
                      for p in files if p.suffix.lower() not in SPREADSHEETS
                      and p.name != "known_names.txt")
    known_file = input_dir / "known_names.txt"
    known = ([n.strip() for n in known_file.read_text(encoding="utf-8-sig").splitlines()
              if n.strip()] if known_file.exists() else [])

    tables = [t for p in sheets for t in _load(p)]
    roles = {id(t): [column_role(h, (r[i] for r in t.body)) for i, h in enumerate(t.header)]
             for t in tables}
    # Pass 1: every name in a name column of any file, so it is caught in free text anywhere.
    full_names = set(known)
    for t in tables:
        for i, role in enumerate(roles[id(t)]):
            if role is Role.NAME:
                full_names.update(r[i].strip() for r in t.body
                                  if r[i] and not to_ascii_digits(r[i])[:1].isdigit()
                                  and not is_generic_label(r[i]))
    # Shops and people are kept apart so "Bhai Bhai Corporation" gets the same SHOP token in a
    # name column and inside a bank description (the files stay joinable).
    shops_full = {n for n in full_names if SHOP_SUFFIX.search(n)}
    shop_names = {part for n in shops_full for part in name_and_parts(n)}
    party_names = {part for n in full_names - shops_full for part in name_and_parts(n)}

    out_dir = out_root / shop
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*out_dir.glob("file*.csv"), out_dir / "REPORT.json"]:
        stale.unlink(missing_ok=True)  # a re-run replaces the previous output completely
    report_files, refused = [], []
    review: Counter[str] = Counter()
    with Session(engine) as session:
        vault = TokenVault(key, entries=SqlVaultEntries(session))
        tok = ShopTokeniser(vault, f"real:{shop}", hashlib.sha256(key + b"trx").digest(),
                            party_names, shop_names)
        file_no = {p: n for n, p in enumerate(sheets, start=1)}
        sheet_no: Counter[Path] = Counter()
        for t in tables:
            sheet_no[t.source] += 1
            name = f"file{file_no[t.source]:02d}"
            if sheet_no[t.source] > 1:
                name += f"_sheet{sheet_no[t.source]}"
            counts: Counter[str] = Counter()
            header = [tok.free_cell(h, counts) for h in t.header]
            body = [[tok.cell(role, v, counts) for role, v in zip(roles[id(t)], row,
                                                                  strict=True)] for row in t.body]
            # KEPT columns passed the strict date/time/amount parser instead: a datetime such
            # as "2025-04-01 12:21" would read as a 10-digit number to the detectors.
            scanned = [c for row in body for c, role in zip(row, roles[id(t)], strict=True)
                       if role is not Role.KEPT]
            left = residual_kinds([*header, *scanned], party_names=party_names,
                                  shop_names=shop_names)
            entry = {
                "output": f"{name}.csv",
                "rows": len(body),
                "preamble_rows_dropped": t.preamble_rows,
                "columns": [{"header": h, "role": r.value}
                            for h, r in zip(header, roles[id(t)], strict=True)],
                "tokenised": dict(sorted(counts.items())),
                "verified": not left,
            }
            sheet_label = f" [{t.sheet}]" if t.sheet else ""
            if left:
                entry["refused_kinds"] = dict(sorted(left.items()))
                refused.append(entry["output"])
                echo(f"REFUSED {t.source.name}{sheet_label}: still contains "
                     f"{', '.join(f'{k} x{n}' for k, n in sorted(left.items()))}; not written")
            else:
                buffer = io.StringIO()
                writer = csv.writer(buffer, lineterminator="\n")
                mode_cols = [i for i, h in enumerate(header)
                             if re.sub(r"[\s_]+", "_", h.casefold()) == "data_mode"]
                if mode_cols:  # the file already has a data-mode column: overwrite it
                    writer.writerow(header)
                    writer.writerows([DATA_MODE if i in mode_cols else c
                                      for i, c in enumerate(row)] for row in body)
                else:
                    writer.writerow([*header, "data_mode"])
                    writer.writerows([*row, DATA_MODE] for row in body)
                (out_dir / entry["output"]).write_text(buffer.getvalue(), encoding="utf-8")
                echo(f"{t.source.name}{sheet_label} -> {out_dir.name}/{entry['output']} "
                     f"({len(body)} rows, {sum(counts.values())} values tokenised)")
                review.update(review_words(
                    c for row in body for c, role in zip(row, roles[id(t)], strict=True)
                    if role is Role.FREE))
            report_files.append(entry)
        session.commit()

    report = {
        "shop": shop,
        "data_mode": DATA_MODE,
        "tool": f"app.privacy.shopfiles v{TOOL_VERSION}",
        "generated_on": dt.datetime.now(DHAKA).date().isoformat(),
        "files": report_files,
        "refused": refused,
        "skipped_files": dict(sorted(skipped.items())),
        "known_names_listed": len(known),
        "words_left_for_review": len(review),
        "note": "Counts and column roles only; no original values. Originals are encrypted in "
                "the local vault outside git.",
    }
    (out_dir / "REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    if skipped.get("image"):
        echo(f"Skipped {skipped['image']} image/PDF file(s): type baki pages into a sheet "
             "first; photos never go into the repo.")
    if review:
        # Console only, never a file: names nobody listed cannot be detected, so a human checks.
        echo("Words left in free-text columns. If any is a person's or shop's name, add it to "
             "known_names.txt in the raw folder and run again:")
        echo("  " + ", ".join(w for w, _ in review.most_common(80)))
    return report


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.privacy.shopfiles",
        description="Anonymise a shop's raw CSV/XLSX files into data/real_anonymised/<shop>/.")
    parser.add_argument("input_dir", type=Path, help="folder with the raw files (outside git)")
    parser.add_argument("--shop", required=True, help="neutral id, e.g. shop01-grocery")
    parser.add_argument("--out", type=Path, default=_repo_root() / "data" / "real_anonymised",
                        help="output root (default: the repo's data/real_anonymised)")
    parser.add_argument("--home", type=Path, default=Path.home() / ".hishab",
                        help="where the vault and its key live (default: ~/.hishab)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Bangla in a cp1252 Windows pipe must not crash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        report = run(args.input_dir, args.shop, args.out, args.home)
    except ShopfilesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    written = sum(1 for f in report["files"] if f["verified"])  # type: ignore[union-attr]
    print(f"Done: {written} file(s) written, {len(report['refused'])} refused. "  # type: ignore[arg-type]
          f"Open REPORT.json and the CSVs and check them by eye before committing.")
    return 1 if report["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
