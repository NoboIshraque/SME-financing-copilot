"""TCB list parser (WP-09 milestone 1) on the saved lists and on hand-made rows."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.contracts import DataMode
from app.engines.market.tcb import ITEMS, TCB_DIR, TcbFormatError, load_directory, merge, parse_list

HEADER = [
    ["পণ্যের নাম ", " মাপের একক", "অদ্যকার মূল্য(টাকায়)", None, "১সপ্তাহ পূর্বের মূল্য", None,
     "১ মাস পূর্বের মূল্য", None],
    [None, None, datetime(2026, 10, 19), None, datetime(2026, 10, 12), None,
     datetime(2026, 9, 19), None],
    [None, None, "সর্বনিম্ন ", "সর্ব্বোচ্চ ", "সর্বনিম্ন ", "সর্ব্বোচ্চ ", "সর্বনিম্ন ", "সর্ব্বোচ্চ "],
]


def rows(*items: list) -> list[list]:
    return [["ট্রেডিং কর্পোরেশন অব বাংলাদেশ"], *HEADER, *items]


def test_the_saved_lists_give_every_watched_item_for_every_published_day():
    found = load_directory(TCB_DIR)
    days = {o.point.observed_on for o in found if o.published_on == o.point.observed_on}
    assert days == {date(2026, 10, d) for d in range(10, 20)}
    for item in ITEMS:
        published = [o for o in found if o.point.commodity == item.commodity
                     and o.published_on == o.point.observed_on]
        assert len(published) == 10, item.commodity
    assert all(o.point.source == "tcb" and o.point.data_mode is DataMode.public
               and o.point.source_url and o.point.source_url.startswith("https://")
               for o in found)


def test_coarse_rice_on_19_october_is_the_midpoint_of_tcbs_range():
    found = load_directory(TCB_DIR)
    rice = next(o for o in found if o.point.commodity == "rice_coarse"
                and o.point.observed_on == date(2026, 10, 19))
    assert (rice.point.low.amount, rice.point.high.amount) == (Decimal("50.00"), Decimal("55.00"))
    assert rice.point.price.amount == Decimal("52.50")
    assert rice.point.unit == "kg" and rice.ref.startswith("tcb:2026-10-19.xlsx#r")


def test_week_and_month_before_columns_become_points_on_their_own_dates():
    found = parse_list(rows(["চিনি  ", "প্রতি কেজি", 110, 115, 108, 112, 100, 104]),
                       "2026-10-19.xlsx", date(2026, 10, 19))
    by_day = {o.point.observed_on: o.point.price.amount for o in found}
    assert by_day == {date(2026, 10, 19): Decimal("112.50"), date(2026, 10, 12): Decimal("110.00"),
                      date(2026, 9, 19): Decimal("102.00")}


@pytest.mark.parametrize("ya", ["\u09df", "\u09af\u09bc"], ids=["precomposed", "decomposed"])
def test_bangla_names_match_in_either_unicode_form(ya):
    name = f"স{ya}াবিন তেল (লুজ)"  # TCB's files use both forms of য়
    found = parse_list(rows([name, "প্রতি লিটার", 189, 200, 189, 200, 186, 195]),
                       "x.xlsx", date(2026, 10, 19))
    assert {o.point.commodity for o in found} == {"soybean_oil"}


@pytest.mark.parametrize("low, high", [(0, 0), (None, None), ("-", "-"), (120, 100)])
def test_an_item_not_on_sale_or_without_a_range_adds_no_point(low, high):
    found = parse_list(rows(["চিনি", "প্রতি কেজি", low, high, 110, 115, 110, 115]),
                       "x.xlsx", date(2026, 10, 19))
    assert {o.point.observed_on for o in found} == {date(2026, 10, 12), date(2026, 9, 19)}


def test_rows_after_the_price_table_are_not_read():
    found = parse_list(rows(["যে সকল বাজার হতে তথ্য সংগ্রহ করা হয়েছেঃ"],
                            ["চিনি", "প্রতি কেজি", 110, 115, 110, 115, 110, 115]),
                       "x.xlsx", date(2026, 10, 19))
    assert found == []


def test_a_sheet_without_the_dated_header_is_refused():
    with pytest.raises(TcbFormatError):
        parse_list([["চিনি", "প্রতি কেজি", 110, 115]], "x.xlsx", date(2026, 10, 19))


def test_the_list_published_on_a_day_wins_over_a_later_lists_week_before_column():
    own = parse_list(rows(["চিনি", "প্রতি কেজি", 110, 110, 1, 1, 1, 1]), "a.xlsx",
                     date(2026, 10, 19))
    later_header = [list(r) for r in HEADER]
    later_header[1] = [None, None, datetime(2026, 10, 26), None, datetime(2026, 10, 19), None,
                       datetime(2026, 9, 26), None]
    later = parse_list([["x"], *later_header, ["চিনি", "প্রতি কেজি", 130, 130, 120, 120, 1, 1]],
                       "b.xlsx", date(2026, 10, 26))
    merged = {o.point.observed_on: o for o in merge(later + own)}
    assert merged[date(2026, 10, 19)].point.price.amount == Decimal("110.00")
    assert merged[date(2026, 10, 19)].ref.startswith("tcb:a.xlsx")
