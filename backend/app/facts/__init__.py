"""Typed Fact Ledger and provenance graph (WP-01).

Every number an engine uses or shows is a typed `Fact` with a traceable origin. Lookups are
exact: `(tenant, metric, period, entity)` must match field for field; there is no fuzzy,
case-folded or vector lookup anywhere in this package.
"""

from app.facts.store import FactNotFound, FactStore, LedgerConflict

__all__ = ["FactNotFound", "FactStore", "LedgerConflict"]
