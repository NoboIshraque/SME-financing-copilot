"""Obligation graph across opted-in tenants (WP-08 milestone 1).

An edge `debtor -> creditor` carries the total amount the debtor owes the creditor across all
open obligations. Amounts are handled in paisa (integers) inside the graph so that flow
algorithms are exact.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import networkx as nx

from app.contracts import Currency, MeshObligation, Money, ObligationStatus

PAISA = Decimal(100)


def to_paisa(money: Money) -> int:
    value = money.amount * PAISA
    if value != value.to_integral_value():
        raise ValueError(f"amount has sub-paisa precision: {money.amount}")
    return int(value)


def from_paisa(paisa: int) -> Money:
    return Money.of(Decimal(paisa) / PAISA)


@dataclass(frozen=True)
class ObligationGraph:
    graph: nx.DiGraph  # edge attrs: paisa (int), obligation_ids (tuple[str, ...])
    obligations: dict[str, MeshObligation]

    @property
    def tenants(self) -> list[str]:
        return sorted(self.graph.nodes)

    def owed(self, debtor: str, creditor: str) -> Money:
        if not self.graph.has_edge(debtor, creditor):
            return Money.zero()
        return from_paisa(self.graph.edges[debtor, creditor]["paisa"])

    def net_position(self, tenant: str) -> Money:
        """Positive: the tenant is owed more than it owes (a net creditor)."""
        incoming = sum(d["paisa"] for _, _, d in self.graph.in_edges(tenant, data=True))
        outgoing = sum(d["paisa"] for _, _, d in self.graph.out_edges(tenant, data=True))
        return from_paisa(incoming - outgoing)

    def positions(self) -> dict[str, Money]:
        return {tenant: self.net_position(tenant) for tenant in self.tenants}

    def gross_total(self) -> Money:
        return from_paisa(sum(d["paisa"] for _, _, d in self.graph.edges(data=True)))

    def cycles(self) -> list[list[str]]:
        """Every simple debt cycle, each rotated to start at its smallest tenant id."""
        found = []
        for cycle in nx.simple_cycles(self.graph):
            start = cycle.index(min(cycle))
            found.append(cycle[start:] + cycle[:start])
        return sorted(found, key=lambda c: (len(c), c))

    def nettable_groups(self) -> list[list[str]]:
        """Groups of tenants whose debts form at least one cycle (strongly connected, >= 2)."""
        groups = [sorted(c) for c in nx.strongly_connected_components(self.graph) if len(c) > 1]
        return sorted(groups)


def build_graph(
    obligations: Iterable[MeshObligation], opted_in: Iterable[str] | None = None
) -> ObligationGraph:
    """Only open obligations between two opted-in tenants enter the graph."""
    allowed = set(opted_in) if opted_in is not None else None
    graph = nx.DiGraph()
    kept: dict[str, MeshObligation] = {}
    totals: dict[tuple[str, str], int] = defaultdict(int)
    ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for obligation in obligations:
        if obligation.status is not ObligationStatus.open:
            continue
        if allowed is not None and not (
            obligation.debtor_tenant in allowed and obligation.creditor_tenant in allowed
        ):
            continue
        if obligation.amount.currency is not Currency.BDT:
            raise ValueError("the mesh nets BDT obligations only")
        if obligation.id in kept:
            raise ValueError(f"duplicate obligation id: {obligation.id}")
        kept[obligation.id] = obligation
        key = (obligation.debtor_tenant, obligation.creditor_tenant)
        totals[key] += to_paisa(obligation.amount)
        ids[key].append(obligation.id)
    for (debtor, creditor), paisa in sorted(totals.items()):
        graph.add_edge(debtor, creditor, paisa=paisa, obligation_ids=tuple(sorted(ids[debtor,
                                                                                       creditor])))
    return ObligationGraph(graph=graph, obligations=kept)
