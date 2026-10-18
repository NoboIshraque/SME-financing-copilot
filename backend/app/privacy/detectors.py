"""Deterministic PII detectors (WP-03 milestone 1).

Detected kinds: Bangladesh mobile numbers (bKash/Nagad accounts are mobile numbers), national
ID numbers, payment cards (Luhn), bank-account-like long numbers, emails, Dhaka addresses and
area names, and person / shop names from the tenant's party registry plus a common-name list.
Bangla digits (০-৯) are recognised everywhere: they are single code points, so offsets in the
normalised text equal offsets in the original.

Design rule: fail closed. Any standalone run of 10 or more digits that is not a mobile number
is treated as sensitive (NID, card or account), because in a shop ledger such a number is
almost never anything else.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


class Kind(StrEnum):
    PHONE = "PHONE"
    NID = "NID"
    CARD = "CARD"
    ACCOUNT = "ACCOUNT"
    EMAIL = "EMAIL"
    ADDRESS = "ADDRESS"
    PERSON = "PERSON"
    SHOP = "SHOP"


@dataclass(frozen=True)
class Detection:
    kind: Kind
    start: int
    end: int
    value: str

    def overlaps(self, other: Detection) -> bool:
        return self.start < other.end and other.start < self.end


def to_ascii_digits(text: str) -> str:
    return text.translate(BANGLA_DIGITS)


# +880 1X XXXXXXXX or 01X XXXXXXXX, allowing spaces or dashes between groups.
# 01XXXXXXXXX with an optional +88 / 88 country code, or +880 1XXXXXXXXX. A leading 0 or the
# country code is required, so a 10-digit NID such as 1987654321 is not read as a phone.
_PHONE = re.compile(
    r"(?<![\w])(?:(?:\+?88[\s-]?)?0|\+?880[\s-]?)1[3-9](?:[\s-]?\d){8}(?![\w])"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Not preceded/followed by letters, digits, "_" or "." so privacy tokens (PARTY_0123456789)
# and decimal amounts are not mistaken for account numbers.
_LONG_NUMBER = re.compile(r"(?<![\w.])\d(?:[\s-]?\d){9,18}(?![\w]|\.\d)")
_NID_CONTEXT = re.compile(r"(nid|national\s*id|জাতীয়\s*পরিচয়|এনআইডি|voter\s*id)", re.I)
_HOUSE_ROAD = re.compile(
    r"\b(?:house|holding|flat|road|rd|lane|block|sector|plot)\s*(?:no\.?\s*)?#?\s*\d+[a-z]?\b"
    r"|(?:বাড়ি|বাসা|রোড|সড়ক|ব্লক|সেক্টর)\s*(?:নং)?\s*\d+",
    re.I,
)

DHAKA_AREAS = (
    "Mirpur", "Dhanmondi", "Gulshan", "Banani", "Uttara", "Mohammadpur", "Motijheel",
    "Islampur", "Nawabpur", "Ashulia", "Savar", "Gazipur", "Narayanganj", "Farmgate",
    "Tejgaon", "Badda", "Rampura", "Khilgaon", "Jatrabari", "Lalbagh", "Keraniganj",
    "Bashundhara", "Mohakhali", "Shyamoli", "Kawran Bazar", "Karwan Bazar", "Shantinagar",
    "Malibagh", "Moghbazar", "Paltan", "Chawkbazar", "Sadarghat", "Wari", "Demra",
    "মিরপুর", "ধানমন্ডি", "গুলশান", "বনানী", "উত্তরা", "মোহাম্মদপুর", "মতিঝিল",
    "ইসলামপুর", "নবাবপুর", "আশুলিয়া", "সাভার", "গাজীপুর", "নারায়ণগঞ্জ", "ফার্মগেট",
    "তেজগাঁও", "বাড্ডা", "রামপুরা", "যাত্রাবাড়ী", "লালবাগ", "কেরানীগঞ্জ", "মোহাখালী",
)
COMMON_NAMES = (
    "Rahim", "Karim", "Salma", "Nasima", "Jamal", "Rafiq", "Shirin", "Habib", "Farzana",
    "Kamal", "Rubina", "Anwar", "Mitu", "Sohel", "Tania", "Babul", "Ruma", "Faruk", "Lipi",
    "Mizan", "Shapla", "Delwar", "Moushumi", "Aziz", "Parvin", "Selim", "Hasan", "Hossain",
    "Rahman", "Akter", "Begum", "Chowdhury", "Talukder", "Bhuiyan", "Sarkar", "Uddin",
    "রহিম", "করিম", "সালমা", "নাসিমা", "জামাল", "রফিক", "হাবিব", "কামাল", "আনোয়ার",
    "সোহেল", "ফারুক", "মিজান", "আজিজ", "সেলিম", "হাসান", "হোসেন", "রহমান", "বেগম",
)
SHOP_SUFFIX = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*)\s+"
    r"(?:Store|Stores|Traders|Trading|Enterprise|Enterprises|Bhandar|Agency|Corporation|"
    r"House|Pharmacy|Telecom|Fashion|Textile|Hardware|Mart)\b"
)


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _word_pattern(words: Iterable[str]) -> re.Pattern[str] | None:
    words = sorted({w for w in words if w and len(w) >= 3}, key=len, reverse=True)
    if not words:
        return None
    alternation = "|".join(re.escape(w) for w in words)
    # Word boundaries that also work for Bangla (no \b support for combining marks).
    return re.compile(rf"(?<![\wঀ-৿])(?:{alternation})(?![\wঀ-৿])", re.I)


_AREA_RE = _word_pattern(DHAKA_AREAS)
_COMMON_NAME_RE = _word_pattern(COMMON_NAMES)


def detect(text: str, *, party_names: Iterable[str] = (), shop_names: Iterable[str] = ()
           ) -> list[Detection]:
    """All detections, longest-first with overlaps removed, sorted by position."""
    norm = to_ascii_digits(text)
    found: list[Detection] = []

    def add(kind: Kind, start: int, end: int) -> None:
        found.append(Detection(kind, start, end, text[start:end]))

    for m in _EMAIL.finditer(norm):
        add(Kind.EMAIL, m.start(), m.end())
    for m in _PHONE.finditer(norm):
        add(Kind.PHONE, m.start(), m.end())
    for m in _LONG_NUMBER.finditer(norm):
        digits = re.sub(r"\D", "", m.group())
        if _PHONE.fullmatch(m.group()):
            continue
        window = norm[max(0, m.start() - 25): m.start()]
        if len(digits) in (10, 13, 17) and _NID_CONTEXT.search(window):
            kind = Kind.NID
        elif 13 <= len(digits) <= 19 and _luhn(digits):
            kind = Kind.CARD
        elif len(digits) in (10, 13, 17):
            kind = Kind.NID
        else:
            kind = Kind.ACCOUNT
        add(kind, m.start(), m.end())
    for m in _HOUSE_ROAD.finditer(norm):
        add(Kind.ADDRESS, m.start(), m.end())
    if _AREA_RE:
        for m in _AREA_RE.finditer(norm):
            add(Kind.ADDRESS, m.start(), m.end())
    shop_re = _word_pattern(shop_names)
    if shop_re:
        for m in shop_re.finditer(norm):
            add(Kind.SHOP, m.start(), m.end())
    for m in SHOP_SUFFIX.finditer(norm):
        add(Kind.SHOP, m.start(), m.end())
    person_re = _word_pattern(party_names)
    for pattern in (person_re, _COMMON_NAME_RE):
        if pattern:
            for m in pattern.finditer(norm):
                add(Kind.PERSON, m.start(), m.end())

    # Keep the longest detection where several overlap (e.g. "Rahim Traders" beats "Rahim").
    kept: list[Detection] = []
    for det in sorted(found, key=lambda d: (-(d.end - d.start), d.start, d.kind.value)):
        if not any(det.overlaps(k) for k in kept):
            kept.append(det)
    kept.sort(key=lambda d: d.start)
    # "Rahim Hossain" is one person: merge PERSON detections separated only by spaces.
    merged: list[Detection] = []
    for det in kept:
        prev = merged[-1] if merged else None
        if (prev and prev.kind is Kind.PERSON and det.kind is Kind.PERSON
                and text[prev.end:det.start].strip() == "" and det.start - prev.end <= 2):
            merged[-1] = Detection(Kind.PERSON, prev.start, det.end, text[prev.start:det.end])
        else:
            merged.append(det)
    return merged


def kinds_in(text: str, **kwargs: Iterable[str]) -> set[Kind]:
    return {d.kind for d in detect(text, **kwargs)}
