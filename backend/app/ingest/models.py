"""Tables of the ingest flow (WP-02).

A preview is stored server side, so the commit commits exactly what the owner saw; only typed
records with party tokens are stored, never raw names, numbers or file bytes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IngestPreviewRow(Base):
    __tablename__ = "ingest_previews"

    preview_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    file_digest: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(256))
    source_format: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | committed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[str] = mapped_column(Text)  # the IngestPreview contract as JSON
    strong_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list, see dedupe
    aliases: Mapped[str] = mapped_column(Text, default="{}")  # JSON {alias digest: party token}
    summary: Mapped[str] = mapped_column(Text, default="{}")  # JSON counts once committed


class PartyAliasRow(Base):
    """Which party token a (keyed digest of a) name or phone number belongs to."""

    __tablename__ = "ingest_party_aliases"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alias: Mapped[str] = mapped_column(String(64), primary_key=True)
    token: Mapped[str] = mapped_column(String(32))
