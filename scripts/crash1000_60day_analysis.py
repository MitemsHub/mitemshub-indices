#!/usr/bin/env python3
"""Crash 1000 60-day analysis: mirror of Boom 1000 but BUY after spikes.

Crash 1000: spikes go DOWN -> fade by BUYING after retrace.
Same logic as boom1000_60day_analysis.py but inverted direction.

Usage:
    .venv/Scripts/python.exe scripts/crash1000_60day_analysis.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5  # shared loader: terminal + .npy cache
from synthlib import slice_60d, get_spike_indices as detect_spikes, compute_atr, trade_stats

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

# EA parameters (mirroring Boom 1000 optimized config)
SPIKE_THRESHOLD = 2.5
FADE_SL_MULT = 0.4
FADE_TP_MULT = 3.2        # OPTIMIZED from Boom 1000 sweep
COOLDOWN_BARS = 1
POST_SPIKE_WINDOW = 5
ATR_PERIOD = 14





def backtest_fade_crash(bars, spike_indices, atr_vals, tp_mult, sl_mult=FADE_SL_MULT):
    """Crash fade: spikes go DOWN -> BUY after retrace."""
    trades = []
    cooldown = 0

    for sidx in spike_indices:
        spike_bar = bars[sidx]
        spike_body = abs(spike_bar["close"] - spike_bar["open"])
        spike_high = spike_bar["high"]
        spike_low = spike_bar["low"]

        for j in range(sidx + 1, min(sidx + POST_SPIKE_WINDOW + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue

            current = bars[j]
            if j >= len(atr_vals) or atr_vals[j] <= 0:
                continue

            atr = atr_vals[j]
            current_price = current["close"]

            # Crash: spike went DOWN, fade by BUYING
            if current_price > spike_low:
                retrace = (current_price - spike_low) / spike_body if spike_body > 0 else 0

                if 0.30 <= retrace <= 0.70:
                    entry = current_price
                    sl = entry - sl_mult * atr
                    tp = entry + tp_mult * atr
                    if tp < spike_high:
                        tp = spike_high + atr * 0.2

                    risk_dist = entry - sl
                    result = None
                    reason = "TIME"

                    for k in range(j + 1, min(j + 12, len(bars))):
                        bar = bars[k]
                        hit_sl = bar["low"] <= sl
                        hit_tp = bar["high"] >= tp
                        if hit_sl:
                            result = -1.0
                            reason = "STOP"
                            break
                        if hit_tp:
                            result = tp_mult / sl_mult
                            reason = "TARGET"
                            break

                    if result is None:
                        exit_idx = min(j + 11, len(bars) - 1)
                        result = (bars[exit_idx]["close"] - entry) / risk_dist if risk_dist > 0 else 0

                    trades.append({
                        "entry_idx": j,
                        "entry_epoch": bars[j]["epoch"],
                        "r": result,
                        "reason": reason,
                        "signal_type": "CB-FADE",
                    })
                    cooldown = COOLDOWN_BARS
                    break

    return trades


def main():
    print("=" * 90)
    print("CRASH 1000 INDEX - 60-DAY FADE-ONLY ANALYSIS")
    print(f"Params: spike_thresh={SPIKE_THRESHOLD}x | fade SL={FADE_SL_MULT}xATR TP={FADE_TP_MULT}xATR")
    print("=" * 90)

    # Shared loader: pulls from the MT5 terminal (fresh) with .npy cache.
    bars_full = load_m5("Crash 1000 Index", "M5")
    bars = slice_60d(bars_full, 60)
    if not bars:
        print("ERROR: No data in 60-day window")
        return 1

    t0 = datetime.fromtimestamp(bars[0]["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
    t1 = datetime.fromtimestamp(bars[-1]["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
    actual_days = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400
    print(f"\n60-day window: {t0} -> {t1}  ({actual_days:.0f}d)  ({len(bars)} M5 bars)")

    # Spike analysis
    print("\n" + "-" * 90)
    print("SPIKE ANALYSIS")
    print("-" * 90)
    spike_indices = detect_spikes(bars)
    spike_bodies = [abs(bars[i]["close"] - bars[i]["open"]) for i in spike_indices]
    if spike_bodies:
        print(f"  Spike count: {len(spike_indices)}")
        print(f"  Body: median={statistics.median(spike_bodies):.2f} mean={statistics.mean(spike_bodies):.2f}")
        gaps = [(spike_indices[i] - spike_indices[i-1]) * 5 for i in range(1, len(spike_indices))]
        if gaps:
            print(f"  Gap: median={statistics.median(gaps):.0f}min mean={statistics.mean(gaps):.0f}min")
        print(f"  Spikes/day: {len(spike_indices)/max(actual_days,1):.2f}")

    # ATR
    atr_vals = compute_atr(bars)

    # Fade backtest with optimized params
    print("\n" + "-" * 90)
    print(f"FADE BACKTEST (SL={FADE_SL_MULT}xATR, TP={FADE_TP_MULT}xATR)")
    print("-" * 90)
    fade_trades = backtest_fade_crash(bars, spike_indices, atr_vals, tp_mult=FADE_TP_MULT)
    stats = trade_stats(fade_trades, "CRASH-1000 FADE (buy after spike)")

    # TP sweep
    print("\n" + "-" * 90)
    print("TP SWEEP")
    print("-" * 90)
    print(f"{'TP':>5} | {'Trades':>6} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6}")
    print(f"{'-'*5}-+{'-'*37}")
    for tp in [1.5, 2.0, 2.5, 3.0, 3.2, 3.5, 4.0]:
        trades = backtest_fade_crash(bars, spike_indices, atr_vals, tp_mult=tp)
        if trades:
            s = trade_stats(trades, f"TP={tp}")
            # Compact print
            print(f"{tp:>5} | {s['trades']:>6} {s['wr']:>5} {s['pf']:>5} {s['exp_r']:>+7.3f} {s['max_dd_r']:>6}")

    # Save
    out = {
        "window": {"start": t0, "end": t1, "days": round(actual_days, 1)},
        "spikes": {"count": len(spike_indices), "per_day": round(len(spike_indices)/max(actual_days,1), 2)},
        "fade_stats": stats,
    }
    out_path = ART / "crash1000_60day_analysis.json"
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")

    # Verdict
    print("\n" + "=" * 90)
    if stats.get("exp_r", 0) > 0.5 and stats.get("pf", 0) > 2.0:
        print("STRONG EDGE on Crash 1000 fade. Ready for fade-only deployment.")
    elif stats.get("exp_r", 0) > 0:
        print("POSITIVE edge on Crash 1000 fade. Demo recommended first.")
    else:
        print("NEGATIVE edge. Do not deploy.")
    print("=" * 90)

    return 0


if __name__ == "__main__":
    sys.exit(main())
