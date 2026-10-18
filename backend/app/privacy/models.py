"""Vault table (WP-03): one encrypted original per (tenant, token). No plaintext column."""

from __future__ import annotations

from sqlalchemy import LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VaultEntry(Base):
    __tablename__ = "privacy_vault"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
