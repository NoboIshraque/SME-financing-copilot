"""Preview -> commit: exactly the previewed file, drafts only when confirmed, no duplicates."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import DataMode
from app.facts import FactStore
from app.ingest.ocr import OcrLine
from app.ingest.parsers import IngestOptions
from app.ingest.preview import (
    MAX_UPLOAD_BYTES,
    IngestError,
    IngestService,
    derive_key,
    keyed_digest,
)
from app.synthetic.universe import UNIVERSE_DIR
from tests.ingest.helpers import T, bank, bkash, csv_bytes

SECRET = "test-secret-0123456789abcdef0123"
TODAY = date(2026, 10, 18)
SALES = bkash("A1,01/10/2026 10:00:00,Payment Received,01711000001,100,0,100,SALE-1",
              "A2,02/10/2026 11:00:00,Payment Received,01711000002,250,0,350,SALE-2")
AMBIGUOUS = csv_bytes(["date,party,category,type,amount,channel,ref",
                       "01/02/2026,Rahim,sales,in,500,cash,R1",
                       "03/02/2026,Karim,sales,in,700,cash,R2"])


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(session, clock) -> IngestService:
    return IngestService(session, SECRET, now=clock)


def _opts(filename: str = "bkash.csv", tenant: str = T, **extra) -> IngestOptions:
    return IngestOptions(tenant_id=tenant, filename=filename, **extra)


def _ledger(service: IngestService, tenant: str = T):
    return FactStore(service.session).transactions(tenant)


def test_preview_touches_nothing_in_the_ledger(service):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    assert len(preview.transactions) == 2
    assert _ledger(service) == []


def test_commit_with_the_matching_digest_writes_exactly_the_preview(service):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    result = service.commit(T, preview.preview_id, preview.file_digest)
    assert (result.transactions, result.duplicates_skipped) == (2, 0)
    assert _ledger(service) == list(preview.transactions)
    (entry,) = service.history(T)
    assert (entry.preview_id, entry.filename, entry.transactions) == (
        preview.preview_id, "bkash.csv", 2)


def test_a_different_file_digest_is_refused(service):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    other = keyed_digest(derive_key(SECRET, "hishab/ingest/digest/v1"), T, SALES + b"\n")
    with pytest.raises(IngestError) as err:
        service.commit(T, preview.preview_id, other)
    assert (err.value.code, err.value.status) == ("digest_mismatch", 409)
    assert _ledger(service) == []


def test_the_digest_is_keyed_and_bound_to_the_tenant(service):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    key = derive_key(SECRET, "hishab/ingest/digest/v1")
    assert preview.file_digest == keyed_digest(key, T, SALES)
    assert preview.file_digest != keyed_digest(key, "tenant_b", SALES)
    assert preview.file_digest != keyed_digest(derive_key("another-secret-0123456789abcdef",
                                                          "hishab/ingest/digest/v1"), T, SALES)


def test_another_tenant_cannot_commit_the_preview(service):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    with pytest.raises(IngestError) as err:
        service.commit("tenant_b", preview.preview_id, preview.file_digest)
    assert err.value.code == "preview_not_found"


def test_a_preview_commits_once(service):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    service.commit(T, preview.preview_id, preview.file_digest)
    with pytest.raises(IngestError) as err:
        service.commit(T, preview.preview_id, preview.file_digest)
    assert err.value.code == "already_committed"


def test_an_old_preview_expires(service, clock):
    preview = service.preview(SALES, _opts(), reference=TODAY)
    clock.now += timedelta(hours=25)
    with pytest.raises(IngestError) as err:
        service.commit(T, preview.preview_id, preview.file_digest)
    assert (err.value.code, err.value.status) == ("preview_expired", 410)


def test_drafts_are_committed_only_when_confirmed(service):
    preview = service.preview(AMBIGUOUS, _opts("book.csv"), reference=TODAY)
    assert [d.row_ref for d in preview.drafts] == ["book.csv#L2", "book.csv#L3"]
    assert preview.transactions == ()
    result = service.commit(T, preview.preview_id, preview.file_digest, confirm=["book.csv#L3"])
    assert (result.transactions, result.drafts_confirmed) == (1, 1)
    assert [t.source_ref for t in _ledger(service)] == ["book.csv#L3"]


def test_without_confirmation_no_draft_is_committed(service):
    preview = service.preview(AMBIGUOUS, _opts("book.csv"), reference=TODAY)
    result = service.commit(T, preview.preview_id, preview.file_digest)
    assert (result.transactions, result.drafts_confirmed) == (0, 0)
    assert _ledger(service) == []


@pytest.mark.parametrize(
    ("confirm", "amounts"),
    [(["book.csv#L9"], None), ([], {"book.csv#L2": "600"})],
    ids=["unknown-row", "correction-without-confirmation"],
)
def test_confirmations_must_name_drafts_of_this_preview(service, confirm, amounts):
    preview = service.preview(AMBIGUOUS, _opts("book.csv"), reference=TODAY)
    with pytest.raises(IngestError) as err:
        service.commit(T, preview.preview_id, preview.file_digest, confirm=confirm,
                       amounts=amounts)
    assert err.value.code == "unknown_draft"
    assert _ledger(service) == []


def test_the_owner_can_correct_a_drafts_amount(service):
    preview = service.preview(AMBIGUOUS, _opts("book.csv"), reference=TODAY)
    service.commit(T, preview.preview_id, preview.file_digest, confirm=["book.csv#L2"],
                   amounts={"book.csv#L2": "৫৫০"})
    assert [t.amount.amount for t in _ledger(service)] == [Decimal("550.00")]


def test_a_correction_must_be_a_real_amount(service):
    preview = service.preview(AMBIGUOUS, _opts("book.csv"), reference=TODAY)
    with pytest.raises(IngestError) as err:
        service.commit(T, preview.preview_id, preview.file_digest, confirm=["book.csv#L2"],
                       amounts={"book.csv#L2": "-5"})
    assert err.value.code == "invalid_amount"


def test_uploading_the_same_statement_again_adds_nothing(service):
    first = service.preview(SALES, _opts(), reference=TODAY)
    service.commit(T, first.preview_id, first.file_digest)
    again = service.preview(SALES, _opts(), reference=TODAY)
    assert (again.transactions, again.duplicates_skipped) == ((), 2)


def test_commit_rechecks_duplicates_against_the_ledger_as_it_is_now(service):
    first = service.preview(SALES, _opts(), reference=TODAY)
    second = service.preview(SALES, _opts(), reference=TODAY)  # previewed before any commit
    service.commit(T, first.preview_id, first.file_digest)
    result = service.commit(T, second.preview_id, second.file_digest)
    assert (result.transactions, result.duplicates_skipped) == (0, 2)
    assert len(_ledger(service)) == 2


def test_party_links_learnt_from_a_register_carry_to_later_uploads(service):
    register = csv_bytes(["number,party,phone,issue_date,due_date,amount,amount_paid,status",
                          "INV-1,Green Traders,01830296422,2026-09-01,2026-09-10,900,0,open"])
    reg = service.preview(register, _opts("baki.csv"), reference=TODAY)
    service.commit(T, reg.preview_id, reg.file_digest)
    statement = service.preview(bank("02-Oct-2026,COLLECTION Green Traders,R,,900.00,900"),
                                _opts("bank.csv"), reference=TODAY)
    assert statement.transactions[0].counterparty_token == reg.invoices[0].counterparty_token


def test_oversized_uploads_are_refused(service):
    with pytest.raises(IngestError) as err:
        service.preview(b"x" * (MAX_UPLOAD_BYTES + 1), _opts(), reference=TODAY)
    assert (err.value.code, err.value.status) == ("file_too_large", 413)


class _Engine:
    def read_lines(self, image: bytes) -> list[OcrLine]:
        return [OcrLine(1, "রহিম চাল ১২০০ টাকা", Decimal("0.93"))]


def test_photos_need_ocr_and_become_drafts(service):
    photo = b"\x89PNG\r\n\x1a\n" + b"pixels"
    with pytest.raises(IngestError) as err:
        service.preview(photo, _opts("khata.png"), reference=TODAY)
    assert (err.value.code, err.value.status) == ("ocr_unavailable", 503)
    preview = service.preview(photo, _opts("khata.png"), reference=TODAY, engine=_Engine())
    assert preview.source_format.value == "ledger_photo"
    assert [d.invoice.amount.amount for d in preview.drafts] == [Decimal("1200.00")]


def test_synthetic_uploads_stay_labelled_synthetic(service):
    data = (UNIVERSE_DIR / "sme_garment" / "bank_statement.csv").read_bytes()
    preview = service.preview(data, _opts("bank_statement.csv", tenant="sme_garment",
                                          data_mode=DataMode.live), reference=TODAY)
    assert preview.data_mode is DataMode.synthetic
    service.commit("sme_garment", preview.preview_id, preview.file_digest)
    assert service.history("sme_garment")[0].data_mode is DataMode.synthetic
