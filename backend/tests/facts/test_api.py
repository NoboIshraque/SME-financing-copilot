from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.contracts import Principal, Role
from app.facts import FactStore
from app.facts.provenance import compute, record_figure
from app.security.deps import current_principal
from app.settings import AppEnv
from tests.facts.helpers import T, txn
from tests.facts.sample import LENDER, OWNER, STRANGER, load_sample

SEP_QUERY = {"tenant_id": T, "start": "2026-09-01", "end": "2026-09-30"}


@pytest.fixture
def seeded(client: TestClient) -> TestClient:
    with client.app.state.session_factory() as session:
        load_sample(FactStore(session))
        session.commit()
    _as(client, OWNER)
    return client


def _as(client: TestClient, principal: Principal | None) -> None:
    """Sign in as `principal` (WP-11's current_principal), or sign out with None."""
    if principal is None:
        client.app.dependency_overrides.pop(current_principal, None)
    else:
        client.app.dependency_overrides[current_principal] = lambda: principal


def test_get_fact_computes_and_returns_a_typed_fact(seeded: TestClient):
    res = seeded.get("/api/facts/dso", params=SEP_QUERY)
    assert res.status_code == 200
    body = res.json()
    assert (body["metric"], Decimal(body["value"]), body["unit"]) == ("dso", Decimal("37.5"),
                                                                     "days")
    assert body["provenance"]["formula_id"] == "receivables.dso"
    assert body["data_mode"] == "synthetic"


def test_new_ledger_rows_change_the_next_answer(seeded: TestClient):
    first = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()
    with seeded.app.state.session_factory() as session:
        FactStore(session).add_transactions([txn(70, date(2026, 9, 25), 4000)])
        session.commit()
    second = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()
    assert (Decimal(first["value"]), Decimal(second["value"])) == (Decimal("1500.00"),
                                                                   Decimal("5500.00"))


def test_stored_only_reads_report_staleness_instead_of_an_old_number(seeded: TestClient):
    stored_only = {**SEP_QUERY, "compute": "false"}
    assert seeded.get("/api/facts/cash_in", params=stored_only).json()["code"] == "fact_not_found"
    seeded.get("/api/facts/cash_in", params=SEP_QUERY)
    assert Decimal(seeded.get("/api/facts/cash_in", params=stored_only).json()["value"]) == \
        Decimal("1500.00")
    with seeded.app.state.session_factory() as session:
        FactStore(session).add_transactions([txn(71, date(2026, 9, 26), 1)])
        session.commit()
    res = seeded.get("/api/facts/cash_in", params=stored_only)
    assert (res.status_code, res.json()["code"]) == (409, "fact_stale")


def test_raw_facts_are_read_by_exact_lookup(seeded: TestClient):
    day = {"tenant_id": T, "start": "2026-08-01", "end": "2026-08-01", "granularity": "day"}
    res = seeded.get("/api/facts/initial_balance", params=day)
    assert Decimal(res.json()["value"]) == Decimal("10000.00")


def test_near_miss_metric_name_is_unknown_not_matched(seeded: TestClient):
    res = seeded.get("/api/facts/DSO", params=SEP_QUERY)
    assert (res.status_code, res.json()["code"]) == (404, "unknown_metric")


def test_uncomputable_metric_returns_an_abstention_with_a_reason_key(seeded: TestClient):
    _as(seeded, Principal(user_id="u-nobody", tenant_id="nobody", role=Role.owner))
    res = seeded.get("/api/facts/cash_in", params={"start": "2026-09-01", "end": "2026-09-30"})
    assert res.status_code == 422
    assert res.json()["code"] == "not_computable"
    assert res.json()["detail"]["reason_key"] == "facts.no_source_rows"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"start": "2026-13-01", "end": "2026-09-30"}, "invalid_period"),
        ({"start": "2026-09-30", "end": "2026-09-01"}, "invalid_period"),
        ({"granularity": "fortnight"}, "invalid_period"),
        ({"start": "2026-09-02"}, "unaligned_period"),
        ({"start": "2026-09-01", "end": "2026-09-07", "granularity": "day"}, "unaligned_period"),
        ({"start": "2026-08-01", "end": "2026-10-31", "granularity": "quarter"},
         "unaligned_period"),
    ],
    ids=["bad-date", "end-before-start", "unknown-granularity", "month-not-from-the-1st",
         "day-spanning-a-week", "quarter-not-aligned"],
)
def test_bad_periods_get_an_api_error_body(seeded: TestClient, params, code):
    res = seeded.get("/api/facts/cash_in", params={**SEP_QUERY, **params})
    assert (res.status_code, res.json()["code"]) == (422, code)
    assert set(res.json()) == {"code", "message_key", "detail"}


@pytest.mark.parametrize(
    ("start", "end", "granularity"),
    [("2026-09-01", "2026-09-07", "week"), ("2026-09-03", "2026-09-03", "day"),
     ("2026-07-01", "2026-09-30", "quarter"), ("2026-01-01", "2026-12-31", "year")],
)
def test_aligned_periods_are_accepted(seeded: TestClient, start, end, granularity):
    res = seeded.get("/api/facts/cash_in", params={"tenant_id": T, "start": start, "end": end,
                                                   "granularity": granularity})
    assert res.status_code in (200, 422)
    assert res.json().get("code") in (None, "not_computable")


def test_the_tenant_comes_from_the_signed_in_caller_not_the_query(seeded: TestClient):
    res = seeded.get("/api/facts/cash_in", params={"start": "2026-09-01", "end": "2026-09-30"})
    assert (res.status_code, Decimal(res.json()["value"])) == (200, Decimal("1500.00"))


def test_a_query_naming_another_tenant_is_refused(seeded: TestClient):
    res = seeded.get("/api/facts/cash_in", params={**SEP_QUERY, "tenant_id": "tenant_b"})
    assert (res.status_code, res.json()["code"]) == (403, "forbidden")
    assert res.json()["detail"] == {"reason": "tenant"}


def test_without_a_session_every_route_answers_401(seeded: TestClient):
    fact_id = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()["id"]
    _as(seeded, None)
    for path in ("/api/facts/cash_in", f"/api/explain/{fact_id}", f"/api/explain/{fact_id}/rows"):
        res = seeded.get(path, params=SEP_QUERY)
        assert (res.status_code, res.json()["code"]) == (401, "not_authenticated"), path


def test_facts_mask_source_rows_for_callers_who_may_not_see_them(seeded: TestClient):
    owner_rows = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()
    _as(seeded, LENDER)
    lender_rows = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()
    assert owner_rows["provenance"]["source_row_ids"] == ["txn:tenant_a-T1", "txn:tenant_a-T2"]
    assert all(r.startswith("masked:") for r in lender_rows["provenance"]["source_row_ids"])
    assert lender_rows["value"] == owner_rows["value"]


def test_explain_returns_formula_inputs_and_rows(seeded: TestClient):
    fact_id = seeded.get("/api/facts/gross_margin", params=SEP_QUERY).json()["id"]
    body = seeded.get(f"/api/explain/{fact_id}", params={"tenant_id": T}).json()
    assert body["formula"]["expression"] == "(net_sales - purchases) / net_sales"
    assert [i["metric"] for i in body["inputs"]] == ["net_sales", "purchases"]
    assert "txn:tenant_a-T3" in body["source_rows"] and body["masked"] is False


def test_explain_a_stored_figure(seeded: TestClient):
    with seeded.app.state.session_factory() as session:
        store = FactStore(session)
        figure = record_figure(store, compute(store, T, "cash_out", load_sample(store)),
                               "cash.cash_out")
        session.commit()
    body = seeded.get(f"/api/explain/{figure.id}", params={"tenant_id": T}).json()
    assert (body["figure_id"], Decimal(body["value"])) == (figure.id, Decimal("650.00"))


def test_explain_never_crosses_tenants(seeded: TestClient):
    fact_id = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()["id"]
    _as(seeded, STRANGER)  # signed in, but to tenant_b: another tenant's figure looks unknown
    for path in (f"/api/explain/{fact_id}", f"/api/explain/{fact_id}/rows"):
        res = seeded.get(path)
        assert (res.status_code, res.json()["code"]) == (404, "figure_not_found")


def test_explain_masks_rows_for_a_lender(seeded: TestClient):
    fact_id = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()["id"]
    _as(seeded, LENDER)
    body = seeded.get(f"/api/explain/{fact_id}").json()
    assert body["masked"] is True
    assert all(row.startswith("masked:") for row in body["source_rows"])


def test_rows_endpoint_pages_through_the_original_records(seeded: TestClient):
    fact_id = seeded.get("/api/facts/closing_balance", params=SEP_QUERY).json()["id"]
    page = seeded.get(f"/api/explain/{fact_id}/rows",
                      params={"tenant_id": T, "offset": 1, "limit": 2}).json()
    assert (page["total"], page["offset"], page["limit"], page["masked"]) == (8, 1, 2, False)
    assert [r["kind"] for r in page["rows"]] == ["transaction", "transaction"]
    assert page["rows"][0]["record"]["source_ref"] == "bkash.csv#L7"


@pytest.mark.parametrize(("offset", "limit"), [("-1", "10"), ("0", "0"), ("0", "501"),
                                               ("a", "10")])
def test_rows_endpoint_rejects_bad_pages(seeded: TestClient, offset, limit):
    fact_id = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()["id"]
    res = seeded.get(f"/api/explain/{fact_id}/rows",
                     params={"tenant_id": T, "offset": offset, "limit": limit})
    assert (res.status_code, res.json()["code"]) == (422, "invalid_page")


def test_explain_unknown_figure_is_404_and_long_ids_are_not_echoed_in_full(seeded: TestClient):
    res = seeded.get(f"/api/explain/fig_{'x' * 300}", params={"tenant_id": T})
    assert (res.status_code, res.json()["code"]) == (404, "figure_not_found")
    assert len(res.json()["detail"]["figure_id"]) == 128


def test_in_the_hosted_demo_an_anonymous_caller_gets_no_figures(seeded: TestClient):
    # The old stub handed any caller a lender view of whatever tenant_id the URL named.
    fact_id = seeded.get("/api/facts/cash_in", params=SEP_QUERY).json()["id"]
    settings = seeded.app.state.settings
    seeded.app.state.settings = settings.model_copy(update={"app_env": AppEnv.demo})
    _as(seeded, None)
    try:
        res = seeded.get(f"/api/explain/{fact_id}", params={"tenant_id": T})
    finally:
        seeded.app.state.settings = settings
    assert res.status_code == 401
    assert "value" not in res.json() and "source_rows" not in res.json()
