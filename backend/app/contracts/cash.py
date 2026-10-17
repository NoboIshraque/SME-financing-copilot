"""Cash-flow forecast, gaps, alerts and smoothing (WP-04; FEATURES group B, Q1, Q3)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.agents import ActionCard
from app.contracts.common import Contract, DataMode, Money, Probability
from app.contracts.facts import Figure


class ForecastPoint(Contract):
    day: date
    p10: Money = Field(description="Worst-case band (10th percentile balance)")
    p50: Money = Field(description="Likely balance (median)")
    p90: Money = Field(description="Best-case band (90th percentile balance)")
    p_below_buffer: Probability

    @model_validator(mode="after")
    def _bands_ordered(self) -> ForecastPoint:
        if not (self.p10 <= self.p50 <= self.p90):
            raise ValueError("forecast bands must satisfy p10 <= p50 <= p90")
        return self


class ForecastBand(Contract):
    tenant_id: str
    as_of: date
    horizon_days: int = Field(ge=1, le=366)
    paths: int = Field(ge=1)
    seed: int
    opening_balance: Money
    buffer: Money
    points: tuple[ForecastPoint, ...]
    data_mode: DataMode
    generated_at: datetime

    @model_validator(mode="after")
    def _points_cover_horizon(self) -> ForecastBand:
        if len(self.points) != self.horizon_days:
            raise ValueError("one forecast point per day of the horizon is required")
        days = [p.day for p in self.points]
        if days != sorted(set(days)):
            raise ValueError("forecast days must be strictly increasing")
        if days and days[0] <= self.as_of:
            raise ValueError("forecast starts the day after as_of")
        return self


class DriverKind(StrEnum):
    late_customer = "late_customer"
    bill_due = "bill_due"
    obligation = "obligation"
    seasonal_dip = "seasonal_dip"
    stock_build = "stock_build"
    cost_shock = "cost_shock"


class GapDriver(Contract):
    kind: DriverKind
    label_key: str
    amount: Money
    reference_id: str | None = Field(default=None, description="Invoice/bill/obligation id")
    counterparty_token: str | None = None


class CashGap(Contract):
    first_breach_day: date
    lead_time_days: int = Field(ge=0)
    probability: Probability
    expected_shortfall: Money
    worst_day: date
    drivers: tuple[GapDriver, ...] = Field(default=(), max_length=3)
    figures: tuple[Figure, ...] = ()

    @model_validator(mode="after")
    def _shortfall_positive(self) -> CashGap:
        if self.expected_shortfall.amount <= 0:
            raise ValueError("a gap has a positive expected shortfall")
        if self.worst_day < self.first_breach_day:
            raise ValueError("worst day cannot be before the first breach")
        return self


class AlertTier(StrEnum):
    watch = "watch"
    warning = "warning"
    critical = "critical"

    @property
    def rank(self) -> int:
        return {"watch": 1, "warning": 2, "critical": 3}[self.value]


class LeadingIndicator(StrEnum):
    dso_rising = "dso_rising"
    top_customer_slowing = "top_customer_slowing"
    stock_building = "stock_building"
    sales_below_seasonal_norm = "sales_below_seasonal_norm"
    payroll_or_emi_at_risk = "payroll_or_emi_at_risk"


class Alert(Contract):
    id: str
    tenant_id: str
    tier: AlertTier
    title_key: str
    gap: CashGap | None = None
    indicators: tuple[LeadingIndicator, ...] = ()
    fixes: tuple[ActionCard, ...] = Field(default=(), description="Ranked fixes, cheapest first")
    dedupe_key: str
    created_at: datetime
    data_mode: DataMode

    @model_validator(mode="after")
    def _has_reason(self) -> Alert:
        if self.gap is None and not self.indicators:
            raise ValueError("an alert needs a gap or at least one leading indicator")
        return self


class LeverKind(StrEnum):
    retime_payable = "retime_payable"
    stagger_purchase = "stagger_purchase"
    request_advance = "request_advance"
    early_pay_discount = "early_pay_discount"
    netting = "netting"
    standby_facility = "standby_facility"
    surplus_sweep = "surplus_sweep"


class SmoothingLever(Contract):
    kind: LeverKind
    gap_reduction: Money
    cost: Money
    action: ActionCard

    @model_validator(mode="after")
    def _non_negative(self) -> SmoothingLever:
        if self.gap_reduction.amount < 0 or self.cost.amount < 0:
            raise ValueError("gap_reduction and cost are non-negative")
        return self
