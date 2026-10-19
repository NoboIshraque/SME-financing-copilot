"""Message drafts and their send log (WP-12)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DraftRow(Base):
    __tablename__ = "messaging_drafts"
    __table_args__ = (Index("ix_messaging_drafts_tenant", "tenant_id", "status"),)

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str] = mapped_column(Text)  # MessageDraft JSON
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
