"""State data adapter (WP-13 milestone 5; FEATURES Q4).

China's national credit-information platform for SMEs shares a fixed set of public-record data
items with lenders (registration, tax, social insurance, utilities, court and penalty records).
Bangladesh has no such platform yet. This interface has the same shape, so when official data
sharing opens it plugs straight in. Today only `MockStateAdapter` exists, and every record it
returns says `data_mode=synthetic` and `source="mock"`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.contracts import DataMode


class StateField(StrEnum):
    business_registration = "business_registration"  # trade licence / RJSC
    tax_registration = "tax_registration"  # e-TIN / BIN
    tax_filings = "tax_filings"  # VAT / income tax returns filed on time
    utility_payments = "utility_payments"  # electricity, gas, water paid on time
    social_insurance = "social_insurance"  # staff contributions (where applicable)
    court_records = "court_records"  # judgments, enforcement
    administrative_penalties = "administrative_penalties"


@dataclass(frozen=True)
class StateRecord:
    field: StateField
    value: str
    as_of: date
    source: str
    data_mode: DataMode


class StateAdapter(Protocol):
    name: str

    def fetch(self, business_id: str, fields: list[StateField], *,
              consent_id: str) -> list[StateRecord]: ...


class ConsentRequiredError(PermissionError):
    pass


class MockStateAdapter:
    """Deterministic stand-in labelled synthetic. Requires a consent id like the real thing."""

    name = "mock"

    def __init__(self, records: dict[str, dict[StateField, str]], as_of: date) -> None:
        self._records = records
        self._as_of = as_of

    def fetch(self, business_id: str, fields: list[StateField], *,
              consent_id: str) -> list[StateRecord]:
        if not consent_id:
            raise ConsentRequiredError("state data is only fetched with the owner's consent")
        known = self._records.get(business_id, {})
        return [StateRecord(field=f, value=known.get(f, "not_on_record"), as_of=self._as_of,
                            source="mock", data_mode=DataMode.synthetic) for f in fields]
