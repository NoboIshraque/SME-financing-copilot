from datetime import date, datetime

import pytest

from app.ingest.tabular import TableError, cell_text, decode_text, read_sheets
from tests.ingest.helpers import csv_bytes, xlsx_bytes


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("﻿তারিখ,টাকা".encode(), "তারিখ,টাকা"),
        ("তারিখ,টাকা".encode("utf-16"), "তারিখ,টাকা"),
        ("তারিখ,টাকা".encode(), "তারিখ,টাকা"),
        ("Caf\xe9,1".encode("latin-1"), "Caf\xe9,1"),
    ],
    ids=["utf8-bom", "utf16-bom", "utf8", "latin1-fallback"],
)
def test_text_decoding(data, expected):
    assert decode_text(data) == expected


def test_csv_rows_keep_their_physical_line_reference():
    data = b'a,b\n1,"two\nlines"\n3,4\n'
    (sheet,) = read_sheets(data, "f.csv")
    assert [(r.ref, r.cells) for r in sheet.rows] == [
        ("f.csv#L1", ("a", "b")), ("f.csv#L3", ("1", "two\nlines")), ("f.csv#L4", ("3", "4"))]


def test_xlsx_rows_reference_sheet_and_row():
    sheets = read_sheets(xlsx_bytes([["Date", "Amount"], [date(2025, 4, 1), 12.5]],
                                    before=[("Cover", [["Hello"]])]), "book.xlsx")
    assert [s.name for s in sheets] == ["Cover", "Statement"]
    assert [(r.ref, r.cells) for r in sheets[1].rows] == [
        ("book.xlsx!Statement#R1", ("Date", "Amount")),
        ("book.xlsx!Statement#R2", ("2025-04-01", "12.5"))]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2479.0, "2479"),
        (0.1, "0.1"),
        (1234.56, "1234.56"),
        (datetime(2025, 4, 1), "2025-04-01"),
        (datetime(2025, 4, 1, 18, 30), "2025-04-01 18:30:00"),
        (None, ""),
        (True, "TRUE"),
        ("  padded ", "padded"),
    ],
    ids=["whole-float", "tenth", "paisa", "midnight-is-a-date", "datetime", "empty", "bool",
         "text"],
)
def test_spreadsheet_cells_become_exact_text(value, expected):
    assert cell_text(value) == expected


def test_semicolon_delimiter_is_sniffed():
    (sheet,) = read_sheets(csv_bytes(["a;b", "1;2"]), "f.csv")
    assert sheet.rows[1].cells == ("1", "2")


def test_empty_upload_is_refused():
    with pytest.raises(TableError) as err:
        read_sheets(b"", "f.csv")
    assert err.value.reason_key == "ingest.file.empty"
