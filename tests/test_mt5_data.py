"""Tests for scripts/mt5_data.py — cache round-trip, staleness, fallback,
BarView, slice_recent, cache_info, and the migrated analysis scripts' loading paths.

All tests run fully offline (no MT5 terminal required).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]

import sys
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import scripts.mt5_data as md


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_array(n: int = 100, base_epoch: float = 1_700_000_000.0) -> np.ndarray:
    """Create a small structured array matching mt5_data.DTYPE."""
    arr = np.zeros(n, dtype=md.DTYPE)
    arr["epoch"] = np.arange(base_epoch, base_epoch + n * 300, 300)[:n]  # 5-min bars
    arr["open"] = 100.0 + np.random.default_rng(42).normal(0, 0.5, n)
    arr["high"] = arr["open"] + 0.2
    arr["low"] = arr["open"] - 0.2
    arr["close"] = arr["open"] + 0.1
    arr["spread"] = 1.0
    arr["volume"] = 100.0
    return arr


@pytest.fixture
def sample_array():
    return _make_array(200)


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Redirect CACHE_DIR to a temporary directory."""
    monkeypatch.setattr(md, "CACHE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def _no_live_mt5(monkeypatch):
    """Block any live MT5 fetch."""
    monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))


# ===========================================================================
# _sanitize
# ===========================================================================
class TestSanitize:
    def test_spaces(self):
        assert md._sanitize("Boom 1000 Index") == "Boom_1000_Index"

    def test_parens(self):
        assert md._sanitize("Volatility 75 (1s) Index") == "Volatility_75_1s_Index"

    def test_no_special_chars(self):
        assert md._sanitize("Synth100") == "Synth100"


# ===========================================================================
# Cache write / read round-trip
# ===========================================================================
class TestCacheRoundTrip:
    def test_write_creates_files(self, tmp_cache, sample_array):
        md._write_cache(sample_array, "TestSymbol", "M5")
        npy, meta = md._cache_paths("TestSymbol", "M5")
        assert npy.exists()
        assert meta.exists()

    def test_read_back_matches(self, tmp_cache, sample_array):
        md._write_cache(sample_array, "TestSymbol", "M5")
        loaded = md._read_cache("TestSymbol", "M5")
        assert loaded is not None
        np.testing.assert_array_equal(loaded["epoch"], sample_array["epoch"])
        np.testing.assert_array_almost_equal(loaded["close"], sample_array["close"])

    def test_read_missing_returns_none(self, tmp_cache):
        assert md._read_cache("Nonexistent", "M5") is None

    def test_meta_json_contents(self, tmp_cache, sample_array):
        md._write_cache(sample_array, "TestSymbol", "M5")
        _, meta_path = md._cache_paths("TestSymbol", "M5")
        meta = json.loads(meta_path.read_text())
        assert meta["symbol"] == "TestSymbol"
        assert meta["timeframe"] == "M5"
        assert meta["rows"] == len(sample_array)
        assert meta["first_epoch"] == float(sample_array["epoch"][0])
        assert meta["last_epoch"] == float(sample_array["epoch"][-1])
        assert "written_at" in meta

    def test_corrupted_npy_returns_none(self, tmp_cache):
        npy_path, _ = md._cache_paths("BadSymbol", "M5")
        npy_path.write_bytes(b"not a valid npy file")
        assert md._read_cache("BadSymbol", "M5") is None

    def test_wrong_dtype_returns_none(self, tmp_cache):
        npy_path, _ = md._cache_paths("WrongDtype", "M5")
        arr = np.zeros(10, dtype=[("x", "f8"), ("y", "f8")])
        np.save(npy_path, arr)
        assert md._read_cache("WrongDtype", "M5") is None

    def test_zero_length_npy_returns_none(self, tmp_cache):
        """Write a valid .npy with 0 rows — _read_cache should reject it."""
        npy_path, _ = md._cache_paths("Empty", "M5")
        arr = np.zeros(0, dtype=md.DTYPE)
        np.save(npy_path, arr)
        assert md._read_cache("Empty", "M5") is None


# ===========================================================================
# Staleness detection
# ===========================================================================
class TestStaleness:
    def test_fresh_cache_is_fresh(self, tmp_cache, sample_array):
        md._write_cache(sample_array, "Fresh", "M5")
        _, meta_path = md._cache_paths("Fresh", "M5")
        age = time.time() - meta_path.stat().st_mtime
        assert age < 5  # just written

    def test_stale_cache_detected(self, tmp_cache, sample_array):
        md._write_cache(sample_array, "Stale", "M5")
        _, meta_path = md._cache_paths("Stale", "M5")
        # Backdate the meta file by 10 hours
        stale_time = time.time() - 10 * 3600
        import os
        os.utime(meta_path, (stale_time, stale_time))
        age = time.time() - meta_path.stat().st_mtime
        assert age > md.MAX_CACHE_AGE_S  # should be stale

    def test_stale_cache_cannot_serve_live_fallback(self, tmp_cache, sample_array, monkeypatch):
        """When MT5 is down and cache is stale, fetch_m5 should raise."""
        md._write_cache(sample_array, "Stale", "M5")
        _, meta_path = md._cache_paths("Stale", "M5")
        stale_time = time.time() - 10 * 3600
        import os
        os.utime(meta_path, (stale_time, stale_time))
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        with pytest.raises(RuntimeError, match="offline"):
            md.fetch_m5("Stale", "M5", prefer_cache=False)

    def test_fresh_cache_serves_live_fallback(self, tmp_cache, sample_array, monkeypatch):
        """When MT5 is down but cache is fresh, fetch_m5 should return cache."""
        md._write_cache(sample_array, "Fresh", "M5")
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        result = md.fetch_m5("Fresh", "M5", prefer_cache=False)
        np.testing.assert_array_equal(result["epoch"], sample_array["epoch"])


# ===========================================================================
# fetch_m5 fallback behavior
# ===========================================================================
class TestFetchFallback:
    def test_prefer_cache_returns_cache_when_mt5_unavailable(self, tmp_cache, sample_array, monkeypatch):
        md._write_cache(sample_array, "Cached", "M5")
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        result = md.fetch_m5("Cached", "M5", prefer_cache=True)
        np.testing.assert_array_equal(result["epoch"], sample_array["epoch"])

    def test_prefer_cache_returns_cache_even_when_stale(self, tmp_cache, sample_array, monkeypatch):
        """prefer_cache=True ignores staleness — useful for offline replays."""
        md._write_cache(sample_array, "Stale", "M5")
        _, meta_path = md._cache_paths("Stale", "M5")
        stale_time = time.time() - 10 * 3600
        import os
        os.utime(meta_path, (stale_time, stale_time))
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        result = md.fetch_m5("Stale", "M5", prefer_cache=True)
        np.testing.assert_array_equal(result["epoch"], sample_array["epoch"])

    def test_no_cache_no_mt5_raises(self, tmp_cache, monkeypatch):
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        with pytest.raises(RuntimeError):
            md.fetch_m5("NoCache", "M5", prefer_cache=False)

    def test_no_cache_no_mt5_prefer_cache_raises(self, tmp_cache, monkeypatch):
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
        with pytest.raises(RuntimeError):
            md.fetch_m5("NoCache", "M5", prefer_cache=True)

    def test_unsupported_timeframe_raises(self, tmp_cache):
        with pytest.raises(ValueError, match="unsupported timeframe"):
            md.fetch_m5("Any", "X99")

    def test_prefer_cache_refreshes_when_mt5_available(self, tmp_cache, sample_array, monkeypatch):
        """prefer_cache=True still attempts to refresh from MT5."""
        md._write_cache(sample_array, "Refresh", "M5")
        new_arr = _make_array(50, base_epoch=2_000_000_000.0)
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: new_arr)
        result = md.fetch_m5("Refresh", "M5", prefer_cache=True)
        np.testing.assert_array_equal(result["epoch"], new_arr["epoch"])


# ===========================================================================
# _BarView
# ===========================================================================
class TestBarView:
    def test_len(self, sample_array):
        bv = md._BarView(sample_array)
        assert len(bv) == len(sample_array)

    def test_getitem_returns_dict(self, sample_array):
        bv = md._BarView(sample_array)
        b = bv[0]
        assert isinstance(b, dict)
        assert all(k in b for k in ("epoch", "open", "high", "low", "close", "spread", "volume"))

    def test_getitem_values_are_float(self, sample_array):
        bv = md._BarView(sample_array)
        b = bv[0]
        for v in b.values():
            assert isinstance(v, float)

    def test_iteration(self, sample_array):
        bv = md._BarView(sample_array)
        count = sum(1 for _ in bv)
        assert count == len(sample_array)

    def test_array_property(self, sample_array):
        bv = md._BarView(sample_array)
        assert bv.array is sample_array

    def test_empty(self):
        arr = np.zeros(0, dtype=md.DTYPE)
        bv = md._BarView(arr)
        assert len(bv) == 0
        assert list(bv) == []


# ===========================================================================
# slice_recent
# ===========================================================================
class TestSliceRecent:
    def test_slices_barview(self):
        """slice_recent with a narrow window should exclude older bars."""
        arr = _make_array(200, base_epoch=1_700_000_000.0)
        # Span: 200 bars × 300s = 60,000s ≈ 16.7 hours
        bv = md._BarView(arr)
        sliced = md.slice_recent(bv, 0.5)  # last 12 hours
        assert len(sliced) > 0
        assert len(sliced) < len(bv)

    def test_slices_ndarray(self, sample_array):
        sliced = md.slice_recent(sample_array, 1)
        assert len(sliced) > 0

    def test_empty_input(self):
        arr = np.zeros(0, dtype=md.DTYPE)
        result = md.slice_recent(md._BarView(arr), 60)
        assert len(result) == 0

    def test_all_bars_within_window(self, sample_array):
        bv = md._BarView(sample_array)
        sliced = md.slice_recent(bv, 60)
        last_epoch = sample_array["epoch"][-1]
        for bar in sliced:
            assert bar["epoch"] >= last_epoch - 60 * 86400


# ===========================================================================
# cache_info
# ===========================================================================
class TestCacheInfo:
    def test_returns_none_when_no_cache(self, tmp_cache):
        assert md.cache_info("Nonexistent", "M5") is None

    def test_returns_metadata(self, tmp_cache, sample_array):
        md._write_cache(sample_array, "InfoTest", "M5")
        info = md.cache_info("InfoTest", "M5")
        assert info is not None
        assert info["symbol"] == "InfoTest"
        assert info["rows"] == len(sample_array)


# ===========================================================================
# load_m5 returns _BarView
# ===========================================================================
class TestLoadM5ReturnsBarView:
    def test_returns_barview(self, tmp_cache, sample_array, _no_live_mt5):
        md._write_cache(sample_array, "BVTest", "M5")
        result = md.load_m5("BVTest", "M5")
        assert isinstance(result, md._BarView)
        assert len(result) == len(sample_array)


# ===========================================================================
# Migrated analysis scripts — load_m5 shim paths
# ===========================================================================
class TestAnalysisLoadShims:
    """Verify that each migrated script has no CSV-based loader and that
    its load_m5 function works against the .npy cache offline.

    We cannot do a strict identity check on the function object because
    exec_module creates a fresh module namespace that imports `mt5_data`
    (not `scripts.mt5_data`), producing a separate module object. Instead
    we verify the two properties that matter:
      1. No `import csv` — confirms the legacy CSV path is gone.
      2. load_m5(symbol) returns data from the .npy cache when MT5 is blocked.
    """

    SCRIPTS_DIR = ROOT / "scripts"
    SCRIPT_NAMES = [
        "60day_analysis",
        "boom1000_60day_analysis",
        "crash1000_60day_analysis",
        "backtest_real_history",
    ]

    def test_no_csv_import(self):
        """None of the migrated scripts should import csv anymore."""
        for name in self.SCRIPT_NAMES:
            source = (self.SCRIPTS_DIR / f"{name}.py").read_text(encoding="utf-8")
            # Allow csv in comments/strings but not as an import
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                assert "import csv" not in stripped, (
                    f"{name}.py still imports csv: {stripped}"
                )

    @pytest.mark.parametrize("script_name", SCRIPT_NAMES)
    def test_load_m5_works_offline(self, script_name, _no_live_mt5):
        """Each script's load_m5 returns data when MT5 is blocked."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            script_name, self.SCRIPTS_DIR / f"{script_name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.load_m5("Boom 1000 Index")
        # Should return an iterable with dict-like bars
        bars = list(result)
        assert len(bars) >= 1000, f"{script_name} loaded only {len(bars)} bars"
        assert all("close" in b for b in bars[:5])


# ===========================================================================
# Offline end-to-end: each script loads data and produces output
# ===========================================================================
class TestOfflineEndToEnd:
    """Run each analysis script's core logic against the .npy cache."""

    @pytest.fixture(autouse=True)
    def _block_mt5(self, monkeypatch):
        monkeypatch.setattr(md, "_fetch_from_mt5", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))

    def test_60day_loads_v75(self):
        bv = md.load_m5("Volatility 75 Index", "M5", prefer_cache=True)
        assert len(bv) >= 1000

    def test_boom1000_loads(self):
        bv = md.load_m5("Boom 1000 Index", "M5", prefer_cache=True)
        assert len(bv) >= 1000

    def test_crash1000_loads(self):
        bv = md.load_m5("Crash 1000 Index", "M5", prefer_cache=True)
        assert len(bv) >= 1000

    def test_boom1000_spike_detects(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "boom1000", ROOT / "scripts" / "boom1000_60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bars = list(md.load_m5("Boom 1000 Index", "M5", prefer_cache=True))
        sliced = mod.slice_60d(bars, 60)
        spikes = mod.detect_spikes(sliced, 2.5)
        assert any(s["is_spike"] for s in spikes)

    def test_crash1000_spike_detects(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "crash1000", ROOT / "scripts" / "crash1000_60day_analysis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bars = list(md.load_m5("Crash 1000 Index", "M5", prefer_cache=True))
        sliced = mod.slice_60d(bars, 60)
        indices = mod.detect_spikes(sliced, 2.5)
        assert len(indices) > 0

    def test_backtest_real_history_simulate(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "backtest", ROOT / "scripts" / "backtest_real_history.py"
        )
        mod = importlib.util.module_from_spec(spec)
        mod.load_m5 = lambda sym, tf="M5": list(md.load_m5(sym, tf, prefer_cache=True))
        spec.loader.exec_module(mod)
        bars = list(md.load_m5("Volatility 75 Index", "M5", prefer_cache=True))
        agg = mod.aggregate(bars, 3)
        result = mod.simulate(agg, 2.0, 1.20)
        assert result["trades"] > 0
        assert result["pf"] > 0
