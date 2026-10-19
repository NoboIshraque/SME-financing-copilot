"""Parties: the business itself and everyone it deals with.

Engines and LLM payloads only ever see `token` (e.g. `SHOP_3f9a1`), never real names.
The token vault (WP-03) maps tokens back to originals for authorised display.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.contracts.common import Contract, DataMode

TOKEN_PATTERN = r"^(PERSON|SHOP|PHONE|ACCOUNT|EMAIL|ADDRESS|ORG|PARTY)_[0-9a-z]{5,16}$"


class PartyRole(StrEnum):
    self_ = "self"
    customer = "customer"
    supplier = "supplier"
    lender = "lender"
    employee = "employee"
    landlord = "landlord"
    government = "government"
    utility = "utility"
    other = "other"


class Party(Contract):
    id: str
    tenant_id: str
    token: str = Field(pattern=TOKEN_PATTERN)
    role: PartyRole
    display_label: str = Field(
        description="Neutral label safe to show anywhere, e.g. 'Customer 3'", max_length=64
    )
    is_tenant: bool = Field(
        default=False, description="True if this party is itself a DecisionGuard tenant (mesh peer)"
    )
    data_mode: DataMode
