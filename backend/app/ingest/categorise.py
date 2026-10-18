"""Transaction categories from what a statement row actually says (WP-02).

Order of evidence: a category column (ledgers), the statement's own transaction-type label,
the reference (shops and banks use telling prefixes such as SALE-, INV-, EMI-), then keywords
in the description in English, Banglish and Bangla. When nothing is telling, the category is
`other`: a guess would distort every engine downstream.
"""

from __future__ import annotations

import re

from app.contracts import Direction, TxCategory
from app.ingest.normalise import clean_text, header_key

C = TxCategory
INFLOW, OUTFLOW = Direction.inflow, Direction.outflow

# Values written in a ledger's category column.
CATEGORY_WORDS: dict[str, TxCategory] = {header_key(k): v for k, v in {
    **{c.value: c for c in TxCategory},
    "supplier payment": C.supplier_payment, "owner draw": C.owner_draw,
    "owner topup": C.owner_topup, "loan repayment": C.loan_repayment,
    "loan disbursement": C.loan_disbursement, "sale": C.sales, "bikri": C.sales,
    "বিক্রি": C.sales, "বিক্রয়": C.sales, "baki adai": C.collection, "বাকি আদায়": C.collection,
    "aday": C.collection, "আদায়": C.collection, "kroy": C.purchase, "kena": C.purchase,
    "ক্রয়": C.purchase, "mal kena": C.purchase, "মাল ক্রয়": C.purchase,
    "bhara": C.rent, "vara": C.rent, "ভাড়া": C.rent, "dokan bhara": C.rent,
    "beton": C.salary, "বেতন": C.salary, "wages": C.salary, "majuri": C.salary, "মজুরি": C.salary,
    "bidyut": C.utility, "bijli": C.utility, "বিদ্যুৎ": C.utility, "gas": C.utility,
    "গ্যাস": C.utility, "pani": C.utility, "internet": C.utility,
    "kisti": C.loan_repayment, "কিস্তি": C.loan_repayment, "emi": C.loan_repayment,
    "vat": C.tax, "কর": C.tax, "ভ্যাট": C.tax, "charge": C.fee, "চার্জ": C.fee,
    "transfer": C.transfer, "স্থানান্তর": C.transfer,
}.items()}

# Reference prefixes/infixes, checked in order. (pattern, inflow category, outflow category)
# A prefix must end at a separator or digit: 'SAL-2025' is salary, 'SALE-2504' is not.
_END = r"(?=[-_/ ]|\d|$)"
_REFERENCE_RULES: tuple[tuple[re.Pattern[str], TxCategory | None, TxCategory | None], ...] = tuple(
    (re.compile(p, re.IGNORECASE), i, o) for p, i, o in (
        (r"^(sweep|topup|top-up|xfer|trf|transfer)" + _END, C.transfer, C.transfer),
        (r"^sales?" + _END, C.sales, None),
        (r"(^|[-_/ ])inv" + _END, C.collection, C.supplier_payment),
        (r"(^|[-_/ ])bill" + _END, C.collection, C.supplier_payment),
        (r"^(util|utility)" + _END, None, C.utility),
        (r"^rent" + _END, None, C.rent),
        (r"^(sal|salary|bonus|payroll|wage|wages)" + _END, None, C.salary),
        (r"^draw" + _END, None, C.owner_draw),
        (r"^(emi|loan)" + _END, C.loan_disbursement, C.loan_repayment),
        (r"^(vat|tax|nbr)" + _END, None, C.tax),
    )
)

# Description keywords (whole words), checked in order; the first that applies wins.
_KEYWORDS: tuple[tuple[re.Pattern[str], TxCategory | None, TxCategory | None], ...] = tuple(
    (re.compile(r"(?<![\wঀ-৿])(" + p + r")(?![\wঀ-৿])", re.IGNORECASE), i, o)
    for p, i, o in (
        (r"sweep|own (?:\w+ )?account|fund transfer|transfer|bkash to bank|"
         r"bank to bkash|nagad to bank|bank to nagad|add money|স্থানান্তর", C.transfer, C.transfer),
        (r"supplier payment|mahajan|মহাজন|supplier", None, C.supplier_payment),
        (r"owner draw|personal|নিজ খরচ", None, C.owner_draw),
        (r"owner top ?up|capital|পুঁজি", C.owner_topup, None),
        (r"loan repayment|emi|kisti|কিস্তি|installment", None, C.loan_repayment),
        (r"loan disbursement|disbursement|ঋণ বিতরণ", C.loan_disbursement, None),
        (r"salary|salaries|payroll|bonus|beton|বেতন|wages|মজুরি", None, C.salary),
        (r"rent|bhara|vara|ভাড়া", None, C.rent),
        (r"utility|utilities|desco|dpdc|titas|wasa|electricity|bidyut|বিদ্যুৎ|gas bill|"
         r"pay bill|bill pay|internet|mobile recharge|recharge", None, C.utility),
        (r"vat|tax|nbr|ভ্যাট|কর", None, C.tax),
        (r"fee|charge|commission|চার্জ", None, C.fee),
        (r"collection|baki|বাকি|আদায়|aday", C.collection, None),
        (r"purchase|kroy|ক্রয়|mal kena", None, C.purchase),
        (r"sales|sale|bikri|বিক্রি|বিক্রয়", C.sales, None),
    )
)


def from_category_column(value: str) -> TxCategory | None:
    return CATEGORY_WORDS.get(header_key(value)) if value.strip() else None


def from_reference(reference: str | None, direction: Direction) -> TxCategory | None:
    if not reference:
        return None
    ref = clean_text(reference)
    for pattern, inflow, outflow in _REFERENCE_RULES:
        if pattern.search(ref):
            found = inflow if direction is INFLOW else outflow
            if found is not None:
                return found
    return None


def from_text(text: str | None, direction: Direction) -> TxCategory | None:
    if not text:
        return None
    for pattern, inflow, outflow in _KEYWORDS:
        if pattern.search(text):
            found = inflow if direction is INFLOW else outflow
            if found is not None:
                return found
    return None


def keyword_span(text: str) -> tuple[int, int] | None:
    """Where the first category keyword sits in `text` (used to split a bank narration such as
    'COLLECTION Dhaka Traders' into the category words and the counterparty)."""
    best: tuple[int, int] | None = None
    for pattern, _i, _o in _KEYWORDS:
        match = pattern.search(text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), match.end())
    return best


def categorise(
    direction: Direction,
    *,
    column: str | None = None,
    label: TxCategory | None = None,
    label_is_strong: bool = False,
    reference: str | None = None,
    text: str | None = None,
) -> TxCategory:
    """Pick the category from the strongest evidence available (see module docstring)."""
    if column and (found := from_category_column(column)) is not None:
        return found
    if label is not None and label_is_strong:
        return label
    for found in (from_reference(reference, direction), from_text(text, direction)):
        if found is not None:
            return found
    return label if label is not None else C.other
