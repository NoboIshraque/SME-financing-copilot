"""Normalise amounts, dates and text from Bangladeshi records (WP-02).

Every function is pure. When a value cannot be read with certainty it raises `NormaliseError`
carrying an i18n reason key; callers turn that into an `UnparsedRow`, never into a guess.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

DHAKA = ZoneInfo("Asia/Dhaka")
BANGLA_DIGITS = "০১২৩৪৫৬৭৮৯"
_TO_ASCII = str.maketrans(BANGLA_DIGITS, "0123456789")
# Zero-width characters that only affect rendering (ZWNJ/ZWJ matter for display, not meaning).
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


class NormaliseError(ValueError):
    def __init__(self, reason_key: str, value: str = "") -> None:
        super().__init__(f"{reason_key}: {value[:60]!r}")
        self.reason_key = reason_key


def ascii_digits(text: str) -> str:
    """Bangla digits (০-৯) to ASCII; everything else unchanged."""
    return text.translate(_TO_ASCII)


def clean_text(text: str) -> str:
    """NFC-normalised, invisible characters removed, whitespace collapsed."""
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    return " ".join(text.split())


def header_key(text: str) -> str:
    """Canonical form of a column header: 'Amount (BDT)' -> 'amount bdt', 'Cheque/Ref No' ->
    'cheque ref no'. Bangla letters and digits are kept."""
    text = clean_text(ascii_digits(text)).casefold()
    return " ".join(re.sub(r"[^\wঀ-৿]+|_", " ", text).split())


# ---------------------------------------------------------------- amounts

_CURRENCY = re.compile(r"(?i)৳|টাকা|\btaka\b|bdt|tk\.?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_DRCR = re.compile(r"(?i)\s*\b(dr|cr)\.?\s*$")


def split_drcr(text: str) -> tuple[str, str | None]:
    """'12,000.00 Cr' -> ('12,000.00', 'cr'). Used for balances and signed amount columns."""
    match = _DRCR.search(text)
    if match is None:
        return text, None
    return text[: match.start()], match.group(1).lower()


def parse_amount(text: str) -> Decimal:
    """Read an amount written the way Bangladeshi records write it.

    Accepts Bangla digits, Tk/৳/BDT/টাকা markers, lakh grouping ('1,25,000'), the '/-' and '/='
    suffixes, a leading minus (ASCII or Unicode) and accounting parentheses for negatives.
    """
    s = clean_text(ascii_digits(text))
    if not s:
        raise NormaliseError("ingest.amount.missing", text)
    s = s.replace("−", "-").replace("–", "-")
    s = _CURRENCY.sub("", s)
    s = re.sub(r"/[-=]\s*$", "", s).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.startswith(("-", "+")):
        negative, s = negative != (s[0] == "-"), s[1:].strip()
    s = s.replace(",", "").replace(" ", "").replace(" ", "")
    if not _NUMBER.fullmatch(s):
        raise NormaliseError("ingest.amount.invalid", text)
    try:
        value = Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - the regex already guarantees a number
        raise NormaliseError("ingest.amount.invalid", text) from exc
    return -value if negative else value


# ---------------------------------------------------------------- dates

MONTHS: dict[str, int] = {}


def _add_months(names_by_month: list[tuple[str, ...]]) -> None:
    for number, names in enumerate(names_by_month, start=1):
        for name in names:
            MONTHS[header_key(name)] = number


_add_months([
    ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",),
    ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"),
    ("october", "oct"), ("november", "nov"), ("december", "dec"),
])

_TIME = (r"(?P<h>\d{1,2})[:.](?P<mi>\d{2})(?:[:.](?P<s>\d{2})(?:\.\d+)?)?"
         r"\s*(?P<ampm>[ap]\.?\s?m\.?)?")
_ISO = re.compile(
    r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})(?:[ T]" + _TIME + r")?"
    r"\s*(?P<tz>z|[+-]\d{2}:?\d{2})?$", re.IGNORECASE)
_NUMERIC = re.compile(
    r"^(?P<a>\d{1,2})[/.\-](?P<b>\d{1,2})[/.\-](?P<y>\d{4}|\d{2})(?:[ ,T]+" + _TIME + r")?$",
    re.IGNORECASE)
_YMD_SLASH = re.compile(
    r"^(?P<y>\d{4})[/.](?P<m>\d{1,2})[/.](?P<d>\d{1,2})(?:[ ,T]+" + _TIME + r")?$", re.IGNORECASE)
_DAY_MONTH_NAME = re.compile(
    r"^(?P<d>\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*(?P<mon>[^\W\d_]+)\.?[\s\-/.,]*(?P<y>\d{4}|\d{2})"
    r"(?:[ ,T]+" + _TIME + r")?$", re.IGNORECASE)
_MONTH_NAME_DAY = re.compile(
    r"^(?P<mon>[^\W\d_]+)\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})"
    r"(?:[ ,T]+" + _TIME + r")?$", re.IGNORECASE)


@dataclass(frozen=True)
class When:
    """A parsed local (Asia/Dhaka) timestamp."""

    at: datetime  # naive, Asia/Dhaka wall time
    has_time: bool
    ambiguous: bool = False  # day and month could have been swapped

    def aware(self) -> datetime:
        return self.at.replace(tzinfo=DHAKA)


def _year(text: str) -> int:
    value = int(text)
    return 2000 + value if len(text) == 2 else value


def _clock(match: re.Match[str]) -> tuple[time, bool]:
    if match.group("h") is None:
        return time(0, 0), False
    hour, minute = int(match.group("h")), int(match.group("mi"))
    second = int(match.group("s") or 0)
    ampm = (match.group("ampm") or "").replace(".", "").replace(" ", "").lower()
    if ampm:
        if not 1 <= hour <= 12:
            raise NormaliseError("ingest.date.invalid_time", match.group(0))
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    try:
        return time(hour, minute, second), True
    except ValueError as exc:
        raise NormaliseError("ingest.date.invalid_time", match.group(0)) from exc


def _make(y: int, m: int, d: int, match: re.Match[str], ambiguous: bool = False) -> When:
    try:
        day = date(y, m, d)
    except ValueError as exc:
        raise NormaliseError("ingest.date.invalid", match.group(0)) from exc
    clock, has_time = _clock(match)
    return When(at=datetime.combine(day, clock), has_time=has_time, ambiguous=ambiguous)


def month_number(name: str) -> int | None:
    return MONTHS.get(header_key(name))


def numeric_parts(text: str) -> tuple[int, int] | None:
    """The first two numbers of a d/m/y or m/d/y date, for day-first inference."""
    match = _NUMERIC.match(clean_text(ascii_digits(text)))
    return (int(match.group("a")), int(match.group("b"))) if match else None


def parse_when(text: str, day_first: bool = True) -> When:
    """Parse a date or date-time. `day_first` decides only genuinely ambiguous numeric dates
    such as 03/04/2025; 13/04/2025 and 04/13/2025 are read the only way they can be."""
    s = clean_text(ascii_digits(text))
    if not s:
        raise NormaliseError("ingest.date.missing", text)
    if match := _ISO.match(s):
        when = _make(int(match["y"]), int(match["m"]), int(match["d"]), match)
        tz = match["tz"]
        if tz and when.has_time:
            offset = timedelta(0) if tz.lower() == "z" else timedelta(
                hours=int(tz[1:3]), minutes=int(tz[-2:])) * (1 if tz[0] == "+" else -1)
            local = (when.at - offset).replace(tzinfo=ZoneInfo("UTC")).astimezone(DHAKA)
            when = When(at=local.replace(tzinfo=None), has_time=True)
        return when
    if match := _YMD_SLASH.match(s):
        return _make(int(match["y"]), int(match["m"]), int(match["d"]), match)
    if match := _NUMERIC.match(s):
        a, b, y = int(match["a"]), int(match["b"]), _year(match["y"])
        if a > 12 and b > 12:
            raise NormaliseError("ingest.date.invalid", text)
        if a > 12:
            return _make(y, b, a, match)
        if b > 12:
            return _make(y, a, b, match)
        ambiguous = a != b
        return _make(y, b, a, match, ambiguous) if day_first else _make(y, a, b, match, ambiguous)
    for pattern in (_DAY_MONTH_NAME, _MONTH_NAME_DAY):
        if match := pattern.match(s):
            month = month_number(match["mon"])
            if month is None:
                raise NormaliseError("ingest.date.unknown_month", text)
            return _make(_year(match["y"]), month, int(match["d"]), match)
    raise NormaliseError("ingest.date.invalid", text)


def infer_day_first(values: list[str], default: bool = True) -> bool:
    """Decide d/m vs m/d for a whole column: a value whose first number exceeds 12 proves
    day-first, one whose second number does proves month-first. Conflicting evidence or none
    at all falls back to `default` (day-first is the Bangladeshi convention)."""
    day_first_seen = month_first_seen = False
    for value in values:
        parts = numeric_parts(value)
        if parts is None:
            continue
        a, b = parts
        day_first_seen |= a > 12 >= b
        month_first_seen |= b > 12 >= a
    if day_first_seen != month_first_seen:
        return day_first_seen
    return default
