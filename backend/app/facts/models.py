"""Tables of the fact ledger (WP-01).

Ledger records are stored as their full contract JSON next to a few indexed columns, so a
record read back is exactly the contract that went in. Decimal values are stored as strings
to stay exact on every database.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LedgerTransactionRow(Base):
    __tablename__ = "facts_transactions"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    source_ref: Mapped[str] = mapped_column(String(256))
    payload: Mapped[str] = mapped_column(Text)


class LedgerDocumentRow(Base):
    """Invoices and bills (`kind` is 'invoice' or 'bill')."""

    __tablename__ = "facts_documents"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    issue_date: Mapped[date] = mapped_column(Date, index=True)
    source_ref: Mapped[str] = mapped_column(String(256))
    payload: Mapped[str] = mapped_column(Text)


class LedgerObligationRow(Base):
    __tablename__ = "facts_obligations"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_ref: Mapped[str] = mapped_column(String(256))
    payload: Mapped[str] = mapped_column(Text)


class FactRow(Base):
    """A typed fact. Immutable once written: a new value or formula version is a new row."""

    __tablename__ = "facts_facts"
    __table_args__ = (
        Index("ix_fact_key", "tenant_id", "metric", "period_start", "period_end", "granularity",
              "entity_token"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    granularity: Mapped[str] = mapped_column(String(16))
    # "" stands for "no entity" so the key columns are never NULL (NULLs never compare equal).
    entity_token: Mapped[str] = mapped_column(String(128), default="")
    # 0 for raw facts read straight from a source row (no formula).
    formula_version: Mapped[int] = mapped_column(Integer, default=0)
    value: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)


class FormulaRow(Base):
    """Every formula version ever used, so old figures keep explaining themselves."""

    __tablename__ = "facts_formulas"

    formula_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    expression: Mapped[str] = mapped_column(Text)


class FigureRow(Base):
    __tablename__ = "facts_figures"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text)
