from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.contracts import EligibilityStatus, Money, ProductKind, RateBasis
from app.engines.financing.catalogue import (
    CATALOGUE_DIR,
    CatalogueError,
    load_catalogue,
    load_file,
    load_unpriced,
)
from app.engines.financing.ranking import match
from tests.financing.helpers import START, need

BD = load_catalogue()
CN = load_catalogue(jurisdiction="cn")
UNPRICED = load_unpriced()
RAW = yaml.safe_load((CATALOGUE_DIR / "bd.yaml").read_text(encoding="utf-8"))
REG = {f["id"]: f for f in yaml.safe_load(
    (CATALOGUE_DIR / "bd_regulatory.yaml").read_text(encoding="utf-8"))["facts"]}


@pytest.mark.parametrize("product", BD, ids=lambda p: p.id)
def test_every_bangladesh_product_is_sourced_and_dated(product):
    assert product.source_url.startswith("https://")
    assert product.checked_on == date(2026, 10, 18)
    assert not product.is_modelled and product.rate_basis is not RateBasis.modelled


@pytest.mark.parametrize("row", RAW["products"], ids=lambda r: r["id"])
def test_every_priced_row_quotes_its_evidence(row):
    assert len(row["evidence_quote"]) >= 10
    assert row["rate_basis"] in {b.value for b in RateBasis}


def test_unpriced_products_are_listed_but_never_ranked():
    assert {u.kind for u in UNPRICED} >= {"factoring", "invoice_discounting", "nano_loan"}
    assert all(u.source_url.startswith("https://") for u in UNPRICED)
    assert not ({u.id for u in UNPRICED} & {p.id for p in BD})


def test_refinance_rates_never_exceed_their_scheme_caps():
    caps = {"bd-bb-cmsme-wc-refinance-2026": 9, "bd-bb-cmsme-prefinance-25000cr": 7,
            "bd-bb-women-refinance": 5, "bd-bb-startup-fund": 4}
    by_id = {p.id: p for p in BD}
    for pid, cap in caps.items():
        assert by_id[pid].nominal_rate_pa <= cap


def test_microfinance_respects_the_mra_cap():
    assert "24 percent" in REG["mra_cap"]["quote"]
    for p in BD:
        if p.kind is ProductKind.mfi_loan:
            assert p.nominal_rate_pa <= 24


def test_nano_loans_respect_the_e_loan_ceiling():
    assert "50,000" in REG["eloan_rule"]["quote"]
    for p in BD:
        if p.kind is ProductKind.nano_loan:
            assert p.max_amount <= Money.of(50000)


def test_china_pack_is_entirely_modelled():
    assert CN and all(p.is_modelled and p.rate_basis is RateBasis.modelled for p in CN)


def test_no_product_id_repeats_across_catalogues():
    ids = [p.id for p in BD + CN] + [u.id for u in UNPRICED]
    assert len(ids) == len(set(ids))


def test_loader_rejects_unknown_fields(tmp_path: Path):
    path = tmp_path / "x.yaml"
    path.write_text(yaml.safe_dump({"products": [{**RAW["products"][0], "teaser_rate": 1}]}))
    with pytest.raises(CatalogueError, match="unknown fields"):
        load_file(path)


def test_loader_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "x.yaml"
    path.write_text(yaml.safe_dump({"products": [RAW["products"][0], RAW["products"][0]]}))
    with pytest.raises(CatalogueError, match="duplicate"):
        load_file(path)


def test_missing_jurisdiction_is_an_error():
    with pytest.raises(CatalogueError):
        load_catalogue(jurisdiction="xx")


GROCERY_FACTS = {"business_age_months": Decimal(74), "trade_licence": Decimal(1),
                 "bkash_account_active": Decimal(1)}


def test_end_to_end_ranking_for_a_dhaka_grocery_needing_two_lakh():
    ranked = match(need(amount=200000, tenor=180), BD, GROCERY_FACTS, start=START)
    options = [c.option for c in ranked]
    assert len(options) == len(BD)
    statuses = [o.eligibility.status for o in options]
    # everything that cannot work sits at the bottom
    first_fail = statuses.index(EligibilityStatus.fail)
    assert all(s is EligibilityStatus.fail for s in statuses[first_fail:])
    by_id = {o.product.id: o for o in options}
    assert by_id["bd-citybank-bkash-loan"].eligibility.status is EligibilityStatus.fail  # > 50k
    # women-only schemes are never assumed: the fact is not on record
    assert by_id["bd-bb-women-refinance"].eligibility.status is EligibilityStatus.not_on_record
    # the cheapest product that passes outright is a refinance scheme, and it costs far less
    # than microfinance at the MRA cap
    passing = [o for o in options if o.eligibility.status is EligibilityStatus.pass_]
    assert by_id["bd-pksf-microenterprise"].effective_apr > 3 * min(o.effective_apr
                                                                     for o in passing)


def test_a_cheap_refinance_scheme_outranks_microfinance_at_the_mra_cap():
    ranked = [c.option.product.id for c in match(need(amount=200000, tenor=180), BD,
                                                  GROCERY_FACTS, start=START)]
    assert ranked.index("bd-bb-startup-fund") < ranked.index("bd-pksf-microenterprise")
    assert ranked[0] == "bd-bb-startup-fund"
