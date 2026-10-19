import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import DataMode, Direction, DocumentStatus, ObligationKind, TxCategory
from app.engines.cash.backtest import (
    actual_balances,
    backtest,
    daily_csv_transactions,
    known_at,
    main,
)
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.calendar import load_festivals
from app.engines.cash.simulate import simulate
from tests.cash.helpers import T, bill, daily, invoice, obligation, txn

D = Decimal
START, END = date(2025, 1, 1), date(2026, 6, 30)


def _predictable():
    """Tk 1,000 of sales every day and Tk 30,000 rent on the 5th: nothing is uncertain."""
    sales = daily(START, (END - START).days + 1, lambda d: 1000)
    rent = [txn(d, 30000, "outflow", TxCategory.rent)
            for d in (date(y, m, 5) for y in (2025, 2026) for m in range(1, 13))
            if START <= d <= END]
    return sales + rent, [obligation(kind=ObligationKind.rent, amount=30000, day=5,
                                     start=START)]


def test_a_perfectly_predictable_ledger_scores_perfectly():
    txns, obligations = _predictable()
    report = backtest(T, txns, [], [], obligations, [], D(50000), buffer=D(45000), paths=20)
    assert report.mape_percent == D(0) and report.coverage == D(1)
    assert report.naive_mape_percent > 0
    assert report.episodes and report.hit_rate == D(1)
    assert report.unrealised_alerts == 0 and report.mean_alert_probability == D(1)
    first_origin = report.origins[0].origin
    for episode in report.episodes:
        assert 1 <= episode.lead_days <= 90  # an alert needs the dip inside days 1-90
        if episode.first > first_origin + timedelta(days=90):
            assert episode.lead_days >= 90 - 13  # flagged by the first origin that could see it


def test_the_weekly_breakdown_covers_the_horizon_and_the_summary_is_plain_json():
    txns, obligations = _predictable()
    report = backtest(T, txns, [], [], obligations, [], D(50000), buffer=D(45000), paths=20,
                      step_days=28)
    assert len(report.mape_by_week) == 13 == len(report.naive_by_week)
    assert set(report.mape_by_week) == {D(0)}
    summary = json.loads(json.dumps(report.summary()))
    assert summary["origins"] == len(report.origins) and summary["mape_percent"] == "0.00"
    assert summary["per_origin"][0]["alert_gaps"]  # (first, last, probability) as text


# ---------------------------------------------------------------- no leakage


ORIGIN = date(2026, 3, 1)
NOW = datetime(2026, 3, 1, 18, 0, tzinfo=UTC)


def test_the_ledger_known_at_an_origin_hides_everything_later():
    paid_late = invoice("I1", date(2026, 2, 1), date(2026, 2, 15), 900, paid=900,
                        paid_date=date(2026, 3, 10))
    paid_early = invoice("I2", date(2026, 2, 1), date(2026, 2, 15), 500, paid=500,
                         paid_date=date(2026, 2, 20))
    disputed = invoice("I3", date(2026, 2, 1), date(2026, 2, 15), 300, status="disputed")
    issued_later = bill("B1", date(2026, 3, 2), date(2026, 3, 9), 400)
    future_rent = obligation(start=date(2026, 4, 1))
    txns, invoices, bills, obligations = known_at(
        [txn(ORIGIN, 10), txn(ORIGIN + timedelta(days=1), 20)],
        [paid_late, paid_early, disputed], [issued_later], [future_rent, obligation()], ORIGIN)
    assert [t.amount.amount for t in txns] == [D(10)]
    late, early, dispute = invoices
    assert (late.status, late.amount_paid.amount, late.paid_date) == (DocumentStatus.open, 0,
                                                                      None)
    assert early == paid_early  # paid before the origin: history
    assert dispute.status is DocumentStatus.open  # a dispute carries no date
    assert bills == [] and len(obligations) == 1


def _rewrite_future(sme, cut):
    """The same shop with everything after `cut` changed: bigger flows, later payments,
    other documents."""
    txns = [t if t.day <= cut else t.model_copy(update={"amount": t.amount.scale(3)})
            for t in sme.transactions]

    def docs(rows):
        out = []
        for d in rows:
            if d.issue_date > cut:
                continue
            if d.paid_date is not None and d.paid_date > cut:
                d = d.model_copy(update={"paid_date": d.paid_date + timedelta(days=9)})
            out.append(d)
        return out

    extra = [invoice("NEW", cut + timedelta(days=1), cut + timedelta(days=5), 99999)]
    return txns, docs(sme.invoices) + extra, docs(sme.bills)


def test_an_origins_forecast_is_the_same_whatever_happened_after_it(universe):
    sme = universe.smes["sme_hardware"]
    txns, invoices, bills = _rewrite_future(sme, ORIGIN)
    opening = sme.balance_on(ORIGIN).amount

    def band(ledger):
        base = forecast_baseline(sme.id, ORIGIN, opening, *known_at(*ledger, ORIGIN),
                                 load_festivals())
        return base.flows, simulate(base, paths=200).band(D(500000), NOW)

    assert band((sme.transactions, sme.invoices, sme.bills, sme.obligations)) == \
        band((txns, invoices, bills, sme.obligations))


def test_rewriting_the_future_changes_the_scores_but_never_an_earlier_forecast(universe):
    sme = universe.smes["sme_pharmacy"]
    cut = date(2026, 2, 1)
    txns, invoices, bills = _rewrite_future(sme, cut)
    kwargs = {"buffer": D(450000), "paths": 100, "step_days": 28, "last_origin": cut}
    plain = backtest(sme.id, sme.transactions, sme.invoices, sme.bills, sme.obligations,
                     load_festivals(), sme.opening_total.amount, **kwargs)
    rewritten = backtest(sme.id, txns, invoices, bills, sme.obligations, load_festivals(),
                         sme.opening_total.amount, **kwargs)
    assert [(o.origin, o.opening_balance, o.alert_gaps) for o in plain.origins] == \
        [(o.origin, o.opening_balance, o.alert_gaps) for o in rewritten.origins]
    assert plain.mape_percent != rewritten.mape_percent  # the actuals did change


# ---------------------------------------------------------------- pieces and inputs


def test_actual_balances_add_every_signed_transaction_to_the_initial_balance():
    txns = [txn(date(2026, 1, 1), 500), txn(date(2026, 1, 1), 200, "outflow",
                                            TxCategory.purchase),
            txn(date(2026, 1, 3), 100)]
    assert actual_balances(txns, D(1000), date(2026, 1, 1), date(2026, 1, 3)) == {
        date(2026, 1, 1): D(1300), date(2026, 1, 2): D(1300), date(2026, 1, 3): D(1400)}


def test_a_ledger_too_short_for_a_past_and_a_horizon_is_refused():
    with pytest.raises(ValueError, match="not enough history"):
        backtest(T, daily(date(2026, 1, 1), 200, lambda d: 1000), [], [], [], [], D(0))


def test_daily_series_become_sales_and_purchases_labelled_public():
    text = "date,inflow,outflow\n2026-01-01,1200.50,0\n2026-01-02,0,300\n2026-01-03,10,20\n"
    rows = daily_csv_transactions(text, "retail", source="retail.csv")
    assert [(t.day.day, t.direction, t.category, t.amount.amount) for t in rows] == [
        (1, Direction.inflow, TxCategory.sales, D("1200.50")),
        (2, Direction.outflow, TxCategory.purchase, D(300)),
        (3, Direction.inflow, TxCategory.sales, D(10)),
        (3, Direction.outflow, TxCategory.purchase, D(20))]
    assert {t.data_mode for t in rows} == {DataMode.public}
    assert rows[1].source_ref == "retail.csv#L3"


def test_the_command_line_backtests_a_daily_csv(tmp_path):
    days = [date(2025, 1, 1) + timedelta(days=n) for n in range(400)]
    lines = ["date,inflow,outflow"] + [
        f"{d},{1000 + 300 * (d.weekday() == 4)},{30000 if d.day == 5 else 0}" for d in days]
    source = tmp_path / "shop_daily.csv"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "report.json"
    assert main(["--daily-csv", str(source), "--opening", "40000", "--paths", "30",
                 "--step-days", "28", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tenant_id"] == "shop_daily" and report["data_mode"] == "public"
    assert report["origins"] >= 4 and report["mape_percent"] is not None


def test_a_synthetic_shop_backtests_with_honest_bands(universe):
    sme = universe.smes["sme_hardware"]
    report = backtest(sme.id, sme.transactions, sme.invoices, sme.bills, sme.obligations,
                      load_festivals(), sme.opening_total.amount, paths=200, step_days=28)
    assert report.data_mode is DataMode.synthetic
    assert D("0.6") < report.coverage < D("0.95")
    assert report.mape_by_week[0] < report.naive_by_week[0]  # the first week beats "no change"
