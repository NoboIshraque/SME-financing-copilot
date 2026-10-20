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
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.agents import marketwords
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
    # Session A: upcoming payments, money owed, safe loan size. {what}/{who}/{when} are names
    # (a supplier label, a date): their digits are not figures.
    "copilot.payables_count": ("Payments falling due over the coming month: {v}.",
                               "সামনের মাসখানেকে যত পেমেন্ট দিতে হবে: {v}টি।",
                               "未来几周内到期的款项：{v} 笔。"),
    "copilot.payables_total": ("Together they come to Tk {v}.", "সব মিলিয়ে {v} টাকা।",
                               "合计 {v} 塔卡。"),
    "copilot.payable_item": ("{what}: Tk {v}, due {when}.", "{what}: {v} টাকা, দিতে হবে {when}।",
                             "{what}：{v} 塔卡，{when}到期。"),
    "copilot.payable_overdue": ("{what}: Tk {v}, overdue since {when}.",
                                "{what}: {v} টাকা, {when} থেকে বকেয়া।",
                                "{what}：{v} 塔卡，自{when}起逾期。"),
    "copilot.receivables_open": ("Customers owe you Tk {v} in total.",
                                 "কাস্টমারদের কাছে মোট পাওনা {v} টাকা।", "客户共欠您 {v} 塔卡。"),
    "copilot.receivables_overdue": ("Of that, Tk {v} is past its due date.",
                                    "এর মধ্যে {v} টাকার তারিখ পেরিয়ে গেছে।", "其中 {v} 塔卡已逾期。"),
    "copilot.chase_first": ("Chase {who} first: Tk {v} open, oldest due {when}.",
                            "আগে {who}-এর কাছে তাগাদা দিন: {v} টাকা বাকি, পুরোনোটা {when} তারিখের।",
                            "先催{who}：未付 {v} 塔卡，最早{when}到期。"),
    "copilot.chase_next": ("Then {who}: Tk {v}, oldest due {when}.",
                           "তারপর {who}: {v} টাকা, পুরোনোটা {when} তারিখের।",
                           "然后是{who}：{v} 塔卡，最早{when}到期。"),
    "copilot.safe_loan": ("The largest loan you can safely repay over the next three months is "
                          "Tk {v}, with {name}: its repayments keep even the cautious forecast "
                          "above your safety buffer.",
                          "আগামী তিন মাসে নিরাপদে শোধ করা যায় এমন সবচেয়ে বড় ঋণ {v} টাকা, {name}: "
                          "এর কিস্তি দিলেও সতর্ক পূর্বাভাসে ব্যালান্স নিরাপত্তা বাফারের উপরে থাকে।",
                          "未来三个月内可安全偿还的最大贷款为 {v} 塔卡（{name}）：即使按保守预测，"
                          "还款后余额仍高于安全缓冲。"),
    "copilot.safe_loan_alt": ("With {name}: up to Tk {v}.", "{name} নিলে: সর্বোচ্চ {v} টাকা।",
                              "选择{name}：最多 {v} 塔卡。"),
    "copilot.no_safe_loan_gap": ("No new loan is safe to repay right now: the forecast already "
                                 "falls short of your safety buffer, by Tk {v} expected. Close "
                                 "that gap first.",
                                 "এখন নতুন ঋণ নিরাপদে শোধ করা যাবে না: পূর্বাভাসে আগেই "
                                 "নিরাপত্তা বাফারের চেয়ে প্রত্যাশিত {v} টাকা কম পড়ছে। আগে "
                                 "ঘাটতিটা মেটান।",
                                 "目前任何新贷款都无法安全偿还：预测余额已低于安全缓冲，预计短缺 "
                                 "{v} 塔卡。请先弥补这个缺口。"),
    "copilot.no_safe_loan": ("No loan size keeps the cautious forecast above your safety buffer "
                             "of Tk {v} while you repay it.",
                             "কোনো অঙ্কের ঋণেই কিস্তি দিতে গিয়ে সতর্ক পূর্বাভাস {v} টাকার "
                             "নিরাপত্তা বাফারের উপরে থাকে না।",
                             "任何金额的贷款在还款期间都无法让保守预测保持在 {v} 塔卡的安全缓冲"
                             "之上。"),
    # WP-09 market, read from TCB's published Dhaka lists. {item}/{unit}/{when} are names.
    "copilot.market_price": ("{item}: Tk {v} per {unit} in Dhaka (TCB list of {when}).",
                             "{item}: প্রতি {unit} {v} টাকা, ঢাকা (টিসিবির {when} তারিখের তালিকা)।",
                             "{item}：每{unit} {v} 塔卡，达卡（TCB {when}价格表）。"),
    "market.change_vs_median": ("Against its median of the past four weeks: {v}.",
                                "গত চার সপ্তাহের মধ্যমা দামের তুলনায়: {v}।",
                                "与过去四周的中位价相比：{v}。"),
    "market.change_vs_previous": ("Against the list before: {v}.", "আগের তালিকার তুলনায়: {v}।",
                                  "与上一份价格表相比：{v}。"),
    "negotiation.offer_low": ("The offer is below your walk-away price of Tk {v} per {unit}: "
                              "do not accept it as it stands.",
                              "প্রস্তাবটি আপনার সর্বনিম্ন গ্রহণযোগ্য দাম প্রতি {unit} {v} টাকার নিচে: "
                              "এভাবে মেনে নেবেন না।",
                              "该报价低于您的底价每{unit} {v} 塔卡：不要照此接受。"),
    "negotiation.offer_ok": ("The offer clears your walk-away price of Tk {v} per {unit}: you "
                             "can accept it, but ask for more first.",
                             "প্রস্তাবটি আপনার সর্বনিম্ন গ্রহণযোগ্য দাম প্রতি {unit} {v} টাকার উপরে: "
                             "মেনে নিতে পারেন, তবে আগে বেশি চেয়ে দেখুন।",
                             "该报价高于您的底价每{unit} {v} 塔卡：可以接受，但先争取更高价格。"),
    "negotiation.open": ("Open by asking Tk {v} per {unit}.", "শুরুতে প্রতি {unit} {v} টাকা চান।",
                         "开价每{unit} {v} 塔卡。"),
    "negotiation.target_price": ("Aim to settle at Tk {v} per {unit}.",
                                 "প্রতি {unit} {v} টাকায় রফা করার চেষ্টা করুন।",
                                 "争取以每{unit} {v} 塔卡成交。"),
    "negotiation.credit_cost": ("Waiting for the payment costs you Tk {v} per {unit} in "
                                "interest.",
                                "টাকা পরে পাওয়ায় আপনার সুদের খরচ প্রতি {unit} {v} টাকা।",
                                "延期收款让您每{unit}承担 {v} 塔卡利息成本。"),
    "negotiation.discount": ("Or offer {v} off for payment on delivery: it costs you less than "
                             "borrowing.",
                             "অথবা হাতে হাতে টাকা দিলে {v} ছাড় দিন: এতে ঋণের চেয়ে খরচ কম।",
                             "或者货到付款给 {v} 折扣：比借钱更便宜。"),
}
_LANG = {"en": 0, "bn": 1, "zh": 2}

# Names the ledger composers put into claims, per language (en, bn, zh).
WHO: dict[str, tuple[str, str, str]] = {"Supplier": ("Supplier", "সরবরাহকারী", "供应商"),
                                        "Customer": ("Customer", "কাস্টমার", "客户")}
PAYMENT_KIND: dict[str, tuple[str, str, str]] = {
    "bill": ("{who} bill", "{who}-এর বিল", "{who}的账单"),
    "rent": ("Rent", "দোকান ভাড়া", "房租"),
    "salary": ("Salaries", "বেতন", "工资"),
    "emi": ("Loan instalment", "ঋণের কিস্তি", "贷款分期"),
    "utility": ("Utility bills", "বিদ্যুৎ-পানি-গ্যাস বিল", "水电费"),
    "tax": ("Tax", "কর", "税款"),
    "subscription": ("Subscription", "সাবস্ক্রিপশন", "订阅费"),
    "other": ("Regular payment", "নিয়মিত পেমেন্ট", "定期付款"),
}
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTHS_BN = ("জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট",
              "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর")
_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def day_text(day: date, language: str) -> str:
    if language == "bn":
        return f"{str(day.day).translate(_BN_DIGITS)} {_MONTHS_BN[day.month - 1]}"
    if language == "zh":
        return f"{day.month}月{day.day}日"
    return f"{day.day} {_MONTHS_EN[day.month - 1]}"


def party(label: str, language: str) -> str:
    """"Supplier 3" -> "সরবরাহকারী 3" (the number is the tenant's stable label, not a figure)."""
    word, _, number = label.partition(" ")
    names = WHO.get(word)
    return f"{names[_LANG.get(language, 0)]} {number}" if names else label


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


def _safe_loans(result: ToolResult, language: str,
                gaps: ToolResult | None) -> list[Statement]:
    """The safe loan size first (what "how big a loan?" asks), or why there is none."""
    safe = result.payload.get("safe") or ()
    if safe:
        (size, figure), *others = safe
        out = [statement("copilot.safe_loan", figure, language, name=size.product.name)]
        out += [statement("copilot.safe_loan_alt", fig, language, name=other.product.name)
                for other, fig in others[:MAX_OPTIONS - 1]]
        return out
    if not result.payload.get("sized") or gaps is None:
        return []
    found = gaps.payload.get("gaps") or ()
    if found:
        short = next((f for f in found[0].figures if f.label_key == "cash.expected_shortfall"),
                     None)
        return [statement("copilot.no_safe_loan_gap", short, language)] if short else []
    target = gaps.figure("cash.buffer_target")
    return [statement("copilot.no_safe_loan", target, language)] if target else []


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


def _payables(result: ToolResult, language: str) -> list[Statement]:
    lang = _LANG.get(language, 0)
    count, total = result.figure("copilot.payables_count"), result.figure("copilot.payables_total")
    out = [statement("copilot.payables_count", count, language)] if count else []
    if total is not None and total.value > 0:
        out.append(statement("copilot.payables_total", total, language))
    by_ref = {f.provenance.parameters.get("ref"): f for f in result.figures
              if f.label_key == "copilot.payable_item"}
    suppliers = result.payload.get("suppliers") or {}
    for item in result.payload.get("due") or ():
        figure = by_ref.get(item.ref)
        if figure is None:
            continue
        who = party(suppliers.get(item.counterparty_token, "Supplier"), language)
        what = PAYMENT_KIND.get(item.kind, PAYMENT_KIND["other"])[lang].format(who=who)
        template = "copilot.payable_overdue" if item.overdue else "copilot.payable_item"
        out.append(statement(template, figure, language, what=what,
                             when=day_text(item.day, language)))
    return out


def _receivables(result: ToolResult, language: str) -> list[Statement]:
    out = _labelled(result.figures, language, ("copilot.receivables_open",))
    overdue = result.figure("copilot.receivables_overdue")
    if overdue is not None and overdue.value > 0:
        out.append(statement("copilot.receivables_overdue", overdue, language))
    owed = result.payload.get("owed")
    labels = result.payload.get("customers") or {}
    by_token = {f.provenance.parameters.get("token"): f for f in result.figures
                if f.label_key == "copilot.customer_owes"}
    for i, customer in enumerate(owed.customers if owed is not None else ()):
        figure = by_token.get(customer.token)
        if figure is None:
            continue
        out.append(statement("copilot.chase_first" if i == 0 else "copilot.chase_next", figure,
                             language, who=party(labels.get(customer.token, "Customer"), language),
                             when=day_text(customer.oldest_due, language)))
    return out


def _market(result: ToolResult, language: str) -> list[Statement]:
    out: list[Statement] = []
    by_id = {f.id: f for f in result.figures}
    for row in result.payload.get("rows") or ():
        point = row.latest.point
        names = {"item": marketwords.name(point.commodity, language),
                 "unit": marketwords.unit(point.unit, language)}
        price = by_id.get(f"market:{point.commodity}:price:{point.observed_on.isoformat()}")
        if price is not None:
            out.append(statement("copilot.market_price", price, language, **names,
                                 when=day_text(row.latest.published_on, language)))
        # Matched by what it was computed from: WP-09 owns the change figure's id format.
        change = next((f for f in result.figures if f.unit is Unit.percent
                       and f.provenance.source_row_ids[:1] == (row.latest.ref,)), None)
        if change is not None and change.label_key in TEMPLATES:
            out.append(statement(change.label_key, change, language))
    return out


def _negotiation(result: ToolResult, language: str) -> list[Statement]:
    plan, row = result.payload.get("plan"), result.payload.get("row")
    if plan is None or row is None:
        return []
    unit = marketwords.unit(row.latest.point.unit, language)
    offer = Decimal(plan.walk_away.provenance.parameters["offer"])
    verdict = "negotiation.offer_ok" if offer >= plan.walk_away.value else "negotiation.offer_low"
    out = [statement(verdict, plan.walk_away, language, unit=unit)]
    by_formula = {f.provenance.formula_id: f for step in plan.steps for f in step.figures}
    for formula in ("negotiation.open", "negotiation.target_price", "negotiation.credit_cost",
                    "negotiation.discount"):
        figure = by_formula.get(formula)
        if figure is not None:
            out.append(statement(formula, figure, language, unit=unit))
    return out


def _mesh(result: ToolResult, language: str) -> list[Statement]:
    return _labelled(result.figures, language, ("mesh.gross_total", "mesh.net_total",
                                                "mesh.cash_saved"))


COMPOSERS = {
    "market.prices": _market,
    "market.negotiate": _negotiation,
    "payables.upcoming": _payables,
    "receivables.plan": _receivables,
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
        items = composer(result, language)
        if name == "financing.match":
            items = _safe_loans(result, language, results.get("cash.gaps")) + items
        for item in items:
            if item.claim.id not in seen:
                seen.add(item.claim.id)
                out.append(item)
    return out
