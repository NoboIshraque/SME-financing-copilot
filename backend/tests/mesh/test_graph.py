from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import Currency, Money, ObligationStatus
from app.engines.mesh.graph import build_graph, from_paisa, to_paisa
from tests.mesh.helpers import ob, ring


@pytest.mark.parametrize("status", [ObligationStatus.in_round, ObligationStatus.settled,
                                    ObligationStatus.disputed])
def test_only_open_obligations_enter_the_graph(status):
    graph = build_graph([ob("a", "x", "y", 100), ob("b", "y", "x", 50, status=status)])
    assert list(graph.obligations) == ["a"]
    assert graph.owed("y", "x") == Money.zero()


def test_tenants_who_did_not_opt_in_are_left_out():
    graph = build_graph(ring(("x", "y", 10), ("y", "z", 10), ("z", "x", 10)),
                        opted_in=["x", "y"])
    assert graph.tenants == ["x", "y"]
    assert list(graph.obligations) == ["o1"]


def test_several_obligations_between_the_same_pair_are_summed():
    graph = build_graph([ob("a", "x", "y", "100.50"), ob("b", "x", "y", "0.50")])
    assert graph.owed("x", "y") == Money.of(101)
    assert graph.graph.edges["x", "y"]["obligation_ids"] == ("a", "b")


def test_duplicate_obligation_ids_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        build_graph([ob("a", "x", "y", 1), ob("a", "y", "x", 1)])


def test_non_taka_obligations_are_refused():
    usd = ob("a", "x", "y", 1).model_copy(update={"amount": Money.of(1, Currency.USD)})
    with pytest.raises(ValueError, match="BDT"):
        build_graph([usd])


def test_demo_ring_from_the_synthetic_universe(universe):
    graph = build_graph(universe.mesh_obligations)
    assert graph.cycles() == [["sme_fabric", "sme_hardware", "sme_garment"]]
    assert graph.positions() == {
        "sme_fabric": Money.of(70000),
        "sme_garment": Money.of(-130000),
        "sme_hardware": Money.of(60000),
    }
    assert graph.gross_total() == Money.of(1_150_000)


def test_a_debt_chain_without_cycles_has_nothing_to_net():
    graph = build_graph(ring(("a", "b", 100), ("b", "c", 100), ("c", "d", 100)))
    assert graph.cycles() == [] and graph.nettable_groups() == []


def test_two_separate_rings_form_two_groups():
    graph = build_graph(ring(("a", "b", 5), ("b", "a", 3), ("x", "y", 7), ("y", "z", 7),
                             ("z", "x", 2)))
    assert graph.nettable_groups() == [["a", "b"], ["x", "y", "z"]]


@given(st.lists(st.tuples(st.sampled_from("abcde"), st.sampled_from("abcde"),
                          st.integers(1, 10**8)), min_size=1, max_size=15))
def test_net_positions_always_sum_to_zero(edges):
    edges = [(d, c, Decimal(a) / 100) for d, c, a in edges if d != c]
    graph = build_graph(ring(*edges))
    assert sum((p for p in graph.positions().values()), Money.zero()) == Money.zero()


@given(st.integers(-10**12, 10**12))
def test_paisa_conversion_round_trips(paisa):
    assert to_paisa(from_paisa(paisa)) == paisa
