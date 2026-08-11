"""Tests for the collector health report (IPC-timeout recurrence verdict)."""

from __future__ import annotations

import json
import time

from synthetic_trader.scripts.collector_health import (
    DEFAULT_EVENTS_PATH,
    run_collector_health,
)


def _write_events(tmp_path, events: list[dict]) -> None:
    path = tmp_path / DEFAULT_EVENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _event(kind: str, message: str, ts: float) -> dict:
    return {"ts": ts, "kind": kind, "message": message}


class TestVerdict:
    def test_no_events_is_ok(self, tmp_path) -> None:
        report = run_collector_health(engine_root=tmp_path, hours=48)
        assert report["verdict"] == "ok"
        assert report["events"]["total"] == 0
        assert "single-flight guard is holding" in report["verdict_reason"]

    def test_three_ipc_timeouts_need_re_tune(self, tmp_path) -> None:
        now = time.time()
        _write_events(
            tmp_path,
            [
                _event("init_failed", "MT5 initialize failed: (-10005, 'IPC timeout')", now - 3600 * i)
                for i in range(1, 4)
            ],
        )
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "needs_re_tune"
        assert report["events"]["ipc_timeouts"] == 3
        assert "reconnect backoff" in report["verdict_reason"]

    def test_single_ipc_timeout_is_attention(self, tmp_path) -> None:
        now = time.time()
        _write_events(
            tmp_path,
            [_event("init_failed", "MT5 initialize failed: (-10005, 'IPC timeout')", now - 100)],
        )
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "attention"
        assert report["events"]["ipc_timeouts"] == 1

    def test_old_events_outside_window_ignored(self, tmp_path) -> None:
        now = time.time()
        # 5 IPC timeouts but all 5 days ago -> outside the 48h window.
        _write_events(
            tmp_path,
            [_event("init_failed", "MT5 initialize failed: (-10005, 'IPC timeout')", now - 5 * 86400.0)],
        )
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "ok"
        assert report["events"]["total"] == 0

    def test_feed_loss_events_are_attention(self, tmp_path) -> None:
        now = time.time()
        _write_events(
            tmp_path,
            [
                _event("feed_lost", "R_75: no fresh tick ... (feed lost) — reconnect", now - 100 * i)
                for i in range(1, 4)
            ],
        )
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "attention"
        assert report["events"]["ipc_timeouts"] == 0


class TestVenueLeak:
    def _write_corpus(self, tmp_path, symbol: str, prices: list[float]) -> None:
        now = time.time()
        csv = tmp_path / "data" / "backfill" / f"{symbol}_ticks.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.write_text(
            "\n".join(f"{now - 300 + i * 60},{symbol},{p}" for i, p in enumerate(prices)),
            encoding="utf-8",
        )

    def test_deriv_scale_tick_flags_venue_leak(self, tmp_path) -> None:
        # Blueberry SYN75 scale ~1,800; one Deriv 1HZ row at ~6,900 (~3.8x)
        # mixed in — the exact leak the append guard is supposed to stop.
        self._write_corpus(
            tmp_path, "R_75", [1770.0 + i * 0.5 for i in range(20)] + [6892.07]
        )
        report = run_collector_health(engine_root=tmp_path, hours=48)
        assert report["verdict"] == "venue_leak"
        assert "VENUE LEAK" in report["verdict_reason"]
        assert "R_75" in report["verdict_reason"]
        assert report["corpus"]["R_75"]["out_of_scale_ticks"] >= 1

    def test_clean_corpus_is_ok(self, tmp_path) -> None:
        self._write_corpus(tmp_path, "R_75", [1770.0 + i * 0.5 for i in range(20)])
        report = run_collector_health(engine_root=tmp_path, hours=48)
        assert report["verdict"] == "ok"
        assert report["corpus"]["R_75"]["out_of_scale_ticks"] == 0

    def test_duplicate_epoch_leak_is_still_detected(self, tmp_path) -> None:
        # A leaked Deriv tick whose epoch collides with a real Blueberry row
        # must still be flagged — dedupe-by-epoch would otherwise mask it.
        now = time.time()
        csv = tmp_path / "data" / "backfill" / "R_75_ticks.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{now - 300 + i * 60},R_75,{1770.0 + i * 0.5}" for i in range(20)]
        # Collide with the i=5 epoch (now - 300 + 300 == now).
        lines.append(f"{now},R_75,6892.07")
        csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "venue_leak"
        assert report["corpus"]["R_75"]["out_of_scale_ticks"] >= 1

    def test_venue_leak_outranks_ipc_timeouts(self, tmp_path) -> None:
        now = time.time()
        _write_events(
            tmp_path,
            [
                _event("init_failed", "MT5 initialize failed: (-10005, 'IPC timeout')", now - 3600 * i)
                for i in range(1, 4)
            ],
        )
        self._write_corpus(tmp_path, "R_75", [1770.0] * 10 + [6920.0])
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "venue_leak"
        assert report["events"]["ipc_timeouts"] == 3  # still measured, but not the verdict


class TestCorpusFreshness:
    def test_stale_corpus_flags_attention(self, tmp_path) -> None:
        now = time.time()
        csv = tmp_path / "data" / "backfill" / "R_75_ticks.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        # Last tick 20h ago (stale) at Blueberry scale.
        csv.write_text(
            "\n".join(
                f"{now - 20 * 3600 + i * 60},R_75,{1770.0 + i * 0.1}"
                for i in range(5)
            ),
            encoding="utf-8",
        )
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "attention"
        assert report["corpus"]["R_75"]["last_tick_age_sec"] > 12 * 3600

    def test_fresh_corpus_with_no_events_is_ok(self, tmp_path) -> None:
        now = time.time()
        csv = tmp_path / "data" / "backfill" / "R_75_ticks.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.write_text(
            "\n".join(f"{now - 300 + i * 60},R_75,{1770.0 + i}" for i in range(5)),
            encoding="utf-8",
        )
        report = run_collector_health(engine_root=tmp_path, hours=48, now=now)
        assert report["verdict"] == "ok"
