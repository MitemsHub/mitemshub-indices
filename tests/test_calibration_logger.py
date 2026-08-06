from __future__ import annotations

import json
from pathlib import Path

from synthetic_trader.live.calibration_logger import append_call_record, build_call_record
from synthetic_trader.live.market_snapshot import build_watch_alert


def test_build_call_record_serializes_actionable_r75_geometry() -> None:
    alert = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "trade_status": "valid",
        "guardian_state": "actionable",
        "direction_bias": "buy",
        "confidence": 0.76,
        "entry": 55620.0,
        "execution_stop": 55280.0,
        "primary_target": 56180.0,
        "thesis_invalidation": 52541.0,
        "hold_horizon_minutes": 60,
        "why": "buyers still control continuation",
        "wait_for": "wait for the 5m continuation trigger to confirm, then manage toward the next hour objective",
        "decision_summary": "4H bullish; 1H setup aligns; 15m continuation aligns",
        "current_close": 55580.0,
        "model_version": "online-logistic-v1",
    }

    record = build_call_record(alert)

    assert record["symbol"] == "R_75"
    assert record["primary_target"] == 56180.0
    assert record["guardian_state"] == "actionable"
    assert record["recorded_at"]


def test_build_call_record_serializes_forming_r100_with_null_geometry() -> None:
    alert = {
        "symbol": "R_100",
        "call": "stand_aside",
        "trade_status": "not_valid",
        "guardian_state": "forming",
        "direction_bias": "buy",
        "confidence": 0.46,
        "entry": None,
        "execution_stop": None,
        "primary_target": None,
        "thesis_invalidation": None,
        "hold_horizon_minutes": None,
        "why": "current movement is active but not a clean setup yet",
        "wait_for": "wait for a cleaner entry so reward outweighs the risk",
        "decision_summary": None,
        "current_close": 483.84,
        "model_version": "online-logistic-v1",
    }

    record = build_call_record(alert)

    assert record["symbol"] == "R_100"
    assert record["primary_target"] is None
    assert record["guardian_state"] == "forming"


def test_build_call_record_uses_watch_alert_shape_from_live_snapshot() -> None:
    snapshot = {
        "call": "buy_candidate",
        "symbol": "R_75",
        "briefing": "buyers still control continuation",
        "trade_status": "valid",
        "direction_bias": "buy",
        "regime": "trend_up",
        "confidence": 0.76,
        "current_close": 55580.0,
        "guardian_state": "actionable",
        "guardian_reason": "setup remains aligned",
        "entry": 55620.0,
        "execution_stop": 55280.0,
        "primary_target": 56180.0,
        "thesis_invalidation": 52541.0,
        "hold_horizon_minutes": 60,
        "decision_summary": "4H bullish; 1H aligns; 15m confirms",
        "why": "buyers still control continuation",
        "wait_for": "wait for the 5m continuation trigger to confirm, then manage toward the next hour objective",
        "invalidates_if": "5m close back below 55280.0 invalidates the execution attempt",
    }

    alert = build_watch_alert(snapshot)
    record = build_call_record(alert)

    assert record["symbol"] == "R_75"
    assert record["primary_target"] == 56180.0
    assert record["trigger_type"] == "setup_candidate"
    assert record["regime"] == "trend_up"
    assert record["guardian_reason"] == "setup remains aligned"
    assert (
        record["invalidates_if"]
        == "5m close back below 55280.0 invalidates the execution attempt"
    )


def test_build_call_record_resolves_levels_from_prepared_state_alert() -> None:
    """The prepared-state alert builder only sets stop_loss/take_profit, but the
    calls journal must persist scorable execution_stop/primary_target levels -
    otherwise every scored outcome is target=0% and the gate suppresses
    everything."""
    alert = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "trade_status": "valid",
        "alert_type": "setup_candidate",
        "entry": 1542.5,
        "stop_loss": 1539.0,
        "take_profit": 1550.0,
        "current_close": 1542.5,
        "generated_at": "2026-08-05T15:00:00+00:00",
    }

    record = build_call_record(alert)

    assert record["execution_stop"] == 1539.0
    assert record["primary_target"] == 1550.0
    # No explicit hold horizon on the alert -> scorer default 60.
    assert record["hold_horizon_minutes"] == 60


def test_build_call_record_keeps_main_path_levels_untouched() -> None:
    """Alerts that already carry execution_stop/primary_target (main
    build_watch_alert path) must not be clobbered by the alias fallback."""
    alert = {
        "symbol": "R_75",
        "call": "sell_candidate",
        "trade_status": "valid",
        "entry": 1545.0,
        "execution_stop": 1548.5,
        "primary_target": 1535.0,
        "stop_loss": 0.0,  # deliberately different - must NOT win
        "take_profit": 9999.0,
        "hold_horizon_minutes": 120,
        "generated_at": "2026-08-05T15:00:00+00:00",
    }

    record = build_call_record(alert)

    assert record["execution_stop"] == 1548.5
    assert record["primary_target"] == 1535.0
    assert record["hold_horizon_minutes"] == 120


def test_append_call_record_appends_jsonl_line(tmp_path: Path) -> None:
    output_path = tmp_path / "journals" / "live_calibration_calls.jsonl"

    append_call_record(
        output_path,
        {
            "symbol": "R_75",
            "guardian_state": "actionable",
            "primary_target": 56180.0,
        },
    )
    append_call_record(
        output_path,
        {
            "symbol": "R_100",
            "guardian_state": "forming",
            "primary_target": None,
        },
    )

    written_lines = output_path.read_text(encoding="utf-8").splitlines()

    assert len(written_lines) == 2
    assert json.loads(written_lines[0])["symbol"] == "R_75"
    assert json.loads(written_lines[1])["primary_target"] is None
