"""Deterministic planner: the provider that is always available (WP-10 milestone 1; PLAN §6).

The last link of every fallback chain, and the only one in `llm_mode=deterministic`. It
answers the same four tasks as the models, in the same JSON shapes, from rules alone:

    plan      keyword intents (EN, BN, Banglish, ZH) -> {"intents", "tools", "language"};
              a greeting or "what can you do" plans to ["help"] with no tools
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
# Reminder drafts are built from the receivables plan (WP-12), so drafting reads that plan.
INTENT_TOOLS: dict[str, tuple[str, ...]] = {
    "cash_outlook": ("cash.forecast", "cash.gaps"),
    "upcoming_payments": ("payables.upcoming",),
    "collect_receivables": ("receivables.plan",),
    "find_financing": ("cash.gaps", "financing.match"),
    "business_health": ("analysis.ratios",),
    "what_if": ("analysis.scenarios",),
    "settle_debts": ("mesh.propose",),
    "market_prices": ("market.prices",),
    "negotiate": ("market.prices", "market.negotiate"),
    "draft_message": ("receivables.plan",),
}
UNKNOWN = "unknown"
HELP = "help"  # a greeting or "what can you do": answered with the copilot's own menu
MAX_INTENTS = 3

# Latin-script keywords (English and Banglish) match whole words. Bangla keywords match at
# the start of a word, because case endings attach to the stem (ঋণের = "of the loan"); short
# stems that start common unrelated words are left out (দর: দরকার "need"; ধার: ধারণা "idea"),
# or listed in BANGLA_WHOLE_WORDS, which match only as a word with a case ending (বিল, বিলের,
# বিলগুলো: "bill"; never বিলম্ব "delay"). Chinese has no spaces between words, so Chinese
# keywords match anywhere (see _CJK_NOT_AFTER for compounds).
# Ties keep the table order: an explicit what-if outranks the topic it is about, a bill or
# "who do I pay next" outranks the general cash question that comes with it, and a deal to
# negotiate outranks the price of the item in it.
KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "what_if": {
        "latin": ("what if", "what happens if", "happens if", "what would happen", "suppose",
                  "scenario", "scenarios", "stress", "jodi", "dhoren"),
        "script": ("যদি", "ধরুন", "如果", "假如", "情景"),
    },
    "upcoming_payments": {
        "latin": ("bill", "bills", "pay next", "payments due", "payment due", "due next",
                  "upcoming payment", "upcoming payments", "coming up", "payable", "payables",
                  "supplier payment", "supplier payments", "pay suppliers", "pay the supplier",
                  "owe suppliers", "owe the supplier", "i owe", "do i owe", "who do i pay",
                  "what do i pay", "dite hobe", "bill dibo"),
        "script": ("বিল", "সাপ্লায়ার", "সরবরাহকারী", "দিতে হবে", "账单", "付款", "应付", "要付"),
    },
    "cash_outlook": {
        # Paying wages and rent is a cash question too: the forecast and the gaps' drivers
        # answer "can I pay salaries on the 31st?". So is "how is today looking?".
        "latin": ("cash", "cash flow", "cashflow", "forecast", "run out", "shortfall", "gap",
                  "liquidity", "balance", "balance next", "enough money", "money left",
                  "taka thakbe", "hate taka", "ghatti", "salary", "salaries", "wage", "wages",
                  "payroll", "rent", "can i pay", "can i afford", "afford", "have to pay",
                  "need to pay", "beton", "bhara", "dite parbo", "today", "today's",
                  "summary", "attention", "aj ki", "ajker"),
        "script": ("নগদ", "ক্যাশ", "ঘাটতি", "পূর্বাভাস", "হাতে টাকা", "টাকা থাকবে",
                   "কত টাকা আছে", "টাকার টান", "বেতন", "মজুরি", "ভাড়া", "দিতে পারব",
                   "আজকের", "আজকে", "现金", "预测", "缺口", "资金", "工资", "薪水", "房租",
                   "钱够", "余额", "今天"),
    },
    "collect_receivables": {
        "latin": ("receivable", "receivables", "owe me", "owes me", "who owes", "owe us",
                  "owes us", "customers owe", "overdue", "unpaid", "outstanding", "invoice",
                  "invoices", "chase", "collect", "collection", "credit sales", "baki",
                  "paona", "aday"),
        "script": ("বাকি", "পাওনা", "আদায়", "应收", "欠款", "欠我", "催收", "催款", "收款"),
    },
    "find_financing": {
        "latin": ("loan", "loans", "financing", "finance", "borrow", "lender", "credit line",
                  "interest rate", "apr", "microfinance", "rin", "dhar", "lon"),
        "script": ("ঋণ", "লোন", "কর্জ", "贷", "融资", "借款", "利率"),
    },
    "business_health": {
        "latin": ("profit", "profits", "margin", "margins", "ratio", "ratios", "p&l",
                  "how is my business", "my business", "business doing", "doing ok",
                  "how am i doing", "performance", "revenue", "earn", "earned", "earning",
                  "labh", "lav", "business kemon", "byabsa kemon"),
        "script": ("লাভ", "মুনাফা", "লোকসান", "ব্যবসা কেমন", "ব্যবসার অবস্থা", "বিক্রি কেমন",
                   "利润", "毛利", "比率", "经营", "赚", "营收"),
    },
    "settle_debts": {
        "latin": ("netting", "net off", "net it", "net out", "offset", "settle", "circular debt",
                  "debt ring", "other shops", "we owe them", "owe each other", "katakati",
                  "mitano"),
        "script": ("কাটাকাটি", "নিষ্পত্তি", "抵消", "轧差", "清算", "三角债"),
    },
    "negotiate": {
        "latin": ("negotiate", "negotiation", "bargain", "better terms", "walk away",
                  "walk-away", "accept the offer", "accept this offer", "counter offer",
                  "dordam", "dor koshakoshi"),
        "script": ("দরদাম", "দর কষাকষি", "谈判", "砍价", "议价"),
    },
    "market_prices": {
        # Items on TCB's Dhaka list name a market question too ("how much is rice today?").
        "latin": ("price", "prices", "market rate", "wholesale", "vendor", "vendors",
                  "cheaper", "dam", "dor", "bazar", "rice", "flour", "atta", "soybean",
                  "lentil", "lentils", "chickpeas", "sugar", "onion", "onions", "potato",
                  "potatoes", "eggs", "garlic", "salt"),
        "script": ("দাম", "বাজার দর", "বাজার", "চাল", "আটা", "তেল", "ডাল", "ছোলা", "চিনি",
                   "পেঁয়াজ", "পিঁয়াজ", "আলু", "ডিম", "রসুন", "লবণ", "价格", "市场价", "批发",
                   "供应商", "大米", "面粉", "豆油", "白糖", "洋葱", "土豆", "鸡蛋", "大蒜"),
    },
    "draft_message": {
        "latin": ("draft", "write a message", "write a", "message to", "send a reminder",
                  "remind", "reminder", "reminders", "sms", "whatsapp", "message likhe",
                  "tagada"),
        "script": ("বার্তা", "মেসেজ", "লিখে দাও", "তাগাদা", "起草", "短信", "消息"),
    },
}
# Short words that start unrelated ones: বিল (bill; বিলম্ব "delay"), চাল (rice; চালান "invoice"),
# তেল (oil; তেলাপিয়া), ডাল, ডিম, আলু, আটা (আটক "detained").
BANGLA_WHOLE_WORDS = frozenset({"বিল", "চাল", "তেল", "ডাল", "ডিম", "আলু", "আটা"})
# Case endings and classifiers a whole Bangla word may carry: বিলের, বিলে, বিলটা, বিলগুলো.
_BANGLA_ENDINGS = ("গুলোর", "গুলোতে", "গুলো", "গুলির", "গুলি", "টার", "টির", "টা", "টি",
                   "ের", "এর", "ে", "র")

# Greetings and "what can you do?": only when nothing else matched, so "Hi, will I run out of
# cash?" is still a cash question.
HELP_PHRASES: dict[str, tuple[str, ...]] = {
    "latin": ("hi", "hello", "hey", "salam", "assalamualaikum", "assalamu alaikum", "help",
              "menu", "what can you do", "what do you do", "how can you help",
              "what can i ask", "how do i use", "ki korte paro", "ki korte paren"),
    "script": ("হ্যালো", "হাই", "সাহায্য", "কী করতে পার", "কি করতে পার", "আসসালামু আলাইকুম",
               "নমস্কার", "你好", "您好", "帮助", "能做什么", "怎么用"),
}

_BANGLA = re.compile(r"[ঀ-৿]")
_CJK = re.compile(r"[一-鿿]")


# Chinese has no word breaks: a keyword inside a longer word must not match. 毛利率 (gross margin)
# contains 利率 (interest rate) and is an analysis question, not a financing one (WP-16 finding).
_CJK_NOT_AFTER = {"利率": "毛"}


def _pattern(word: str) -> re.Pattern[str]:
    word = unicodedata.normalize("NFC", word)
    if word in BANGLA_WHOLE_WORDS:
        endings = "|".join(unicodedata.normalize("NFC", e) for e in _BANGLA_ENDINGS)
        return re.compile(rf"(?<![ঀ-৿]){re.escape(word)}(?:{endings})?(?![ঀ-৿])")
    if _BANGLA.search(word):
        return re.compile(rf"(?<![ঀ-৿]){re.escape(word)}")
    if _CJK.search(word):
        before = _CJK_NOT_AFTER.get(word)
        return re.compile((rf"(?<!{before})" if before else "") + re.escape(word))
    return re.compile(rf"(?<![a-z]){re.escape(word)}(?![a-z])")


_PATTERNS = {intent: [_pattern(w) for w in (*words["latin"], *words["script"])]
             for intent, words in KEYWORDS.items()}
_HELP = [_pattern(w) for w in (*HELP_PHRASES["latin"], *HELP_PHRASES["script"])]


def language_of(text: str) -> str:
    if _BANGLA.search(text):
        return "bn"
    if _CJK.search(text):
        return "zh"
    return "en"


# Words that set the scene rather than name the topic count half, so "how much is rice today?"
# is a price question and "what needs my attention today?" still a cash check-in.
WEAK_WORDS = frozenset({"today", "today's", "summary", "attention", "আজকের", "আজকে", "今天"})
_WEAK = {id(p) for intent, words in KEYWORDS.items()
         for p, w in zip(_PATTERNS[intent], (*words["latin"], *words["script"]), strict=True)
         if w in WEAK_WORDS}


def classify(question: str) -> list[str]:
    """Matched intents, strongest first (ties keep the table order); [] if none match."""
    text = unicodedata.normalize("NFC", question).casefold()
    scores: dict[str, float] = {}
    for intent, patterns in _PATTERNS.items():
        score = sum(0.5 if id(p) in _WEAK else 1 for p in patterns if p.search(text))
        if score:
            scores[intent] = score
    order = list(KEYWORDS)
    return sorted(scores, key=lambda i: (-scores[i], order.index(i)))[:MAX_INTENTS]


def is_help(question: str) -> bool:
    """A greeting or a question about the copilot itself, with no finance intent in it."""
    text = unicodedata.normalize("NFC", question).casefold()
    return not classify(question) and any(p.search(text) for p in _HELP)


def plan(question: str) -> dict[str, Any]:
    intents = classify(question)
    tools: list[str] = []
    for intent in intents:
        tools.extend(t for t in INTENT_TOOLS[intent] if t not in tools)
    fallback = HELP if is_help(question) else UNKNOWN
    return {"intents": intents or [fallback], "tools": tools, "language": language_of(question)}


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
