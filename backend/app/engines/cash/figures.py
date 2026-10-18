"""Every number the cash engine shows, as a `Figure` with its formula and provenance (WP-04).

A figure carries: the formula id and version (`FORMULAS`), the input fact ids the caller vouches
for (`Evidence`: the opening-balance fact, the buffer figure, ...), the records behind it
('bill:<id>', 'inv:<id>', 'obl:<id>') and the simulation parameters (as_of, horizon, paths,
seed, scenario). The API records each figure in the fact ledger, so `/explain` can open it.
Figure ids are content hashes: the same inputs always give the same id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import Figure, FormulaRef, Provenance, Unit
from app.engines.cash.simulate import Simulation

_QUANTUM = {Unit.BDT: Decimal("0.01"), Unit.USD: Decimal("0.01"), Unit.CNY: Decimal("0.01"),
            Unit.probability: Decimal("0.0001"), Unit.ratio: Decimal("0.0001"),
            Unit.percent: Decimal("0.01"), Unit.days: Decimal(1), Unit.count: Decimal(1),
            Unit.score: Decimal("0.1")}


def quantize(value: Decimal, unit: Unit) -> Decimal:
    return value.quantize(_QUANTUM[unit], rounding=ROUND_HALF_UP)


_EXPRESSIONS = {
    "cash.forecast_band": "nearest-rank P10/P50/P90 of the end-of-day balance over the seeded "
                          "Monte Carlo paths",
    "cash.p_below_buffer": "paths with end-of-day balance < buffer / paths",
    "cash.gap_probability": "paths below the buffer on at least one day of the gap / paths",
    "cash.expected_shortfall": "mean over all paths of max(0, buffer - lowest balance during "
                               "the gap)",
    "cash.lead_time_days": "first breach day - as_of",
    "cash.dso_30d": "receivables at the end of the 30 days / invoices issued in them x 30",
    "cash.customer_delay_median": "median of (paid date - due date) over the customer's "
                                  "invoices settled in the period",
    "cash.days_overdue": "as_of - due date of the customer's oldest open invoice",
    "cash.purchase_to_sales": "(cash purchases + bills issued) / (cash sales + invoices "
                              "issued) over the period",
    "cash.sales_vs_norm": "actual sales over the last 14 days; norm = what the seasonal model "
                          "fitted before them expected",
    "cash.p50_on_due_day": "likely (P50) end-of-day balance on the day a salary or EMI is due",
}
FORMULAS: dict[str, FormulaRef] = {
    formula_id: FormulaRef(formula_id=formula_id, version=1, expression=expression)
    for formula_id, expression in _EXPRESSIONS.items()
}


@dataclass(frozen=True)
class Evidence:
    """Facts a caller vouches for, cited by every figure built from them (the API passes the
    opening-balance fact id; pure callers may pass none)."""

    input_fact_ids: tuple[str, ...] = ()


NO_EVIDENCE = Evidence()


def sim_parameters(sim: Simulation) -> dict[str, str]:
    return {"as_of": sim.baseline.as_of.isoformat(), "horizon_days": str(sim.baseline.horizon),
            "paths": str(sim.paths), "seed": str(sim.seed), "scenario": sim.scenario.name}


def make_figure(sim: Simulation, formula_id: str, label_key: str, value: Decimal, unit: Unit,
                evidence: Evidence = NO_EVIDENCE, rows: Iterable[str] = (),
                params: Mapping[str, object] | None = None) -> Figure:
    formula = FORMULAS[formula_id]
    parameters = {**sim_parameters(sim), **{k: str(v) for k, v in (params or {}).items()}}
    source_rows = tuple(dict.fromkeys(rows))
    key = json.dumps([sim.baseline.tenant_id, formula_id, formula.version, label_key,
                      parameters, list(source_rows), list(evidence.input_fact_ids)],
                     sort_keys=True)
    return Figure(
        id="cash_" + hashlib.sha256(key.encode()).hexdigest()[:24], label_key=label_key,
        value=quantize(value, unit), unit=unit, data_mode=sim.baseline.data_mode,
        provenance=Provenance(formula_id=formula_id, formula_version=formula.version,
                              input_fact_ids=evidence.input_fact_ids,
                              source_row_ids=source_rows, parameters=parameters))
