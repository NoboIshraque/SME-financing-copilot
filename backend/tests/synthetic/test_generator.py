"""The synthetic universe is deterministic, labelled, realistic and contains the demo cases."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
UNIVERSE = REPO / "data" / "synthetic" / "universe"
SMES = ("sme_grocery", "sme_pharmacy", "sme_fabric", "sme_garment", "sme_hardware")


def _load_generator():
    spec = importlib.util.spec_from_file_location("hishab_generate",
                                                  REPO / "data" / "synthetic" / "generate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


gen = _load_generator()
MANIFEST = json.loads((UNIVERSE / "manifest.json").read_text(encoding="utf-8"))
CSV_FILES = sorted(name for name in MANIFEST["files"] if name.endswith(".csv"))


@pytest.fixture(scope="module")
def rendered():
    return gen.render_universe(MANIFEST["seed"])


def rows(name: str) -> list[dict[str, str]]:
    with (UNIVERSE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def truth(sme: str) -> list[dict[str, str]]:
    return rows(f"{sme}/transactions_truth.csv")


def test_same_seed_reproduces_the_committed_universe_byte_for_byte(rendered):
    manifest = gen.build_manifest(rendered, MANIFEST["seed"])
    assert manifest["universe_sha256"] == MANIFEST["universe_sha256"], (
        "generator output changed: run `npm run synthetic` and commit data/synthetic/universe"
    )


def test_committed_files_match_their_manifest_hashes():
    for name, digest in MANIFEST["files"].items():
        data = (UNIVERSE / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name


def test_a_different_seed_gives_a_different_universe(rendered):
    other = gen.build_manifest(gen.render_universe(MANIFEST["seed"] + 1), MANIFEST["seed"] + 1)
    assert other["universe_sha256"] != MANIFEST["universe_sha256"]


@pytest.mark.parametrize("name", CSV_FILES)
def test_every_row_is_labelled_synthetic(name):
    text = (UNIVERSE / name).read_text(encoding="utf-8")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    mode_col = [i for i, col in enumerate(header) if col.lower().replace(" ", "_") == "data_mode"]
    assert mode_col, f"{name} has no data_mode column"
    assert all(row[mode_col[0]] == "synthetic" for row in reader)


@pytest.mark.parametrize("sme", SMES)
def test_profiles_are_labelled_and_cover_eighteen_months(sme):
    profile = json.loads((UNIVERSE / sme / "profile.json").read_text(encoding="utf-8"))
    assert profile["data_mode"] == "synthetic"
    start = date.fromisoformat(profile["period"]["start"])
    end = date.fromisoformat(profile["period"]["end"])
    assert (end.year - start.year) * 12 + end.month - start.month + 1 == 18


def _daily_sales(sme: str) -> dict[date, float]:
    totals: dict[date, float] = {}
    for row in truth(sme):
        if row["category"] == "sales":
            day = datetime.fromisoformat(row["occurred_at"]).date()
            totals[day] = totals.get(day, 0.0) + float(row["amount"])
    return totals


@pytest.mark.parametrize(("sme", "min_lift"), [("sme_fabric", 1.4), ("sme_grocery", 1.15)])
def test_pre_eid_weeks_sell_more_than_normal_weeks(sme, min_lift):
    sales = _daily_sales(sme)
    eid = date(2026, 3, 21)
    pre_eid = sum(sales.get(eid - timedelta(days=d), 0.0) for d in range(1, 22))
    windows = []
    day = date(2025, 7, 1)
    while day + timedelta(days=21) < date(2026, 1, 31):
        windows.append(sum(sales.get(day + timedelta(days=d), 0.0) for d in range(21)))
        day += timedelta(days=21)
    assert pre_eid > min_lift * statistics.median(windows)


def test_wholesalers_sell_little_on_friday():
    sales = _daily_sales("sme_fabric")
    by_weekday: dict[int, list[float]] = {}
    for day, amount in sales.items():
        by_weekday.setdefault(day.weekday(), []).append(amount)
    friday = sum(by_weekday.get(4, [0.0]))
    monday = sum(by_weekday[0])
    assert friday < 0.35 * monday


@pytest.mark.parametrize("sme", ["sme_grocery", "sme_pharmacy"])
def test_retail_sales_are_mostly_mobile_money(sme):
    channels = Counter(r["channel"] for r in truth(sme) if r["category"] == "sales")
    share = (channels["bkash"] + channels["nagad"]) / sum(channels.values())
    assert 0.5 <= share <= 0.7


@pytest.mark.parametrize("sme", SMES)
def test_salary_and_rent_are_paid_every_month(sme):
    months_salary = {r["reference"] for r in truth(sme) if r["reference"].startswith("SAL-")}
    months_rent = {r["reference"] for r in truth(sme) if r["reference"].startswith("RENT-")}
    assert len(months_salary) == 18 and len(months_rent) == 18


def test_eid_bonus_is_paid_before_each_eid():
    refs = {r["reference"] for r in truth("sme_garment")}
    for ref in ("BONUS-EID_UL_ADHA-2025", "BONUS-EID_UL_FITR-2026", "BONUS-EID_UL_ADHA-2026"):
        assert ref in refs


def test_the_circular_debt_ring_is_open_and_forms_a_cycle():
    ring = rows("mesh_obligations.csv")
    edges = {(r["debtor"], r["creditor"]) for r in ring}
    assert len(edges) == 3
    nodes = {n for edge in edges for n in edge}
    assert nodes == {"sme_fabric", "sme_garment", "sme_hardware"}
    out_degree = Counter(d for d, _ in edges)
    in_degree = Counter(c for _, c in edges)
    assert all(out_degree[n] == 1 and in_degree[n] == 1 for n in nodes)  # a single cycle
    for r in ring:  # both sides of every ring debt are booked and still open
        invoice = [x for x in rows(f"{r['creditor']}/baki_register.csv")
                   if x["number"] == r["ref"]]
        bill = [x for x in rows(f"{r['debtor']}/bills_register.csv") if x["number"] == r["ref"]]
        assert invoice and bill
        assert invoice[0]["status"] == bill[0]["status"] == "open"
        assert invoice[0]["amount"] == bill[0]["amount"] == r["amount"]


def test_exactly_two_disputed_invoices():
    disputed = [r for sme in SMES for r in rows(f"{sme}/baki_register.csv")
                if r["status"] == "disputed"]
    assert len(disputed) == 2
    assert all(r["note"] for r in disputed)


@pytest.mark.parametrize("sme", SMES)
def test_bank_statement_balances_reconcile_with_transactions(sme):
    profile = json.loads((UNIVERSE / sme / "profile.json").read_text(encoding="utf-8"))
    balance = float(profile["opening_balances"]["bank"])
    for row in truth(sme):
        if row["channel"] == "bank":
            sign = 1 if row["direction"] == "inflow" else -1
            balance += sign * float(row["amount"])
    statement = rows(f"{sme}/bank_statement.csv")
    assert round(balance, 2) == float(statement[-1]["Balance"])


@pytest.mark.parametrize("sme", ["sme_grocery", "sme_fabric", "sme_hardware"])
def test_mobile_money_wallets_never_go_negative(sme):
    for name in ("bkash_statement.csv", "nagad_statement.csv"):
        balances = [float(r.get("Balance", 0)) for r in rows(f"{sme}/{name}")]
        assert all(b >= 0 for b in balances), name


@pytest.mark.parametrize("sme", ["sme_fabric", "sme_hardware", "sme_grocery"])
def test_paid_baki_has_a_matching_collection(sme):
    collections = {r["reference"]: r for r in truth(sme) if r["category"] == "collection"}
    paid = [r for r in rows(f"{sme}/baki_register.csv")
            if r["status"] == "paid" and r["paid_date"] >= "2025-04-01"]
    assert paid
    for invoice in paid:
        match = collections[invoice["number"]]
        assert match["amount"] == invoice["amount"]
        assert match["occurred_at"][:10] == invoice["paid_date"]


def test_some_customers_are_chronic_late_payers():
    late_days = []
    for r in rows("sme_fabric/baki_register.csv"):
        if r["status"] == "paid":
            late = (date.fromisoformat(r["paid_date"]) - date.fromisoformat(r["due_date"])).days
            late_days.append(late)
    assert max(late_days) >= 20  # chronic payers exist
    assert statistics.median(late_days) <= 7  # but most pay close to terms


def test_the_universe_contains_at_least_one_real_cash_gap():
    """Demo needs a real dip: some SME's bank balance goes below zero at least once."""
    dips = []
    for sme in SMES:
        balances = [float(r["Balance"]) for r in rows(f"{sme}/bank_statement.csv")]
        dips.append(min(balances) < 0)
    assert any(dips)
