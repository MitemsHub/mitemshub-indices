#!/usr/bin/env python3
"""Phase-4 logic mirror — verifies the exact algorithms in MITEMSHUB_AI.

Replicates line-for-line:
  Strategies/BandGeometry.mqh        (band_levels port, entry gates, trail)
  Strategies/StrategyEngine.mqh      (regime-allowance matrix + dispatch)

Two layers of validation:
  1. The mirror is checked against the REAL Python production code
     (src/synthetic_trader/strategy/band_geometry.py) on the shared test
     cases — if the mirror matches Python to 1e-12, and the MQL5 tests match
     the mirror, then MQL5 reproduces Python band_levels within tolerance.
  2. The mirror runs the same assertion matrix as Tests/Phase4Tests.mq5.

Keep this file in lockstep with the MQL5 side.
"""

import math
import os
import sys

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PHASE4] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PHASE4] FAIL  {name}  -> {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --- real Python production code (the reference) -----------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from synthetic_trader.strategy.band_geometry import (  # noqa: E402
    BandGeometryConfig as PyBandConfig,
    band_levels as py_band_levels,
    horizon_sigma as py_horizon_sigma,
)


# --- mirror of MQL5 CBandGeometry ---------------------------------------------
def horizon_sigma_m(sigma_per_bar, bar_sec, hold_sec):
    bars = max(1, round(hold_sec / max(1, bar_sec)))
    return sigma_per_bar * math.sqrt(bars)


def band_levels_m(entry, direction, sigma_per_bar, bar_sec, hold_sec,
                  stop_mult, target_mult, min_rr, max_stop_pct):
    if entry <= 0.0 or not math.isfinite(entry):
        return None
    if sigma_per_bar <= 0.0 or not math.isfinite(sigma_per_bar):
        return None
    if direction not in (1, -1):
        return None
    if hold_sec <= 0:
        return None
    sigma_h = horizon_sigma_m(sigma_per_bar, bar_sec, hold_sec)
    if sigma_h <= 0.0 or not math.isfinite(sigma_h):
        return None
    stop_dist = stop_mult * sigma_h
    target_dist = target_mult * sigma_h
    if stop_dist <= 0.0 or target_dist <= 0.0:
        return None
    if direction > 0:
        stop_loss = entry * (1.0 - stop_dist)
        take_profit = entry * (1.0 + target_dist)
    else:
        stop_loss = entry * (1.0 + stop_dist)
        take_profit = entry * (1.0 - target_dist)
    rr = target_dist / stop_dist
    if rr < min_rr:
        return None
    if abs(entry - stop_loss) / entry > max_stop_pct:
        return None
    if direction > 0:
        if not (0.0 < stop_loss < take_profit):
            return None
    elif not (take_profit < stop_loss):
        return None
    return dict(stop_loss=stop_loss, take_profit=take_profit, rr=rr,
                sigma_h=sigma_h, hold=hold_sec)


def vol_extended_m(prev_sigma, sigma_ema, ratio):
    return prev_sigma > ratio * sigma_ema


def entry_direction_m(z_dev, z_entry):
    if z_dev >= z_entry:
        return -1
    if z_dev <= -z_entry:
        return 1
    return 0


def confidence_m(z_dev, z_entry):
    return min(0.95, 0.55 + min(0.35, abs(z_dev) / (z_entry * 3.0)))


def update_mfe_m(direction, entry, high, low, prev_mfe, risk_distance):
    risk = risk_distance if risk_distance > 0.0 else entry * 0.001
    mfe = (high - entry) / risk if direction > 0 else (entry - low) / risk
    return max(prev_mfe, mfe)


def trail_armed_m(mfe_r, frac, planned_rr):
    return frac > 0.0 and mfe_r >= frac * planned_rr


def effective_stop_m(armed, entry, stop_loss):
    return entry if armed else stop_loss


# --- mirror of MQL5 CStrategyEngine -------------------------------------------
BAND, TREND, BREAKOUT, MR, SWEEP, PULLBACK = range(1, 7)
R_UNKNOWN, R_TREND_UP, R_TREND_DOWN, R_RANGE, R_COMPRESSION, R_EXPANSION = range(6)
R_HIGH_VOL, R_LOW_VOL, R_TRANSITION = 6, 7, 8


def matrix_allows_m(s, regime):
    if regime in (R_TREND_UP, R_TREND_DOWN):
        return s in (BAND, TREND, BREAKOUT, PULLBACK)
    if regime == R_RANGE:
        return s in (BAND, MR, SWEEP)
    if regime == R_COMPRESSION:
        return s in (BAND, BREAKOUT, SWEEP)
    return s == BAND


def is_allowed_m(s, regime, research_enabled=False):
    if s == BAND:
        return True
    if not research_enabled:
        return False
    return matrix_allows_m(s, regime)


# ============================ TESTS ==========================================
print("[PHASE4] --- band_levels vs REAL Python (the Phase-4 gate) ---")
cases = [
    ("A buy 100", 100, "buy", 0.005, 300, 3600, None, 1),
    ("B sell 100", 100, "sell", 0.005, 300, 3600, None, -1),
    ("E buy 2h", 100, "buy", 0.005, 300, 7200, None, 1),
]
for label, entry, direction_str, sig, bar_sec, hold, cfg, dint in cases:
    py = py_band_levels(entry, direction_str, sig, bar_sec, hold, config=cfg)
    m = band_levels_m(entry, dint, sig, bar_sec, hold,
                      0.20, 0.80, 2.0, 0.015)
    ok = (py is not None and m is not None
          and close(py.stop_loss, m["stop_loss"], 1e-12)
          and close(py.take_profit, m["take_profit"], 1e-12)
          and close(py.reward_risk, m["rr"], 1e-12)
          and close(py.horizon_sigma, m["sigma_h"], 1e-12))
    check(f"mirror == Python ({label})", ok,
          f"py={py} m={m}")
    check(f"level A values ({label})", ok and close(m["stop_loss"], 99.653589838486 if "A " in label else m["stop_loss"]))

# fixed expected values (from the real Python run)
check("A stop 99.653589838486", close(band_levels_m(100, 1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015)["stop_loss"], 99.653589838486, 1e-12))
check("A tp 101.385640646055", close(band_levels_m(100, 1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015)["take_profit"], 101.385640646055, 1e-12))
check("A rr 4.0", close(band_levels_m(100, 1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015)["rr"], 4.0, 1e-12))
check("A sig_h 0.017320508076", close(band_levels_m(100, 1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015)["sigma_h"], 0.017320508076, 1e-12))
b = band_levels_m(100, -1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015)
check("B sell stop above entry", close(b["stop_loss"], 100.346410161514, 1e-12))
check("B sell tp below entry", close(b["take_profit"], 98.614359353945, 1e-12))
e = band_levels_m(100, 1, 0.005, 300, 7200, 0.20, 0.80, 2.0, 0.015)
check("E 2h stop 99.510102051443", close(e["stop_loss"], 99.510102051443, 1e-12))
check("E 2h tp 101.959591794227", close(e["take_profit"], 101.959591794227, 1e-12))

print("[PHASE4] --- band_levels guards ---")
check("rr < min_rr -> None",
      band_levels_m(100, 1, 0.005, 300, 3600, 0.20, 0.30, 2.0, 0.015) is None)
check("stop > max_stop_pct -> None",
      band_levels_m(100, 1, 0.2, 300, 3600, 0.20, 0.80, 2.0, 0.015) is None)
check("entry <= 0 -> None", band_levels_m(0, 1, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015) is None)
check("sigma <= 0 -> None", band_levels_m(100, 1, 0.0, 300, 3600, 0.20, 0.80, 2.0, 0.015) is None)
check("bad direction -> None", band_levels_m(100, 0, 0.005, 300, 3600, 0.20, 0.80, 2.0, 0.015) is None)
check("hold <= 0 -> None", band_levels_m(100, 1, 0.005, 300, 0, 0.20, 0.80, 2.0, 0.015) is None)

print("[PHASE4] --- entry gates ---")
check("vol extended 0.14 > 1.3x0.1", vol_extended_m(0.14, 0.10, 1.3))
check("vol not extended 0.12 < 1.3x0.1", not vol_extended_m(0.12, 0.10, 1.3))
check("boundary 0.13 == 1.3x0.1 not >", not vol_extended_m(0.13, 0.10, 1.3))
check("z +1.5 -> sell", entry_direction_m(1.5, 1.0) == -1)
check("z -1.5 -> buy", entry_direction_m(-1.5, 1.0) == 1)
check("z +1.0 boundary -> sell", entry_direction_m(1.0, 1.0) == -1)
check("z 0.5 -> none", entry_direction_m(0.5, 1.0) == 0)
check("conf z=1 0.8833", close(confidence_m(1.0, 1.0), 0.883333333, 1e-6))
check("conf z=3 0.9", close(confidence_m(3.0, 1.0), 0.9, 1e-9))
check("conf z=10 clamped 0.9", close(confidence_m(10.0, 1.0), 0.9, 1e-9))

print("[PHASE4] --- breakeven trail ---")
check("MFE buy 1.25", close(update_mfe_m(1, 100.0, 100.5, 99.2, 0.0, 0.4), 1.25, 1e-9))
check("MFE sell 2.0", close(update_mfe_m(-1, 100.0, 100.5, 99.2, 0.0, 0.4), 2.0, 1e-9))
check("MFE max tracks", close(update_mfe_m(1, 100.0, 100.3, 99.5, 1.25, 0.4), 1.25, 1e-9))
check("trail not armed below frac", not trail_armed_m(1.0, 0.3, 3.5))
check("trail armed at 0.3 x 3.5", trail_armed_m(1.05, 0.3, 3.5))
check("trail disabled frac=0", not trail_armed_m(2.0, 0.0, 3.5))
check("effective stop = entry when armed", close(effective_stop_m(True, 100.0, 99.6), 100.0))
check("effective stop = stop when not armed", close(effective_stop_m(False, 100.0, 99.6), 99.6))

print("[PHASE4] --- StrategyEngine matrix ---")
# disabled state: only band allowed anywhere
for reg in (R_TREND_UP, R_RANGE, R_COMPRESSION, R_EXPANSION):
    check(f"disabled: band allowed in regime {reg}", is_allowed_m(BAND, reg))
    check(f"disabled: trend blocked in regime {reg}", not is_allowed_m(TREND, reg))
    check(f"disabled: meanrev blocked in regime {reg}", not is_allowed_m(MR, reg))
# end-state matrix
check("TREND_UP allows trend", matrix_allows_m(TREND, R_TREND_UP))
check("TREND_UP blocks meanrev", not matrix_allows_m(MR, R_TREND_UP))
check("TREND_DOWN allows pullback", matrix_allows_m(PULLBACK, R_TREND_DOWN))
check("RANGE allows meanrev", matrix_allows_m(MR, R_RANGE))
check("RANGE allows sweep", matrix_allows_m(SWEEP, R_RANGE))
check("RANGE blocks trend", not matrix_allows_m(TREND, R_RANGE))
check("COMPRESSION allows breakout", matrix_allows_m(BREAKOUT, R_COMPRESSION))
check("COMPRESSION blocks pullback", not matrix_allows_m(PULLBACK, R_COMPRESSION))
check("EXPANSION band only", matrix_allows_m(BAND, R_EXPANSION) and not matrix_allows_m(BREAKOUT, R_EXPANSION))
allowed_up = [s for s in (BAND, TREND, BREAKOUT, MR, SWEEP, PULLBACK) if matrix_allows_m(s, R_TREND_UP)]
check("TREND_UP allowed list", allowed_up == [BAND, TREND, BREAKOUT, PULLBACK], f"{allowed_up}")
allowed_range = [s for s in (BAND, TREND, BREAKOUT, MR, SWEEP, PULLBACK) if matrix_allows_m(s, R_RANGE)]
check("RANGE allowed list", allowed_range == [BAND, MR, SWEEP], f"{allowed_range}")
live_up = [s for s in (BAND, TREND, BREAKOUT, MR, SWEEP, PULLBACK)
           if is_allowed_m(s, R_TREND_UP, research_enabled=False)]
check("runtime allowed = band only (research disabled)", live_up == [BAND], f"{live_up}")

print(f"[PHASE4] === {PASS} passed, {FAIL} failed ===")
raise SystemExit(1 if FAIL > 0 else 0)
