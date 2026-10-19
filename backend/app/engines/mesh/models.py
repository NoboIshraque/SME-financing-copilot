"""Mesh tables (WP-08 milestone 8): stored obligations and netting rounds.

The engine stays pure: only `store.py`, the API and jobs touch these tables. A round's salt is
stored next to it and never leaves the server: the public anchor is a salted digest, so the salt
is what stops anyone brute-forcing small amounts from the hash.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MeshObligationRow(Base):
    __tablename__ = "mesh_obligations"
    __table_args__ = (Index("ix_mesh_obligations_parties", "debtor_tenant", "creditor_tenant"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    debtor_tenant: Mapped[str] = mapped_column(String(64))
    creditor_tenant: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str] = mapped_column(Text)  # MeshObligation JSON


class NettingRoundRow(Base):
    __tablename__ = "mesh_rounds"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    participants: Mapped[str] = mapped_column(String(512))  # space-separated, for filtering
    salt: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str] = mapped_column(Text)  # NettingRound JSON
