"""Tests for the automatic live-call scoring service (live/auto_scorer.py)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from synthetic_trader.live.auto_scorer import (
    _count_pending_calls,
    run_auto_score_loop,
    sweep_once,
)
from synthetic_trader.live.calibration_scorer import CalibrationScoringResult


def _write_calls(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _call(symbol: str, generated_at: str) -> dict:
    return {
        "symbol": symbol,
        "generated_at": generated_at,
        "call": "buy_candidate",
        "trade_status": "valid",
        "trigger_type": "continuation_close",
        "entry": 100.0,
        "execution_stop": 99.0,
        "primary_target": 101.0,
        "current_close": 100.0,
        "hold_horizon_minutes": 60,
    }


def test_single_sweep_scores_resolved_calls(tmp_path: Path, monkeypatch) -> None:
    calls = tmp_path / "calls.jsonl"
    outcomes = tmp_path / "outcomes.jsonl"
    _write_calls(
        calls,
        [
            # 2+ hours old -> hold horizon elapsed -> scored.
            _call("R_75", "2026-07-12T08:00:00+00:00"),
            _call("R_75", "2026-07-12T08:05:00+00:00"),
            # 10 minutes old -> still within the hold window -> skipped.
            _call("R_100", "2026-07-12T11:55:00+00:00"),
        ],
    )

    def fake_run(**kwargs):
        return CalibrationScoringResult(scored_records=2, failed_records=0, skipped_records=1)

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_score_unresolved_records_from_market",
        fake_run,
    )
    # Scoring has no Deriv fallback: without MT5 configured the sweep fails
    # before ever calling the scorer, so pretend MT5 is available.
    monkeypatch.setattr(
        "synthetic_trader.execution.mt5_data.is_mt5_configured",
        lambda: True,
    )
    # Freeze "now" mid-2026-07-12 so the 2h-old records are resolved.
    from datetime import datetime, timezone

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.datetime",
        type(
            "FakeDatetime",
            (),
            {
                "now": staticmethod(lambda tz=None: datetime(2026, 7, 12, 12, 0, tzinfo=tz or timezone.utc)),
                "utcnow": staticmethod(lambda: datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)),
            },
        ),
    )

    stats = asyncio.run(
        run_auto_score_loop(
            calls_path=calls,
            outcomes_path=outcomes,
            run_once=True,
            status_path=tmp_path / "status.json",
        )
    )
    assert stats["ALL"].calls_scored == 2
    assert stats["ALL"].calls_skipped == 1
    assert stats["ALL"].calls_failed == 0
    # Status telemetry written.
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert "symbols" in status
    assert status["symbols"]["ALL"]["calls_scored"] == 2


def test_pending_count_tracks_unscored_backlog(tmp_path: Path) -> None:
    calls = tmp_path / "calls.jsonl"
    outcomes = tmp_path / "outcomes.jsonl"
    _write_calls(calls, [_call("R_75", "2026-07-12T08:00:00+00:00"), _call("R_75", "2026-07-12T08:05:00+00:00")])
    # One already scored.
    outcomes.write_text(
        json.dumps({"symbol": "R_75", "generated_at": "2026-07-12T08:00:00+00:00", "outcome_label": "target_hit"})
        + "\n",
        encoding="utf-8",
    )
    assert _count_pending_calls(calls, outcomes) == 1


def test_sweep_once_writes_status_and_reports_failure(tmp_path: Path, monkeypatch) -> None:
    """The public single-sweep entry point records a failure on the status
    file instead of raising, so callers (live-watch auto-sweep) can rely on it
    never crashing the watch."""

    def boom(**kwargs):
        raise RuntimeError("deriv_unavailable")

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_score_unresolved_records_from_market",
        boom,
    )
    # Scoring has no Deriv fallback: the sweep must resolve MT5 first, so
    # pretend MT5 is configured to reach the mocked scorer.
    monkeypatch.setattr(
        "synthetic_trader.execution.mt5_data.is_mt5_configured",
        lambda: True,
    )
    status_path = tmp_path / "status.json"
    stats = sweep_once(
        calls_path=tmp_path / "calls.jsonl",
        outcomes_path=tmp_path / "outcomes.jsonl",
        status_path=status_path,
    )
    assert stats.error is not None
    assert "deriv_unavailable" in stats.error
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["symbols"]["ALL"]["error"] is not None


def test_loop_writes_status_even_when_sweep_fails(tmp_path: Path, monkeypatch) -> None:
    def boom(**kwargs):
        raise RuntimeError("deriv_unavailable")

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_score_unresolved_records_from_market",
        boom,
    )
    # Scoring has no Deriv fallback: the sweep must resolve MT5 first, so
    # pretend MT5 is configured to reach the mocked scorer.
    monkeypatch.setattr(
        "synthetic_trader.execution.mt5_data.is_mt5_configured",
        lambda: True,
    )
    stats = asyncio.run(
        run_auto_score_loop(
            calls_path=tmp_path / "calls.jsonl",
            outcomes_path=tmp_path / "outcomes.jsonl",
            run_once=True,
            status_path=tmp_path / "status.json",
        )
    )
    entry = stats["ALL"]
    assert entry.error is not None
    assert "deriv_unavailable" in entry.error
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["symbols"]["ALL"]["error"] is not None


def test_sweep_once_prefers_mt5_client_when_configured(tmp_path: Path, monkeypatch) -> None:
    """When SYNTHETIC_MT5_* is configured, scoring must use the Deriv MT5
    terminal so outcomes are measured on the same SYN75/SYN100 scale as the
    call levels -- never the Deriv 1HZ75V fallback (~7,000 vs ~1,542)."""
    captured: dict = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return CalibrationScoringResult(scored_records=0, failed_records=0, skipped_records=0)

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_score_unresolved_records_from_market",
        fake_run,
    )
    monkeypatch.setattr(
        "synthetic_trader.execution.mt5_data.is_mt5_configured",
        lambda: True,
    )

    from synthetic_trader.live.auto_scorer import _sweep_once

    stats = _sweep_once(
        calls_path=tmp_path / "calls.jsonl",
        outcomes_path=tmp_path / "outcomes.jsonl",
        symbol=None,
        window_minutes=None,
        app_id=None,
    )
    assert captured.get("client_factory") is not None
    assert stats.warning is None


def test_sweep_once_errors_when_mt5_unavailable_no_deriv_fallback(tmp_path: Path, monkeypatch) -> None:
    """Without MT5 config the sweep must FAIL — there is no Deriv fallback.
    Deriv's 1HZ75V/1HZ100V are on the WRONG price scale vs the call levels
    (SYN75/SYN100), so scoring without the Deriv terminal is a hard
    error, never a warning, and the scorer is never invoked."""
    called: dict = {}

    def fake_run(**kwargs):
        called["hit"] = True
        return CalibrationScoringResult(scored_records=0, failed_records=0, skipped_records=0)

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_score_unresolved_records_from_market",
        fake_run,
    )
    monkeypatch.setattr(
        "synthetic_trader.execution.mt5_data.is_mt5_configured",
        lambda: False,
    )

    from synthetic_trader.live.auto_scorer import sweep_once

    stats = sweep_once(
        calls_path=tmp_path / "calls.jsonl",
        outcomes_path=tmp_path / "outcomes.jsonl",
        status_path=tmp_path / "status.json",
    )
    assert called.get("hit") is not True  # scorer never ran on wrong scale
    assert stats.error is not None
    assert "MT5" in stats.error
    assert "fallback" in stats.error.lower() or "removed" in stats.error.lower()
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["symbols"]["ALL"]["error"] is not None
