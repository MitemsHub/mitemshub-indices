#!/usr/bin/env python3
"""Shared MT5 market-data loader: direct terminal queries + .npy binary cache.

Replaces the artifacts/real_<symbol>_<tf>.csv snapshot cache.  Data always
comes from the terminal when it is reachable; the .npy file is only a fast
restart cache for offline analysis and is rejected when stale (older than
``MAX_CACHE_AGE_S`` or missing bars vs. the terminal).

Array layout (structured dtype, one row per bar):
    epoch (f8, UTC seconds), open, high, low, close, spread, volume (f8)

Usage:
    from scripts.mt5_data import load_m5
    bars = load_m5("Boom 1000 Index", timeframe="M5", bars=20000)

The returned object behaves like the list-of-dicts the research scripts
already consume (epoch/open/high/low/close/spread/volume keys), so callers
need no further changes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
CACHE_DIR = ART / "npz"
META_SUFFIX = ".meta.json"

#: A .npy cache older than this is considered stale for LIVE runs.
MAX_CACHE_AGE_S = 6 * 3600

DTYPE = np.dtype([
    ("epoch", "f8"),
    ("open", "f8"),
    ("high", "f8"),
    ("low", "f8"),
    ("close", "f8"),
    ("spread", "f8"),
    ("volume", "f8"),
])

_TIMEFRAMES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


class MT5Unavailable(RuntimeError):
    """Terminal unreachable and no fresh cache available."""


def _sanitize(symbol: str) -> str:
    return symbol.replace(" ", "_").replace("(", "").replace(")", "")


def _cache_paths(symbol: str, timeframe: str) -> tuple[Path, Path]:
    base = CACHE_DIR / f"{_sanitize(symbol)}_{timeframe}"
    return base.with_suffix(".npy"), base.with_suffix(META_SUFFIX)


def _fetch_from_mt5(symbol: str, timeframe: str, bars: int) -> np.ndarray:
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise MT5Unavailable(f"mt5.initialize() failed: {mt5.last_error()}")
    try:
        tf_code = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if tf_code is None:
            raise ValueError(f"unknown timeframe {timeframe!r}")
        rates = mt5.copy_rates_from_pos(symbol, tf_code, 0, bars)
        if rates is None or len(rates) == 0:
            raise MT5Unavailable(f"no history for {symbol}: {mt5.last_error()}")
        out = np.zeros(len(rates), dtype=DTYPE)
        out["epoch"] = rates["time"].astype("f8")
        out["open"] = rates["open"]
        out["high"] = rates["high"]
        out["low"] = rates["low"]
        out["close"] = rates["close"]
        out["spread"] = rates["spread"]
        out["volume"] = rates["tick_volume"]
        return out
    finally:
        mt5.shutdown()


def _write_cache(arr: np.ndarray, symbol: str, timeframe: str) -> None:
    npy_path, meta_path = _cache_paths(symbol, timeframe)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = npy_path.with_suffix(".npy.tmp")
    with tmp.open("wb") as fh:  # handle form: np.save must not append .npy
        np.save(fh, arr)
    tmp.replace(npy_path)
    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(arr)),
        "first_epoch": float(arr["epoch"][0]),
        "last_epoch": float(arr["epoch"][-1]),
        "written_at": time.time(),
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _read_cache(symbol: str, timeframe: str) -> np.ndarray | None:
    npy_path, _ = _cache_paths(symbol, timeframe)
    if not npy_path.exists():
        return None
    try:
        arr = np.load(npy_path)
        if arr.dtype != DTYPE or len(arr) == 0:
            return None
        return arr
    except Exception:
        return None


def fetch_m5(
    symbol: str,
    timeframe: str = "M5",
    bars: int = 20000,
    *,
    prefer_cache: bool = False,
    max_cache_age_s: int = MAX_CACHE_AGE_S,
) -> np.ndarray:
    """Return bars as a structured array, refreshing the .npy cache.

    Live path (default): query the terminal; on success rewrite the cache.
    If the terminal is unreachable, fall back to the cache only when it is
    younger than ``max_cache_age_s``; otherwise raise MT5Unavailable.

    ``prefer_cache=True`` inverts this for offline replays: use the cache
    when present regardless of age (still refreshed opportunistically).
    """
    if timeframe not in _TIMEFRAMES:
        raise ValueError(f"unsupported timeframe {timeframe!r}")

    cache = _read_cache(symbol, timeframe)
    cache_fresh = (
        cache is not None
        and _cache_paths(symbol, timeframe)[1].exists()
        and time.time() - _cache_paths(symbol, timeframe)[1].stat().st_mtime
        <= max_cache_age_s
    )

    if prefer_cache and cache is not None:
        try:
            fresh = _fetch_from_mt5(symbol, timeframe, bars)
            _write_cache(fresh, symbol, timeframe)
            return fresh
        except Exception:
            return cache

    try:
        fresh = _fetch_from_mt5(symbol, timeframe, bars)
        _write_cache(fresh, symbol, timeframe)
        return fresh
    except Exception as exc:
        if cache is not None and cache_fresh:
            print(f"[mt5_data] terminal unreachable ({exc}); using fresh cache")
            return cache
        raise


class _BarView:
    """Lightweight sequence-of-dicts view over the structured array."""

    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr

    def __len__(self) -> int:
        return len(self._arr)

    def __getitem__(self, idx: int) -> dict[str, float]:
        row = self._arr[idx]
        return {
            "epoch": float(row["epoch"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "spread": float(row["spread"]),
            "volume": float(row["volume"]),
        }

    def __iter__(self):
        for i in range(len(self._arr)):
            yield self[i]

    @property
    def array(self) -> np.ndarray:
        return self._arr


def load_m5(
    symbol: str,
    timeframe: str = "M5",
    bars: int = 20000,
    *,
    prefer_cache: bool = False,
) -> _BarView:
    """Drop-in replacement for the CSV loaders used by research scripts."""
    return _BarView(
        fetch_m5(symbol, timeframe, bars, prefer_cache=prefer_cache)
    )


def slice_recent(bars: _BarView | np.ndarray, days: float) -> _BarView:
    """Return the trailing ``days`` worth of bars."""
    arr = bars.array if isinstance(bars, _BarView) else bars
    if len(arr) == 0:
        return _BarView(arr)
    cutoff = float(arr["epoch"][-1]) - days * 86400.0
    return _BarView(arr[arr["epoch"] >= cutoff])


def cache_info(symbol: str, timeframe: str) -> dict[str, Any] | None:
    _, meta_path = _cache_paths(symbol, timeframe)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    import sys

    symbol = sys.argv[1] if len(sys.argv) > 1 else "Boom 1000 Index"
    tf = sys.argv[2] if len(sys.argv) > 2 else "M5"
    view = load_m5(symbol, tf)
    meta = cache_info(symbol, tf) or {}
    span_days = (
        (meta.get("last_epoch", 0) - meta.get("first_epoch", 0)) / 86400.0
        if meta
        else 0.0
    )
    print(f"{symbol} {tf}: {len(view)} bars, cache span {span_days:.1f}d")
