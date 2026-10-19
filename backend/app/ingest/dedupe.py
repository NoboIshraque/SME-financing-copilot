"""Duplicate detection across uploads (WP-02 milestone 2).

Statements overlap: April's export repeats the last days of March, and owners upload the same
file twice. Some transactions are pinned by their source: they carry the source's own
transaction id (a bKash TrxID) or a running balance that fixes the row. Others are not: rows
from a cash book without ids, rows typed in by hand, and the seeded demo ledger. A candidate is
a duplicate of a ledger transaction when

- its id is already in the ledger, or
- the ledger holds a transaction with the same moment, amount, direction, channel and
  reference (`match_key`, the weak key) that no other candidate has claimed, and at least one
  of the two is unpinned.

Two pinned rows only ever match by id: two different TrxIDs are two payments even when every
other column agrees. A pinned candidate may still match an unpinned ledger row on the weak key,
so the shop's own bKash statement is recognised in a ledger that was seeded or typed in without
TrxIDs, instead of being counted twice.

The weak-key rule matches multisets, so two genuine identical cash sales on one day are not
merged into one: only as many candidates are dropped as the ledger already holds. An unpinned
candidate claims a pinned ledger row before an unpinned one, since a pinned candidate could
only use the latter; that way as many duplicates as possible are found and never more.

Which ledger rows are unpinned is the caller's knowledge (the ingest service keeps the pinned
ids of every committed upload); a ledger row not named unpinned is treated as pinned.

Known limit: two rows identical in every column, running balance included (a deposit, an equal
withdrawal and the same deposit again on one day), cannot be told apart across overlapping
files, so the second upload's copy counts as the one already held.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime
from decimal import Decimal

from app.contracts import Channel, Direction, Transaction

Key = tuple[datetime, Decimal, Direction, Channel, str]


def match_key(txn: Transaction) -> Key:
    """Same amount + time + reference (and direction/channel, which a duplicate shares too)."""
    return (txn.occurred_at, txn.amount.amount, txn.direction, txn.channel, txn.reference or "")


def dedupe(
    candidates: Sequence[Transaction],
    existing: Iterable[Transaction],
    strong_ids: Collection[str] = (),
    *,
    unpinned_ledger_ids: Collection[str] = (),
) -> tuple[list[Transaction], int]:
    """Candidates that are new, in their original order, and how many were duplicates.

    `strong_ids`: the candidates pinned by their source (`ParseResult.strong_ids`).
    `unpinned_ledger_ids`: the ledger transactions known to have no strong identity."""
    existing = list(existing)
    unpinned = set(unpinned_ledger_ids)
    held = {t.id: t for t in existing}
    # Unclaimed ledger rows per weak key, pinned and unpinned counted apart.
    pinned_left: Counter[Key] = Counter()
    unpinned_left: Counter[Key] = Counter()
    for t in existing:
        (unpinned_left if t.id in unpinned else pinned_left)[match_key(t)] += 1
    duplicate = [False] * len(candidates)
    for index, txn in enumerate(candidates):
        row = held.get(txn.id)
        if row is None:
            continue
        duplicate[index] = True
        left = unpinned_left if row.id in unpinned else pinned_left
        if left[match_key(row)] > 0:
            left[match_key(row)] -= 1
    for index, txn in enumerate(candidates):
        if duplicate[index]:
            continue
        key = match_key(txn)
        if txn.id not in strong_ids and pinned_left[key] > 0:
            pinned_left[key] -= 1
        elif unpinned_left[key] > 0:
            unpinned_left[key] -= 1
        else:
            continue
        duplicate[index] = True
    kept = [t for t, dup in zip(candidates, duplicate, strict=True) if not dup]
    return kept, sum(duplicate)
