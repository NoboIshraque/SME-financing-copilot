import pytest

from app.contracts import Direction, TxCategory
from app.ingest.categorise import categorise, from_reference, from_text, keyword_span

C = TxCategory
IN, OUT = Direction.inflow, Direction.outflow


@pytest.mark.parametrize(
    ("reference", "direction", "expected"),
    [
        ("SALE-250401", IN, C.sales),
        ("GRO-INV-00135", IN, C.collection),
        ("GRO-INV-00135", OUT, C.supplier_payment),
        ("GRO-BILL-00023", OUT, C.supplier_payment),
        ("SWEEP-CASH-250404", IN, C.transfer),
        ("TOPUP-BKASH-2504-1", OUT, C.transfer),
        ("UTIL-202504", OUT, C.utility),
        ("RENT-202504", OUT, C.rent),
        ("SAL-202504", OUT, C.salary),
        ("BONUS-EID_UL_FITR-2025", OUT, C.salary),
        ("DRAW-202504", OUT, C.owner_draw),
        ("EMI-202504", OUT, C.loan_repayment),
        ("EMI-202504", IN, C.loan_disbursement),
        ("VAT-Q1", OUT, C.tax),
        ("SALE-250401", OUT, None),
        ("INVOICE", IN, None),
    ],
)
def test_reference_prefixes(reference, direction, expected):
    assert from_reference(reference, direction) is expected


@pytest.mark.parametrize(
    ("text", "direction", "expected"),
    [
        ("Own bank account", OUT, C.transfer),
        ("DESCO prepaid meter", OUT, C.utility),
        ("দোকান ভাড়া", OUT, C.rent),
        ("কর্মচারী বেতন", OUT, C.salary),
        ("মাল বিক্রি", IN, C.sales),
        ("baki aday Rahim", IN, C.collection),
        ("kisti BRAC", OUT, C.loan_repayment),
        ("SUPPLIER PAYMENT Bismillah Gas House", OUT, C.supplier_payment),
        ("Rahim Store", IN, None),
        ("Rentu Mia", OUT, None),
    ],
    ids=["own-account", "desco", "bangla-rent", "bangla-salary", "bangla-sale", "banglish-baki",
         "banglish-kisti", "supplier-before-gas", "plain-name", "keyword-inside-a-word"],
)
def test_description_keywords(text, direction, expected):
    assert from_text(text, direction) is expected


def test_evidence_order_column_label_reference_text_default():
    assert categorise(OUT, column="rent", label=C.utility, label_is_strong=True,
                      reference="SAL-1") is C.rent
    assert categorise(OUT, label=C.utility, label_is_strong=True, reference="SAL-1") is C.utility
    assert categorise(OUT, reference="SAL-1", text="DESCO") is C.salary
    assert categorise(OUT, label=C.sales, reference="XYZ", text="DESCO") is C.utility
    assert categorise(IN, label=C.sales, reference="XYZ", text="Rahim") is C.sales
    assert categorise(IN, reference="XYZ", text="Rahim") is C.other


def test_unknown_category_column_value_falls_back_to_other_evidence():
    assert categorise(OUT, column="misc stuff", reference="RENT-1") is C.rent


def test_keyword_span_marks_the_leading_category_words():
    text = "SUPPLIER PAYMENT Sonali House"
    start, end = keyword_span(text)
    assert (start, text[start:end]) == (0, "SUPPLIER PAYMENT")
    assert keyword_span("Sonali House") is None
