import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import DataMode, ForecastBand, TxCategory
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.calendar import load_festivals
from app.engines.cash.simulate import (
    InvoiceChange,
    Scenario,
    draw,
    from_paisa,
    rank,
    run,
    simulate,
)
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
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
OCT = {n: date(2026, 10, n) for n in range(1, 32)}


def _base(txns=(), invoices=(), bills=(), obligations=(), opening="10000", horizon=91,
          as_of=AS_OF, tenant=T):
    return forecast_baseline(tenant, as_of, D(opening), list(txns), list(invoices), list(bills),
                             list(obligations), [], horizon=horizon)


def _taka(sim, day):
    """Every path's end-of-day balance on `day`, in taka."""
    return [from_paisa(v) for v in sim.balances[:, (day - sim.baseline.as_of).days - 1]]


def _sales(sim, day):
    """Every path's net flow on `day` (the day's sales when nothing else moves), in taka."""
    t = (day - sim.baseline.as_of).days - 1
    before = sim.balances[:, t - 1] if t else np.full(sim.paths, int(sim.baseline.opening_balance
                                                                       * 100))
    return [from_paisa(v) for v in sim.balances[:, t] - before]


CUSTOMER_HISTORY = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), delay)
                    for n, delay in enumerate([2, 4, 4])]  # this customer pays 2 or 4 days late


# ---------------------------------------------------------------- determinism


def test_the_same_seed_gives_the_same_band_and_another_seed_does_not(universe):
    sme = universe.smes["sme_grocery"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    first, again = simulate(base, seed=7), simulate(base, seed=7)
    assert np.array_equal(first.balances, again.balances)
    assert first.band(D(100000), NOW) == again.band(D(100000), NOW)
    assert not np.array_equal(first.balances, simulate(base, seed=8).balances)


# ---------------------------------------------------------------- hand-computed cases


def test_certain_flows_give_a_band_with_no_width():
    base = _base(bills=[bill("B1", date(2026, 9, 25), OCT[2], 2000)],
                 obligations=[obligation(amount=3000, day=5)], horizon=6)
    band = simulate(base, paths=200).band(D(6000), NOW)
    assert [(p.p10.amount, p.p50.amount, p.p90.amount) for p in band.points] == [
        (D(v), D(v), D(v)) for v in (10000, 8000, 8000, 8000, 5000, 5000)]
    assert [p.p_below_buffer for p in band.points] == [D(0), D(0), D(0), D(0), D(1), D(1)]


def test_a_balance_exactly_at_the_buffer_is_not_below_it():
    base = _base(obligations=[obligation(amount=5000, day=1)], horizon=3)
    assert simulate(base, paths=10).p_below(D(5000)) == [D(0), D(0), D(0)]
    assert simulate(base, paths=10).p_below(D("5000.01")) == [D(1), D(1), D(1)]


def test_a_flat_sales_history_forecasts_flat_sales_with_no_noise():
    base = _base(txns=daily(date(2026, 3, 1), 214, lambda d: 1000), opening="0", horizon=5)
    band = simulate(base, paths=100).band(D(0), NOW)
    assert [(p.p10.amount, p.p90.amount) for p in band.points] == [
        (D(1000 * k), D(1000 * k)) for k in range(1, 6)]


def test_an_open_invoice_is_paid_on_a_day_its_customer_has_paid_before():
    open_inv = invoice("I1", date(2026, 9, 20), OCT[5], 900)  # 2 or 4 days late: 7 or 9 Oct
    sim = simulate(_base(invoices=[*CUSTOMER_HISTORY, open_inv]), paths=2000)
    assert set(_taka(sim, OCT[6])) == {D(10000)}
    on_8th = _taka(sim, OCT[8])
    assert set(on_8th) == {D(10000), D(10900)}
    assert abs(D(on_8th.count(D(10900))) / len(on_8th) - D(1) / 3) < D("0.03")
    assert set(_taka(sim, OCT[9])) == {D(10900)}
    assert abs(sim.p_below(D(10001))[7] - D(2) / 3) < D("0.03")


def test_a_customer_is_equally_late_on_all_their_invoices_in_a_path():
    first = invoice("I1", date(2026, 9, 20), OCT[5], 900)  # 7 or 9 Oct
    second = invoice("I2", date(2026, 9, 25), OCT[10], 500)  # 12 or 14 Oct
    sim = simulate(_base(invoices=[*CUSTOMER_HISTORY, first, second]), paths=500)
    early_first = sim.balances[:, 7] == 1090000  # paisa on 8 Oct: the first is already in
    early_second = sim.balances[:, 12] == 1140000  # 13 Oct: both are in
    assert 0 < early_first.sum() < 500
    assert np.array_equal(early_first, early_second)


def test_different_customers_are_late_independently_of_each_other():
    other = [paid_invoice(f"Q{n}", date(2026, 8, 1) + timedelta(days=n), delay,
                          party="PARTY_cust000002") for n, delay in enumerate([2, 4, 4])]
    mine = invoice("I1", date(2026, 9, 20), OCT[5], 900)
    theirs = invoice("I2", date(2026, 9, 20), OCT[5], 500, party="PARTY_cust000002")
    sim = simulate(_base(invoices=[*CUSTOMER_HISTORY, *other, mine, theirs]), paths=500)
    on_8th = set(_taka(sim, OCT[8]))
    assert on_8th == {D(10000), D(10900), D(10500), D(11400)}  # all four combinations occur


# ---------------------------------------------------------------- bootstrap


def test_a_slow_spell_in_the_sales_history_stays_slow_for_weeks():
    history = daily(date(2026, 3, 1), 214, lambda d: 1000 if d < date(2026, 6, 15) else 1500)
    sim = simulate(_base(txns=history, opening="0", horizon=30), paths=1000)
    slow1 = [v < 1400 for v in _sales(sim, OCT[1])]  # the slow regime, scaled to today (~1130)
    slow2 = [v < 1400 for v in _sales(sim, OCT[2])]
    assert 300 < sum(slow1) < 700  # both regimes of the history occur
    same = sum(1 for a, b in zip(slow1, slow2, strict=True) if a == b)
    assert same >= 950  # day-by-day resampling would agree only about half the time


def test_cost_shocks_recur_with_their_own_size_and_rhythm():
    shocks = [txn(AS_OF - timedelta(days=n), 9100, "outflow", TxCategory.owner_draw)
              for n in range(0, 91, 7)]  # 13 draws of Tk 9,100, one every 7th day
    sim = simulate(_base(txns=shocks, horizon=28), paths=300)
    flows = -np.diff(np.concatenate([np.full((300, 1), 1000000), sim.balances], axis=1), axis=1)
    assert set(np.unique(flows)) == {0, 910000}  # a shock is never averaged into small costs
    assert set((flows == 910000).sum(axis=1)) == {4}  # 28 days hold exactly four, as before


@given(st.lists(st.integers(min_value=0, max_value=5000), min_size=60, max_size=120),
       st.lists(st.tuples(st.integers(1, 20), st.integers(100, 3000)), max_size=6),
       st.integers(min_value=0, max_value=2**32))
def test_bands_never_cross_and_agree_with_the_breach_probability(sales, docs, seed):
    start = AS_OF - timedelta(days=len(sales) - 1)
    txns = daily(start, len(sales), lambda d: sales[(d - start).days])
    invoices = [*CUSTOMER_HISTORY,
                *(invoice(f"R{i}", AS_OF - timedelta(days=5), AS_OF + timedelta(days=due), amt)
                  for i, (due, amt) in enumerate(docs))]
    sim = simulate(_base(txns=txns, invoices=invoices, horizon=21), seed=seed, paths=50)
    p10, p90 = sim.percentile(10), sim.percentile(90)
    band = sim.band(D(10000), NOW)  # the contract itself refuses p10 > p50 or p50 > p90
    for t, point in enumerate(band.points):
        assert sim.p_below(from_paisa(p90[t]) + D("0.01"))[t] >= D("0.9")
        assert sim.p_below(from_paisa(p10[t]))[t] < D("0.1")
        assert point.p10 <= point.p50 <= point.p90


def test_percentiles_are_nearest_rank_order_statistics():
    assert [rank(1000, q) for q in (10, 50, 90)] == [100, 500, 900]
    assert [rank(7, q) for q in (10, 50, 90)] == [1, 4, 7]


def test_a_higher_buffer_never_lowers_the_breach_probability(universe):
    sme = universe.smes["sme_fabric"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    sim = simulate(base)
    rows = [sim.p_below(D(b)) for b in (0, 500000, 1000000, 1500000, 2500000)]
    assert all(lo <= hi for low, high in zip(rows, rows[1:], strict=False)
               for lo, hi in zip(low, high, strict=True))
    assert rows[0] != rows[-1]


def test_a_dip_anywhere_in_a_window_is_at_least_as_likely_as_on_its_worst_day(universe):
    sme = universe.smes["sme_fabric"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    sim = simulate(base)
    daily_p = sim.p_below(D(1200000))
    assert sim.p_dip(D(1200000), 1, 91) >= max(daily_p) > 0
    assert sim.p_dip(D(1200000), 22, 45) >= max(daily_p[21:45])


def test_paths_are_centred_on_the_baseline_forecast(universe):
    sme = universe.smes["sme_hardware"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    expected = np.array([int(v * 100) for _d, v in base.balances()])
    mean = simulate(base, paths=4000).balances.mean(axis=0)
    assert np.abs(mean - expected).max() < 0.01 * np.abs(expected).max()


# ---------------------------------------------------------------- scenarios


def _shared(base, scenario, paths=200):
    draws = draw(base, 3, paths)
    return run(base, draws), run(base, draws, scenario)


def test_a_one_off_cost_lowers_every_path_by_exactly_that_amount_from_its_day(universe):
    sme = universe.smes["sme_grocery"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    plain, shocked = _shared(base, Scenario(flows=((OCT[10], D("-75000.50")),)))
    diff = shocked.balances - plain.balances
    assert (diff[:, :9] == 0).all() and (diff[:, 9:] == -7500050).all()


def test_a_collection_delay_moves_customer_payments_exactly_that_many_days():
    steady = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), 3) for n in range(3)]
    open_inv = invoice("I1", date(2026, 9, 20), OCT[5], 900)  # always 3 days late: 8 Oct
    plain, late = _shared(_base(invoices=[*steady, open_inv], horizon=20),
                          Scenario(collection_delay_days=5))
    assert set(_taka(plain, OCT[8])) == {D(10900)} and set(_taka(late, OCT[12])) == {D(10000)}
    assert set(_taka(late, OCT[13])) == {D(10900)}


def test_sales_and_cost_changes_scale_sales_and_spending_but_not_obligations():
    txns = daily(date(2026, 3, 1), 214, lambda d: 1000)
    txns += [txn(AS_OF - timedelta(days=n), 700, "outflow", TxCategory.purchase)
             for n in range(91)]
    base = _base(txns=txns, obligations=[obligation(amount=2000, day=3)], opening="0",
                 horizon=3)
    plain, changed = _shared(base, Scenario(sales_change_pct=D(-20), cost_change_pct=D(10)))
    assert set(_taka(plain, OCT[3])) == {D(3 * 300 - 2000)}
    assert set(_taka(changed, OCT[3])) == {D(3 * (800 - 770) - 2000)}


def test_paying_a_bill_later_raises_the_balance_only_until_its_new_day():
    base = _base(bills=[bill("B1", date(2026, 9, 25), OCT[3], 2500)], horizon=12)
    plain, moved = _shared(base, Scenario(bill_payments={f"{T}:B1": ((OCT[9], D(2500)),)}))
    diff = (moved.balances - plain.balances)[0]
    assert list(diff) == [0, 0] + [250000] * 6 + [0] * 4


def test_an_advance_brings_part_of_an_invoice_forward_and_the_rest_comes_as_usual():
    open_inv = invoice("I1", date(2026, 9, 20), OCT[5], 900)  # 7 or 9 Oct
    base = _base(invoices=[*CUSTOMER_HISTORY, open_inv], horizon=12)
    change = InvoiceChange(receipts=((OCT[2], D(400)),), remainder=D(500))
    plain, advanced = _shared(base, Scenario(invoice_changes={f"{T}:I1": change}))
    assert set(_taka(advanced, OCT[2])) == {D(10400)}
    assert set(_taka(advanced, OCT[9])) == {D(10900)} == set(_taka(plain, OCT[9]))
    late = plain.balances[:, 7] == 1000000  # paths where the customer pays on 9 Oct
    assert (advanced.balances[late, 7] == 1040000).all()


@pytest.mark.parametrize(
    "scenario",
    [Scenario(flows=((AS_OF, D(-1)),)),
     Scenario(bill_payments={"nope": ((OCT[3], D(1)),)}),
     Scenario(invoice_changes={"nope": InvoiceChange()})],
    ids=["flow-on-as-of", "unknown-bill", "unknown-invoice"],
)
def test_a_scenario_cannot_touch_the_past_or_unknown_documents(scenario):
    base = _base(bills=[bill("B1", date(2026, 9, 25), OCT[3], 2500)], horizon=5)
    with pytest.raises(ValueError):
        simulate(base, paths=5, scenario=scenario)


@pytest.mark.parametrize(
    "kwargs", [{"sales_change_pct": D(-101)}, {"cost_change_pct": D(501)},
               {"collection_delay_days": -1}],
    ids=["sales-below-minus-100", "costs-above-500", "negative-delay"])
def test_scenario_limits(kwargs):
    with pytest.raises(ValueError):
        Scenario(**kwargs)


# ---------------------------------------------------------------- invariance, contract


def test_row_order_and_party_names_do_not_change_the_band(universe):
    sme = universe.smes["sme_hardware"]
    rename = {p.token: f"PARTY_{n:010d}" for n, p in enumerate(reversed(sme.parties))}

    def renamed(doc):
        return doc.model_copy(update={"counterparty_token": rename[doc.counterparty_token]})

    shuffled = [list(sme.transactions), [renamed(i) for i in sme.invoices],
                [renamed(b) for b in sme.bills]]
    for rows in shuffled:
        random.Random(5).shuffle(rows)
    opening = sme.balance_on(universe.as_of).amount
    plain = forecast_baseline(sme.id, universe.as_of, opening, sme.transactions, sme.invoices,
                              sme.bills, sme.obligations, load_festivals())
    other = forecast_baseline(sme.id, universe.as_of, opening, *shuffled, sme.obligations,
                              load_festivals())
    assert simulate(plain).band(D(500000), NOW) == simulate(other).band(D(500000), NOW)


def test_a_synthetic_shop_gets_a_full_labelled_band(universe):
    sme = universe.smes["sme_grocery"]
    opening = sme.balance_on(universe.as_of).amount
    base = forecast_baseline(sme.id, universe.as_of, opening, sme.transactions, sme.invoices,
                             sme.bills, sme.obligations, load_festivals())
    band = simulate(base).band(D(100000), NOW)
    assert isinstance(band, ForecastBand) and band.data_mode is DataMode.synthetic
    assert (band.paths, band.seed, band.horizon_days, len(band.points)) == (1000, 20261020, 91,
                                                                            91)
    assert band.opening_balance.amount == opening and band.buffer.amount == D(100000)
    width = [p.p90.amount - p.p10.amount for p in band.points]
    assert width[90] > width[6] > 0  # uncertainty grows with the horizon
