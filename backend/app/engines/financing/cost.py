"""True cost of a financing option (WP-06 milestone 2).

Every option is turned into dated cash flows from the borrower's side:
  day 0: + principal - upfront fees - compulsory deposit
  later: - instalments (and + the deposit back at maturity)
The effective annual rate (EAR) is the rate r that makes the present value zero:
  sum(cf_i / (1 + r) ** (day_i / 365)) = 0
solved by bisection in Decimal arithmetic (deterministic, no floats).

Rate conventions (as Bangladeshi lenders publish them):
  reducing_balance  equal monthly instalments (EMI) at nominal/12 per month
  flat              interest = principal x rate x years, repaid in equal monthly instalments
  daily_debit       flat interest over the tenor, repaid in equal daily debits (nano loans)
  discount          receive face - face x rate x days/365 now, repay face at maturity
  none              no interest (owner top-up, netting, supplier term extension, grant)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from app.contracts import Fee, FeeKind, FeeTiming, FinancingProduct, Money, RateType

FORMULA_ID = "financing.effective_annual_rate"
FORMULA_VERSION = 1
DAYS_PER_YEAR = Decimal(365)
MONTH = DAYS_PER_YEAR / 12
HUNDRED = Decimal(100)
CENT = Decimal("0.01")


class CostError(ValueError):
    pass


@dataclass(frozen=True)
class CashFlow:
    day: Decimal  # days after disbursement (may be fractional: months are 365/12 days)
    amount: Decimal  # borrower's view: + received, - paid
    label: str


@dataclass(frozen=True)
class CostResult:
    product_id: str
    principal: Money
    tenor_days: int
    flows: tuple[CashFlow, ...]
    net_proceeds: Money  # cash actually usable on day 0
    total_repaid: Money
    total_cost: Money  # everything paid beyond the principal, fees included
    effective_annual_rate: Decimal  # percent, 2 dp

    @property
    def instalments(self) -> tuple[CashFlow, ...]:
        return tuple(f for f in self.flows if f.label == "instalment")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fee_amount(fee: Fee, principal: Decimal) -> Decimal:
    if fee.kind is FeeKind.fixed:
        return fee.value
    return principal * fee.value / HUNDRED


def months_in(tenor_days: int) -> int:
    months = int((Decimal(tenor_days) / MONTH).to_integral_value(rounding=ROUND_HALF_UP))
    return max(months, 1)


def build_flows(product: FinancingProduct, principal: Decimal, tenor_days: int) -> list[CashFlow]:
    if principal <= 0:
        raise CostError("principal must be positive")
    if tenor_days <= 0:
        raise CostError("tenor must be at least one day")
    rate = product.nominal_rate_pa / HUNDRED
    years = Decimal(tenor_days) / DAYS_PER_YEAR
    flows: list[CashFlow] = []

    upfront = Decimal(0)
    deposit = Decimal(0)
    periodic_fees: list[Fee] = []
    maturity_fees = Decimal(0)
    for fee in product.fees:
        if fee.kind is FeeKind.compulsory_deposit_percent:
            deposit += principal * fee.value / HUNDRED
        elif fee.timing is FeeTiming.upfront:
            upfront += _fee_amount(fee, principal)
        elif fee.timing is FeeTiming.periodic:
            periodic_fees.append(fee)
        else:
            maturity_fees += _fee_amount(fee, principal)

    rate_type = product.rate_type
    if rate_type is RateType.discount:
        discount = principal * rate * years
        flows.append(CashFlow(Decimal(0), principal - discount - upfront - deposit, "proceeds"))
        flows.append(CashFlow(Decimal(tenor_days), -principal, "repayment"))
    else:
        flows.append(CashFlow(Decimal(0), principal - upfront - deposit, "proceeds"))
        if rate_type is RateType.reducing_balance:
            n = months_in(tenor_days)
            monthly = rate / 12
            if monthly == 0:
                emi = principal / n
            else:
                growth = (1 + monthly) ** n
                emi = principal * monthly * growth / (growth - 1)
            flows += [CashFlow(MONTH * k, -emi, "instalment") for k in range(1, n + 1)]
        elif rate_type is RateType.flat:
            n = months_in(tenor_days)
            total = principal * (1 + rate * Decimal(n) / 12)
            flows += [CashFlow(MONTH * k, -total / n, "instalment") for k in range(1, n + 1)]
        elif rate_type is RateType.daily_debit:
            total = principal * (1 + rate * years)
            flows += [CashFlow(Decimal(d), -total / tenor_days, "instalment")
                      for d in range(1, tenor_days + 1)]
        elif rate_type is RateType.none:
            flows.append(CashFlow(Decimal(tenor_days), -principal, "repayment"))
        else:  # pragma: no cover - enum is exhaustive
            raise CostError(f"unsupported rate type {rate_type}")

    for fee in periodic_fees:
        amount = _fee_amount(fee, principal)
        flows += [CashFlow(MONTH * k, -amount, "fee") for k in range(1, months_in(tenor_days) + 1)]
    if maturity_fees:
        flows.append(CashFlow(Decimal(tenor_days), -maturity_fees, "fee"))
    if deposit:
        flows.append(CashFlow(Decimal(tenor_days), deposit, "deposit_returned"))
    return flows


def present_value(flows: list[CashFlow] | tuple[CashFlow, ...], annual_rate: Decimal) -> Decimal:
    """Sum of discounted flows. Whole days and whole months use integer powers of a per-day /
    per-month factor (fast and exact to precision); anything else uses a fractional power."""
    base = 1 + annual_rate
    per_day = base ** (1 / DAYS_PER_YEAR)
    per_month = base ** (Decimal(1) / 12)
    total = Decimal(0)
    for f in flows:
        months = f.day / MONTH
        if f.day == f.day.to_integral_value():
            factor = per_day ** int(f.day)
        elif months == months.to_integral_value():
            factor = per_month ** int(months)
        else:
            factor = base ** (f.day / DAYS_PER_YEAR)
        total += f.amount / factor
    return total


def effective_annual_rate(flows: list[CashFlow] | tuple[CashFlow, ...]) -> Decimal:
    """EAR as a fraction (0.1268 = 12.68%). Bisection: robust and deterministic."""
    if not any(f.amount > 0 for f in flows) or not any(f.amount < 0 for f in flows):
        raise CostError("cash flows need money in and money out")
    with localcontext() as ctx:
        ctx.prec = 34
        if sum(f.amount for f in flows) >= 0:
            return Decimal(0)  # repaying no more than received: costless
        low, high = Decimal(0), Decimal(1)
        while present_value(flows, high) < 0:
            high *= 2
            if high > 10**6:
                raise CostError("effective rate above 100,000,000% - check the inputs")
        for _ in range(200):
            mid = (low + high) / 2
            if present_value(flows, mid) < 0:
                low = mid
            else:
                high = mid
            if high - low < Decimal("1e-12"):
                break
        return (low + high) / 2


def true_cost(product: FinancingProduct, principal: Money, tenor_days: int) -> CostResult:
    flows = build_flows(product, principal.amount, tenor_days)
    proceeds = flows[0].amount
    repaid = -sum((f.amount for f in flows[1:] if f.amount < 0), Decimal(0))
    returned = sum((f.amount for f in flows[1:] if f.amount > 0), Decimal(0))
    total_cost = repaid - returned - proceeds
    ear = effective_annual_rate(flows)
    return CostResult(
        product_id=product.id,
        principal=principal,
        tenor_days=tenor_days,
        flows=tuple(flows),
        net_proceeds=Money.of(_q(proceeds)),
        total_repaid=Money.of(_q(repaid)),
        total_cost=Money.of(_q(total_cost)),
        effective_annual_rate=_q(ear * HUNDRED),
    )


def early_pay_discount_cost(discount_percent: Decimal, days_early: int) -> Decimal:
    """Annualised cost (percent) of giving `discount_percent` off to be paid `days_early` sooner.

    Used by WP-05: offer the discount only if this is below the best financing EAR.
    """
    if not (Decimal(0) < discount_percent < HUNDRED):
        raise CostError("discount must be between 0 and 100 percent")
    if days_early <= 0:
        raise CostError("days_early must be positive")
    d = discount_percent / HUNDRED
    with localcontext() as ctx:
        ctx.prec = 34
        ear = (1 / (1 - d)) ** (DAYS_PER_YEAR / Decimal(days_early)) - 1
    return _q(ear * HUNDRED)
