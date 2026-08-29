"""Smoke tests for research scripts: verify they load data from .npy cache
and produce sensible output without a live MT5 terminal.

These tests monkey-patch the MT5 fetch to always raise, forcing the loader
into its offline cache-fallback path.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# Ensure scripts/ is importable
sys.path.insert(0, str(SCRIPTS))
# Also ensure repo root is importable for scripts.mt5_data path
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helper: block any live MT5 fetch so the cache path is exercised
# ---------------------------------------------------------------------------
def _block_mt5_fetch(*a, **k):
    raise RuntimeError("offline smoke test: MT5 fetch blocked")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_live_mt5(monkeypatch):
    """Force mt5_data into offline/cached mode for all tests."""
    import scripts.mt5_data as md
    monkeypatch.setattr(md, "_fetch_from_mt5", _block_mt5_fetch)


@pytest.fixture
def v75_bars():
    """Load Volatility 75 Index from cache as a plain list (needed for slicing in aggregate())."""
    from scripts.mt5_data import load_m5
    return list(load_m5("Volatility 75 Index", "M5", prefer_cache=True))


@pytest.fixture
def boom_bars():
    """Load Boom 1000 Index from cache as a plain list."""
    from scripts.mt5_data import load_m5
    return list(load_m5("Boom 1000 Index", "M5", prefer_cache=True))


@pytest.fixture
def crash_bars():
    """Load Crash 1000 Index from cache as a plain list."""
    from scripts.mt5_data import load_m5
    return list(load_m5("Crash 1000 Index", "M5", prefer_cache=True))


# ---------------------------------------------------------------------------
# mt5_data loader tests
# ---------------------------------------------------------------------------
class TestMt5DataLoader:
    """Verify the shared mt5_data loader works against .npy cache."""

    def test_load_v75(self, v75_bars):
        assert len(v75_bars) >= 1000, f"expected 1000+ bars, got {len(v75_bars)}"
        b = v75_bars[0]
        assert all(k in b for k in ("epoch", "open", "high", "low", "close", "spread", "volume"))
        assert b["epoch"] > 0
        assert b["close"] > 0

    def test_load_boom(self, boom_bars):
        assert len(boom_bars) >= 1000

    def test_load_crash(self, crash_bars):
        assert len(crash_bars) >= 1000

    def test_slice_recent(self):
        from scripts.mt5_data import load_m5, slice_recent
        raw = load_m5("Volatility 75 Index", "M5", prefer_cache=True)
        sliced = slice_recent(raw, 60)
        assert len(sliced) > 0
        assert len(sliced) < len(raw)
        # All bars should be within the last 60 days
        last_epoch = raw[-1]["epoch"]
        for bar in sliced:
            assert bar["epoch"] >= last_epoch - 60 * 86400

    def test_offline_fallback_raises_without_cache(self):
        """If cache is missing and MT5 is blocked, should raise."""
        from scripts.mt5_data import load_m5
        with pytest.raises(RuntimeError):
            load_m5("Nonexistent Symbol_xyz", "M5")


# ---------------------------------------------------------------------------
# backtest_real_history.py tests
# ---------------------------------------------------------------------------
class TestBacktestRealHistory:
    """Verify the backtest script's simulate() function works on real data."""

    def test_simulate_produces_trades(self, v75_bars):
        """Import and run the simulate function on real V75 data."""
        # Import the module
        spec = importlib.util.spec_from_file_location(
            "backtest_real_history", SCRIPTS / "backtest_real_history.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Override the load_m5 import to return our cached data
        mod.load_m5 = lambda sym, tf="M5": v75_bars
        spec.loader.exec_module(mod)

        # Aggregate M5 to M15
        bars = mod.aggregate(v75_bars, 3)
        assert len(bars) > 100, f"expected 100+ M15 bars, got {len(bars)}"

        # Run simulate with default parameters
        result = mod.simulate(bars, 2.0, 1.20)
        assert "trades" in result
        assert result["trades"] > 0, "expected at least some trades on V75"

    def test_simulate_output_shape(self, v75_bars):
        spec = importlib.util.spec_from_file_location(
            "backtest_real_history", SCRIPTS / "backtest_real_history.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": v75_bars
        spec.loader.exec_module(mod)

        bars = mod.aggregate(v75_bars, 3)
        result = mod.simulate(bars, 2.0, 1.20)

        # Check all expected keys
        assert "trades" in result
        assert "per_day" in result
        assert "wr" in result
        assert "pf" in result
        assert "exp_r" in result
        assert "max_dd_r" in result
        assert "exits" in result
        assert "pass" in result

        # Sanity: win rate between 0-100
        if result["trades"] > 0:
            assert 0 <= result["wr"] <= 100
            assert result["pf"] >= 0
            assert "TARGET" in result["exits"]
            assert "STOP" in result["exits"]
            assert "TIME" in result["exits"]

    def test_main_runs_without_error(self, v75_bars, monkeypatch):
        """Run main() with --only to limit to one symbol."""
        spec = importlib.util.spec_from_file_location(
            "backtest_real_history", SCRIPTS / "backtest_real_history.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Monkeypatch the module-level load_m5 so main() picks it up
        mod.load_m5 = lambda sym, tf="M5": v75_bars

        # Capture output
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mod.main(["--only", "Volatility 75", "--tf", "M15"])
        assert rc == 0
        output = buf.getvalue()
        assert "Volatility 75" in output
        assert "PASS" in output or "FAIL" in output  # should produce a verdict


# ---------------------------------------------------------------------------
# 60day_analysis.py tests
# ---------------------------------------------------------------------------
class Test60DayAnalysis:
    """Verify 60day_analysis loads and runs the simulate function."""

    def test_load_and_simulate(self, v75_bars):
        spec = importlib.util.spec_from_file_location(
            "60day_analysis", SCRIPTS / "60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": v75_bars
        spec.loader.exec_module(mod)

        from scripts.synthlib import slice_60d
        sliced = slice_60d(v75_bars, 60)
        assert len(sliced) > 100

        bars = mod.aggregate(sliced, 3)
        result = mod.simulate(bars, 2.0, 1.20)
        assert "trades" in result
        assert result["trades"] >= 0


# ---------------------------------------------------------------------------
# boom1000_60day_analysis.py tests
# ---------------------------------------------------------------------------
class TestBoom1000Analysis:
    """Verify boom1000_60day_analysis loads and can run detect + simulate."""

    def test_load_and_detect_spikes(self, boom_bars):
        spec = importlib.util.spec_from_file_location(
            "boom1000_60day_analysis", SCRIPTS / "boom1000_60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": boom_bars
        spec.loader.exec_module(mod)

        sliced = mod.slice_60d(boom_bars, 60)
        assert len(sliced) > 100

        spikes = mod.detect_spikes(sliced, 2.5)
        spike_indices = [s["idx"] for s in spikes if s["is_spike"]]
        assert len(spike_indices) > 0, "expected at least some spikes on Boom 1000"
        assert len(spike_indices) < len(sliced), "spikes should be a small fraction of bars"

    def test_atr_computes(self, boom_bars):
        spec = importlib.util.spec_from_file_location(
            "boom1000_60day_analysis", SCRIPTS / "boom1000_60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": boom_bars
        spec.loader.exec_module(mod)

        sliced = mod.slice_60d(boom_bars, 60)
        atr = mod.compute_atr(sliced)
        assert len(atr) == len(sliced) - 1
        assert atr[-1] > 0, "ATR should be positive"


# ---------------------------------------------------------------------------
# crash1000_60day_analysis.py tests
# ---------------------------------------------------------------------------
class TestCrash1000Analysis:
    """Verify crash1000_60day_analysis loads and can run detect + simulate."""

    def test_load_and_detect_spikes(self, crash_bars):
        spec = importlib.util.spec_from_file_location(
            "crash1000_60day_analysis", SCRIPTS / "crash1000_60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": crash_bars
        spec.loader.exec_module(mod)

        sliced = mod.slice_60d(crash_bars, 60)
        assert len(sliced) > 100

        spike_indices = mod.detect_spikes(sliced, 2.5)
        assert len(spike_indices) > 0, "expected at least some spikes on Crash 1000"

    def test_atr_computes(self, crash_bars):
        spec = importlib.util.spec_from_file_location(
            "crash1000_60day_analysis", SCRIPTS / "crash1000_60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": crash_bars
        spec.loader.exec_module(mod)

        sliced = mod.slice_60d(crash_bars, 60)
        atr = mod.compute_atr(sliced)
        assert len(atr) == len(sliced) - 1
        assert atr[-1] > 0


# ---------------------------------------------------------------------------
# mt5_probe.py structural test
# ---------------------------------------------------------------------------
class TestMt5Probe:
    """Verify mt5_probe.py imports cleanly and its helper is well-formed."""

    def test_imports(self):
        spec = importlib.util.spec_from_file_location(
            "mt5_probe", SCRIPTS / "mt5_probe.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Don't exec (would fail without MT5), just verify parse
        import ast
        ast.parse((SCRIPTS / "mt5_probe.py").read_text(encoding="utf-8"))

    def test_sanitize_name(self):
        from scripts.mt5_probe import _sanitize_name
        assert _sanitize_name("Boom 1000 Index") == "Boom_1000_Index"
        assert _sanitize_name("Volatility 75 (1s) Index") == "Volatility_75_1s_Index"
