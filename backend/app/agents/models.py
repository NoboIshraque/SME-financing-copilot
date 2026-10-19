"""Tables of the agents (WP-10): claims the checker refused, abstentions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RejectedClaimRow(Base):
    """A claim removed from an answer: rejected (recomputed differently) or unverifiable.
    Holds ids, values and the reason; never the question or any personal data."""

    __tablename__ = "agents_rejected_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), index=True)
    claim_id: Mapped[str] = mapped_column(String(200))
    formula_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))
    claimed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recomputed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AbstentionRow(Base):
    """Every time the copilot said "I don't know" (FEATURES N17): why, and what is missing.
    The question is the tenant's own and is shown only to that tenant."""

    __tablename__ = "agents_abstentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(32))
    message_key: Mapped[str] = mapped_column(String(64))
    missing: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    stakes: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
