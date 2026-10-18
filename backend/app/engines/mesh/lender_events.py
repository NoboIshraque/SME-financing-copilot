"""Lender events from peer-verified repayment records (WP-08 milestone 7; FEATURES N20).

A loan's track record is only as good as its evidence. A loan becomes a WP-06 `LenderEvent`
only when it is fully repaid and every repayment obligation is attested by both the borrower and
the lender in the mesh. Then:

- realised APR = the effective annual rate (WP-06 engine, the same bisection) of the cash the
  borrower actually received and actually repaid, by date;
- hidden fee = the borrower received less than the principal minus the fees disclosed up front
  (tolerance Tk 1 for rounding);
- disputed = any party filed a `dispute` attestation on one of the loan's obligations.

`quoted_apr` must be the effective annual rate shown at offer time (WP-06 `effective_apr`), so
quoted and realised are the same measure. Loans that are still open, or whose repayments are not
attested, are skipped with a reason: no track record is better than an unverified one. Events
carry the lender id only, never the borrower.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import (
    Attestation,
    AttestationKind,
    DataMode,
    LenderProfile,
    LicenceStatus,
    MeshObligation,
    Money,
    ObligationStatus,
)
from app.engines.financing.cost import CashFlow, effective_annual_rate
from app.engines.financing.lenders import LenderEvent, build_profile
from app.engines.mesh.attestations import is_peer_verified

HIDDEN_FEE_TOLERANCE = Decimal("1.00")
SKIP_OPEN = "lender_event.loan_not_fully_repaid"
SKIP_UNATTESTED = "lender_event.repayments_not_peer_verified"
SKIP_NO_REPAYMENTS = "lender_event.no_repayments"


@dataclass(frozen=True)
class Repayment:
    obligation_id: str  # the mesh obligation borrower -> lender this payment discharged
    paid_on: date
    amount: Money


@dataclass(frozen=True)
class LoanRecord:
    loan_id: str
    lender_id: str  # = FinancingProduct.provider, the key WP-06 ranking looks profiles up by
    borrower_tenant: str
    principal: Money
    quoted_apr: Decimal  # percent: WP-06 effective_apr shown at offer time
    disclosed_upfront_fees: Money
    applied_on: date
    disbursed_on: date
    received: Money  # cash that actually reached the borrower at disbursal
    repayments: tuple[Repayment, ...]


@dataclass(frozen=True)
class EventsResult:
    events: tuple[LenderEvent, ...]
    skipped: dict[str, str]  # loan_id -> reason key


def realised_apr(loan: LoanRecord) -> Decimal:
    """Effective annual rate (percent, 2 dp) of the borrower's actual cash flows."""
    flows = [CashFlow(Decimal(0), loan.received.amount, "received")]
    flows += [CashFlow(Decimal((r.paid_on - loan.disbursed_on).days), -r.amount.amount,
                       f"repayment {r.obligation_id}") for r in loan.repayments]
    rate = effective_annual_rate(flows) * 100
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def lender_event(
    loan: LoanRecord,
    obligations: Mapping[str, MeshObligation],
    attestations: Sequence[Attestation],
) -> LenderEvent | str:
    """The event for one loan, or the reason key it was skipped."""
    if not loan.repayments:
        return SKIP_NO_REPAYMENTS
    own = [obligations.get(r.obligation_id) for r in loan.repayments]
    if any(o is None for o in own):
        return SKIP_OPEN
    ids = {r.obligation_id for r in loan.repayments}
    disputed = (any(a.kind is AttestationKind.dispute and a.obligation_id in ids
                    for a in attestations)
                or any(o.status is ObligationStatus.disputed for o in own if o is not None))
    days = (loan.disbursed_on - loan.applied_on).days
    if disputed:
        # A dispute counts against the lender on its own; the contested amounts are not used to
        # claim a cost gap or a hidden fee.
        return LenderEvent(lender_id=loan.lender_id, quoted_apr=loan.quoted_apr,
                           realised_apr=loan.quoted_apr, disbursal_days=days, hidden_fee=False,
                           disputed=True)
    if any(o.status is not ObligationStatus.settled for o in own if o is not None):
        return SKIP_OPEN
    if not all(is_peer_verified(o, attestations) for o in own if o is not None):
        return SKIP_UNATTESTED
    expected = loan.principal - loan.disclosed_upfront_fees
    hidden = (expected - loan.received).amount > HIDDEN_FEE_TOLERANCE
    return LenderEvent(
        lender_id=loan.lender_id,
        quoted_apr=loan.quoted_apr,
        realised_apr=realised_apr(loan),
        disbursal_days=days,
        hidden_fee=hidden,
        disputed=False,
    )


def lender_events(
    loans: Iterable[LoanRecord],
    obligations: Mapping[str, MeshObligation],
    attestations: Sequence[Attestation],
) -> EventsResult:
    events, skipped = [], {}
    for loan in loans:
        result = lender_event(loan, obligations, attestations)
        if isinstance(result, str):
            skipped[loan.loan_id] = result
        else:
            events.append(result)
    return EventsResult(tuple(events), skipped)


@dataclass(frozen=True)
class LenderInfo:
    name: str
    licence: LicenceStatus
    regulator: str | None = None


def lender_profiles(
    registry: Mapping[str, LenderInfo],
    events: Iterable[LenderEvent],
    *,
    data_mode: DataMode,
) -> dict[str, LenderProfile]:
    """WP-06 profiles for every registered lender (no events = cold start, score 60)."""
    events = tuple(events)
    return {
        lender_id: build_profile(lender_id, info.name, info.licence, events,
                                 regulator=info.regulator, data_mode=data_mode)
        for lender_id, info in registry.items()
    }
