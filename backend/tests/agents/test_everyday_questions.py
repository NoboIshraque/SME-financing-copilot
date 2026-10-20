"""Everyday questions owners, accountants and staff of a small Bangladeshi shop type (Session A).

Each row is a question as people actually write it, in English, Bangla, Banglish or Chinese,
and the intent the deterministic planner must find for it. The deterministic planner is what
the hosted demo runs (`LLM_MODE=fixtures`, no keys) and the fallback when a live model is
rate-limited, so a row that plans to `unknown` here is a "won't guess" on the hosted site.

The last block is precision: questions that must *not* be pulled into an intent by a keyword
that merely looks similar (বিলম্ব "delay" is not বিল "bill").
"""

import pytest

from app.llm import deterministic

CASH, PAY, OWED, LOAN = "cash_outlook", "upcoming_payments", "collect_receivables", "find_financing"
HEALTH, WHAT_IF, MESH, DRAFT = "business_health", "what_if", "settle_debts", "draft_message"
MARKET, HELP, UNKNOWN = "market_prices", "help", "unknown"

EVERYDAY = [
    # cash on hand, salaries, rent
    ("How much cash do I have?", CASH),
    ("Will I have enough money next week?", CASH),
    ("What will my balance look like this month?", CASH),
    ("Can I pay salaries on the 31st?", CASH),
    ("Can I afford to pay rent next week?", CASH),
    ("হাতে কত টাকা আছে?", CASH),
    ("এই মাসে কি টাকার টান পড়বে?", CASH),
    ("amar cash koto ache", CASH),
    ("ei mashe taka thakbe to?", CASH),
    ("staff der beton dite parbo?", CASH),
    ("我的现金能撑多久？", CASH),
    ("下个月钱够不够？", CASH),
    # upcoming payments: bills, suppliers, who to pay next
    ("সামনে কবে বিল দিব", PAY),  # hosted-site failure, 20 Oct (demo accountant, grocery)
    ("বিলগুলো কবে দিতে হবে?", PAY),
    ("বিলের টাকা কবে দিতে হবে?", PAY),
    ("Who do I pay next?", PAY),
    ("What bills are due this month?", PAY),
    ("Which supplier payments are coming up?", PAY),
    ("What payables are due?", PAY),
    ("How much do I owe suppliers?", PAY),
    ("সাপ্লায়ারকে কত টাকা দিতে হবে?", PAY),
    ("kon bill age dite hobe", PAY),
    ("接下来要付哪些账单？", PAY),
    # money owed to the shop
    ("Who owes me money?", OWED),
    ("Which customer should I chase first?", OWED),
    ("Show overdue invoices", OWED),
    ("How much is outstanding from customers?", OWED),
    ("কে কে টাকা বাকি রেখেছে?", OWED),
    ("customer der kach theke koto paona ache", OWED),
    ("baki khata dekhao", OWED),
    ("谁还欠我钱？", OWED),
    # loans
    ("How big a loan can I safely take?", LOAN),  # hosted-site failure, 20 Oct (garment owner)
    ("Which loan is best for me?", LOAN),
    ("Can I get a bank loan?", LOAN),
    ("Should I borrow money for Eid stock?", LOAN),
    ("আমি কত টাকা ঋণ নিতে পারব?", LOAN),
    ("bkash loan nibo?", LOAN),
    ("我能贷多少钱？", LOAN),
    # profit and how the business is doing
    ("Is my business doing ok?", HEALTH),
    ("How much profit did I make last month?", HEALTH),
    ("Show me the ratios for this quarter", HEALTH),
    ("What's my gross margin?", HEALTH),
    ("ব্যবসা কেমন চলছে?", HEALTH),
    ("amar business kemon cholche", HEALTH),
    ("这个季度赚了多少钱？", HEALTH),
    # what-ifs
    ("What if sales drop by 20%?", WHAT_IF),
    ("What happens if costs go up 10%?", WHAT_IF),
    ("যদি খরচ ১০% বাড়ে?", WHAT_IF),
    ("jodi customer 15 din deri kore pay kore?", WHAT_IF),
    ("如果销售下降两成会怎样？", WHAT_IF),
    # debts with other shops
    ("Can we settle the circular debt with the fabric and hardware shops?", MESH),
    ("Other shops owe us and we owe them, can we net it out?", MESH),
    ("অন্য দোকানের সাথে দেনা কাটাকাটি করা যায়?", MESH),
    ("三角债能抵消吗？", MESH),
    # drafting a reminder
    ("Draft a reminder to Customer 3", DRAFT),
    ("Write a payment reminder for my customers", DRAFT),
    ("একটা তাগাদা মেসেজ লিখে দাও", DRAFT),
    # today's summary
    ("What's today's summary?", CASH),
    ("What needs my attention today?", CASH),
    ("আজকের অবস্থা কী?", CASH),
    # market (cut from this version: must be recognised, then declined politely)
    ("What's the wholesale price of rice?", MARKET),
    # greetings and "what can you do"
    ("hi", HELP),
    ("Hello!", HELP),
    ("help", HELP),
    ("What can you do?", HELP),
    ("কী করতে পারো?", HELP),
    ("你能做什么？", HELP),
]

PRECISION = [
    ("বিলম্ব হলে জরিমানা কত?", PAY),  # বিলম্ব (delay) starts with বিল (bill)
    ("Tell me a joke", CASH),
    ("Hi, will I run out of cash next month?", HELP),  # a real question is not a greeting
    ("我们的毛利率是多少？", LOAN),  # 毛利率 contains 利率 (interest rate)
]


@pytest.mark.parametrize(("question", "intent"), EVERYDAY, ids=[q for q, _ in EVERYDAY])
def test_everyday_question_plans_to_its_intent(question, intent):
    assert deterministic.plan(question)["intents"][0] == intent


@pytest.mark.parametrize(("question", "not_intent"), PRECISION, ids=[q for q, _ in PRECISION])
def test_lookalike_words_do_not_pull_in_an_intent(question, not_intent):
    assert not_intent not in deterministic.plan(question)["intents"]


def test_no_everyday_question_falls_to_unknown():
    misses = [q for q, _ in EVERYDAY if deterministic.plan(q)["intents"] == [UNKNOWN]]
    assert misses == []
