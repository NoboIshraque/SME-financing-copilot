"""Trust Passport versions and share grants (WP-13 API).

A passport's salt is stored next to it and stays on the server; only the salted digest is
anchored. A share grant stores only the SHA-256 of its token.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PassportRow(Base):
    __tablename__ = "reports_passports"
    __table_args__ = (Index("ix_reports_passports_tenant", "tenant_id", "version"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    salt: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str] = mapped_column(Text)  # PassportVersion JSON


class ShareRow(Base):
    __tablename__ = "reports_shares"
    __table_args__ = (Index("ix_reports_shares_tenant", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)  # ShareGrant JSON
