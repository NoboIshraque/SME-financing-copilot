import re
from decimal import Decimal

import pytest

from app.contracts import DataMode, Direction, DocumentStatus, Money, TxCategory
from app.contracts.party import TOKEN_PATTERN
from app.synthetic import party_token
from app.synthetic.universe import SME_IDS


def test_all_five_smes_load_with_typed_records(universe):
    assert set(universe.smes) == set(SME_IDS)
    for sme in universe.smes.values():
        assert sme.transactions and sme.invoices and sme.bills and sme.obligations
        assert all(t.data_mode is DataMode.synthetic for t in sme.transactions)


def test_transactions_are_in_time_order_and_inside_the_period(universe):
    for sme in universe.smes.values():
        times = [t.occurred_at for t in sme.transactions]
        assert times == sorted(times)
        assert universe.start <= times[0].date() and times[-1].date() <= universe.as_of


def test_party_tokens_are_deterministic_and_reveal_no_names(universe):
    assert party_token("sme_grocery", "Rahim Hossain") == party_token(
        "sme_grocery", "Rahim Hossain")
    assert party_token("sme_grocery", "Rahim Hossain") != party_token(
        "sme_pharmacy", "Rahim Hossain")
    for sme in universe.smes.values():
        for party in sme.parties:
            assert re.match(TOKEN_PATTERN, party.token)
            assert re.fullmatch(r"[A-Z][a-z ]+ \d+", party.display_label)


def test_mesh_peers_are_marked_as_tenants(universe):
    fabric = universe.smes["sme_fabric"]
    assert sum(1 for p in fabric.parties if p.is_tenant) == 2  # garment and hardware


def test_mesh_obligations_load_as_contracts(universe):
    total = sum((o.amount for o in universe.mesh_obligations), Money.zero())
    assert total == Money.of(1_150_000)


@pytest.mark.parametrize("sme_id", SME_IDS)
def test_balance_on_as_of_matches_signed_sum(universe, sme_id):
    sme = universe.smes[sme_id]
    expected = sme.opening_total.amount + sum(
        (t.amount.amount if t.direction is Direction.inflow else -t.amount.amount)
        for t in sme.transactions
    )
    assert sme.balance_on(universe.as_of).amount == expected


def test_collections_point_at_their_invoice(universe):
    sme = universe.smes["sme_hardware"]
    invoice_ids = {i.id for i in sme.invoices}
    collections = [t for t in sme.transactions if t.category is TxCategory.collection]
    assert collections and all(t.invoice_id in invoice_ids for t in collections)


def test_open_receivables_exist_on_as_of_for_forecasting(universe):
    open_amount = sum(
        (i.outstanding.amount for i in universe.smes["sme_fabric"].invoices
         if i.status is DocumentStatus.open),
        Decimal(0),
    )
    assert open_amount > Decimal(500_000)
