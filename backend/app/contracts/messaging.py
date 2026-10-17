"""Messaging (WP-12; FEATURES N2). Channels: in-app, email, copy-to-clipboard (P10 was cut)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.contracts.common import Contract, DataMode, Language, Tier


class MessageChannel(StrEnum):
    in_app = "in_app"
    email = "email"
    copy = "copy"


class MessagePurpose(StrEnum):
    pre_due_reminder = "pre_due_reminder"
    overdue_reminder = "overdue_reminder"
    payment_plan_offer = "payment_plan_offer"
    supplier_term_extension = "supplier_term_extension"
    lender_update = "lender_update"
    netting_invitation = "netting_invitation"
    sale_memo = "sale_memo"


class DraftStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    sent = "sent"
    rejected = "rejected"


class MessageDraft(Contract):
    id: str
    tenant_id: str
    template_id: str
    purpose: MessagePurpose
    language: Language
    channel: MessageChannel
    recipient_token: str
    body: str = Field(max_length=2000)
    variables: dict[str, str] = Field(
        default_factory=dict, description="Filled from typed facts only"
    )
    tier: Tier
    status: DraftStatus = DraftStatus.draft
    created_at: datetime
    data_mode: DataMode
