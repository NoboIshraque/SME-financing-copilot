from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import ActionType, DataMode, DocumentStatus, Invoice, Money, Tier
from app.engines.receivables.aging import aging, bucket, histories
from app.engines.receivables.ladder import next_step, plan
from app.engines.receivables.risk import NO_HISTORY_POINTS, score, score_all

AS_OF = date(2026, 9, 30)


def inv(n: int, *, customer: str = "C1", amount: str = "1000", due: date = AS_OF,
        paid: str = "0", status: DocumentStatus = DocumentStatus.open,
        paid_date: date | None = None, issue: date | None = None) -> Invoice:
    issue = issue or due - timedelta(days=30)
    return Invoice(id=f"t:INV-{n}", tenant_id="t", counterparty_token=customer, issue_date=issue,
                   due_date=due, amount=Money.of(amount), amount_paid=Money.of(paid),
                   status=status, paid_date=paid_date, source_ref=f"r#{n}",
                   data_mode=DataMode.synthetic)


def paid_inv(n: int, days_late: int, customer: str = "C1", amount: str = "1000") -> Invoice:
    due = AS_OF - timedelta(days=60)
    return inv(n, customer=customer, amount=amount, due=due, paid=amount,
               status=DocumentStatus.paid, paid_date=due + timedelta(days=days_late))


@pytest.mark.parametrize("days, expected", [
    (0, "0_30"), (30, "0_30"), (31, "31_60"), (60, "31_60"), (61, "61_90"), (90, "61_90"),
    (91, "90_plus"),
])
def test_bucket_boundaries(days, expected):
    assert bucket(days) == expected


def test_aging_counts_only_what_is_still_owed():
    docs = [inv(1, due=AS_OF - timedelta(days=45), amount="500", paid="200"),  # 300 left, 31-60
            inv(2, due=AS_OF + timedelta(days=5)),                              # not yet due
            paid_inv(3, 2),                                                     # paid: out
            inv(4, status=DocumentStatus.written_off),                          # written off: out
            inv(5, issue=AS_OF + timedelta(days=1), due=AS_OF + timedelta(days=9))]  # future
    totals = {b.bucket: (b.amount.amount, b.count) for b in aging(docs, AS_OF)}
    assert totals == {"0_30": (Decimal("1000.00"), 1), "31_60": (Decimal("300.00"), 1),
                      "61_90": (Decimal("0.00"), 0), "90_plus": (Decimal("0.00"), 0)}


def test_history_late_share_and_median_days_late():
    hist = histories([paid_inv(1, -2), paid_inv(2, 4), paid_inv(3, 10)], AS_OF)["C1"]
    assert (hist.paid_count, hist.late_count) == (3, 2)
    assert hist.median_days_late == Decimal(4)


@given(st.integers(min_value=0, max_value=200), st.integers(min_value=0, max_value=200))
def test_risk_never_falls_as_lateness_rises(a, b):
    early, late = sorted((a, b))
    history = histories([paid_inv(1, 5)], AS_OF)
    def at(days):
        return score(inv(9, due=AS_OF - timedelta(days=days)), history["C1"], others_open=0,
                     as_of=AS_OF).score
    assert at(early) <= at(late)


def test_unknown_customer_carries_uncertainty_but_no_invented_factor():
    risk = score(inv(1, due=AS_OF + timedelta(days=3)), None, others_open=0, as_of=AS_OF)
    assert risk.score == NO_HISTORY_POINTS and risk.factor_keys == []


def test_dispute_raises_risk_and_a_recent_payment_lowers_it():
    slow = histories([paid_inv(1, 20)], AS_OF)["C1"]
    open_inv = inv(2, due=AS_OF - timedelta(days=10))
    base = score(open_inv, slow, others_open=0, as_of=AS_OF)
    disputed = score(open_inv.model_copy(update={"status": DocumentStatus.disputed}), slow,
                     others_open=0, as_of=AS_OF)
    recent = histories([paid_inv(1, 20), inv(3, due=AS_OF - timedelta(days=5), paid="1000",
                                              status=DocumentStatus.paid,
                                              paid_date=AS_OF - timedelta(days=2))], AS_OF)["C1"]
    relieved = score(open_inv, recent, others_open=0, as_of=AS_OF)
    assert disputed.score - base.score == Decimal(20) and "risk.disputed" in disputed.factor_keys
    assert relieved.score < base.score


def test_top_three_factors_explain_the_score_largest_first():
    hist = histories([paid_inv(1, 30), paid_inv(2, 40, amount="1000")], AS_OF)
    docs = [inv(3, amount="3000", due=AS_OF - timedelta(days=80))] + \
        [inv(10 + i, due=AS_OF - timedelta(days=1)) for i in range(5)]
    risk = score_all(docs, hist, AS_OF)["t:INV-3"]
    assert risk.factor_keys == ["risk.days_late", "risk.history_slow", "risk.amount_above_usual"]
    values = [v for _, v in risk.factors]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("due_in, step, send_in", [
    (5, "pre_due", 2), (3, "pre_due", 0), (1, "due", 1), (-2, "plus_3", 1),
    (-15, "plus_20", 5), (-30, "plus_20", 0),
])
def test_next_reminder_step(due_in, step, send_in):
    found = next_step(inv(1, due=AS_OF + timedelta(days=due_in)), AS_OF)
    assert (found.name, found.send_on) == (step, AS_OF + timedelta(days=send_in))


def test_plan_has_one_execute_card_per_customer_soonest_first():
    docs = [inv(1, customer="A", due=AS_OF + timedelta(days=8), amount="700"),
            inv(2, customer="B", due=AS_OF - timedelta(days=2), amount="400"),
            inv(3, customer="B", due=AS_OF + timedelta(days=20), amount="100"),
            paid_inv(4, 0, customer="C")]
    cards = plan(docs, AS_OF, {"A": "Customer 1", "B": "Customer 2", "C": "Customer 3"}.get)
    assert [c.payload["counterparty_label"] for c in cards] == ["Customer 2", "Customer 1"]
    assert {(c.action_type, c.tier) for c in cards} == {(ActionType.send_reminder, Tier.EXECUTE)}
    b = cards[0]
    assert (b.payload["step"], b.payload["invoice_count"]) == ("plus_3", "2")
    assert b.impact.value == Decimal("500.00")
    assert b.impact.provenance.source_row_ids == ("t:INV-2", "t:INV-3")
    assert cards[1].title_key == "action.send_pre_due_reminder"
