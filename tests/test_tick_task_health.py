"""Tests for the tick-collector task health check (scripts/tick_task_health.py).

The check reads the artifacts the Windows Task Scheduler job leaves behind and
warns when the corpus stopped growing (ticks flat for ``flat_hours``) or the
task went stale.  Exit code 0 = healthy, 1 = warnings — the alert gate.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from synthetic_trader.scripts.tick_task_health import (
    check_task_health,
    render_report,
)

SYMBOLS = ("R_75", "R_100")


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _log_line(ts: datetime, text: str) -> str:
    return f"[{ts:%Y-%m-%d %H:%M:%S}] {text}"


def _write_log(root: Path, lines: list[str]) -> Path:
    path = root / ".data" / "live_tick_task.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _snapshot(ticks: dict[str, int], generated_at: float) -> dict:
    return {
        "generated_at": generated_at,
        "symbols": [
            {
                "symbol": sym,
                "tick_csv": f"data/backfill/{sym}_ticks.csv",
                "ticks": n,
                "span_hours": 167.98,
                "span_days": 7.0,
            }
            for sym, n in ticks.items()
        ],
    }


def _write_csv(root: Path, symbol: str, rows: int, mtime_ts: float) -> None:
    path = root / "data" / "backfill" / f"{symbol}_ticks.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Header row (backfill writes one) + data rows.
    path.write_text(
        "epoch,symbol,price\n" + "\n".join(f"{i},R_75,100.0" for i in range(rows)),
        encoding="utf-8",
    )
    # Reset mtime to the caller-provided timestamp (backdate the write).
    import os

    os.utime(path, (mtime_ts, mtime_ts))


class TestFlatCorpus:
    def test_flat_corpus_warns_and_exits_unhealthy(self, tmp_path) -> None:
        """Baseline + verify + CSV all at the same count, CSV mtime older than
        flat_hours → both symbols flagged flat, healthy=False."""
        now = _now_epoch()
        # Registration 4 days ago, same 40080 ticks ever since.
        baseline_ts = now - 4 * 86400
        verify_ts = now - 3600
        _write_json(
            tmp_path / ".data" / "live_tick_task_setup_baseline.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, baseline_ts),
        )
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, verify_ts),
        )
        # Task log: two runs, same count, one 3 days ago and one yesterday.
        _write_log(
            tmp_path,
            [
                _log_line(
                    datetime.fromtimestamp(now - 3 * 86400),
                    "coverage R_75 (40080 ticks, 7.0 days): ...",
                ),
                _log_line(
                    datetime.fromtimestamp(now - 86400),
                    "coverage R_75 (40080 ticks, 7.0 days): ...",
                ),
                _log_line(
                    datetime.fromtimestamp(now - 86400),
                    "task action complete",
                ),
            ],
        )
        # CSV written once 3 days ago, still 40080 data rows (+1 header).
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 3 * 86400)

        report = check_task_health(tmp_path, flat_hours=48.0)
        assert report.healthy is False
        assert len(report.warnings) == 2
        for sh in report.symbols:
            assert sh.flat is True
            assert sh.flat_hours >= 48.0
        assert "corpus stopped growing" in report.warnings[0]

    def test_growing_corpus_is_healthy(self, tmp_path) -> None:
        """Verify count above baseline + fresh CSV mtime + recent task action
        → no flat warning, healthy=True."""
        now = _now_epoch()
        baseline_ts = now - 4 * 86400
        verify_ts = now - 1800
        _write_json(
            tmp_path / ".data" / "live_tick_task_setup_baseline.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, baseline_ts),
        )
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 42000, "R_100": 42000}, verify_ts),
        )
        _write_log(
            tmp_path,
            [
                _log_line(
                    datetime.fromtimestamp(now - 1800),
                    "coverage R_75 (42000 ticks, 7.3 days): ...",
                ),
                _log_line(
                    datetime.fromtimestamp(now - 1800),
                    "task action complete",
                ),
            ],
        )
        # CSV mtime fresh (collector still appending).
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 42000, now - 60)

        report = check_task_health(tmp_path, flat_hours=48.0)
        assert report.healthy is True
        assert report.warnings == []
        for sh in report.symbols:
            assert sh.flat is False

    def test_flat_but_fresh_csv_is_healthy(self, tmp_path) -> None:
        """The corpus count looks flat in the snapshots, but the CSV mtime is
        fresh (collector actively appending; snapshots merely lag) → not flat."""
        now = _now_epoch()
        baseline_ts = now - 4 * 86400
        verify_ts = now - 7200
        _write_json(
            tmp_path / ".data" / "live_tick_task_setup_baseline.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, baseline_ts),
        )
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, verify_ts),
        )
        _write_log(
            tmp_path,
            [
                _log_line(
                    datetime.fromtimestamp(now - 3600),
                    "task action complete",
                ),
            ],
        )
        # CSV rewritten a minute ago → appending is alive.
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 60)

        report = check_task_health(tmp_path, flat_hours=48.0)
        assert report.healthy is True
        assert all(sh.flat is False for sh in report.symbols)

    def test_missing_from_verify_but_old_csv_still_warns(self, tmp_path) -> None:
        """A symbol absent from the verify snapshot must still warn when its
        CSV is old — the CSV mtime is ground truth, not the snapshot count."""
        now = _now_epoch()
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080}, now - 3600),  # R_100 missing
        )
        _write_log(
            tmp_path,
            [
                _log_line(
                    datetime.fromtimestamp(now - 3600),
                    "task action complete",
                ),
            ],
        )
        # R_75 CSV fresh; R_100 CSV old with no snapshot ever written for it.
        _write_csv(tmp_path, "R_75", 40080, now - 3600)
        _write_csv(tmp_path, "R_100", 40080, now - 3 * 86400)

        report = check_task_health(tmp_path, flat_hours=48.0)
        r75 = next(s for s in report.symbols if s.symbol == "R_75")
        r100 = next(s for s in report.symbols if s.symbol == "R_100")
        assert r75.flat is False
        assert r100.flat is True
        assert any(
            "R_100" in w and "corpus stopped growing" in w
            for w in report.warnings
        )

    def test_flat_window_tracks_csv_mtime_not_older_evidence(self, tmp_path) -> None:
        """When the CSV exists, flat_hours measures from the CSV mtime (the
        last real append), not the older registration/log timestamps."""
        now = _now_epoch()
        _write_json(
            tmp_path / ".data" / "live_tick_task_setup_baseline.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 6 * 86400),
        )
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 3600),
        )
        _write_log(
            tmp_path,
            [
                _log_line(
                    datetime.fromtimestamp(now - 5 * 86400),
                    "coverage R_75 (40080 ticks, 7.0 days): ...",
                ),
                _log_line(
                    datetime.fromtimestamp(now - 3600),
                    "task action complete",
                ),
            ],
        )
        # CSV last appended 50h ago (48h threshold + 2h margin).  Old min()
        # logic would report ~5-6 days flat from the registration/log stamps.
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 50 * 3600)

        report = check_task_health(tmp_path, flat_hours=48.0)
        for sh in report.symbols:
            assert sh.flat is True
            assert 48.0 <= sh.flat_hours < 52.0
            assert sh.flat_reason is not None
            assert "CSV not written" in sh.flat_reason


class TestTaskStaleness:
    def test_stale_task_warns(self, tmp_path) -> None:
        now = _now_epoch()
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 3600),
        )
        # Last task action 3 days ago → stale beyond the 26h default.
        _write_log(
            tmp_path,
            [
                _log_line(
                    datetime.fromtimestamp(now - 3 * 86400),
                    "task action starting (daily collector restart)",
                ),
            ],
        )
        report = check_task_health(tmp_path)
        assert report.task_stale is True
        assert report.healthy is False
        assert any("task stale" in w for w in report.warnings)

    def test_missing_log_and_verify_warns(self, tmp_path) -> None:
        """No log, no verify, no CSV → task stale + verify stale warnings."""
        report = check_task_health(tmp_path)
        assert report.healthy is False
        assert report.task_stale is True
        assert report.verify_stale is True
        texts = " ".join(report.warnings).lower()
        assert "task stale" in texts
        assert "verify snapshot missing" in texts


class TestReportShape:
    def test_json_shape(self, tmp_path) -> None:
        now = _now_epoch()
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 3600),
        )
        _write_log(
            tmp_path,
            [
                _log_line(datetime.fromtimestamp(now - 3600), "task action complete"),
            ],
        )
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 3 * 86400)

        report = check_task_health(tmp_path, flat_hours=24.0)
        d = report.to_dict()
        assert d["healthy"] is False
        assert isinstance(d["checked_at"], float)
        assert d["task"]["last_action_age_hours"] is not None
        assert d["verify"]["age_hours"] is not None
        assert len(d["symbols"]) == 2
        first = d["symbols"][0]
        for key in ("symbol", "ticks_latest", "csv_ticks", "flat", "flat_hours"):
            assert key in first
        assert isinstance(d["warnings"], list)

    def test_render_report_runs(self, tmp_path) -> None:
        now = _now_epoch()
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 3600),
        )
        _write_log(
            tmp_path,
            [
                _log_line(datetime.fromtimestamp(now - 3600), "task action complete"),
            ],
        )
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 3 * 86400)

        report = check_task_health(tmp_path, flat_hours=24.0)
        out = render_report(report)
        assert "TICK-COLLECTOR HEALTH" in out
        assert "WARNINGS" in out
        assert "R_75" in out

    def test_cli_exit_codes(self, tmp_path) -> None:
        """CLI exit code = 1 with warnings, 0 when healthy — the alert gate."""
        from synthetic_trader.scripts.tick_task_health import main

        now = _now_epoch()
        # Unhealthy: flat corpus.
        _write_json(
            tmp_path / ".data" / "live_tick_task_setup_baseline.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 4 * 86400),
        )
        _write_json(
            tmp_path / ".data" / "live_tick_task_verify.json",
            _snapshot({"R_75": 40080, "R_100": 40080}, now - 3600),
        )
        _write_log(
            tmp_path,
            [
                _log_line(datetime.fromtimestamp(now - 86400), "task action complete"),
            ],
        )
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 3 * 86400)
        rc = main(["--engine-root", str(tmp_path), "--flat-hours", "24", "--json"])
        assert rc == 1

        # Healthy: fresh CSV mtime.
        for sym in SYMBOLS:
            _write_csv(tmp_path, sym, 40080, now - 60)
        rc = main(["--engine-root", str(tmp_path), "--flat-hours", "24", "--json"])
        assert rc == 0
