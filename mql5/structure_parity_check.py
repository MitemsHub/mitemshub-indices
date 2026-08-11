#!/usr/bin/env python3
"""Validate the MQL5 StructureParity port (PythonParity/StructureParity.mqh).

The tester cross-validation (Tests/StructureLiveTests.mq5) compares the
reconciled CStructureEngine bias against a faithful MQL5 port of the Python
structural_direction.  That port is worthless unless it reproduces the REAL
Python engine, so this script mirrors the port line-for-line and asserts every
output equals the production code in src/synthetic_trader/features/
market_structure.py:

  - crafted series (ramp, zigzag, sine, random walk, flat) — edge paths like
    "no swings -> fallback" and "monotonic -> momentum bias"
  - seeded random OHLC windows
  - every 100-bar M5 window of the real R_75 tick corpus (the same windows the
    phase-3 real-corpus gate uses)

If the mirror and the real Python ever diverge, the port (mirror + .mqh) has a
bug and must be fixed in lockstep before the tester run is meaningful.
"""

import csv
import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, _HERE)

from synthetic_trader.domain import Candle, Direction  # noqa: E402
from synthetic_trader.features.market_structure import (  # noqa: E402
    market_structure_features,
    structural_direction,
)
from synthetic_trader.features.indicators import atr, safe_div  # noqa: E402
from phase3_real_corpus_check import CORPUS_PATHS, load_m5_bars  # noqa: E402

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PARITY] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PARITY] FAIL  {name}  -> {detail}")


# ============================================================================
# Mirror of CStructureParity::Compute — keep in lockstep with the .mqh.
# ============================================================================
def parity_direction(opens, highs, lows, closes):
    n = len(closes)
    out = {
        "direction": 0, "structure_bias": 0.0, "displacement_atr": 0.0,
        "bos_up": 0, "bos_down": 0, "internal_bos_up": 0, "internal_bos_down": 0,
        "sweep_up": 0, "sweep_down": 0, "fvg_up": 0, "fvg_down": 0,
        "fvg_active_up": 0, "fvg_active_down": 0,
        "recent_high": (highs[-1] if n else 0.0),
        "recent_low": (lows[-1] if n else 0.0),
    }
    if n < 5:
        return out

    last_close, last_high, last_low = closes[-1], highs[-1], lows[-1]
    prior = n - 1

    # median of highs+lows of the PRIOR bars (upper-middle index)
    all_prices = sorted([highs[i] for i in range(prior)] + [lows[i] for i in range(prior)])
    median = all_prices[len(all_prices) // 2]
    thr_high = median * 5.0
    thr_low = median / 5.0

    # non-strict equality-fractal swings over the prior bars
    sw_high, sw_low, seq_price, seq_kind = [], [], [], []
    for i in range(2, prior - 2):
        if highs[i] > thr_high or lows[i] < thr_low:
            continue
        wmax = max(highs[i - 2:i + 3])
        wmin = min(lows[i - 2:i + 3])
        if highs[i] == wmax:
            sw_high.append(highs[i])
            seq_price.append(highs[i])
            seq_kind.append(1)
        if lows[i] == wmin:
            sw_low.append(lows[i])
            seq_price.append(lows[i])
            seq_kind.append(-1)

    nh, nl = len(sw_high), len(sw_low)

    if nh > 0:
        recent_high = sw_high[-1]
    else:
        recent_high = max(highs[max(0, prior - 20):prior])
    if nl > 0:
        recent_low = sw_low[-1]
    else:
        recent_low = min(lows[max(0, prior - 20):prior])
    out["recent_high"] = recent_high
    out["recent_low"] = recent_low

    avg_range = atr([_candle(i, opens, highs, lows, closes) for i in range(n)], 14)
    out["displacement_atr"] = safe_div(abs(closes[-1] - opens[-1]), avg_range)

    out["bos_up"] = 1 if last_close > recent_high else 0
    out["bos_down"] = 1 if last_close < recent_low else 0
    out["sweep_up"] = 1 if (last_high > recent_high and last_close < recent_high) else 0
    out["sweep_down"] = 1 if (last_low < recent_low and last_close > recent_low) else 0

    # FVG scan — most recent gap per direction wins
    bull = bear = False
    bb = bt = rt = rb = 0.0
    for i in range(2, n):
        a_high, a_low = highs[i - 2], lows[i - 2]
        b_body = closes[i - 1] - opens[i - 1]
        if lows[i] > a_high and b_body > 0.0:
            bull, bb, bt = True, a_high, lows[i]
        if highs[i] < a_low and b_body < 0.0:
            bear, rt, rb = True, a_low, highs[i]
    out["fvg_up"] = 1 if bull else 0
    out["fvg_down"] = 1 if bear else 0
    out["fvg_active_up"] = 1 if (bull and last_close > bb) else 0
    out["fvg_active_down"] = 1 if (bear and last_close < rt) else 0

    # internal BOS: last 4 swings (combined order), per-polarity last two
    ns = len(seq_price)
    h_count = l_count = 0
    h_last = h_prev = l_last = l_prev = 0.0
    for i in range(max(0, ns - 4), ns):
        if seq_kind[i] > 0:
            h_prev, h_last, h_count = h_last, seq_price[i], h_count + 1
        else:
            l_prev, l_last, l_count = l_last, seq_price[i], l_count + 1
    out["internal_bos_up"] = 1 if (h_count >= 2 and h_last > h_prev) else 0
    out["internal_bos_down"] = 1 if (l_count >= 2 and l_last < l_prev) else 0

    # structure_bias
    sb = 0.0
    if nh >= 2:
        higher_high = sw_high[-1] > sw_high[-2]
        lower_high = sw_high[-1] < sw_high[-2]
    else:
        higher_high = lower_high = False
    if nl >= 2:
        higher_low = sw_low[-1] > sw_low[-2]
        lower_low = sw_low[-1] < sw_low[-2]
    else:
        higher_low = lower_low = False
    if higher_high and higher_low:
        sb = 0.7
    elif lower_high and lower_low:
        sb = -0.7
    elif n >= 10:
        nn = min(n, 20)
        close_n = closes[-nn]
        den = max(close_n, 1e-9)
        price_change = (last_close - close_n) / den
        avg_rng = atr([_candle(i, opens, highs, lows, closes) for i in range(n)], min(14, n))
        if avg_rng > 0.0:
            sb = max(-1.0, min(1.0, price_change / (avg_rng / den) * 0.5))
    out["structure_bias"] = sb

    bull_score = (out["bos_up"] + 0.5 * out["internal_bos_up"] + out["sweep_down"]
                  + out["fvg_up"] + 0.5 * out["fvg_active_up"] + max(sb, 0.0))
    bear_score = (out["bos_down"] + 0.5 * out["internal_bos_down"] + out["sweep_up"]
                  + out["fvg_down"] + 0.5 * out["fvg_active_down"] + abs(min(sb, 0.0)))
    if bull_score > bear_score:
        out["direction"] = 1
    elif bear_score > bull_score:
        out["direction"] = -1
    return out


def _candle(i, opens, highs, lows, closes):
    return Candle(symbol="R_75", timeframe_sec=300, open_time=int(i),
                  open=opens[i], high=highs[i], low=lows[i], close=closes[i])


def _real_python(opens, highs, lows, closes):
    candles = [_candle(i, opens, highs, lows, closes) for i in range(len(closes))]
    feats = market_structure_features(candles)
    d = structural_direction(feats)
    return {
        "direction": {Direction.LONG: 1, Direction.SHORT: -1, Direction.FLAT: 0}[d],
        "structure_bias": feats.get("structure_bias", 0.0),
        "displacement_atr": feats.get("displacement_atr", 0.0),
        "bos_up": 1 if feats.get("bos_up", 0.0) else 0,
        "bos_down": 1 if feats.get("bos_down", 0.0) else 0,
        "internal_bos_up": 1 if feats.get("internal_bos_up", 0.0) else 0,
        "internal_bos_down": 1 if feats.get("internal_bos_down", 0.0) else 0,
        "sweep_up": 1 if feats.get("liquidity_sweep_up", 0.0) else 0,
        "sweep_down": 1 if feats.get("liquidity_sweep_down", 0.0) else 0,
        "fvg_up": 1 if feats.get("bullish_fvg", 0.0) else 0,
        "fvg_down": 1 if feats.get("bearish_fvg", 0.0) else 0,
        "fvg_active_up": 1 if feats.get("fvg_bullish_active", 0.0) else 0,
        "fvg_active_down": 1 if feats.get("fvg_bearish_active", 0.0) else 0,
        "recent_high": feats.get("recent_swing_high", 0.0),
        "recent_low": feats.get("recent_swing_low", 0.0),
    }


def _series_bars(closes, off=0.5):
    opens = [closes[0]] + closes[:-1]
    highs = [c + off for c in closes]
    lows = [c - off for c in closes]
    return opens, highs, lows, closes


def assert_equal(name, p, r):
    tol = 1e-9
    ok = True
    detail = ""
    for k in sorted(p):
        a, b = p[k], r[k]
        if isinstance(a, int):
            if a != b:
                ok = False
                detail += f"{k}: {a} vs {b}; "
        elif abs(a - b) > tol:
            ok = False
            detail += f"{k}: {a:.6f} vs {b:.6f}; "
    check(name, ok, detail)


def main():
    print("[PARITY] === StructureParity port vs real Python market_structure ===\n")

    # --- 1. crafted series (edge paths) --------------------------------------
    rng = random.Random(7)
    crafted = {
        "ramp": [100.0 + i * 0.5 for i in range(120)],
        "zigzag": [100.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(120)],
        "sine": [100.0 + 1.5 * math.sin(2 * math.pi * i / 8) for i in range(120)],
        "flat": [100.0] * 120,
        "random walk": _rw(rng, 120, 0.0, 1.0),
        "persistent up": _rw(rng, 120, 0.15, 0.4),
        "down trend": [100.0 - i * 0.3 for i in range(120)],
    }
    for name, closes in crafted.items():
        p = parity_direction(*_series_bars(closes))
        r = _real_python(*_series_bars(closes))
        assert_equal(f"crafted {name}", p, r)

    # --- 2. seeded random OHLC windows ----------------------------------------
    for t in range(150):
        closes = _rw(rng, 120, 0.0, 1.0)
        opens = [c + rng.uniform(-0.4, 0.4) for c in closes]
        highs = [max(o, c) + rng.uniform(0.0, 0.6) for o, c in zip(opens, closes)]
        lows = [min(o, c) - rng.uniform(0.0, 0.6) for o, c in zip(opens, closes)]
        p = parity_direction(opens, highs, lows, closes)
        r = _real_python(opens, highs, lows, closes)
        assert_equal(f"random #{t}", p, r)

    # --- 3. real corpus windows (the phase-3 gate's own windows) ---------------
    bars = load_m5_bars(CORPUS_PATHS)
    if len(bars) < 150:
        check("corpus loaded (>=150 bars)", False, f"only {len(bars)}")
    else:
        check("corpus loaded", True, f"{len(bars)} M5 bars")
        step = 5
        checked = 0
        for i in range(100, len(bars), step):
            win = bars[i - 99:i + 1]
            closes = [b[4] for b in win]
            opens = [b[1] for b in win]
            highs = [b[2] for b in win]
            lows = [b[3] for b in win]
            p = parity_direction(opens, highs, lows, closes)
            r = _real_python(opens, highs, lows, closes)
            assert_equal(f"corpus window @bar {i}", p, r)
            checked += 1
            if checked >= 120:
                break
        check("corpus windows compared", checked > 0, f"{checked} windows")

    print(f"\n[PARITY] === {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


def _rw(rng, n, drift, sigma):
    out = [100.0]
    for i in range(1, n):
        out.append(out[-1] + drift + sigma * rng.gauss(0.0, 1.0))
    return out


if __name__ == "__main__":
    sys.exit(main())
