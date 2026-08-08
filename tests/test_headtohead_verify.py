"""Tests for the milestone-gated head-to-head verifier."""

from __future__ import annotations

import json
import math
import time

import pytest

from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.domain import Tick
from synthetic_trader.research.headtohead_verify import (
    DEFAULT_ARTIFACT_SUBDIR,
    HOLD_THRESHOLD_R,
    MILESTONE_TRADES,
    band_verdict,
    load_latest_verify,
    run_headtohead_verify,
)


def _ticks(n: int = 700, symbol: str = "R_75") -> list[Tick]:
    """Quiet base, then a sustained elevated-vol regime (fires the gates)."""
    closes: list[float] = []
    for i in range(120):
        closes.append(100.0 + 0.005 * math.sin(i / 3.0))
    base = closes[-1]
    rng = [0.02, -0.018, 0.021, -0.019, 0.02, 0.017, -0.021, 0.019]
    for i in range(n - len(closes)):
        closes.append(base * math.exp(rng[i % len(rng)]))
    return [Tick(symbol=symbol, epoch=float(i * 60), price=c) for i, c in enumerate(closes)]


def _write_corpus(tmp_path, ticks: list[Tick], symbol: str = "R_75"):
    csv = tmp_path / "data" / "backfill" / f"{symbol}_ticks.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_text(
        "\n".join(f"{t.epoch:.0f},{t.symbol},{t.price:.6f}" for t in ticks),
        encoding="utf-8",
    )
    return csv


class TestBandVerdict:
    def test_insufficient_n(self) -> None:
        v = band_verdict({"trades": MILESTONE_TRADES - 1, "expectancy_r": 2.0})
        assert v["status"] == "insufficient_n"

    def test_holds_at_sample_size(self) -> None:
        v = band_verdict({"trades": MILESTONE_TRADES, "expectancy_r": HOLD_THRESHOLD_R})
        assert v["status"] == "holds"

    def test_positive_but_diluted(self) -> None:
        v = band_verdict({"trades": MILESTONE_TRADES, "expectancy_r": 0.15})
        assert v["status"] == "positive_but_diluted"

    def test_edge_lost(self) -> None:
        v = band_verdict({"trades": MILESTONE_TRADES, "expectancy_r": -0.3})
        assert v["status"] == "edge_lost"


class TestGates:
    def test_span_too_short_skips(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())  # ~0.49d span
        report = run_headtohead_verify(symbol="R_75", engine_root=tmp_path)
        assert report["verdict"] == "skipped"
        assert "span_too_short" in report["skip_reason"]

    def test_no_tick_csv_skips(self, tmp_path) -> None:
        report = run_headtohead_verify(symbol="R_75", engine_root=tmp_path)
        assert report["verdict"] == "skipped"
        assert "no_tick_csv" in report["skip_reason"]

    def test_growth_gate_after_first_run(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        t0 = time.time()
        first = run_headtohead_verify(
            symbol="R_75", engine_root=tmp_path, min_span_days=0.0, force=True, now=t0
        )
        assert first["verdict"] in ("insufficient_n", "holds", "edge_lost",
                                    "positive_but_diluted")
        # Same corpus, later -> growth < MIN_GROWTH_DAYS -> skip.
        second = run_headtohead_verify(
            symbol="R_75",
            engine_root=tmp_path,
            min_span_days=0.0,
            now=t0 + 10 * 86400.0,
        )
        assert second["verdict"] == "skipped"
        assert "insufficient_growth" in second["skip_reason"]

    def test_force_bypasses_growth_gate(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        t0 = time.time()
        run_headtohead_verify(
            symbol="R_75", engine_root=tmp_path, min_span_days=0.0, force=True, now=t0
        )
        second = run_headtohead_verify(
            symbol="R_75",
            engine_root=tmp_path,
            min_span_days=0.0,
            force=True,
            now=t0 + 86400.0,
        )
        assert second["verdict"] != "skipped"


class TestPipeline:
    def test_full_run_writes_artifact_with_all_legs(self, tmp_path) -> None:
        _write_corpus(tmp_path, _ticks())
        report = run_headtohead_verify(
            symbol="R_75", engine_root=tmp_path, timeframe_sec=60,
            min_span_days=0.0, force=True,
        )
        assert set(report["legs"]) == {"band", "fade", "momentum", "sniper"}
        for leg in report["legs"].values():
            assert "trades" in leg and "expectancy_r" in leg and "net_pnl" in leg
        latest = tmp_path / DEFAULT_ARTIFACT_SUBDIR / "latest_R_75.json"
        assert latest.exists()
        persisted = json.loads(latest.read_text(encoding="utf-8"))
        assert persisted["verdict"] == report["verdict"]
        assert load_latest_verify("R_75", tmp_path) == persisted
        # Timeframe and corpus metadata are captured.
        assert report["timeframe_sec"] == 60
        assert report["corpus"]["ticks"] == 700
