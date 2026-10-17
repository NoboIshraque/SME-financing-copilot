from datetime import UTC, date, datetime, timedelta

import pytest

from app.contracts import DataMode
from app.reports.sharing import ShareLedger, SharingError
from app.reports.state_adapter import (
    ConsentRequiredError,
    MockStateAdapter,
    StateField,
)

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


@pytest.fixture
def ledger():
    return ShareLedger()


def share(ledger, scopes=("passport:read",), ttl=timedelta(days=7)):
    return ledger.grant(tenant_id="sme_fabric", passport_id="pp-1", lender_label="Lender 1",
                        scopes=scopes, ttl=ttl, now=NOW)


def test_a_valid_link_opens_within_scope_and_is_logged(ledger):
    grant, token = share(ledger)
    assert ledger.access(token, "passport:read", now=NOW + timedelta(days=1)) == grant
    assert [r.allowed for r in ledger.views(grant.id)] == [True]


def test_tokens_are_not_stored_in_clear(ledger):
    _, token = share(ledger)
    assert token not in ledger.token_hashes and len(token) >= 40


def test_expired_link_is_denied_and_logged(ledger):
    grant, token = share(ledger, ttl=timedelta(hours=1))
    with pytest.raises(SharingError, match="expired"):
        ledger.access(token, "passport:read", now=NOW + timedelta(hours=1))
    assert ledger.views(grant.id)[-1].reason == "expired"


def test_scope_is_enforced(ledger):
    _, token = share(ledger, scopes=("passport:read",))
    with pytest.raises(SharingError, match="out of scope"):
        ledger.access(token, "report:read", now=NOW)


def test_revoked_link_is_denied(ledger):
    grant, token = share(ledger)
    ledger.revoke(grant.id)
    with pytest.raises(SharingError, match="revoked"):
        ledger.access(token, "passport:read", now=NOW)


def test_unknown_token_is_denied_and_logged(ledger):
    with pytest.raises(SharingError, match="invalid"):
        ledger.access("guess", "passport:read", now=NOW)
    assert ledger.log[-1].allowed is False


@pytest.mark.parametrize(("scopes", "ttl"), [
    (("everything",), timedelta(days=1)),
    (("passport:read",), timedelta(days=31)),
    (("passport:read",), timedelta(0)),
])
def test_grants_are_narrow_and_short(ledger, scopes, ttl):
    with pytest.raises(SharingError):
        share(ledger, scopes=scopes, ttl=ttl)


def test_state_adapter_mock_needs_consent_and_labels_its_data():
    adapter = MockStateAdapter({"sme_fabric": {StateField.tax_registration: "registered"}},
                               as_of=date(2026, 10, 1))
    with pytest.raises(ConsentRequiredError):
        adapter.fetch("sme_fabric", [StateField.tax_registration], consent_id="")
    records = adapter.fetch("sme_fabric", [StateField.tax_registration, StateField.court_records],
                            consent_id="consent-1")
    assert [r.value for r in records] == ["registered", "not_on_record"]
    assert all(r.data_mode is DataMode.synthetic and r.source == "mock" for r in records)
