"""Typed tool registry (WP-10 milestone 2; FEATURES N7).

A tool is the only way an agent gets a number: it wraps one engine API, validates its
parameters with a Pydantic model, and returns a `ToolResult` whose every figure carries
provenance (formula id + the facts, source rows or parameters it was computed from). The
registry refuses a result that does not, so a figure without a trail can never reach a
recommendation (CLAUDE.md rule 1).

    registry.run("cash.gaps", ctx, {"buffer": "20000"}) -> ToolResult

Before running, the registry checks that the engine is installed (`ToolUnavailable`) and that
the tenant has the history the tool needs (`InsufficientData`, naming exactly what is
missing). Both become abstentions (milestone 8), never guesses.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.contracts import ActionCard, DataMode, Fact, Figure, Tier
from app.facts import FactStore

# Most cautious first: a result built from any synthetic input is labelled synthetic.
MODE_ORDER = (DataMode.synthetic, DataMode.real_anonymised, DataMode.public, DataMode.live)


class ToolError(Exception):
    """Base class: the tool could not produce a result."""


class UnknownTool(ToolError, KeyError):
    pass


class BadParameters(ToolError):
    def __init__(self, tool: str, errors: list[str]) -> None:
        self.tool, self.errors = tool, errors
        super().__init__(f"{tool}: invalid parameters: {'; '.join(errors)}")


class ToolUnavailable(ToolError):
    """The engine behind the tool is not installed yet (its work package has not landed)."""

    def __init__(self, tool: str, engine: str) -> None:
        self.tool, self.engine = tool, engine
        super().__init__(f"{tool}: the {engine} engine is not available")


class InsufficientData(ToolError):
    """The tenant's data cannot support this tool; `missing` says exactly what to add."""

    def __init__(self, tool: str, missing: Iterable[str], detail: str = "") -> None:
        self.tool, self.missing = tool, tuple(missing)
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"{tool}: missing {', '.join(self.missing)}{suffix}")


class MissingProvenance(ToolError):
    """A tool returned a figure that cannot explain itself. Always a bug in the adapter."""


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def most_cautious(modes: Iterable[DataMode]) -> DataMode:
    present = set(modes)
    return next((m for m in MODE_ORDER if m in present), DataMode.public)


@dataclass(frozen=True)
class ToolResult:
    tool: str
    figures: tuple[Figure, ...] = ()
    facts: tuple[Fact, ...] = ()  # the input facts the figures cite, for the checker
    cards: tuple[ActionCard, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)  # engine contracts, server-side
    notes: tuple[str, ...] = ()  # reason keys, e.g. "financing.no_gap"
    data_mode: DataMode = DataMode.synthetic

    def all_figures(self) -> tuple[Figure, ...]:
        """Figures of the result and of its action cards, each once."""
        seen: dict[str, Figure] = {f.id: f for f in self.figures}
        for card in self.cards:
            for fig in (*card.figures, card.impact, card.cost):
                if fig is not None:
                    seen.setdefault(fig.id, fig)
        return tuple(seen.values())

    def figure(self, label_key: str) -> Figure | None:
        return next((f for f in self.all_figures() if f.label_key == label_key), None)


def check_provenance(result: ToolResult) -> None:
    """Every figure names its formula and cites inputs; every cited fact is in `facts` or
    was recorded in the ledger (WP-01 raw facts cite their source rows instead)."""
    for fig in result.all_figures():
        prov = fig.provenance
        if not prov.formula_id:
            raise MissingProvenance(f"{result.tool}: figure {fig.id} has no formula")
        if not (prov.input_fact_ids or prov.source_row_ids or prov.parameters):
            raise MissingProvenance(f"{result.tool}: figure {fig.id} cites nothing")
    if not result.all_figures() and not result.notes:
        raise MissingProvenance(f"{result.tool}: an empty result must say why (notes)")


@dataclass
class ToolContext:
    """What a tool may read: the tenant's fact ledger, the clock, earlier results of this run.

    Sub-agents run in parallel threads but share one database session, so every store access
    goes through `ctx.db()` (a re-entrant lock); engine maths runs outside it."""

    store: FactStore
    tenant_id: str
    now: datetime
    results: dict[str, ToolResult] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _history: tuple[date, date] | None = field(default=None, repr=False)
    _mode: DataMode | None = field(default=None, repr=False)

    @contextmanager
    def db(self) -> Iterator[FactStore]:
        with self._lock:
            yield self.store

    def history(self) -> tuple[date, date] | None:
        """First and last transaction day of the tenant, or None without transactions."""
        if self._history is None:
            with self.db() as store:
                days = [t.day for t in store.transactions(self.tenant_id)]
            if days:
                self._history = (min(days), max(days))
        return self._history

    @property
    def history_days(self) -> int:
        span = self.history()
        return 0 if span is None else (span[1] - span[0]).days + 1

    @property
    def data_mode(self) -> DataMode:
        """The tenant's data label (synthetic unless its ledger says otherwise)."""
        if self._mode is None:
            with self.db() as store:
                txns = store.transactions(self.tenant_id)
            self._mode = most_cautious(t.data_mode for t in txns) if txns else DataMode.synthetic
        return self._mode

    @property
    def as_of(self) -> date:
        """The ledger's own today: the day of its latest transaction (as WP-04 forecasts)."""
        span = self.history()
        return span[1] if span is not None else self.now.date()


Runner = Callable[[ToolContext, Any], ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str  # "<area>.<verb>", as the planner names it
    description: str
    engine: str  # owner, e.g. "WP-04 cash engine"
    params: type[BaseModel] = NoParams
    tier: Tier = Tier.READ  # what running the tool itself does (cards carry their own tier)
    min_history_days: int = 0  # per-tool data sufficiency (FEATURES N17)
    history_label: str = ""  # what to ask the owner for when history is short
    run: Runner | None = None  # None: the engine has not landed; the tool is unavailable

    @property
    def available(self) -> bool:
        return self.run is not None


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        if tool.tier in (Tier.EXECUTE, Tier.DENY):
            raise ValueError(f"{tool.name}: tools read, suggest or draft; execution needs an "
                             "approved action card")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownTool(name) from None

    def names(self, *, available_only: bool = False) -> list[str]:
        return sorted(n for n, t in self._tools.items() if t.available or not available_only)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def manifest(self) -> list[dict[str, object]]:
        """Plain description of every tool, for the planner prompt and the API."""
        return [{"name": t.name, "description": t.description, "engine": t.engine,
                 "tier": t.tier.value, "available": t.available,
                 "min_history_days": t.min_history_days,
                 "params": sorted(t.params.model_fields)}
                for t in sorted(self._tools.values(), key=lambda t: t.name)]

    def parse(self, name: str, params: Mapping[str, Any] | None) -> BaseModel:
        tool = self.get(name)
        try:
            return tool.params.model_validate(dict(params or {}))
        except ValidationError as exc:
            errors = [f"{'.'.join(map(str, e['loc'])) or '-'}: {e['msg']}" for e in exc.errors()]
            raise BadParameters(name, errors) from None

    def run(self, name: str, ctx: ToolContext,
            params: Mapping[str, Any] | BaseModel | None = None) -> ToolResult:
        tool = self.get(name)
        parsed = params if isinstance(params, BaseModel) else self.parse(name, params)
        if tool.run is None:
            raise ToolUnavailable(name, tool.engine)
        if ctx.history_days < tool.min_history_days:
            raise InsufficientData(name, [tool.history_label or
                                          f"at least {tool.min_history_days} days of "
                                          "transactions"],
                                   f"{ctx.history_days} days on record")
        result = tool.run(ctx, parsed)
        if result.tool != name:
            raise MissingProvenance(f"{name}: result labelled {result.tool}")
        check_provenance(result)
        ctx.results[name] = result
        return result
