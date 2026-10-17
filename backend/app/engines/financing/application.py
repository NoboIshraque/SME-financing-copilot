"""Application pack draft (WP-06 milestone 7).

Turns a ranked option into an ActionCard. Submitting an application commits the business, so
the card is EXECUTE tier: the owner approves it with a step-up code. The payload carries only
facts we hold (with their values) and the list of facts the lender will ask for that we lack.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from app.contracts import ActionCard, ActionType, FinancingNeed, FinancingOption, Tier
from app.engines.financing.eligibility import missing_facts

CARD_TTL = timedelta(hours=24)


def draft_application(option: FinancingOption, need: FinancingNeed,
                      facts: Mapping[str, Decimal | None], *, now: datetime) -> ActionCard:
    product = option.product
    used = sorted({rule.metric for rule in product.rules})
    provided = {m: str(facts[m]) for m in used if facts.get(m) is not None}
    payload = {
        "product_id": product.id,
        "provider": product.provider,
        "amount": str(need.amount.amount),
        "tenor_days": need.tenor_days,
        "purpose": need.purpose_key,
        "effective_annual_rate": str(option.effective_apr),
        "rate_basis": product.rate_basis.value,
        "facts_provided": provided,
        "facts_missing": missing_facts(option.eligibility, product),
        "source_url": product.source_url,
    }
    by_label = {f.label_key: f for f in option.figures}
    return ActionCard(
        id=f"apply:{product.id}:{need.tenant_id}",
        title_key="action.draft_loan_application",
        action_type=ActionType.draft_loan_application,
        tier=Tier.EXECUTE,
        payload=payload,
        figures=option.figures,
        cost=by_label.get("financing.total_cost"),
        expires_at=now + CARD_TTL,
    )
