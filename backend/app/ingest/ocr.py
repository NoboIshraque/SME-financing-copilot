"""Baki-khata photo OCR -> drafts the owner confirms row by row (WP-02 milestone 3).

The photo never leaves the server: OCR runs on local Tesseract with Bangla and English
(`ben+eng`). Each recognised line is read for a name, an amount and, when written, a date, and
becomes a *draft*: an invoice for credit given (baki), or a collection when the line notes a
payment (জমা, পরিশোধ, aday). Every draft carries a confidence: the OCR engine's certainty times
how completely the line could be read. Low-confidence drafts are flagged. No draft is ever
committed on its own; the owner confirms each one (see `app.ingest.preview`).
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from app.contracts import (
    Channel,
    Direction,
    DocumentStatus,
    DraftRow,
    Invoice,
    Money,
    SourceFormat,
    Transaction,
    TxCategory,
    UnparsedRow,
)
from app.ingest.normalise import (
    BENGALI_MONTHS,
    DHAKA,
    MONTHS,
    NormaliseError,
    ascii_digits,
    bengali_to_gregorian,
    clean_text,
    header_key,
    parse_amount,
)
from app.ingest.parsers import SUMMARY_WORDS, IngestOptions, ParseResult
from app.ingest.parties import PartyResolver, identifiers, mask_excerpt

FLAG_BELOW = Decimal("0.80")
_HUNDREDTH = Decimal("0.01")
PAYMENT_WORDS = frozenset(header_key(w) for w in (
    "জমা", "পরিশোধ", "আদায়", "দিলো", "দিল", "joma", "jama", "porishodh", "aday", "adai",
    "paid", "payment", "received",
))
# Goods written after a customer's name ("রহিম চাল ১২০০"): the name stops before them.
ITEM_WORDS = frozenset(header_key(w) for w in (
    "চাল", "ডাল", "তেল", "চিনি", "আটা", "ময়দা", "লবণ", "সাবান", "ডিম", "দুধ", "মাল", "বাকি",
    "chal", "dal", "tel", "chini", "ata", "moyda", "lobon", "saban", "dim", "dudh", "mal",
    "baki", "rice", "oil", "sugar", "flour", "salt", "soap", "eggs", "milk", "goods",
))
CURRENCY_WORDS = frozenset(header_key(w) for w in ("টাকা", "taka", "tk", "bdt", "৳"))
_NUMERIC_DATE = re.compile(r"(?<![\d.,])(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{4}|\d{2}))?(?![\d,])")
_NAMED_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th|লা|রা|ঠা|ই|শে)?\s*([a-zঀ-৿]+)\.?(?:\s+(\d{4}))?",
    re.IGNORECASE)
_AMOUNT = re.compile(
    r"(?P<pre>৳\s*|tk\.?\s*|bdt\s*)?(?P<num>\d[\d,]*(?:\.\d{1,2})?)"
    r"(?P<post>\s*(?:/-|/=|টাকা|taka|tk\b))?", re.IGNORECASE)


class OcrUnavailable(RuntimeError):
    """Local OCR is not installed (Tesseract with the `ben` and `eng` languages)."""


@dataclass(frozen=True)
class OcrLine:
    number: int  # 1-based, in reading order
    text: str
    confidence: Decimal  # 0..1, from the OCR engine


class OcrEngine(Protocol):
    def read_lines(self, image: bytes) -> list[OcrLine]: ...


def lines_from_tesseract(data: Mapping[str, Sequence[object]]) -> list[OcrLine]:
    """Group `pytesseract.image_to_data(..., output_type=DICT)` words into lines. Entries with
    confidence -1 (layout boxes) or no text are ignored; a line's confidence is the mean of
    its words' confidences."""
    groups: dict[tuple[int, int, int, int], list[tuple[str, float]]] = {}
    for i, raw in enumerate(data["text"]):
        text, conf = str(raw).strip(), float(str(data["conf"][i]))
        if not text or conf < 0:
            continue
        key = tuple(int(str(data[k][i])) for k in ("page_num", "block_num", "par_num",
                                                    "line_num"))
        groups.setdefault(key, []).append((text, conf))  # type: ignore[arg-type]
    lines = []
    for number, key in enumerate(sorted(groups), start=1):
        words = groups[key]
        mean = Decimal(str(sum(c for _t, c in words) / len(words))) / 100
        lines.append(OcrLine(number, " ".join(t for t, _c in words),
                             min(mean, Decimal(1)).quantize(Decimal("0.0001"))))
    return lines


class TesseractEngine:
    """Local Tesseract through pytesseract. Images are cleaned up first: EXIF rotation,
    grayscale, auto-contrast, and upscaling of small photos (Bangla needs pixels)."""

    def __init__(self, lang: str = "ben+eng", psm: int = 6, min_width: int = 1600) -> None:
        self.lang, self.psm, self.min_width = lang, psm, min_width

    @staticmethod
    def available(lang: str = "ben+eng") -> bool:
        if shutil.which("tesseract") is None:
            return False
        try:
            import pytesseract

            installed = set(pytesseract.get_languages(config=""))
        except Exception:  # noqa: BLE001 - any failure means "not usable here"
            return False
        return all(code in installed for code in lang.split("+"))

    def read_lines(self, image: bytes) -> list[OcrLine]:
        import pytesseract
        from PIL import Image, ImageOps, UnidentifiedImageError

        try:
            picture = Image.open(io.BytesIO(image))
            picture.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise NormaliseError("ingest.photo.unreadable") from exc
        picture = ImageOps.autocontrast(ImageOps.exif_transpose(picture).convert("L"))
        if picture.width < self.min_width:
            ratio = self.min_width / picture.width
            picture = picture.resize((self.min_width, round(picture.height * ratio)))
        try:
            data = pytesseract.image_to_data(picture, lang=self.lang,
                                             config=f"--psm {self.psm}",
                                             output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailable("tesseract is not installed") from exc
        return lines_from_tesseract(data)


# ---------------------------------------------------------------- reading one line


@dataclass(frozen=True)
class KhataLine:
    """What one ledger line says, before tokens and contracts."""

    name: str
    amount: Decimal
    day: date
    payment: bool
    certainty: Decimal  # how completely the line could be read, 0..1


def _find_date(text: str, reference: date) -> tuple[date | None, Decimal, tuple[int, int]]:
    """(date, certainty penalty, span) for the first date written on the line."""
    for match in _NUMERIC_DATE.finditer(text):
        a, b, year_text = int(match[1]), int(match[2]), match[3]
        year = (2000 + int(year_text) if year_text and len(year_text) == 2 else
                int(year_text) if year_text else reference.year)
        day_, month_ = (a, b) if a > 12 or b <= 12 else (b, a)  # Bangladeshi day-first
        try:
            found = date(year, month_, day_)
        except ValueError:
            continue
        penalty = Decimal("0.15") if a <= 12 and b <= 12 and a != b else Decimal(0)
        if not year_text:
            penalty += Decimal("0.05")
        return found, penalty, match.span()
    for match in _NAMED_DATE.finditer(text):
        key = header_key(match[2])
        day_ = int(match[1])
        try:
            if key in BENGALI_MONTHS:
                if not match[3]:
                    continue  # a Bangabda date needs its year to be converted safely
                found = bengali_to_gregorian(day_, BENGALI_MONTHS[key], int(match[3]))
                return found, Decimal(0), match.span()
            if key in MONTHS:
                year = int(match[3]) if match[3] else reference.year
                penalty = Decimal(0) if match[3] else Decimal("0.05")
                return date(year, MONTHS[key], day_), penalty, match.span()
        except (ValueError, NormaliseError):
            continue
    return None, Decimal(0), (0, 0)


def read_khata_line(text: str, reference: date) -> KhataLine:
    """Read a baki-khata line such as '০৫/১০ রহিম চাল ১,২৫০' or 'Karim joma 500/-'."""
    line = clean_text(ascii_digits(text))
    key = header_key(line)
    if any(key == w or key.startswith(w + " ") for w in SUMMARY_WORDS):
        raise NormaliseError("ingest.row.summary", text)
    day, penalty, (start, end) = _find_date(line, reference)
    certainty = Decimal(1) - penalty
    if day is None:
        day, certainty = reference, certainty - Decimal("0.25")
    rest = line[:start] + " " + line[end:]
    candidates = list(_AMOUNT.finditer(rest))
    if not candidates:
        raise NormaliseError("ingest.ocr.no_amount", text)
    marked = [c for c in candidates if c["pre"] or c["post"]]
    chosen = marked[-1] if len(marked) == 1 else candidates[-1]
    if len(candidates) > 1 and len(marked) != 1:
        certainty -= Decimal("0.20")  # a quantity and a price, or two prices
    amount = parse_amount(chosen.group(0))
    if amount <= 0 or amount != amount.quantize(_HUNDREDTH):
        raise NormaliseError("ingest.ocr.no_amount", text)
    words = [w for w in re.sub(r"[^\wঀ-৿ ]+", " ",
                               rest[:chosen.start()] + " " + rest[chosen.end():]).split()
             if not any(ch.isdigit() for ch in w) and header_key(w) not in CURRENCY_WORDS]
    payment = any(header_key(w) in PAYMENT_WORDS for w in words)
    name_words: list[str] = []
    for word in words:
        if header_key(word) in PAYMENT_WORDS:
            continue
        if header_key(word) in ITEM_WORDS or len(name_words) == 3:
            break
        name_words.append(word)
    name = " ".join(name_words)
    if sum(ch.isalpha() for ch in name) < 2:
        raise NormaliseError("ingest.ocr.no_name", text)
    return KhataLine(name=name, amount=amount, day=day, payment=payment,
                     certainty=max(certainty, Decimal(0)))


# ---------------------------------------------------------------- lines -> drafts


def parse_khata_lines(lines: Sequence[OcrLine], opts: IngestOptions, resolver: PartyResolver,
                      *, photo_id: str, reference: date) -> ParseResult:
    """Drafts for every readable line, unparsed rows (masked) for the rest."""
    result = ParseResult(source_format=SourceFormat.ledger_photo, default_mode=opts.data_mode)
    result.modes.add(opts.data_mode)
    read: list[tuple[OcrLine, KhataLine]] = []
    for line in lines:
        ref = f"{opts.filename}#line{line.number}"
        try:
            read.append((line, read_khata_line(line.text, reference)))
        except NormaliseError as exc:
            result.unparsed.append(UnparsedRow(row_ref=ref, reason_key=exc.reason_key,
                                               raw_excerpt=mask_excerpt(line.text)))
    tokens = resolver.resolve_many(opts.tenant_id, [identifiers(k.name) for _l, k in read])
    for (line, khata), token in zip(read, tokens, strict=True):
        ref = f"{opts.filename}#line{line.number}"
        record_id = f"{opts.tenant_id}:photo-{photo_id}-L{line.number}"
        confidence = (line.confidence * khata.certainty).quantize(_HUNDREDTH, ROUND_HALF_UP)
        flagged = confidence < FLAG_BELOW
        if khata.payment:
            draft = DraftRow(row_ref=ref, confidence=confidence, flagged=flagged,
                             transaction=Transaction(
                                 id=record_id, tenant_id=opts.tenant_id,
                                 occurred_at=datetime.combine(khata.day, time(0), DHAKA),
                                 amount=Money.of(khata.amount), direction=Direction.inflow,
                                 channel=Channel.cash, category=TxCategory.collection,
                                 counterparty_token=token, source_ref=ref,
                                 data_mode=opts.data_mode))
        else:
            draft = DraftRow(row_ref=ref, confidence=confidence, flagged=flagged,
                             invoice=Invoice(
                                 id=record_id, tenant_id=opts.tenant_id,
                                 counterparty_token=token or "PARTY_unknown",
                                 issue_date=khata.day, due_date=khata.day,
                                 amount=Money.of(khata.amount), amount_paid=Money.zero(),
                                 status=DocumentStatus.open, source_ref=ref,
                                 data_mode=opts.data_mode))
        result.drafts.append(draft)
    return result


def photo_id(image: bytes) -> str:
    return hashlib.sha256(image).hexdigest()[:10]


def drafts_from_photo(image: bytes, opts: IngestOptions, resolver: PartyResolver,
                      engine: OcrEngine, reference: date) -> ParseResult:
    """OCR a ledger photo and turn its lines into drafts (nothing is committed here)."""
    try:
        lines = engine.read_lines(image)
    except NormaliseError as exc:
        result = ParseResult(source_format=SourceFormat.ledger_photo,
                             default_mode=opts.data_mode)
        result.unparsed.append(UnparsedRow(row_ref=opts.filename, reason_key=exc.reason_key,
                                           raw_excerpt=""))
        return result
    return parse_khata_lines(lines, opts, resolver, photo_id=photo_id(image),
                             reference=reference)
