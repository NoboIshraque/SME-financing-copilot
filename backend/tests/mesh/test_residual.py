"""Residual gaps after netting, routed through WP-06 (WP-08 milestone 4)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.contracts import EligibilityRule, Money
from app.engines.financing.cost import true_cost
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import propose_rounds
from app.engines.mesh.residual import (
    FORMULA_GAP,
    NO_ELIGIBLE,
    cash_out_by_tenant,
    residual_gaps,
    route_gap,
    route_round,
)
from tests.financing.helpers import product
from tests.mesh.helpers import NOW, ring

FACTS = {"business_age_months": Decimal(36)}
START = NOW.date()
OLD_ONLY = EligibilityRule(id="age", metric="business_age_months", op=">=",
                           threshold=Decimal(60), description_key="rule.business_age")


@pytest.fixture
def round_():
    # The demo ring: garment -> fabric 4.5L, hardware -> garment 3.2L, fabric -> hardware 3.8L.
    obligations = ring(("garment", "fabric", 450000), ("hardware", "garment", 320000),
                       ("fabric", "hardware", 380000))
    return propose_rounds(build_graph(obligations), now=NOW)[0]


def test_netting_leaves_garment_and_fabric_paying_cash(round_):
    out = cash_out_by_tenant(round_)
    assert out == {"garment": Money.of(130000), "fabric": Money.of(60000),
                   "hardware": Money.zero()}


def test_a_gap_is_recorded_only_where_cash_on_hand_falls_short(round_):
    available = {"garment": Money.of(100000), "fabric": Money.of(60000),
                 "hardware": Money.zero()}

    gaps = residual_gaps(round_, available, fact_ids={"garment": "fact-cash-garment"})

    assert [(g.tenant, g.gap) for g in gaps] == [("garment", Money.of(30000))]
    prov = gaps[0].figure.provenance
    assert prov.formula_id == FORMULA_GAP
    assert prov.input_fact_ids == ("fact-cash-garment",)
    assert prov.parameters["cash_out"] == "130000.00"
    assert prov.parameters["available"] == "100000.00"


def test_unknown_cash_counts_as_none_rather_than_assumed(round_):
    gaps = residual_gaps(round_, {})
    assert {g.tenant: g.gap for g in gaps} == {"garment": Money.of(130000),
                                               "fabric": Money.of(60000)}


def test_the_cheapest_eligible_option_wins_even_when_wp06_ranks_another_first(round_):
    gap = residual_gaps(round_, {"garment": Money.of(100000), "fabric": Money.of(60000)})[0]
    cheap_slow = product("refi", kind="refinance_scheme", rate="9")
    fast_dear = product("nano", kind="nano_loan", rate="15")
    products = [fast_dear, cheap_slow]

    routed = route_gap(gap, products, FACTS, start=START, needed_by=START + timedelta(days=2),
                       tenor_days=30)

    costs = {p.id: true_cost(p, gap.gap, 30).total_cost for p in products}
    assert routed.option.product.id == "refi" == min(costs, key=lambda k: costs[k].amount)
    assert routed.total_cost == costs["refi"]
    assert routed.option.rank == 2  # WP-06's balanced score preferred the fast nano loan
    assert "mesh.residual.cheaper_than_top_ranked" in routed.reason_keys
    assert routed.alternatives == 2


def test_ineligible_products_are_never_chosen_however_cheap(round_):
    gap = residual_gaps(round_, {"garment": Money.of(100000), "fabric": Money.of(60000)})[0]
    cheapest_but_ineligible = product("free", kind="refinance_scheme", rate="1", rules=(OLD_ONLY,))
    ok = product("nano", kind="nano_loan", rate="15")

    routed = route_gap(gap, [cheapest_but_ineligible, ok], FACTS, start=START,
                       needed_by=START, tenor_days=30)

    assert routed.option.product.id == "nano" and routed.alternatives == 1


def test_with_nothing_eligible_the_router_abstains(round_):
    gap = residual_gaps(round_, {"garment": Money.of(100000), "fabric": Money.of(60000)})[0]
    routed = route_gap(gap, [product("free", rate="1", rules=(OLD_ONLY,))], FACTS, start=START,
                       needed_by=START, tenor_days=30)
    assert routed.option is None and routed.total_cost is None
    assert routed.reason_keys == (NO_ELIGIBLE,)
    assert routed.figures == (gap.figure,)  # the gap itself is still shown, with provenance


def test_routing_a_round_bridges_each_gap_for_the_tenor_and_by_round_expiry(round_):
    routed = route_round(round_, {"garment": Money.of(100000)}, [product("p", rate="12")],
                         {"garment": FACTS, "fabric": FACTS}, start=START, tenor_days=45)

    assert [(r.gap.tenant, r.gap.gap) for r in routed] == [("fabric", Money.of(60000)),
                                                           ("garment", Money.of(30000))]
    for r in routed:
        cost_fig = next(f for f in r.figures if f.id.endswith(":residual_cost"))
        assert cost_fig.value == true_cost(product("p", rate="12"), r.gap.gap, 45).total_cost.amount
        assert cost_fig.provenance.parameters["tenor_days"] == "45"
        assert cost_fig.data_mode.value == "synthetic"
