"""Ingest API (WP-02 milestone 5).

    POST /api/ingest/preview   multipart: file, tenant_id [, document_kind, day_first,
                               default_channel, mapping (JSON)]           -> IngestPreview
    POST /api/ingest/columns   multipart: file, tenant_id                 -> ColumnsView
    POST /api/ingest/commit    JSON CommitRequest                         -> CommitResponse
    GET  /api/ingest/history?tenant_id=&limit=                            -> [HistoryItem]

A preview writes nothing to the ledger. A commit needs the preview's keyed digest and commits
drafts only when the owner confirms them. Errors are `ApiError` bodies.

The caller is the signed-in principal (WP-11 `current_principal`): without a session every
route answers 401. The tenant always comes from the principal; a `tenant_id` in the form, query
or body is optional and must then name the caller's own tenant (403 otherwise). Preview and
column mapping need `ingest:upload` (owner, accountant, staff). Committing writes the shop's
ledger, so it is allowed only for the owner or accountant.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.contracts import ApiError, Channel, IngestPreview, Principal, Role
from app.ingest.formats import LEDGER
from app.ingest.normalise import DHAKA
from app.ingest.ocr import TesseractEngine
from app.ingest.parsers import IngestOptions
from app.ingest.parties import mask_excerpt
from app.ingest.preview import MAX_UPLOAD_BYTES, IngestError, IngestService
from app.ingest.tabular import TableError, read_sheets
from app.main import get_session
from app.security.deps import current_principal, require
from app.security.errors import ProblemRoute
from app.security.roles import Permission

router = APIRouter(tags=["ingest"], route_class=ProblemRoute)
COMMIT_ROLES = frozenset({Role.owner, Role.accountant})


class CommitRequest(BaseModel):
    tenant_id: str | None = Field(default=None, max_length=64)  # optional; must be the caller's
    preview_id: str = Field(min_length=1, max_length=64)
    file_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: list[str] = Field(default_factory=list, max_length=5000)
    amounts: dict[str, str] = Field(default_factory=dict)


class CommitResponse(BaseModel):
    preview_id: str
    transactions: int
    invoices: int
    bills: int
    drafts_confirmed: int
    duplicates_skipped: int
    committed_at: datetime


class HistoryItem(CommitResponse):
    filename: str
    source_format: str
    file_digest: str
    data_mode: str
    unparsed: int


class ColumnsView(BaseModel):
    """Header candidates for the generic-ledger mapping step (values masked)."""

    rows: list[list[str]]
    fields: list[str]
    suggested: dict[str, str]


def _tenant(principal: Principal, requested: str | None) -> str | JSONResponse:
    """The caller's tenant; a requested tenant_id must be that same tenant."""
    if requested and requested != principal.tenant_id:
        return _error(403, "forbidden", reason="tenant")
    return principal.tenant_id


def _error(status: int, code: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=f"error.{code}",
                    detail={k: str(v)[:128] for k, v in detail.items()})
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _service(request: Request, session: Session) -> IngestService:
    secret = request.app.state.settings.secret_key.get_secret_value()
    return IngestService(session, secret)


async def _read(file: UploadFile) -> bytes | JSONResponse:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return _error(413, "file_too_large", max_bytes=str(MAX_UPLOAD_BYTES))
    return data


def _options(tenant_id: str, filename: str, document_kind: str | None, day_first: str | None,
             default_channel: str | None, mapping: str | None) -> IngestOptions | JSONResponse:
    try:
        columns = json.loads(mapping) if mapping else None
        if columns is not None and not (isinstance(columns, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in columns.items())):
            raise ValueError("mapping must be an object of strings")
        flag = None if day_first in (None, "") else day_first.lower() in ("true", "1", "yes")
        channel = Channel(default_channel) if default_channel else Channel.cash
    except ValueError:
        return _error(422, "invalid_options")
    if document_kind not in (None, "", "invoice", "bill"):
        return _error(422, "invalid_options")
    return IngestOptions(tenant_id=tenant_id, filename=filename[:200] or "upload",
                         mapping=columns, document_kind=document_kind or None,
                         default_channel=channel, day_first=flag)


@router.post("/ingest/preview", response_model=IngestPreview)
async def preview(
    request: Request,
    file: UploadFile = File(...),
    tenant_id: str = Form(""),
    document_kind: str | None = Form(None),
    day_first: str | None = Form(None),
    default_channel: str | None = Form(None),
    mapping: str | None = Form(None),
    principal: Principal = Depends(require(Permission.ingest_upload)),
    session: Session = Depends(get_session),
) -> IngestPreview | JSONResponse:
    tenant = _tenant(principal, tenant_id)
    if isinstance(tenant, JSONResponse):
        return tenant
    data = await _read(file)
    if isinstance(data, JSONResponse):
        return data
    opts = _options(tenant, file.filename or "upload", document_kind, day_first,
                    default_channel, mapping)
    if isinstance(opts, JSONResponse):
        return opts
    engine = TesseractEngine() if TesseractEngine.available() else None
    try:
        return _service(request, session).preview(
            data, opts, reference=datetime.now(DHAKA).date(), engine=engine)
    except IngestError as exc:
        return _error(exc.status, exc.code)


@router.post("/ingest/columns", response_model=ColumnsView)
async def columns(
    request: Request,
    file: UploadFile = File(...),
    tenant_id: str = Form(""),
    principal: Principal = Depends(require(Permission.ingest_upload)),
) -> ColumnsView | JSONResponse:
    tenant = _tenant(principal, tenant_id)
    if isinstance(tenant, JSONResponse):
        return tenant
    data = await _read(file)
    if isinstance(data, JSONResponse):
        return data
    try:
        sheets = read_sheets(data, file.filename or "upload")
    except TableError as exc:
        return _error(422, exc.reason_key.rsplit(".", 1)[-1])
    rows = [r.cells for r in sheets[0].rows if not r.blank][:5] if sheets else []
    suggested: dict[str, str] = {}
    if rows:
        mapping = LEDGER.map_header(rows[0])
        suggested = {name: rows[0][index] for name, index in mapping.items()}
    return ColumnsView(rows=[[mask_excerpt(c, limit=60) for c in row] for row in rows],
                       fields=list(LEDGER.columns), suggested=suggested)


@router.post("/ingest/commit", response_model=CommitResponse)
def commit(
    request: Request,
    body: CommitRequest,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> CommitResponse | JSONResponse:
    tenant = _tenant(principal, body.tenant_id)
    if isinstance(tenant, JSONResponse):
        return tenant
    if principal.role not in COMMIT_ROLES:
        return _error(403, "not_permitted")
    try:
        result = _service(request, session).commit(tenant, body.preview_id,
                                                   body.file_digest, confirm=body.confirm,
                                                   amounts=body.amounts)
    except IngestError as exc:
        return _error(exc.status, exc.code)
    return CommitResponse(**result.__dict__)


@router.get("/ingest/history", response_model=list[HistoryItem])
def history(
    request: Request,
    tenant_id: str = "",
    limit: str = "50",
    principal: Principal = Depends(require(Permission.ledger_read)),
    session: Session = Depends(get_session),
) -> list[HistoryItem] | JSONResponse:
    tenant = _tenant(principal, tenant_id)
    if isinstance(tenant, JSONResponse):
        return tenant
    try:
        size = int(limit)
    except ValueError:
        size = 0
    if not 1 <= size <= 200:
        return _error(422, "invalid_limit")
    entries = _service(request, session).history(tenant, size)
    return [HistoryItem(**{**e.__dict__, "data_mode": e.data_mode.value}) for e in entries]
