import random
from decimal import Decimal

import pytest

from app.contracts import EligibilityRule, EligibilityStatus, LicenceStatus, Money, ProductKind
from app.engines.financing.cost import early_pay_discount_cost, true_cost
from app.engines.financing.lenders import LenderEvent, build_profile
from app.engines.financing.nonloan import (
    buyer_early_pay,
    mesh_netting,
    owner_topup,
    supplier_term_extension,
)
from app.engines.financing.ranking import match, score_option
from tests.financing.helpers import START, band, need, product

AGE = EligibilityRule(id="age", metric="business_age_months", op=">=", threshold=Decimal(24),
                      description_key="rule.business_age")
FACTS = {"business_age_months": Decimal(36)}


def ranked_ids(candidates):
    return [c.option.product.id for c in candidates]


def test_score_formula_hand_case():
    # cost 100-2.5x12=70 (x.45) + fit 90 (x.25) + approval 50 (x.15) + speed 100-30=70 (x.10)
    # + lender 60 (x.05) = 31.5 + 22.5 + 7.5 + 7 + 3 = 71.5
    assert score_option(Decimal(12), Decimal("0.1"), Decimal("0.5"), 10, Decimal(60)) == Decimal(
        "71.50")


def test_very_expensive_money_scores_zero_on_cost():
    cheap = score_option(Decimal(40), Decimal(0), Decimal(1), 0, Decimal(100))
    dearer = score_option(Decimal(90), Decimal(0), Decimal(1), 0, Decimal(100))
    assert cheap == dearer == Decimal("55.00")  # cost part is 0 from 40% a year up


def test_cheaper_option_ranks_first_when_all_else_is_equal():
    cands = match(need(), [product("dear", rate="20"), product("cheap", rate="10")], FACTS,
                  start=START)
    assert ranked_ids(cands) == ["cheap", "dear"]
    assert [c.option.rank for c in cands] == [1, 2]


def test_ineligible_options_are_kept_but_always_rank_last():
    cands = match(need(), [product("eligible", rate="40"),
                           product("ineligible", rate="1", rules=(AGE,))],
                  {"business_age_months": Decimal(6)}, start=START)
    assert ranked_ids(cands) == ["eligible", "ineligible"]
    last = cands[-1].option
    assert last.eligibility.status is EligibilityStatus.fail and last.score == Decimal(0)


def test_missing_facts_reduce_approval_and_are_flagged():
    cands = match(need(), [product("p", rules=(AGE,))], {}, start=START)
    option = cands[0].option
    assert option.eligibility.status is EligibilityStatus.not_on_record
    assert "approval.facts_missing" in option.reason_keys
    assert option.approval_likelihood == Decimal("0.27")  # 0.45 x 0.6


def test_collateral_requirement_halves_approval_without_collateral():
    p = product("secured", collateral_required=True)
    without = match(need(), [p], FACTS, start=START)[0].option.approval_likelihood
    with_c = match(need(), [p], {**FACTS, "collateral_available": Decimal(1)},
                   start=START)[0].option.approval_likelihood
    assert (with_c, without) == (Decimal("0.45"), Decimal("0.23"))  # 0.45 x 0.5, rounded


def test_fit_uses_the_forecast():
    # the loan adds ~Tk 82k of cash by day 60, so the dip must outweigh it
    risky = band(p50=200000, buffer=150000, dip=(30, 60, 220000))
    cands = match(need(), [product("p")], FACTS, start=START, band=risky)
    assert cands[0].option.p_buffer_breach > Decimal("0.5")
    assert "fit.no_forecast" not in cands[0].option.reason_keys
    assert "fit.no_forecast" in match(need(), [product("p")], FACTS,
                                      start=START)[0].option.reason_keys


def test_bad_lender_record_lowers_the_score():
    bad = build_profile("prov-p", "Lender", LicenceStatus.licensed,
                        [LenderEvent("prov-p", Decimal(10), Decimal(16), 9, True, True)])
    plain = match(need(), [product("p")], FACTS, start=START)[0].option.score
    marked = match(need(), [product("p")], FACTS, start=START,
                   lenders={"prov-p": bad})[0].option.score
    assert marked < plain


def test_every_option_carries_explainable_figures():
    option = match(need(), [product("p")], FACTS, start=START)[0].option
    labels = {f.label_key for f in option.figures}
    assert labels == {"financing.effective_apr", "financing.total_cost",
                      "financing.p_buffer_breach"}
    assert all(f.provenance.parameters["product_id"] == "p" for f in option.figures)


def test_ranking_ignores_the_order_products_are_listed_in():
    """N16 hook: irrelevant noise (input order) must not change the decision."""
    products = [product(f"p{i}", rate=str(5 + 3 * i), kind=kind)
                for i, kind in enumerate(["working_capital", "nano_loan", "mfi_loan",
                                          "factoring", "term_loan", "leasing"])]
    baseline = ranked_ids(match(need(tenor=180), products, FACTS, start=START))
    rng = random.Random(7)
    for _ in range(10):
        shuffled = products[:]
        rng.shuffle(shuffled)
        assert ranked_ids(match(need(tenor=180), shuffled, FACTS, start=START)) == baseline


def test_non_loan_options_compete_in_the_same_ranking():
    options = [
        product("bank", rate="13"),
        owner_topup(Money.of(500000), "synthetic"),
        supplier_term_extension("SUP1", Money.of(200000), 30, Decimal(1), "synthetic"),
        mesh_netting(Money.of(130000), "synthetic"),
    ]
    cands = match(need(amount=100000, tenor=30), options, FACTS, start=START)
    assert ranked_ids(cands)[0] == "own-owner-topup"
    kinds = {c.option.product.kind for c in cands}
    assert ProductKind.mesh_netting in kinds and ProductKind.supplier_term_extension in kinds


def test_buyer_early_pay_costs_exactly_the_early_pay_discount_rate():
    p = buyer_early_pay("CUST3", Money.of(100000), Decimal(2), 20, "synthetic")
    result = true_cost(p, Money.of(100000), 20)
    assert abs(result.effective_annual_rate - early_pay_discount_cost(Decimal(2), 20)) <= Decimal(
        "0.01")


def test_supplier_extension_fee_shows_up_as_cost():
    p = supplier_term_extension("SUP1", Money.of(200000), 30, Decimal(1), "synthetic")
    result = true_cost(p, Money.of(100000), 30)
    assert result.total_cost == Money.of(1000)
    assert result.effective_annual_rate == Decimal("12.87")  # 1.01^(365/30) - 1 = 12.870%


@pytest.mark.parametrize("days", [0, -5])
def test_buyer_early_pay_needs_positive_days(days):
    with pytest.raises(ValueError):
        buyer_early_pay("C", Money.of(1), Decimal(1), days, "synthetic")
