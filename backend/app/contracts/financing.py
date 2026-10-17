"""Financing options (WP-06; FEATURES group A, P1, P14, N20)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, DataMode, Money, Probability, Score100
from app.contracts.facts import Figure


class ProductKind(StrEnum):
    term_loan = "term_loan"
    working_capital = "working_capital"
    nano_loan = "nano_loan"
    refinance_scheme = "refinance_scheme"
    factoring = "factoring"
    invoice_discounting = "invoice_discounting"
    leasing = "leasing"
    mfi_loan = "mfi_loan"
    buyer_early_pay = "buyer_early_pay"
    supplier_term_extension = "supplier_term_extension"
    mesh_netting = "mesh_netting"
    owner_topup = "owner_topup"
    grant = "grant"
    digital_credit_modelled = "digital_credit_modelled"

    @property
    def is_loan(self) -> bool:
        return self in {
            ProductKind.term_loan,
            ProductKind.working_capital,
            ProductKind.nano_loan,
            ProductKind.refinance_scheme,
            ProductKind.mfi_loan,
            ProductKind.digital_credit_modelled,
        }


class RateType(StrEnum):
    reducing_balance = "reducing_balance"
    flat = "flat"
    daily_debit = "daily_debit"
    discount = "discount"  # factoring / early-pay: a % off the face value
    none = "none"  # e.g. owner top-up, netting, grants


class RateBasis(StrEnum):
    """How we know the rate. Shown next to every rate in the UI."""

    published = "published"  # the provider's own product page states it
    rate_sheet_upper = "rate_sheet_upper"  # upper bound of the bank's published rate sheet range
    regulatory_cap = "regulatory_cap"  # the maximum a regulator allows for this scheme
    last_published = "last_published"  # older published figure; the provider no longer shows one
    modelled = "modelled"  # illustrative assumption (P14 China pack)
    own_terms = "own_terms"  # options built from the SME's own data (top-up, early pay, ...)


class FeeKind(StrEnum):
    fixed = "fixed"
    percent_of_principal = "percent_of_principal"
    compulsory_deposit_percent = "compulsory_deposit_percent"


class FeeTiming(StrEnum):
    upfront = "upfront"
    periodic = "periodic"
    at_maturity = "at_maturity"


class Fee(Contract):
    name: str
    kind: FeeKind
    value: Decimal = Field(ge=0)
    timing: FeeTiming = FeeTiming.upfront


class RuleOp(StrEnum):
    gte = ">="
    lte = "<="
    eq = "=="
    exists = "exists"


class EligibilityRule(Contract):
    id: str
    metric: str = Field(description="Fact metric name, e.g. 'business_age_months'")
    op: RuleOp
    threshold: Decimal | None = None
    description_key: str

    @model_validator(mode="after")
    def _threshold_needed(self) -> EligibilityRule:
        if self.op is not RuleOp.exists and self.threshold is None:
            raise ValueError("comparison rules need a threshold")
        return self


class FinancingProduct(Contract):
    id: str
    provider: str
    name: str
    kind: ProductKind
    rate_type: RateType
    nominal_rate_pa: Decimal = Field(ge=0, description="Percent per year as published, e.g. 9")
    rate_basis: RateBasis = RateBasis.published
    notes: str | None = Field(default=None, max_length=600)
    fees: tuple[Fee, ...] = ()
    min_amount: Money | None = None
    max_amount: Money | None = None
    min_tenor_days: int | None = Field(default=None, ge=0)
    max_tenor_days: int | None = Field(default=None, ge=0)
    collateral_required: bool = False
    rules: tuple[EligibilityRule, ...] = ()
    source_url: str | None = None
    checked_on: date | None = None
    is_modelled: bool = Field(
        default=False, description="True for illustrative products (e.g. the P14 China pack)"
    )
    data_mode: DataMode

    @model_validator(mode="after")
    def _sourced(self) -> FinancingProduct:
        if (self.rate_basis is RateBasis.modelled) != self.is_modelled:
            raise ValueError("modelled products must say so: is_modelled and rate_basis=modelled")
        if self.kind.is_loan and not self.is_modelled:
            if not self.source_url or self.checked_on is None:
                raise ValueError("a real loan product needs source_url and checked_on")
        if self.min_amount is not None and self.max_amount is not None:
            if self.min_amount > self.max_amount:
                raise ValueError("min_amount is above max_amount")
        if self.min_tenor_days is not None and self.max_tenor_days is not None:
            if self.min_tenor_days > self.max_tenor_days:
                raise ValueError("min_tenor_days is above max_tenor_days")
        return self


class FinancingNeed(Contract):
    tenant_id: str
    amount: Money
    needed_by: date
    tenor_days: int = Field(ge=1, le=3650)
    purpose_key: str = "working_capital"


class EligibilityStatus(StrEnum):
    pass_ = "pass"
    fail = "fail"
    not_on_record = "not_on_record"  # we do not have the fact; never invent it


class EligibilityReason(Contract):
    rule_id: str
    status: EligibilityStatus
    observed_value: Decimal | None = None
    message_key: str


class Eligibility(Contract):
    product_id: str
    status: EligibilityStatus
    reasons: tuple[EligibilityReason, ...] = ()

    @model_validator(mode="after")
    def _overall_status(self) -> Eligibility:
        statuses = {r.status for r in self.reasons}
        if EligibilityStatus.fail in statuses:
            expected = EligibilityStatus.fail
        elif EligibilityStatus.not_on_record in statuses:
            expected = EligibilityStatus.not_on_record
        else:
            expected = EligibilityStatus.pass_
        if self.status is not expected:
            raise ValueError(f"overall status should be {expected.value}")
        return self


class FinancingOption(Contract):
    product: FinancingProduct
    eligibility: Eligibility
    effective_apr: Decimal = Field(description="True annual cost in percent, fees included")
    total_cost: Money
    p_buffer_breach: Probability
    speed_days: int = Field(ge=0)
    approval_likelihood: Probability
    score: Score100
    rank: int = Field(ge=1)
    figures: tuple[Figure, ...] = ()
    reason_keys: tuple[str, ...] = ()


class LicenceStatus(StrEnum):
    licensed = "licensed"
    not_found = "not_found"
    revoked = "revoked"
    unknown = "unknown"


class LenderProfile(Contract):
    lender_id: str
    name: str
    licence_status: LicenceStatus
    regulator: str | None = Field(default=None, description="e.g. 'Bangladesh Bank', 'MRA'")
    events_count: int = Field(ge=0)
    quoted_vs_realised_apr_gap: Decimal | None = Field(
        default=None, description="Average realised minus quoted APR, percentage points"
    )
    median_disbursal_days: Decimal | None = None
    hidden_fee_incidents: int = Field(default=0, ge=0)
    disputes: int = Field(default=0, ge=0)
    data_mode: DataMode
