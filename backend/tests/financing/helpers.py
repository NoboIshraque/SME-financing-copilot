from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.contracts import (
    DataMode,
    Fee,
    FinancingNeed,
    FinancingProduct,
    ForecastBand,
    ForecastPoint,
    Money,
)

START = date(2026, 10, 1)


def product(pid="p", kind="working_capital", rate_type="reducing_balance", rate="12", fees=(),
            rules=(), **extra) -> FinancingProduct:
    return FinancingProduct(
        id=pid, provider=extra.pop("provider", f"prov-{pid}"), name=pid, kind=kind,
        rate_type=rate_type, nominal_rate_pa=Decimal(rate),
        fees=tuple(Fee(**f) if isinstance(f, dict) else f for f in fees), rules=rules,
        is_modelled=True, rate_basis="modelled", data_mode=DataMode.synthetic, **extra,
    )


def need(amount=100000, tenor=365) -> FinancingNeed:
    return FinancingNeed(tenant_id="sme_grocery", amount=Money.of(amount),
                         needed_by=START + timedelta(days=5), tenor_days=tenor)


def band(p50=200000, spread=40000, buffer=100000, days=120, dip=None) -> ForecastBand:
    """A flat forecast; `dip` = (start_offset, end_offset, amount) lowers P50 in a window."""
    points = []
    for i in range(1, days + 1):
        mid = Decimal(p50)
        if dip and dip[0] <= i <= dip[1]:
            mid -= Decimal(dip[2])
        points.append(ForecastPoint(day=START + timedelta(days=i), p10=Money.of(mid - spread),
                                    p50=Money.of(mid), p90=Money.of(mid + spread),
                                    p_below_buffer=Decimal("0.0")))
    return ForecastBand(tenant_id="sme_grocery", as_of=START, horizon_days=days, paths=1000,
                        seed=1, opening_balance=Money.of(p50), buffer=Money.of(buffer),
                        points=tuple(points), data_mode=DataMode.synthetic,
                        generated_at=datetime(2026, 10, 1, tzinfo=UTC))
