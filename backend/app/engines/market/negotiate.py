"""Negotiation engine (WP-09 milestone 4, FEATURES N19): walk-away, target and a script.

The shop sells `quantity` units to a buyer who offers `offer` per unit and pays after
`payment_days`. Its cash price is today's public market price (TCB midpoint); its cost of money is
the best effective APR among the financing options it is eligible for (WP-06).

    credit factor   f = APR / 100 * payment_days / 365
    credit cost     = market price * f                         (per unit)
    walk-away       W = market price * (1 + f)
        selling on credit below W earns less than selling for cash today at the market price
    market ceiling  H = TCB high * (1 + f)          (the top of today's market, on credit)
    target          T = max(offer, W + TARGET_SHARE * (H - W))
    opening ask     O = max(H, T)

So O >= T >= W always: the plan never recommends terms worse than walk-away. When the buyer pays
later than a week, the script also prices a discount for paying on delivery: DISCOUNT_SHARE of the
credit factor, which costs the shop less per month than borrowing at its APR.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.contracts import DataMode, Figure, PricePoint, Provenance, Unit

TARGET_SHARE = Decimal("0.5")
DISCOUNT_SHARE = Decimal("0.8")
DAYS_PER_YEAR = Decimal(365)
MONTH_DAYS = Decimal(30)
HUNDRED = Decimal(100)
CENT = Decimal("0.01")

EXPRESSIONS = {
    "negotiation.walk_away": "market price * (1 + APR / 100 * payment_days / 365)",
    "negotiation.credit_cost": "market price * APR / 100 * payment_days / 365",
    "negotiation.target": "max(offer, walk-away + 0.5 * (market high on credit - walk-away))",
    "negotiation.target_price": "max(offer, walk-away + 0.5 * (market high on credit - walk-away))",
    "negotiation.open": "max(market high * (1 + APR / 100 * payment_days / 365), target)",
    "negotiation.discount": "0.8 * APR * payment_days / 365",
    "negotiation.discount_monthly_cost": "discount * 30 / payment_days",
    "negotiation.loan_monthly_cost": "APR / 12",
}


@dataclass(frozen=True)
class Step:
    text_key: str
    figures: tuple[Figure, ...]


@dataclass(frozen=True)
class Plan:
    walk_away: Figure
    target: Figure
    steps: tuple[Step, ...]


def _up(value: Decimal) -> Decimal:
    """Prices the shop asks for round up to the paisa, so rounding never lands below a floor."""
    return value.quantize(CENT, rounding=ROUND_CEILING)


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def plan(*, market: PricePoint, market_ref: str, offer: Decimal, quantity: Decimal,
         payment_days: int, apr_percent: Decimal, apr_ref: str,
         data_mode: DataMode) -> Plan:
    """Walk-away, target and script for one sale (see the module docstring for the formulas)."""
    if offer <= 0 or quantity <= 0 or payment_days < 0 or apr_percent < 0:
        raise ValueError("offer and quantity must be positive, days and APR not negative")
    mid = market.price.amount
    high = market.high.amount if market.high is not None else mid
    factor = apr_percent / HUNDRED * Decimal(payment_days) / DAYS_PER_YEAR
    walk = _up(mid * (1 + factor))
    ceiling = _up(high * (1 + factor))
    target = max(_up(offer), _up(walk + TARGET_SHARE * (ceiling - walk)))
    opening = max(ceiling, target)
    credit_cost = _round(mid * factor)

    params = {"market_price": str(mid), "market_high": str(high), "offer": str(offer),
              "quantity": str(quantity), "payment_days": str(payment_days),
              "apr_percent": str(apr_percent), "source": market.source.value,
              "observed_on": market.observed_on.isoformat()}
    rows = (market_ref, apr_ref)

    def fig(name: str, label: str, value: Decimal, unit: Unit = Unit.BDT) -> Figure:
        return Figure(id=f"negotiation:{name}:{market.commodity}:{payment_days}:{offer}:"
                         f"{quantity}:{apr_percent}:{market.observed_on.isoformat()}",
                      label_key=label, value=value, unit=unit, data_mode=data_mode,
                      provenance=Provenance(formula_id=f"negotiation.{name}", formula_version=1,
                                            source_row_ids=rows, parameters=params))

    walk_fig = fig("walk_away", "negotiation.walk_away", walk)
    target_fig = fig("target", "negotiation.target", target)
    steps = [Step("negotiation.step.open_high", (fig("open", "negotiation.price", opening),)),
             Step("negotiation.step.trade_term",
                  (fig("target_price", "negotiation.price", target),
                   fig("credit_cost", "negotiation.credit_cost", credit_cost)))]
    if payment_days > 7:
        discount = _round(DISCOUNT_SHARE * factor * HUNDRED)
        steps.append(Step("negotiation.step.discount_for_speed", (
            fig("discount", "negotiation.discount", discount, Unit.percent),
            fig("discount_monthly_cost", "negotiation.monthly_cost",
                _round(discount * MONTH_DAYS / Decimal(payment_days)), Unit.percent),
            fig("loan_monthly_cost", "negotiation.loan_monthly_cost",
                _round(apr_percent / 12), Unit.percent))))
    steps.append(Step("negotiation.step.walk_away", (walk_fig,)))
    return Plan(walk_away=walk_fig, target=target_fig, steps=tuple(steps))
