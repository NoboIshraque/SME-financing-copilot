import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.api.ingest as ingest_api
from app.contracts import Principal, Role
from app.ingest.ocr import TesseractEngine
from app.security.deps import current_principal
from app.settings import AppEnv
from tests.ingest.helpers import T, bkash, csv_bytes

SALES = bkash("A1,01/10/2026 10:00:00,Payment Received,01711000001,100,0,100,SALE-1",
              "A2,02/10/2026 11:00:00,Payment Received,01711000002,250,0,350,SALE-2")
AMBIGUOUS = csv_bytes(["date,party,category,type,amount,channel,ref",
                       "01/02/2026,Rahim,sales,in,500,cash,R1",
                       "03/02/2026,Karim,sales,in,700,cash,R2"])
OWNER = Principal(user_id="u-owner", tenant_id=T, role=Role.owner)
LENDER = Principal(user_id="u-lender", tenant_id=T, role=Role.lender_viewer,
                   expires_at=datetime(2026, 12, 31, tzinfo=UTC))


def _as(client: TestClient, principal: Principal | None) -> None:
    """Sign in as `principal` (WP-11's current_principal), or sign out with None."""
    if principal is None:
        client.app.dependency_overrides.pop(current_principal, None)
    else:
        client.app.dependency_overrides[current_principal] = lambda: principal


@pytest.fixture(autouse=True)
def signed_in_owner(client: TestClient) -> None:
    _as(client, OWNER)


def _preview(client: TestClient, data: bytes = SALES, filename: str = "bkash.csv", **form):
    return client.post("/api/ingest/preview", files={"file": (filename, data, "text/csv")},
                       data={"tenant_id": T, **form})


def _commit(client: TestClient, preview: dict, **extra):
    return client.post("/api/ingest/commit", json={
        "tenant_id": T, "preview_id": preview["preview_id"],
        "file_digest": preview["file_digest"], **extra})


def test_preview_then_commit_then_history(client: TestClient):
    preview = _preview(client).json()
    assert (preview["source_format"], len(preview["transactions"])) == ("bkash_statement", 2)
    assert len(preview["file_digest"]) == 64
    committed = _commit(client, preview)
    assert committed.status_code == 200
    assert (committed.json()["transactions"], committed.json()["duplicates_skipped"]) == (2, 0)
    (item,) = client.get("/api/ingest/history", params={"tenant_id": T}).json()
    assert (item["preview_id"], item["filename"], item["transactions"]) == (
        preview["preview_id"], "bkash.csv", 2)


def test_commit_with_another_files_digest_is_refused(client: TestClient):
    preview = _preview(client).json()
    res = _commit(client, {**preview, "file_digest": "0" * 64})
    assert (res.status_code, res.json()["code"]) == (409, "digest_mismatch")
    assert client.get("/api/ingest/history", params={"tenant_id": T}).json() == []


def test_drafts_need_explicit_confirmation(client: TestClient):
    preview = _preview(client, AMBIGUOUS, "book.csv").json()
    assert [d["row_ref"] for d in preview["drafts"]] == ["book.csv#L2", "book.csv#L3"]
    res = _commit(client, preview, confirm=["book.csv#L2"], amounts={"book.csv#L2": "520"})
    assert (res.json()["transactions"], res.json()["drafts_confirmed"]) == (1, 1)


def test_the_tenant_comes_from_the_signed_in_caller(client: TestClient):
    res = client.post("/api/ingest/preview", files={"file": ("b.csv", SALES, "text/csv")})
    assert (res.status_code, res.json()["tenant_id"]) == (200, T)


def test_a_form_naming_another_tenant_is_refused(client: TestClient):
    res = _preview(client, tenant_id="tenant_b")
    assert (res.status_code, res.json()["code"], res.json()["detail"]) == (
        403, "forbidden", {"reason": "tenant"})


def test_without_a_session_ingest_answers_401(client: TestClient):
    preview = _preview(client).json()
    _as(client, None)
    responses = [
        _preview(client),
        client.post("/api/ingest/columns", files={"file": ("b.csv", SALES, "text/csv")}),
        _commit(client, preview),
        client.get("/api/ingest/history"),
    ]
    assert [(r.status_code, r.json()["code"]) for r in responses] == [
        (401, "not_authenticated")] * 4


@pytest.mark.parametrize(
    "form",
    [{"mapping": "{not json"}, {"mapping": '["when"]'}, {"document_kind": "receipt"},
     {"default_channel": "barter"}],
    ids=["mapping-not-json", "mapping-not-an-object", "unknown-document-kind",
         "unknown-channel"],
)
def test_bad_options_are_refused(client: TestClient, form):
    res = _preview(client, **form)
    assert (res.status_code, res.json()["code"]) == (422, "invalid_options")


def test_oversized_upload_is_refused(client: TestClient, monkeypatch):
    monkeypatch.setattr(ingest_api, "MAX_UPLOAD_BYTES", 64)
    res = _preview(client)
    assert (res.status_code, res.json()["code"]) == (413, "file_too_large")


def test_photo_without_local_ocr_is_a_clear_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(TesseractEngine, "available", staticmethod(lambda lang="ben+eng": False))
    res = client.post("/api/ingest/preview",
                      files={"file": ("khata.png", b"\x89PNG\r\n\x1a\nxx", "image/png")},
                      data={"tenant_id": T})
    assert (res.status_code, res.json()["code"]) == (503, "ocr_unavailable")


def test_a_lender_viewer_may_not_commit_to_the_ledger(client: TestClient):
    preview = _preview(client).json()
    _as(client, LENDER)
    res = _commit(client, preview)
    assert (res.status_code, res.json()["code"]) == (403, "not_permitted")


def test_a_signed_in_owner_can_commit_in_the_hosted_demo(client: TestClient):
    # The old stub refused every commit outside development, so the demo could not import.
    settings = client.app.state.settings
    client.app.state.settings = settings.model_copy(update={"app_env": AppEnv.demo})
    try:
        preview = _preview(client).json()
        res = _commit(client, preview)
    finally:
        client.app.state.settings = settings
    assert (res.status_code, res.json()["transactions"]) == (200, 2)


def test_columns_offer_the_mapping_step_with_masked_values(client: TestClient):
    data = csv_bytes(["Tarikh,Naam,Phone,Joma,Khoroch", "15/10/2026,Rahim,01711000001,500,"])
    res = client.post("/api/ingest/columns", files={"file": ("export.csv", data, "text/csv")},
                      data={"tenant_id": T})
    body = res.json()
    assert body["rows"][0] == ["Tarikh", "Naam", "Phone", "Joma", "Khoroch"]
    assert "01711000001" not in body["rows"][1]
    assert body["suggested"] == {"when": "Tarikh", "credit": "Joma", "debit": "Khoroch",
                                 "phone": "Phone"}
    mapping = {"when": "Tarikh", "counterparty": "Naam", "credit": "Joma", "debit": "Khoroch"}
    preview = _preview(client, data, "export.csv", mapping=json.dumps(mapping))
    assert Decimal(preview.json()["transactions"][0]["amount"]["amount"]) == Decimal("500.00")


def test_history_limit_is_validated(client: TestClient):
    res = client.get("/api/ingest/history", params={"tenant_id": T, "limit": "0"})
    assert (res.status_code, res.json()["code"]) == (422, "invalid_limit")


def test_a_lender_viewer_may_not_list_uploads(client: TestClient):
    _as(client, LENDER)  # consented scopes are passport and reports only, not ledger:read
    res = client.get("/api/ingest/history")
    assert (res.status_code, res.json()["code"]) == (403, "forbidden")
