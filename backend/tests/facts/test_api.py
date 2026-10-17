from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.facts import caller_role
from app.contracts import Role
from app.facts import FactStore
from app.facts.provenance import compute, record_figure
from tests.facts.helpers import T
from tests.facts.sample import load_sample

SEP_QUERY = {"tenant_id": T, "start": "2026-09-01", "end": "2026-09-30"}


@pytest.fixture
def seeded(client: TestClient) -> TestClient:
    with client.app.state.session_factory() as session:
        load_sample(FactStore(session))
        session.commit()
    return client


def test_get_fact_computes_and_returns_a_typed_fact(seeded: TestClient):
    res = seeded.get("/api/facts/dso", params=SEP_QUERY)
    assert res.status_code == 200
    body = res.json()
    assert (body["metric"], Decimal(body["value"]), body["unit"]) == ("dso", Decimal("25.0"),
                                                                     "days")
    assert body["provenance"]["formula_id"] == "receivables.dso"
    assert body["data_mode"] == "synthetic"


def test_get_fact_is_stable_across_calls(seeded: TestClient):
    first = seeded.get("/api/facts/closing_balance", params=SEP_QUERY).json()
    second = seeded.get("/api/facts/closing_balance", params=SEP_QUERY).json()
    assert first["id"] == second["id"] and Decimal(first["value"]) == Decimal("11250.00")


def test_near_miss_metric_name_is_unknown_not_matched(seeded: TestClient):
    res = seeded.get("/api/facts/DSO", params=SEP_QUERY)
    assert res.status_code == 404
    assert res.json()["code"] == "unknown_metric"


def test_compute_false_only_reads_stored_facts(seeded: TestClient):
    res = seeded.get("/api/facts/cash_in", params={**SEP_QUERY, "compute": "false"})
    assert (res.status_code, res.json()["code"]) == (404, "fact_not_found")
    seeded.get("/api/facts/cash_in", params=SEP_QUERY)
    res = seeded.get("/api/facts/cash_in", params={**SEP_QUERY, "compute": "false"})
    assert Decimal(res.json()["value"]) == Decimal("1500.00")


def test_uncomputable_metric_returns_an_abstention_error(seeded: TestClient):
    res = seeded.get("/api/facts/cash_in", params={**SEP_QUERY, "tenant_id": "nobody"})
    assert res.status_code == 422
    assert res.json()["code"] == "not_computable"
    assert res.json()["message_key"] == "error.not_computable"


def test_reversed_period_is_rejected(seeded: TestClient):
    res = seeded.get("/api/facts/cash_in", params={**SEP_QUERY, "end": "2026-08-01"})
    assert (res.status_code, res.json()["code"]) == (422, "invalid_period")


def test_explain_returns_formula_inputs_and_rows(seeded: TestClient):
    fact_id = seeded.get("/api/facts/gross_margin", params=SEP_QUERY).json()["id"]
    body = seeded.get(f"/api/explain/{fact_id}").json()
    assert body["formula"]["expression"] == "(net_sales - purchases) / net_sales"
    assert [i["metric"] for i in body["inputs"]] == ["net_sales", "purchases"]
    assert "bkash.csv#L3" in body["source_rows"] and body["masked"] is False


def test_explain_a_stored_figure(seeded: TestClient):
    with seeded.app.state.session_factory() as session:
        store = FactStore(session)
        figure = record_figure(store, compute(store, T, "cash_out", load_sample(store)),
                               "cash.cash_out")
        session.commit()
    body = seeded.get(f"/api/explain/{figure.id}").json()
    assert (body["figure_id"], Decimal(body["value"])) == (figure.id, Decimal("650.00"))


def test_explain_masks_rows_for_a_lender(seeded: TestClient):
    fact_id = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()["id"]
    seeded.app.dependency_overrides[caller_role] = lambda: Role.lender_viewer
    try:
        body = seeded.get(f"/api/explain/{fact_id}").json()
    finally:
        seeded.app.dependency_overrides.clear()
    assert body["masked"] is True
    assert all(row.startswith("masked:") for row in body["source_rows"])


def test_explain_unknown_figure_is_404(seeded: TestClient):
    res = seeded.get("/api/explain/fig_missing")
    assert (res.status_code, res.json()["code"]) == (404, "figure_not_found")
