"""Business financial analysis (WP-07): ratios, variance, scenarios, stability (N1, N12, N16)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, Money, Period, Probability
from app.contracts.facts import Provenance, Unit


class Ratio(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="e.g. 'current_ratio'")
    value: Decimal | None = Field(description="None when the denominator is zero or missing")
    unit: Unit
    period: Period
    provenance: Provenance
    benchmark: Decimal | None = None
    interpretation_key: str | None = None


class Variance(Contract):
    metric: str
    period: Period
    expected: Decimal
    actual: Decimal
    unit: Unit
    rank: int = Field(ge=1)

    @property
    def difference(self) -> Decimal:
        return self.actual - self.expected

    @property
    def percent(self) -> Decimal | None:
        if self.expected == 0:
            return None
        return (self.difference / abs(self.expected) * 100).quantize(Decimal("0.01"))


class Scenario(Contract):
    id: str
    name_key: str
    assumptions: dict[str, Decimal] = Field(
        description="Shock name -> size, e.g. {'sales_change_pct': -20}"
    )
    expected_outcome: Money
    worst_5pct_outcome: Money
    p_buffer_breach: Probability
    paths: int = Field(ge=1)
    seed: int

    @model_validator(mode="after")
    def _worst_not_above_expected(self) -> Scenario:
        if self.worst_5pct_outcome > self.expected_outcome:
            raise ValueError("worst 5% outcome cannot exceed the expected outcome")
        return self


class VariationKind(StrEnum):
    stress = "stress"  # an economic change that SHOULD be able to change the decision
    noise = "noise"  # irrelevant change that must NOT change the decision


class VariationResult(Contract):
    name: str = Field(description="e.g. 'sales_minus_20' or 'rows_shuffled'")
    kind: VariationKind
    choice: str
    held: bool


class StabilityReport(Contract):
    recommendation_id: str
    baseline_choice: str
    results: tuple[VariationResult, ...] = Field(min_length=1)
    score: Probability = Field(description="Share of variations where the choice held")
    what_would_flip: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _score_matches(self) -> StabilityReport:
        held = sum(1 for r in self.results if r.held)
        expected = Decimal(held) / Decimal(len(self.results))
        if abs(expected - self.score) > Decimal("0.0001"):
            raise ValueError("score does not match the variation results")
        for result in self.results:
            if result.held != (result.choice == self.baseline_choice):
                raise ValueError(f"variation {result.name}: held flag disagrees with choice")
        return self

    @property
    def noise_flips(self) -> int:
        return sum(1 for r in self.results if r.kind is VariationKind.noise and not r.held)

    @property
    def unreliable(self) -> bool:
        """Any flip on irrelevant noise means the decision cannot be trusted."""
        return self.noise_flips > 0
