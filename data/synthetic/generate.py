"""Synthetic SME universe for Hishab (WP-00). Deterministic: same seed -> same bytes.

Five Dhaka SMEs, 18 months of activity (2025-04-01 .. 2026-09-30):
grocery, pharmacy, fabric wholesaler, garment subcontractor, hardware.

Every row is labelled `synthetic`. Files use the shapes of real exports so WP-02 parses
realistic input: a bKash-style merchant statement, a Nagad-style statement, a bank statement,
a cash book, a baki (credit sales) register, a bills register and recurring obligations.
A circular debt ring between three SMEs (fabric -> garment -> hardware -> fabric) is left
open on the as-of date for the liquidity-mesh demo.

Run:  npm run synthetic      (writes data/synthetic/universe/ and manifest.json)
"""

# Naive datetimes are deliberate: exports show Dhaka local time, as real statements do.
# ruff: noqa: DTZ001

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261020
START = date(2025, 4, 1)
AS_OF = date(2026, 9, 30)
WARMUP_DAYS = 120  # simulated before START so baki and bills are already in flight on day one
DATA_MODE = "synthetic"

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CALENDAR_FILE = REPO_ROOT / "data" / "public" / "calendar" / "bd_festivals.yaml"
DEFAULT_OUT = HERE / "universe"

FIRST_NAMES = [
    "Rahim", "Karim", "Salma", "Nasima", "Jamal", "Rafiq", "Shirin", "Habib", "Farzana",
    "Kamal", "Rubina", "Anwar", "Mitu", "Sohel", "Tania", "Babul", "Ruma", "Faruk",
    "Lipi", "Mizan", "Shapla", "Delwar", "Moushumi", "Aziz", "Parvin", "Selim",
]
LAST_NAMES = [
    "Hossain", "Rahman", "Islam", "Ahmed", "Uddin", "Akter", "Begum", "Mia", "Sarkar",
    "Chowdhury", "Khan", "Sheikh", "Molla", "Talukder", "Bhuiyan", "Das", "Saha",
]
SHOP_WORDS = ["Store", "Traders", "Enterprise", "Bhandar", "Agency", "Corporation", "House"]
SHOP_PREFIX = ["Bismillah", "Madina", "New", "Rupali", "Sonali", "Dhaka", "Mayer Doa",
               "Bhai Bhai", "Al-Amin", "Shapla", "Green", "Janata", "Nabil", "Ma"]


# --------------------------------------------------------------------------------------
# Configuration of the five SMEs
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SMEConfig:
    id: str
    sector: str
    area: str
    business_age_months: int
    staff: int
    daily_sales: int  # baseline Tk per normal day
    tickets_per_day: int  # retail baskets / wholesale orders per day
    channel_mix: tuple[tuple[str, float], ...]  # sales channel shares
    credit_share: float  # share of sales made on baki (credit)
    credit_customers: int
    credit_terms_days: int
    cogs_ratio: float
    supplier_terms_days: int
    opening: tuple[tuple[str, int], ...]
    rent: int
    salary: int
    utility: int
    emi: int  # 0 = no loan
    friday_factor: float
    month_start_factor: float
    eid_fitr_factor: float
    eid_adha_factor: float
    boishakh_factor: float
    target_balance: int = 300000  # owner draws most cash above this each month
    festival_bonus: float = 0.5  # share of monthly salary paid as Eid bonus (x2 a year)
    trade_licence: bool = True
    etin: bool = True


SMES: tuple[SMEConfig, ...] = (
    SMEConfig(
        id="sme_grocery", sector="grocery", area="Mirpur", business_age_months=74, staff=4,
        daily_sales=26000, tickets_per_day=14,
        channel_mix=(("bkash", 0.40), ("nagad", 0.20), ("cash", 0.40)),
        credit_share=0.08, credit_customers=12, credit_terms_days=15,
        cogs_ratio=0.82, supplier_terms_days=7,
        opening=(("bank", 160000), ("bkash", 35000), ("nagad", 15000), ("cash", 20000)),
        rent=35000, salary=60000, utility=9000, emi=0,
        friday_factor=1.25, month_start_factor=1.15,
        eid_fitr_factor=1.35, eid_adha_factor=1.45, boishakh_factor=1.10,
        target_balance=340000,
    ),
    SMEConfig(
        id="sme_pharmacy", sector="pharmacy", area="Dhanmondi", business_age_months=41, staff=3,
        daily_sales=31000, tickets_per_day=16,
        channel_mix=(("bkash", 0.42), ("nagad", 0.18), ("cash", 0.30), ("card", 0.10)),
        credit_share=0.04, credit_customers=6, credit_terms_days=30,
        cogs_ratio=0.76, supplier_terms_days=21,
        opening=(("bank", 210000), ("bkash", 30000), ("nagad", 10000), ("cash", 15000)),
        rent=45000, salary=55000, utility=11000, emi=0,
        friday_factor=0.90, month_start_factor=1.05,
        eid_fitr_factor=0.95, eid_adha_factor=0.95, boishakh_factor=1.0, etin=False,
        target_balance=330000,
    ),
    SMEConfig(
        id="sme_fabric", sector="fabric_wholesale", area="Islampur", business_age_months=132,
        staff=6, daily_sales=118000, tickets_per_day=4,
        channel_mix=(("bank", 0.50), ("bkash", 0.25), ("cash", 0.25)),
        credit_share=0.55, credit_customers=20, credit_terms_days=30,
        cogs_ratio=0.83, supplier_terms_days=30,
        opening=(("bank", 650000), ("bkash", 60000), ("nagad", 0), ("cash", 40000)),
        rent=90000, salary=140000, utility=14000, emi=0,
        friday_factor=0.15, month_start_factor=1.0,
        eid_fitr_factor=1.85, eid_adha_factor=1.25, boishakh_factor=1.55,
        target_balance=1300000,
    ),
    SMEConfig(
        id="sme_garment", sector="garment_subcontract", area="Ashulia", business_age_months=58,
        staff=38, daily_sales=0, tickets_per_day=0,
        channel_mix=(("bank", 1.0),),
        credit_share=1.0, credit_customers=4, credit_terms_days=60,
        cogs_ratio=0.45, supplier_terms_days=45,
        opening=(("bank", 1500000), ("bkash", 20000), ("nagad", 0), ("cash", 30000)),
        rent=120000, salary=620000, utility=55000, emi=85000,
        friday_factor=0.0, month_start_factor=1.0,
        eid_fitr_factor=1.5, eid_adha_factor=1.2, boishakh_factor=1.0,
        target_balance=2300000, festival_bonus=1.0,
    ),
    SMEConfig(
        id="sme_hardware", sector="hardware", area="Nawabpur", business_age_months=96, staff=5,
        daily_sales=58000, tickets_per_day=7,
        channel_mix=(("bank", 0.30), ("bkash", 0.30), ("nagad", 0.10), ("cash", 0.30)),
        credit_share=0.30, credit_customers=14, credit_terms_days=21,
        cogs_ratio=0.77, supplier_terms_days=30,
        opening=(("bank", 380000), ("bkash", 40000), ("nagad", 10000), ("cash", 25000)),
        rent=60000, salary=95000, utility=10000, emi=42000,
        friday_factor=0.20, month_start_factor=1.0,
        eid_fitr_factor=1.05, eid_adha_factor=1.10, boishakh_factor=1.0,
        target_balance=650000,
    ),
)

# Circular debt ring left open on AS_OF: (creditor, debtor, amount, issue, due, invoice no)
RING: tuple[tuple[str, str, int, date, date, str], ...] = (
    ("sme_fabric", "sme_garment", 450000, date(2026, 8, 28), date(2026, 10, 12), "RING-FG-001"),
    ("sme_garment", "sme_hardware", 320000, date(2026, 9, 2), date(2026, 10, 15), "RING-GH-001"),
    ("sme_hardware", "sme_fabric", 380000, date(2026, 9, 5), date(2026, 10, 10), "RING-HF-001"),
)
SME_DISPLAY = {
    "sme_grocery": "Mirpur Mudi Store",
    "sme_pharmacy": "Dhanmondi Care Pharmacy",
    "sme_fabric": "Islampur Fabric House",
    "sme_garment": "Ashulia Stitch Works",
    "sme_hardware": "Nawabpur Hardware Traders",
}
# Exactly two disputed invoices in the universe: (sme, customer index, issue date)
DISPUTES = (("sme_fabric", 3, date(2026, 8, 18)), ("sme_hardware", 5, date(2026, 9, 8)))


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def tk(value: float | int | Decimal) -> Decimal:
    """Whole-taka Decimal (rounded half-up) so outputs are identical on every platform."""
    return Decimal(str(round(float(value), 4))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def money_str(value: Decimal) -> str:
    return f"{value:.2f}"


def load_festivals(path: Path = CALENDAR_FILE) -> list[tuple[str, date]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for row in data["festivals"]:
        day = row["date"] if isinstance(row["date"], date) else date.fromisoformat(row["date"])
        out.append((row["name"], day))
    return sorted(out, key=lambda item: item[1])


def daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def month_end(day: date) -> date:
    nxt = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def seasonal_factor(cfg: SMEConfig, day: date, festivals: list[tuple[str, date]]) -> float:
    factor = 1.0
    if day.weekday() == 4:  # Friday: weekly holiday in Bangladesh
        factor *= cfg.friday_factor
    if day.day <= 7:
        factor *= cfg.month_start_factor
    for name, fday in festivals:
        delta = (fday - day).days  # > 0 means the festival is ahead
        if name == "eid_ul_fitr":
            if 1 <= delta <= 21:
                factor *= cfg.eid_fitr_factor
            elif -2 <= delta <= 0:
                factor *= 0.25
            elif -9 <= delta <= -3:
                factor *= 0.7
        elif name == "eid_ul_adha":
            if 1 <= delta <= 10:
                factor *= cfg.eid_adha_factor
            elif -2 <= delta <= 0:
                factor *= 0.3
        elif name == "pohela_boishakh" and 1 <= delta <= 10:
            factor *= cfg.boishakh_factor
    return factor


def stock_build_factor(cfg: SMEConfig, day: date, festivals: list[tuple[str, date]]) -> float:
    """Purchases run ahead of festival sales (the classic pre-Eid cash squeeze)."""
    for name, fday in festivals:
        delta = (fday - day).days
        if name == "eid_ul_fitr" and 22 <= delta <= 35:
            return 1.0 + (cfg.eid_fitr_factor - 1.0) * 1.6
        if name == "eid_ul_adha" and 11 <= delta <= 20:
            return 1.0 + (cfg.eid_adha_factor - 1.0) * 1.4
    return 1.0


@dataclass
class Txn:
    at: datetime
    channel: str
    direction: str  # inflow | outflow
    amount: Decimal
    category: str
    party: str
    party_phone: str
    reference: str
    note: str = ""


@dataclass
class Doc:
    number: str
    party: str
    party_phone: str
    issue: date
    due: date
    amount: Decimal
    paid: Decimal = Decimal(0)
    paid_date: date | None = None
    status: str = "open"
    note: str = ""


@dataclass
class World:
    txns: list[Txn] = field(default_factory=list)
    invoices: list[Doc] = field(default_factory=list)
    bills: list[Doc] = field(default_factory=list)
    obligations: list[dict[str, str]] = field(default_factory=list)
    opening_at_start: dict[str, Decimal] = field(default_factory=dict)


class Names:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.used: set[str] = set()

    def phone(self) -> str:
        prefix = self.rng.choice(["013", "014", "015", "016", "017", "018", "019"])
        return prefix + "".join(str(self.rng.randrange(10)) for _ in range(8))

    def person(self) -> str:
        while True:
            name = f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"
            if name not in self.used:
                self.used.add(name)
                return name

    def shop(self) -> str:
        while True:
            name = f"{self.rng.choice(SHOP_PREFIX)} {self.rng.choice(SHOP_WORDS)}"
            if name not in self.used:
                self.used.add(name)
                return name


# --------------------------------------------------------------------------------------
# Simulation of one SME
# --------------------------------------------------------------------------------------


def simulate(cfg: SMEConfig, seed: int, festivals: list[tuple[str, date]]) -> World:
    rng = random.Random(f"{seed}:{cfg.id}")
    names = Names(rng)
    world = World()
    walk_in = "Walk-in customer"

    customers = []
    for i in range(cfg.credit_customers):
        label = names.shop() if cfg.sector != "garment_subcontract" else f"Exporter {i + 1} Ltd"
        # Payment habit: mean delay beyond terms (days) and spread; a few chronic late payers.
        chronic = i % 5 == 4
        habit_mean = rng.uniform(8, 25) if chronic else rng.uniform(-3, 6)
        habit_sd = rng.uniform(4, 10) if chronic else rng.uniform(1.5, 5)
        customers.append((label, names.phone(), habit_mean, habit_sd))
    suppliers = [(names.shop(), names.phone()) for _ in range(4)]
    landlord = (names.person(), names.phone())
    lender = ("Sonali Commerce Bank PLC (synthetic)", "")
    utility = ("DESCO / Titas utilities", "")

    inv_seq = 0
    bill_seq = 0

    def new_invoice(day: date, customer: tuple, amount: Decimal, terms: int, ref=None) -> Doc:
        nonlocal inv_seq
        inv_seq += 1
        doc = Doc(
            number=ref or f"{cfg.id[4:7].upper()}-INV-{inv_seq:05d}",
            party=customer[0], party_phone=customer[1],
            issue=day, due=day + timedelta(days=terms), amount=amount,
        )
        world.invoices.append(doc)
        return doc

    def new_bill(day: date, supplier: tuple, amount: Decimal, terms: int, ref=None) -> Doc:
        nonlocal bill_seq
        bill_seq += 1
        doc = Doc(
            number=ref or f"{cfg.id[4:7].upper()}-BILL-{bill_seq:05d}",
            party=supplier[0], party_phone=supplier[1],
            issue=day, due=day + timedelta(days=terms), amount=amount,
        )
        world.bills.append(doc)
        return doc

    def at(day: date, lo: int = 9, hi: int = 21) -> datetime:
        return datetime(day.year, day.month, day.day, rng.randint(lo, hi), rng.randint(0, 59),
                        rng.randint(0, 59))

    def pick_channel(mix) -> str:
        r = rng.random()
        acc = 0.0
        for name, share in mix:
            acc += share
            if r < acc:
                return name
        return mix[-1][0]

    pending_collections: list[tuple[date, Doc, Decimal]] = []  # (pay day, invoice, amount)
    purchase_accumulator = Decimal(0)
    prebought = Decimal(0)  # festival stock bought ahead, consumed by later weeks

    for day in daterange(START - timedelta(days=WARMUP_DAYS), AS_OF):
        factor = seasonal_factor(cfg, day, festivals)

        # ---- Sales ---------------------------------------------------------------
        if cfg.sector == "garment_subcontract":
            # 2-4 export orders a month, invoiced on delivery, paid by bank on long terms.
            if day.weekday() != 4 and rng.random() < 0.16 * max(factor, 0.3):
                customer = customers[rng.randrange(len(customers))]
                amount = tk(rng.uniform(280000, 820000) * (1.25 if factor > 1.2 else 1.0))
                doc = new_invoice(day, customer, amount, cfg.credit_terms_days)
                purchase_accumulator += amount * Decimal(str(cfg.cogs_ratio))
                delay = max(0, round(rng.gauss(customer[2], customer[3])))
                pending_collections.append((doc.due + timedelta(days=delay), doc, amount))
        else:
            expected = cfg.daily_sales * factor
            tickets = max(0, round(cfg.tickets_per_day * factor * rng.uniform(0.7, 1.3)))
            if tickets:
                day_total = expected * math.exp(rng.gauss(0, 0.15) - 0.01125)
                weights = [rng.uniform(0.3, 1.7) for _ in range(tickets)]
                scale = day_total / sum(weights)
                for w in weights:
                    amount = tk(w * scale)
                    if amount < 20:
                        continue
                    purchase_accumulator += amount * Decimal(str(cfg.cogs_ratio))
                    if rng.random() < cfg.credit_share:
                        customer = customers[rng.randrange(len(customers))]
                        doc = new_invoice(day, customer, amount, cfg.credit_terms_days)
                        delay = max(-5, round(rng.gauss(customer[2], customer[3])))
                        pay_day = max(day + timedelta(days=1), doc.due + timedelta(days=delay))
                        pending_collections.append((pay_day, doc, amount))
                    else:
                        channel = pick_channel(cfg.channel_mix)
                        phone = names.phone() if channel in ("bkash", "nagad") else ""
                        world.txns.append(Txn(at(day), channel, "inflow", amount, "sales",
                                              walk_in, phone, f"SALE-{day:%y%m%d}"))

        # ---- Collections of baki -------------------------------------------------
        still_pending = []
        for pay_day, doc, amount in pending_collections:
            if pay_day <= day and doc.status != "disputed":
                channel = "bank" if cfg.sector == "garment_subcontract" else pick_channel(
                    (("bkash", 0.45), ("bank", 0.30), ("cash", 0.25)))
                world.txns.append(Txn(at(day), channel, "inflow", amount, "collection",
                                      doc.party, doc.party_phone, doc.number))
                doc.paid = doc.amount
                doc.paid_date = day
                doc.status = "paid"
            else:
                still_pending.append((pay_day, doc, amount))
        pending_collections = still_pending

        # ---- Purchases: weekly (Saturday) bills from suppliers -------------------
        if day.weekday() == 5 and purchase_accumulator > 0:
            build = stock_build_factor(cfg, day + timedelta(days=7), festivals)
            total = purchase_accumulator * Decimal(str(build))
            if build > 1:
                prebought += total - purchase_accumulator
            elif prebought > 0:
                used = min(prebought, purchase_accumulator * Decimal("0.6"))
                total -= used
                prebought -= used
            split = rng.randint(1, 2)
            for k in range(split):
                supplier = suppliers[(day.toordinal() + k) % len(suppliers)]
                amount = tk(total / split)
                if amount <= 0:
                    continue
                terms = cfg.supplier_terms_days
                doc = new_bill(day, supplier, amount, terms)
                lateness = rng.choice([0, 0, 0, 1, 2, 3])
                pay_day = doc.due + timedelta(days=lateness)
                if pay_day <= AS_OF:
                    channel = "bank" if amount > 50000 else rng.choice(["bank", "bkash", "cash"])
                    world.txns.append(Txn(at(pay_day, 10, 17), channel, "outflow", amount,
                                          "supplier_payment", supplier[0], supplier[1],
                                          doc.number))
                    doc.paid = doc.amount
                    doc.paid_date = pay_day
                    doc.status = "paid"
            purchase_accumulator = Decimal(0)

        # ---- Recurring obligations -----------------------------------------------
        if day.day == 5:
            world.txns.append(Txn(at(day, 10, 13), "bank", "outflow", tk(cfg.rent), "rent",
                                  landlord[0], landlord[1], f"RENT-{day:%Y%m}"))
        if day == month_end(day):
            world.txns.append(Txn(at(day, 17, 20), "bank", "outflow", tk(cfg.salary), "salary",
                                  "Staff payroll", "", f"SAL-{day:%Y%m}"))
        if day.day == 15:
            amount = tk(cfg.utility * rng.uniform(0.85, 1.25))
            world.txns.append(Txn(at(day, 10, 16), "bkash", "outflow", amount, "utility",
                                  utility[0], "", f"UTIL-{day:%Y%m}"))
        for name, fday in festivals:
            if name in ("eid_ul_fitr", "eid_ul_adha") and (fday - day).days == 7:
                world.txns.append(Txn(at(day, 15, 18), "bank", "outflow",
                                      tk(cfg.salary * cfg.festival_bonus), "salary",
                                      "Staff payroll", "", f"BONUS-{name.upper()}-{fday:%Y}"))
        if cfg.emi and day.day == 10:
            world.txns.append(Txn(at(day, 9, 11), "bank", "outflow", tk(cfg.emi),
                                  "loan_repayment", lender[0], "", f"EMI-{day:%Y%m}"))

    # ---- Disputes ---------------------------------------------------------------
    for sme_id, cust_index, issue in DISPUTES:
        if sme_id == cfg.id:
            customer = customers[cust_index]
            doc = new_invoice(issue, customer, tk(rng.uniform(60000, 140000)),
                              cfg.credit_terms_days)
            doc.status = "disputed"
            doc.note = "Buyer disputes quantity delivered"

    # ---- Open ring invoices / bills (mesh demo) -----------------------------------
    for creditor, debtor, amount, issue, due, ref in RING:
        if creditor == cfg.id:
            doc = new_invoice(issue, (SME_DISPLAY[debtor], ""), tk(amount), (due - issue).days,
                              ref=ref)
            doc.note = "Hishab tenant (mesh peer)"
        if debtor == cfg.id:
            doc = new_bill(issue, (SME_DISPLAY[creditor], ""), tk(amount), (due - issue).days,
                           ref=ref)
            doc.note = "Hishab tenant (mesh peer)"

    # ---- Obligation register -------------------------------------------------------
    world.obligations = [
        {"kind": "rent", "counterparty": landlord[0], "amount": money_str(tk(cfg.rent)),
         "frequency": "monthly", "day_of_period": "5", "start_date": START.isoformat()},
        {"kind": "salary", "counterparty": "Staff payroll", "amount": money_str(tk(cfg.salary)),
         "frequency": "monthly", "day_of_period": "31", "start_date": START.isoformat()},
        {"kind": "utility", "counterparty": utility[0], "amount": money_str(tk(cfg.utility)),
         "frequency": "monthly", "day_of_period": "15", "start_date": START.isoformat()},
    ]
    if cfg.emi:
        world.obligations.append(
            {"kind": "emi", "counterparty": lender[0], "amount": money_str(tk(cfg.emi)),
             "frequency": "monthly", "day_of_period": "10", "start_date": START.isoformat()})

    _sweep_balances(cfg, world, rng)
    _drop_warmup(world)
    world.txns.sort(key=lambda t: (t.at, t.channel, t.reference, t.amount))
    return world


def _sweep_balances(cfg: SMEConfig, world: World, rng: random.Random) -> None:
    """Move surplus mobile money and cash to the bank, and top up mobile money when an
    outflow would overdraw it, the way a real shop does. Adds `transfer` rows."""
    world.txns.sort(key=lambda t: (t.at, t.channel, t.reference, t.amount))
    balances = {name: Decimal(value) for name, value in cfg.opening}
    balances.setdefault("card", Decimal(0))
    floats = {"bkash": Decimal(25000), "nagad": Decimal(15000), "cash": Decimal(15000),
              "card": Decimal(0)}
    extra: list[Txn] = []
    last_day: date | None = None
    for txn in list(world.txns):
        day = txn.at.date()
        if day >= START and not world.opening_at_start:
            world.opening_at_start = dict(balances)
        if last_day is not None and (day.year, day.month) != (last_day.year, last_day.month):
            total = sum(balances.values())
            excess = total - Decimal(cfg.target_balance)
            if excess > 0:
                amount = tk(excess * Decimal("0.6"))
                moment = datetime(day.year, day.month, day.day, 8, 0)
                extra.append(Txn(moment, "bank", "outflow", amount, "owner_draw",
                                 "Owner (personal account)", "", f"DRAW-{day:%Y%m}"))
                balances["bank"] -= amount
        if last_day is not None and day != last_day:
            for channel, keep in floats.items():
                surplus = balances[channel] - keep
                daily = channel in ("cash", "card")  # card acquirers settle to the bank daily
                if surplus > (0 if channel == "card" else 20000) and (
                    daily or last_day.weekday() in (0, 3)
                ):
                    moment = datetime(last_day.year, last_day.month, last_day.day, 23, 59)
                    amount = tk(surplus)
                    ref = f"SWEEP-{channel.upper()}-{last_day:%y%m%d}"
                    extra.append(Txn(moment, channel, "outflow", amount, "transfer",
                                     "Own bank account", "", ref))
                    extra.append(Txn(moment, "bank", "inflow", amount, "transfer",
                                     f"Own {channel} account", "", ref))
                    balances[channel] -= amount
                    balances["bank"] += amount
        last_day = day
        if txn.direction == "outflow" and txn.channel != "bank":
            shortfall = txn.amount - balances[txn.channel]
            if shortfall > 0:
                amount = tk(shortfall + 5000)
                moment = txn.at - timedelta(minutes=5)
                ref = f"TOPUP-{txn.channel.upper()}-{day:%y%m%d}-{rng.randrange(1000):03d}"
                extra.append(Txn(moment, "bank", "outflow", amount, "transfer",
                                 f"Own {txn.channel} account", "", ref))
                extra.append(Txn(moment, txn.channel, "inflow", amount, "transfer",
                                 "Own bank account", "", ref))
                balances["bank"] -= amount
                balances[txn.channel] += amount
        sign = 1 if txn.direction == "inflow" else -1
        balances[txn.channel] += sign * txn.amount
    world.txns.extend(extra)
    if not world.opening_at_start:
        world.opening_at_start = dict(balances)


def _drop_warmup(world: World) -> None:
    """Keep only what a statement starting on START shows: rows from START on, and documents
    still unpaid on START (older baki carried into the register)."""
    world.txns = [t for t in world.txns if t.at.date() >= START]
    for docs in (world.invoices, world.bills):
        docs[:] = [d for d in docs if d.paid_date is None or d.paid_date >= START]


# --------------------------------------------------------------------------------------
# Writers in each source's export shape
# --------------------------------------------------------------------------------------


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _trx_id(rng: random.Random, length: int = 10) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
    return "".join(rng.choice(alphabet) for _ in range(length))


def render_sme(cfg: SMEConfig, world: World, seed: int) -> dict[str, str]:
    rng = random.Random(f"{seed}:{cfg.id}:ids")
    opening = world.opening_at_start
    files: dict[str, str] = {}

    def running(channel: str) -> list[tuple[Txn, Decimal]]:
        balance = Decimal(opening.get(channel, 0))
        out = []
        for txn in world.txns:
            if txn.channel != channel:
                continue
            balance += txn.amount if txn.direction == "inflow" else -txn.amount
            out.append((txn, balance))
        return out

    # bKash-style merchant statement
    rows = []
    for txn, bal in running("bkash"):
        kind = {
            ("inflow", "sales"): "Payment Received",
            ("inflow", "collection"): "Payment Received",
            ("inflow", "transfer"): "Bank to bKash",
            ("outflow", "transfer"): "bKash to Bank",
            ("outflow", "utility"): "Pay Bill",
        }.get((txn.direction, txn.category), "Send Money" if txn.direction == "outflow" else
              "Cash In")
        fee = Decimal(0)
        if kind == "bKash to Bank":
            fee = Decimal(0)
        party = txn.party_phone or txn.party
        rows.append([_trx_id(rng), txn.at.strftime("%d/%m/%Y %H:%M:%S"), kind, party,
                     money_str(txn.amount), money_str(fee), money_str(bal), txn.reference,
                     DATA_MODE])
    files["bkash_statement.csv"] = _csv_text(
        ["TrxID", "Date Time", "Transaction Type", "From/To", "Amount (BDT)", "Fee",
         "Balance", "Reference", "Data Mode"], rows)

    # Nagad-style statement (different column names and date format on purpose)
    rows = []
    for txn, bal in running("nagad"):
        kind = "Received" if txn.direction == "inflow" else "Sent"
        rows.append([_trx_id(rng, 12), txn.at.strftime("%Y-%m-%d %I:%M %p"), kind,
                     txn.party_phone or txn.party, money_str(txn.amount), "0.00",
                     money_str(bal), DATA_MODE])
    files["nagad_statement.csv"] = _csv_text(
        ["Txn ID", "Txn Date", "Txn Type", "Counterpart", "Amount", "Charge", "Balance",
         "Data Mode"], rows)

    # Bank statement (debit/credit columns)
    rows = []
    for txn, bal in running("bank"):
        debit = money_str(txn.amount) if txn.direction == "outflow" else ""
        credit = money_str(txn.amount) if txn.direction == "inflow" else ""
        description = f"{txn.category.replace('_', ' ').upper()} {txn.party}".strip()
        rows.append([txn.at.strftime("%d-%b-%Y"), description, txn.reference, debit, credit,
                     money_str(bal), DATA_MODE])
    files["bank_statement.csv"] = _csv_text(
        ["Date", "Description", "Cheque/Ref No", "Debit", "Credit", "Balance", "Data Mode"],
        rows)

    # Cash book (ledger style)
    rows = []
    for txn, _bal in running("cash") + running("card"):
        rows.append([txn.at.strftime("%Y-%m-%d"), txn.party, txn.category,
                     "in" if txn.direction == "inflow" else "out", money_str(txn.amount),
                     txn.channel, txn.reference, DATA_MODE])
    rows.sort(key=lambda r: (r[0], r[2], r[6], r[4]))
    files["cash_book.csv"] = _csv_text(
        ["date", "party", "category", "type", "amount", "channel", "ref", "data_mode"], rows)

    # Ground truth: every transaction fully typed (for engine tests and parser checks).
    rows = []
    for n, txn in enumerate(world.txns, start=1):
        rows.append([f"{cfg.id}-T{n:06d}", txn.at.isoformat(), txn.channel, txn.direction,
                     money_str(txn.amount), txn.category, txn.party, txn.party_phone,
                     txn.reference, DATA_MODE])
    files["transactions_truth.csv"] = _csv_text(
        ["id", "occurred_at", "channel", "direction", "amount", "category", "counterparty",
         "phone", "reference", "data_mode"], rows)

    def doc_rows(docs: list[Doc]) -> list[list[str]]:
        out = []
        for doc in sorted(docs, key=lambda d: (d.issue, d.number)):
            out.append([doc.number, doc.party, doc.party_phone, doc.issue.isoformat(),
                        doc.due.isoformat(), money_str(doc.amount), money_str(doc.paid),
                        doc.paid_date.isoformat() if doc.paid_date else "", doc.status,
                        doc.note, DATA_MODE])
        return out

    doc_header = ["number", "party", "phone", "issue_date", "due_date", "amount",
                  "amount_paid", "paid_date", "status", "note", "data_mode"]
    files["baki_register.csv"] = _csv_text(doc_header, doc_rows(world.invoices))
    files["bills_register.csv"] = _csv_text(doc_header, doc_rows(world.bills))
    files["obligations.csv"] = _csv_text(
        ["kind", "counterparty", "amount", "frequency", "day_of_period", "start_date",
         "data_mode"],
        [[o["kind"], o["counterparty"], o["amount"], o["frequency"], o["day_of_period"],
          o["start_date"], DATA_MODE] for o in world.obligations])

    profile = {
        "id": cfg.id,
        "display_name": SME_DISPLAY[cfg.id],
        "sector": cfg.sector,
        "area": cfg.area,
        "business_age_months": cfg.business_age_months,
        "staff": cfg.staff,
        "trade_licence": cfg.trade_licence,
        "etin": cfg.etin,
        "opening_balances": {k: money_str(v) for k, v in sorted(world.opening_at_start.items())},
        "period": {"start": START.isoformat(), "end": AS_OF.isoformat()},
        "data_mode": DATA_MODE,
    }
    files["profile.json"] = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    return files


def render_universe(seed: int) -> dict[str, str]:
    festivals = load_festivals()
    files: dict[str, str] = {}
    for cfg in SMES:
        world = simulate(cfg, seed, festivals)
        for name, text in render_sme(cfg, world, seed).items():
            files[f"{cfg.id}/{name}"] = text
    files["mesh_obligations.csv"] = _csv_text(
        ["ref", "creditor", "debtor", "amount", "issue_date", "due_date", "data_mode"],
        [[ref, cred, debt, money_str(tk(amount)), issue.isoformat(), due.isoformat(), DATA_MODE]
         for cred, debt, amount, issue, due, ref in RING])
    return files


def build_manifest(files: dict[str, str], seed: int) -> dict[str, object]:
    digests = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in sorted(files.items())
    }
    combined = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in digests.items()).encode())
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "start": START.isoformat(),
        "as_of": AS_OF.isoformat(),
        "data_mode": DATA_MODE,
        "files": digests,
        "universe_sha256": combined.hexdigest(),
    }


def write(out_dir: Path, seed: int) -> dict[str, object]:
    files = render_universe(seed)
    for name, text in files.items():
        path = out_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    manifest = build_manifest(files, seed)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    manifest = write(args.out, args.seed)
    print(f"universe {manifest['universe_sha256'][:12]} -> {args.out} "
          f"({len(manifest['files'])} files, seed {args.seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
