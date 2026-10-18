from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.contracts import DataMode, Direction, DocumentStatus, Frequency, ObligationKind, TxCategory
from app.engines.cash.baseline import FlowKind, forecast_baseline, obligation_days
from app.engines.cash.calendar import Festival, festival_offsets, load_festivals
from app.engines.cash.delays import DelayTable
from app.engines.cash.sales import fit_sales
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
OCT1 = date(2026, 10, 1)


def _baseline(txns=(), invoices=(), bills=(), obligations=(), festivals=(), opening="0",
              horizon=91):
    return forecast_baseline(T, AS_OF, D(opening), list(txns), list(invoices), list(bills),
                             list(obligations), list(festivals), horizon=horizon)


def _flows(base, kind):
    return [(f.day, f.amount) for f in base.flows if f.kind is kind]


# ---------------------------------------------------------------- schedules


@pytest.mark.parametrize(
    ("frequency", "day", "start", "end", "expected"),
    [
        (Frequency.monthly, 31, date(2025, 1, 1), None,
         [date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31)]),
        (Frequency.monthly, 5, date(2026, 11, 20), None, [date(2026, 12, 5)]),
        (Frequency.monthly, 5, date(2025, 1, 1), date(2026, 11, 4), [date(2026, 10, 5)]),
        (Frequency.weekly, 5, date(2025, 1, 1), date(2026, 10, 20),
         [date(2026, 10, 2), date(2026, 10, 9), date(2026, 10, 16)]),
        (Frequency.quarterly, 15, date(2026, 1, 15), None, [date(2026, 10, 15)]),
        (Frequency.yearly, 1, date(2024, 12, 1), None, [date(2026, 12, 1)]),
    ],
    ids=["day-31-in-short-months", "starts-mid-horizon", "ends-mid-horizon", "weekly-fridays",
         "quarterly", "yearly"],
)
def test_obligation_schedule(frequency, day, start, end, expected):
    ob = obligation(frequency=frequency, day=day, start=start, end=end)
    assert obligation_days(ob, OCT1, date(2026, 12, 31)) == expected


def test_obligations_are_known_outflows_on_their_days():
    base = _baseline(obligations=[obligation(amount=35000, day=5)])
    assert _flows(base, FlowKind.obligation) == [
        (date(2026, 10, 5), D("35000.00")), (date(2026, 11, 5), D("35000.00")),
        (date(2026, 12, 5), D("35000.00"))]


def _settled_bill(number, due, delay, party):
    return bill(number, due - timedelta(days=20), due, 500, paid=500,
                paid_date=due + timedelta(days=delay), party=party)


def test_an_open_bill_is_paid_when_the_business_usually_pays_that_supplier_never_later():
    early = [_settled_bill(f"E{n}", date(2026, 8, 25) + timedelta(days=n), -5, "PARTY_supp_early")
             for n in range(3)]  # this supplier is always paid 5 days before the due date
    late = [_settled_bill(f"L{n}", date(2026, 8, 25) + timedelta(days=n), 3, "PARTY_supp_late")
            for n in range(3)]  # and this one 3 days after it
    open_bills = [bill("B1", date(2026, 9, 25), date(2026, 10, 20), 900, party="PARTY_supp_early"),
                  bill("B2", date(2026, 9, 25), date(2026, 10, 20), 400, party="PARTY_supp_late")]
    base = _baseline(bills=[*early, *late, *open_bills])
    assert sorted(_flows(base, FlowKind.bill)) == [(date(2026, 10, 15), D("900.00")),
                                                   (date(2026, 10, 20), D("400.00"))]
    assert [(ob.bill.id, ob.pay_day) for ob in base.open_bills] == [
        (f"{T}:B1", date(2026, 10, 15)), (f"{T}:B2", date(2026, 10, 20))]


def test_the_run_rates_are_the_mean_of_the_daily_history_the_simulation_resamples():
    txns = [txn(AS_OF - timedelta(days=n), 700, "outflow", TxCategory.purchase)
            for n in range(0, 91, 2)]  # Tk 700 every other day
    base = _baseline(txns=txns, bills=[bill("B1", date(2026, 9, 1), date(2026, 9, 8), 910,
                                            paid=910, paid_date=date(2026, 9, 8))])
    history = base.history(FlowKind.purchases)
    assert len(history) == 91 and history[-1] == D(700) and history[-2] == D(0)
    assert {a for _d, a in _flows(base, FlowKind.purchases)} == {sum(history) / 91}
    assert sum(base.history(FlowKind.new_bills)) == D(910)


def test_open_bills_fall_on_their_due_date_and_overdue_ones_tomorrow():
    bills = [bill("B1", date(2026, 9, 25), date(2026, 10, 2), 900),
             bill("B2", date(2026, 9, 1), date(2026, 9, 20), 400),
             bill("B3", date(2026, 9, 1), date(2026, 9, 10), 700, paid=700,
                  paid_date=date(2026, 9, 10)),
             bill("B4", date(2026, 9, 1), date(2026, 9, 10), 300,
                  status=DocumentStatus.written_off)]
    assert sorted(_flows(_baseline(bills=bills), FlowKind.bill)) == [
        (OCT1, D("400.00")), (date(2026, 10, 2), D("900.00"))]


# ---------------------------------------------------------------- collections


HISTORY = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), delay)
           for n, delay in enumerate([2, 4, 4])]


def test_open_invoice_follows_the_customers_delay_distribution():
    open_inv = invoice("I1", date(2026, 9, 20), date(2026, 10, 5), 900)
    flows = _flows(_baseline(invoices=[*HISTORY, open_inv]), FlowKind.collection)
    assert flows == [(date(2026, 10, 7), D("300")), (date(2026, 10, 9), D("600"))]


def test_delays_already_elapsed_are_ruled_out():
    overdue = invoice("I1", date(2026, 9, 12), date(2026, 9, 27), 900)  # due 3 days ago
    flows = _flows(_baseline(invoices=[*HISTORY, overdue]), FlowKind.collection)
    assert flows == [(date(2026, 10, 1), D("900"))]  # only the 4-day delay is still possible


def test_a_customer_later_than_ever_contributes_nothing():
    stale = invoice("I1", date(2026, 8, 1), date(2026, 8, 16), 900)
    assert _flows(_baseline(invoices=[*HISTORY, stale]), FlowKind.collection) == []


def test_disputed_invoices_are_not_expected():
    disputed = invoice("I1", date(2026, 9, 20), date(2026, 10, 5), 900,
                       status=DocumentStatus.disputed)
    assert _flows(_baseline(invoices=[*HISTORY, disputed]), FlowKind.collection) == []


def test_a_new_customer_borrows_the_tenant_wide_delays():
    table = DelayTable.from_documents(
        [*HISTORY, paid_invoice("X1", date(2026, 8, 1), 9, party="PARTY_cust000002")], AS_OF)
    assert table.delays_for("PARTY_cust000002") == (2, 4, 4, 9)  # one own document is too few
    assert table.delays_for("PARTY_cust000001") == (2, 4, 4)


def test_settlements_after_as_of_are_not_history():
    later = paid_invoice("L1", date(2026, 9, 28), 5)  # paid on 3 Oct, after as_of
    assert DelayTable.from_documents([later], AS_OF).overall == ()


def test_invoices_not_yet_issued_arrive_after_their_usual_payment_time():
    paid_history = [paid_invoice(f"P{n}", date(2026, 5, 1) + timedelta(days=n), 0)
                    for n in range(3)]  # each paid 15 days after it was issued
    recent = [invoice(f"R{n}", AS_OF - timedelta(days=n), AS_OF + timedelta(days=200), 91)
              for n in range(91)]  # 91 Tk of credit sales a day over the run-rate window
    flows = _flows(_baseline(invoices=paid_history + recent), FlowKind.new_invoices)
    assert flows[0] == (date(2026, 10, 16), D("91"))  # day 16: invoices from day 1 come due
    assert len(flows) == 91 - 15 and all(amount == D("91") for _d, amount in flows)


# ---------------------------------------------------------------- sales model


def test_weekday_pattern_is_learnt():
    txns = daily(date(2026, 3, 1), 214, lambda d: 2000 if d.weekday() == 4 else 1000)
    model = fit_sales(txns, AS_OF, [])
    assert model.weekday[4] == D("1.7500") and model.weekday[0] == D("0.8750")
    friday, monday = date(2026, 10, 2), date(2026, 10, 5)
    assert abs(model.expected(friday) - 2000) < 1 and abs(model.expected(monday) - 1000) < 1


def test_days_the_shop_is_closed_forecast_nothing():
    txns = daily(date(2026, 3, 1), 214, lambda d: 0 if d.weekday() == 4 else 1000)
    base = _baseline(txns=txns)
    fridays = [a for d, a in _flows(base, FlowKind.sales) if d.weekday() == 4]
    assert fridays == [] and len(_flows(base, FlowKind.sales)) == 91 - 13


def test_month_end_lift_is_learnt():
    def amount(day):
        return 2000 if (day + timedelta(days=3)).month != day.month else 1000

    model = fit_sales(daily(date(2026, 3, 1), 214, amount), AS_OF, [])
    assert abs(model.month_end - 2) < D("0.01")


def test_level_follows_the_recent_trend():
    txns = daily(date(2026, 3, 1), 214, lambda d: 1000 if d < date(2026, 8, 5) else 1500)
    model = fit_sales(txns, AS_OF, [])
    assert abs(model.expected(date(2026, 10, 6)) - 1500) < 15  # not the 26-week mean (~1180)


FEST = [Festival("eid_ul_adha", date(2025, 6, 7)), Festival("eid_ul_adha", date(2026, 5, 27)),
        Festival("eid_ul_fitr", date(2027, 3, 10)), Festival("pohela_boishakh", date(2027, 4, 14))]


def _festive(day):
    offsets = festival_offsets(day, FEST)
    return 3000 if any(-10 <= k <= -1 for _n, k in offsets) else 1000


def test_festival_run_up_is_learnt_from_past_occurrences():
    model = fit_sales(daily(date(2025, 4, 1), 548, _festive), AS_OF, FEST)
    assert model.festival_factor("eid_ul_adha", -5) == D("3.0000")
    assert model.festival_factor("eid_ul_adha", 2) == D("1.0000")


def test_a_festival_never_seen_borrows_its_familys_effect_and_others_stay_neutral():
    model = fit_sales(daily(date(2025, 4, 1), 548, _festive), AS_OF, FEST)
    assert model.festival_factor("eid_ul_fitr", -5) == D("3.0000")
    assert model.festival_factor("pohela_boishakh", -5) == D("1")


def test_festival_effect_shows_in_the_forecast():
    txns = daily(date(2025, 4, 1), 548, _festive)
    base = forecast_baseline(T, date(2027, 2, 20), D(0), txns, [], [], [], FEST, horizon=30)
    sales = dict(_flows(base, FlowKind.sales))
    assert sales[date(2027, 3, 5)] > 2 * sales[date(2027, 2, 25)]


def test_the_real_calendar_file_loads():
    names = {f.name for f in load_festivals()}
    assert {"eid_ul_fitr", "eid_ul_adha", "pohela_boishakh"} <= names


# ---------------------------------------------------------------- running costs, balance


def test_running_costs_skip_transfers_and_what_obligations_already_cover():
    txns = [txn(AS_OF - timedelta(days=n), 910, "outflow", category)
            for n in range(0, 91, 7)
            for category in (TxCategory.owner_draw, TxCategory.rent, TxCategory.transfer)]
    base = _baseline(txns=txns, obligations=[obligation(kind=ObligationKind.rent)])
    rates = {a for _d, a in _flows(base, FlowKind.running_cost)}
    assert rates == {D(910 * 13) / 91}  # owner draws only


def test_expected_balance_is_opening_plus_cumulative_net():
    base = _baseline(bills=[bill("B1", date(2026, 9, 25), date(2026, 10, 2), 900)],
                     obligations=[obligation(amount=100, day=1)], opening="5000", horizon=3)
    assert base.balances() == [(OCT1, D("4900.00")), (date(2026, 10, 2), D("4000.00")),
                               (date(2026, 10, 3), D("4000.00"))]


def test_rows_after_as_of_never_change_the_forecast():
    history = daily(date(2026, 3, 1), 214, lambda d: 1000 + d.day)
    future = [txn(date(2026, 10, 3), 999999), txn(date(2026, 10, 4), 5, "outflow",
                                                  TxCategory.owner_draw)]
    assert _baseline(txns=history).flows == _baseline(txns=history + future).flows


def test_synthetic_shops_get_a_full_labelled_forecast(universe):
    sme = universe.smes["sme_grocery"]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    assert len(base.balances()) == 91 and base.data_mode is DataMode.synthetic
    assert all(base.as_of < f.day <= base.days[-1] for f in base.flows)
    assert {f.direction for f in base.flows} == {Direction.inflow, Direction.outflow}
