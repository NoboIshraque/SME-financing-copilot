"""Multilateral netting (WP-08 milestone 2).

For each group of tenants whose debts form cycles, find settlements that discharge every
obligation in the group while moving the least cash. Settlements may only run along existing
debts (debtor -> creditor), so nobody ends up paying a firm it never owed.

Formulation (min-cost flow, exact integer paisa):
  node demand  = net position (positive = net creditor receives)
  edge d -> c  = capacity: amount d owes c; cost 1 per paisa
The original obligations are themselves a feasible flow, so a solution always exists, and the
minimum-cost flow is the original minus the largest circulation that can be cancelled.

With `allow_new_links=True` a net debtor may pay any net creditor in the group (the theoretical
minimum: cash moved = sum of positive net positions). That needs every participant to accept a
payment from a firm it had no direct debt with, so it is opt-in.

Invariants (property-tested):
  1. every tenant's net position is unchanged;
  2. along debts: no settlement on an edge exceeds what was owed on that edge;
     with new links: no tenant pays more in total than it owed in total;
  3. net total <= gross total.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import networkx as nx

from app.contracts import (
    DataMode,
    Money,
    NettingRound,
    RoundStatus,
    Settlement,
)
from app.engines.mesh.graph import ObligationGraph, from_paisa

ROUND_TTL = timedelta(hours=48)
FORMULA_ID = "mesh.netting.min_cost_flow"
FORMULA_VERSION = 1


def settle_flows(
    graph: ObligationGraph, group: list[str], *, allow_new_links: bool = False
) -> dict[tuple[str, str], int]:
    """Minimum-cash settlement flows (paisa) inside one group of tenants."""
    sub = graph.graph.subgraph(group)
    flow_net = nx.DiGraph()
    demand: dict[str, int] = {}
    for tenant in sorted(group):
        incoming = sum(d["paisa"] for _, _, d in sub.in_edges(tenant, data=True))
        outgoing = sum(d["paisa"] for _, _, d in sub.out_edges(tenant, data=True))
        demand[tenant] = incoming - outgoing  # networkx: demand > 0 means the node receives
        flow_net.add_node(tenant, demand=demand[tenant])
    if allow_new_links:
        payers = [t for t in sorted(group) if demand[t] < 0]
        payees = [t for t in sorted(group) if demand[t] > 0]
        for payer in payers:
            for payee in payees:
                flow_net.add_edge(payer, payee, capacity=-demand[payer], weight=1)
    else:
        for debtor, creditor, data in sorted(sub.edges(data=True)):
            flow_net.add_edge(debtor, creditor, capacity=data["paisa"], weight=1)
    flow = nx.min_cost_flow(flow_net)
    return {
        (debtor, creditor): amount
        for debtor, targets in sorted(flow.items())
        for creditor, amount in sorted(targets.items())
        if amount > 0
    }


def propose_rounds(
    graph: ObligationGraph,
    *,
    now: datetime,
    round_id_prefix: str = "round",
    data_mode: DataMode = DataMode.synthetic,
    allow_new_links: bool = False,
) -> list[NettingRound]:
    """One proposed round per group of tenants with circular debt. Empty if no cycles."""
    rounds = []
    for index, group in enumerate(graph.nettable_groups(), start=1):
        sub = graph.graph.subgraph(group)
        obligation_ids = sorted(
            oid for _, _, data in sub.edges(data=True) for oid in data["obligation_ids"]
        )
        gross = sum(data["paisa"] for _, _, data in sub.edges(data=True))
        flows = settle_flows(graph, group, allow_new_links=allow_new_links)
        settlements = tuple(
            Settlement(payer_tenant=d, payee_tenant=c, amount=from_paisa(paisa))
            for (d, c), paisa in flows.items()
        )
        rounds.append(
            NettingRound(
                id=f"{round_id_prefix}-{now:%Y%m%d%H%M%S}-{index}",
                obligation_ids=tuple(obligation_ids),
                participants=tuple(group),
                settlements=settlements,
                gross_total=from_paisa(gross),
                net_total=from_paisa(sum(flows.values())),
                status=RoundStatus.proposed,
                created_at=now,
                expires_at=now + ROUND_TTL,
                data_mode=data_mode,
            )
        )
    return rounds


def positions_after(round_: NettingRound) -> dict[str, Money]:
    """Net position each participant gets from the settlements alone."""
    out = {tenant: Money.zero() for tenant in round_.participants}
    for s in round_.settlements:
        out[s.payer_tenant] = out[s.payer_tenant] - s.amount
        out[s.payee_tenant] = out[s.payee_tenant] + s.amount
    return out
