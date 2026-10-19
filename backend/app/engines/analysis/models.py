"""Frozen forecast snapshots (WP-07 milestone 3; FEATURES N1).

One row per (tenant, kind, period): the first snapshot stored for a period is the one every
later check compares against. Rows are insert-only: an UPDATE of a stored snapshot raises, so
a forecast can never be edited after the fact to look more accurate.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SnapshotRow(Base):
    __tablename__ = "analysis_snapshots"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "period_start",
                                       name="uq_analysis_snapshot_period"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(40), unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    as_of: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reconstructed: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[str] = mapped_column(Text)


class SnapshotImmutable(RuntimeError):
    """A stored snapshot was about to be changed."""


@event.listens_for(SnapshotRow, "before_update")
def _refuse_update(_mapper, _connection, target: SnapshotRow) -> None:
    raise SnapshotImmutable(f"snapshot {target.id} is frozen and cannot be changed")
