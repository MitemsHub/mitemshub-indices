"""Tests for the calibration health stats (synthetic_trader.scripts.calibration_health)."""

from __future__ import annotations

import json
from pathlib import Path

from synthetic_trader.scripts.calibration_health import (
    get_calibration_health,
    summarize_trigger_rates,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_get_calibration_health_reads_cache_and_outcomes(tmp_path: Path) -> None:
    engine_root = tmp_path
    _write_jsonl(
        engine_root / "data" / "forecast_verdicts.json",
        [
            {
                "R_75": {
                    "4h": {"verdict": "calibrated", "windows": 42, "coverage_p50": 0.52, "coverage_p90": 0.91},
                    "6h": {"verdict": "calibrated", "windows": 38, "coverage_p50": 0.48, "coverage_p90": 0.89},
                },
                "R_100": {
                    "4h": {"verdict": "needs_more_data_or_tuning", "windows": 31, "coverage_p50": 0.24, "coverage_p90": 0.80},
                    "6h": {"verdict": "needs_more_data_or_tuning", "windows": 29, "coverage_p50": 0.23, "coverage_p90": 0.79},
                },
            }
        ],
    )
    _write_jsonl(
        engine_root / "journals" / "live_calibration_outcomes.jsonl",
        [
            {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "target_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0},
            {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "target_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0},
            {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "stop_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0},
            {"symbol": "R_100", "trigger_type": "reclaim_pullback", "trade_status": "valid", "outcome_label": "stop_hit", "entry": 300.0, "execution_stop": 297.0, "primary_target": 305.0},
        ],
    )

    result = get_calibration_health(str(engine_root))

    r75 = result["R_75"]
    assert r75["cache_fresh"] is True
    assert r75["horizons"]["4h"]["verdict"] == "calibrated"
    assert r75["horizons"]["4h"]["windows"] == 42
    assert r75["horizons"]["4h"]["coverage_p50"] == 0.52
    assert r75["horizons"]["4h"]["coverage_p90"] == 0.91

    trigger = next(t for t in r75["triggers"] if t["trigger_type"] == "continuation_close")
    assert trigger["count"] == 3
    assert trigger["target_hit_rate"] == round(2 / 3, 4)
    assert trigger["stop_hit_rate"] == round(1 / 3, 4)
    assert trigger["enough_samples"] is False  # 3 < 10

    r100 = result["R_100"]
    assert r100["cache_fresh"] is True
    assert r100["horizons"]["4h"]["verdict"] == "needs_more_data_or_tuning"
    assert [t["trigger_type"] for t in r100["triggers"]] == ["reclaim_pullback"]


def test_get_calibration_health_missing_files(tmp_path: Path) -> None:
    result = get_calibration_health(str(tmp_path))
    r75 = result["R_75"]
    assert r75["cache_fresh"] is False
    assert r75["horizons"]["4h"]["verdict"] is None
    assert r75["horizons"]["4h"]["windows"] is None
    assert r75["triggers"] == []


def test_summarize_trigger_rates_groups_by_symbol_and_trigger(tmp_path: Path) -> None:
    path = tmp_path / "outcomes.jsonl"
    _write_jsonl(
        path,
        [
            {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "target_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0},
            {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "stop_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0},
            {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "not_valid", "outcome_label": "target_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0},
            {"symbol": "R_75", "trigger_type": "reclaim_pullback", "trade_status": "valid", "outcome_label": "neither_reached", "entry": 300.0, "execution_stop": 297.0, "primary_target": 305.0},
            {"symbol": "R_100", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "target_hit", "entry": 400.0, "execution_stop": 398.0, "primary_target": 403.0},
        ],
    )
    rates = summarize_trigger_rates(outcomes_path=path)

    r75 = {t["trigger_type"]: t for t in rates["R_75"]}
    assert r75["continuation_close"]["count"] == 3
    assert r75["continuation_close"]["target_hit_rate"] == round(2 / 3, 4)
    assert r75["reclaim_pullback"]["count"] == 1
    assert r75["reclaim_pullback"]["target_hit_rate"] == 0.0
    assert rates["R_100"][0]["trigger_type"] == "continuation_close"


def test_summarize_trigger_rates_marks_suppressed_below_floor(tmp_path: Path) -> None:
    """A trigger type with >= MIN_SAMPLES outcomes and a hit rate below the
    gate floor is flagged suppressed — the same rule the Stage-3 gate uses.
    """
    path = tmp_path / "outcomes.jsonl"
    rows = [
        {"symbol": "R_75", "trigger_type": "breakout_fade", "trade_status": "valid", "outcome_label": "stop_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0}
        for _ in range(12)  # 12 scored, 0% hit rate -> below the 0.5 floor
    ]
    rows.append(
        {"symbol": "R_75", "trigger_type": "continuation_close", "trade_status": "valid", "outcome_label": "target_hit", "entry": 100.0, "execution_stop": 98.0, "primary_target": 102.0}
    )
    _write_jsonl(path, rows)
    rates = summarize_trigger_rates(outcomes_path=path)
    r75 = {t["trigger_type"]: t for t in rates["R_75"]}

    assert r75["breakout_fade"]["enough_samples"] is True
    assert r75["breakout_fade"]["target_hit_rate"] == 0.0
    assert r75["breakout_fade"]["suppressed"] is True
    # Not enough samples yet -> not flagged suppressed even at 0% hit rate.
    assert r75["continuation_close"]["enough_samples"] is False
    assert r75["continuation_close"]["suppressed"] is False


def test_summarize_trigger_rates_missing_journal(tmp_path: Path) -> None:
    assert summarize_trigger_rates(outcomes_path=tmp_path / "nope.jsonl") == {}
