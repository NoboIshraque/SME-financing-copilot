"""WFP (Bangladesh markets), NBS (China national) and Xinfadi (Beijing) parsers on saved files."""

from datetime import date
from decimal import Decimal

import pytest

from app.contracts import Currency
from app.engines.market import nbs, wfp, xinfadi
from app.engines.market.locations import DHAKA_CITY, distance_km, load_wfp_markets


def test_nbs_sept_late_release_gives_rebar_at_its_published_price_and_the_period_before():
    found = {(o.point.commodity, o.point.observed_on): o for o in nbs.load_directory()}
    rebar = found[("rebar", date(2026, 9, 30))]
    assert rebar.point.price.amount == Decimal("3175.90")
    assert rebar.point.price.currency is Currency.CNY and rebar.point.unit == "metric_ton"
    assert rebar.ref.endswith("#rebar:current")
    # Sep 中旬 comes from its own release (3165.1 = 3175.9 - 10.8 there too)
    assert found[("rebar", date(2026, 9, 20))].ref.startswith("nbs:t20260923")


@pytest.mark.parametrize("day, before", [(date(2026, 9, 10), date(2026, 8, 31)),
                                         (date(2026, 9, 20), date(2026, 9, 10)),
                                         (date(2026, 9, 30), date(2026, 9, 20))])
def test_nbs_ten_day_periods_step_back_correctly(day, before):
    assert nbs.previous_period(day) == before


def test_nbs_refuses_a_page_that_is_not_a_price_release():
    with pytest.raises(nbs.NbsFormatError):
        nbs.parse_release("<html>2026年9月份居民消费价格</html>", "x.html", date(2026, 10, 1))


def test_xinfadi_takes_the_median_of_a_days_rows_and_their_full_range():
    rows = [{"prodName": "土豆", "unitInfo": "斤", "specInfo": "", "lowPrice": lo, "highPrice": hi,
             "avgPrice": avg, "pubDate": "2026-10-20 00:00:00", "id": i}
            for i, (lo, hi, avg) in enumerate([("0.8", "1.0", "0.9"), ("0.7", "1.2", "1.0"),
                                                ("0.6", "0.8", "0.7")])]
    other_kind = {**rows[0], "specInfo": "黄金薯", "avgPrice": "9", "highPrice": "9.5"}
    rows.append(other_kind)
    [obs] = xinfadi.parse_answer({"list": rows}, "potato.json")
    assert obs.point.price.amount == Decimal("0.90")
    assert (obs.point.low.amount, obs.point.high.amount) == (Decimal("0.60"), Decimal("1.20"))
    assert obs.point.unit == "jin" and obs.point.price.currency is Currency.CNY


def test_wfp_reads_only_observed_retail_taka_prices():
    base = {"date": "2026-07-15", "market": "Gazipur Sadar", "market_id": "4035",
            "commodity": "Sugar", "commodity_id": "97", "pricetype": "Retail",
            "priceflag": "actual", "currency": "BDT", "price": "125"}
    rows = [base, {**base, "priceflag": "aggregate", "market_id": "1"},
            {**base, "pricetype": "Wholesale", "market_id": "2"},
            {**base, "commodity": "Papaya (green)", "market_id": "3"}]
    found = wfp.parse_rows(rows)
    assert list(found) == ["wfp-4035"]
    assert found["wfp-4035"][0].point.price.amount == Decimal("125.00")


def test_saved_wfp_markets_cover_all_eight_divisions():
    markets = load_wfp_markets()
    assert {m.division for m in markets.values()} >= {
        "Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet"}
    assert distance_km(DHAKA_CITY, DHAKA_CITY) == 0
