"""Row-level behaviour of the parsers: rejections with reasons, ids, fees, labels, privacy."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.contracts import DataMode, Direction, TxCategory
from app.ingest.normalise import DHAKA
from app.ingest.parties import identifiers
from tests.ingest.helpers import RESOLVER, T, bank, bkash, csv_bytes, parse, reasons

GOOD = "AAA0000001,01/04/2025 12:00:00,Payment Received,01711000001,100.00,0.00,100.00,SALE-1"
LEDGER_HEADER = "date,party,category,type,amount,channel,ref"
REGISTER_HEADER = "number,party,issue_date,due_date,amount,amount_paid,paid_date,status"


def _ledger(*rows: str) -> bytes:
    return csv_bytes([LEDGER_HEADER, *rows])


def _register(*rows: str) -> bytes:
    return csv_bytes([REGISTER_HEADER, *rows])


MALFORMED = {
    # case: (file, filename, reason)
    "amount-missing": (bkash("A1,01/04/2025 12:00:00,Payment Received,017,,0,0,R"), "b.csv",
                       "ingest.amount.missing"),
    "amount-not-a-number": (bkash("A1,01/04/2025 12:00:00,Payment Received,017,12.3.4,0,0,R"),
                            "b.csv", "ingest.amount.invalid"),
    "amount-zero": (bkash("A1,01/04/2025 12:00:00,Payment Received,017,0.00,0,0,R"), "b.csv",
                    "ingest.amount.zero"),
    "amount-sub-paisa": (bkash("A1,01/04/2025 12:00:00,Payment Received,017,10.005,0,0,R"),
                         "b.csv", "ingest.amount.precision"),
    "date-unreadable": (bkash("A1,yesterday,Payment Received,017,10,0,0,R"), "b.csv",
                        "ingest.date.invalid"),
    "date-impossible": (bkash("A1,31/02/2025 10:00:00,Payment Received,017,10,0,0,R"), "b.csv",
                        "ingest.date.invalid"),
    "time-impossible": (bkash("A1,01/04/2025 25:61:00,Payment Received,017,10,0,0,R"), "b.csv",
                        "ingest.date.invalid_time"),
    "type-unknown": (bkash("A1,01/04/2025 12:00:00,Mystery,017,10,0,0,R"), "b.csv",
                     "ingest.type.unknown"),
    "debit-and-credit": (bank("01-Apr-2025,X,R,10.00,20.00,0"), "bank.csv",
                         "ingest.row.both_debit_and_credit"),
    "no-amount": (bank("01-Apr-2025,COUNTER CHEQUE,R,,,0"), "bank.csv", "ingest.amount.missing"),
    "direction-unknown": (_ledger("2025-04-01,Rahim,sales,maybe,10,cash,R"), "book.csv",
                          "ingest.direction.unknown"),
    "channel-unknown": (_ledger("2025-04-01,Rahim,sales,in,10,barter,R"), "book.csv",
                        "ingest.channel.unknown"),
    "extra-cells": (bank("01-Apr-2025,X,R,10.00,,0,UNEXPECTED"), "bank.csv",
                    "ingest.row.column_mismatch"),
    "summary-line": (bank("Total,,,10.00,20.00,"), "bank.csv", "ingest.row.summary"),
    "status-unknown": (_register("INV-1,Rahim,2025-04-01,2025-04-10,500,0,,lost"), "baki.csv",
                       "ingest.document.status_unknown"),
    "paid-without-date": (_register("INV-1,Rahim,2025-04-01,2025-04-10,500,500,,"), "baki.csv",
                          "ingest.document.invalid"),
    "due-before-issue": (_register("INV-1,Rahim,2025-04-10,2025-04-01,500,0,,open"), "baki.csv",
                         "ingest.document.invalid"),
    "number-missing": (_register(",Rahim,2025-04-01,2025-04-10,500,0,,open"), "baki.csv",
                       "ingest.document.number_missing"),
}


@pytest.mark.parametrize("case", list(MALFORMED))
def test_malformed_row_is_rejected_with_its_reason(case):
    data, filename, reason = MALFORMED[case]
    result = parse(data, filename)
    assert reasons(result) == [reason]
    assert result.transactions == result.invoices == []
    assert result.unparsed[0].row_ref == f"{filename}#L2"


def test_good_rows_survive_next_to_bad_ones():
    result = parse(bkash(GOOD, "A2,31/02/2025 10:00:00,Payment Received,017,10,0,0,R"), "b.csv")
    assert [t.id for t in result.transactions] == [f"{T}:bkash:AAA0000001"]
    assert reasons(result) == ["ingest.date.invalid"]


def test_repeated_source_transaction_id_is_a_duplicate_not_a_second_sale():
    result = parse(bkash(GOOD, GOOD), "b.csv")
    assert len(result.transactions) == 1
    assert result.duplicates_skipped == 1


def test_wallet_fee_becomes_its_own_outflow():
    row = "AB1,05/04/2025 19:45:00,Send Money,01811000000,1200.00,5.00,900.00,GRO-BILL-9"
    sent, fee = parse(bkash(row), "b.csv").transactions
    assert (sent.category, sent.amount.amount) == (TxCategory.supplier_payment, Decimal("1200"))
    assert (fee.id, fee.direction, fee.category, fee.amount.amount) == (
        f"{sent.id}:fee", Direction.outflow, TxCategory.fee, Decimal("5.00"))
    assert fee.counterparty_token is None


def test_negative_amount_without_a_known_type_is_an_outflow():
    row = "AB1,05/04/2025 19:45:00,Adjustment,01811000000,-50.00,0,0,R"
    (txn,) = parse(bkash(row), "b.csv").transactions
    assert (txn.direction, txn.amount.amount) == (Direction.outflow, Decimal("50.00"))


def test_moments_are_dhaka_local_and_date_only_rows_sit_at_midnight():
    (wallet,) = parse(bkash(GOOD), "b.csv").transactions
    (banked,) = parse(bank("02-Apr-2025,SALES Walk-in,R,,650.00,0"), "bank.csv").transactions
    assert wallet.occurred_at == datetime(2025, 4, 1, 12, 0, tzinfo=DHAKA)
    assert banked.occurred_at == datetime(2025, 4, 2, 0, 0, tzinfo=DHAKA)
    assert wallet.occurred_at.utcoffset().total_seconds() == 6 * 3600


def test_ids_are_stable_and_identical_rows_stay_distinct():
    rows = ["2025-04-02,Walk-in customer,sales,in,1633.00,cash,SALE-250402"] * 2
    first = [t.id for t in parse(_ledger(*rows), "book.csv").transactions]
    again = [t.id for t in parse(_ledger(*rows), "book.csv").transactions]
    longer = [t.id for t in parse(_ledger(*rows, "2025-04-03,Walk-in customer,sales,in,99,cash,"
                                          "SALE-250403"), "book.csv").transactions]
    assert first == again
    assert len(set(first)) == 2
    assert longer[:2] == first  # appending rows never renumbers earlier ones


def test_data_mode_column_wins_and_synthetic_is_never_lost():
    plain = parse(bkash(GOOD), "b.csv", data_mode=DataMode.real_anonymised)
    mixed = parse(csv_bytes(["TrxID,Date Time,Transaction Type,From/To,Amount (BDT),Data Mode",
                             "A1,01/04/2025 12:00:00,Payment Received,017,10,live",
                             "A2,01/04/2025 13:00:00,Payment Received,017,10,synthetic"]), "b.csv")
    assert plain.data_mode is DataMode.real_anonymised
    assert [t.data_mode for t in mixed.transactions] == [DataMode.live, DataMode.synthetic]
    assert mixed.data_mode is DataMode.synthetic


def test_collection_links_to_its_invoice():
    row = "AB1,05/04/2025 10:00:00,Payment Received,01811000000,500,0,0,GRO-INV-00135"
    (txn,) = parse(bkash(row), "b.csv").transactions
    assert (txn.category, txn.invoice_id) == (TxCategory.collection, f"{T}:GRO-INV-00135")


def test_bank_narration_is_split_into_category_and_counterparty():
    (txn,) = parse(bank("02-Apr-2025,COLLECTION Dhaka Traders,R,,1579.00,0"),
                   "bank.csv").transactions
    assert txn.category is TxCategory.collection
    assert txn.counterparty_token == RESOLVER.resolve(T, identifiers("Dhaka Traders"))


def test_raw_phone_numbers_never_reach_the_records_or_excerpts():
    data = bkash(GOOD, "A2,31/02/2025 10:00:00,Payment Received,01711000001,10,0,0,R")
    result = parse(data, "b.csv")
    dumped = "".join(t.model_dump_json() for t in result.transactions)
    assert "01711000001" not in dumped and "1711000001" not in dumped
    assert "1711000001" not in result.unparsed[0].raw_excerpt
    assert result.transactions[0].counterparty_token.startswith("PARTY_")


def test_register_without_due_date_is_due_on_issue():
    data = csv_bytes(["number,party,issue_date,amount,amount_paid", "INV-9,Rahim,2025-04-01,500,0"])
    (doc,) = parse(data, "baki.csv").invoices
    assert doc.due_date == doc.issue_date
    assert doc.status.value == "open"


# ---------------------------------------------------------------- ambiguous dates -> drafts

AMBIGUOUS = ["01/02/2025,Rahim,sales,in,500,cash,R1", "03/02/2025,Karim,sales,in,700,cash,R2"]


def test_hand_made_ledger_with_undecidable_dates_becomes_drafts():
    result = parse(_ledger(*AMBIGUOUS), "book.csv")
    assert result.transactions == []
    assert [(d.row_ref, d.flagged, d.confidence) for d in result.drafts] == [
        ("book.csv#L2", True, Decimal("0.50")), ("book.csv#L3", True, Decimal("0.50"))]
    assert result.drafts[0].transaction.occurred_at.date().isoformat() == "2025-02-01"


def test_owner_stating_the_order_removes_the_doubt():
    result = parse(_ledger(*AMBIGUOUS), "book.csv", day_first=False)
    assert result.drafts == []
    assert [t.occurred_at.date().isoformat() for t in result.transactions] == [
        "2025-01-02", "2025-03-02"]


def test_one_unambiguous_date_settles_the_whole_file():
    result = parse(_ledger(*AMBIGUOUS, "13/02/2025,Rahim,sales,in,100,cash,R3"), "book.csv")
    assert result.drafts == [] and len(result.transactions) == 3


def test_ambiguous_invoices_become_drafts_and_ambiguous_bills_are_refused():
    rows = ["INV-1,Rahim,01/02/2025,03/02/2025,500,0,,open",
            "INV-2,Karim,02/02/2025,04/02/2025,700,0,,open"]
    invoices = parse(_register(*rows), "baki.csv")
    bills = parse(_register(*(r.replace("INV", "BILL") for r in rows)), "bills.csv")
    assert [d.invoice.id for d in invoices.drafts] == [f"{T}:INV-1", f"{T}:INV-2"]
    assert invoices.invoices == []
    assert reasons(bills) == ["ingest.date.ambiguous"] * 2 and bills.bills == []


def test_institution_statements_are_read_day_first_without_drafts():
    result = parse(bkash("A1,01/02/2025 10:00:00,Payment Received,017,10,0,0,R",
                         "A2,02/02/2025 10:00:00,Payment Received,017,10,0,0,R"), "b.csv")
    assert result.drafts == []
    assert [t.occurred_at.date().isoformat() for t in result.transactions] == [
        "2025-02-01", "2025-02-02"]
