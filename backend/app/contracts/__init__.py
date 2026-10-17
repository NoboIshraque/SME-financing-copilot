"""Shared, frozen contracts (owned by WP-00).

Import from here: `from app.contracts import Money, Transaction, ...`.
To change a contract, write the request under "Questions" in your WP file and stop; the
orchestrator changes it, bumps CONTRACTS_VERSION and regenerates docs/api/contracts.json.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.contracts import (
    agents,
    analysis,
    cash,
    common,
    facts,
    financing,
    ingest,
    ledger,
    market,
    mesh,
    messaging,
    party,
    reports,
    security,
)
from app.contracts.agents import *  # noqa: F403
from app.contracts.analysis import *  # noqa: F403
from app.contracts.cash import *  # noqa: F403
from app.contracts.common import *  # noqa: F403
from app.contracts.facts import *  # noqa: F403
from app.contracts.financing import *  # noqa: F403
from app.contracts.ingest import *  # noqa: F403
from app.contracts.ledger import *  # noqa: F403
from app.contracts.market import *  # noqa: F403
from app.contracts.mesh import *  # noqa: F403
from app.contracts.messaging import *  # noqa: F403
from app.contracts.party import *  # noqa: F403
from app.contracts.reports import *  # noqa: F403
from app.contracts.security import *  # noqa: F403

CONTRACTS_VERSION = "1.1.0"  # 1.1: FinancingProduct.rate_basis + notes

MODULES = (
    common,
    party,
    ledger,
    facts,
    market,
    analysis,
    agents,
    cash,
    financing,
    mesh,
    security,
    messaging,
    ingest,
    reports,
)


def all_contract_models() -> dict[str, type[BaseModel]]:
    """Every public contract model, keyed by class name (sorted, stable)."""
    found: dict[str, type[BaseModel]] = {}
    for module in MODULES:
        for name, obj in vars(module).items():
            if name.startswith("_") or not isinstance(obj, type):
                continue
            if issubclass(obj, common.Contract) and obj is not common.Contract:
                if obj.__module__ == module.__name__:
                    if name in found and found[name] is not obj:
                        raise RuntimeError(f"duplicate contract name: {name}")
                    found[name] = obj
    return dict(sorted(found.items()))
