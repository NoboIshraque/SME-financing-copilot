from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts import (
    DataMode,
    FinancingProduct,
    LeverKind,
    MeshObligation,
    Money,
    ProductKind,
    RateType,
    Tier,
    TxCategory,
)
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.calendar import load_festivals
from app.engines.cash.figures import FORMULAS
from app.engines.cash.gaps import find_gaps, shortfall
from app.engines.cash.levers import LeverContext, combine, cover_amount, smoothing_levers
from app.engines.cash.simulate import Scenario, draw, run
from app.engines.financing.catalogue import load_catalogue
from app.engines.financing.cost import true_cost
from tests.cash.helpers import (
    AS_OF,
    T,
    bill,
    daily,
    invoice,
    obligation,
    paid_invoice,
    txn,
)

D = Decimal
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
OCT = {n: date(2026, 10, n) for n in range(1, 32)}
STEADY = [paid_invoice(f"P{n}", date(2026, 8, 1) + timedelta(days=n), 3) for n in range(3)]
FACTS = {"business_age_months": D(74), "trade_licence": D(1)}


def _context(txns=(), invoices=(), bills=(), obligations=(), opening="10000", horizon=30,
             paths=40, **kw):
    base = forecast_baseline(T, AS_OF, D(opening), list(txns), list(invoices), list(bills),
                             list(obligations), [], horizon=horizon)
    draws = draw(base, 5, paths)
    return LeverContext(sim=run(base, draws), draws=draws, now=NOW, **kw)


def _levers(ctx, buffer, which=0):
    gap = find_gaps(ctx.sim, D(buffer))[which]
    return gap, smoothing_levers(ctx, gap)


def _by_kind(levers, kind):
    return [lv for lv in levers if lv.lever.kind is kind]


def _loan(product_id="test-wc", rate="12", speed_kind=ProductKind.working_capital, rules=()):
    return FinancingProduct(id=product_id, provider="Test Bank PLC", name="Test working capital",
                            kind=speed_kind, rate_type=RateType.reducing_balance,
                            nominal_rate_pa=D(rate), rules=rules,
                            source_url="https://example.com/rates", checked_on=date(2026, 10, 1),
                            data_mode=DataMode.public)


# ---------------------------------------------------------------- each lever, hand-computed


def _early_payer_setup():
    """A bill the shop usually pays 5 days early opens a gap that the due date avoids."""
    early = [bill(f"E{n}", date(2026, 5, 1), date(2026, 5, 20) + timedelta(days=n), 500,
                  paid=500, paid_date=date(2026, 5, 15) + timedelta(days=n)) for n in range(3)]
    # issued before the 91-day run-rate window, so no new bills or invoices are projected
    open_bill = bill("B1", date(2026, 6, 30), OCT[20], 8000)  # paid 15 Oct by habit
    collect = invoice("I1", date(2026, 6, 30), OCT[16], 9000)  # STEADY: 3 days late, 19 Oct
    return _context(invoices=[*STEADY, collect], bills=[*early, open_bill])


def test_retiming_a_bill_to_its_due_date_closes_the_gap_it_caused():
    gap, levers = _levers(_early_payer_setup(), 5000)
    assert (gap.first, gap.last, gap.gap.expected_shortfall.amount) == (15, 18, D(3000))
    (lever,) = _by_kind(levers, LeverKind.retime_payable)
    assert lever.lever.gap_reduction.amount == D(3000) and lever.lever.cost.amount == 0
    card = lever.lever.action
    assert (card.tier, card.action_type.value) == (Tier.EXECUTE, "retime_payable")
    assert card.payload["new_date"] == "2026-10-20" == card.payload["due_date"]
    assert card.payload["usual_pay_date"] == "2026-10-15"


def test_a_bill_already_paid_on_its_due_date_cannot_be_retimed_within_terms():
    ctx = _context(bills=[bill("B1", date(2026, 9, 25), OCT[5], 8000)])
    _gap, levers = _levers(ctx, 5000)
    assert _by_kind(levers, LeverKind.retime_payable) == []


def _late_customer_setup(**kw):
    """Rent on 5 Oct leaves Tk 2,000 until a Tk 4,000 invoice arrives on 13 Oct."""
    return _context(invoices=[*STEADY, invoice("I1", date(2026, 9, 25), OCT[10], 4000)],
                    obligations=[obligation(amount=8000, day=5)], **kw)


def test_an_advance_brings_half_an_invoice_forward():
    gap, levers = _levers(_late_customer_setup(), 5000)
    assert (gap.first, gap.last, gap.gap.expected_shortfall.amount) == (5, 12, D(3000))
    (lever,) = _by_kind(levers, LeverKind.request_advance)
    assert (lever.lever.gap_reduction.amount, lever.lever.cost.amount) == (D(2000), D(0))
    assert lever.lever.action.payload["amount"] == "2000.00"
    assert lever.lever.action.payload["by_date"] == "2026-10-02"
    assert lever.lever.action.tier is Tier.EXECUTE


def test_an_early_pay_discount_is_offered_when_no_loan_is_eligible():
    out_of_reach = _loan(rules=())
    out_of_reach = out_of_reach.model_copy(update={"min_amount": Money.of(10**7)})
    gap, levers = _levers(_late_customer_setup(products=[out_of_reach], facts=FACTS), 5000)
    (lever,) = _by_kind(levers, LeverKind.early_pay_discount)
    assert lever.lever.cost.amount == D(80)  # 2% of Tk 4,000
    assert lever.lever.gap_reduction.amount == D(3000)  # Tk 3,920 arrives on 2 Oct
    assert lever.lever.action.payload["reason_key"] == "lever.early_pay.no_eligible_loan"
    assert lever.lever.action.payload["days_early"] == 11


def test_an_early_pay_discount_dearer_than_borrowing_is_not_offered():
    _gap, levers = _levers(_late_customer_setup(products=[_loan()], facts=FACTS), 5000)
    assert _by_kind(levers, LeverKind.early_pay_discount) == []  # 2% for 11 days >> 12% a year


def test_without_a_catalogue_no_discount_is_offered_because_it_cannot_be_compared():
    _gap, levers = _levers(_late_customer_setup(), 5000)
    assert _by_kind(levers, LeverKind.early_pay_discount) == []


def test_staggering_the_buying_week_before_the_trough_closes_a_short_gap():
    flat = daily(date(2026, 3, 1), 214, lambda d: 1000)
    buys = [txn(AS_OF - timedelta(days=n), 1000, "outflow", TxCategory.purchase)
            for n in range(91)]
    ctx = _context(txns=flat + buys,
                   invoices=[*STEADY, invoice("I1", date(2026, 6, 30), OCT[11], 5000)],
                   obligations=[obligation(amount=12000, day=10)], opening="20000", horizon=20)
    gap, levers = _levers(ctx, 10000)
    assert (gap.first, gap.last, gap.gap.expected_shortfall.amount) == (10, 13, D(2000))
    (lever,) = _by_kind(levers, LeverKind.stagger_purchase)
    assert lever.lever.gap_reduction.amount == D(2000) and lever.lever.cost.amount == 0
    payload = lever.lever.action.payload
    assert (payload["from_date"], payload["to_date"], payload["days_later"]) == (
        "2026-10-04", "2026-10-10", 7)


def _ring(amounts=(450000, 320000, 380000)):
    g_f, h_g, f_h = amounts
    return [
        MeshObligation(id="R1", debtor_tenant="sme_g", creditor_tenant=T, amount=Money.of(g_f),
                       due_date=OCT[12], invoice_ref="R1", data_mode=DataMode.synthetic),
        MeshObligation(id="R2", debtor_tenant="sme_h", creditor_tenant="sme_g",
                       amount=Money.of(h_g), due_date=OCT[15], invoice_ref="R2",
                       data_mode=DataMode.synthetic),
        MeshObligation(id="R3", debtor_tenant=T, creditor_tenant="sme_h", amount=Money.of(f_h),
                       due_date=OCT[10], invoice_ref="R3", data_mode=DataMode.synthetic)]


def _ring_setup(mesh, invoice_amount=450000):
    receivable = invoice("R1", date(2026, 8, 28), OCT[12], invoice_amount, party="PARTY_g")
    payable = bill("R3", date(2026, 9, 5), OCT[10], 380000, party="PARTY_h")
    return _context(invoices=[*STEADY, receivable], bills=[payable], opening="400000",
                    mesh=mesh)


def test_netting_clears_the_ring_and_pays_only_the_settlement():
    gap, levers = _levers(_ring_setup(_ring()), 100000)
    (lever,) = _by_kind(levers, LeverKind.netting)
    card = lever.lever.action
    assert (card.tier, card.action_type.value) == (Tier.DRAFT, "propose_netting_round")
    assert (card.payload["you_receive"], card.payload["you_pay"]) == ("130000.00", "60000.00")
    assert lever.scenario.bill_payments == {f"{T}:R3": ()}
    assert set(lever.scenario.invoice_changes) == {f"{T}:R1"}
    assert lever.lever.cost.amount == 0 and lever.lever.gap_reduction.amount > 0
    assert gap.gap.first_breach_day == OCT[10]


def test_netting_is_never_proposed_for_a_debt_the_ledger_does_not_show_open():
    _gap, levers = _levers(_ring_setup(_ring(), invoice_amount=440000), 100000)
    assert _by_kind(levers, LeverKind.netting) == []


def test_a_standby_facility_covers_the_gap_in_19_of_20_paths_and_costs_its_interest():
    product = _loan()
    ctx = _context(obligations=[obligation(amount=8000, day=25)], products=[product],
                   facts=FACTS, horizon=40)
    gap, levers = _levers(ctx, 5000)
    (lever,) = _by_kind(levers, LeverKind.standby_facility)
    assert cover_amount(ctx.sim, gap) == D(3000)
    expected = true_cost(product, Money.of(3000), 90)
    assert lever.lever.cost == expected.total_cost
    card = lever.lever.action
    assert (card.tier, card.action_type.value) == (Tier.DRAFT, "draft_loan_application")
    assert card.payload["draw_on"] == "2026-10-24"  # ready after 21 days, drawn on the eve
    assert lever.lever.gap_reduction.amount == D(3000)


def test_a_standby_loan_that_cannot_pay_out_in_time_is_passed_over_for_one_that_can():
    slow = _loan("slow", rate="4", speed_kind=ProductKind.term_loan)  # 30 days to cash
    fast = _loan("fast", rate="24", speed_kind=ProductKind.mfi_loan)  # 7 days
    ctx = _context(obligations=[obligation(amount=8000, day=12)], products=[slow, fast],
                   facts=FACTS)
    _gap, levers = _levers(ctx, 5000)
    (lever,) = _by_kind(levers, LeverKind.standby_facility)
    assert lever.lever.action.payload["product_id"] == "fast"


# ---------------------------------------------------------------- properties


def _audit_cost(base, scenario):
    """What a scenario costs over its whole life, from its own cash flows (an independent
    check of each lever's claimed cost)."""
    owed_bill = {ob.bill.id: ob.owed for ob in base.open_bills}
    owed_inv = dict(base.open_invoices)
    owed_inv = {inv.id: owed for inv, owed in owed_inv.items()}
    cost = sum((sum((a for _d, a in pays), D(0)) - owed_bill[bid]
                for bid, pays in scenario.bill_payments.items()), D(0))
    cost += sum((owed_inv[iid] - sum((a for _d, a in ch.receipts), D(0)) - ch.remainder
                 for iid, ch in scenario.invoice_changes.items()), D(0))
    return cost - sum((a for _d, a in scenario.flows), D(0))


def _check(ctx, gap, levers):
    for lv in levers:
        after = run(ctx.sim.baseline, ctx.draws, combine(ctx.sim.scenario, lv.scenario))
        _p, left = shortfall(after, gap.buffer, gap.first, gap.last)
        assert gap.gap.expected_shortfall.amount - left == lv.lever.gap_reduction.amount > 0
        assert _audit_cost(ctx.sim.baseline, lv.scenario) == lv.lever.cost.amount


SYNTHETIC = [("sme_grocery", 400000), ("sme_pharmacy", 500000), ("sme_fabric", 1000000),
             ("sme_hardware", 1000000)]


@pytest.mark.parametrize(("sme_id", "buffer"), SYNTHETIC, ids=[s for s, _b in SYNTHETIC])
def test_every_lever_reduces_its_gap_by_exactly_what_it_claims_and_costs_what_it_says(
        universe, sme_id, buffer):
    sme = universe.smes[sme_id]
    base = forecast_baseline(sme.id, universe.as_of, sme.balance_on(universe.as_of).amount,
                             sme.transactions, sme.invoices, sme.bills, sme.obligations,
                             load_festivals())
    draws = draw(base, 9, 300)
    ctx = LeverContext(sim=run(base, draws), draws=draws, now=NOW, products=load_catalogue(),
                       facts=FACTS, mesh=universe.mesh_obligations)
    kinds = set()
    for gap in find_gaps(ctx.sim, D(buffer))[:2]:
        levers = smoothing_levers(ctx, gap)
        _check(ctx, gap, levers)
        kinds |= {lv.lever.kind for lv in levers}
    assert kinds


@settings(max_examples=25, deadline=None)
@given(st.integers(2000, 30000), st.lists(st.integers(500, 9000), min_size=1, max_size=4),
       st.lists(st.integers(-6, 6), min_size=3, max_size=3),
       st.lists(st.integers(1, 25), min_size=1, max_size=3), st.integers(0, 2**31))
def test_levers_on_random_ledgers_keep_their_claims(opening, bills_due, habit, due_days, seed):
    history = [bill(f"H{n}", date(2026, 5, 1), date(2026, 5, 20) + timedelta(days=n), 500,
                    paid=500, paid_date=date(2026, 5, 20) + timedelta(days=n + d))
               for n, d in enumerate(habit)]
    payables = [bill(f"B{n}", date(2026, 9, 25), OCT[1] + timedelta(days=n * 3 + 2), amount)
                for n, amount in enumerate(bills_due)]
    customers = [invoice(f"I{n}", date(2026, 9, 20), OCT[1] + timedelta(days=d), 3000)
                 for n, d in enumerate(due_days)]
    base = forecast_baseline(T, AS_OF, D(opening), [], [*STEADY, *customers],
                             [*history, *payables], [obligation(amount=6000, day=6)], [],
                             horizon=30)
    draws = draw(base, seed, 30)
    ctx = LeverContext(sim=run(base, draws), draws=draws, now=NOW, products=[_loan()],
                       facts=FACTS)
    for gap in find_gaps(ctx.sim, D(5000)):
        _check(ctx, gap, smoothing_levers(ctx, gap))


# ---------------------------------------------------------------- ranking, cards


def test_fixes_are_ranked_cheapest_first_then_by_the_larger_reduction():
    ctx = _late_customer_setup(products=[_loan(rules=()).model_copy(
        update={"min_amount": Money.of(10**7)})], facts=FACTS)
    _gap, levers = _levers(ctx, 5000)
    assert [(lv.lever.kind, lv.lever.cost.amount) for lv in levers] == [
        (LeverKind.request_advance, D(0)), (LeverKind.early_pay_discount, D(80))]


def test_lever_cards_carry_explainable_impact_and_cost_and_expire_at_the_breach():
    gap, levers = _levers(_early_payer_setup(), 5000)
    card = levers[0].lever.action
    assert card.impact.value == levers[0].lever.gap_reduction.amount
    assert card.cost.value == levers[0].lever.cost.amount
    for fig in (card.impact, card.cost, *card.figures):
        assert fig.provenance.formula_id in FORMULAS
        assert fig.provenance.parameters["lever"] == f"retime:{T}:B1"
    assert card.figures[0].label_key == "action.breach_probability_after"
    assert card.expires_at == datetime.combine(gap.gap.first_breach_day, time(0),
                                               ZoneInfo("Asia/Dhaka"))
    again = smoothing_levers(_early_payer_setup(), gap)
    assert [lv.lever.action.id for lv in again] == [lv.lever.action.id for lv in levers]


def test_a_what_if_keeps_its_own_changes_under_every_lever():
    what_if = Scenario(name="what_if", flows=((OCT[3], D(-1000)),), collection_delay_days=1)
    lever = Scenario(name="advance:x", flows=((OCT[2], D(500)),))
    both = combine(what_if, lever)
    assert both.flows == ((OCT[3], D(-1000)), (OCT[2], D(500)))
    assert both.collection_delay_days == 1 and both.name == "what_if+advance:x"
    assert combine(Scenario(), lever).name == "advance:x"
