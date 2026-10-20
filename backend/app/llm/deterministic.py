"""Deterministic planner: the provider that is always available (WP-10 milestone 1; PLAN §6).

The last link of every fallback chain, and the only one in `llm_mode=deterministic`. It
answers the same four tasks as the models, in the same JSON shapes, from rules alone:

    plan      keyword intents (EN, BN, Banglish, ZH) -> {"intents", "tools", "language"}
    vote      the engine's own top-ranked option     -> {"choice", "rationale"}
    critique  the most severe code-detected risk     -> {"objection", "severity"}
    narrate   the verified claims, joined            -> {"text"}

It never invents a number: narration only repeats claim texts that the checker verified.
Free-form chat has no rule-based answer (`Task.chat` raises `Unsupported`).
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from app.llm.messages import LLMRequest, Task


class Unsupported(RuntimeError):
    """The rules have no answer for this task."""


# Intent -> tools the orchestrator runs for it. Tool names are the registry's (milestone 2).
INTENT_TOOLS: dict[str, tuple[str, ...]] = {
    "cash_outlook": ("cash.forecast", "cash.gaps"),
    "collect_receivables": ("receivables.plan",),
    "find_financing": ("cash.gaps", "financing.match"),
    "business_health": ("analysis.ratios",),
    "what_if": ("analysis.scenarios",),
    "settle_debts": ("mesh.propose",),
    "market_prices": ("market.prices",),
    "negotiate": ("market.prices", "market.negotiate"),
    "draft_message": ("messaging.draft",),
}
UNKNOWN = "unknown"
MAX_INTENTS = 3

# Latin-script keywords (English and Banglish) match whole words. Bangla keywords match at
# the start of a word, because case endings attach to the stem (ঋণের = "of the loan"); short
# stems that start common unrelated words are left out (দর: দরকার "need"; ধার: ধারণা "idea").
# Chinese has no spaces between words, so Chinese keywords match anywhere.
KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "cash_outlook": {
        # Paying what is due (wages, rent, bills, suppliers) is a cash question too: the forecast
        # and the gaps' drivers answer "can I pay salaries on the 31st?" and "who do I pay next?".
        "latin": ("cash", "cash flow", "cashflow", "forecast", "run out", "shortfall", "gap",
                  "liquidity", "balance next", "taka thakbe", "hate taka", "ghatti",
                  "salary", "salaries", "wage", "wages", "payroll", "rent", "bill", "bills",
                  "can i pay", "can i afford", "afford", "have to pay", "need to pay",
                  "pay next", "payments due", "due next", "upcoming payments", "beton",
                  "bhara", "dite parbo"),
        "script": ("নগদ", "ক্যাশ", "ঘাটতি", "পূর্বাভাস", "হাতে টাকা", "টাকা থাকবে",
                   "বেতন", "মজুরি", "ভাড়া", "দিতে পারব",
                   "现金", "预测", "缺口", "资金", "工资", "薪水", "房租", "账单", "付款"),
    },
    "collect_receivables": {
        "latin": ("receivable", "receivables", "owe me", "owes me", "overdue", "unpaid",
                  "collect", "collection", "baki", "paona", "aday"),
        "script": ("বাকি", "পাওনা", "আদায়", "应收", "欠款", "催收", "收款"),
    },
    "find_financing": {
        "latin": ("loan", "loans", "financing", "finance", "borrow", "lender", "credit line",
                  "interest rate", "apr", "microfinance", "rin", "dhar", "lon"),
        "script": ("ঋণ", "লোন", "কর্জ", "贷款", "融资", "借款", "利率"),
    },
    "business_health": {
        "latin": ("profit", "profits", "margin", "margins", "ratio", "ratios", "p&l",
                  "how is my business", "performance", "labh", "lav", "business kemon",
                  "byabsa kemon"),
        "script": ("লাভ", "মুনাফা", "লোকসান", "ব্যবসা কেমন", "利润", "毛利", "比率", "经营"),
    },
    "what_if": {
        "latin": ("what if", "suppose", "scenario", "scenarios", "stress", "jodi", "dhoren"),
        "script": ("যদি", "ধরুন", "如果", "假如", "情景"),
    },
    "settle_debts": {
        "latin": ("netting", "net off", "offset", "settle", "circular debt", "debt ring",
                  "katakati", "mitano"),
        "script": ("কাটাকাটি", "নিষ্পত্তি", "抵消", "轧差", "清算", "三角债"),
    },
    "market_prices": {
        "latin": ("price", "prices", "market rate", "wholesale", "vendor", "vendors",
                  "cheaper", "dam", "dor", "bazar"),
        "script": ("দাম", "বাজার দর", "বাজার", "价格", "市场价", "批发", "供应商"),
    },
    "negotiate": {
        "latin": ("negotiate", "negotiation", "bargain", "better terms", "dordam",
                  "dor koshakoshi"),
        "script": ("দরদাম", "দর কষাকষি", "谈判", "砍价", "议价"),
    },
    "draft_message": {
        "latin": ("draft", "write a message", "message to", "send a reminder", "remind",
                  "sms", "whatsapp", "message likhe"),
        "script": ("বার্তা", "মেসেজ", "লিখে দাও", "起草", "短信", "消息"),
    },
}

_BANGLA = re.compile(r"[ঀ-৿]")
_CJK = re.compile(r"[一-鿿]")


# Chinese has no word breaks: a keyword inside a longer word must not match. 毛利率 (gross margin)
# contains 利率 (interest rate) and is an analysis question, not a financing one (WP-16 finding).
_CJK_NOT_AFTER = {"利率": "毛"}


def _pattern(word: str) -> re.Pattern[str]:
    if _BANGLA.search(word):
        return re.compile(rf"(?<![ঀ-৿]){re.escape(word)}")
    if _CJK.search(word):
        before = _CJK_NOT_AFTER.get(word)
        return re.compile((rf"(?<!{before})" if before else "") + re.escape(word))
    return re.compile(rf"(?<![a-z]){re.escape(word)}(?![a-z])")


_PATTERNS = {intent: [_pattern(w) for w in (*words["latin"], *words["script"])]
             for intent, words in KEYWORDS.items()}


def language_of(text: str) -> str:
    if _BANGLA.search(text):
        return "bn"
    if _CJK.search(text):
        return "zh"
    return "en"


def classify(question: str) -> list[str]:
    """Matched intents, strongest first (ties keep the table order); [] if none match."""
    text = unicodedata.normalize("NFC", question).casefold()
    scores: dict[str, int] = {}
    for intent, patterns in _PATTERNS.items():
        score = sum(1 for pattern in patterns if pattern.search(text))
        if score:
            scores[intent] = score
    order = list(KEYWORDS)
    return sorted(scores, key=lambda i: (-scores[i], order.index(i)))[:MAX_INTENTS]


def plan(question: str) -> dict[str, Any]:
    intents = classify(question)
    tools: list[str] = []
    for intent in intents:
        tools.extend(t for t in INTENT_TOOLS[intent] if t not in tools)
    return {"intents": intents or [UNKNOWN], "tools": tools, "language": language_of(question)}


def vote(context: dict[str, Any]) -> dict[str, Any]:
    options = list(context.get("options") or ())
    if not options:
        raise Unsupported("a vote needs options")
    default = context.get("default")
    choice = default if default in options else options[0]
    return {"choice": choice, "rationale": "rules: the engine's top-ranked option"}


_SEVERITY = {"high": 3, "medium": 2, "low": 1}


def critique(context: dict[str, Any]) -> dict[str, Any]:
    risks = [r for r in context.get("risks") or () if r.get("text")]
    if not risks:
        return {"objection": None, "severity": None}
    worst = max(risks, key=lambda r: _SEVERITY.get(r.get("severity", "low"), 0))
    return {"objection": worst["text"], "severity": worst.get("severity", "low")}


def narrate(context: dict[str, Any]) -> dict[str, Any]:
    texts = [c["text"] for c in context.get("claims") or () if c.get("text")]
    if not texts:
        raise Unsupported("nothing verified to narrate")
    return {"text": " ".join(texts)}


_HANDLERS: dict[Task, Callable[[LLMRequest], dict[str, Any]]] = {
    Task.plan: lambda r: plan(str(r.context.get("question", ""))),
    Task.vote: lambda r: vote(r.context),
    Task.critique: lambda r: critique(r.context),
    Task.narrate: lambda r: narrate(r.context),
}


def answer(request: LLMRequest) -> str:
    """The rule-based answer as the JSON text a model would return."""
    handler = _HANDLERS.get(request.task)
    if handler is None:
        raise Unsupported(f"no rule-based answer for {request.task.value}")
    return json.dumps(handler(request), ensure_ascii=False, sort_keys=True)
