"""The fact ledger store (WP-01 milestone 1).

`FactStore` wraps one SQLAlchemy session. It persists ledger records (transactions, invoices,
bills, recurring obligations) and typed `Fact` rows, and answers exact lookups only:

    store.get("sme_grocery", "net_sales", period)            # Fact, or raises FactNotFound

A metric, period or entity that differs in any field (case, whitespace, one day of the
period, granularity) is a miss, never a near match.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    Bill,
    Fact,
    Figure,
    FormulaRef,
    Invoice,
    Period,
    RecurringObligation,
    Transaction,
)
from app.facts.models import (
    FactRow,
    FigureRow,
    FormulaRow,
    LedgerDocumentRow,
    LedgerObligationRow,
    LedgerTransactionRow,
)

_NO_ENTITY = ""


class FactNotFound(KeyError):
    """No fact (or formula, or figure) matches the exact key."""


class LedgerConflict(ValueError):
    """An immutable record (fact, formula, figure) already exists with different content."""


def _entity_column(entity_token: str | None) -> str:
    if entity_token == _NO_ENTITY:
        raise ValueError("entity_token must be None or a non-empty token")
    return entity_token if entity_token is not None else _NO_ENTITY


class FactStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ----------------------------------------------------------------- ledger records

    def add_transactions(self, transactions: Iterable[Transaction]) -> int:
        """Insert or replace transactions by (tenant, id). Returns how many were written."""
        count = 0
        for txn in transactions:
            self.session.merge(
                LedgerTransactionRow(
                    tenant_id=txn.tenant_id,
                    id=txn.id,
                    occurred_at=txn.occurred_at,
                    day=txn.day,
                    source_ref=txn.source_ref,
                    payload=txn.model_dump_json(),
                )
            )
            count += 1
        self.session.flush()
        return count

    def add_invoices(self, invoices: Iterable[Invoice]) -> int:
        return self._add_documents("invoice", invoices)

    def add_bills(self, bills: Iterable[Bill]) -> int:
        return self._add_documents("bill", bills)

    def _add_documents(self, kind: str, documents: Iterable[Invoice] | Iterable[Bill]) -> int:
        count = 0
        for doc in documents:
            self.session.merge(
                LedgerDocumentRow(
                    tenant_id=doc.tenant_id,
                    kind=kind,
                    id=doc.id,
                    issue_date=doc.issue_date,
                    source_ref=doc.source_ref,
                    payload=doc.model_dump_json(),
                )
            )
            count += 1
        self.session.flush()
        return count

    def add_obligations(self, obligations: Iterable[RecurringObligation]) -> int:
        count = 0
        for obligation in obligations:
            self.session.merge(
                LedgerObligationRow(
                    tenant_id=obligation.tenant_id,
                    id=obligation.id,
                    source_ref=obligation.source_ref,
                    payload=obligation.model_dump_json(),
                )
            )
            count += 1
        self.session.flush()
        return count

    def transactions(
        self, tenant_id: str, start: date | None = None, end: date | None = None
    ) -> list[Transaction]:
        """Transactions of a tenant whose day is within [start, end], oldest first."""
        query = select(LedgerTransactionRow.payload).where(
            LedgerTransactionRow.tenant_id == tenant_id
        )
        if start is not None:
            query = query.where(LedgerTransactionRow.day >= start)
        if end is not None:
            query = query.where(LedgerTransactionRow.day <= end)
        query = query.order_by(LedgerTransactionRow.occurred_at, LedgerTransactionRow.id)
        return [Transaction.model_validate_json(p) for p in self.session.scalars(query)]

    def invoices(self, tenant_id: str, issued_by: date | None = None) -> list[Invoice]:
        return [Invoice.model_validate_json(p)
                for p in self._documents("invoice", tenant_id, issued_by)]

    def bills(self, tenant_id: str, issued_by: date | None = None) -> list[Bill]:
        return [Bill.model_validate_json(p) for p in self._documents("bill", tenant_id, issued_by)]

    def _documents(self, kind: str, tenant_id: str, issued_by: date | None) -> list[str]:
        query = select(LedgerDocumentRow.payload).where(
            LedgerDocumentRow.tenant_id == tenant_id, LedgerDocumentRow.kind == kind
        )
        if issued_by is not None:
            query = query.where(LedgerDocumentRow.issue_date <= issued_by)
        query = query.order_by(LedgerDocumentRow.issue_date, LedgerDocumentRow.id)
        return list(self.session.scalars(query))

    def obligations(self, tenant_id: str) -> list[RecurringObligation]:
        query = (
            select(LedgerObligationRow.payload)
            .where(LedgerObligationRow.tenant_id == tenant_id)
            .order_by(LedgerObligationRow.id)
        )
        return [RecurringObligation.model_validate_json(p) for p in self.session.scalars(query)]

    # ----------------------------------------------------------------- facts

    def put_fact(self, fact: Fact) -> Fact:
        """Store a fact. Facts are immutable: the same id with other content is refused."""
        existing = self.session.scalar(select(FactRow.payload).where(FactRow.id == fact.id))
        if existing is not None:
            if Fact.model_validate_json(existing) != fact:
                raise LedgerConflict(f"fact {fact.id} already exists with different content")
            return fact
        self.session.add(
            FactRow(
                id=fact.id,
                tenant_id=fact.tenant_id,
                metric=fact.metric,
                period_start=fact.period.start,
                period_end=fact.period.end,
                granularity=fact.period.granularity.value,
                entity_token=_entity_column(fact.entity_token),
                formula_version=fact.provenance.formula_version if fact.provenance else 0,
                value=str(fact.value),
                payload=fact.model_dump_json(),
            )
        )
        self.session.flush()
        return fact

    def get(
        self,
        tenant_id: str,
        metric: str,
        period: Period,
        entity_token: str | None = None,
        version: int | None = None,
    ) -> Fact:
        """Exact lookup. Without `version`, the newest fact of the highest formula version."""
        query = select(FactRow.payload).where(
            FactRow.tenant_id == tenant_id,
            FactRow.metric == metric,
            FactRow.period_start == period.start,
            FactRow.period_end == period.end,
            FactRow.granularity == period.granularity.value,
            FactRow.entity_token == _entity_column(entity_token),
        )
        if version is not None:
            query = query.where(FactRow.formula_version == version)
        query = query.order_by(FactRow.formula_version.desc(), FactRow.seq.desc()).limit(1)
        payload = self.session.scalar(query)
        if payload is None:
            raise FactNotFound(
                f"no fact {metric!r} for {tenant_id} {period.start}..{period.end}"
                f" ({period.granularity.value}) entity={entity_token!r}"
            )
        fact = Fact.model_validate_json(payload)
        # Defence in depth against database collations that ignore case or trailing spaces.
        if (fact.metric, fact.tenant_id, fact.period, fact.entity_token) != (
            metric, tenant_id, period, entity_token
        ):
            raise FactNotFound(f"no exact match for {metric!r}")
        return fact

    def get_fact(self, fact_id: str) -> Fact:
        payload = self.session.scalar(select(FactRow.payload).where(FactRow.id == fact_id))
        if payload is None:
            raise FactNotFound(f"no fact with id {fact_id!r}")
        return Fact.model_validate_json(payload)

    def facts(self, tenant_id: str, metric: str) -> list[Fact]:
        """Every stored fact of one metric for a tenant, oldest period first."""
        query = (
            select(FactRow.payload)
            .where(FactRow.tenant_id == tenant_id, FactRow.metric == metric)
            .order_by(FactRow.period_start, FactRow.period_end, FactRow.formula_version,
                      FactRow.seq)
        )
        return [Fact.model_validate_json(p) for p in self.session.scalars(query)]

    # ----------------------------------------------------------------- formulas and figures

    def put_formula(self, formula: FormulaRef) -> FormulaRef:
        """Record a formula version. A recorded version never changes its expression."""
        row = self.session.get(FormulaRow, (formula.formula_id, formula.version))
        if row is not None:
            if row.expression != formula.expression:
                raise LedgerConflict(
                    f"formula {formula.formula_id} v{formula.version} is already recorded with "
                    "a different expression; bump the version"
                )
            return formula
        self.session.add(FormulaRow(formula_id=formula.formula_id, version=formula.version,
                                    expression=formula.expression))
        self.session.flush()
        return formula

    def formula(self, formula_id: str, version: int) -> FormulaRef:
        row = self.session.get(FormulaRow, (formula_id, version))
        if row is None:
            raise FactNotFound(f"formula {formula_id} v{version} was never recorded")
        return FormulaRef(formula_id=row.formula_id, version=row.version,
                          expression=row.expression)

    def put_figure(self, tenant_id: str, figure: Figure) -> Figure:
        row = self.session.get(FigureRow, figure.id)
        if row is not None:
            if row.tenant_id != tenant_id or Figure.model_validate_json(row.payload) != figure:
                raise LedgerConflict(f"figure {figure.id} already exists with different content")
            return figure
        self.session.add(FigureRow(id=figure.id, tenant_id=tenant_id,
                                   payload=figure.model_dump_json()))
        self.session.flush()
        return figure

    def get_figure(self, figure_id: str) -> tuple[str, Figure]:
        """Return (tenant_id, figure)."""
        row = self.session.get(FigureRow, figure_id)
        if row is None:
            raise FactNotFound(f"no figure with id {figure_id!r}")
        return row.tenant_id, Figure.model_validate_json(row.payload)


def fact_id(
    tenant_id: str,
    metric: str,
    period: Period,
    entity_token: str | None,
    formula_version: int,
    value: object,
    source_refs: Iterable[str],
) -> str:
    """Deterministic, content-addressed fact id.

    Same inputs give the same id (idempotent re-runs); a different value, formula version or
    set of source rows gives a new id, so an old fact is never overwritten.
    """
    key = "|".join(
        [tenant_id, metric, period.start.isoformat(), period.end.isoformat(),
         period.granularity.value, entity_token or "", str(formula_version), str(value),
         *sorted(source_refs)]
    )
    return "fact_" + hashlib.sha256(key.encode()).hexdigest()[:24]
