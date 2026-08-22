from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

_JOURNAL_DIR = Path(tempfile.mkdtemp(prefix="mitems-test-journals-"))

from synthetic_trader.cli import build_parser, main
from synthetic_trader.live.calibration_scorer import CalibrationScoringResult


def test_build_parser_exposes_log_live_call_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["log-live-call", "--symbol", "R_75", "--payload-json", "call.json"])

    assert args.command == "log-live-call"


def test_build_parser_exposes_score_live_calibration_command() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["score-live-calibration", "--calls-journal", str(_JOURNAL_DIR / "live_calibration_calls.jsonl")]
    )

    assert args.command == "score-live-calibration"


def test_build_parser_exposes_score_live_loop_command() -> None:
    parser = build_parser()

    args = parser.parse_args(["score-live-loop", "--once"])

    assert args.command == "score-live-loop"
    assert args.once is True


def _score_stats(error: str | None) -> dict:
    from synthetic_trader.live.auto_scorer import AutoScoreStats

    return {
        "ALL": AutoScoreStats(
            symbol="ALL",
            calls_pending=0,
            calls_scored=0,
            calls_failed=0,
            calls_skipped=0,
            error=error,
        )
    }


def test_score_live_loop_once_exits_nonzero_on_sweep_error(monkeypatch) -> None:
    """A scheduled --once sweep must exit non-zero on failure so Task Scheduler
    sees it instead of logging a false 'ok' every day."""

    async def fake_loop(**kwargs):
        return _score_stats(error="RuntimeError: deriv_unavailable")

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_auto_score_loop",
        fake_loop,
    )
    code = main(
        [
            "score-live-loop",
            "--once",
            "--calls-journal", str(_JOURNAL_DIR / "calls.jsonl"),
            "--output", str(_JOURNAL_DIR / "outcomes.jsonl"),
            "--status-path", str(_JOURNAL_DIR / "auto_scorer.json"),
        ]
    )
    assert code == 1


def test_score_live_loop_once_exits_zero_on_success(monkeypatch) -> None:
    async def fake_loop(**kwargs):
        return _score_stats(error=None)

    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer.run_auto_score_loop",
        fake_loop,
    )
    code = main(
        [
            "score-live-loop",
            "--once",
            "--calls-journal", str(_JOURNAL_DIR / "calls.jsonl"),
            "--output", str(_JOURNAL_DIR / "outcomes.jsonl"),
            "--status-path", str(_JOURNAL_DIR / "auto_scorer.json"),
        ]
    )
    assert code == 0


def test_build_parser_live_watch_exposes_calls_journal() -> None:
    parser = build_parser()

    args = parser.parse_args(["live-watch", "--symbol", "R_75"])

    assert args.calls_journal == "journals/live_calibration_calls.jsonl"


def test_build_parser_live_watch_auto_score_flag_defaults_to_300() -> None:
    parser = build_parser()

    args = parser.parse_args(["live-watch", "--symbol", "R_75", "--auto-score"])

    assert args.auto_score == 300.0
    assert args.auto_score_status_path == "data/auto_scorer.json"


def test_build_parser_live_watch_auto_score_accepts_interval() -> None:
    parser = build_parser()

    args = parser.parse_args(["live-watch", "--symbol", "R_75", "--auto-score", "60"])

    assert args.auto_score == 60.0


def test_build_parser_live_watch_auto_score_disabled_by_default() -> None:
    parser = build_parser()

    args = parser.parse_args(["live-watch", "--symbol", "R_75"])

    assert args.auto_score is None


def test_main_log_live_call_appends_a_record(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    output_path = tmp_path / "calls.jsonl"
    payload_path.write_text(
        json.dumps(
            {
                "symbol": "R_75",
                "call": "buy_candidate",
                "trade_status": "valid",
                "guardian_state": "actionable",
                "entry": 123.4,
                "execution_stop": 120.0,
                "primary_target": 130.0,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "log-live-call",
            "--symbol",
            "R_75",
            "--payload-json",
            str(payload_path),
            "--output",
            str(output_path),
        ]
    )

    written_lines = output_path.read_text(encoding="utf-8").splitlines()

    assert exit_code == 0
    assert len(written_lines) == 1
    assert json.loads(written_lines[0])["symbol"] == "R_75"


def test_main_score_live_calibration_reports_missing_calls_journal(tmp_path: Path) -> None:
    output = io.StringIO()
    missing_path = tmp_path / "missing_calls.jsonl"

    with contextlib.redirect_stdout(output):
        exit_code = main(["score-live-calibration", "--calls-journal", str(missing_path)])

    assert exit_code == 1
    assert f"error=journal_not_found:{missing_path}" in output.getvalue()


def test_main_score_live_calibration_prints_scored_failed_and_skipped_counts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '{"symbol":"R_100","generated_at":"2026-07-12T10:00:00+00:00"}\n',
        encoding="utf-8",
    )
    output = io.StringIO()

    def fake_run_score_unresolved_records_from_market(
        **_: object,
    ) -> CalibrationScoringResult:
        return CalibrationScoringResult(
            scored_records=2,
            failed_records=1,
            skipped_records=3,
        )

    monkeypatch.setattr(
        "synthetic_trader.cli.run_score_unresolved_records_from_market",
        fake_run_score_unresolved_records_from_market,
    )

    with contextlib.redirect_stdout(output):
        exit_code = main(
            [
                "score-live-calibration",
                "--calls-journal",
                str(calls_path),
                "--output",
                str(outcomes_path),
                "--now",
                "2026-07-12T11:05:00+00:00",
            ]
        )

    assert exit_code == 0
    assert "scored_records=2" in output.getvalue()
    assert "failed_records=1" in output.getvalue()
    assert "skipped_records=3" in output.getvalue()


def test_log_live_call_and_score_live_calibration_commands_work_together_with_real_scoring_wrapper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "symbol": "R_100",
                "call": "buy_candidate",
                "trade_status": "valid",
                "guardian_state": "actionable",
                "direction_bias": "buy",
                "confidence": 0.74,
                "entry": 476.1,
                "execution_stop": 474.8,
                "primary_target": 488.4,
                "thesis_invalidation": 440.67,
                "hold_horizon_minutes": 60,
                "why": "buyers reclaimed the pullback shelf",
                "wait_for": "wait for the 5m reclaim to confirm, then manage toward the next hour objective",
                "decision_summary": "4H bullish; 1H setup aligns; 15m reclaim aligns",
                "current_close": 476.5,
                "model_version": "online-logistic-v1",
            }
        ),
        encoding="utf-8",
    )
    log_output = io.StringIO()
    score_output = io.StringIO()
    wrapper_calls: list[dict[str, object]] = []

    with contextlib.redirect_stdout(log_output):
        log_exit_code = main(
            [
                "log-live-call",
                "--symbol",
                "R_100",
                "--payload-json",
                str(payload_path),
                "--output",
                str(calls_path),
            ]
        )

    written_calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
    score_now = (datetime.fromisoformat(written_calls[0]["generated_at"]) + timedelta(minutes=65)).isoformat()

    def fake_run_score_unresolved_records_from_market(
        *,
        calls_path: Path,
        outcomes_path: Path,
        now: datetime,
        symbol: str | None = None,
        window_minutes: int | None = None,
        client_factory: object = None,
    ) -> CalibrationScoringResult:
        wrapper_calls.append(
            {
                "calls_path": calls_path,
                "outcomes_path": outcomes_path,
                "now": now,
                "symbol": symbol,
                "window_minutes": window_minutes,
            }
        )
        calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()]
        outcomes_path.write_text(
            json.dumps(
                {
                    "symbol": calls[0]["symbol"],
                    "generated_at": calls[0]["generated_at"],
                    "outcome_label": "neither_reached",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return CalibrationScoringResult(
            scored_records=1,
            failed_records=0,
            skipped_records=0,
        )

    monkeypatch.setattr(
        "synthetic_trader.cli.run_score_unresolved_records_from_market",
        fake_run_score_unresolved_records_from_market,
    )
    # The CLI resolves the Deriv MT5 client before scoring (no Deriv
    # fallback); pretend it resolved so the mocked scorer is reached.
    monkeypatch.setattr(
        "synthetic_trader.live.auto_scorer._resolve_scoring_client_factory",
        lambda: object,
    )

    with contextlib.redirect_stdout(score_output):
        score_exit_code = main(
            [
                "score-live-calibration",
                "--calls-journal",
                str(calls_path),
                "--output",
                str(outcomes_path),
                "--now",
                score_now,
            ]
        )

    written_outcomes = [json.loads(line) for line in outcomes_path.read_text(encoding="utf-8").splitlines()]

    assert log_exit_code == 0
    assert "symbol=R_100" in log_output.getvalue()
    assert len(written_calls) == 1
    assert written_calls[0]["symbol"] == "R_100"
    assert written_calls[0]["generated_at"]
    assert score_exit_code == 0
    assert wrapper_calls == [
        {
            "calls_path": calls_path,
            "outcomes_path": outcomes_path,
            "now": datetime.fromisoformat(score_now),
            "symbol": None,
            "window_minutes": None,
        }
    ]
    assert "scored_records=1" in score_output.getvalue()
    assert "failed_records=0" in score_output.getvalue()
    assert "skipped_records=0" in score_output.getvalue()
    assert len(written_outcomes) == 1
    assert written_outcomes[0]["symbol"] == "R_100"
    assert written_outcomes[0]["outcome_label"] == "neither_reached"
