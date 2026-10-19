"""Checks on ML artefacts committed by WP-17 notebooks (no ML libraries needed)."""

import json
from pathlib import Path

import pytest

ART = Path(__file__).resolve().parents[3] / "ml" / "artifacts"
SCHEMA = json.loads((ART / "payment_delay_schema.json").read_text())
METRICS = json.loads((ART / "payment_delay_metrics.json").read_text())
FIXTURE = json.loads((ART / "payment_delay_fixture.json").read_text())


def lgb_feature_names(path: Path) -> list[str]:
    for line in path.read_text().splitlines():
        if line.startswith("feature_names="):
            return line.split("=", 1)[1].split()
    raise AssertionError(f"{path.name} has no feature_names line")


@pytest.mark.parametrize("model", ["payment_delay_days.txt", "payment_late7_prob.txt"])
def test_models_were_trained_on_exactly_the_documented_features(model):
    assert lgb_feature_names(ART / model) == SCHEMA["features"]


def test_metrics_say_which_data_they_come_from():
    assert METRICS["data_mode"] in {"synthetic", "mixed"}
    assert "synthetic" in METRICS["data"]
    assert METRICS["split"].startswith("time:")  # no random split: no leakage across time


def test_the_simpler_model_wins_unless_lightgbm_is_clearly_better():
    mae = METRICS["mae_days"]
    gain = 1 - mae["lightgbm"] / mae["customer_mean_baseline"]
    expected = "lightgbm" if gain >= 0.05 else "customer_history_baseline"
    assert METRICS["decision"]["use"] == expected


def test_fixture_rows_match_the_schema_for_deterministic_inference_checks():
    assert len(FIXTURE) == 5
    for row in FIXTURE:
        assert set(SCHEMA["features"]) <= set(row)
        assert row["sector"] in SCHEMA["categorical"]["sector"]


def test_forecast_backtest_report_is_well_formed_when_present():
    path = ART / "forecast_backtest.json"
    if not path.exists():
        pytest.skip("notebook 01 has not been run on Kaggle yet")
    report = json.loads(path.read_text())
    assert report["data_mode"] == "public" and report["chosen_model"] in report["models"]
    for model in report["models"].values():
        assert 0 <= model["coverage_80_mean"] <= 1


INJECTION_METRICS = sorted(ART.glob("injection_metrics*.json"))


@pytest.mark.parametrize("path", INJECTION_METRICS, ids=[p.name for p in INJECTION_METRICS])
def test_injection_threshold_is_chosen_off_the_test_split(path):
    # Picking the threshold (or the checkpoint) on test would make test recall a given, not a
    # measurement. Notebook 03 picks both on held-out training families.
    metrics = json.loads(path.read_text(encoding="utf-8"))
    assert "validation" in metrics["threshold_rule"]
    assert set(metrics["validation_families"]).isdisjoint(metrics["test_families"])
    assert metrics["validation"]["recall"] >= 0.95  # the rule held where it was applied
