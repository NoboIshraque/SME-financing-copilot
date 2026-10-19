"""Reminder ladder (WP-05 milestone 4; FEATURES Q2, N2).

Each open invoice has reminders at due -3 days (friendly, pre-due), due day, +3, +10 and +20.
Per customer, the plan takes the most urgent invoice: its next step on or after `as_of` (an
invoice more than 20 days late stays on the last step). One card per customer, soonest first.

Sending a message leaves Hishab, so the card is `send_reminder` at EXECUTE tier: the owner
approves it with a step-up code (WP-11). Sending channels were cut (WP-12), so an approved
reminder is recorded and the owner sends the drafted text themselves. The payment link is a
placeholder until a payment provider is connected.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.contracts import ActionCard, ActionType, Figure, Invoice, Money, Provenance, Tier, Unit
from app.engines.receivables.aging import is_open, open_amount

STEPS = ((-3, "pre_due"), (0, "due"), (3, "plus_3"), (10, "plus_10"), (20, "plus_20"))
FORMULA_ID = "receivables.reminder_amount"


@dataclass(frozen=True)
class Step:
    offset: int
    name: str
    send_on: date


def next_step(invoice: Invoice, as_of: date) -> Step:
    for offset, name in STEPS:
        day = invoice.due_date + timedelta(days=offset)
        if day >= as_of:
            return Step(offset, name, day)
    return Step(STEPS[-1][0], STEPS[-1][1], as_of)


def plan(invoices: Sequence[Invoice], as_of: date, label: Callable[[str], str]) -> list[ActionCard]:
    by_customer: dict[str, list[Invoice]] = defaultdict(list)
    for inv in invoices:
        if is_open(inv, as_of):
            by_customer[inv.counterparty_token].append(inv)
    cards = []
    for token, docs in by_customer.items():
        docs.sort(key=lambda d: (d.due_date, d.id))
        step = min((next_step(d, as_of) for d in docs), key=lambda s: (s.send_on, -s.offset))
        total = sum((open_amount(d) for d in docs), Money.zero())
        ids = tuple(d.id for d in docs)
        impact = Figure(
            id=f"remind:{token}:{as_of.isoformat()}:amount",
            label_key="action.expected_collection", value=total.amount, unit=Unit.BDT,
            data_mode=docs[0].data_mode,
            provenance=Provenance(formula_id=FORMULA_ID, formula_version=1, source_row_ids=ids,
                                  parameters={"as_of": as_of.isoformat()}))
        pre_due = step.name == "pre_due"
        cards.append(ActionCard(
            id=f"remind:{token}:{step.send_on.isoformat()}",
            title_key="action.send_pre_due_reminder" if pre_due else "action.send_reminder",
            action_type=ActionType.send_reminder,
            tier=Tier.EXECUTE,
            payload={"counterparty_label": label(token), "due_date": docs[0].due_date.isoformat(),
                     "invoice_count": str(len(docs)), "step": step.name,
                     "send_on": step.send_on.isoformat(), "invoice_ids": list(ids),
                     "payment_link": "placeholder"},
            impact=impact,
            expires_at=datetime.combine(step.send_on + timedelta(days=1), time(), tzinfo=UTC),
        ))
    return sorted(cards, key=lambda c: (c.payload["send_on"], c.id))
