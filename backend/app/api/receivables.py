"""Receivables API (WP-05 milestone 7, reduced scope; FEATURES Q2).

    GET /api/receivables        -> ReceivablesOverview {as_of, figures, aging, invoices, customers}
    GET /api/receivables/plan   -> ReceivablesPlan {reminders: [ActionCard]}

Shapes follow `web/src/api/types.ts`. The caller is the signed-in principal (WP-11) with
`ledger:read`; the tenant always comes from the principal. Customers are shown as "Customer N"
(stable per tenant), never by name. `as_of` is today in Dhaka, or the tenant's last transaction
day when the ledger stops earlier. Credit limits, the dispute log and the early-pay calculator
were cut (19 Oct): `credit_limit` is null and `stop_credit` false. With no transactions on
record the API abstains with 422 `not_enough_data`.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.contracts import (
    ActionCard,
    ApiError,
    Figure,
    Granularity,
    Invoice,
    Money,
    Period,
    Principal,
    Provenance,
    Unit,
)
from app.engines.analysis.ledger import NotEnoughData
from app.engines.analysis.store import records
from app.engines.receivables import aging as aging_mod
from app.engines.receivables import ladder, risk
from app.facts import FactStore
from app.facts.provenance import compute, record_figure
from app.facts.registry import NotComputable
from app.main import get_session
from app.security.approvals import issue_cards
from app.security.clock import Clock
from app.security.deps import get_clock, require
from app.security.errors import ProblemRoute
from app.security.roles import Permission

router = APIRouter(prefix="/receivables", tags=["receivables"], route_class=ProblemRoute)
DHAKA = ZoneInfo("Asia/Dhaka")
OVERDUE_FORMULA = "receivables.overdue"


class AgingRow(BaseModel):
    bucket: str
    amount: Money
    count: int


class ReceivableRow(BaseModel):
    invoice: Invoice
    counterparty_label: str
    days_overdue: int
    bucket: str
    risk_score: Decimal
    risk_factor_keys: list[str]
    disputed: bool
    dispute_reason: str | None = None


class CustomerCredit(BaseModel):
    counterparty_token: str
    counterparty_label: str
    open: Money
    avg_days_late: Decimal
    credit_limit: Figure | None = None
    stop_credit: bool = False


class ReceivablesOverview(BaseModel):
    as_of: date
    figures: list[Figure]
    aging: list[AgingRow]
    invoices: list[ReceivableRow]
    customers: list[CustomerCredit]


class ReceivablesPlan(BaseModel):
    reminders: list[ActionCard]


def _ledger(session: Session, tenant_id: str, clock: Clock):
    try:
        found = records(FactStore(session), tenant_id)
    except NotEnoughData:
        return None, None
    if not found.transactions:
        return None, None
    return found, min(clock().astimezone(DHAKA).date(), found.last_day)


def _labels(invoices: tuple[Invoice, ...]) -> dict[str, str]:
    tokens = sorted({inv.counterparty_token for inv in invoices})
    return {token: f"Customer {i}" for i, token in enumerate(tokens, start=1)}


def _abstain() -> JSONResponse:
    body = ApiError(code="not_enough_data", message_key="error.not_enough_data",
                    detail={"missing": "transactions"})
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


def _figures(store: FactStore, tenant_id: str, invoices: tuple[Invoice, ...],
             as_of: date) -> list[Figure]:
    figures = []
    day = Period(start=as_of, end=as_of, granularity=Granularity.day)
    month = Period(start=as_of.replace(day=1),
                   end=as_of.replace(day=calendar.monthrange(as_of.year, as_of.month)[1]),
                   granularity=Granularity.month)
    for metric, period, label in (("receivables", day, "receivables.open"),
                                  ("dso", month, "receivables.dso")):
        try:
            figures.append(record_figure(store, compute(store, tenant_id, metric, period), label))
        except NotComputable:
            continue  # abstain on this figure; the rest of the overview still stands
    overdue = [inv for inv in invoices
               if aging_mod.is_open(inv, as_of) and aging_mod.days_overdue(inv, as_of) > 0]
    total = sum((aging_mod.open_amount(inv) for inv in overdue), Money.zero())
    figures.append(Figure(
        id=f"{tenant_id}:receivables.overdue:{as_of.isoformat()}", label_key="receivables.overdue",
        value=total.amount, unit=Unit.BDT,
        data_mode=invoices[0].data_mode if invoices else figures[0].data_mode,
        provenance=Provenance(formula_id=OVERDUE_FORMULA, formula_version=1,
                              source_row_ids=tuple(sorted(inv.id for inv in overdue)),
                              parameters={"as_of": as_of.isoformat(),
                                          "rule": "open and past due date"})))
    return figures


@router.get("", response_model=ReceivablesOverview)
def overview(principal: Principal = Depends(require(Permission.ledger_read)),
             clock: Clock = Depends(get_clock),
             session: Session = Depends(get_session)) -> ReceivablesOverview | JSONResponse:
    found, as_of = _ledger(session, principal.tenant_id, clock)
    if found is None:
        return _abstain()
    invoices = found.invoices
    labels = _labels(invoices)
    histories = aging_mod.histories(invoices, as_of)
    risks = risk.score_all(invoices, histories, as_of)
    rows = []
    for inv in invoices:
        if inv.id not in risks:
            continue
        days = aging_mod.days_overdue(inv, as_of)
        rows.append(ReceivableRow(
            invoice=inv, counterparty_label=labels[inv.counterparty_token], days_overdue=days,
            bucket=aging_mod.bucket(days), risk_score=risks[inv.id].score,
            risk_factor_keys=risks[inv.id].factor_keys,
            disputed=inv.status.value == "disputed"))
    rows.sort(key=lambda r: (-r.risk_score, r.invoice.id))
    customers = []
    for token, label in labels.items():
        open_total = sum((aging_mod.open_amount(inv) for inv in invoices
                          if inv.counterparty_token == token and inv.id in risks),
                         Money.zero())
        if open_total.amount <= 0:
            continue
        hist = histories.get(token)
        late = hist.median_days_late if hist else Decimal(0)
        customers.append(CustomerCredit(counterparty_token=token, counterparty_label=label,
                                        open=open_total,
                                        avg_days_late=late.quantize(Decimal("0.1"),
                                                                    rounding=ROUND_HALF_UP)))
    customers.sort(key=lambda c: (-c.open.amount, c.counterparty_token))
    return ReceivablesOverview(
        as_of=as_of, figures=_figures(FactStore(session), principal.tenant_id, invoices, as_of),
        aging=[AgingRow(bucket=b.bucket, amount=b.amount, count=b.count)
               for b in aging_mod.aging(invoices, as_of)],
        invoices=rows, customers=customers)


@router.get("/plan", response_model=ReceivablesPlan)
def reminder_plan(principal: Principal = Depends(require(Permission.ledger_read)),
                  clock: Clock = Depends(get_clock),
                  session: Session = Depends(get_session)) -> ReceivablesPlan | JSONResponse:
    found, as_of = _ledger(session, principal.tenant_id, clock)
    if found is None:
        return _abstain()
    labels = _labels(found.invoices)
    reminders = ladder.plan(found.invoices, as_of, labels.__getitem__)
    issue_cards(session, principal.tenant_id, reminders, clock())
    return ReceivablesPlan(reminders=reminders)
