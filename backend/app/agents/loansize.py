"""How big a loan the shop can safely repay (Session A; answers "how big a loan can I take?").

A loan's proceeds are spent on what it was taken for (stock, equipment), so what the cash
balance feels is the repayments. A principal is *safe* for a product when

    for every day d of the forecast:  P10(d) + repayments_so_far(d) >= safety buffer

(P10: the cautious forecast line, the balance is above it on nine days in ten; repayments are
the product's cash flows after disbursement, negative, from the WP-06 cost engine; a payment
falling after the forecast's last day is counted on that day), and the product's eligibility
check does not fail for that amount. The safe size is the largest such principal on a
Tk 1,000 grid, capped by the product's maximum.

Repayments grow with the principal, so the search bisects; the checker does not trust it:
it re-checks that the claimed amount is safe and that one more step is not (or is above the
product's cap).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import (
    EligibilityStatus,
    FinancingProduct,
    ForecastBand,
    Money,
    ProductKind,
)
from app.engines.financing import cost as cost_mod
from app.engines.financing.eligibility import evaluate

FORMULA_ID = "copilot.safe_loan_amount"
FORMULA_VERSION = 1
STEP = Decimal(1000)
LOAN_KINDS = frozenset({ProductKind.nano_loan, ProductKind.mfi_loan, ProductKind.working_capital,
                        ProductKind.term_loan, ProductKind.refinance_scheme,
                        ProductKind.digital_credit_modelled})


@dataclass(frozen=True)
class SafeSize:
    product: FinancingProduct
    amount: Decimal
    capped: bool  # the product's maximum, not the forecast, set the limit


def repayments_by_day(product: FinancingProduct, principal: Decimal, tenor_days: int,
                      start: date, last_day: date) -> list[tuple[date, Decimal]]:
    """Running total of the cash flows after disbursement (negative = paid), by day."""
    result = cost_mod.true_cost(product, Money.of(principal), tenor_days)
    running = Decimal(0)
    steps: list[tuple[date, Decimal]] = []
    for flow in sorted(result.flows, key=lambda f: f.day):
        if flow.day == 0:
            continue  # the proceeds: spent on the loan's purpose
        offset = int(flow.day.to_integral_value(rounding=ROUND_HALF_UP))
        running += flow.amount
        steps.append((min(start + timedelta(days=offset), last_day), running))
    return steps


def is_safe(product: FinancingProduct, principal: Decimal, tenor_days: int, start: date,
            band: ForecastBand, facts: Mapping[str, Decimal | None],
            purpose: str = "working_capital") -> bool:
    if principal <= 0 or not band.points:
        return False
    eligibility = evaluate(product, facts, Money.of(principal), tenor_days, purpose)
    if eligibility.status is EligibilityStatus.fail:
        return False
    steps = repayments_by_day(product, principal, tenor_days, start, band.points[-1].day)
    buffer = band.buffer.amount
    for point in band.points:
        paid = Decimal(0)
        for day, total in steps:
            if day <= point.day:
                paid = total
        if point.p10.amount + paid < buffer:
            return False
    return True


def _grid(value: Decimal, up: bool) -> Decimal:
    steps = value / STEP
    whole = steps.to_integral_value(rounding="ROUND_CEILING" if up else "ROUND_FLOOR")
    return whole * STEP


def ceiling(product: FinancingProduct, band: ForecastBand) -> Decimal:
    """No principal above the largest headroom over the buffer can be repaid inside it."""
    headroom = max(p.p10.amount - band.buffer.amount for p in band.points)
    top = headroom if product.max_amount is None else min(headroom, product.max_amount.amount)
    return _grid(top, up=False)


def safe_amount(product: FinancingProduct, tenor_days: int, start: date, band: ForecastBand,
                facts: Mapping[str, Decimal | None],
                purpose: str = "working_capital") -> SafeSize | None:
    """The largest safe principal on the grid, or None if even the smallest is not safe."""
    if product.kind not in LOAN_KINDS or not band.points:
        return None
    low = _grid(max(product.min_amount.amount if product.min_amount else STEP, STEP), up=True)
    high = ceiling(product, band)
    if high < low or not is_safe(product, low, tenor_days, start, band, facts, purpose):
        return None
    while high - low > 0:  # invariant: low is safe
        mid = _grid((low + high + STEP) / 2, up=False)
        if mid <= low:
            mid = low + STEP
        if is_safe(product, mid, tenor_days, start, band, facts, purpose):
            low = mid
        else:
            high = mid - STEP
    cap = product.max_amount.amount if product.max_amount is not None else None
    return SafeSize(product, low, capped=cap is not None and low + STEP > cap)


def confirm(product: FinancingProduct, amount: Decimal, tenor_days: int, start: date,
            band: ForecastBand, facts: Mapping[str, Decimal | None],
            purpose: str = "working_capital") -> bool:
    """The checker's test: `amount` is safe, and one more step is not (or is over the cap)."""
    if amount % STEP or not is_safe(product, amount, tenor_days, start, band, facts, purpose):
        return False
    above = amount + STEP
    if above > ceiling(product, band):
        return True
    return not is_safe(product, above, tenor_days, start, band, facts, purpose)
