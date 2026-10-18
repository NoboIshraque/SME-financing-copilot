"""Normalise amounts, dates and text from Bangladeshi records (WP-02).

Every function is pure. When a value cannot be read with certainty it raises `NormaliseError`
carrying an i18n reason key; callers turn that into an `UnparsedRow` (or a draft the owner
confirms), never into a guess.

Covered: Bangla digits (০-৯); Tk/৳/BDT/টাকা markers, lakh grouping and লাখ/কোটি/হাজার words;
Gregorian month names in English, Bangla and Banglish; Bengali (Bangabda) calendar dates under
the revised Bangladesh calendar; Bangla times of day (সকাল, দুপুর, বিকাল, সন্ধ্যা, রাত);
day/month order decided per file by evidence, then by chronology.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
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
    """Canonical form of a column header or label: 'Amount (BDT)' -> 'amount bdt',
    'Cheque/Ref No' -> 'cheque ref no', 'issue_date' -> 'issue date'. Bangla is kept."""
    text = clean_text(ascii_digits(text)).casefold()
    return " ".join(re.sub(r"[^\wঀ-৿]+|_", " ", text).split())


# ---------------------------------------------------------------- amounts

_CURRENCY = re.compile(r"(?i)৳|টাকা|\btaka\b|bdt|tk\.?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_WITH_WORD = re.compile(r"^(?P<n>\d+(?:\.\d+)?|\.\d+)\s*(?P<w>[a-zঀ-৿]+)$", re.I)
_DRCR = re.compile(r"(?i)\s*\b(dr|cr)\.?\s*$")
MULTIPLIERS: dict[str, int] = {header_key(k): v for k, v in {
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "লাখ": 100_000,
    "লক্ষ": 100_000, "crore": 10_000_000, "crores": 10_000_000, "koti": 10_000_000,
    "কোটি": 10_000_000, "hazar": 1_000, "hajar": 1_000, "thousand": 1_000, "হাজার": 1_000,
    "k": 1_000,
}.items()}


def split_drcr(text: str) -> tuple[str, str | None]:
    """'12,000.00 Cr' -> ('12,000.00', 'cr'). Used for balances and signed amount columns."""
    match = _DRCR.search(text)
    if match is None:
        return text, None
    return text[: match.start()], match.group(1).lower()


def parse_amount(text: str) -> Decimal:
    """Read an amount written the way Bangladeshi records write it.

    Accepts Bangla digits, Tk/৳/BDT/টাকা markers, lakh grouping ('1,25,000'), the '/-' and '/='
    suffixes, a leading minus (ASCII or Unicode), accounting parentheses for negatives, and a
    trailing lakh/crore/hazar word ('১.৫ লাখ' = 150000).
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
    s = s.replace(",", "").replace(" ", " ").strip()
    multiplier = 1
    if (worded := _WITH_WORD.match(s)) is not None:
        found = MULTIPLIERS.get(header_key(worded["w"]))
        if found is None:
            raise NormaliseError("ingest.amount.invalid", text)
        s, multiplier = worded["n"], found
    s = s.replace(" ", "")
    if not _NUMBER.fullmatch(s):
        raise NormaliseError("ingest.amount.invalid", text)
    try:
        value = Decimal(s) * multiplier
    except InvalidOperation as exc:  # pragma: no cover - the regex already guarantees a number
        raise NormaliseError("ingest.amount.invalid", text) from exc
    return -value if negative else value


# ---------------------------------------------------------------- calendars

MONTHS: dict[str, int] = {}
BENGALI_MONTHS: dict[str, int] = {}


def _table(target: dict[str, int], names_by_month: list[tuple[str, ...]]) -> None:
    for number, names in enumerate(names_by_month, start=1):
        for name in names:
            target[header_key(name)] = number


_table(MONTHS, [
    ("january", "jan", "januari", "janu", "জানুয়ারি", "জানুয়ারী", "জানু"),
    ("february", "feb", "februari", "febru", "ফেব্রুয়ারি", "ফেব্রুয়ারী", "ফেব্রু"),
    ("march", "mar", "marc", "মার্চ"),
    ("april", "apr", "epril", "এপ্রিল"),
    ("may", "মে"),
    ("june", "jun", "জুন"),
    ("july", "jul", "julai", "জুলাই"),
    ("august", "aug", "agust", "agost", "আগস্ট", "আগষ্ট"),
    ("september", "sep", "sept", "septembor", "সেপ্টেম্বর", "সেপ্টে"),
    ("october", "oct", "oktobor", "অক্টোবর", "অক্টো"),
    ("november", "nov", "nobhembor", "নভেম্বর", "নভে"),
    ("december", "dec", "disembor", "ডিসেম্বর", "ডিসে"),
])
_table(BENGALI_MONTHS, [
    ("বৈশাখ", "boishakh", "baishakh", "boisakh", "baisakh"),
    ("জ্যৈষ্ঠ", "জৈষ্ঠ", "joishtho", "jyoishtho", "jaishtha", "jaistha", "jyaistha"),
    ("আষাঢ়", "asharh", "ashar", "asar", "asadh"),
    ("শ্রাবণ", "srabon", "shrabon", "sraban", "shraban"),
    ("ভাদ্র", "bhadro", "bhadra", "vadro"),
    ("আশ্বিন", "ashwin", "ashshin", "asshin", "aswin"),
    ("কার্তিক", "kartik", "kartic"),
    ("অগ্রহায়ণ", "ogrohayon", "agrahayan", "ograhayan", "agrahayon", "ogrohayan"),
    ("পৌষ", "poush", "paush", "pous"),
    ("মাঘ", "magh"),
    ("ফাল্গুন", "falgun", "phalgun", "falgoon"),
    ("চৈত্র", "choitro", "chaitra", "choitra", "chaitro"),
])


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def bengali_to_gregorian(day: int, month: int, year: int) -> date:
    """Convert a Bangabda date under the revised Bangladesh calendar (Bangla Academy, in force
    since 1426 / 2019): 1 Boishakh is 14 April; Boishakh to Ashwin have 31 days, Kartik to Magh
    and Choitro 30, Falgun 29, or 30 when its Gregorian year is a leap year. This keeps
    21 February on 8 Falgun, 26 March on 12 Choitro and 16 December on 1 Poush."""
    if not 1300 <= year <= 1600:
        raise NormaliseError("ingest.date.calendar_mismatch", f"{day}/{month}/{year}")
    lengths = [31] * 6 + [30] * 4 + [30 if is_leap(year + 594) else 29, 30]
    if not 1 <= month <= 12 or not 1 <= day <= lengths[month - 1]:
        raise NormaliseError("ingest.date.invalid", f"{day}/{month}/{year}")
    return date(year + 593, 4, 14) + timedelta(days=sum(lengths[: month - 1]) + day - 1)


# ---------------------------------------------------------------- dates and times

# Bangla/Banglish words for the part of the day, as written next to a clock time.
PERIOD_WORDS: dict[str, str] = {header_key(k): v for k, v in {
    "সকাল": "am", "সকালে": "am", "ভোর": "am", "ভোরে": "am", "sokal": "am", "shokal": "am",
    "bhor": "am", "দুপুর": "noon", "দুপুরে": "noon", "dupur": "noon", "বিকাল": "pm",
    "বিকালে": "pm", "বিকেল": "pm", "বিকেলে": "pm", "bikal": "pm", "bikel": "pm",
    "সন্ধ্যা": "pm", "সন্ধ্যায়": "pm", "sondha": "pm", "shondha": "pm", "রাত": "night",
    "রাতে": "night", "raat": "night", "rat": "night",
}.items()}
_O_CLOCK = re.compile(r"(?<!\d)(\d{1,2})\s*টা(?:য়)?(?!\w)")
_TIME = (r"(?P<h>\d{1,2})[:.](?P<mi>\d{2})(?:[:.](?P<s>\d{2})(?:\.\d+)?)?"
         r"\s*(?P<ampm>[ap]\.?\s?m\.?)?")
_MON = r"(?P<mon>[a-zঀ-৿]+)"
_ORDINAL = r"(?:st|nd|rd|th|লা|রা|ঠা|ই|শে|তম)?"
_ISO = re.compile(
    r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})(?:[ T]" + _TIME + r")?"
    r"\s*(?P<tz>z|[+-]\d{2}:?\d{2})?$", re.IGNORECASE)
_NUMERIC = re.compile(
    r"^(?P<a>\d{1,2})[/.\-](?P<b>\d{1,2})[/.\-](?P<y>\d{4}|\d{2})(?:[ ,T]+" + _TIME + r")?$",
    re.IGNORECASE)
_YMD_SLASH = re.compile(
    r"^(?P<y>\d{4})[/.](?P<m>\d{1,2})[/.](?P<d>\d{1,2})(?:[ ,T]+" + _TIME + r")?$", re.IGNORECASE)
_DAY_MONTH_NAME = re.compile(
    r"^(?P<d>\d{1,2})" + _ORDINAL + r"[\s\-/.,]*" + _MON + r"\.?[\s\-/.,]*(?P<y>\d{4}|\d{2})"
    r"(?:[ ,T]+" + _TIME + r")?$", re.IGNORECASE)
_MONTH_NAME_DAY = re.compile(
    r"^" + _MON + r"\.?\s+(?P<d>\d{1,2})" + _ORDINAL + r",?\s+(?P<y>\d{4})"
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


def _clock(match: re.Match[str], period: str | None) -> tuple[time, bool]:
    if match.group("h") is None:
        return time(0, 0), False
    hour, minute = int(match.group("h")), int(match.group("mi"))
    second = int(match.group("s") or 0)
    ampm = (match.group("ampm") or "").replace(".", "").replace(" ", "").lower()
    if ampm:
        if not 1 <= hour <= 12:
            raise NormaliseError("ingest.date.invalid_time", match.group(0))
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    elif period == "am" and hour == 12:
        hour = 0
    elif period == "pm" and 1 <= hour <= 11:
        hour += 12  # বিকাল ৪টা is 16:00; a 24-hour time next to the word is kept as written
    elif period == "noon" and 1 <= hour <= 5:
        hour += 12  # দুপুর ১টা is 13:00
    elif period == "night" and 6 <= hour <= 11:
        hour += 12  # রাত ৯টা is 21:00; রাত ১টা stays 01:00
    elif period == "night" and hour == 12:
        hour = 0
    try:
        return time(hour, minute, second), True
    except ValueError as exc:
        raise NormaliseError("ingest.date.invalid_time", match.group(0)) from exc


def _make(y: int, m: int, d: int, match: re.Match[str], period: str | None,
          ambiguous: bool = False) -> When:
    try:
        day = date(y, m, d)
    except ValueError as exc:
        raise NormaliseError("ingest.date.invalid", match.group(0)) from exc
    clock, has_time = _clock(match, period)
    return When(at=datetime.combine(day, clock), has_time=has_time, ambiguous=ambiguous)


def month_number(name: str) -> int | None:
    return MONTHS.get(header_key(name))


def _split_period(text: str) -> tuple[str, str | None]:
    """Remove a part-of-day word ('রাত ৯টা' -> '9:00', 'night') and o'clock suffixes."""
    words, period = [], None
    for word in text.split():
        found = PERIOD_WORDS.get(header_key(word))
        if found is not None and period is None:
            period = found
        else:
            words.append(word)
    return _O_CLOCK.sub(r"\1:00", " ".join(words)), period


def numeric_parts(text: str) -> tuple[int, int] | None:
    """The first two numbers of a d/m/y or m/d/y date, for day-first inference."""
    match = _NUMERIC.match(clean_text(ascii_digits(text)))
    return (int(match.group("a")), int(match.group("b"))) if match else None


def parse_when(text: str, day_first: bool = True) -> When:
    """Parse a date or date-time. `day_first` decides only genuinely ambiguous numeric dates
    such as 03/04/2025; 13/04/2025 and 04/13/2025 are read the only way they can be."""
    s, period = _split_period(clean_text(ascii_digits(text)))
    if not s:
        raise NormaliseError("ingest.date.missing", text)
    if match := _ISO.match(s):
        when = _make(int(match["y"]), int(match["m"]), int(match["d"]), match, period)
        tz = match["tz"]
        if tz and when.has_time:
            offset = timedelta(0) if tz.lower() == "z" else timedelta(
                hours=int(tz[1:3]), minutes=int(tz[-2:])) * (1 if tz[0] == "+" else -1)
            local = (when.at - offset).replace(tzinfo=ZoneInfo("UTC")).astimezone(DHAKA)
            when = When(at=local.replace(tzinfo=None), has_time=True)
        return when
    if match := _YMD_SLASH.match(s):
        return _make(int(match["y"]), int(match["m"]), int(match["d"]), match, period)
    if match := _NUMERIC.match(s):
        a, b, y = int(match["a"]), int(match["b"]), _year(match["y"])
        if a > 12 and b > 12:
            raise NormaliseError("ingest.date.invalid", text)
        if a > 12:
            return _make(y, b, a, match, period)
        if b > 12:
            return _make(y, a, b, match, period)
        ambiguous = a != b
        if day_first:
            return _make(y, b, a, match, period, ambiguous)
        return _make(y, a, b, match, period, ambiguous)
    for pattern in (_DAY_MONTH_NAME, _MONTH_NAME_DAY):
        if match := pattern.match(s):
            day, key = int(match["d"]), header_key(match["mon"])
            if key in BENGALI_MONTHS:
                bengali = bengali_to_gregorian(day, BENGALI_MONTHS[key], int(match["y"]))
                return _make(bengali.year, bengali.month, bengali.day, match, period)
            month = MONTHS.get(key)
            if month is None:
                raise NormaliseError("ingest.date.unknown_month", text)
            return _make(_year(match["y"]), month, day, match, period)
    raise NormaliseError("ingest.date.invalid", text)


# ---------------------------------------------------------------- day/month order per file


def _evidence(values: Sequence[str]) -> tuple[bool, bool, bool]:
    """(some value proves day-first, some proves month-first, some is genuinely ambiguous)."""
    day_first = month_first = ambiguous = False
    for value in values:
        parts = numeric_parts(value)
        if parts is None:
            continue
        a, b = parts
        day_first |= a > 12 >= b
        month_first |= b > 12 >= a
        ambiguous |= a != b and a <= 12 and b <= 12
    return day_first, month_first, ambiguous


def infer_day_first(values: Sequence[str], default: bool = True) -> bool:
    """Day/month order for a whole column from proof alone; `default` (Bangladeshi day-first)
    when there is none or it conflicts. See `resolve_day_first` for the full decision."""
    day_first, month_first, _ambiguous = _evidence(values)
    return day_first if day_first != month_first else default


def order_violations(values: Sequence[str], day_first: bool) -> int | None:
    """How far a reading is from sorted (statements are in date order, either direction)."""
    moments = []
    for value in values:
        try:
            moments.append(parse_when(value, day_first=day_first).at)
        except NormaliseError:
            continue
    if len(moments) < 2:
        return None
    pairs = list(zip(moments, moments[1:], strict=False))
    return min(sum(b < a for a, b in pairs), sum(b > a for a, b in pairs))


def resolve_day_first(values: Sequence[str], default: bool = True,
                      extra_evidence: Sequence[str] = (),
                      default_is_known: bool = False) -> tuple[bool, bool]:
    """(day_first, certain) for a date column.

    A value like 13/04 proves day-first and 04/13 proves month-first; `extra_evidence` adds the
    file's other date columns (due dates, paid dates) as proof. `default_is_known` is for
    exports whose institution fixes the order (bKash, Nagad and Bangladeshi banks write
    dd/mm): without proof otherwise, the default holds. For hand-made files the reading under
    which `values` run in order wins; when nothing decides and some dates really are ambiguous,
    the answer is `default` with certain=False: those rows need the owner's word.
    """
    day_first, month_first, ambiguous = _evidence([*values, *extra_evidence])
    if day_first != month_first:
        return day_first, True
    if not ambiguous or (default_is_known and not (day_first and month_first)):
        return default, True
    if day_first and month_first:
        return default, False  # the file mixes both orders
    as_day, as_month = order_violations(values, True), order_violations(values, False)
    if as_day is not None and as_month is not None and as_day != as_month:
        return as_day < as_month, True
    return default, False
