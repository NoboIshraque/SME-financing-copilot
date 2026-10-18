"""Builders for ingest tests: files made in memory and a fixed-key party resolver."""

from __future__ import annotations

import io
from collections.abc import Sequence

from openpyxl import Workbook

from app.ingest.parsers import IngestOptions, ParseResult, parse_file
from app.ingest.parties import HmacPartyResolver

KEY = b"test-key-0123456789abcdef"
RESOLVER = HmacPartyResolver(KEY)
T = "tenant_a"

BKASH_HEADER = "TrxID,Date Time,Transaction Type,From/To,Amount (BDT),Fee,Balance,Reference"
BANK_HEADER = "Date,Description,Cheque/Ref No,Debit,Credit,Balance"


def csv_bytes(lines: Sequence[str], encoding: str = "utf-8", newline: str = "\n") -> bytes:
    return (newline.join(lines) + newline).encode(encoding)


def xlsx_bytes(rows: Sequence[Sequence[object]], title: str = "Statement",
               before: Sequence[tuple[str, Sequence[Sequence[object]]]] = ()) -> bytes:
    """A workbook whose sheets `before` come first, then a sheet `title` holding `rows`."""
    book = Workbook()
    first = True
    for name, sheet_rows in [*before, (title, rows)]:
        sheet = book.active if first else book.create_sheet()
        first = False
        sheet.title = name
        for row in sheet_rows:
            sheet.append(list(row))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def parse(data: bytes, filename: str, tenant: str = T, **options: object) -> ParseResult:
    return parse_file(data, IngestOptions(tenant_id=tenant, filename=filename, **options),
                      RESOLVER)


def bkash(*rows: str) -> bytes:
    return csv_bytes([BKASH_HEADER, *rows])


def bank(*rows: str) -> bytes:
    return csv_bytes([BANK_HEADER, *rows])


def reasons(result: ParseResult) -> list[str]:
    return [u.reason_key for u in result.unparsed]
