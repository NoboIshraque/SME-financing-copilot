"""Message templates (WP-12 milestone 1; FEATURES N2).

English and Bangla text for each purpose. Variables are filled from typed values only (the WP-05
plan: customer label, open amount, due date, invoice count); a template whose variables are not
all supplied is refused, so no message ever goes out with a hole in it. Amounts are written in
taka with two decimals, never rounded by a model.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.contracts import Language, MessagePurpose

P = MessagePurpose
TEMPLATES: dict[tuple[MessagePurpose, Language], str] = {
    (P.pre_due_reminder, Language.en):
        "Dear {customer}, a friendly reminder: Tk {amount} for {invoices} invoice(s) is due on "
        "{due_date}. Thank you for your business. - {shop}",
    (P.pre_due_reminder, Language.bn):
        "প্রিয় {customer}, একটি বিনীত স্মরণ: {invoices}টি বিলের মোট {amount} টাকা {due_date} "
        "তারিখে পরিশোধযোগ্য। ধন্যবাদ। - {shop}",
    (P.overdue_reminder, Language.en):
        "Dear {customer}, Tk {amount} for {invoices} invoice(s) was due on {due_date} and is "
        "still open. Please pay at your earliest convenience, or reply to agree a date. - {shop}",
    (P.overdue_reminder, Language.bn):
        "প্রিয় {customer}, {invoices}টি বিলের মোট {amount} টাকা {due_date} তারিখে পরিশোধের কথা "
        "ছিল, এখনও বাকি আছে। অনুগ্রহ করে দ্রুত পরিশোধ করুন অথবা একটি তারিখ জানান। - {shop}",
    (P.payment_plan_offer, Language.en):
        "Dear {customer}, to make Tk {amount} easier, we can split it into {installments} "
        "payments starting {due_date}. Reply YES to agree. - {shop}",
    (P.payment_plan_offer, Language.bn):
        "প্রিয় {customer}, {amount} টাকা সহজ করতে আমরা {due_date} থেকে {installments} কিস্তিতে "
        "নিতে পারি। রাজি থাকলে হ্যাঁ লিখুন। - {shop}",
    (P.supplier_term_extension, Language.en):
        "Dear {customer}, could we pay the Tk {amount} bill due {due_date} {days} days later? "
        "We value working with you. - {shop}",
    (P.supplier_term_extension, Language.bn):
        "প্রিয় {customer}, {due_date} তারিখের {amount} টাকার বিলটি কি {days} দিন পরে পরিশোধ "
        "করতে পারি? আপনার সাথে কাজ করে আমরা খুশি। - {shop}",
}

_VARIABLE = re.compile(r"{(\w+)}")


class TemplateError(ValueError):
    pass


def amount_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,}"


def render(purpose: MessagePurpose, language: Language, variables: dict[str, str]) -> str:
    template = TEMPLATES.get((purpose, language))
    if template is None:
        raise TemplateError(f"no {language.value} template for {purpose.value}")
    needed = set(_VARIABLE.findall(template))
    missing = sorted(needed - {k for k, v in variables.items() if v})
    if missing:
        raise TemplateError(f"unfilled variables: {', '.join(missing)}")
    return _VARIABLE.sub(lambda m: variables[m.group(1)], template)
