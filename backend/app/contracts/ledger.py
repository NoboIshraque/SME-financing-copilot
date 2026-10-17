"""Ledger records produced by ingest (WP-02) and stored by the fact ledger (WP-01)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, DataMode, Money


class Channel(StrEnum):
    bkash = "bkash"
    nagad = "nagad"
    rocket = "rocket"
    bank = "bank"
    cash = "cash"
    card = "card"
    other = "other"

    @property
    def is_mobile_money(self) -> bool:
        return self in (Channel.bkash, Channel.nagad, Channel.rocket)


class Direction(StrEnum):
    inflow = "inflow"
    outflow = "outflow"


class TxCategory(StrEnum):
    sales = "sales"
    collection = "collection"  # payment received against an invoice (baki)
    purchase = "purchase"
    supplier_payment = "supplier_payment"
    rent = "rent"
    salary = "salary"
    loan_repayment = "loan_repayment"
    loan_disbursement = "loan_disbursement"
    utility = "utility"
    tax = "tax"
    owner_draw = "owner_draw"
    owner_topup = "owner_topup"
    transfer = "transfer"  # between the business's own accounts
    fee = "fee"
    other = "other"


class Transaction(Contract):
    id: str
    tenant_id: str
    occurred_at: datetime
    amount: Money = Field(description="Always positive; `direction` gives the sign")
    direction: Direction
    channel: Channel
    category: TxCategory = TxCategory.other
    counterparty_token: str | None = None
    reference: str | None = None
    invoice_id: str | None = None
    source_ref: str = Field(description="Source file + row, e.g. 'bkash.csv#L42'")
    data_mode: DataMode

    @model_validator(mode="after")
    def _positive(self) -> Transaction:
        if self.amount.amount <= 0:
            raise ValueError("transaction amount must be positive; use direction for sign")
        return self

    @property
    def day(self) -> date:
        return self.occurred_at.date()

    @property
    def signed_amount(self) -> Money:
        return self.amount if self.direction is Direction.inflow else -self.amount


class DocumentStatus(StrEnum):
    open = "open"
    partially_paid = "partially_paid"
    paid = "paid"
    disputed = "disputed"
    written_off = "written_off"


class _Document(Contract):
    id: str
    tenant_id: str
    counterparty_token: str
    issue_date: date
    due_date: date
    amount: Money
    amount_paid: Money
    status: DocumentStatus
    paid_date: date | None = None
    source_ref: str
    data_mode: DataMode

    @model_validator(mode="after")
    def _consistent(self) -> _Document:
        if self.due_date < self.issue_date:
            raise ValueError("due_date is before issue_date")
        if self.amount.amount <= 0:
            raise ValueError("document amount must be positive")
        if self.amount_paid.amount < 0 or self.amount_paid > self.amount:
            raise ValueError("amount_paid must be between 0 and amount")
        if self.status is DocumentStatus.paid:
            if self.amount_paid != self.amount or self.paid_date is None:
                raise ValueError("a paid document needs amount_paid == amount and a paid_date")
        if self.paid_date is not None and self.paid_date < self.issue_date:
            raise ValueError("paid_date is before issue_date")
        return self

    @property
    def outstanding(self) -> Money:
        return self.amount - self.amount_paid


class Invoice(_Document):
    """Money a customer owes the business (includes baki / credit sales)."""


class Bill(_Document):
    """Money the business owes a supplier."""


class ObligationKind(StrEnum):
    rent = "rent"
    salary = "salary"
    emi = "emi"
    utility = "utility"
    tax = "tax"
    subscription = "subscription"
    other = "other"


class Frequency(StrEnum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class RecurringObligation(Contract):
    id: str
    tenant_id: str
    kind: ObligationKind
    counterparty_token: str
    amount: Money
    frequency: Frequency
    day_of_period: int = Field(ge=1, le=31, description="Day of month (or weekday 1-7)")
    start_date: date
    end_date: date | None = None
    source_ref: str
    data_mode: DataMode

    @model_validator(mode="after")
    def _valid(self) -> RecurringObligation:
        if self.amount.amount <= 0:
            raise ValueError("obligation amount must be positive")
        if self.frequency is Frequency.weekly and self.day_of_period > 7:
            raise ValueError("weekly obligations use day_of_period 1-7")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self
