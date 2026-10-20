"""Vendor ranking by landed cost (WP-09 milestone 3, FEATURES N3).

    landed cost per unit = quoted price
                         + delivery cost / quantity
                         + waiting cost: price * (lead days + expected late days) * APR / 365
                         + reliability penalty: price * (1 - on-time share) * RELIABILITY_SHARE

The on-time share is the shop's own history with that supplier: the share of its settled bills
settled by their due date (delivery dates are not recorded, so this is the only reliability
signal on file). Expected late days = (1 - on-time share) * LATE_DAYS. A supplier with no settled
bill gets no penalty and says so (`on_time_rate` null).

Quotes for the demo shops are generated (synthetic, labelled so): for each of the shop's real
ledger suppliers, a price within -6%..+4% of today's TCB price, a delivery charge and a lead time,
all derived from a hash of (shop, supplier, item) so the same request gives the same quotes.
Ranking is by landed cost, ties broken by the supplier label, so it does not depend on the order
the quotes arrive in.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import Bill, DataMode, Figure, Money, Provenance, Unit, VendorQuote

RELIABILITY_SHARE = Decimal("0.05")
LATE_DAYS = Decimal(3)
DAYS_PER_YEAR = Decimal(365)
HUNDRED = Decimal(100)
CENT = Decimal("0.01")
MAX_SUPPLIERS = 4

EXPRESSIONS = {
    "market.landed_cost_per_unit": "price + delivery / quantity + waiting cost + reliability "
                                   "penalty",
    "market.unit_price": "quoted price per unit",
    "market.delivery_per_unit": "delivery cost / quantity",
    "market.delay_cost": "price * (lead days + (1 - on-time share) * 3) * APR / 100 / 365",
    "market.reliability_penalty": "price * (1 - on-time share) * 0.05",
}


@dataclass(frozen=True)
class Ranked:
    rank: int
    label: str
    quote: VendorQuote
    landed_cost: Figure
    breakdown: tuple[Figure, ...]


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def on_time_rate(bills: Iterable[Bill], supplier: str) -> Decimal | None:
    """Share of this supplier's settled bills that were settled by their due date."""
    settled = [b for b in bills if b.counterparty_token == supplier and b.paid_date is not None]
    if not settled:
        return None
    on_time = sum(1 for b in settled if b.paid_date is not None and b.paid_date <= b.due_date)
    return (Decimal(on_time) / Decimal(len(settled))).quantize(Decimal("0.01"))


def main_suppliers(bills: Sequence[Bill], limit: int = MAX_SUPPLIERS) -> list[str]:
    """The shop's suppliers with the most bills (ties by token), at most `limit`."""
    counts: dict[str, int] = {}
    for bill in bills:
        counts[bill.counterparty_token] = counts.get(bill.counterparty_token, 0) + 1
    return [token for token, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]


def _unit_hash(*parts: str) -> Decimal:
    """A stable number in [0, 1) from the parts."""
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return Decimal(int.from_bytes(digest[:4], "big")) / Decimal(2**32)


def synthetic_quotes(tenant_id: str, suppliers: Sequence[str], commodity: str, unit: str,
                     market_price: Money, bills: Sequence[Bill], quoted_on: date
                     ) -> list[VendorQuote]:
    """Generated quotes from the shop's real ledger suppliers (demo shops only; synthetic)."""
    quotes = []
    for supplier in suppliers:
        h = _unit_hash(tenant_id, supplier, commodity)
        price = _q(market_price.amount * (Decimal("0.94") + Decimal("0.10") * h))
        delivery = Decimal(int(_unit_hash(supplier, "delivery") * 10) * 100)  # 0..900 taka
        lead = int(_unit_hash(supplier, "lead") * 5)  # 0..4 days
        quotes.append(VendorQuote(
            vendor_token=supplier, commodity=commodity, unit=unit,
            unit_price=Money.of(price), delivery_cost=Money.of(delivery), lead_time_days=lead,
            on_time_rate=on_time_rate(bills, supplier), quoted_on=quoted_on,
            data_mode=DataMode.synthetic))
    return quotes


def rank(quotes: Sequence[VendorQuote], labels: dict[str, str], quantity: Decimal,
         apr_percent: Decimal, apr_ref: str, data_mode: DataMode) -> list[Ranked]:
    """Quotes ranked by landed cost per unit, each with its breakdown as Figures."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    rows = []
    for quote in quotes:
        price = quote.unit_price.amount
        on_time = quote.on_time_rate
        miss = Decimal(1) - on_time if on_time is not None else Decimal(0)
        parts = {
            "unit_price": _q(price),
            "delivery_per_unit": _q(quote.delivery_cost.amount / quantity),
            "delay_cost": _q(price * (Decimal(quote.lead_time_days) + miss * LATE_DAYS)
                             * apr_percent / HUNDRED / DAYS_PER_YEAR),
            "reliability_penalty": _q(price * miss * RELIABILITY_SHARE),
        }
        params = {"vendor_token": quote.vendor_token, "quantity": str(quantity),
                  "unit_price": str(price), "delivery_cost": str(quote.delivery_cost.amount),
                  "lead_time_days": str(quote.lead_time_days),
                  "on_time_rate": str(on_time) if on_time is not None else "no_history",
                  "apr_percent": str(apr_percent), "quoted_on": quote.quoted_on.isoformat()}
        refs = (f"quote:{quote.vendor_token}:{quote.commodity}:{quote.quoted_on.isoformat()}",
                apr_ref)
        mode = DataMode.synthetic if DataMode.synthetic in (data_mode, quote.data_mode) \
            else data_mode

        def fig(name: str, formula: str, value: Decimal, quote: VendorQuote = quote,
                params: dict[str, str] = params, refs: tuple[str, ...] = refs,
                mode: DataMode = mode) -> Figure:
            return Figure(
                id=f"market:{name}:{quote.vendor_token}:{quote.commodity}:{quantity}:"
                   f"{apr_percent}:{quote.quoted_on.isoformat()}",
                label_key=f"market.{name}", value=value, unit=Unit.BDT, data_mode=mode,
                provenance=Provenance(formula_id=formula, formula_version=1,
                                      source_row_ids=refs, parameters=params))

        breakdown = tuple(fig(name, f"market.{name}", value) for name, value in parts.items())
        landed = fig("landed_cost", "market.landed_cost_per_unit", sum(parts.values(),
                                                                       Decimal(0)))
        rows.append((landed.value, labels[quote.vendor_token], quote, landed, breakdown))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [Ranked(i, label, quote, landed, breakdown)
            for i, (_, label, quote, landed, breakdown) in enumerate(rows, start=1)]
