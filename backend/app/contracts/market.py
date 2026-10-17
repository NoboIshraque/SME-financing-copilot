"""Market watch (WP-09): public prices and vendor quotes (FEATURES N3)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, DataMode, Money, Probability


class PriceSource(StrEnum):
    tcb = "tcb"  # Trading Corporation of Bangladesh daily Dhaka prices
    agripricebd = "agripricebd"
    worldbank_pinksheet = "worldbank_pinksheet"
    vendor = "vendor"
    manual = "manual"


class PricePoint(Contract):
    commodity: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="e.g. 'rice_coarse'")
    unit: str = Field(description="e.g. 'kg', 'litre', 'metric_ton'")
    price: Money = Field(description="Mid price; low/high when the source gives a range")
    low: Money | None = None
    high: Money | None = None
    market: str = Field(description="e.g. 'Dhaka' or 'World'")
    source: PriceSource
    source_url: str | None = None
    observed_on: date
    data_mode: DataMode

    @model_validator(mode="after")
    def _range(self) -> PricePoint:
        if self.price.amount <= 0:
            raise ValueError("price must be positive")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("low price is above high price")
        if self.low is not None and self.price < self.low:
            raise ValueError("price is below the low of its range")
        if self.high is not None and self.price > self.high:
            raise ValueError("price is above the high of its range")
        return self


class VendorQuote(Contract):
    vendor_token: str
    commodity: str
    unit: str
    unit_price: Money
    delivery_cost: Money
    lead_time_days: int = Field(ge=0)
    on_time_rate: Probability | None = Field(
        default=None, description="Share of past orders delivered on time (SME's own history)"
    )
    quoted_on: date
    data_mode: DataMode
