"""Plans: which intents, which tools, in what order, with which parameters (WP-10 milestone 3).

The brain (a model, or the deterministic planner) proposes intents and tools. Code then
repairs the proposal: unknown intents and tools are dropped, every intent gets the tools it
needs, and tools run in dependency order. Tool *parameters* are never taken from a model:
the few that come from the owner's own words (what-if shocks) are read by the rules below,
so a model cannot slip a number into an engine (CLAUDE.md rule 1).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.agents.tools import ToolRegistry
from app.llm.deterministic import INTENT_TOOLS, MAX_INTENTS, UNKNOWN, language_of

# A tool listed here runs after the tools it reads (financing is sized to the cash gap).
DEPENDS: dict[str, tuple[str, ...]] = {"financing.match": ("cash.gaps",)}
TOOL_ORDER = ("cash.forecast", "cash.gaps", "payables.upcoming", "analysis.scenarios",
              "analysis.ratios", "receivables.plan", "financing.match", "mesh.propose",
              "market.prices", "market.negotiate", "messaging.draft")
# The tool whose result answers the intent's question, stated before the context it needs
# ("how big a loan?" leads with the loan, then the cash gap it was sized on).
LEAD_TOOL = {"find_financing": "financing.match"}
# "How big / how much / how safely" a loan: size the largest loan the forecast can carry.
_LOAN_SIZE = re.compile(r"how (?:big|much|large)|max(?:imum)?|largest|biggest|safe(?:ly)?|"
                        r"afford|koto|কত|কতো|সর্বোচ্চ|নিরাপদ|多少|多大|最多|最高|安全")
LANGUAGES = ("en", "bn", "zh")
DEFAULT_SALES_SHOCK = Decimal(-20)  # a what-if with no number stresses sales by 20%

_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM = r"(\d{1,3}(?:\.\d+)?)"
_SALES = r"(?:sales|sale|revenue|বিক্রি|bikri|销售|销量|营业额)"
_COSTS = r"(?:costs?|expenses?|prices?|খরচ|দাম|khoroch|成本|费用)"
_DOWN = r"(?:drops?|fall|falls|down|decline|declines|less|lower|কমে|কম|kome|kom|下降|减少|下跌)"
_UP = r"(?:rise|rises|up|increase|increases|more|higher|বাড়ে|বেড়ে|বাড়|bare|bere|上涨|增加|上升)"
_PATTERNS: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("sales_change_pct", -1, re.compile(rf"{_SALES}\D{{0,25}}?{_DOWN}\D{{0,15}}?{_NUM}\s*%")),
    ("sales_change_pct", -1, re.compile(rf"{_SALES}\D{{0,25}}?{_NUM}\s*%\s*{_DOWN}")),
    ("sales_change_pct", 1, re.compile(rf"{_SALES}\D{{0,25}}?{_UP}\D{{0,15}}?{_NUM}\s*%")),
    ("sales_change_pct", 1, re.compile(rf"{_SALES}\D{{0,25}}?{_NUM}\s*%\s*{_UP}")),
    ("cost_change_pct", 1, re.compile(rf"{_COSTS}\D{{0,25}}?{_UP}\D{{0,15}}?{_NUM}\s*%")),
    ("cost_change_pct", 1, re.compile(rf"{_COSTS}\D{{0,25}}?{_NUM}\s*%\s*{_UP}")),
    ("cost_change_pct", -1, re.compile(rf"{_COSTS}\D{{0,25}}?{_DOWN}\D{{0,15}}?{_NUM}\s*%")),
)
_DELAY = re.compile(r"(\d{1,3})\s*(?:days?|দিন|din|天)\s*(?:late|later|দেরি|deri|晚|迟)")


@dataclass(frozen=True)
class Plan:
    intents: tuple[str, ...]
    tools: tuple[str, ...]
    language: str
    planner: str  # the slot that planned: a model, or "deterministic"
    params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    dropped: tuple[str, ...] = ()  # names the planner gave that do not exist
    notes: tuple[str, ...] = ()
    asked: str = ""  # the question as the models saw it (anonymised); "" if none saw it

    @property
    def understood(self) -> bool:
        return bool(self.tools)

    def answer_order(self) -> tuple[str, ...]:
        """Tools in the order their statements are told: the primary intent's lead first."""
        lead = LEAD_TOOL.get(self.intents[0]) if self.intents else None
        if lead not in self.tools:
            return self.tools
        return (lead, *(t for t in self.tools if t != lead))

    def subagents(self) -> list[tuple[str, tuple[str, ...]]]:
        """(intent, tools) per sub-agent; a shared tool runs once and both read the result."""
        return [(intent, tuple(t for t in self.tools if t in INTENT_TOOLS.get(intent, ())))
                for intent in self.intents if intent in INTENT_TOOLS]


def what_if_params(question: str) -> tuple[dict[str, Decimal | int], tuple[str, ...]]:
    """Shocks the owner stated, read by rules from their own words."""
    text = question.translate(_DIGITS).casefold()
    params: dict[str, Decimal | int] = {}
    for name, sign, pattern in _PATTERNS:
        if name in params:
            continue
        found = pattern.search(text)
        if found:
            params[name] = Decimal(found.group(1)) * sign
    delay = _DELAY.search(text)
    if delay:
        params["collection_delay_days"] = int(delay.group(1))
    if params:
        return params, ()
    return {"sales_change_pct": DEFAULT_SALES_SHOCK}, ("scenario.default_shock",)


def _ordered(tools: Iterable[str]) -> tuple[str, ...]:
    wanted = set(tools)
    for tool in list(wanted):
        wanted.update(DEPENDS.get(tool, ()))
    rank = {t: i for i, t in enumerate(TOOL_ORDER)}
    return tuple(sorted(wanted, key=lambda t: (rank.get(t, len(rank)), t)))


def build_plan(proposal: Mapping[str, Any] | None, question: str, registry: ToolRegistry, *,
               planner: str, language: str | None = None, asked: str = "") -> Plan:
    """Repair a planner's proposal into a runnable plan (or an empty one: not understood)."""
    proposal = proposal or {}
    raw_intents = [i for i in proposal.get("intents") or () if isinstance(i, str)]
    raw_tools = [t for t in proposal.get("tools") or () if isinstance(t, str)]
    intents = tuple(dict.fromkeys(i for i in raw_intents if i in INTENT_TOOLS))[:MAX_INTENTS]
    dropped = tuple(dict.fromkeys(
        [i for i in raw_intents if i not in INTENT_TOOLS and i != UNKNOWN]
        + [t for t in raw_tools if t not in registry]))
    tools = [t for intent in intents for t in INTENT_TOOLS[intent]]
    # A tool the planner named on its own is kept only if it serves one of the intents.
    tools += [t for t in raw_tools if t in registry and any(t in INTENT_TOOLS[i] for i in intents)]
    ordered = _ordered(tools)
    params: dict[str, dict[str, Any]] = {}
    notes: tuple[str, ...] = ()
    if "analysis.scenarios" in ordered:
        params["analysis.scenarios"], notes = what_if_params(question)
    if "financing.match" in ordered and _LOAN_SIZE.search(question.casefold()):
        params["financing.match"] = {"safe_size": True}
    proposed_language = proposal.get("language")
    lang = language or (proposed_language if proposed_language in LANGUAGES
                        else language_of(question))
    return Plan(intents=intents if ordered else (), tools=ordered, language=lang,
                planner=planner, params=params, dropped=dropped, notes=notes, asked=asked)
