"""Chain tables (WP-08 milestone 8): digests anchored offline, so verify survives a restart."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OfflineAnchorRow(Base):
    __tablename__ = "chain_offline_anchors"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
