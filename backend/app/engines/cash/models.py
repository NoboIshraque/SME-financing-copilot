"""What the alert scan has sent (WP-04): the history that dedupe and cooldown are judged on.

One row per alert actually delivered; `alerts.deliver()` reads them back as `SentAlert`s. The
engine itself stays pure: only the API and the scan job touch this table.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import AlertTier
from app.db import Base
from app.engines.cash.alerts import SentAlert


class SentAlertRow(Base):
    __tablename__ = "cash_sent_alerts"
    __table_args__ = (Index("ix_cash_sent_alerts_tenant", "tenant_id", "sent_at"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    alert_id: Mapped[str] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(160))
    tier: Mapped[str] = mapped_column(String(16))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_breach_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_gap_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_shortfall: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    channels: Mapped[str] = mapped_column(String(120))
    reason_key: Mapped[str] = mapped_column(String(64))

    def as_sent(self) -> SentAlert:
        sent_at = self.sent_at if self.sent_at.tzinfo else self.sent_at.replace(tzinfo=UTC)
        return SentAlert(dedupe_key=self.dedupe_key, tier=AlertTier(self.tier),
                         sent_at=sent_at, first_breach_day=self.first_breach_day,
                         last_gap_day=self.last_gap_day,
                         expected_shortfall=self.expected_shortfall)
