"""One case per supported format variant: detection, header location and row reading."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.contracts import Channel, Direction, SourceFormat, TxCategory
from tests.ingest.helpers import BKASH_HEADER, csv_bytes, parse, reasons, xlsx_bytes

D = Decimal
IN, OUT = Direction.inflow, Direction.outflow
BKASH_ROWS = [
    "9C78BFNDBF,01/04/2025 12:21:40,Payment Received,01339325575,2479.00,0.00,81789.00,SALE-250401",
    "JXDWNH7E3L,13/04/2025 09:05:00,bKash to Bank,Own bank account,5000.00,0.00,76789.00,"
    "SWEEP-BKASH-250413",
]


def _bkash_xlsx() -> bytes:
    rows = [[c for c in line.split(",")] for line in [BKASH_HEADER, *BKASH_ROWS]]
    return xlsx_bytes(rows, before=[("Info", [["bKash merchant statement"], ["Wallet", "01X"]])])


def _bank_xlsx_with_preamble_and_totals() -> bytes:
    return xlsx_bytes([
        ["Dutch-Bangla Bank PLC"],
        ["Account Name", "Mirpur Mudi Store"],
        ["Statement Period", "01/04/2025 to 30/04/2025"],
        [],
        ["Txn Date", "Particulars", "Cheque No", "Withdrawal", "Deposit", "Balance"],
        [datetime(2025, 4, 1), "Opening Balance", None, None, None, 209867],
        [datetime(2025, 4, 2), "COLLECTION Dhaka Traders", "GRO-INV-00135", None, 1579, 211446],
        [datetime(2025, 4, 3), "RENT Rafiq Sarkar", "RENT-202504", 35000, None, 176446],
        ["Total", None, None, 35000, 1579, None],
    ])


CASES = {
    # name: (filename, file bytes, expected format, expected (moment, amount, direction) rows)
    "bkash-csv": ("bkash_statement.csv", csv_bytes([BKASH_HEADER, *BKASH_ROWS]),
                  SourceFormat.bkash_statement,
                  [(datetime(2025, 4, 1, 12, 21, 40), D("2479.00"), IN),
                   (datetime(2025, 4, 13, 9, 5), D("5000.00"), OUT)]),
    "bkash-xlsx-second-sheet": ("statement.xlsx", _bkash_xlsx(), SourceFormat.bkash_statement,
                                [(datetime(2025, 4, 1, 12, 21, 40), D("2479.00"), IN),
                                 (datetime(2025, 4, 13, 9, 5), D("5000.00"), OUT)]),
    "bkash-bom-and-preamble": (
        "merchant.csv",
        "﻿bKash Merchant Statement\nWallet: 01711000000\nPeriod: 01/04/2025 - 30/04/2025\n"
        .encode() + csv_bytes([BKASH_HEADER, BKASH_ROWS[0]]),
        SourceFormat.bkash_statement, [(datetime(2025, 4, 1, 12, 21, 40), D("2479.00"), IN)]),
    "wallet-separate-date-and-time": (
        "bkash_export.csv",
        csv_bytes(["Transaction ID,Date,Time,Transaction Type,Account,Amount,Fee,Balance",
                   "AB12CD34EF,05/04/2025,7:45 PM,Send Money,01811000000,1200,5,900"]),
        SourceFormat.bkash_statement, [(datetime(2025, 4, 5, 19, 45), D("1200.00"), OUT),
                                       (datetime(2025, 4, 5, 19, 45), D("5.00"), OUT)]),
    "nagad-csv": (
        "nagad_statement.csv",
        csv_bytes(["Txn ID,Txn Date,Txn Type,Counterpart,Amount,Charge,Balance",
                   "8SA7349W5T49,2025-04-02 03:24 PM,Received,01747382007,1385.00,0.00,44000.00"]),
        SourceFormat.nagad_statement, [(datetime(2025, 4, 2, 15, 24), D("1385.00"), IN)]),
    "nagad-told-apart-by-type-labels": (
        "wallet.csv",
        csv_bytes(["Transaction ID,Date,Type,Amount", "N1,02/04/2025 10:00,Received,700",
                   "N2,03/04/2025 11:00,Sent,200"]),
        SourceFormat.nagad_statement, [(datetime(2025, 4, 2, 10, 0), D("700.00"), IN),
                                       (datetime(2025, 4, 3, 11, 0), D("200.00"), OUT)]),
    "bank-debit-credit-csv": (
        "bank_statement.csv",
        csv_bytes(["Date,Description,Cheque/Ref No,Debit,Credit,Balance",
                   "01-Apr-2025,OWNER DRAW Owner (personal account),DRAW-202504,11452.00,,"
                   "209867.00",
                   "02-Apr-2025,COLLECTION Dhaka Traders,GRO-INV-00135,,1579.00,211446.00"]),
        SourceFormat.bank_csv, [(datetime(2025, 4, 1), D("11452.00"), OUT),
                                (datetime(2025, 4, 2), D("1579.00"), IN)]),
    "bank-amount-with-drcr-column": (
        "statement.csv",
        csv_bytes(["Txn Date,Particulars,Ref No,Amount,Dr/Cr,Balance",
                   "05/04/2025,BEFTN ABC TRADERS,R1,\"12,500.00\",CR,50000.00",
                   "06/04/2025,CHEQUE 4411,4411,\"2,000.00\",DR,48000.00"]),
        SourceFormat.bank_csv, [(datetime(2025, 4, 5), D("12500.00"), IN),
                                (datetime(2025, 4, 6), D("2000.00"), OUT)]),
    "bank-amount-with-drcr-suffix": (
        "statement.csv",
        csv_bytes(["Date,Narration,Amount,Balance", "07/04/2025,NPSB TRANSFER,1500.00 Dr,100",
                   "08/04/2025,CASH DEPOSIT,\"৳ ২,০০০.০০ Cr\",2100"]),
        SourceFormat.bank_csv, [(datetime(2025, 4, 7), D("1500.00"), OUT),
                                (datetime(2025, 4, 8), D("2000.00"), IN)]),
    "bank-xlsx-preamble-and-totals": (
        "dbbl.xlsx", _bank_xlsx_with_preamble_and_totals(), SourceFormat.bank_csv,
        [(datetime(2025, 4, 2), D("1579.00"), IN), (datetime(2025, 4, 3), D("35000.00"), OUT)]),
    "bank-utf16-tab-separated": (
        "statement.txt",
        csv_bytes(["Date\tDescription\tDebit\tCredit\tBalance",
                   "09/04/2025\tUTILITY DESCO\t900.00\t\t1200.00"], encoding="utf-16"),
        SourceFormat.bank_csv, [(datetime(2025, 4, 9), D("900.00"), OUT)]),
    "bank-semicolon-separated": (
        "statement.csv",
        csv_bytes(["Date;Description;Debit;Credit;Balance",
                   "10/04/2025;SALES Walk-in;;650.00;1850.00"]),
        SourceFormat.bank_csv, [(datetime(2025, 4, 10), D("650.00"), IN)]),
    "ledger-bangla-headers-and-digits": (
        "khata.csv",
        csv_bytes(["তারিখ,বিবরণ,জমা,খরচ", "০১/০৪/২০২৫,মাল বিক্রি,১২০০,",
                   "০২/০৪/২০২৫,দোকান ভাড়া,,৩৫০০০"]),
        SourceFormat.ledger_csv, [(datetime(2025, 4, 1), D("1200.00"), IN),
                                  (datetime(2025, 4, 2), D("35000.00"), OUT)]),
    "ledger-xlsx-native-cells": (
        "cashbook.xlsx",
        xlsx_bytes([["Date", "Party", "Category", "Type", "Amount", "Channel"],
                    [date(2025, 4, 3), "Walk-in customer", "sales", "in", 2364.5, "cash"],
                    [datetime(2025, 4, 4, 18, 30), "Janata Bhandar", "purchase", "out", 7000,
                     "bkash"]]),
        SourceFormat.ledger_xlsx, [(datetime(2025, 4, 3), D("2364.50"), IN),
                                   (datetime(2025, 4, 4, 18, 30), D("7000.00"), OUT)]),
}


@pytest.mark.parametrize("name", list(CASES))
def test_format_variant_is_detected_and_read(name):
    filename, data, expected_format, expected_rows = CASES[name]
    result = parse(data, filename)
    got = [(t.occurred_at.replace(tzinfo=None), t.amount.amount, t.direction)
           for t in result.transactions]
    assert result.source_format is expected_format
    assert got == expected_rows
    assert all(r == "ingest.row.summary" for r in reasons(result))


def test_bank_summary_rows_are_reported_not_dropped():
    result = parse(_bank_xlsx_with_preamble_and_totals(), "dbbl.xlsx")
    assert [(u.row_ref, u.reason_key) for u in result.unparsed] == [
        ("dbbl.xlsx!Statement#R6", "ingest.row.summary"),
        ("dbbl.xlsx!Statement#R9", "ingest.row.summary"),
    ]


def test_bangla_ledger_categories_come_from_bangla_words():
    _f, data, _fmt, _rows = CASES["ledger-bangla-headers-and-digits"]
    assert [t.category for t in parse(data, "khata.csv").transactions] == [
        TxCategory.sales, TxCategory.rent]


def test_ledger_channel_column_sets_the_channel():
    _f, data, _fmt, _rows = CASES["ledger-xlsx-native-cells"]
    assert [t.channel for t in parse(data, "cashbook.xlsx").transactions] == [
        Channel.cash, Channel.bkash]


@pytest.mark.parametrize(
    ("filename", "kind", "header_number", "expected"),
    [
        ("baki_register.csv", None, "X-1", ("invoices", 1)),
        ("bills.csv", None, "X-1", ("bills", 1)),
        ("register.csv", None, "GRO-INV-7", ("invoices", 1)),
        ("register.csv", None, "SUP-BILL-7", ("bills", 1)),
        ("register.csv", "bill", "X-1", ("bills", 1)),
    ],
    ids=["filename-baki", "filename-bills", "number-inv", "number-bill", "explicit-kind"],
)
def test_register_kind_comes_from_option_filename_or_numbers(filename, kind, header_number,
                                                             expected):
    data = csv_bytes(["number,party,phone,issue_date,due_date,amount,amount_paid,paid_date,status",
                      f"{header_number},Green Traders,01830296422,2025-03-09,2025-03-24,839.00,"
                      "0.00,,open"])
    result = parse(data, filename, document_kind=kind)
    attr, count = expected
    assert len(getattr(result, attr)) == count
    assert result.unparsed == []


def test_register_kind_that_cannot_be_told_is_asked_for():
    data = csv_bytes(["number,party,issue_date,due_date,amount", "77,Green Traders,2025-03-09,"
                      "2025-03-24,839.00"])
    result = parse(data, "register.csv")
    assert (result.invoices, result.bills) == ([], [])
    assert reasons(result) == ["ingest.document.kind_required"]


def test_explicit_column_mapping_reads_an_unrecognised_ledger():
    data = csv_bytes(["When,What,Money,InOut", "2025-04-05,Rent for April,35000,out"])
    mapping = {"when": "When", "description": "What", "amount": "Money", "direction": "InOut"}
    result = parse(data, "export.csv", mapping=mapping)
    (txn,) = result.transactions
    assert (result.source_format, txn.direction, txn.category) == (
        SourceFormat.ledger_csv, OUT, TxCategory.rent)


def test_mapping_naming_a_missing_header_is_refused():
    data = csv_bytes(["When,Money", "2025-04-05,35000"])
    result = parse(data, "export.csv", mapping={"when": "When", "amount": "Cash"})
    assert reasons(result) == ["ingest.mapping.headers_not_found"]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "ingest.file.empty"),
        (b"PK\x03\x04not really a workbook", "ingest.file.malformed_xlsx"),
        (csv_bytes(["kind,counterparty,frequency", "rent,Rafiq,monthly"]),
         "ingest.format.unknown"),
    ],
    ids=["empty", "corrupt-xlsx", "no-known-header"],
)
def test_unreadable_files_are_reported_with_a_reason(data, reason):
    result = parse(data, "upload.csv")
    assert result.source_format is SourceFormat.unknown
    assert reasons(result) == [reason]
