import csv
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from argon2.profiles import CHEAPEST
from fastapi.testclient import TestClient

import app.api.cash as cash_api
from app.api.cash import clear_cache
from app.contracts import DataMode, Role
from app.engines.cash.jobs import scan_tenant
from app.facts import FactStore, NotComputable
from app.facts.seed import load_sme_into
from app.main import create_app
from app.security import passwords
from app.security.accounts import Accounts
from app.settings import Settings
from app.synthetic.universe import UNIVERSE_DIR
from tests.cash.helpers import daily

D = Decimal
PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def cash_app(universe):
    previous = passwords.use_parameters(CHEAPEST)
    clear_cache()
    settings = Settings(_env_file=None, app_env="test", demo_mode=False,
                        database_url="sqlite://", llm_mode="fixtures", chain_mode="offline")
    app = create_app(settings)
    with app.state.session_factory() as session:
        store = FactStore(session)
        for sme_id in ("sme_grocery", "sme_hardware", "sme_garment"):
            load_sme_into(store, universe.smes[sme_id], universe.start, universe.as_of)
        short = [t.model_copy(update={"tenant_id": "short_shop", "id": f"short-{t.id}"})
                 for t in daily(date(2026, 9, 1), 30, lambda d: 1000)]
        store.add_transactions(short)  # 30 days of history only
        store.add_transactions([t.model_copy(update={"tenant_id": "no_opening",
                                                     "id": f"no-{t.id}"})
                                for t in daily(date(2026, 3, 1), 200, lambda d: 1000)])
        accounts = Accounts(session, settings)
        for email, tenant, role in (("owner@grocery.test", "sme_grocery", Role.owner),
                                    ("lender@grocery.test", "sme_grocery", Role.lender_viewer),
                                    ("staff@grocery.test", "sme_grocery", Role.staff),
                                    ("owner@hardware.test", "sme_hardware", Role.owner),
                                    ("owner@garment.test", "sme_garment", Role.owner),
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
    clear_cache()


@pytest.fixture(scope="module")
def signed_in(cash_app) -> Iterator:
    clients: dict[str, TestClient] = {}

    def client_for(email: str) -> TestClient:
        if email not in clients:
            client = TestClient(cash_app)
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
def hardware(signed_in) -> TestClient:
    return signed_in("owner@hardware.test")


def _band(response):
    assert response.status_code == 200, response.text
    return response.json()["band"]


def _figures(response):
    return {f["label_key"]: f for f in response.json()["figures"]}


# ---------------------------------------------------------------- forecast


def test_the_forecast_is_a_labelled_band_with_the_headline_figures(grocery, universe):
    res = grocery.get("/api/cash/forecast")
    band = _band(res)
    sme = universe.smes["sme_grocery"]
    assert (band["tenant_id"], band["as_of"], band["horizon_days"], band["paths"],
            band["seed"], band["data_mode"]) == ("sme_grocery", "2026-09-30", 91, 1000, 20261020,
                                                 "synthetic")
    assert D(band["opening_balance"]["amount"]) == sme.balance_on(universe.as_of).amount
    figures = _figures(res)
    assert set(figures) == {"cash.closing_balance", "cash.buffer_target", "cash.runway_days",
                            "cash.lowest_likely_balance"}
    assert D(figures["cash.closing_balance"]["value"]) == D(band["opening_balance"]["amount"])
    assert D(figures["cash.buffer_target"]["value"]) == D(band["buffer"]["amount"])


def test_a_shop_whose_last_day_has_only_outflows_still_gets_its_forecast(signed_in):
    """The garment shop's last ledger day (2026-09-30) holds only the payroll: no cash came
    in that day. The forecast still opens at its cash at close, which is the ground truth:
    the opening balances in its profile plus every transaction's signed amount."""
    folder = UNIVERSE_DIR / "sme_garment"
    with (folder / "transactions_truth.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    last_day = max(r["occurred_at"][:10] for r in rows)
    assert {r["direction"] for r in rows if r["occurred_at"][:10] == last_day} == {"outflow"}
    profile = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    truth = sum((D(v) for v in profile["opening_balances"].values()), D(0)) + sum(
        (D(r["amount"]) if r["direction"] == "inflow" else -D(r["amount"]) for r in rows), D(0))
    res = signed_in("owner@garment.test").get("/api/cash/forecast")
    band = _band(res)
    assert (band["tenant_id"], band["as_of"]) == ("sme_garment", last_day)
    assert D(band["opening_balance"]["amount"]) == truth
    assert D(_figures(res)["cash.closing_balance"]["value"]) == truth


def test_every_cash_figure_opens_in_explain_with_the_balance_it_starts_from(grocery):
    figures = _figures(grocery.get("/api/cash/forecast"))
    closing = D(figures["cash.closing_balance"]["value"])
    for label in ("cash.buffer_target", "cash.runway_days", "cash.lowest_likely_balance"):
        res = grocery.get(f"/api/explain/{figures[label]['id']}",
                          params={"tenant_id": "sme_grocery"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["formula"]["formula_id"] == figures[label]["provenance"]["formula_id"]
        assert D(body["value"]) == D(figures[label]["value"])
        (only,) = body["inputs"]
        assert only["metric"] == "opening_balance" and D(only["value"]) == closing


def test_the_same_ledger_and_seed_give_the_same_answer_and_another_seed_does_not(grocery):
    first, again = _band(grocery.get("/api/cash/forecast")), _band(
        grocery.get("/api/cash/forecast"))
    other = _band(grocery.get("/api/cash/forecast", params={"seed": 7}))
    assert first["points"] == again["points"] and first["points"] != other["points"]


def test_an_owner_buffer_replaces_the_target_in_the_band_but_the_target_is_still_shown(grocery):
    plain = grocery.get("/api/cash/forecast")
    mine = grocery.get("/api/cash/forecast", params={"buffer": "400000"})
    assert _band(mine)["buffer"]["amount"] == "400000.00"
    assert _figures(mine)["cash.buffer_target"]["value"] == \
        _figures(plain)["cash.buffer_target"]["value"]
    assert [p["p50"] for p in _band(mine)["points"]] == [p["p50"] for p in _band(plain)["points"]]
    assert [p["p_below_buffer"] for p in _band(mine)["points"]] != \
        [p["p_below_buffer"] for p in _band(plain)["points"]]


# ---------------------------------------------------------------- what-if


def test_a_what_if_without_shocks_is_the_plain_forecast(grocery):
    plain = _band(grocery.get("/api/cash/forecast"))
    same = _band(grocery.post("/api/cash/whatif", json={}))
    assert same["points"] == plain["points"]


def test_a_one_off_cost_lowers_every_band_by_exactly_that_amount_from_its_day(grocery):
    plain = _band(grocery.get("/api/cash/forecast"))
    shocked = _band(grocery.post("/api/cash/whatif", json={
        "one_off_cost": {"amount": "50000.00", "currency": "BDT"}, "one_off_day": "2026-10-10"}))
    for before, after in zip(plain["points"], shocked["points"], strict=True):
        drop = D(50000) if after["day"] >= "2026-10-10" else D(0)
        for band in ("p10", "p50", "p90"):
            assert D(before[band]["amount"]) - D(after[band]["amount"]) == drop


def test_a_sales_drop_lowers_the_likely_balance_and_slower_collections_never_raise_it(grocery):
    plain = _band(grocery.get("/api/cash/forecast"))["points"]
    drop = _band(grocery.post("/api/cash/whatif", json={"sales_change_pct": "-20"}))["points"]
    slow = _band(grocery.post("/api/cash/whatif", json={"collection_delay_days": 10}))["points"]
    assert D(drop[-1]["p50"]["amount"]) < D(plain[-1]["p50"]["amount"]) - D(300000)
    assert all(D(s["p50"]["amount"]) <= D(p["p50"]["amount"]) for s, p in zip(slow, plain,
                                                                              strict=True))


@pytest.mark.parametrize(
    "body",
    [{"sales_change_pct": "-150"}, {"one_off_day": "2027-06-01",
                                    "one_off_cost": {"amount": "10", "currency": "BDT"}},
     {"one_off_cost": {"amount": "10", "currency": "USD"}}, {"collection_delay_days": -1},
     {"surprise": 1}],
    ids=["sales-below-minus-100", "one-off-after-the-horizon", "one-off-not-in-taka",
         "negative-delay", "unknown-field"],
)
def test_a_what_if_refuses_impossible_shocks(grocery, body):
    assert grocery.post("/api/cash/whatif", json=body).status_code == 422


# ---------------------------------------------------------------- gaps and alerts


def test_gaps_come_with_their_numbers_drivers_and_indicators(hardware):
    res = hardware.get("/api/cash/gaps")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["as_of"] == "2026-09-30" and body["data_mode"] == "synthetic"
    days = [g["first_breach_day"] for g in body["gaps"]]
    assert days and days == sorted(days)
    first = body["gaps"][0]
    assert {f["label_key"] for f in first["figures"]} == {
        "cash.expected_shortfall", "cash.breach_probability", "cash.lead_time_days"}
    assert first["drivers"] and all(f["id"].startswith("fig_") for f in first["figures"])
    assert "dso_rising" in {i["indicator"] for i in body["indicators"]}


def test_alerts_come_highest_tier_first_with_up_to_three_fixes_cheapest_first(hardware):
    res = hardware.get("/api/cash/alerts")
    assert res.status_code == 200, res.text
    alerts = res.json()
    ranks = {"critical": 3, "warning": 2, "watch": 1}
    assert alerts and [ranks[a["tier"]] for a in alerts] == sorted(
        (ranks[a["tier"]] for a in alerts), reverse=True)
    with_fixes = [a for a in alerts if a["fixes"]]
    assert with_fixes
    for alert in with_fixes:
        costs = [D(c["cost"]["value"]) for c in alert["fixes"]]
        assert len(costs) <= 3 and costs == sorted(costs)
        for card in alert["fixes"]:
            assert card["tier"] in ("DRAFT", "EXECUTE") and card["impact"]["id"].startswith("fig_")
            explained = hardware.get(f"/api/explain/{card['impact']['id']}",
                                     params={"tenant_id": "sme_hardware"})
            assert explained.status_code == 200
            assert explained.json()["formula"]["formula_id"] == "cash.lever_gap_reduction"


def test_the_daily_scan_delivers_once_and_then_holds_back_duplicates(cash_app):
    with cash_app.state.session_factory() as session:
        first = scan_tenant(session, "sme_hardware", NOW)
        again = scan_tenant(session, "sme_hardware", NOW + timedelta(hours=1))
        session.commit()
    assert first and again == []
    assert {row.reason_key for row in first} == {"alert.new"}
    assert all(row.channels for row in first)


# ---------------------------------------------------------------- who may ask, and abstaining


def test_each_owner_sees_only_their_own_shop(grocery, hardware):
    assert _band(grocery.get("/api/cash/forecast"))["tenant_id"] == "sme_grocery"
    assert _band(hardware.get("/api/cash/forecast"))["tenant_id"] == "sme_hardware"


@pytest.mark.parametrize("path", ["/api/cash/forecast", "/api/cash/gaps", "/api/cash/alerts"])
def test_a_lender_viewer_without_ledger_access_is_refused(signed_in, path):
    res = signed_in("lender@grocery.test").get(path)
    assert res.status_code == 403 and res.json()["code"] == "forbidden"


def test_a_signed_out_caller_is_refused(cash_app):
    with TestClient(cash_app) as anonymous:
        res = anonymous.get("/api/cash/forecast")
    assert res.status_code == 401 and res.json()["message_key"] == "error.not_authenticated"


def test_too_little_history_abstains_and_says_what_is_missing(signed_in):
    res = signed_in("owner@short.test").get("/api/cash/forecast")
    assert res.status_code == 422
    body = res.json()
    assert (body["code"], body["message_key"]) == ("insufficient_data",
                                                   "abstain.insufficient_data")
    assert body["detail"] == {"missing": "at least 8 weeks of transactions",
                              "history_days": "30"}


def test_no_opening_balance_on_record_abstains_instead_of_assuming_zero(signed_in):
    res = signed_in("owner@none.test").get("/api/cash/alerts")
    assert res.status_code == 422
    assert res.json()["detail"]["missing"] == \
        "the balance the ledger starts from (initial_balance)"


def test_an_abstention_for_another_reason_does_not_blame_the_initial_balance(signed_in,
                                                                             monkeypatch):
    def refuse(*_args, **_kwargs):
        raise NotComputable("facts.no_source_rows")

    monkeypatch.setattr(cash_api, "compute", refuse)
    res = signed_in("owner@grocery.test").get("/api/cash/forecast", params={"seed": 99})
    assert res.status_code == 422
    assert (res.json()["message_key"], res.json()["detail"]) == (
        "facts.no_source_rows", {"missing": "the cash balance at the start of 2026-10-01"})


def test_only_the_owner_may_choose_the_simulation_seed(signed_in, grocery):
    """Known risk R12: every new seed is a fresh simulation recorded as facts."""
    engine_seed = _band(grocery.get("/api/cash/forecast"))
    staff = _band(signed_in("staff@grocery.test").get("/api/cash/forecast", params={"seed": 7}))
    assert staff["seed"] == engine_seed["seed"] == 20261020
    assert _band(grocery.get("/api/cash/forecast", params={"seed": 7}))["seed"] == 7
