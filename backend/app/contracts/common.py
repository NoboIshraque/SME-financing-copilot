"""Shared primitives: money, periods, data modes, permission tiers.

All contracts subclass `Contract`: immutable, unknown fields rejected, money as `Decimal`.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

TWO_PLACES = Decimal("0.01")


class Contract(BaseModel):
    """Base class for every shared schema."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


def quantize_money(value: Any) -> Decimal:
    """Convert to Decimal with exactly 2 decimal places (half-up). Floats are refused."""
    if isinstance(value, bool):
        raise ValueError("booleans are not money")
    if isinstance(value, float):
        raise ValueError("floats are not allowed for money; pass a str, int or Decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a decimal amount: {value!r}") from exc
    if not number.is_finite():
        raise ValueError("amount must be finite")
    return number.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


MoneyAmount = Annotated[Decimal, BeforeValidator(quantize_money)]
"""A Decimal amount, always 2 dp, never built from a float."""

Probability = Annotated[Decimal, Field(ge=Decimal(0), le=Decimal(1))]
"""A probability in [0, 1] as a Decimal."""

Score100 = Annotated[Decimal, Field(ge=Decimal(0), le=Decimal(100))]


class Currency(StrEnum):
    BDT = "BDT"
    USD = "USD"
    CNY = "CNY"


class DataMode(StrEnum):
    """Where data came from. Shown to users; synthetic data is always labelled."""

    synthetic = "synthetic"
    real_anonymised = "real_anonymised"
    public = "public"
    live = "live"


class Tier(StrEnum):
    """Permission tier of an action (FEATURES P2)."""

    READ = "READ"
    SUGGEST = "SUGGEST"
    DRAFT = "DRAFT"
    EXECUTE = "EXECUTE"
    DENY = "DENY"

    @property
    def needs_owner_approval(self) -> bool:
        return self is Tier.EXECUTE

    @property
    def allowed(self) -> bool:
        return self is not Tier.DENY


class Granularity(StrEnum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"


class Money(Contract):
    amount: MoneyAmount
    currency: Currency = Currency.BDT

    @classmethod
    def of(cls, amount: Any, currency: Currency = Currency.BDT) -> Money:
        return cls(amount=amount, currency=currency)

    @classmethod
    def zero(cls, currency: Currency = Currency.BDT) -> Money:
        return cls(amount=Decimal(0), currency=currency)

    def _same(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._same(other)
        return self.amount >= other.amount

    def scale(self, factor: Decimal | int) -> Money:
        if isinstance(factor, float):
            raise ValueError("scale factor must be Decimal or int")
        return Money(amount=self.amount * Decimal(factor), currency=self.currency)


class Period(Contract):
    start: date
    end: date
    granularity: Granularity = Granularity.month

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period end is before start")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


class Language(StrEnum):
    en = "en"
    bn = "bn"
    zh = "zh"


class ApiError(Contract):
    """Error body returned by every endpoint. `message_key` is an i18n key."""

    code: str
    message_key: str
    detail: dict[str, str] = Field(default_factory=dict)
