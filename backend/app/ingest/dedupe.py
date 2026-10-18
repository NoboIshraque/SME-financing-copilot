"""Duplicate detection across uploads (WP-02 milestone 2).

Statements overlap: April's export repeats the last days of March, and owners upload the same
file twice. A candidate is a duplicate of a ledger transaction when

- it has a strong identity (the source's own transaction id, or a running balance that pins
  the row) and that id is already in the ledger, or
- it has no strong identity and the ledger holds a transaction with the same moment, amount,
  direction, channel and reference that no other candidate has claimed.

The second rule matches multisets, so two genuine identical cash sales on one day are not
merged into one: only as many candidates are dropped as the ledger already holds.

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
) -> tuple[list[Transaction], int]:
    """Candidates that are new, in their original order, and how many were duplicates."""
    existing = list(existing)
    known_ids = {t.id for t in existing}
    unclaimed = Counter(match_key(t) for t in existing)
    duplicate = [False] * len(candidates)
    for index, txn in enumerate(candidates):
        if txn.id in known_ids:
            duplicate[index] = True
            key = match_key(txn)
            if unclaimed[key] > 0:
                unclaimed[key] -= 1
    for index, txn in enumerate(candidates):
        if duplicate[index] or txn.id in strong_ids:
            continue
        key = match_key(txn)
        if unclaimed[key] > 0:
            unclaimed[key] -= 1
            duplicate[index] = True
    kept = [t for t, dup in zip(candidates, duplicate, strict=True) if not dup]
    return kept, sum(duplicate)
