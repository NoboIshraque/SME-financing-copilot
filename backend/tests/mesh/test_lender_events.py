"""Lender events from peer-verified repayments, feeding WP-06 lender scores (WP-08 milestone 7)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.contracts import AttestationKind, DataMode, LicenceStatus, Money, ObligationStatus
from app.engines.financing.lenders import COLD_START_SCORE, lender_score
from app.engines.financing.ranking import match
from app.engines.mesh.attestations import attest
from app.engines.mesh.lender_events import (
    SKIP_NO_REPAYMENTS,
    SKIP_OPEN,
    SKIP_UNATTESTED,
    LenderInfo,
    LoanRecord,
    Repayment,
    lender_event,
    lender_events,
    lender_profiles,
    realised_apr,
)
from tests.financing.helpers import START, need, product
from tests.mesh.helpers import NOW, ob

BORROWER = "sme_grocery"
DISBURSED = date(2026, 1, 10)


def _loan(loan_id="L1", lender="lender_a", *, received=99000, quoted="12.87", repay=101000,
          days=30, n=1, applied_days=3, fees=1000):
    reps = tuple(Repayment(f"{loan_id}-r{i}", DISBURSED + timedelta(days=days * i),
                           Money.of(repay)) for i in range(1, n + 1))
    return LoanRecord(loan_id=loan_id, lender_id=lender, borrower_tenant=BORROWER,
                      principal=Money.of(100000), quoted_apr=Decimal(quoted),
                      disclosed_upfront_fees=Money.of(fees),
                      applied_on=DISBURSED - timedelta(days=applied_days), disbursed_on=DISBURSED,
                      received=Money.of(received), repayments=reps)


def _ledger(loan, *, settled=True, confirm_by=(BORROWER, None), dispute=False):
    """Mesh obligations for the loan's repayments, attested while open, then settled."""
    obligations, attestations = {}, []
    for r in loan.repayments:
        o = ob(r.obligation_id, BORROWER, loan.lender_id, r.amount.amount)
        for who in confirm_by:
            attestations.append(attest(o, who or loan.lender_id, AttestationKind.confirm,
                                       attestation_id=f"a-{r.obligation_id}-{who}", now=NOW))
        if dispute:
            attestations.append(attest(o, BORROWER, AttestationKind.dispute,
                                       attestation_id=f"d-{r.obligation_id}", now=NOW))
        status = ObligationStatus.settled if settled else ObligationStatus.open
        obligations[o.id] = o.model_copy(update={"status": status})
    return obligations, attestations


def test_realised_rate_is_the_effective_annual_rate_of_the_actual_cash_flows():
    # Tk 99,000 received, Tk 101,000 repaid 30 days later.
    expected = (101000 / 99000) ** (365 / 30) - 1
    assert realised_apr(_loan()) == Decimal(str(round(expected * 100, 2)))
    # Tk 100,000 in, Tk 112,000 back after exactly a year: 12.00%.
    assert realised_apr(_loan(received=100000, repay=112000, days=365, fees=0)) == Decimal("12.00")


def test_an_honest_loan_becomes_an_event_even_though_attested_before_it_settled():
    loan = _loan()
    obligations, attestations = _ledger(loan)

    event = lender_event(loan, obligations, attestations)

    assert event.lender_id == "lender_a" and event.disbursal_days == 3
    assert event.hidden_fee is False and event.disputed is False
    assert event.realised_apr == realised_apr(loan)


@pytest.mark.parametrize(("received", "hidden"), [
    (99000, False),      # principal 100,000 minus the disclosed 1,000 fee
    ("98999.50", False),  # 50 paisa short: rounding, within the Tk 1 tolerance
    (97000, True),       # 2,000 more withheld than disclosed
])
def test_a_hidden_fee_is_cash_withheld_beyond_the_disclosed_fees(received, hidden):
    loan = _loan(received=received)
    event = lender_event(loan, *_ledger(loan))
    assert event.hidden_fee is hidden


def test_a_dispute_counts_against_the_lender_without_using_the_contested_figures():
    loan = _loan(received=90000)  # would look like a hidden fee, but the record is contested
    event = lender_event(loan, *_ledger(loan, dispute=True))
    assert event.disputed is True
    assert event.hidden_fee is False and event.realised_apr == loan.quoted_apr


@pytest.mark.parametrize(("loan", "ledger_kwargs", "reason"), [
    (_loan(), {"settled": False}, SKIP_OPEN),                       # still being repaid
    (_loan(), {"confirm_by": (BORROWER,)}, SKIP_UNATTESTED),        # lender never confirmed
    (_loan(n=0), {}, SKIP_NO_REPAYMENTS),
])
def test_unverifiable_loans_are_skipped_with_a_reason(loan, ledger_kwargs, reason):
    result = lender_events([loan], *_ledger(loan, **ledger_kwargs))
    assert result.events == () and result.skipped == {loan.loan_id: reason}


def test_profiles_from_events_change_scores_and_wp06_ranking():
    clean = [_loan(f"A{i}", "lender_a") for i in range(2)]
    shady = [_loan("B1", "lender_b", received=95000)]
    obligations, attestations = {}, []
    for loan in clean + shady:
        o, a = _ledger(loan)
        obligations.update(o)
        attestations += a
    events = lender_events(clean + shady, obligations, attestations).events
    registry = {k: LenderInfo(k, LicenceStatus.licensed, "Bangladesh Bank")
                for k in ("lender_a", "lender_b", "lender_c")}

    profiles = lender_profiles(registry, events, data_mode=DataMode.synthetic)

    assert profiles["lender_b"].hidden_fee_incidents == 1
    assert lender_score(profiles["lender_a"]) > lender_score(profiles["lender_b"])
    assert lender_score(profiles["lender_c"]) == COLD_START_SCORE
    # Same product terms from both lenders: the track record decides the order in WP-06.
    a, b = product("pa", provider="lender_a"), product("pb", provider="lender_b")
    ranked = match(need(), [b, a], {"business_age_months": Decimal(36)}, start=START,
                   lenders=profiles)
    assert [c.option.product.id for c in ranked] == ["pa", "pb"]

