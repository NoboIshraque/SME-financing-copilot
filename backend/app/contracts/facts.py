"""Typed facts and provenance (FEATURES N13: every number is clickable)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from app.contracts.common import Contract, DataMode, Period


class Unit(StrEnum):
    BDT = "BDT"
    USD = "USD"
    CNY = "CNY"
    ratio = "ratio"
    percent = "percent"
    days = "days"
    count = "count"
    probability = "probability"
    score = "score"


class FormulaRef(Contract):
    formula_id: str = Field(pattern=r"^[a-z][a-z0-9_.]*$", description="e.g. 'cash.dso'")
    version: int = Field(ge=1)
    expression: str = Field(description="Human-readable formula, e.g. 'receivables / sales * days'")


class Provenance(Contract):
    formula_id: str
    formula_version: int = Field(ge=1)
    input_fact_ids: tuple[str, ...] = ()
    source_row_ids: tuple[str, ...] = ()
    parameters: dict[str, str] = Field(
        default_factory=dict, description="Non-fact inputs such as seed or horizon, as strings"
    )


class Fact(Contract):
    id: str
    tenant_id: str
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Decimal
    unit: Unit
    period: Period
    entity_token: str | None = None
    provenance: Provenance | None = Field(
        default=None, description="None only for raw facts read straight from a source row"
    )
    source_refs: tuple[str, ...] = ()
    data_mode: DataMode
    computed_at: datetime | None = None


class Figure(Contract):
    """A number shown to a user. Always computed by code, always explainable."""

    id: str
    label_key: str = Field(description="i18n key for the label")
    value: Decimal
    unit: Unit
    provenance: Provenance
    data_mode: DataMode


class ExplainedInput(Contract):
    fact_id: str
    metric: str
    value: Decimal
    unit: Unit


class Explanation(Contract):
    """Answer of `GET /explain/{figure_id}`."""

    figure_id: str
    formula: FormulaRef
    value: Decimal
    unit: Unit
    inputs: tuple[ExplainedInput, ...]
    source_rows: tuple[str, ...]
    masked: bool = Field(description="True if source rows were masked for the caller's role")
