"""Ledger photo OCR: line reading, confidence, drafts. The OCR engine is replaced by recorded
lines except in the live test, which runs only where Tesseract with Bangla is installed."""

import io
from datetime import date
from decimal import Decimal

import pytest

from app.contracts import DataMode, Direction, SourceFormat, TxCategory
from app.ingest.normalise import NormaliseError
from app.ingest.ocr import (
    OcrLine,
    TesseractEngine,
    drafts_from_photo,
    lines_from_tesseract,
    parse_khata_lines,
    photo_id,
    read_khata_line,
)
from app.ingest.parsers import IngestOptions
from app.ingest.parties import identifiers
from tests.ingest.helpers import RESOLVER, T

TODAY = date(2026, 10, 18)
OPTS = IngestOptions(tenant_id=T, filename="khata.jpg", data_mode=DataMode.real_anonymised)
D = Decimal


@pytest.mark.parametrize(
    ("text", "name", "amount", "day", "payment", "certainty"),
    [
        ("০৫/১০/২০২৬ রহিম চাল ১,২৫০", "রহিম", "1250", date(2026, 10, 5), False, "0.85"),
        ("Karim joma 500/-", "Karim", "500", TODAY, True, "0.75"),
        ("১২ অক্টোবর ২০২৬ জসিম ২০০০ টাকা", "জসিম", "2000", date(2026, 10, 12), False, "1"),
        ("Md Rahim Uddin 3 kg chal 240", "Md Rahim Uddin", "240", TODAY, False, "0.55"),
        ("১৫ বৈশাখ ১৪৩৩ সালাম ভাই ৮৫০", "সালাম ভাই", "850", date(2026, 4, 28), False, "1"),
        ("৳ ১৫০০ রিনা আপা 13/10", "রিনা আপা", "1500", date(2026, 10, 13), False, "0.95"),
        ("শফিক পরিশোধ ৩০০ টাকা ১৭/১০/২০২৬", "শফিক", "300", date(2026, 10, 17), True, "1"),
    ],
    ids=["bangla-date-name-item-amount", "banglish-payment-no-date", "bangla-month-name",
         "quantity-and-price", "bengali-calendar", "taka-sign-and-day-over-12",
         "bangla-payment-word"],
)
def test_khata_lines_are_read(text, name, amount, day, payment, certainty):
    line = read_khata_line(text, TODAY)
    assert (line.name, line.amount, line.day, line.payment) == (name, D(amount), day, payment)
    assert line.certainty == D(certainty)


@pytest.mark.parametrize(
    ("text", "reason"),
    [("মোট ১২,৫০০", "ingest.row.summary"), ("রহিম চাল", "ingest.ocr.no_amount"),
     ("১২/১০ ৫০০", "ingest.ocr.no_name")],
    ids=["total-line", "no-amount", "no-name"],
)
def test_unreadable_lines_carry_a_reason(text, reason):
    with pytest.raises(NormaliseError) as err:
        read_khata_line(text, TODAY)
    assert err.value.reason_key == reason


def _lines(*rows: tuple[str, str]) -> list[OcrLine]:
    return [OcrLine(n, text, D(conf)) for n, (text, conf) in enumerate(rows, start=1)]


def test_drafts_carry_confidence_and_low_ones_are_flagged():
    result = parse_khata_lines(_lines(("১২ অক্টোবর ২০২৬ জসিম ২০০০ টাকা", "0.95"),
                                      ("Karim joma 500/-", "0.95")),
                               OPTS, RESOLVER, photo_id="abc", reference=TODAY)
    assert [(d.row_ref, d.confidence, d.flagged) for d in result.drafts] == [
        ("khata.jpg#line1", D("0.95"), False), ("khata.jpg#line2", D("0.71"), True)]
    assert result.transactions == result.invoices == []  # nothing committed from a photo


def test_credit_lines_become_invoices_and_payment_lines_collections():
    credit, payment = parse_khata_lines(
        _lines(("০৫/১০/২০২৬ রহিম চাল ১,২৫০", "0.9"), ("Karim joma 500/-", "0.9")),
        OPTS, RESOLVER, photo_id="abc", reference=TODAY).drafts
    assert credit.invoice is not None and credit.transaction is None
    assert (credit.invoice.amount.amount, credit.invoice.status.value) == (D("1250.00"), "open")
    assert credit.invoice.id == f"{T}:photo-abc-L1"
    assert payment.transaction is not None and payment.invoice is None
    assert (payment.transaction.direction, payment.transaction.category) == (
        Direction.inflow, TxCategory.collection)


def test_names_become_tokens_and_bad_lines_are_masked():
    result = parse_khata_lines(_lines(("রহিম ১২০০", "0.9"), ("Kamal 01711000001", "0.9"),
                                      ("কিছু একটা", "0.9")),
                               OPTS, RESOLVER, photo_id="abc", reference=TODAY)
    (draft,) = result.drafts[:1]
    assert draft.invoice.counterparty_token == RESOLVER.resolve(T, identifiers("রহিম"))
    assert "রহিম" not in draft.model_dump_json()
    assert [u.reason_key for u in result.unparsed] == ["ingest.ocr.no_amount"]
    assert result.source_format is SourceFormat.ledger_photo
    assert result.data_mode is DataMode.real_anonymised


def test_tesseract_words_are_grouped_into_lines_with_mean_confidence():
    data = {
        "text": ["", "রহিম", "১২০০", "", "Karim", "joma", "500"],
        "conf": ["-1", "90", "80", "-1", "96", "94", "92.5"],
        "page_num": [1] * 7, "block_num": [1, 1, 1, 1, 1, 1, 1], "par_num": [1] * 7,
        "line_num": [0, 1, 1, 0, 2, 2, 2],
    }
    assert lines_from_tesseract(data) == [
        OcrLine(1, "রহিম ১২০০", D("0.8500")), OcrLine(2, "Karim joma 500", D("0.9417"))]


class _FakeEngine:
    def __init__(self, lines):
        self.lines = lines

    def read_lines(self, image: bytes) -> list[OcrLine]:
        return self.lines


def test_photo_drafts_have_ids_tied_to_the_photo():
    photo = b"\x89PNG fake bytes"
    result = drafts_from_photo(photo, OPTS, RESOLVER, _FakeEngine(_lines(("রহিম ১২০০", "0.9"))),
                               TODAY)
    assert result.drafts[0].invoice.id == f"{T}:photo-{photo_id(photo)}-L1"


def test_an_unreadable_photo_is_reported_not_guessed():
    result = drafts_from_photo(b"not an image", OPTS, RESOLVER, TesseractEngine(), TODAY)
    assert [u.reason_key for u in result.unparsed] == ["ingest.photo.unreadable"]
    assert result.drafts == []


@pytest.mark.skipif(not TesseractEngine.available(), reason="Tesseract with ben+eng not installed")
def test_live_ocr_of_a_rendered_ledger_page():
    from PIL import Image, ImageDraw, ImageFont

    page = Image.new("L", (1400, 420), 255)
    draw = ImageDraw.Draw(page)
    font = ImageFont.load_default(size=56)
    for n, text in enumerate(["05/10/2026 Rahim 1250", "Karim joma 500"]):
        draw.text((40, 40 + n * 160), text, fill=0, font=font)
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    result = drafts_from_photo(buffer.getvalue(), OPTS, RESOLVER, TesseractEngine(), TODAY)
    amounts = sorted((d.invoice or d.transaction).amount.amount for d in result.drafts)
    assert amounts == [D("500.00"), D("1250.00")]
