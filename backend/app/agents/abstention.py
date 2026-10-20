"""Required "I don't know" (WP-10 milestone 8; FEATURES N17).

Prefer abstaining to guessing (CLAUDE.md rule 5). Any package can build an abstention here:

    from app.agents.abstention import insufficient_data
    raise SomeError(insufficient_data(["at least 8 weeks of transactions"]))

An abstention says *why* (`reason`, with the web's `abstain.<reason>` message key) and names
exactly what is missing, so the owner knows what to upload or answer. After a run,
`after_checks()` decides with thresholds that rise with the stakes:

    unverifiable   no claim survived the checker, or (high stakes) any claim was rejected
    low_agreement  the voting models did not back code's answer by the stakes' threshold
    unverifiable   the decision flipped on irrelevant noise in the self-loop (N16)

Every abstention is logged (`AbstentionRow`, served by `GET /api/copilot/abstentions`) and
appended to the tenant's audit chain (WP-11): the log feeds the trust report.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agreement import AgreementOutcome
from app.agents.models import AbstentionRow
from app.agents.stakes import Stakes
from app.contracts import (
    Abstention,
    AbstentionReason,
    CheckResult,
    CheckStatus,
    StabilityReport,
    Tier,
)
from app.security.audit import AuditLog

log = logging.getLogger("app.agents.abstention")
R = AbstentionReason


def _make(reason: AbstentionReason, missing: Iterable[str] = (),
          detail: str | None = None) -> Abstention:
    return Abstention(reason=reason, missing=tuple(dict.fromkeys(missing)),
                      message_key=f"abstain.{reason.value}",
                      detail=detail[:500] if detail else None)


def insufficient_data(missing: Iterable[str], detail: str | None = None) -> Abstention:
    return _make(R.insufficient_data, missing, detail)


def out_of_scope(missing: Iterable[str] = (), detail: str | None = None) -> Abstention:
    return _make(R.out_of_scope, missing, detail)


# Market prices and negotiation were cut from this version (19 Oct): said plainly, not "won't
# guess". Any other engine that is not installed gets the general "not in this version".
CUT_TOOLS = frozenset({"market.prices", "market.negotiate"})
HELP_KEY = "copilot.help.intro"


def not_in_this_version(tools: Iterable[str], engines: Iterable[str]) -> Abstention:
    names = set(tools)
    key = "abstain.market_unavailable" if names and names <= CUT_TOOLS \
        else "abstain.engine_unavailable"
    return Abstention(reason=R.out_of_scope, missing=tuple(dict.fromkeys(engines)),
                      message_key=key, detail="engine_unavailable")


def help_menu() -> Abstention:
    """A greeting or "what can you do?": the web shows the copilot's menu for the user's role
    (i18n keys only, no numbers). Carried as an out-of-scope abstention with its own key so
    no tool runs and nothing numeric is shown; it is not logged as an abstention."""
    return Abstention(reason=R.out_of_scope, missing=(), message_key=HELP_KEY, detail="help")


def is_help(abstention: Abstention) -> bool:
    return abstention.message_key == HELP_KEY


def unverifiable(missing: Iterable[str] = (), detail: str | None = None) -> Abstention:
    return _make(R.unverifiable, missing, detail)


def low_agreement(detail: str | None = None) -> Abstention:
    return _make(R.low_agreement, (), detail)


def budget_exhausted(missing: Iterable[str]) -> Abstention:
    return _make(R.budget_exhausted, missing)


def policy(detail: str | None = None) -> Abstention:
    return _make(R.policy, (), detail)


def after_checks(stakes: Stakes, checks: Sequence[CheckResult],
                 agreement: AgreementOutcome | None,
                 stability: StabilityReport | None) -> Abstention | None:
    """The reason to withhold a composed answer, if there is one (first reason wins)."""
    verified = [c for c in checks if c.status is CheckStatus.verified]
    rejected = [c for c in checks if c.status is CheckStatus.rejected]
    if checks and not verified:
        return unverifiable(detail="no figure could be recomputed")
    if stakes is Stakes.high and rejected:
        return unverifiable(missing=[c.claim_id for c in rejected],
                            detail="a figure did not recompute; at high stakes nothing is shown")
    if agreement is not None and agreement.report is not None and not agreement.supports_code:
        report = agreement.report
        won = sum(v.choice == report.winning_choice for v in report.votes)
        return low_agreement(
            detail=f"{report.winning_choice} won {won} of {len(report.votes)} votes; "
                   f"{stakes.value} stakes need {report.threshold} for code's choice "
                   f"{agreement.judgement.default}")
    if stability is not None and stability.unreliable:
        flipped = [r.name for r in stability.results if not r.held]
        return unverifiable(detail="the decision changed on irrelevant noise: "
                            + ", ".join(flipped))
    return None


def record(db: Session, *, tenant_id: str, recommendation_id: str, question: str,
           abstention: Abstention, stakes: Stakes | None, actor: str, now: datetime) -> None:
    """Log the abstention and append it to the tenant's audit chain (ids and reasons only)."""
    db.add(AbstentionRow(tenant_id=tenant_id, recommendation_id=recommendation_id,
                         question=question, reason=abstention.reason.value,
                         message_key=abstention.message_key,
                         missing=json.dumps(list(abstention.missing), ensure_ascii=False),
                         detail=abstention.detail, stakes=stakes.value if stakes else None,
                         created_at=now))
    AuditLog(db).append(tenant_id, actor=actor, action="copilot.abstain", now=now,
                        tier=Tier.SUGGEST, target=recommendation_id,
                        details={"reason": abstention.reason.value,
                                 "missing": len(abstention.missing)})
    log.info("abstained on %s: %s", recommendation_id, abstention.reason.value)


def history(db: Session, tenant_id: str, limit: int = 100) -> list[AbstentionRow]:
    query = (select(AbstentionRow).where(AbstentionRow.tenant_id == tenant_id)
             .order_by(AbstentionRow.created_at.desc(), AbstentionRow.id.desc()).limit(limit))
    return list(db.scalars(query))


def as_contract(row: AbstentionRow) -> Abstention:
    return Abstention(reason=AbstentionReason(row.reason), missing=tuple(json.loads(row.missing)),
                      message_key=row.message_key, detail=row.detail)
