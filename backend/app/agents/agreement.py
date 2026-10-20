"""Multi-model agreement on judgements (WP-10 milestone 6; FEATURES N9).

Numbers always come from code; *judgements* do not: which financing option, which fix, which
intent. Above the low stakes level, two other models (different from the brain where
possible: gpt-oss-120b and Qwen, falling back to gpt-oss-20b, then Gemma) are asked the same
judgement as the engine's own ranking. The agreement rate is the share of all votes for the
winning choice, and that is the confidence, not any model's own say-so.

    engine ranking  opt_a   (always the first vote: code's answer)
    groq_gpt_oss    opt_a
    groq_qwen       opt_b   -> winner opt_a, rate 2/3

The deterministic planner never votes: echoing the engine would fake agreement. With fewer
than two model votes there is no agreement report (nothing measured), and the run says so.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.agents.claims import render
from app.agents.planning import Plan
from app.agents.stakes import Stakes
from app.agents.tools import ToolResult
from app.contracts import ActionCard, AgreementReport, Unit, Vote
from app.llm import LLMRequest, LLMResponse
from app.llm.deterministic import INTENT_TOOLS
from app.llm.prompts import vote_request

VOTER_SLOTS: tuple[tuple[str, ...], ...] = (
    ("groq_gpt_oss_120b", "groq_gpt_oss_20b", "gemma"),
    ("groq_qwen", "groq_gpt_oss_20b", "gemma"),
)
MIN_MODEL_VOTES = 2
ENGINE = "engine:ranking"


@dataclass(frozen=True)
class Judgement:
    kind: str  # "financing_option" | "fix" | "intent"
    question: str
    options: tuple[dict[str, str], ...]  # {"id", "summary"}
    default: str  # code's answer: the engine's top-ranked option, or the plan's first intent
    default_by: str = ENGINE

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(o["id"] for o in self.options)


def _money(value: Decimal) -> str:
    return f"Tk {render(value, Unit.BDT)}"


def judgement_for(plan: Plan, results: Mapping[str, ToolResult],
                  cards: Sequence[ActionCard], question: str) -> Judgement | None:
    """`question` is the owner's question, anonymised: only an intent vote needs it."""
    financing = results.get("financing.match")
    options = financing.payload.get("options") or () if financing is not None else ()
    # Only a choice sized on the cash gap is one the self-loop can re-make; an amount the owner
    # named ("can I take Tk 50 lakh?") is answered by the safe-size check, not voted on.
    if len(options) >= 2 and financing.payload.get("asked") is None:
        need = financing.payload["need"]
        summaries = tuple({
            "id": o.product.id,
            "summary": (f"{o.product.name}: true annual cost "
                        f"{render(o.effective_apr, Unit.percent)}, total cost "
                        f"{_money(o.total_cost.amount)}, approval in about "
                        f"{o.speed_days} days, eligibility {o.eligibility.status.value}")}
            for o in options)
        return Judgement("financing_option",
                         f"A shop needs {_money(need.amount.amount)} for {need.tenor_days} days "
                         f"to cover a cash gap. Which option should it choose?",
                         summaries, options[0].product.id)
    fixes = [c for c in cards if c.impact is not None]
    if len(fixes) >= 2:
        summaries = tuple({
            "id": c.id,
            "summary": (f"{c.action_type.value.replace('_', ' ')}: closes "
                        f"{_money(c.impact.value)} of the gap, costs "
                        f"{_money(c.cost.value) if c.cost else 'nothing'}")}
            for c in fixes)
        return Judgement("fix", "A shop expects a cash gap. Which fix should it try first?",
                         summaries, fixes[0].id)
    if plan.intents and plan.planner != "deterministic":
        intents = tuple({"id": i, "summary": ", ".join(INTENT_TOOLS[i])} for i in INTENT_TOOLS)
        return Judgement("intent", f"Which intent matches this question best: {question}",
                         intents, plan.intents[0], default_by=f"planner:{plan.planner}")
    return None


def tally(votes: Sequence[Vote], default: str) -> tuple[str, Decimal]:
    """Winning choice (ties go to code's answer, then to the earliest vote) and its share."""
    counts = Counter(v.choice for v in votes)
    best = max(counts.values())
    leaders = [v.choice for v in votes if counts[v.choice] == best]
    winner = default if default in leaders else leaders[0]
    return winner, Decimal(counts[winner]) / Decimal(len(votes))


@dataclass(frozen=True)
class AgreementOutcome:
    report: AgreementReport | None
    judgement: Judgement | None
    note: str | None = None  # why there is no report

    @property
    def supports_code(self) -> bool:
        """Code's answer won the vote by at least the stakes' threshold."""
        return (self.report is not None and self.judgement is not None
                and self.report.winning_choice == self.judgement.default
                and self.report.passed)


def agree(call: Callable[[LLMRequest, str, Sequence[str]], LLMResponse | None],
          judgement: Judgement, stakes: Stakes, *, private: bool = False) -> AgreementOutcome:
    """Ask the voters, one model each, and measure their agreement with code's answer."""
    used: set[str] = set()
    votes = [Vote(model=judgement.default_by, choice=judgement.default,
                  rationale="code's own ranking")]
    request = vote_request(judgement.question, list(judgement.options), private=private)
    for chain in VOTER_SLOTS:  # one voter per chain: its first model that answers validly
        for slot in chain:
            if slot in used:
                continue
            reply = call(request, "vote", [slot])
            if reply is None or reply.deterministic:
                continue  # unavailable: try the chain's fallback
            used.add(slot)  # one vote per model
            choice = (reply.data or {}).get("choice")
            if choice not in judgement.ids:
                continue
            rationale = (reply.data or {}).get("rationale")
            votes.append(Vote(model=f"{reply.slot}:{reply.model}", choice=choice,
                              rationale=rationale[:300] if isinstance(rationale, str) else None))
            break
    if len(votes) - 1 < MIN_MODEL_VOTES:
        return AgreementOutcome(None, judgement, "agreement.unavailable")
    winner, rate = tally(votes, judgement.default)
    report = AgreementReport(question=judgement.question, votes=tuple(votes),
                             winning_choice=winner, agreement_rate=rate,
                             threshold=stakes.agreement_threshold, stakes=stakes.value)
    return AgreementOutcome(report, judgement)
