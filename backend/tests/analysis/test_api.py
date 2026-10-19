"""Analysis API (WP-07 milestone 6): statements, ratios, variance, scenarios, stability."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from argon2.profiles import CHEAPEST
from fastapi.testclient import TestClient

from app.contracts import DataMode, Role, TxCategory
from app.db import init_db, make_engine, session_factory
from app.engines.analysis import store as analysis_store
from app.engines.analysis.jobs import freeze_tenant
from app.engines.analysis.variance import SnapshotKind
from app.facts import FactStore
from app.facts.seed import load_sme_into
from app.main import create_app
from app.security import passwords
from app.security.accounts import Accounts
from app.settings import Settings
from tests.analysis.helpers import anchor, out

D = Decimal
PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)  # the morning after the books end
ROUTES = [("GET", "/api/analysis/statements"), ("GET", "/api/analysis/ratios"),
          ("GET", "/api/analysis/variance"), ("POST", "/api/analysis/scenarios"),
          ("POST", "/api/analysis/stability")]


@pytest.fixture(scope="module")
def analysis_app(universe):
    previous = passwords.use_parameters(CHEAPEST)
    analysis_store.clear_cache()
    settings = Settings(_env_file=None, app_env="test", demo_mode=False,
                        database_url="sqlite://", llm_mode="fixtures", chain_mode="offline")
    app = create_app(settings)
    app.state.security_clock = lambda: NOW
    with app.state.session_factory() as session:
        store = FactStore(session)
        for sme_id in ("sme_grocery", "sme_garment", "sme_hardware"):
            load_sme_into(store, universe.smes[sme_id], universe.start, universe.as_of)
        grocery = universe.smes["sme_grocery"].transactions
        store.add_transactions(t.model_copy(update={"tenant_id": "short_shop",
                                                    "id": f"short-{t.id}"})
                               for t in grocery if t.day >= date(2026, 9, 1))
        store.put_fact(anchor("100000", date(2026, 9, 1), "short_shop"))  # one month of books
        store.add_transactions(t.model_copy(update={"tenant_id": "no_opening",
                                                    "id": f"none-{t.id}"}) for t in grocery)
        accounts = Accounts(session, settings)
        for email, tenant, role in (("owner@grocery.test", "sme_grocery", Role.owner),
                                    ("lender@grocery.test", "sme_grocery", Role.lender_viewer),
                                    ("owner@garment.test", "sme_garment", Role.owner),
                                    ("owner@hardware.test", "sme_hardware", Role.owner),
                                    ("owner@short.test", "short_shop", Role.owner),
                                    ("owner@none.test", "no_opening", Role.owner)):
            accounts.ensure_tenant(tenant, tenant, DataMode.synthetic, NOW)
            accounts.create_user(email=email, password=PASSWORD, tenant_id=tenant, role=role,
                                 display_name="Test", now=NOW,
                                 expires_at=NOW + timedelta(days=3650)
                                 if role is Role.lender_viewer else None)
        session.commit()
    yield app
    passwords.use_parameters(previous)
    analysis_store.clear_cache()


@pytest.fixture(scope="module")
def signed_in(analysis_app) -> Iterator:
    clients: dict[str, TestClient] = {}

    def client_for(email: str) -> TestClient:
        if email not in clients:
            client = TestClient(analysis_app)
            client.__enter__()
            assert client.post("/api/auth/login",
                               json={"email": email, "password": PASSWORD}).status_code == 200
            clients[email] = client
        return clients[email]

    yield client_for
    for client in clients.values():
        client.__exit__(None, None, None)


@pytest.fixture(scope="module")
def grocery(signed_in) -> TestClient:
    return signed_in("owner@grocery.test")


@pytest.fixture(scope="module")
def garment(signed_in) -> TestClient:
    return signed_in("owner@garment.test")


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _explain(client: TestClient, figure_id: str, tenant: str) -> dict:
    return _ok(client.get(f"/api/explain/{figure_id}", params={"tenant_id": tenant}))


def _values(lines):
    return {line["figure"]["label_key"].removeprefix("statement."): D(line["figure"]["value"])
            for line in lines}


# ---------------------------------------------------------------- statements and ratios


def test_september_statements_of_the_grocery(grocery, universe):
    body = _ok(grocery.get("/api/analysis/statements"))
    assert body["period"] == {"start": "2026-09-01", "end": "2026-09-30",
                              "granularity": "month"}
    assert (body["through"], body["partial"], body["data_mode"]) == ("2026-09-30", False,
                                                                     "synthetic")
    cash = _values(body["cash_flow"])
    assert cash["closing_cash"] == universe.smes["sme_grocery"].balance_on(
        date(2026, 9, 30)).amount
    assert cash["closing_cash"] == cash["opening_cash"] + cash["cash_in"] - cash["cash_out"]
    assert body["missing"] == ["stock_value"]
    assert [line["label_key"] for line in body["pnl"] if line["total"]] == [
        "statement.revenue", "statement.gross_profit", "statement.operating_expenses",
        "statement.operating_profit", "statement.net_profit"]


def test_every_statement_number_opens_in_explain(grocery):
    body = _ok(grocery.get("/api/analysis/statements"))
    for section in ("pnl", "balance_sheet", "cash_flow"):
        for line in body[section]:
            figure = line["figure"]
            explained = _explain(grocery, figure["id"], "sme_grocery")
            assert explained["formula"]["formula_id"] == figure["provenance"]["formula_id"]
            assert D(explained["value"]) == D(figure["value"])
    opening = next(line["figure"] for line in body["cash_flow"]
                   if line["label_key"] == "statement.opening_cash")
    explained = _explain(grocery, opening["id"], "sme_grocery")
    assert [i["metric"] for i in explained["inputs"]] == ["opening_balance"]  # WP-01's fact
    assert len(explained["source_rows"]) == 1  # that fact, not 8,000 earlier transactions


def test_quarterly_statements_and_bad_periods(garment):
    body = _ok(garment.get("/api/analysis/statements", params={"granularity": "quarter"}))
    assert (body["period"]["start"], body["period"]["end"]) == ("2026-07-01", "2026-09-30")
    assert set(body["missing"]) == {"stock_value", "loan_outstanding"}  # the EMI is on record
    week = garment.get("/api/analysis/statements", params={"granularity": "week"})
    assert week.status_code == 422 and week.json()["code"] == "invalid_request"
    early = garment.get("/api/analysis/statements", params={"on": "2025-01-15"})
    assert early.status_code == 422 and early.json()["code"] == "insufficient_data"


def test_ratios_cite_recorded_facts(garment):
    ratios = _ok(garment.get("/api/analysis/ratios"))
    by_name = {r["name"]: r for r in ratios}
    assert len(ratios) == 13 and by_name["current_ratio"]["value"] is None
    assert by_name["current_ratio"]["interpretation_key"] == "ratio.missing.stock_value"
    statements = _ok(garment.get("/api/analysis/statements"))
    net = _values(statements["pnl"])["net_profit"]
    repaid = -_values(statements["cash_flow"])["loan_flows"]
    assert D(by_name["dscr"]["value"]) == (net / repaid).quantize(D("0.01"))
    for input_id in by_name["dscr"]["provenance"]["input_fact_ids"]:
        assert _explain(garment, input_id, "sme_garment")["formula"]["formula_id"] in (
            "analysis.pnl.net_profit", "analysis.input.debt_service")


# ---------------------------------------------------------------- expected vs reality


def test_weekly_expected_vs_reality(grocery):
    body = _ok(grocery.get("/api/analysis/variance"))
    assert body["period"] == {"start": "2026-09-21", "end": "2026-09-27",
                              "granularity": "week"}  # the last week that has ended
    ranks = [v["rank"] for v in body["variances"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert [v["metric"] for v in body["variances"]][-2:] == ["net_cash_flow", "closing_balance"]
    assert body["snapshot"]["reconstructed"]  # frozen today, after the week began
    assert len(body["history"]) == 8
    assert body["correction"]["applied"] and len(body["correction"]["figures"]) == 2
    accuracy = _explain(grocery, body["accuracy"]["id"], "sme_grocery")
    assert accuracy["formula"]["formula_id"] == "analysis.variance.accuracy"
    line = body["lines"]["cash_sales"]
    assert line["favourable"] == (D(line["actual"]["value"]) >= D(line["expected"]["value"]))


def test_a_frozen_week_survives_a_late_upload(signed_in, analysis_app):
    hardware = signed_in("owner@hardware.test")
    first = _ok(hardware.get("/api/analysis/variance"))
    week = first["history"][-1]
    with analysis_app.state.session_factory() as session:  # a bill paid that week, found later
        late = out(date(2026, 9, 23), 50000, TxCategory.supplier_payment)
        FactStore(session).add_transactions([late.model_copy(update={
            "tenant_id": "sme_hardware", "id": "late-upload-1"})])
        session.commit()
    again = _ok(hardware.get("/api/analysis/variance"))
    assert again["history"][-1]["snapshot"] == week["snapshot"]  # the forecast stays frozen
    paid = {v["metric"]: D(v["actual"]) for v in again["variances"]}
    before = {v["metric"]: D(v["actual"]) for v in first["variances"]}
    assert paid["supplier_payments"] == before["supplier_payments"] + 50000


def test_quarterly_check_and_too_little_history(garment, signed_in):
    body = _ok(garment.get("/api/analysis/variance", params={"kind": "quarterly"}))
    assert (body["period"]["start"], body["period"]["end"]) == ("2026-07-01", "2026-09-30")
    short = signed_in("owner@short.test").get("/api/analysis/variance")
    assert short.status_code == 422 and short.json()["code"] == "insufficient_data"
    none = signed_in("owner@none.test").get("/api/analysis/statements")
    assert none.status_code == 422 and "initial_balance" in none.json()["detail"]["missing"]


# ---------------------------------------------------------------- scenarios and stability


def test_scenarios_compare_the_menu_against_the_buffer_target(grocery):
    body = _ok(grocery.post("/api/analysis/scenarios", json={}))
    ids = [s["id"] for s in body["scenarios"]]
    assert body["recommended_id"] in ids and "sc_do_nothing" in ids
    assert {s["decision"] for s in body["skipped"]} >= {"retime_supplier"}
    forecast = _ok(grocery.get("/api/cash/forecast"))
    assert D(body["buffer"]["amount"]) == D(forecast["band"]["buffer"]["amount"])
    for scenario in body["scenarios"]:
        expected, worst, breach, _risk, _cost = body["figures"][scenario["id"]]
        assert D(expected["value"]) == D(scenario["expected_outcome"]["amount"])
        assert D(worst["value"]) <= D(expected["value"])
        assert D(breach["value"]) == D(scenario["p_buffer_breach"])
    loan = body["figures"]["sc_take_loan"][0]
    assert _explain(grocery, loan["id"], "sme_grocery")["inputs"][0]["metric"] == \
        "opening_balance"
    assert body["details"]["sc_take_loan"]["product_id"]


def test_scenarios_are_reproducible_and_validated(grocery):
    request = {"decisions": ["do_nothing", "offer_discount"], "seed": 7}
    first = _ok(grocery.post("/api/analysis/scenarios", json=request))
    again = _ok(grocery.post("/api/analysis/scenarios", json=request))
    assert first["scenarios"] == again["scenarios"]
    assert first["recommendation_id"] == again["recommendation_id"]
    for bad in ({"decisions": ["buy_gold"]},
                {"assumptions": {"delay_days": [0, 7], "delay_weights_pct": [50, 40]}},
                {"decisions": []}, {"surprise": 1}):
        response = grocery.post("/api/analysis/scenarios", json=bad)
        assert response.status_code == 422, bad


def test_stability_of_a_recommendation(garment):
    comparison = _ok(garment.post("/api/analysis/scenarios", json={
        "decisions": ["do_nothing", "offer_discount", "net_via_mesh"]}))
    body = _ok(garment.post("/api/analysis/stability",
                            json={"recommendation_id": comparison["recommendation_id"]}))
    chosen = comparison["recommended_id"].removeprefix("sc_")
    assert body["recommendation_id"] == comparison["recommendation_id"]
    assert body["baseline_choice"] == chosen
    names = [r["name"] for r in body["results"]]
    assert names[-4:] == ["rows_shuffled", "parties_renamed", "question_reworded",
                          "dates_shifted_format"]
    held = sum(1 for r in body["results"] if r["held"])
    assert D(body["score"]) == (D(held) / len(names)).quantize(D("0.0001"))
    assert not body["unreliable"]
    assert set(body["what_would_flip"]) == {r["name"] for r in body["results"]
                                            if not r["held"]}
    assert _explain(garment, body["figure"]["id"], "sme_garment")["formula"]["formula_id"] == \
        "analysis.stability.score"


def test_stability_ids_belong_to_their_tenant(grocery, garment):
    mine = _ok(grocery.post("/api/analysis/scenarios",
                            json={"decisions": ["do_nothing"]}))["recommendation_id"]
    theirs = garment.post("/api/analysis/stability", json={"recommendation_id": mine})
    assert theirs.status_code == 404 and theirs.json()["code"] == "not_found"
    assert grocery.post("/api/analysis/stability",
                        json={"recommendation_id": "rec_unknown"}).status_code == 404
    both = grocery.post("/api/analysis/stability",
                        json={"recommendation_id": mine, "decisions": ["take_loan"]})
    assert both.status_code == 422


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_only_signed_in_ledger_readers(signed_in, analysis_app, method, path):
    lender = signed_in("lender@grocery.test")
    assert lender.request(method, path, json={} if method == "POST" else None).status_code \
        == 403
    with TestClient(analysis_app) as anonymous:
        assert anonymous.request(method, path,
                                 json={} if method == "POST" else None).status_code == 401


def test_the_nightly_job_freezes_what_is_due_once(universe):
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as db:
        load_sme_into(FactStore(db), universe.smes["sme_garment"], universe.start,
                      universe.as_of)
        on_time = datetime(2026, 9, 27, 17, 45, tzinfo=UTC)  # 23:45 on Sunday in Dhaka
        stored = freeze_tenant(db, "sme_garment", on_time)
        assert stored == 9 + 5  # 8 past weeks + the coming one; 4 past quarters + this one
        assert freeze_tenant(db, "sme_garment", on_time + timedelta(days=1)) == 0
        weeks = analysis_store.history(db, "sme_garment", SnapshotKind.weekly)
        assert weeks[-1].period.start == date(2026, 9, 28) and not weeks[-1].reconstructed
        assert all(w.reconstructed for w in weeks[:-1])
    engine.dispose()
