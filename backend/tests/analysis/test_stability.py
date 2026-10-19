"""Decision stability (WP-07 milestone 5): stress may flip a decision, noise never may."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts import (
    DataMode,
    FinancingProduct,
    Frequency,
    Money,
    ObligationKind,
    ProductKind,
    RateBasis,
    RateType,
    RecurringObligation,
    TxCategory,
    VariationKind,
)
from app.engines.analysis.scenarios import (
    Assumptions,
    compare_decisions,
    prepare,
)
from app.engines.analysis.stability import (
    EngineDecider,
    Request,
    engine_stability,
    reformat_dates,
    rename_parties,
    reword,
    shuffle_rows,
    stability,
    stresses,
)
from app.engines.cash.calendar import load_festivals
from tests.analysis.helpers import T, bill, invoice, ledger, out, txn

D = Decimal
C = TxCategory
NOW = datetime(2026, 3, 1, 18, 0, tzinfo=UTC)
FESTIVALS = load_festivals()
CALM = Assumptions(sales_sd_pct=D(0), input_price_sd_pct=D(0), delay_days=(0,),
                   delay_weights_pct=(100,), rate_pp_max=D(0), shock_probability_pct=D(0))
CUSTOMER = "PARTY_cust000001"
STRESS_NAMES = ["late_payer", "sales_minus_10", "sales_minus_20", "inputs_plus_8",
                "rates_plus_2pp", "surprise_bill"]
NOISE_NAMES = ["rows_shuffled", "parties_renamed", "question_reworded", "dates_shifted_format"]
NANO = FinancingProduct(id="test-nano", provider="Test MFI", name="Nano",
                        kind=ProductKind.nano_loan, rate_type=RateType.reducing_balance,
                        nominal_rate_pa=D(24), rate_basis=RateBasis.modelled, is_modelled=True,
                        data_mode=DataMode.synthetic)


def _rent(amount):
    return RecurringObligation(id=f"{T}:OBL-rent", tenant_id=T, kind=ObligationKind.rent,
                               counterparty_token="PARTY_land000001", amount=Money.of(amount),
                               frequency=Frequency.monthly, day_of_period=5,
                               start_date=date(2026, 1, 1), source_ref="obligations.csv#L2",
                               data_mode=DataMode.synthetic)


def _shop():
    """Sales of 1,000 a day from 1 January to 1 March, rent of 20,000 on the 5th, and one
    customer who pays 5 days late and owes 20,000 due on 10 March. Opening on 2 March:
    10,000 + 60,000 - 2 x 20,000 = 30,000; the lowest balance is 14,000 after rent on 5 March."""
    sales = [txn(date(2026, 1, 1) + timedelta(days=n), 1000) for n in range(60)]
    rent = [out(date(2026, m, 5), 20000, C.rent) for m in (1, 2)]
    paid = invoice("I-0", date(2026, 1, 1), date(2026, 1, 15), 5000, paid=5000,
                   paid_date=date(2026, 1, 20), party=CUSTOMER)
    owed = invoice("I-1", date(2026, 2, 20), date(2026, 3, 10), 20000, party=CUSTOMER)
    return ledger([*sales, *rent], [paid, owed], obligations=[_rent(20000)])


def _decider(**kw):
    return EngineDecider(FESTIVALS, D(5000), NOW, names=("do_nothing", "offer_discount"),
                         assumptions=CALM, paths=200, **kw)


@pytest.fixture(scope="module")
def quiet():
    return engine_stability("rec_quiet", Request(_shop(), "Should I offer a discount?"),
                            _decider())


def test_a_stress_flip_is_reported(quiet):
    report = quiet.report
    # nothing dips below 5,000, so keeping the full 20,000 wins; a surprise bill of a month's
    # rent on 8 March takes cash to -3,000 unless the discounted 19,600 came in on 3 March
    assert report.baseline_choice == "do_nothing"
    assert report.what_would_flip == ("surprise_bill",)
    flipped = next(r for r in report.results if r.name == "surprise_bill")
    assert (flipped.choice, flipped.held) == ("offer_discount", False)
    assert report.score == D("0.9000")  # 9 of 10 held
    assert not report.unreliable


def test_every_variation_is_run_once_in_a_fixed_order(quiet):
    report = quiet.report
    assert [r.name for r in report.results] == STRESS_NAMES + NOISE_NAMES
    assert Counter(r.kind for r in report.results) == {VariationKind.stress: 6,
                                                       VariationKind.noise: 4}
    assert quiet.skipped == ()
    params = quiet.figure.provenance.parameters
    assert quiet.figure.value == report.score
    assert (params["recommendation_id"], params["held"], params["flipped"]) == (
        "rec_quiet", "9", "surprise_bill")


def test_a_stress_that_does_not_apply_is_left_out():
    shop = ledger([txn(date(2026, 1, 1) + timedelta(days=n), 1000) for n in range(60)])
    result = engine_stability("rec_x", Request(shop), _decider())
    assert result.skipped == ("late_payer", "surprise_bill")  # no invoices, no costs at all
    assert len(result.report.results) == 8
    assert result.report.score == 1


def test_a_noise_flip_makes_the_advice_unreliable():
    """A decision function that reads row order (as a careless agent might)."""
    def first_row(request, _shift):
        return ",".join(t.id for t in request.ledger.transactions[:3])

    shop = _shop()
    stress, _skipped = stresses(prepare(shop, FESTIVALS, D(5000), NOW, paths=200))
    result = stability("rec_bad", Request(shop, "Which?"), first_row, stress)
    report = result.report
    assert [r.name for r in report.results if not r.held] == ["rows_shuffled"]
    assert report.unreliable and report.noise_flips == 1
    assert report.what_would_flip == ()  # noise flips are not "what would flip this"
    assert report.score == D("0.9000")


def test_a_reworded_question_flips_an_agent_that_reads_the_wording():
    question = "Should I borrow on 2026-03-02?"

    def literal(request, _shift):
        return "borrow" if request.question == question else "wait"

    result = stability("rec_words", Request(_shop(), question), literal, [])
    flipped = [r.name for r in result.report.results if not r.held]
    assert flipped == ["question_reworded", "dates_shifted_format"]
    assert result.report.unreliable and result.report.score == D("0.5000")


def test_noise_transforms_change_form_not_content():
    shop = _shop()
    shuffled = shuffle_rows(shop, 1)
    assert shuffled.transactions != shop.transactions
    assert Counter(shuffled.transactions) == Counter(shop.transactions)
    renamed = rename_parties(shop, 1)
    tokens = {i.counterparty_token for i in renamed.invoices}
    assert len(tokens) == 1 and tokens != {CUSTOMER}  # both invoices: the same new name
    assert renamed.obligations[0].counterparty_token != "PARTY_land000001"
    assert reformat_dates("Pay on 2026-03-02?", date(2026, 3, 1)) == "Pay on 2 Mar 2026?"
    assert reformat_dates("Pay now?", date(2026, 3, 1)) == "Pay now? (books up to 1 Mar 2026)"
    assert "Should I pay?" in reword("Should I pay?", 1)


@st.composite
def _ledgers(draw):
    days = draw(st.integers(56, 75))
    sales = draw(st.lists(st.sampled_from([0, 800, 1500, 2600]), min_size=days, max_size=days))
    txns = [txn(date(2026, 1, 1) + timedelta(days=n), amount)
            for n, amount in enumerate(sales) if amount]
    txns.append(txn(date(2026, 1, 1) + timedelta(days=days - 1), 1))
    txns += [out(date(2026, 1, 1) + timedelta(days=d), amount, C.purchase)
             for d, amount in draw(st.lists(st.tuples(st.integers(0, days - 1),
                                                      st.sampled_from([700, 3000])),
                                            max_size=12))]
    parties = [f"PARTY_cust{n:06d}" for n in range(3)]
    issue_day = st.one_of(st.integers(0, days - 2), st.sampled_from([days - 12, days - 6]))
    docs = draw(st.lists(st.tuples(st.integers(0, 2), issue_day,  # shared days make ties
                                   st.sampled_from([5, 15, 30]),
                                   st.sampled_from([4000, 9000]),  # repeats make ties
                                   st.one_of(st.none(), st.integers(-3, 20)),
                                   st.booleans()), max_size=8))
    invoices, bills = [], []
    for n, (who, day, term, amount, delay, is_bill) in enumerate(docs):
        issue = date(2026, 1, 1) + timedelta(days=day)
        due = issue + timedelta(days=term)
        paid_on = due + timedelta(days=delay) if delay is not None else None
        settled = paid_on is not None and paid_on <= date(2026, 1, 1) + timedelta(days=days - 1)
        kw = {"paid": amount, "paid_date": paid_on} if settled else {}
        if is_bill:
            bills.append(bill(f"B-{n}", issue, due, amount, party=f"PARTY_supp{who:06d}", **kw))
        else:
            invoices.append(invoice(f"I-{n}", issue, due, amount, party=parties[who], **kw))
    return ledger(txns, invoices, bills), D(draw(st.integers(0, 60)) * 1000)


@pytest.mark.property
@settings(max_examples=15, deadline=None)
@given(case=_ledgers(), seed=st.integers(0, 2**16))
def test_noise_never_changes_the_engine_decision(case, seed):
    shop, buffer = case

    def compared(variant):
        inputs = prepare(variant, FESTIVALS, buffer, NOW, seed, paths=200, products=[NANO])
        return inputs.draws, compare_decisions(inputs, states=20)

    draws, plain = compared(shop)
    for noisy in (shuffle_rows(shop, seed), rename_parties(shop, seed)):
        noisy_draws, again = compared(noisy)
        for name in DRAWN:  # the same random world, path by path
            assert np.array_equal(getattr(noisy_draws, name), getattr(draws, name)), name
        assert again.scenarios == plain.scenarios  # every number, not just the choice
        assert again.choice == plain.choice
        assert again.skipped == plain.skipped


DRAWN = ("sales_ratio", "invoice_day", "new_invoice", "new_invoice_delay", "new_bill",
         "new_bill_delay", "purchase", "running")
# Two customers owing the same are the case that once broke this (WP-04 tied them on their
# token); tests/cash/test_names.py pins it at the source.
