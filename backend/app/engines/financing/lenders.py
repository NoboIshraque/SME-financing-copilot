"""Lender check from track record (WP-06 milestone 6; FEATURES N20).

Mesh events (WP-08) record what each lender quoted and what borrowers actually paid. The score
falls with every hidden fee, dispute and gap between quoted and realised cost; an unlicensed
lender scores zero whatever its history. Cold start: 60 ("no track record yet").
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.contracts import DataMode, LenderProfile, LicenceStatus

COLD_START_SCORE = Decimal(60)
FORMULA_ID = "financing.lender_score"


@dataclass(frozen=True)
class LenderEvent:
    lender_id: str
    quoted_apr: Decimal  # percent
    realised_apr: Decimal  # percent, from the actual cash flows
    disbursal_days: int
    hidden_fee: bool
    disputed: bool


def build_profile(
    lender_id: str,
    name: str,
    licence: LicenceStatus,
    events: Iterable[LenderEvent],
    *,
    regulator: str | None = None,
    data_mode: DataMode = DataMode.synthetic,
) -> LenderProfile:
    own = [e for e in events if e.lender_id == lender_id]
    gap = None
    days = None
    if own:
        gap = (sum((e.realised_apr - e.quoted_apr for e in own), Decimal(0)) / len(own)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        days = Decimal(str(median(e.disbursal_days for e in own)))
    return LenderProfile(
        lender_id=lender_id,
        name=name,
        licence_status=licence,
        regulator=regulator,
        events_count=len(own),
        quoted_vs_realised_apr_gap=gap,
        median_disbursal_days=days,
        hidden_fee_incidents=sum(1 for e in own if e.hidden_fee),
        disputes=sum(1 for e in own if e.disputed),
        data_mode=data_mode,
    )


def lender_score(profile: LenderProfile) -> Decimal:
    if profile.licence_status in (LicenceStatus.not_found, LicenceStatus.revoked):
        return Decimal(0)
    if profile.events_count == 0:
        return COLD_START_SCORE
    n = Decimal(profile.events_count)
    score = Decimal(100)
    score -= Decimal(50) * profile.hidden_fee_incidents / n
    score -= Decimal(30) * profile.disputes / n
    score -= Decimal(4) * max(Decimal(0), profile.quoted_vs_realised_apr_gap or Decimal(0))
    if profile.licence_status is LicenceStatus.unknown:
        score -= Decimal(15)
    return max(Decimal(0), score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
