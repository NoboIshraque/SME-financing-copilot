"""Claims: every number in an answer, as a checkable statement (WP-10 milestones 3-4; N8).

The composer turns tool figures into `Claim{text, value, unit, formula_id, input_fact_ids}`,
one per number, in the owner's language (en, bn, zh). Templates hold no digits of their own,
so every digit in an answer comes from a figure, and `render()` is the one way a value
becomes text: the narration check (checker.py) compares the digits of a narrated answer with
the digits of the verified claims, exactly as rendered here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.agents.tools import ToolResult
from app.contracts import ActionCard, Claim, Figure, Unit
from app.engines.financing import cost as cost_mod
from app.engines.financing import fit as fit_mod

CENT = Decimal("0.01")
MONEY = (Unit.BDT, Unit.USD, Unit.CNY)
MAX_OPTIONS = 2  # financing options described in words (all of them are on the cards/screen)
MAX_GAPS = 2


def _grouped(integer: int) -> str:
    """South Asian grouping: 12,34,567."""
    digits = str(integer)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def render(value: Decimal, unit: Unit) -> str:
    """The value as the owner reads it (no currency word: the template adds it)."""
    if unit in MONEY:
        amount = value.quantize(CENT, rounding=ROUND_HALF_UP)
        sign = "-" if amount < 0 else ""
        whole, frac = divmod(abs(amount), 1)
        text = sign + _grouped(int(whole))
        return text if frac == 0 else f"{text}.{str(frac.quantize(CENT))[2:]}"
    if unit in (Unit.ratio, Unit.probability):
        return f"{(value * 100).quantize(CENT, rounding=ROUND_HALF_UP)}%"
    if unit is Unit.percent:
        return f"{value.quantize(CENT, rounding=ROUND_HALF_UP)}%"
    if unit in (Unit.days, Unit.count):
        return str(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return str(value)


# label -> en, bn, zh. {v} is the rendered value; {name} a product name. No digits allowed.
TEMPLATES: dict[str, tuple[str, str, str]] = {
    "cash.closing_balance": ("Cash on hand now: Tk {v}.", "এখন হাতে নগদ: {v} টাকা।",
                             "当前现金余额：{v} 塔卡。"),
    "cash.lowest_likely_balance": (
        "Likely lowest balance over the next three months: Tk {v}.",
        "আগামী তিন মাসে সম্ভাব্য সর্বনিম্ন ব্যালান্স: {v} টাকা।",
        "未来三个月最可能的最低余额：{v} 塔卡。"),
    "cash.runway_days": ("Your cash stays above the safety buffer for {v} days.",
                         "নিরাপত্তা বাফারের উপরে নগদ থাকবে {v} দিন।",
                         "现金在安全缓冲之上可维持 {v} 天。"),
    "cash.buffer_target": ("Recommended safety buffer: Tk {v}.", "প্রস্তাবিত নিরাপত্তা বাফার: {v} টাকা।",
                           "建议的安全缓冲：{v} 塔卡。"),
    "cash.no_gap": ("No cash gap is expected over the next three months: the balance stays "
                    "above the safety buffer of Tk {v}.",
                    "আগামী তিন মাসে নগদ ঘাটতির আশঙ্কা নেই: ব্যালান্স {v} টাকার নিরাপত্তা বাফারের "
                    "উপরে থাকবে।",
                    "未来三个月预计没有现金缺口：余额保持在 {v} 塔卡的安全缓冲之上。"),
    "cash.expected_shortfall": ("A cash gap is likely, with an expected shortfall of Tk {v}.",
                                "নগদ ঘাটতির সম্ভাবনা আছে, প্রত্যাশিত ঘাটতি {v} টাকা।",
                                "可能出现现金缺口，预计短缺 {v} 塔卡。"),
    "cash.lead_time_days": ("It starts in {v} days.", "এটি শুরু হবে {v} দিন পরে।",
                            "将在 {v} 天后开始。"),
    "cash.breach_probability": ("Chance that it happens: {v}.", "ঘটার সম্ভাবনা: {v}।",
                                "发生概率：{v}。"),
    "action.gap_reduced": ("The cheapest fix closes Tk {v} of the gap.",
                           "সবচেয়ে সস্তা সমাধানে ঘাটতির {v} টাকা মেটে।",
                           "最便宜的办法可弥补 {v} 塔卡的缺口。"),
    "action.cost": ("That fix costs Tk {v}.", "এই সমাধানের খরচ {v} টাকা।", "该办法的成本为 {v} 塔卡。"),
    "financing.effective_apr": ("{name}: true annual cost {v}.",
                                        "{name}: প্রকৃত বার্ষিক খরচ {v}।",
                                        "{name}：真实年化成本 {v}。"),
    "financing.total_cost": ("{name} costs Tk {v} in total for this need.",
                             "{name}: এই প্রয়োজনে মোট খরচ {v} টাকা।",
                             "{name}：此次需求总成本 {v} 塔卡。"),
    "financing.p_buffer_breach": ("With {name}, the chance of still falling below the buffer "
                                  "is {v}.",
                                  "{name} নিলেও বাফারের নিচে নামার সম্ভাবনা {v}।",
                                  "使用{name}后，仍低于缓冲的概率为 {v}。"),
    "mesh.gross_total": ("The circular debt you are part of totals Tk {v}.",
                         "আপনি যে চক্রাকার দেনায় আছেন তার মোট {v} টাকা।",
                         "您所在的三角债总额为 {v} 塔卡。"),
    "mesh.net_total": ("Netting settles it with Tk {v} of actual payments.",
                       "কাটাকাটি করলে আসল লেনদেন লাগবে {v} টাকা।",
                       "轧差后实际只需支付 {v} 塔卡。"),
    "mesh.cash_saved": ("That frees Tk {v} of cash across the group.",
                        "এতে দলের মধ্যে {v} টাকা নগদ বাঁচে।",
                        "这为整个群体节省 {v} 塔卡现金。"),
    "analysis.net_sales": ("Net sales in the review period: Tk {v}.",
                           "পর্যালোচনার সময়ে নিট বিক্রি: {v} টাকা।", "审查期内净销售额：{v} 塔卡。"),
    "analysis.gross_profit": ("Gross profit: Tk {v}.", "মোট লাভ: {v} টাকা।", "毛利：{v} 塔卡。"),
    "analysis.gross_margin": ("Gross margin: {v}.", "মোট লাভের হার: {v}।", "毛利率：{v}。"),
    "analysis.operating_expenses": ("Running costs (rent, salaries, utilities, fees): Tk {v}.",
                                    "চলতি খরচ (ভাড়া, বেতন, বিল, ফি): {v} টাকা।",
                                    "运营费用（租金、工资、水电、费用）：{v} 塔卡。"),
    "analysis.net_cash_flow": ("Net cash flow: Tk {v}.", "নিট নগদ প্রবাহ: {v} টাকা।",
                               "净现金流：{v} 塔卡。"),
    "analysis.dso": ("Customers take {v} days on average to pay credit sales.",
                     "বাকিতে বিক্রির টাকা পেতে গড়ে {v} দিন লাগে।",
                     "客户平均 {v} 天付清赊销款。"),
    "analysis.dpo": ("You take {v} days on average to pay suppliers.",
                     "সরবরাহকারীদের টাকা দিতে গড়ে {v} দিন লাগে।",
                     "您平均 {v} 天付清供应商款项。"),
    "scenario.lowest_before": ("Today's forecast: lowest likely balance Tk {v}.",
                               "এখনকার পূর্বাভাস: সম্ভাব্য সর্বনিম্ন ব্যালান্স {v} টাকা।",
                               "当前预测：最可能的最低余额 {v} 塔卡。"),
    "scenario.lowest_after": ("With the change you asked about: lowest likely balance Tk {v}.",
                              "আপনার প্রশ্নের পরিবর্তনে: সম্ভাব্য সর্বনিম্ন ব্যালান্স {v} টাকা।",
                              "按您假设的变化：最可能的最低余额 {v} 塔卡。"),
    "scenario.runway_before": ("Today the cash lasts above the buffer for {v} days.",
                               "এখন বাফারের উপরে নগদ থাকে {v} দিন।",
                               "目前现金在缓冲之上可维持 {v} 天。"),
    "scenario.runway_after": ("With the change it lasts {v} days.",
                              "পরিবর্তনের পরে থাকবে {v} দিন।", "变化后可维持 {v} 天。"),
}
_LANG = {"en": 0, "bn": 1, "zh": 2}


@dataclass(frozen=True)
class Statement:
    """A claim and the figure behind it (the checker reads the figure's provenance)."""

    claim: Claim
    figure: Figure
    names: tuple[str, ...] = ()  # entity names in the text (their digits are not figures)


def statement(template: str, figure: Figure, language: str, **names: str) -> Statement:
    text = TEMPLATES[template][_LANG.get(language, 0)].format(
        v=render(figure.value, figure.unit), **names)
    claim = Claim(id=f"claim:{template}:{figure.id}", text=text, value=figure.value,
                  unit=figure.unit, formula_id=figure.provenance.formula_id,
                  input_fact_ids=figure.provenance.input_fact_ids)
    return Statement(claim, figure, tuple(names.values()))


def _labelled(figures: Iterable[Figure], language: str,
              labels: Iterable[str]) -> list[Statement]:
    by_label = {f.label_key: f for f in figures}
    return [statement(label, by_label[label], language) for label in labels if label in by_label]


def _card(card: ActionCard, language: str) -> list[Statement]:
    out = []
    if card.impact is not None and card.impact.label_key in TEMPLATES:
        out.append(statement(card.impact.label_key, card.impact, language))
    if card.cost is not None and card.cost.label_key in TEMPLATES:
        out.append(statement(card.cost.label_key, card.cost, language))
    return out


def _forecast(result: ToolResult, language: str) -> list[Statement]:
    return _labelled(result.figures, language, ("cash.closing_balance",
                                                "cash.lowest_likely_balance", "cash.runway_days",
                                                "cash.buffer_target"))


def _gaps(result: ToolResult, language: str) -> list[Statement]:
    gaps = result.payload.get("gaps") or ()
    if not gaps:
        target = result.figure("cash.buffer_target")
        return [statement("cash.no_gap", target, language)] if target is not None else []
    out: list[Statement] = []
    for gap in gaps[:MAX_GAPS]:
        out += _labelled(gap.figures, language, ("cash.expected_shortfall", "cash.lead_time_days",
                                                 "cash.breach_probability"))
    if result.cards:
        out += _card(result.cards[0], language)
    return out


def _financing(result: ToolResult, language: str) -> list[Statement]:
    out: list[Statement] = []
    for option in (result.payload.get("options") or ())[:MAX_OPTIONS]:
        # Told apart by formula and unit, not by label (labels are the web's to rename).
        cost = [f for f in option.figures if f.provenance.formula_id == cost_mod.FORMULA_ID]
        for template, unit in (("financing.effective_apr", Unit.percent),
                               ("financing.total_cost", Unit.BDT)):
            fig = next((f for f in cost if f.unit is unit), None)
            if fig is not None:
                out.append(statement(template, fig, language, name=option.product.name))
        breach = next((f for f in option.figures
                       if f.provenance.formula_id == fit_mod.FORMULA_ID), None)
        if breach is not None and "fit.no_forecast" not in option.reason_keys:
            out.append(statement("financing.p_buffer_breach", breach, language,
                                 name=option.product.name))
    return out


def _ratios(result: ToolResult, language: str) -> list[Statement]:
    return _labelled(result.figures, language, (
        "analysis.net_sales", "analysis.gross_profit", "analysis.gross_margin",
        "analysis.operating_expenses", "analysis.net_cash_flow", "analysis.dso", "analysis.dpo"))


def _scenario(result: ToolResult, language: str) -> list[Statement]:
    before = {f.label_key: f for f in result.payload.get("before") or ()}
    after = {f.label_key: f for f in result.payload.get("after") or ()}
    out = []
    for label, key in (("cash.lowest_likely_balance", "lowest"), ("cash.runway_days", "runway")):
        if label in before and label in after:
            out.append(statement(f"scenario.{key}_before", before[label], language))
            out.append(statement(f"scenario.{key}_after", after[label], language))
    return out


def _mesh(result: ToolResult, language: str) -> list[Statement]:
    return _labelled(result.figures, language, ("mesh.gross_total", "mesh.net_total",
                                                "mesh.cash_saved"))


COMPOSERS = {
    "cash.forecast": _forecast,
    "cash.gaps": _gaps,
    "financing.match": _financing,
    "analysis.ratios": _ratios,
    "analysis.scenarios": _scenario,
    "mesh.propose": _mesh,
}


def compose(results: Mapping[str, ToolResult], order: Iterable[str],
            language: str) -> list[Statement]:
    """Statements for every result, in plan order, each figure stated once."""
    out: list[Statement] = []
    seen: set[str] = set()
    for name in order:
        result = results.get(name)
        composer = COMPOSERS.get(name)
        if result is None or composer is None:
            continue
        for item in composer(result, language):
            if item.claim.id not in seen:
                seen.add(item.claim.id)
                out.append(item)
    return out
