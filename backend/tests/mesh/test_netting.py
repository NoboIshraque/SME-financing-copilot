from datetime import timedelta
from decimal import Decimal

import networkx as nx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import Money, RoundStatus
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import positions_after, propose_rounds
from tests.mesh.helpers import NOW, ring


def one_round(obligations, **kw):
    rounds = propose_rounds(build_graph(obligations), now=NOW, **kw)
    assert len(rounds) == 1
    return rounds[0]


def flows(round_):
    return {(s.payer_tenant, s.payee_tenant): s.amount.amount for s in round_.settlements}


HAND_CASES = [
    # name, edges, along-debts settlements, new-links net total
    ("equal 3-ring cancels fully", [("a", "b", 100), ("b", "c", 100), ("c", "a", 100)], {}, 0),
    ("two-party mutual debt", [("a", "b", 100), ("b", "a", 60)], {("a", "b"): 40}, 40),
    ("demo ring along debts",
     [("garment", "fabric", 450000), ("hardware", "garment", 320000),
      ("fabric", "hardware", 380000)],
     {("garment", "fabric"): 130000, ("fabric", "hardware"): 60000}, 130000),
    ("5-ring with a chord",
     [("a", "b", 50), ("b", "c", 50), ("c", "d", 50), ("d", "e", 50), ("e", "a", 50),
      ("a", "c", 20)],
     {("a", "c"): 20}, 20),
    ("paisa-level amounts", [("a", "b", "0.03"), ("b", "a", "0.01")],
     {("a", "b"): Decimal("0.02")}, Decimal("0.02")),
]


IDS = [c[0] for c in HAND_CASES]


@pytest.mark.parametrize(("name", "edges", "expected", "_"), HAND_CASES, ids=IDS)
def test_hand_cases_along_debts(name, edges, expected, _):
    result = one_round(ring(*edges))
    assert flows(result) == {k: Decimal(str(v)) for k, v in expected.items()}


@pytest.mark.parametrize(("name", "edges", "_", "net"), HAND_CASES, ids=IDS)
def test_hand_cases_with_new_links_reach_the_theoretical_minimum(name, edges, _, net):
    result = one_round(ring(*edges), allow_new_links=True)
    assert result.net_total == Money.of(Decimal(str(net)))


def test_debts_outside_any_cycle_are_not_pulled_into_the_round():
    result = one_round(ring(("a", "b", 100), ("b", "a", 100), ("b", "tail", 500)))
    assert result.participants == ("a", "b")
    assert result.obligation_ids == ("o1", "o2")


def test_no_round_without_circular_debt():
    assert propose_rounds(build_graph(ring(("a", "b", 1), ("b", "c", 1))), now=NOW) == []


def test_round_is_proposed_and_expires_after_48_hours():
    result = one_round(ring(("a", "b", 10), ("b", "a", 4)))
    assert result.status is RoundStatus.proposed
    assert result.expires_at - result.created_at == timedelta(hours=48)
    assert result.approvals == {}


def test_proposal_is_deterministic():
    edges = ring(("a", "b", 70), ("b", "c", 30), ("c", "a", 50), ("c", "b", 5))
    first = propose_rounds(build_graph(edges), now=NOW)
    assert first == propose_rounds(build_graph(edges), now=NOW)


def test_cash_saved_on_the_demo_ring(universe):
    result = propose_rounds(build_graph(universe.mesh_obligations), now=NOW)[0]
    assert result.cash_saved == Money.of(960000)  # 11.5 lakh of debt cleared with 1.9 lakh


# ---- Properties on random debt graphs ---------------------------------------------------

edge_lists = st.lists(
    st.tuples(st.sampled_from("abcdef"), st.sampled_from("abcdef"), st.integers(1, 10**7)),
    min_size=2, max_size=18,
).map(lambda es: [(d, c, Decimal(a) / 100) for d, c, a in es if d != c])


def _rounds(edges, allow_new_links):
    graph = build_graph(ring(*edges))
    return graph, propose_rounds(graph, now=NOW, allow_new_links=allow_new_links)


@pytest.mark.property
@given(edge_lists, st.booleans())
def test_every_net_position_is_unchanged(edges, new_links):
    graph, rounds = _rounds(edges, new_links)
    for r in rounds:
        sub = build_graph([graph.obligations[o] for o in r.obligation_ids])
        before = sub.positions()
        assert positions_after(r) == before


@pytest.mark.property
@given(edge_lists)
def test_along_debts_no_one_pays_more_than_owed_on_any_edge(edges):
    graph, rounds = _rounds(edges, False)
    for r in rounds:
        for s in r.settlements:
            assert s.amount <= graph.owed(s.payer_tenant, s.payee_tenant)


@pytest.mark.property
@given(edge_lists)
def test_with_new_links_no_one_pays_more_than_their_total_debt(edges):
    graph, rounds = _rounds(edges, True)
    for r in rounds:
        for tenant in r.participants:
            paid = sum((s.amount for s in r.settlements if s.payer_tenant == tenant),
                       Money.zero())
            owed = sum((graph.owed(tenant, other) for other in r.participants), Money.zero())
            assert paid <= owed


@pytest.mark.property
@given(edge_lists, st.booleans())
def test_net_never_exceeds_gross(edges, new_links):
    _, rounds = _rounds(edges, new_links)
    for r in rounds:
        assert r.net_total <= r.gross_total
        assert r.net_total == sum((s.amount for s in r.settlements), Money.zero())


@pytest.mark.property
@given(edge_lists)
def test_new_links_hit_the_lower_bound_and_beat_along_debts(edges):
    _, along = _rounds(edges, False)
    graph, linked = _rounds(edges, True)
    for a, b in zip(along, linked, strict=True):
        sub = build_graph([graph.obligations[o] for o in b.obligation_ids])
        lower_bound = sum((p for p in sub.positions().values() if p.amount > 0), Money.zero())
        assert b.net_total == lower_bound
        assert b.net_total <= a.net_total


@pytest.mark.property
@given(edge_lists)
def test_along_debts_result_has_no_payment_cycle_left(edges):
    """Optimality certificate: a cycle of positive payments could be cancelled for less cash."""
    _, rounds = _rounds(edges, False)
    for r in rounds:
        paid = nx.DiGraph([(s.payer_tenant, s.payee_tenant) for s in r.settlements])
        assert list(nx.simple_cycles(paid)) == []
