"""Anonymiser for LLM payloads (WP-03 milestone 3; FEATURES N6, N15, P11).

Before any text reaches a model:
  1. raw PII is tokenised through the vault (names, phones, NIDs, accounts, addresses);
  2. tokens become neutral labels in order of first appearance: "Customer 1", "Supplier 2",
     "Person 3", "Firm A" ... so the model sees no stable identifier across requests;
  3. dates become relative to an anchor ("day t-12", "month t-2"): no calendar fingerprint;
  4. place names and caller-listed rare terms (e.g. a unique product) become "[place]" /
     "[item]", a memorisation guard;
  5. optionally (P11) taka amounts are multiplied by a secret factor: ratios survive, the
     scale of the business does not. Thresholds stay in code, never in the prompt.
`restore()` maps labels in the model's answer back to tokens. Numbers in answers are never
restored or trusted: figures always come from the engines (CLAUDE.md rule 1).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.privacy.detectors import DHAKA_AREAS
from app.privacy.vault import TOKEN_RE, TokenVault, tokenise

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_AMOUNT = re.compile(r"(?P<cur>Tk\.?|BDT|৳)\s?(?P<num>\d[\d,]*(?:\.\d+)?)", re.I)
_LABEL = re.compile(r"\b(Customer|Supplier|Person|Firm|Contact|Account|Address|Email) "
                    r"(\d+|[A-Z]{1,2})\b")


def _letters(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 26)
        out = chr(65 + r) + out
        if n == 0:
            return out
        n -= 1


@dataclass
class Anonymised:
    text: str
    labels: dict[str, str] = field(default_factory=dict)  # label -> token
    scale: Decimal = Decimal(1)
    anchor: date | None = None

    def restore(self, answer: str) -> str:
        """Put tokens back where the model used our labels. Unknown labels stay as they are."""
        return _LABEL.sub(lambda m: self.labels.get(m.group(0), m.group(0)), answer)


def _label_for(token: str, roles: Mapping[str, str], counters: dict[str, int]) -> str:
    prefix = token.split("_", 1)[0]
    role = roles.get(token)
    if role in ("customer", "supplier"):
        family = role.capitalize()
    else:
        family = {"PERSON": "Person", "SHOP": "Firm", "PARTY": "Contact", "PHONE": "Contact",
                  "ACCOUNT": "Account", "EMAIL": "Email", "ADDRESS": "Address",
                  "ORG": "Firm"}.get(prefix, "Contact")
    counters[family] = counters.get(family, 0) + 1
    n = counters[family]
    return f"{family} {_letters(n - 1)}" if family == "Firm" else f"{family} {n}"


def _relative_dates(text: str, anchor: date) -> str:
    def rel(d: date) -> str:
        days = (d - anchor).days
        if abs(days) <= 62:
            return f"day t{days:+d}"
        months = (d.year - anchor.year) * 12 + d.month - anchor.month
        return f"month t{months:+d}"

    def iso(m: re.Match[str]) -> str:
        try:
            return rel(date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            return "[date]"

    def dmy(m: re.Match[str]) -> str:
        try:
            return rel(date(int(m[3]), int(m[2]), int(m[1])))
        except ValueError:
            return "[date]"

    return _DMY_DATE.sub(dmy, _ISO_DATE.sub(iso, text))


def _scale_amounts(text: str, scale: Decimal) -> str:
    def repl(m: re.Match[str]) -> str:
        value = Decimal(m["num"].replace(",", "")) * scale
        return f"{m['cur']} {value.quantize(Decimal('1'), rounding=ROUND_HALF_UP)}"

    return _AMOUNT.sub(repl, text)


def new_scale() -> Decimal:
    """A secret factor in [0.50, 2.00), two decimals, fresh per request."""
    return Decimal(50 + secrets.randbelow(150)) / Decimal(100)


def anonymise(
    text: str,
    *,
    vault: TokenVault,
    tenant: str,
    anchor: date,
    roles: Mapping[str, str] | None = None,
    party_names: Iterable[str] = (),
    shop_names: Iterable[str] = (),
    rare_terms: Iterable[str] = (),
    scale_amounts: bool = False,
    scale: Decimal | None = None,
) -> Anonymised:
    roles = roles or {}
    tokenised = tokenise(vault, tenant, text, party_names=party_names, shop_names=shop_names)
    out = tokenised.text
    labels: dict[str, str] = {}
    by_token: dict[str, str] = {}
    counters: dict[str, int] = {}

    def replace(m: re.Match[str]) -> str:
        token = m.group(0)
        if token not in by_token:
            label = _label_for(token, roles, counters)
            by_token[token] = label
            labels[label] = token
        return by_token[token]

    out = TOKEN_RE.sub(replace, out)
    out = _relative_dates(out, anchor)
    for term in sorted({t for t in rare_terms if t}, key=len, reverse=True):
        out = re.sub(re.escape(term), "[item]", out, flags=re.I)
    used_scale = Decimal(1)
    if scale_amounts:
        used_scale = scale if scale is not None else new_scale()
        out = _scale_amounts(out, used_scale)
    # Places last: tokenisation already replaced detected addresses; catch bare area names.
    for area in sorted(DHAKA_AREAS, key=len, reverse=True):
        out = re.sub(rf"(?<![\wঀ-৿]){re.escape(area)}(?![\wঀ-৿])",
                     "[place]", out, flags=re.I)
    return Anonymised(text=out, labels=labels, scale=used_scale, anchor=anchor)
