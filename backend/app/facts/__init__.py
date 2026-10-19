"""Typed Fact Ledger and provenance graph (WP-01).

Every number an engine uses or shows is a typed `Fact` with a traceable origin. Lookups are
exact: `(tenant, metric, period, entity)` must match field for field; there is no fuzzy,
case-folded or vector lookup anywhere in this package.

    from app.facts import FactStore, compute, record_computed, explain
"""

from app.facts.provenance import (
    ProvenanceIncomplete,
    compute,
    explain,
    explain_rows,
    record_computed,
    record_figure,
)
from app.facts.registry import REGISTRY, NotComputable, UnknownMetric, cite
from app.facts.store import FactNotFound, FactStore, LedgerConflict, fact_id

__all__ = [
    "REGISTRY",
    "FactNotFound",
    "FactStore",
    "LedgerConflict",
    "NotComputable",
    "ProvenanceIncomplete",
    "UnknownMetric",
    "cite",
    "compute",
    "explain",
    "explain_rows",
    "fact_id",
    "record_computed",
    "record_figure",
]
