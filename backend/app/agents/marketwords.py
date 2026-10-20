"""Market words in the owner's own language (copilot side of WP-09).

    commodities("চালের দাম কত?")           -> ("rice_coarse", "rice_fine")
    deal_terms("... 500 kg at Tk 60, pay in 30 days") -> {"quantity": 500, "offer": 60, ...}

Rules only, read from the owner's words, so a model can never put a number into an engine
(CLAUDE.md rule 1). Item and unit names for answers are here too, in en, bn and zh.
TCB's item keys are the WP-09 engine's (`app.engines.market.tcb.ITEMS`).
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

# commodity -> words naming it (English and Banglish whole words; Bangla whole words with case
# endings; Chinese anywhere). "rice" alone names both TCB rice grades.
WORDS: dict[str, tuple[str, ...]] = {
    "rice_coarse": ("rice", "coarse rice", "mota chal", "chal", "chaal", "চাল", "মোটা চাল",
                    "大米", "米价"),
    "rice_fine": ("rice", "fine rice", "miniket", "chikon chal", "চাল", "সরু চাল", "大米",
                  "米价"),
    "atta_loose": ("atta", "flour", "আটা", "面粉"),
    "soybean_oil": ("oil", "soybean", "soyabean", "soybean oil", "tel", "তেল", "সয়াবিন",
                    "豆油", "食用油"),
    "lentil_masur": ("lentil", "lentils", "dal", "daal", "ডাল", "মসুর", "মশুর", "扁豆"),
    "chickpea": ("chickpea", "chickpeas", "chola", "chhola", "ছোলা", "鹰嘴豆"),
    "sugar": ("sugar", "chini", "চিনি", "白糖", "糖价"),
    "onion": ("onion", "onions", "piaj", "peyaj", "পেঁয়াজ", "পিঁয়াজ", "洋葱"),
    "potato": ("potato", "potatoes", "alu", "aloo", "আলু", "土豆"),
    "egg_farm": ("egg", "eggs", "dim", "ডিম", "鸡蛋"),
    "garlic": ("garlic", "rosun", "রসুন", "大蒜"),
    "salt": ("salt", "lobon", "লবণ", "食盐"),
    "ms_rod": ("rod", "ms rod", "steel rod", "রড", "钢筋"),
}

NAMES: dict[str, tuple[str, str, str]] = {
    "rice_coarse": ("Coarse rice", "মোটা চাল", "粗米"),
    "rice_fine": ("Fine rice", "সরু চাল", "精米"),
    "atta_loose": ("Loose atta", "খোলা আটা", "散装面粉"),
    "soybean_oil": ("Loose soybean oil", "খোলা সয়াবিন তেল", "散装豆油"),
    "lentil_masur": ("Masur dal (large)", "মসুর ডাল (বড় দানা)", "小扁豆（大粒）"),
    "chickpea": ("Chickpeas", "ছোলা", "鹰嘴豆"),
    "sugar": ("Sugar", "চিনি", "白糖"),
    "onion": ("Onion (local)", "দেশি পেঁয়াজ", "本地洋葱"),
    "potato": ("Potato", "আলু", "土豆"),
    "egg_farm": ("Farm eggs", "ফার্মের ডিম", "养殖鸡蛋"),
    "garlic": ("Garlic (local)", "দেশি রসুন", "本地大蒜"),
    "salt": ("Salt", "লবণ", "食盐"),
    "ms_rod": ("MS rod", "এমএস রড", "钢筋"),
}
UNITS: dict[str, tuple[str, str, str]] = {
    "kg": ("kg", "কেজি", "公斤"), "litre": ("litre", "লিটার", "升"),
    "hali": ("hali (4 eggs)", "হালি", "四个"), "metric_ton": ("tonne", "টন", "吨"),
}
_LANG = {"en": 0, "bn": 1, "zh": 2}

_BANGLA = re.compile(r"[ঀ-৿]")
_CJK = re.compile(r"[一-鿿]")
_BN_ENDINGS = "ের|এর|গুলো|গুলোর|টা|টি|টার|টির|ে|র|ও"


def _pattern(word: str) -> re.Pattern[str]:
    word = unicodedata.normalize("NFC", word).casefold()
    if _BANGLA.search(word):
        return re.compile(rf"(?<![ঀ-৿]){re.escape(word)}(?:{_BN_ENDINGS})?(?![ঀ-৿])")
    if _CJK.search(word):
        return re.compile(re.escape(word))
    return re.compile(rf"(?<![a-z]){re.escape(word)}(?![a-z])")


_PATTERNS = {key: [_pattern(w) for w in words] for key, words in WORDS.items()}


def _text(question: str) -> str:
    return unicodedata.normalize("NFC", question).casefold()


def commodities(question: str) -> tuple[str, ...]:
    """TCB items the question names, in TCB's order."""
    text = _text(question)
    return tuple(key for key, patterns in _PATTERNS.items()
                 if any(p.search(text) for p in patterns))


def name(commodity: str, language: str) -> str:
    return NAMES.get(commodity, (commodity,) * 3)[_LANG.get(language, 0)]


def unit(unit_key: str, language: str) -> str:
    return UNITS.get(unit_key, (unit_key,) * 3)[_LANG.get(language, 0)]


# ---------------------------------------------------------------- the deal the owner describes

_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_QTY_UNITS = r"(?:kg|kgs|kilo|kilos|kilogram|kilograms|কেজি|公斤|千克|litres?|liters?|লিটার|升|" \
             r"hali|হালি|tons?|tonnes?|টন|吨|bags?|বস্তা|袋|pieces?|pcs|টি|个)"
_MONEY = r"(?:tk\.?|taka|৳|টাকা|塔卡|元|bdt)"
_QUANTITY = re.compile(rf"{_NUM}\s*{_QTY_UNITS}(?![a-z])")
_OFFER = (re.compile(rf"{_MONEY}\s*{_NUM}"), re.compile(rf"{_NUM}\s*{_MONEY}"))
_DAYS = re.compile(rf"{_NUM}\s*(?:days?|দিন|din|天)")
CASH_NOW = re.compile(r"\bcash\b|on delivery|নগদে|nagode|现金|货到付款")


def _number(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def deal_terms(question: str) -> dict[str, Decimal | int]:
    """Quantity, offer per unit and payment days the owner stated; absent ones are left out."""
    text = _text(question).translate(_DIGITS)
    terms: dict[str, Decimal | int] = {}
    quantity = _QUANTITY.search(text)
    if quantity:
        terms["quantity"] = _number(quantity.group(1))
    for pattern in _OFFER:
        offer = pattern.search(text)
        if offer:
            terms["offer"] = _number(offer.group(1))
            break
    days = _DAYS.search(text)
    if days:
        terms["payment_days"] = int(_number(days.group(1)))
    elif CASH_NOW.search(text):
        terms["payment_days"] = 0
    return terms
