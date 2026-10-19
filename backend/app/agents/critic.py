"""The critic: the case against every material recommendation (WP-10 milestone 5; N11).

A model from a *different family* than the brain that wrote the answer argues against it,
from the verified claims and the risks code found (`risks()`). Self-reflection does not
correct a model reliably (Huang et al., ICLR 2024), so the critic is another model with the
data, and the code-found risks are always there to fall back on. Its strongest objection is
attached to the recommendation for the owner to read.

The objection is shown to the owner, so it obeys the narration rule: a number in it must be
one a verified claim states, otherwise the rules' strongest risk is shown instead.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.agents.checker import unverified_numbers
from app.agents.claims import Statement
from app.agents.tools import ToolResult
from app.contracts import ActionCard, ActionType, DataMode, EligibilityStatus
from app.llm import LLMRequest, LLMResponse
from app.llm.prompts import critique_request

SEVERITIES = ("low", "medium", "high")
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
MAX_OBJECTION = 400
STILL_BREACH = Decimal("0.2")
UNLIKELY_GAP = Decimal("0.5")
SHORT_HISTORY_DAYS = 182

# code -> (severity, en, bn, zh). No digits: a risk never states a number of its own.
RISKS: dict[str, tuple[str, str, str, str]] = {
    "eligibility_unknown": (
        "high", "We could not confirm that you qualify for {name}: the lender will ask for "
        "facts Hishab does not hold.",
        "{name} পাওয়ার যোগ্যতা নিশ্চিত করা যায়নি: ঋণদাতা এমন তথ্য চাইবে যা হিসাবে নেই।",
        "无法确认您符合{name}的条件：贷方会要求 Hishab 没有的资料。"),
    "loan_too_slow": (
        "high", "{name} may not be approved before the cash gap starts.",
        "নগদ ঘাটতি শুরুর আগে {name} অনুমোদন নাও হতে পারে।",
        "{name}可能无法在现金缺口出现前获批。"),
    "still_breach": (
        "medium", "Even with {name}, the balance may still fall below the safety buffer.",
        "{name} নিলেও ব্যালান্স নিরাপত্তা বাফারের নিচে নামতে পারে।",
        "即使使用{name}，余额仍可能低于安全缓冲。"),
    "gap_uncertain": (
        "medium", "The gap is less likely than not; acting early has a cost if it never comes.",
        "ঘাটতি হওয়ার সম্ভাবনা অর্ধেকেরও কম; আগে ব্যবস্থা নিলে খরচ হতে পারে যদি তা না আসে।",
        "缺口发生的可能性不到一半；若缺口未出现，提前行动会有成本。"),
    "advance_strains": (
        "low", "Asking a customer to pay early can strain the relationship and may be refused.",
        "গ্রাহককে আগে টাকা দিতে বললে সম্পর্কে চাপ পড়তে পারে, আর তিনি রাজি নাও হতে পারেন।",
        "要求客户提前付款可能影响关系，也可能被拒绝。"),
    "netting_consent": (
        "medium", "Netting needs every firm in the ring to agree before the round expires.",
        "কাটাকাটি করতে চক্রের প্রতিটি প্রতিষ্ঠানের সময়মতো সম্মতি লাগবে।",
        "轧差需要链条中每家企业在本轮到期前同意。"),
    "short_history": (
        "medium", "The forecast rests on less than six months of history.",
        "পূর্বাভাসটি ছয় মাসের কম সময়ের তথ্যের উপর ভিত্তি করে।",
        "该预测所依据的历史数据不足六个月。"),
    "no_track_record": (
        "low", "The lender has no track record with Hishab users yet.",
        "এই ঋণদাতার সাথে হিসাব ব্যবহারকারীদের এখনও কোনো অভিজ্ঞতা নেই।",
        "该贷方在 Hishab 用户中尚无记录。"),
    "synthetic": (
        "low", "These figures come from synthetic demo data, not real books.",
        "এই সংখ্যাগুলো ডেমোর কৃত্রিম তথ্য থেকে, আসল হিসাব থেকে নয়।",
        "这些数字来自合成演示数据，而非真实账簿。"),
    "general": (
        "low", "Check these figures against your own records before acting.",
        "ব্যবস্থা নেওয়ার আগে নিজের হিসাবের সাথে সংখ্যাগুলো মিলিয়ে নিন।",
        "行动前请将这些数字与您自己的账目核对。"),
}
_LANG = {"en": 1, "bn": 2, "zh": 3}


@dataclass(frozen=True)
class Risk:
    code: str
    severity: str
    text: str

    def as_context(self) -> dict[str, str]:
        return {"text": self.text, "severity": self.severity}


@dataclass(frozen=True)
class Objection:
    text: str
    severity: str
    source: str  # the slot that argued it, or "rules"
    family: str  # the critic's model family ("rules" for code-found risks)


def risk(code: str, language: str, **names: str) -> Risk:
    entry = RISKS[code]
    return Risk(code, entry[0], entry[_LANG.get(language, 1)].format(**names))


def risks(results: Mapping[str, ToolResult], cards: Sequence[ActionCard], language: str, *,
          history_days: int, data_mode: DataMode) -> list[Risk]:
    """What code can see that could make the recommendation wrong, most severe first."""
    found: list[Risk] = []
    gaps = results.get("cash.gaps")
    first_gap = (gaps.payload.get("gaps") or (None,))[0] if gaps is not None else None
    financing = results.get("financing.match")
    options = financing.payload.get("options") or () if financing is not None else ()
    if options:
        top = options[0]
        name = top.product.name
        if top.eligibility.status is EligibilityStatus.not_on_record:
            found.append(risk("eligibility_unknown", language, name=name))
        if first_gap is not None and top.speed_days > first_gap.lead_time_days:
            found.append(risk("loan_too_slow", language, name=name))
        if "fit.no_forecast" not in top.reason_keys and top.p_buffer_breach >= STILL_BREACH:
            found.append(risk("still_breach", language, name=name))
        if "lender.no_track_record" in top.reason_keys:
            found.append(risk("no_track_record", language))
    if first_gap is not None and first_gap.probability < UNLIKELY_GAP and cards:
        found.append(risk("gap_uncertain", language))
    actions = {c.action_type for c in cards}
    if ActionType.propose_netting_round in actions:
        found.append(risk("netting_consent", language))
    if ActionType.request_advance in actions:
        found.append(risk("advance_strains", language))
    if (gaps is not None or "cash.forecast" in results) and history_days < SHORT_HISTORY_DAYS:
        found.append(risk("short_history", language))
    if data_mode is DataMode.synthetic:
        found.append(risk("synthetic", language))
    if not found:
        found.append(risk("general", language))
    return sorted(found, key=lambda r: -_RANK[r.severity])


def strongest(found: Sequence[Risk]) -> Objection:
    worst = found[0]
    return Objection(worst.text, worst.severity, "rules", "rules")


def critique(call: Callable[[LLMRequest, str], LLMResponse], answer: str,
             statements: Sequence[Statement], found: Sequence[Risk], *, language: str,
             brain_families: Sequence[str], private: bool = False) -> Objection:
    """The strongest objection: a model of a family that took no part in the answer, else
    the worst code-found risk."""
    exclude = tuple(sorted({f for f in brain_families if f != "rules"}))
    request = critique_request(answer, [s.claim.text for s in statements],
                               [r.as_context() for r in found], language=language,
                               exclude_families=exclude, private=private)
    reply = call(request, "critique")
    data = reply.data or {}
    text, severity = data.get("objection"), data.get("severity")
    usable = (not reply.deterministic and isinstance(text, str) and text.strip()
              and len(text) <= MAX_OBJECTION and severity in SEVERITIES
              and reply.family not in exclude
              and not unverified_numbers(text, statements))
    if usable:
        return Objection(text.strip(), severity, reply.slot, reply.family)
    return strongest(found)
