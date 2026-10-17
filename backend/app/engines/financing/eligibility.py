"""Eligibility with reasons (WP-06 milestone 3).

Each published rule becomes pass / fail / not_on_record. A missing fact is never treated as a
pass: we say exactly which fact is not on record instead of guessing.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from app.contracts import (
    Eligibility,
    EligibilityReason,
    EligibilityRule,
    EligibilityStatus,
    FinancingProduct,
    Money,
    RuleOp,
)

PASS, FAIL, MISSING = (
    EligibilityStatus.pass_,
    EligibilityStatus.fail,
    EligibilityStatus.not_on_record,
)


def check_rule(rule: EligibilityRule, facts: Mapping[str, Decimal | None]) -> EligibilityReason:
    value = facts.get(rule.metric)
    if value is None:
        return EligibilityReason(rule_id=rule.id, status=MISSING,
                                 message_key=f"{rule.description_key}.not_on_record")
    if rule.op is RuleOp.exists:
        ok = value != 0
    elif rule.op is RuleOp.gte:
        ok = value >= rule.threshold
    elif rule.op is RuleOp.lte:
        ok = value <= rule.threshold
    else:
        ok = value == rule.threshold
    return EligibilityReason(rule_id=rule.id, status=PASS if ok else FAIL, observed_value=value,
                             message_key=rule.description_key)


def _limit_reasons(product: FinancingProduct, amount: Money, tenor_days: int):
    if product.min_amount is not None and amount < product.min_amount:
        yield EligibilityReason(rule_id="limit.amount_min", status=FAIL,
                                observed_value=amount.amount, message_key="rule.amount_below_min")
    if product.max_amount is not None and amount > product.max_amount:
        yield EligibilityReason(rule_id="limit.amount_max", status=FAIL,
                                observed_value=amount.amount, message_key="rule.amount_above_max")
    if product.min_tenor_days is not None and tenor_days < product.min_tenor_days:
        yield EligibilityReason(rule_id="limit.tenor_min", status=FAIL,
                                observed_value=Decimal(tenor_days),
                                message_key="rule.tenor_below_min")
    if product.max_tenor_days is not None and tenor_days > product.max_tenor_days:
        yield EligibilityReason(rule_id="limit.tenor_max", status=FAIL,
                                observed_value=Decimal(tenor_days),
                                message_key="rule.tenor_above_max")


def evaluate(
    product: FinancingProduct,
    facts: Mapping[str, Decimal | None],
    amount: Money,
    tenor_days: int,
) -> Eligibility:
    reasons = [check_rule(rule, facts) for rule in product.rules]
    reasons += list(_limit_reasons(product, amount, tenor_days))
    statuses = {r.status for r in reasons}
    if FAIL in statuses:
        overall = FAIL
    elif MISSING in statuses:
        overall = MISSING
    else:
        overall = PASS
    return Eligibility(product_id=product.id, status=overall, reasons=tuple(reasons))


def missing_facts(eligibility: Eligibility, product: FinancingProduct) -> list[str]:
    """Metric names the owner could add to move `not_on_record` to a decision."""
    by_id = {rule.id: rule.metric for rule in product.rules}
    return [by_id[r.rule_id] for r in eligibility.reasons
            if r.status is MISSING and r.rule_id in by_id]
