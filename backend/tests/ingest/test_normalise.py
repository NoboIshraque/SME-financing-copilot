from datetime import date, datetime
from decimal import Decimal

import pytest

from app.ingest.normalise import (
    NormaliseError,
    ascii_digits,
    bengali_to_gregorian,
    header_key,
    parse_amount,
    parse_when,
    resolve_day_first,
    split_drcr,
)


def test_every_bangla_digit_maps_to_its_ascii_digit():
    assert ascii_digits("০১২৩৪৫৬৭৮৯") == "0123456789"
    assert ascii_digits("ক১খ") == "ক1খ"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("০", "0"),
        ("৯৮৭৬৫", "98765"),
        ("১2৩", "123"),
        ("১২.৫০", "12.50"),
        ("১,২৫,০০০", "125000"),
        ("৳১০০", "100"),
        ("১০০ টাকা", "100"),
        ("Tk ২,০০০/-", "2000"),
        ("BDT 1,200.00", "1200.00"),
        ("1200/=", "1200"),
        ("(১,২০০.০০)", "-1200.00"),
        ("−250", "-250"),
        ("১.৫ লাখ", "150000.0"),
        ("২ কোটি", "20000000"),
        ("৫ হাজার", "5000"),
        ("3.5 lakh", "350000.0"),
        ("12k", "12000"),
    ],
    ids=["zero", "five-digits", "mixed-scripts", "decimals", "lakh-grouping", "taka-sign",
         "taka-word", "tk-and-slash-dash", "bdt", "slash-equals", "accounting-negative",
         "unicode-minus", "lakh-word", "crore-word", "hazar-word", "banglish-lakh", "k-suffix"],
)
def test_bangla_digit_and_amount_table(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "reason"),
    [("", "ingest.amount.missing"), ("১২ক", "ingest.amount.invalid"),
     ("1.2.3", "ingest.amount.invalid"), ("5 dozen", "ingest.amount.invalid")],
    ids=["empty", "letter-after-digits", "two-points", "unknown-word"],
)
def test_unreadable_amounts_carry_a_reason(text, reason):
    with pytest.raises(NormaliseError) as err:
        parse_amount(text)
    assert err.value.reason_key == reason


def test_drcr_marker_is_split_off():
    assert split_drcr("12,000.00 Cr") == ("12,000.00", "cr")
    assert split_drcr("500 DR.") == ("500", "dr")
    assert split_drcr("700") == ("700", None)


@pytest.mark.parametrize(
    ("text", "day_first", "expected", "ambiguous"),
    [
        ("03/04/2025", True, date(2025, 4, 3), True),
        ("03/04/2025", False, date(2025, 3, 4), True),
        ("13/04/2025", False, date(2025, 4, 13), False),
        ("04/13/2025", True, date(2025, 4, 13), False),
        ("05/05/2025", True, date(2025, 5, 5), False),
        ("2025-04-03", False, date(2025, 4, 3), False),
        ("03-04-25", True, date(2025, 4, 3), True),
    ],
    ids=["ambiguous-day-first", "ambiguous-month-first", "day-over-12-wins",
         "month-over-12-wins", "same-day-and-month", "iso-is-never-ambiguous", "two-digit-year"],
)
def test_date_ambiguity_table(text, day_first, expected, ambiguous):
    when = parse_when(text, day_first=day_first)
    assert (when.at.date(), when.ambiguous) == (expected, ambiguous)


@pytest.mark.parametrize(
    ("values", "known", "expected"),
    [
        (["13/04/2025", "01/05/2025"], False, (True, True)),
        (["04/13/2025", "01/05/2025"], False, (False, True)),
        (["10/03/2025", "11/03/2025", "05/04/2025"], False, (True, True)),
        (["03/10/2025", "03/11/2025", "04/05/2025"], False, (False, True)),
        (["01/02/2025", "02/02/2025", "03/02/2025"], False, (True, False)),
        (["13/04/2025", "04/13/2025", "01/02/2025"], False, (True, False)),
        (["01/02/2025", "02/02/2025"], True, (True, True)),
        (["2025-04-01", "2025-04-02"], False, (True, True)),
    ],
    ids=["proof-day-first", "proof-month-first", "order-says-day-first",
         "order-says-month-first", "nothing-decides", "conflicting-proof",
         "institution-default", "no-ambiguous-values"],
)
def test_file_level_day_month_order(values, known, expected):
    assert resolve_day_first(values, default_is_known=known) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("১৫ এপ্রিল ২০২৫", date(2025, 4, 15)),
        ("১লা জানুয়ারি ২০২৬", date(2026, 1, 1)),
        ("১লা জানুয়ারী ২০২৬", date(2026, 1, 1)),
        ("২১শে ফেব্রুয়ারি ২০২৫", date(2025, 2, 21)),
        ("5 Agost 2025", date(2025, 8, 5)),
        ("ডিসে ৩১, ২০২৫", date(2025, 12, 31)),
        ("01-Apr-2025", date(2025, 4, 1)),
        ("Apr 5, 2025", date(2025, 4, 5)),
    ],
    ids=["bangla-month", "bangla-ordinal-la", "alternate-spelling", "bangla-ordinal-she",
         "banglish-month", "bangla-abbreviation-first", "english-abbreviation",
         "english-month-first"],
)
def test_month_names_in_bangla_banglish_and_english(text, expected):
    assert parse_when(text).at.date() == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("১ বৈশাখ ১৪৩২", date(2025, 4, 14)),
        ("৮ ফাল্গুন ১৪৩১", date(2025, 2, 21)),
        ("১২ চৈত্র ১৪৩১", date(2025, 3, 26)),
        ("১ পৌষ ১৪৩১", date(2024, 12, 16)),
        ("৩১ আশ্বিন ১৪৩২", date(2025, 10, 16)),
        ("30 Falgun 1430", date(2024, 3, 14)),
        ("15 Boishakh 1432", date(2025, 4, 28)),
    ],
    ids=["pohela-boishakh", "ekushey-8-falgun", "independence-12-choitro", "victory-1-poush",
         "last-31-day-month", "leap-falgun-30", "banglish-boishakh"],
)
def test_bengali_calendar_dates_convert_under_the_revised_calendar(text, expected):
    assert parse_when(text).at.date() == expected


@pytest.mark.parametrize(
    ("args", "reason"),
    [((30, 11, 1431), "ingest.date.invalid"), ((31, 12, 1431), "ingest.date.invalid"),
     ((32, 1, 1432), "ingest.date.invalid"), ((15, 1, 2025), "ingest.date.calendar_mismatch")],
    ids=["falgun-30-in-common-year", "choitro-has-30", "no-day-32", "gregorian-year"],
)
def test_impossible_bengali_dates_are_refused(args, reason):
    with pytest.raises(NormaliseError) as err:
        bengali_to_gregorian(*args)
    assert err.value.reason_key == reason


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("০১/০৪/২০২৫ রাত ৯টা", datetime(2025, 4, 1, 21, 0)),
        ("০১/০৪/২০২৫ রাত ১২:৩০", datetime(2025, 4, 1, 0, 30)),
        ("০১/০৪/২০২৫ সকাল ১০:৩০", datetime(2025, 4, 1, 10, 30)),
        ("০১/০৪/২০২৫ দুপুর ১টা", datetime(2025, 4, 1, 13, 0)),
        ("০১/০৪/২০২৫ বিকাল ৪টা", datetime(2025, 4, 1, 16, 0)),
        ("01/04/2025 bikal 4:15", datetime(2025, 4, 1, 16, 15)),
        ("01/04/2025 বিকাল 16:00", datetime(2025, 4, 1, 16, 0)),
        ("2025-04-02 03:24 PM", datetime(2025, 4, 2, 15, 24)),
        ("01/04/2025 12:05 AM", datetime(2025, 4, 1, 0, 5)),
    ],
    ids=["night-nine", "night-half-past-twelve", "morning", "noon-one", "afternoon-four",
         "banglish-afternoon", "24-hour-kept", "english-pm", "english-midnight"],
)
def test_times_of_day_in_bangla_and_english(text, expected):
    assert parse_when(text).at == expected


def test_utc_timestamps_become_dhaka_wall_time():
    assert parse_when("2025-04-01T02:00:00Z").at == datetime(2025, 4, 1, 8, 0)
    assert parse_when("2025-04-01T08:00:00+06:00").at == datetime(2025, 4, 1, 8, 0)


@pytest.mark.parametrize(
    ("text", "reason"),
    [("13/13/2025", "ingest.date.invalid"), ("31/02/2025", "ingest.date.invalid"),
     ("1 Foo 2025", "ingest.date.unknown_month"), ("", "ingest.date.missing"),
     ("01/04/2025 13:00 PM", "ingest.date.invalid_time")],
    ids=["no-month-13", "no-31-february", "unknown-month", "empty", "pm-after-12"],
)
def test_unreadable_dates_carry_a_reason(text, reason):
    with pytest.raises(NormaliseError) as err:
        parse_when(text)
    assert err.value.reason_key == reason


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Amount (BDT)", "amount bdt"), ("Cheque/Ref No", "cheque ref no"),
     ("issue_date", "issue date"), ("  Txn  ID ", "txn id"), ("Date​", "date"),
     ("তারিখ", "তারিখ")],
)
def test_header_keys(text, expected):
    assert header_key(text) == expected
