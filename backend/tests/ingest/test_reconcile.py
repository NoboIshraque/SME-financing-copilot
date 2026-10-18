"""Every synthetic export file parses back to exactly the typed ground truth.

The WP-00 universe ships each shop's records twice: as the raw files a shop would export
(bKash, Nagad, bank statement, cash book, registers) and as typed truth. Parsing the raw files
must recover the truth: same moments (at the precision the format keeps), amounts, directions,
references and categories, with no row rejected.
"""

from collections import Counter

import pytest

from app.synthetic.universe import SME_IDS, UNIVERSE_DIR
from tests.ingest.helpers import parse

EXPORTS = {
    # file -> (channels it covers, timestamp precision as isoformat length, keeps references)
    "bkash_statement.csv": ({"bkash"}, 19, True),
    "nagad_statement.csv": ({"nagad"}, 16, False),
    "bank_statement.csv": ({"bank"}, 10, True),
    "cash_book.csv": ({"cash", "card"}, 10, True),
}


def _key(at, amount, direction, reference, category, precision, keep_ref):
    return (at.replace(tzinfo=None).isoformat(sep=" ")[:precision], amount, direction,
            reference if keep_ref else "", category)


@pytest.mark.parametrize("sme", SME_IDS)
@pytest.mark.parametrize("filename", list(EXPORTS))
def test_export_file_reconciles_with_ground_truth(universe, sme, filename):
    channels, precision, keep_ref = EXPORTS[filename]
    result = parse((UNIVERSE_DIR / sme / filename).read_bytes(), filename, tenant=sme)
    truth = [t for t in universe.smes[sme].transactions if t.channel.value in channels]
    want = Counter(_key(t.occurred_at, t.amount.amount, t.direction, t.reference or "",
                        t.category, precision, keep_ref) for t in truth)
    got = Counter(_key(t.occurred_at, t.amount.amount, t.direction, t.reference or "",
                       t.category, precision, keep_ref) for t in result.transactions)
    assert result.unparsed == []
    assert got == want
    if truth:
        assert result.data_mode.value == "synthetic"


@pytest.mark.parametrize("sme", SME_IDS)
def test_typed_truth_file_round_trips_through_the_ledger_parser(universe, sme):
    result = parse((UNIVERSE_DIR / sme / "transactions_truth.csv").read_bytes(),
                   "transactions_truth.csv", tenant=sme)
    strip = {"id", "counterparty_token"}
    got = [t.model_dump(exclude=strip) for t in result.transactions]
    want = [t.model_dump(exclude=strip) for t in universe.smes[sme].transactions]
    assert result.source_format.value == "ledger_csv"
    assert got == want


@pytest.mark.parametrize("sme", SME_IDS)
def test_registers_parse_to_the_same_invoices_and_bills(universe, sme):
    invoices = parse((UNIVERSE_DIR / sme / "baki_register.csv").read_bytes(),
                     "baki_register.csv", tenant=sme)
    bills = parse((UNIVERSE_DIR / sme / "bills_register.csv").read_bytes(), "bills_register.csv",
                  tenant=sme)
    strip = {"counterparty_token"}
    assert [d.model_dump(exclude=strip) for d in invoices.invoices] == [
        d.model_dump(exclude=strip) for d in universe.smes[sme].invoices]
    assert [d.model_dump(exclude=strip) for d in bills.bills] == [
        d.model_dump(exclude=strip) for d in universe.smes[sme].bills]
    assert invoices.unparsed == bills.unparsed == []


def test_same_customer_gets_one_token_across_register_and_wallet_statement(universe):
    """A customer's phone in the bKash statement and in the baki register maps to one party."""
    sme = "sme_grocery"
    register = parse((UNIVERSE_DIR / sme / "baki_register.csv").read_bytes(), "baki_register.csv")
    wallet = parse((UNIVERSE_DIR / sme / "bkash_statement.csv").read_bytes(), "bkash.csv")
    collections = {t.reference: t.counterparty_token for t in wallet.transactions
                   if t.category.value == "collection"}
    by_number = {d.id.split(":", 1)[1]: d.counterparty_token for d in register.invoices}
    linked = [ref for ref in collections if ref in by_number]
    assert len(linked) > 100
    assert all(collections[ref] == by_number[ref] for ref in linked)
