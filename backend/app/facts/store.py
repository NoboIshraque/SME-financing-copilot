"""The fact ledger store (WP-01 milestone 1).

`FactStore` wraps one SQLAlchemy session. It persists ledger records (transactions, invoices,
bills, recurring obligations) and typed `Fact` rows, and answers exact lookups only:

    store.get("sme_grocery", "net_sales", period)            # Fact, or raises FactNotFound

A metric, period or entity that differs in any field (case, whitespace, one day of the
period, granularity) is a miss, never a near match.

Every change to a tenant's ledger records or raw facts bumps the tenant's ledger revision.
Computed facts record the revision they were confirmed against, so a figure that may predate
newer rows is never served as current (see `app.facts.provenance.compute`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import select, tuple_, update
from sqlalchemy.exc import IntegrityError
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
from app.db import Base
from app.facts.models import (
    FactRow,
    FigureRow,
    FormulaRow,
    LedgerDocumentRow,
    LedgerObligationRow,
    LedgerRevisionRow,
    LedgerTransactionRow,
)

_NO_ENTITY = ""
_CHUNK = 400  # keys per IN (...) query, well under every database's parameter limit
R = TypeVar("R", bound=Base)


class FactNotFound(KeyError):
    """No fact (or formula, figure or record) matches the exact key for this tenant."""


class LedgerConflict(ValueError):
    """An immutable record (fact, formula, figure) already exists with different content."""


def _entity_column(entity_token: str | None) -> str:
    if entity_token == _NO_ENTITY:
        raise ValueError("entity_token must be None or a non-empty token")
    return entity_token if entity_token is not None else _NO_ENTITY


def _chunks(items: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), _CHUNK):
        yield items[start:start + _CHUNK]


class FactStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ----------------------------------------------------------------- ledger revision

    def revision(self, tenant_id: str) -> int:
        value = self.session.scalar(
            select(LedgerRevisionRow.revision).where(LedgerRevisionRow.tenant_id == tenant_id))
        return value or 0

    def _bump(self, tenant_id: str) -> None:
        """Atomic increment; the first bump for a tenant inserts its row (race-safe)."""
        done = self.session.execute(
            update(LedgerRevisionRow).where(LedgerRevisionRow.tenant_id == tenant_id)
            .values(revision=LedgerRevisionRow.revision + 1))
        if done.rowcount:
            return
        if self._insert(LedgerRevisionRow(tenant_id=tenant_id, revision=1)):
            return
        self.session.execute(
            update(LedgerRevisionRow).where(LedgerRevisionRow.tenant_id == tenant_id)
            .values(revision=LedgerRevisionRow.revision + 1))

    def _insert(self, row: Base) -> bool:
        """Insert in a savepoint. False when a concurrent writer already holds the key."""
        try:
            with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            return False
        return True

    # ----------------------------------------------------------------- ledger records

    def _upsert(self, model: type[R], rows: Sequence[R],
                key: Callable[[R], tuple[str, ...]]) -> set[str]:
        """Insert new rows and update changed ones with one lookup per chunk of keys.
        Returns the tenants whose ledger changed."""
        latest: dict[tuple[str, ...], R] = {key(r): r for r in rows}  # last one wins
        changed: set[str] = set()
        by_tenant: dict[str, list[tuple[str, ...]]] = {}
        for k in latest:
            by_tenant.setdefault(k[0], []).append(k)
        for tenant, keys in by_tenant.items():
            stored: dict[tuple[str, ...], str] = {}
            pk = model.__table__.primary_key.columns
            for chunk in _chunks(keys):
                query = select(*pk, model.payload).where(tuple_(*pk).in_(chunk))
                for found in self.session.execute(query):
                    stored[tuple(found[:-1])] = found[-1]
            for k in keys:
                row = latest[k]
                if k not in stored:
                    self.session.add(row)
                    changed.add(tenant)
                elif stored[k] != row.payload:
                    self.session.merge(row)
                    changed.add(tenant)
        self.session.flush()
        for tenant in changed:
            self._bump(tenant)
        return changed

    def add_transactions(self, transactions: Iterable[Transaction]) -> int:
        """Insert or replace transactions by (tenant, id). Returns how many were given."""
        rows = [LedgerTransactionRow(tenant_id=t.tenant_id, id=t.id, occurred_at=t.occurred_at,
                                     day=t.day, source_ref=t.source_ref,
                                     payload=t.model_dump_json()) for t in transactions]
        self._upsert(LedgerTransactionRow, rows, lambda r: (r.tenant_id, r.id))
        return len(rows)

    def add_invoices(self, invoices: Iterable[Invoice]) -> int:
        return self._add_documents("invoice", invoices)

    def add_bills(self, bills: Iterable[Bill]) -> int:
        return self._add_documents("bill", bills)

    def _add_documents(self, kind: str, documents: Iterable[Invoice] | Iterable[Bill]) -> int:
        rows = [LedgerDocumentRow(tenant_id=d.tenant_id, kind=kind, id=d.id,
                                  issue_date=d.issue_date, source_ref=d.source_ref,
                                  payload=d.model_dump_json()) for d in documents]
        self._upsert(LedgerDocumentRow, rows, lambda r: (r.tenant_id, r.kind, r.id))
        return len(rows)

    def add_obligations(self, obligations: Iterable[RecurringObligation]) -> int:
        rows = [LedgerObligationRow(tenant_id=o.tenant_id, id=o.id, source_ref=o.source_ref,
                                    payload=o.model_dump_json()) for o in obligations]
        self._upsert(LedgerObligationRow, rows, lambda r: (r.tenant_id, r.id))
        return len(rows)

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

    def transactions_by_id(self, tenant_id: str, ids: Sequence[str]) -> dict[str, Transaction]:
        found: dict[str, Transaction] = {}
        for chunk in _chunks(list(ids)):
            query = select(LedgerTransactionRow.payload).where(
                LedgerTransactionRow.tenant_id == tenant_id, LedgerTransactionRow.id.in_(chunk))
            for payload in self.session.scalars(query):
                txn = Transaction.model_validate_json(payload)
                found[txn.id] = txn
        return found

    def documents_by_id(self, tenant_id: str, kind: str,
                        ids: Sequence[str]) -> dict[str, Invoice | Bill]:
        cls = Invoice if kind == "invoice" else Bill
        found: dict[str, Invoice | Bill] = {}
        for chunk in _chunks(list(ids)):
            query = select(LedgerDocumentRow.payload).where(
                LedgerDocumentRow.tenant_id == tenant_id, LedgerDocumentRow.kind == kind,
                LedgerDocumentRow.id.in_(chunk))
            for payload in self.session.scalars(query):
                doc = cls.model_validate_json(payload)
                found[doc.id] = doc
        return found

    # ----------------------------------------------------------------- facts

    def put_fact(self, fact: Fact, revision: int | None = None) -> Fact:
        """Store a fact. Facts are immutable: the same id with other content is refused.

        A raw fact (no provenance) is a ledger input, so storing a new one bumps the tenant's
        revision. A computed fact is stamped with `revision` (default: the current one).
        """
        existing = self._fact_payload(fact.id)
        if existing is not None:
            return self._same_fact(existing, fact)
        raw = fact.provenance is None
        row = FactRow(
            id=fact.id, tenant_id=fact.tenant_id, metric=fact.metric,
            period_start=fact.period.start, period_end=fact.period.end,
            granularity=fact.period.granularity.value,
            entity_token=_entity_column(fact.entity_token),
            formula_version=fact.provenance.formula_version if fact.provenance else 0,
            revision=self.revision(fact.tenant_id) if revision is None else revision,
            value=str(fact.value), payload=fact.model_dump_json(),
        )
        if not self._insert(row):  # a concurrent writer stored the same id first
            payload = self._fact_payload(fact.id)
            if payload is None:
                raise LedgerConflict(f"fact {fact.id} could not be stored")
            return self._same_fact(payload, fact)
        if raw:
            self._bump(fact.tenant_id)
        self.session.flush()
        return fact

    def _fact_payload(self, fact_id: str) -> str | None:
        return self.session.scalar(select(FactRow.payload).where(FactRow.id == fact_id))

    @staticmethod
    def _same_fact(payload: str, fact: Fact) -> Fact:
        stored = Fact.model_validate_json(payload)
        if stored.model_copy(update={"computed_at": None}) != fact.model_copy(
                update={"computed_at": None}):
            raise LedgerConflict(f"fact {fact.id} already exists with different content")
        return stored

    def touch(self, fact_id: str, revision: int) -> None:
        """Mark a stored fact as confirmed against `revision` (it is current again)."""
        self.session.execute(update(FactRow).where(FactRow.id == fact_id)
                             .values(revision=revision))

    def fact_revision(self, fact_id: str) -> int:
        value = self.session.scalar(select(FactRow.revision).where(FactRow.id == fact_id))
        if value is None:
            raise FactNotFound(f"no fact with id {fact_id!r}")
        return value

    def _key_query(self, tenant_id: str, metric: str, period: Period,
                   entity_token: str | None):  # type: ignore[no-untyped-def]
        return select(FactRow.payload).where(
            FactRow.tenant_id == tenant_id,
            FactRow.metric == metric,
            FactRow.period_start == period.start,
            FactRow.period_end == period.end,
            FactRow.granularity == period.granularity.value,
            FactRow.entity_token == _entity_column(entity_token),
        )

    def _exact(self, payload: str | None, tenant_id: str, metric: str, period: Period,
               entity_token: str | None) -> Fact:
        if payload is None:
            raise FactNotFound(
                f"no fact {metric[:64]!r} for {tenant_id} {period.start}..{period.end}"
                f" ({period.granularity.value})"
            )
        fact = Fact.model_validate_json(payload)
        # Defence in depth against database collations that ignore case or trailing spaces.
        if (fact.metric, fact.tenant_id, fact.period, fact.entity_token) != (
            metric, tenant_id, period, entity_token
        ):
            raise FactNotFound(f"no exact match for {metric[:64]!r}")
        return fact

    def get(
        self,
        tenant_id: str,
        metric: str,
        period: Period,
        entity_token: str | None = None,
        version: int | None = None,
    ) -> Fact:
        """Exact lookup. Without `version`, the highest formula version; among those, the fact
        most recently confirmed against the ledger."""
        query = self._key_query(tenant_id, metric, period, entity_token)
        if version is not None:
            query = query.where(FactRow.formula_version == version)
        query = query.order_by(FactRow.formula_version.desc(), FactRow.revision.desc(),
                               FactRow.seq.desc()).limit(1)
        return self._exact(self.session.scalar(query), tenant_id, metric, period, entity_token)

    def get_current(self, tenant_id: str, metric: str, period: Period,
                    entity_token: str | None, version: int) -> Fact:
        """Exact lookup of a fact confirmed against the tenant's current ledger revision."""
        query = self._key_query(tenant_id, metric, period, entity_token).where(
            FactRow.formula_version == version,
            FactRow.revision == self.revision(tenant_id),
        ).order_by(FactRow.seq.desc()).limit(1)
        return self._exact(self.session.scalar(query), tenant_id, metric, period, entity_token)

    def is_current(self, fact: Fact) -> bool:
        """Raw facts are always current; a computed fact only if confirmed at this revision."""
        if fact.provenance is None:
            return True
        return self.fact_revision(fact.id) == self.revision(fact.tenant_id)

    def get_fact(self, fact_id: str, tenant_id: str | None = None) -> Fact:
        """A fact by id; with `tenant_id`, another tenant's fact is reported as not found."""
        payload = self._fact_payload(fact_id)
        if payload is None:
            raise FactNotFound(f"no fact with id {fact_id[:128]!r}")
        fact = Fact.model_validate_json(payload)
        if tenant_id is not None and fact.tenant_id != tenant_id:
            raise FactNotFound(f"no fact with id {fact_id[:128]!r}")
        return fact

    def facts(self, tenant_id: str, metric: str) -> list[Fact]:
        """Every stored fact of one metric for a tenant, oldest period first."""
        query = (
            select(FactRow.payload)
            .where(FactRow.tenant_id == tenant_id, FactRow.metric == metric)
            .order_by(FactRow.period_start, FactRow.period_end, FactRow.formula_version,
                      FactRow.revision, FactRow.seq)
        )
        return [Fact.model_validate_json(p) for p in self.session.scalars(query)]

    def latest(self, tenant_id: str, metric: str, as_of: date,
               entity_token: str | None = None) -> Fact | None:
        """The most recent value of `metric` known on `as_of` (period ending on or before it).
        For slowly changing facts such as business age or a trade licence."""
        query = (
            select(FactRow.payload)
            .where(FactRow.tenant_id == tenant_id, FactRow.metric == metric,
                   FactRow.entity_token == _entity_column(entity_token),
                   FactRow.period_end <= as_of)
            .order_by(FactRow.period_end.desc(), FactRow.formula_version.desc(),
                      FactRow.revision.desc(), FactRow.seq.desc())
            .limit(1)
        )
        payload = self.session.scalar(query)
        return Fact.model_validate_json(payload) if payload is not None else None

    def snapshot(self, tenant_id: str, metrics: Iterable[str],
                 as_of: date) -> dict[str, Decimal | None]:
        """metric -> latest value on `as_of`, or None when nothing is on record (abstain)."""
        result: dict[str, Decimal | None] = {}
        for metric in metrics:
            fact = self.latest(tenant_id, metric, as_of)
            result[metric] = fact.value if fact is not None else None
        return result

    # ----------------------------------------------------------------- formulas and figures

    def put_formula(self, formula: FormulaRef) -> FormulaRef:
        """Record a formula version. A recorded version never changes its expression."""
        row = self.session.get(FormulaRow, (formula.formula_id, formula.version))
        if row is None:
            if self._insert(FormulaRow(formula_id=formula.formula_id, version=formula.version,
                                       expression=formula.expression)):
                self.session.flush()
                return formula
            row = self.session.get(FormulaRow, (formula.formula_id, formula.version),
                                   populate_existing=True)
        if row is None or row.expression != formula.expression:
            raise LedgerConflict(
                f"formula {formula.formula_id} v{formula.version} is already recorded with "
                "a different expression; bump the version"
            )
        return formula

    def formula(self, formula_id: str, version: int) -> FormulaRef:
        row = self.session.get(FormulaRow, (formula_id, version))
        if row is None:
            raise FactNotFound(f"formula {formula_id} v{version} was never recorded")
        return FormulaRef(formula_id=row.formula_id, version=row.version,
                          expression=row.expression)

    def has_formula(self, formula_id: str, version: int) -> bool:
        return self.session.get(FormulaRow, (formula_id, version)) is not None

    def put_figure(self, tenant_id: str, figure: Figure) -> Figure:
        row = self.session.get(FigureRow, figure.id)
        if row is None:
            if self._insert(FigureRow(id=figure.id, tenant_id=tenant_id,
                                      payload=figure.model_dump_json())):
                self.session.flush()
                return figure
            row = self.session.get(FigureRow, figure.id, populate_existing=True)
        if row is None or row.tenant_id != tenant_id or \
                Figure.model_validate_json(row.payload) != figure:
            raise LedgerConflict(f"figure {figure.id} already exists with different content")
        return figure

    def get_figure(self, figure_id: str, tenant_id: str | None = None) -> tuple[str, Figure]:
        """(tenant_id, figure); with `tenant_id`, another tenant's figure is not found."""
        row = self.session.get(FigureRow, figure_id)
        if row is None or (tenant_id is not None and row.tenant_id != tenant_id):
            raise FactNotFound(f"no figure with id {figure_id[:128]!r}")
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
