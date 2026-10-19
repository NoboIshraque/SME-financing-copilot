from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.contracts import DriverKind, LeadingIndicator, ObligationKind, TxCategory, Unit
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.calendar import load_festivals
from app.engines.cash.figures import FORMULAS, Evidence
from app.engines.cash.gaps import drivers, find_gaps, leading_indicators, shortfall
from app.engines.cash.simulate import BASE, Scenario, Simulation, simulate
from tests.cash.helpers import (
    AS_OF,
    T,
    bill,
    daily,
    invoice,
    obligation,
    paid_invoice,
    txn,
)

D = Decimal
OCT = {n: date(2026, 10, n) for n in range(1, 32)}
STEADY = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), 3) for n in range(3)]


def _base(txns=(), invoices=(), bills=(), obligations=(), opening="10000", horizon=10):
    return forecast_baseline(T, AS_OF, D(opening), list(txns), list(invoices), list(bills),
                             list(obligations), [], horizon=horizon)


def _paths(rows, horizon=None):
    """A simulation with hand-written balances (taka per path per day)."""
    horizon = horizon or len(rows[0])
    return Simulation(baseline=_base(horizon=horizon), scenario=BASE, seed=0,
                      balances=np.array(rows, dtype=np.int64) * 100)


# ---------------------------------------------------------------- gap numbers


def test_a_certain_dip_is_a_gap_with_hand_computed_numbers():
    base = _base(invoices=[*STEADY, invoice("I1", date(2026, 9, 15), OCT[1], 2000)],  # 3 Oct
                 bills=[bill("B1", date(2026, 9, 20), OCT[2], 500)],
                 obligations=[obligation(amount=8000, day=5)])
    (found,) = find_gaps(simulate(base, paths=50), D(5000))
    gap = found.gap
    assert (gap.first_breach_day, gap.lead_time_days, gap.worst_day) == (OCT[5], 5, OCT[5])
    assert gap.probability == D(1) and gap.expected_shortfall.amount == D("1500.00")
    assert (found.peak, found.first, found.last) == (4, 5, 10)  # 11,500 from 3 Oct to 4 Oct
    assert [(d.kind, d.label_key, d.amount.amount) for d in gap.drivers] == [
        (DriverKind.obligation, "driver.rent", D(8000))]  # the 2 Oct bill came before the high


def test_no_gap_while_every_path_stays_at_or_above_the_buffer():
    assert find_gaps(_paths([[5000, 6000, 5000]] * 10), D(5000)) == ()


@pytest.mark.parametrize(("below", "expected"), [(2, 0), (3, 1)],
                         ids=["two-in-ten-is-not-more-than-20pct", "three-in-ten-is"])
def test_a_gap_needs_more_than_a_fifth_of_paths_to_dip(below, expected):
    rows = [[9000, 4000, 9000]] * below + [[9000, 9000, 9000]] * (10 - below)
    assert len(find_gaps(_paths(rows), D(5000))) == expected


def test_the_first_breach_is_when_more_than_a_fifth_of_paths_have_dipped_so_far():
    dips = [[1000 if day == dip else 9000 for day in range(1, 6)] for dip in (2, 3, 4)]
    rows = dips + [[9000] * 5] * 7  # each day only one path in ten is low, but they add up
    (found,) = find_gaps(_paths(rows), D(5000))
    assert (found.first, found.last, found.gap.lead_time_days) == (2, 4, 4)
    assert found.gap.probability == D("0.3") and found.gap.expected_shortfall.amount == D(1200)


def test_two_separate_dips_are_two_gaps_soonest_first():
    rows = [[9000, 1000, 9000, 9000, 2000, 9000]] * 10
    first, second = find_gaps(_paths(rows), D(5000))
    assert (first.first, first.last, second.first, second.last) == (2, 2, 5, 5)
    assert (first.gap.expected_shortfall.amount, second.gap.expected_shortfall.amount) == (
        D(4000), D(3000))


def test_the_worst_day_is_the_lowest_likely_balance_from_the_breach_on():
    rows = [[4000, 3000, 1000, 2000]] * 6 + [[9000, 8000, 7000, 9000]] * 4
    (found,) = find_gaps(_paths(rows), D(5000))
    assert found.gap.first_breach_day == OCT[1] and found.gap.worst_day == OCT[3]


def test_expected_shortfall_averages_over_paths_that_never_dip_too():
    rows = [[3000]] * 4 + [[6000]] * 6
    assert shortfall(_paths(rows), D(5000), 1, 1) == (D("0.4"), D(800))


# ---------------------------------------------------------------- drivers


def test_drivers_are_the_three_largest_reasons_in_taka():
    base = _base(bills=[bill("B1", date(2026, 9, 20), OCT[4], 3000)],
                 obligations=[obligation(amount=8000, day=5),
                              obligation(kind=ObligationKind.salary, amount=6000, day=6),
                              obligation(kind=ObligationKind.utility, amount=900, day=6)])
    found = drivers(simulate(base, paths=10), 0, 7)
    assert [(d.label_key, d.amount.amount) for d in found] == [
        ("driver.rent", D(8000)), ("driver.salary", D(6000)), ("driver.supplier_bill", D(3000))]
    assert found[2].reference_id == f"{T}:B1" and found[2].counterparty_token == \
        "PARTY_supp000001"


def test_a_customer_due_before_the_worst_day_but_paying_after_it_is_a_driver():
    history = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), delay)
               for n, delay in enumerate([2, 4, 4])]
    base = _base(invoices=[*history, invoice("I1", date(2026, 9, 20), OCT[3], 900)])  # 5 or 7
    (late,) = drivers(simulate(base, paths=10), 0, 5)
    assert (late.kind, late.label_key, late.amount.amount) == (
        DriverKind.late_customer, "driver.late_customer", D(600))  # 2 of 3 delays land later
    assert late.reference_id == f"{T}:I1" and late.counterparty_token == "PARTY_cust000001"


def test_a_customer_later_than_ever_counts_in_full_and_a_disputed_invoice_is_named():
    stale = invoice("I1", date(2026, 8, 1), date(2026, 8, 16), 700)  # STEADY pays 3 days late
    disputed = invoice("I2", date(2026, 9, 1), date(2026, 9, 16), 400,
                       status="disputed", party="PARTY_cust000002")
    found = drivers(simulate(_base(invoices=[*STEADY, stale, disputed]), paths=10), 0, 3)
    assert [(d.label_key, d.amount.amount) for d in found] == [
        ("driver.late_customer", D(700)), ("driver.disputed_invoice", D(400))]


def test_sales_below_their_normal_level_are_a_seasonal_dip():
    def half_at_month_end(day):
        return 500 if (day + timedelta(days=3)).month != day.month else 1000

    base = _base(txns=daily(date(2026, 3, 1), 214, half_at_month_end), horizon=31)
    (dip,) = drivers(simulate(base, paths=10), 25, 31)  # 29-31 Oct: half of a normal day
    assert (dip.kind, dip.label_key) == (DriverKind.seasonal_dip, "driver.seasonal_dip")
    assert abs(dip.amount.amount - D(1500)) < D(15)


def test_a_what_ifs_sales_drop_and_one_off_cost_are_drivers():
    base = _base(txns=daily(date(2026, 3, 1), 214, lambda d: 1000))
    what_if = Scenario(name="what_if", sales_change_pct=D(-20), flows=((OCT[2], D(-5000)),))
    found = simulate(base, paths=10, scenario=what_if)
    assert [(d.kind, d.label_key, d.amount.amount) for d in drivers(found, 0, 4)] == [
        (DriverKind.cost_shock, "driver.one_off_cost", D(5000)),
        (DriverKind.seasonal_dip, "driver.sales_drop", D(800))]


def test_every_gap_figure_has_provenance_and_cites_its_drivers():
    base = _base(bills=[bill("B1", date(2026, 9, 20), OCT[2], 9000)],
                 obligations=[obligation(amount=4000, day=3)])
    evidence = Evidence(input_fact_ids=("fact_opening",))
    (found,) = find_gaps(simulate(base, paths=20, seed=11), D(5000), evidence)
    by_label = {f.label_key: f for f in found.gap.figures}
    assert by_label["cash.expected_shortfall"].value == found.gap.expected_shortfall.amount
    assert by_label["cash.breach_probability"].value == found.gap.probability
    assert by_label["cash.lead_time_days"].value == found.gap.lead_time_days
    assert by_label["cash.lead_time_days"].unit is Unit.days
    for fig in found.gap.figures:
        prov = fig.provenance
        assert prov.formula_id in FORMULAS and prov.input_fact_ids == ("fact_opening",)
        assert {f"bill:{T}:B1", f"obl:{base.obligations[0].id}"} <= set(prov.source_row_ids)
        assert (prov.parameters["seed"], prov.parameters["paths"], prov.parameters["buffer"]) \
            == ("11", "20", "5000")
    assert len({f.id for f in found.gap.figures}) == 3


def test_a_synthetic_shop_shows_its_gaps_with_named_drivers(universe):
    sme = universe.smes["sme_fabric"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    gaps = find_gaps(simulate(base), D(1000000))
    assert gaps and all(g.gap.lead_time_days >= 1 and g.gap.drivers for g in gaps)
    assert [g.gap.first_breach_day for g in gaps] == sorted(g.gap.first_breach_day for g in gaps)
    assert all(g.gap.expected_shortfall.amount > 0 for g in gaps)


# ---------------------------------------------------------------- leading indicators


def _signals(txns=(), invoices=(), bills=(), obligations=(), opening="10000", horizon=10,
             festivals=()):
    base = forecast_baseline(T, AS_OF, D(opening), list(txns), list(invoices), list(bills),
                             list(obligations), list(festivals), horizon=horizon)
    sim = simulate(base, paths=20)
    return leading_indicators(sim, txns, invoices, bills, festivals)


def _fired(signals):
    return [s.indicator for s in signals]


def _dso_book(old, before_owed, now_owed):
    """Tk 6,000 invoiced in August and in September; `before_owed` still owed on 31 Aug,
    `now_owed` on 30 Sep, plus an old unpaid invoice of `old`."""
    docs = []
    if old:
        docs.append(invoice("OLD", date(2026, 6, 1), date(2026, 6, 15), old))
    for tag, issued, settled, owed, paid_on in (("A", date(2026, 8, 10), date(2026, 8, 20),
                                                 before_owed, date(2026, 9, 1)),
                                                ("S", date(2026, 9, 10), date(2026, 9, 20),
                                                 now_owed, None)):
        if owed < 6000:
            docs.append(invoice(f"{tag}1", issued, issued, 6000 - owed, paid=6000 - owed,
                                paid_date=settled))
        if owed:
            kw = {"paid": owed, "paid_date": paid_on} if paid_on else {}
            docs.append(invoice(f"{tag}2", issued, issued + timedelta(days=5), owed, **kw))
    return docs


@pytest.mark.parametrize(
    ("old", "before_owed", "now_owed", "fires"),
    [(0, 2000, 4000, True), (0, 5000, 6000, True), (0, 2000, 2600, False),
     (6000, 0, 1000, False)],
    ids=["10-to-20-days", "25-to-30-days-both-limits-met", "10-to-13-only-3-days-more",
         "30-to-35-only-17pct-more"],
)
def test_dso_rising_needs_a_fifth_more_and_five_days_more(old, before_owed, now_owed, fires):
    signals = _signals(invoices=_dso_book(old, before_owed, now_owed))
    assert (LeadingIndicator.dso_rising in _fired(signals)) is fires


def test_dso_rising_reports_both_dsos_as_figures():
    (signal,) = _signals(invoices=_dso_book(0, 2000, 4000))
    assert [(f.label_key, f.value) for f in signal.figures] == [("cash.dso_now", D(20)),
                                                                ("cash.dso_before", D(10))]


def _customer(delays_before, delays_recent, party="PARTY_cust000001", tag="C"):
    early = [paid_invoice(f"{tag}E{n}", date(2026, 6, 1) + timedelta(days=n), d, party=party)
             for n, d in enumerate(delays_before)]  # settled in June
    recent = [paid_invoice(f"{tag}R{n}", date(2026, 9, 1) + timedelta(days=n), d, party=party)
              for n, d in enumerate(delays_recent)]  # issued mid-August, settled in September
    return early + recent


@pytest.mark.parametrize(("recent", "fires"), [([7, 8], True), ([3, 4], False)],
                         ids=["median-up-7-days", "median-up-3-days"])
def test_a_top_customer_paying_later_than_they_used_to_is_flagged(recent, fires):
    signals = _signals(invoices=_customer([0, 1, 1], recent))
    assert (LeadingIndicator.top_customer_slowing in _fired(signals)) is fires


def test_a_top_customer_overdue_longer_than_ever_before_is_flagged():
    overdue = invoice("I1", date(2026, 9, 5), date(2026, 9, 20), 900)  # 10 days overdue
    (signal,) = _signals(invoices=[*_customer([0, 1, 2], []), overdue])
    assert signal.indicator is LeadingIndicator.top_customer_slowing
    assert signal.reference_id == f"{T}:I1" and signal.figures[0].value == D(10)


def test_a_small_customer_slowing_down_is_not_a_top_customer_signal():
    big = [_customer([0, 0, 0], [0, 0], party=f"PARTY_big{n}", tag=f"B{n}") for n in range(3)]
    for docs in big:  # three customers who each buy more than the slow one
        docs.extend(invoice(f"{docs[0].counterparty_token}-X{k}", date(2026, 9, 1),
                            date(2026, 9, 1), 5000, paid=5000, paid_date=date(2026, 9, 1))
                    for k in range(2))
    slow = _customer([0, 1, 1], [9, 9], party="PARTY_small", tag="S")
    signals = _signals(invoices=[*slow, *(d for docs in big for d in docs)])
    assert LeadingIndicator.top_customer_slowing not in _fired(signals)


@pytest.mark.parametrize(("recent_purchases", "fires"), [(900, True), (870, False)],
                         ids=["ratio-up-29pct", "ratio-up-24pct"])
def test_stock_building_faster_than_sales_is_flagged(recent_purchases, fires):
    sales = daily(date(2026, 3, 1), 214, lambda d: 1000)
    buys = [txn(d, recent_purchases if d > date(2026, 8, 31) else 700, "outflow",
                TxCategory.purchase)
            for d in (date(2026, 3, 1) + timedelta(days=n) for n in range(214))]
    signals = _signals(txns=sales + buys)
    assert (LeadingIndicator.stock_building in _fired(signals)) is fires


@pytest.mark.parametrize(("recent_sales", "fires"), [(800, True), (900, False)],
                         ids=["80pct-of-norm", "90pct-of-norm"])
def test_sales_below_the_seasonal_norm_are_flagged(recent_sales, fires):
    txns = daily(date(2026, 3, 1), 214,
                 lambda d: recent_sales if d > date(2026, 9, 16) else 1000)
    signals = _signals(txns=txns)
    assert (LeadingIndicator.sales_below_seasonal_norm in _fired(signals)) is fires


@pytest.mark.parametrize(
    ("kind", "opening", "fires"),
    [(ObligationKind.salary, "1000", True), (ObligationKind.emi, "1000", True),
     (ObligationKind.salary, "9000", False), (ObligationKind.rent, "1000", False)],
    ids=["salary-unaffordable", "emi-unaffordable", "salary-affordable", "rent-is-not-payroll"],
)
def test_a_salary_or_emi_day_with_a_likely_negative_balance_is_flagged(kind, opening, fires):
    signals = _signals(obligations=[obligation(kind=kind, amount=5000, day=5)], opening=opening)
    assert (LeadingIndicator.payroll_or_emi_at_risk in _fired(signals)) is fires
    if fires:
        assert signals[0].figures[0].value == D(-4000)


def test_indicators_never_read_rows_after_as_of():
    invoices = _dso_book(0, 2000, 4000)
    future = [invoice("F1", date(2026, 10, 2), date(2026, 10, 3), 99999),
              txn(date(2026, 10, 2), 50000, "outflow", TxCategory.purchase)]
    plain = _signals(invoices=invoices)
    assert _signals(txns=[future[1]], invoices=[*invoices, future[0]]) == plain
