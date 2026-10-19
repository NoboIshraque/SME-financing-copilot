"""Duplicate detection: same amount + time + reference, without merging genuine repeats."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.ingest.dedupe import dedupe
from tests.ingest.helpers import bank, bkash, csv_bytes, parse

CASH_HEADER = "date,party,category,type,amount,channel,ref"
START = date(2025, 4, 1)


def _cash_book(rows: list[tuple[int, int, str]]) -> bytes:
    return csv_bytes([CASH_HEADER, *(
        f"{(START + timedelta(days=d)).isoformat()},Walk-in,sales,{kind},{amount}.00,cash,R{d}"
        for d, amount, kind in rows)])


def test_reuploaded_statement_adds_nothing():
    first = parse(bkash("A1,01/04/2025 10:00:00,Payment Received,017,100,0,0,SALE-1",
                        "A2,01/04/2025 11:00:00,Payment Received,017,100,0,0,SALE-1"), "b.csv")
    kept, skipped = dedupe(first.transactions, first.transactions, first.strong_ids)
    assert (kept, skipped) == ([], 2)


def test_two_identical_cash_sales_are_not_merged_when_the_ledger_holds_one():
    one = parse(_cash_book([(0, 50, "in")]), "book.csv").transactions
    two = parse(_cash_book([(0, 50, "in"), (0, 50, "in")]), "book.csv")
    kept, skipped = dedupe(two.transactions, one, two.strong_ids)
    assert (len(kept), skipped) == (1, 1)


def test_same_moment_amount_and_reference_on_another_channel_is_not_a_duplicate():
    wallet = parse(bkash("A1,01/04/2025 00:00:00,Payment Received,017,100,0,,R0"), "b.csv")
    book = parse(_cash_book([(0, 100, "in")]), "book.csv")
    kept, skipped = dedupe(book.transactions, wallet.transactions, book.strong_ids)
    assert (len(kept), skipped) == (1, 0)


def test_rows_pinned_by_their_source_id_are_never_dropped_on_a_look_alike():
    old = parse(bkash("A1,01/04/2025 10:00:00,Payment Received,017,100,0,0,SALE-1"), "b.csv")
    new = parse(bkash("A2,01/04/2025 10:00:00,Payment Received,017,100,0,0,SALE-1"), "b.csv")
    kept, skipped = dedupe(new.transactions, old.transactions, new.strong_ids)
    assert ([t.id for t in kept], skipped) == ([new.transactions[0].id], 0)


def test_kept_candidates_stay_in_file_order():
    ledger = parse(_cash_book([(1, 20, "in")]), "book.csv").transactions
    upload = parse(_cash_book([(0, 10, "in"), (1, 20, "in"), (2, 30, "out")]), "book.csv")
    kept, _ = dedupe(upload.transactions, ledger, upload.strong_ids)
    assert [t.amount.amount for t in kept] == [Decimal("10.00"), Decimal("30.00")]


_rows = st.lists(st.tuples(st.integers(0, 6), st.integers(1, 3), st.sampled_from(["in", "out"])),
                 min_size=1, max_size=20)
_windows = st.tuples(st.integers(0, 20), st.integers(0, 20))


def _bounds(n: int, cut: tuple[int, int]) -> tuple[int, int]:
    i, j = sorted(c % (n + 1) for c in cut)
    return i, j


@pytest.mark.property
@given(rows=_rows, cut=_windows)
def test_overlapping_wallet_statements_union_to_the_whole(rows, cut):
    """Unique source ids: any two overlapping windows together give every row exactly once,
    even when rows share amount, time and reference."""
    lines = [f"T{n},{(START + timedelta(days=d)).strftime('%d/%m/%Y')} 10:00:00,"
             f"{'Payment Received' if kind == 'in' else 'Send Money'},017,{amount},0,0,R"
             for n, (d, amount, kind) in enumerate(rows)]
    i, j = _bounds(len(lines), cut)
    first = parse(bkash(*lines[:j]), "b.csv").transactions
    later = parse(bkash(*lines[i:]), "b.csv")
    kept, skipped = dedupe(later.transactions, first, later.strong_ids)
    whole = parse(bkash(*lines), "b.csv").transactions
    assert sorted(t.id for t in first + kept) == sorted(t.id for t in whole)
    assert skipped == j - i


@pytest.mark.property
@given(rows=_rows, cut=_windows)
def test_overlapping_bank_statements_with_running_balance_union_to_the_whole(rows, cut):
    """No source id, but the running balance pins each row: overlaps resolve exactly.

    (Rows identical in every column, balance included, cannot be told apart across files and
    count as one; see app/ingest/dedupe.py. They are excluded here by construction.)"""
    balance, lines, seen = 0, [], set()
    for d, amount, kind in rows:
        balance += amount if kind == "in" else -amount
        assume((d, amount, kind, balance) not in seen)
        seen.add((d, amount, kind, balance))
        debit, credit = ("", amount) if kind == "in" else (amount, "")
        lines.append(f"{(START + timedelta(days=d)).strftime('%d-%b-%Y')},SALES X,R,"
                     f"{debit},{credit},{balance}")
    i, j = _bounds(len(lines), cut)
    first = parse(bank(*lines[:j]), "bank.csv").transactions
    later = parse(bank(*lines[i:]), "bank.csv")
    kept, skipped = dedupe(later.transactions, first, later.strong_ids)
    whole = parse(bank(*lines), "bank.csv").transactions
    assert len(first) + len(kept) == len(whole)
    assert sorted(t.id for t in first + kept) == sorted(t.id for t in whole)
    assert skipped == j - i


@pytest.mark.property
@given(rows=_rows, cut=_windows)
def test_any_window_of_a_committed_cash_book_adds_nothing(rows, cut):
    """Without ids or balances, re-uploading part of what is already in the ledger is
    recognised in full, and nothing new is invented."""
    committed = parse(_cash_book(rows), "book.csv").transactions
    i, j = _bounds(len(rows), cut)
    again = parse(_cash_book(rows[i:j]), "book.csv")
    kept, skipped = dedupe(again.transactions, committed, again.strong_ids)
    assert (kept, skipped) == ([], j - i)


@pytest.mark.property
@given(rows=_rows)
def test_rows_absent_from_the_ledger_are_always_kept(rows):
    upload = parse(_cash_book(rows), "book.csv")
    other_days = parse(_cash_book([(d + 10, amount, kind) for d, amount, kind in rows]),
                       "book.csv").transactions
    kept, skipped = dedupe(upload.transactions, other_days, upload.strong_ids)
    assert (len(kept), skipped) == (len(rows), 0)
