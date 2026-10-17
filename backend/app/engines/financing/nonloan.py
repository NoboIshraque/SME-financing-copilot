"""Non-loan options built from the SME's own situation (WP-06 milestone 1, generated part).

These compete in the same ranking as loans, priced with the same cost engine:
  owner top-up             the owner lends to the shop: no interest (opportunity cost not modelled)
  supplier term extension  pay a supplier later for an agreed fee (percent of the bill)
  buyer early pay          give a customer x% off to be paid d days early
  mesh netting             clear circular debt through the liquidity mesh (WP-08): no interest
"""

from __future__ import annotations

from decimal import Decimal

from app.contracts import (
    DataMode,
    Fee,
    FeeKind,
    FeeTiming,
    FinancingProduct,
    Money,
    ProductKind,
    RateType,
)

DAYS = Decimal(365)


def owner_topup(max_amount: Money, data_mode: DataMode) -> FinancingProduct:
    return FinancingProduct(
        id="own-owner-topup", provider="Owner", name="Owner top-up",
        kind=ProductKind.owner_topup, rate_type=RateType.none, nominal_rate_pa=Decimal(0),
        max_amount=max_amount, data_mode=data_mode,
    )


def supplier_term_extension(supplier_token: str, bill_amount: Money, extra_days: int,
                            fee_percent: Decimal, data_mode: DataMode) -> FinancingProduct:
    fees = (Fee(name="extension fee", kind=FeeKind.percent_of_principal, value=fee_percent,
                timing=FeeTiming.at_maturity),) if fee_percent > 0 else ()
    return FinancingProduct(
        id=f"own-supplier-ext-{supplier_token}", provider=supplier_token,
        name=f"Pay {supplier_token} {extra_days} days later",
        kind=ProductKind.supplier_term_extension, rate_type=RateType.none,
        nominal_rate_pa=Decimal(0), fees=fees, max_amount=bill_amount,
        max_tenor_days=extra_days, data_mode=data_mode,
    )


def buyer_early_pay(customer_token: str, invoice_amount: Money, discount_percent: Decimal,
                    days_early: int, data_mode: DataMode) -> FinancingProduct:
    """x% off for d days earlier == a discount of x% x 365/d per year on the face value."""
    if days_early <= 0:
        raise ValueError("days_early must be positive")
    annual = discount_percent * DAYS / Decimal(days_early)
    return FinancingProduct(
        id=f"own-early-pay-{customer_token}", provider=customer_token,
        name=f"{discount_percent}% off if {customer_token} pays {days_early} days early",
        kind=ProductKind.buyer_early_pay, rate_type=RateType.discount, nominal_rate_pa=annual,
        max_amount=invoice_amount, max_tenor_days=days_early, data_mode=data_mode,
    )


def mesh_netting(cash_saved: Money, data_mode: DataMode) -> FinancingProduct:
    return FinancingProduct(
        id="own-mesh-netting", provider="Hishab liquidity mesh", name="Net circular debts",
        kind=ProductKind.mesh_netting, rate_type=RateType.none, nominal_rate_pa=Decimal(0),
        max_amount=cash_saved, data_mode=data_mode,
    )
