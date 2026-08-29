#!/usr/bin/env python3
"""Boom 1000 FADE-PERFECTION: deep spike profiling + retrace optimization.

This script goes beyond the basic optimizer — it:
1. Profiles EVERY spike's retrace behavior (depth, speed, shape)
2. Finds the optimal entry window (retrace % range)
3. Sweeps TP/SL/trailing/hold/cut combinations
4. Backtests with realistic time-based exits
5. Generates EA-ready parameters with confidence scores

Data comes from the MT5 terminal via the shared mt5_data loader
(direct fetch + .npy cache + staleness check); no CSV snapshots.

Usage:
    .venv/Scripts/python.exe scripts/boom1000_fade_perfection.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
sys.path.insert(0, str(ROOT))
from scripts.mt5_data import load_m5
from scripts.synthlib import slice_60d, detect_spikes, compute_atr, trade_stats

ATR_PERIOD = 14



# ================================================================
# SPIKE RETRACE PROFILING
# ================================================================

def profile_spike_retraces(bars, spike_indices, atr_vals, lookforward=15):
    """Profile what happens AFTER each spike — retrace depth, speed, shape."""
    profiles = []

    for sidx in spike_indices:
        if sidx + 1 >= len(bars):
            continue

        spike_bar = bars[sidx]
        spike_body = spike_bar["close"] - spike_bar["open"]  # signed
        spike_high = spike_bar["high"]
        spike_low = spike_bar["low"]
        spike_body_abs = abs(spike_body)

        if spike_body_abs <= 0:
            continue

        # Boom: spikes go UP (positive body)
        # Profile: how deep does price retrace from the spike high?
        max_retrace = 0
        retrace_speed = 0  # bars to reach max retrace
        retrace_at_1 = 0
        retrace_at_3 = 0
        retrace_at_5 = 0
        retrace_at_10 = 0
        close_retrace = 0

        for j in range(sidx + 1, min(sidx + lookforward + 1, len(bars))):
            if spike_high > spike_low:
                # Retrace from spike high
                current_retrace = (spike_high - bars[j]["low"]) / spike_body_abs
                current_retrace = max(0, min(1, current_retrace))

                if current_retrace > max_retrace:
                    max_retrace = current_retrace
                    retrace_speed = j - sidx

            bars_out = j - sidx
            current_price = bars[j]["close"]
            if spike_high > spike_low:
                cr = (spike_high - current_price) / spike_body_abs
                cr = max(0, min(1, cr))

                if bars_out == 1:
                    retrace_at_1 = cr
                if bars_out == 3:
                    retrace_at_3 = cr
                if bars_out == 5:
                    retrace_at_5 = cr
                if bars_out == 10:
                    retrace_at_10 = cr

        # Final retrace at end of lookforward
        end_idx = min(sidx + lookforward, len(bars) - 1)
        if spike_high > spike_low:
            close_retrace = (spike_high - bars[end_idx]["close"]) / spike_body_abs
            close_retrace = max(0, min(1, close_retrace))

        profiles.append({
            "idx": sidx,
            "spike_body": spike_body_abs,
            "spike_high": spike_high,
            "spike_low": spike_low,
            "body_ratio": spike_data[sidx]["body_ratio"] if sidx < len(spike_data) else 0,
            "max_retrace": max_retrace,
            "retrace_speed": retrace_speed,
            "retrace_at_1": retrace_at_1,
            "retrace_at_3": retrace_at_3,
            "retrace_at_5": retrace_at_5,
            "retrace_at_10": retrace_at_10,
            "close_retrace": close_retrace,
            "atr": atr_vals[min(sidx, len(atr_vals) - 1)] if sidx < len(atr_vals) else 0,
        })

    return profiles


def print_spike_profiles(profiles):
    """Print detailed spike retrace analysis."""
    if not profiles:
        print("  No spikes to profile")
        return

    print(f"\n  Total spikes profiled: {len(profiles)}")

    # Retrace depth distribution
    max_retraces = [p["max_retrace"] for p in profiles]
    print(f"\n  MAX RETRACE DEPTH (from spike high):")
    print(f"    Mean: {statistics.mean(max_retraces)*100:.1f}%")
    print(f"    Median: {statistics.median(max_retraces)*100:.1f}%")
    print(f"    Std: {statistics.stdev(max_retraces)*100:.1f}%" if len(max_retraces) > 1 else "")
    for pct in [25, 50, 75, 90]:
        val = sorted(max_retraces)[int(len(max_retraces) * pct / 100)]
        print(f"    P{pct}: {val*100:.1f}%")

    # How many reach key retrace levels
    for level in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
        count = sum(1 for r in max_retraces if r >= level)
        print(f"    Spikes reaching {level*100:.0f}% retrace: {count}/{len(profiles)} ({100*count/len(profiles):.1f}%)")

    # Retrace timing
    speeds = [p["retrace_speed"] for p in profiles if p["max_retrace"] >= 0.30]
    if speeds:
        print(f"\n  TIME TO 30%+ RETRACE:")
        print(f"    Mean: {statistics.mean(speeds):.1f} bars")
        print(f"    Median: {statistics.median(speeds):.1f} bars")

    # Retrace at specific bar offsets
    print(f"\n  RETRACE AT BAR OFFSET (of spikes reaching 30%+):")
    eligible = [p for p in profiles if p["max_retrace"] >= 0.30]
    if eligible:
        for offset, key in [(1, "retrace_at_1"), (3, "retrace_at_3"), (5, "retrace_at_5"), (10, "retrace_at_10")]:
            vals = [p[key] for p in eligible]
            if vals:
                print(f"    Bar +{offset}: mean={statistics.mean(vals)*100:.1f}% median={statistics.median(vals)*100:.1f}%")

    # Spike body size distribution
    bodies = [p["spike_body"] for p in profiles]
    print(f"\n  SPIKE BODY SIZE:")
    print(f"    Mean: {statistics.mean(bodies):.2f}")
    print(f"    Median: {statistics.median(bodies):.2f}")
    for pct in [25, 50, 75, 90]:
        val = sorted(bodies)[int(len(bodies) * pct / 100)]
        print(f"    P{pct}: {val:.2f}")

    # Correlation: spike size vs retrace depth
    if len(profiles) > 5:
        sizes = [p["spike_body"] for p in profiles]
        retrace = [p["max_retrace"] for p in profiles]
        mean_s = statistics.mean(sizes)
        mean_r = statistics.mean(retrace)
        cov = sum((s - mean_s) * (r - mean_r) for s, r in zip(sizes, retrace)) / len(profiles)
        std_s = statistics.stdev(sizes) if len(sizes) > 1 else 1
        std_r = statistics.stdev(retrace) if len(retrace) > 1 else 1
        corr = cov / (std_s * std_r) if std_s * std_r > 0 else 0
        print(f"\n  CORRELATION (spike size vs retrace depth): {corr:+.3f}")
        print(f"    {'Bigger spikes retrace MORE' if corr > 0.1 else 'Bigger spikes retrace LESS' if corr < -0.1 else 'No clear relationship'}")


# ================================================================
# FADE BACKTEST ENGINE
# ================================================================

def backtest_fade_v2(bars, spike_indices, atr_vals, *,
                     sl_mult=0.4, tp_mult=1.8,
                     require_spike_direction=True,
                     retrace_min=0.30, retrace_max=0.70,
                     max_hold_bars=8, early_cut_r=None,
                     use_trail=False, trail_start_r=0.0, trail_dist_r=0.0,
                     post_spike_window=5, cooldown_bars=1,
                     profit_lock_r=None, breakeven_r=None):
    """Production-faithful fade backtest with all exit types."""
    trades = []
    cooldown = 0

    for sidx in spike_indices:
        spike_bar = bars[sidx]
        spike_body = abs(spike_bar["close"] - spike_bar["open"])
        spike_high = spike_bar["high"]
        spike_low = spike_bar["low"]

        if spike_body <= 0 or sidx + 1 >= len(bars):
            continue
        if require_spike_direction and spike_bar["close"] <= spike_bar["open"]:
            continue

        for j in range(sidx + 1, min(sidx + post_spike_window + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue

            if j >= len(atr_vals) or atr_vals[j] <= 0:
                continue

            atr = atr_vals[j]
            current_price = bars[j]["close"]

            # Boom: spike UP, fade by SELLING
            if current_price >= spike_high:
                continue

            retrace = (spike_high - current_price) / spike_body
            if not (retrace_min <= retrace <= retrace_max):
                continue

            entry = current_price
            sl = entry + sl_mult * atr
            tp = entry - tp_mult * atr

            # Ensure TP is below spike low
            if tp > spike_low:
                tp = spike_low - atr * 0.1

            risk_dist = sl - entry  # positive for sell
            if risk_dist <= 0:
                continue

            # Simulate forward
            result = None
            reason = "TIME"
            highest_price = entry  # for trailing (lowest since entry for sell)
            best_r = 0
            actual_exit_idx = j

            for k in range(j + 1, min(j + max_hold_bars + 5, len(bars))):
                bar = bars[k]
                actual_exit_idx = k

                # Update best price for trailing/profit-lock
                if bar["low"] < highest_price:
                    highest_price = bar["low"]
                current_r = (entry - highest_price) / risk_dist
                if current_r > best_r:
                    best_r = current_r

                # Breakeven: move SL to entry at breakeven_r
                if breakeven_r and best_r >= breakeven_r and sl > entry:
                    sl = entry + 1  # 1 point above entry for sell

                # Profit lock: close if best_r >= threshold and drops back
                if profit_lock_r and best_r >= profit_lock_r * 2 and current_r <= profit_lock_r:
                    result = current_r
                    reason = "PLOCK"
                    break

                # Trailing stop
                if use_trail and best_r >= trail_start_r:
                    new_sl = entry - (current_r - trail_dist_r) * risk_dist
                    if new_sl < sl:
                        sl = new_sl

                hit_sl = bar["high"] >= sl
                hit_tp = bar["low"] <= tp

                if hit_sl:
                    result = -(sl - entry) / risk_dist if sl != entry else -1.0
                    reason = "TRAIL" if sl < entry + sl_mult * atr * 0.5 else "STOP"
                    break
                if hit_tp:
                    result = tp_mult / sl_mult
                    reason = "TARGET"
                    break

                # Early cut
                if early_cut_r is not None:
                    cr = (entry - bar["close"]) / risk_dist
                    if cr < early_cut_r:
                        result = cr
                        reason = "ECUT"
                        break

            if result is None:
                exit_idx = min(j + max_hold_bars + 4, len(bars) - 1)
                result = (entry - bars[exit_idx]["close"]) / risk_dist if risk_dist > 0 else 0

            trades.append({
                "entry_idx": j,
                "entry_epoch": bars[j]["epoch"],
                "dir": -1,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "r": result,
                "reason": reason,
                "retrace_pct": retrace,
                "spike_body": spike_body,
            })
            cooldown = cooldown_bars
            break

    return trades


def split_walk_forward(bars, train_days=42, test_days=18):
    """Return chronological train/test slices; never optimize on the test tail."""
    if not bars:
        return [], []
    cutoff = bars[-1]["epoch"] - test_days * 86400
    train = [b for b in bars if b["epoch"] < cutoff]
    test = [b for b in bars if b["epoch"] >= cutoff]
    return train, test


def validate_out_of_sample(bars, params):
    """Evaluate fixed parameters on the unseen chronological tail."""
    _, test = split_walk_forward(bars)
    if len(test) < ATR_PERIOD + 20:
        return {"trades": 0, "warning": "insufficient test history"}
    test_atr = compute_atr(test)
    test_spikes = detect_spikes(test, threshold=params["spike_threshold"])
    test_indices = [s["idx"] for s in test_spikes if s["is_spike"]]
    trades = backtest_fade_v2(
        test, test_indices, test_atr,
        sl_mult=params["fade_sl_mult"], tp_mult=params["fade_tp_mult"],
        retrace_min=params["fade_r_entry"], retrace_max=params["fade_retrace_max"],
        max_hold_bars=params["max_hold_bars"],
        early_cut_r=params["early_cut_r"],
        use_trail=params["use_trail"],
        trail_start_r=params["trail_start_r"],
        trail_dist_r=params["trail_dist_r"],
        profit_lock_r=params["profit_lock_r"],
        breakeven_r=params["breakeven_r"],
    )
    return trade_stats(trades, "out-of-sample")





# ================================================================
# OPTIMIZATION SWEEPS
# ================================================================

def sweep_tp(bars, spikes, atr_vals):
    """Sweep TP multiplier with SL fixed."""
    print("\n" + "=" * 100)
    print("SWEEP 1: TP MULTIPLIER (SL=0.4xATR, no trail, no cut)")
    print("=" * 100)
    print(f"{'TP':>5} | {'Trades':>6} {'PerD':>5} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} {'EC':>3}")
    print("-" * 75)

    results = []
    for tp in [1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5, 3.0, 3.5]:
        trades = backtest_fade_v2(bars, spikes, atr_vals, tp_mult=tp)
        s = trade_stats(trades, f"TP={tp}")
        results.append((tp, s))
        ex = s.get("exits", {})
        print(f"{tp:>5} | {s['trades']:>6} {s.get('per_day',0):>5} {s.get('wr',0):>5} {s.get('pf',0):>5} "
              f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
              f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} {ex.get('ECUT',0):>3}")

    best = max(results, key=lambda x: x[1].get("exp_r", 0))
    print(f"\n  >> Best TP: {best[0]}x -> ExpR {best[1]['exp_r']:+.3f}, PF {best[1]['pf']}")
    return best[0]


def sweep_retrace_window(bars, spikes, atr_vals, tp_mult):
    """Sweep entry retrace window."""
    print("\n" + "=" * 100)
    print(f"SWEEP 2: RETRACE ENTRY WINDOW (TP={tp_mult}x, SL=0.4xATR)")
    print("=" * 100)
    print(f"{'Window':<12} | {'Trades':>6} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6}")
    print("-" * 60)

    results = []
    for rmin, rmax in [(0.20, 0.80), (0.25, 0.75), (0.25, 0.60), (0.30, 0.70),
                        (0.30, 0.60), (0.35, 0.65), (0.35, 0.55), (0.40, 0.60),
                        (0.40, 0.50), (0.20, 0.50), (0.25, 0.50)]:
        trades = backtest_fade_v2(bars, spikes, atr_vals, tp_mult=tp_mult,
                                   retrace_min=rmin, retrace_max=rmax)
        s = trade_stats(trades, f"{rmin*100:.0f}-{rmax*100:.0f}%")
        results.append(((rmin, rmax), s))
        print(f"{rmin*100:.0f}-{rmax*100:.0f}%{'':<5} | {s['trades']:>6} {s.get('wr',0):>5} "
              f"{s.get('pf',0):>5} {s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6}")

    best = max(results, key=lambda x: x[1].get("exp_r", 0))
    print(f"\n  >> Best window: {best[0][0]*100:.0f}-{best[0][1]*100:.0f}% -> ExpR {best[1]['exp_r']:+.3f}")
    return best[0]


def sweep_hold_and_cuts(bars, spikes, atr_vals, tp_mult, retrace_min, retrace_max):
    """Sweep max hold bars and early cut levels."""
    print("\n" + "=" * 100)
    print(f"SWEEP 3: HOLD + EARLY CUT (TP={tp_mult}x, SL=0.4x, window={retrace_min*100:.0f}-{retrace_max*100:.0f}%)")
    print("=" * 100)
    print(f"{'Hold':>5} {'ECut':>6} | {'Trades':>6} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} {'EC':>3}")
    print("-" * 75)

    results = []
    for hold in [5, 6, 8, 10, 12, 15]:
        for ec in [None, -0.20, -0.25, -0.30, -0.35, -0.40, -0.50]:
            trades = backtest_fade_v2(bars, spikes, atr_vals, tp_mult=tp_mult,
                                       retrace_min=retrace_min, retrace_max=retrace_max,
                                       max_hold_bars=hold, early_cut_r=ec)
            s = trade_stats(trades)
            results.append((hold, ec, s))
            ec_str = f"{ec:.2f}" if ec else "None"
            ex = s.get("exits", {})
            print(f"{hold:>5} {ec_str:>6} | {s['trades']:>6} {s.get('wr',0):>5} {s.get('pf',0):>5} "
                  f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
                  f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} {ex.get('ECUT',0):>3}")

    best = max(results, key=lambda x: x[2].get("exp_r", 0))
    print(f"\n  >> Best: Hold={best[0]} ECut={best[1]} -> ExpR {best[2]['exp_r']:+.3f}")
    return best[0], best[1]


def sweep_trailing(bars, spikes, atr_vals, tp_mult, retrace_min, retrace_max, max_hold, ec):
    """Sweep trailing stop configurations."""
    print("\n" + "=" * 100)
    print(f"SWEEP 4: TRAILING STOP (TP={tp_mult}x, hold={max_hold}, EC={ec})")
    print("=" * 100)
    print(f"{'Config':<25} | {'Trades':>6} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} {'Trl':>3}")
    print("-" * 80)

    configs = [
        ("No trail", False, 0, 0),
        ("Start@0.5R Dist@0.2R", True, 0.5, 0.2),
        ("Start@0.5R Dist@0.3R", True, 0.5, 0.3),
        ("Start@0.8R Dist@0.3R", True, 0.8, 0.3),
        ("Start@0.8R Dist@0.4R", True, 0.8, 0.4),
        ("Start@1.0R Dist@0.3R", True, 1.0, 0.3),
        ("Start@1.0R Dist@0.5R", True, 1.0, 0.5),
        ("Start@1.2R Dist@0.4R", True, 1.2, 0.4),
        ("Start@1.5R Dist@0.5R", True, 1.5, 0.5),
        ("Start@0.5R Dist@0.5R", True, 0.5, 0.5),
    ]

    results = []
    for name, use_trail, t_start, t_dist in configs:
        trades = backtest_fade_v2(bars, spikes, atr_vals, tp_mult=tp_mult,
                                   retrace_min=retrace_min, retrace_max=retrace_max,
                                   max_hold_bars=max_hold, early_cut_r=ec,
                                   use_trail=use_trail, trail_start_r=t_start, trail_dist_r=t_dist)
        s = trade_stats(trades, name)
        results.append((name, use_trail, t_start, t_dist, s))
        ex = s.get("exits", {})
        print(f"{name:<25} | {s['trades']:>6} {s.get('wr',0):>5} {s.get('pf',0):>5} "
              f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
              f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} {ex.get('TRAIL',0):>3}")

    best = max(results, key=lambda x: x[4].get("exp_r", 0))
    print(f"\n  >> Best trail: {best[0]} -> ExpR {best[4]['exp_r']:+.3f}")
    return best[1], best[2], best[3]


def sweep_profit_lock(bars, spikes, atr_vals, tp_mult, retrace_min, retrace_max,
                      max_hold, ec, use_trail, t_start, t_dist):
    """Sweep profit lock + breakeven configurations."""
    print("\n" + "=" * 100)
    print(f"SWEEP 5: PROFIT LOCK + BREAKEVEN")
    print("=" * 100)
    print(f"{'PLock':>6} {'BE':>6} | {'Trades':>6} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} {'PL':>3}")
    print("-" * 75)

    results = []
    for pl in [None, 0.5, 0.8, 1.0, 1.2]:
        for be in [None, 0.5, 0.8, 1.0]:
            trades = backtest_fade_v2(bars, spikes, atr_vals, tp_mult=tp_mult,
                                       retrace_min=retrace_min, retrace_max=retrace_max,
                                       max_hold_bars=max_hold, early_cut_r=ec,
                                       use_trail=use_trail, trail_start_r=t_start, trail_dist_r=t_dist,
                                       profit_lock_r=pl, breakeven_r=be)
            s = trade_stats(trades)
            results.append((pl, be, s))
            pl_str = f"{pl:.1f}" if pl else "None"
            be_str = f"{be:.1f}" if be else "None"
            ex = s.get("exits", {})
            print(f"{pl_str:>6} {be_str:>6} | {s['trades']:>6} {s.get('wr',0):>5} {s.get('pf',0):>5} "
                  f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
                  f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} {ex.get('PLOCK',0):>3}")

    best = max(results, key=lambda x: x[2].get("exp_r", 0))
    print(f"\n  >> Best: PLock={best[0]} BE={best[1]} -> ExpR {best[2]['exp_r']:+.3f}")
    return best[0], best[1]


def sweep_spike_threshold(bars, atr_vals, tp_mult, retrace_min, retrace_max,
                          max_hold, ec, use_trail, t_start, t_dist, pl, be):
    """Sweep spike detection threshold."""
    print("\n" + "=" * 100)
    print("SWEEP 6: SPIKE DETECTION THRESHOLD")
    print("=" * 100)
    print(f"{'Thresh':>7} | {'Trades':>6} {'PerD':>5} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6}")
    print("-" * 65)

    results = []
    for thresh in [2.0, 2.2, 2.5, 2.8, 3.0, 3.5, 4.0]:
        spikes = detect_spikes(bars, threshold=thresh)
        spike_indices = [s["idx"] for s in spikes if s["is_spike"]]
        trades = backtest_fade_v2(bars, spike_indices, atr_vals, tp_mult=tp_mult,
                                   retrace_min=retrace_min, retrace_max=retrace_max,
                                   max_hold_bars=max_hold, early_cut_r=ec,
                                   use_trail=use_trail, trail_start_r=t_start, trail_dist_r=t_dist,
                                   profit_lock_r=pl, breakeven_r=be)
        s = trade_stats(trades, f"thresh={thresh}")
        results.append((thresh, s, len(spike_indices)))
        print(f"{thresh:>7} | {s['trades']:>6} {s.get('per_day',0):>5} {s.get('wr',0):>5} "
              f"{s.get('pf',0):>5} {s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6}")

    best = max(results, key=lambda x: x[1].get("exp_r", 0))
    print(f"\n  >> Best threshold: {best[0]}x -> ExpR {best[1]['exp_r']:+.3f} ({best[2]} spikes)")
    return best[0]


# ================================================================
# CRASH 1000 MIRROR
# ================================================================

def backtest_fade_crash_v2(bars, spike_indices, atr_vals, **kwargs):
    """Crash 1000 mirror: spikes go DOWN, fade by BUYING."""
    trades = []
    cooldown = kwargs.get("cooldown_bars", 1)
    cd_counter = 0
    sl_mult = kwargs.get("sl_mult", 0.4)
    tp_mult = kwargs.get("tp_mult", 1.8)
    retrace_min = kwargs.get("retrace_min", 0.30)
    retrace_max = kwargs.get("retrace_max", 0.70)
    max_hold = kwargs.get("max_hold_bars", 8)
    early_cut = kwargs.get("early_cut_r", None)
    post_window = kwargs.get("post_spike_window", 5)

    for sidx in spike_indices:
        spike_bar = bars[sidx]
        spike_body = abs(spike_bar["close"] - spike_bar["open"])
        spike_high = spike_bar["high"]
        spike_low = spike_bar["low"]

        if spike_body <= 0 or sidx + 1 >= len(bars):
            continue

        for j in range(sidx + 1, min(sidx + post_window + 1, len(bars))):
            if cd_counter > 0:
                cd_counter -= 1
                continue
            if j >= len(atr_vals) or atr_vals[j] <= 0:
                continue

            atr = atr_vals[j]
            price = bars[j]["close"]

            # Crash: spike DOWN, fade by BUYING
            if price <= spike_low:
                continue

            retrace = (price - spike_low) / spike_body
            if not (retrace_min <= retrace <= retrace_max):
                continue

            entry = price
            sl = entry - sl_mult * atr
            tp = entry + tp_mult * atr
            if tp < spike_high:
                tp = spike_high + atr * 0.1

            risk_dist = entry - sl
            if risk_dist <= 0:
                continue

            result = None
            reason = "TIME"
            for k in range(j + 1, min(j + max_hold + 5, len(bars))):
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
                if early_cut is not None:
                    cr = (bar["close"] - entry) / risk_dist
                    if cr < early_cut:
                        result = cr
                        reason = "ECUT"
                        break

            if result is None:
                exit_idx = min(j + max_hold + 4, len(bars) - 1)
                result = (bars[exit_idx]["close"] - entry) / risk_dist if risk_dist > 0 else 0

            trades.append({
                "entry_idx": j, "entry_epoch": bars[j]["epoch"],
                "r": result, "reason": reason,
            })
            cd_counter = cooldown
            break

    return trades


# ================================================================
# MAIN
# ================================================================

global spike_data

def main():
    global spike_data

    print("=" * 100)
    print("BOOM 1000 — FADE-PERFECTION OPTIMIZER")
    print("Deep spike profiling + multi-dimensional parameter sweep")
    print("=" * 100)

    # Step 1: Load data via the shared terminal-first loader (no CSV snapshots)
    print("\n[mt5] Loading Boom 1000 M5 from terminal (shared mt5_data loader)...")
    try:
        bars_full = load_m5("Boom 1000 Index", "M5", 20000)
    except Exception as exc:
        print(f"ERROR: could not load Boom 1000 data: {exc}")
        return 1

    bars = slice_60d(bars_full, 60)
    if not bars:
        print("ERROR: No 60-day data")
        return 1

    t0 = datetime.fromtimestamp(bars[0]["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
    t1 = datetime.fromtimestamp(bars[-1]["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
    actual_days = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400
    print(f"60-day window: {t0} -> {t1} ({actual_days:.0f}d) ({len(bars)} bars)")

    # Step 2: Detect spikes
    spike_data = detect_spikes(bars, threshold=2.5)
    spike_indices = [s["idx"] for s in spike_data if s["is_spike"]]
    print(f"\nDetected {len(spike_indices)} spikes (threshold=2.5x)")

    # Step 3: Compute ATR
    atr_vals = compute_atr(bars)

    # Step 4: Profile spike retrace patterns
    print("\n" + "=" * 100)
    print("SPIKE RETRACE PROFILING")
    print("=" * 100)
    profiles = profile_spike_retraces(bars, spike_indices, atr_vals)
    print_spike_profiles(profiles)

    # Step 5: HONEST WALK-FORWARD — every sweep below runs on the TRAIN slice
    # only. The final 18-day tail is touched exactly once, with fixed params,
    # and is the sole deployment gate. (The previous version swept the full
    # 60d window and then "validated" on its own tail — OOS was contaminated.)
    train, test = split_walk_forward(bars)
    train_spikes = detect_spikes(train, threshold=2.5)
    train_indices = [s["idx"] for s in train_spikes if s["is_spike"]]
    train_atr = compute_atr(train)
    print(f"\nWalk-forward: train={len(train)} bars ({len(train_indices)} spikes) | "
          f"test={len(test)} bars held out from every sweep")

    tp_mult = sweep_tp(train, train_indices, train_atr)
    retrace_min, retrace_max = sweep_retrace_window(train, train_indices, train_atr, tp_mult)
    max_hold, ec = sweep_hold_and_cuts(train, train_indices, train_atr, tp_mult, retrace_min, retrace_max)
    use_trail, t_start, t_dist = sweep_trailing(train, train_indices, train_atr, tp_mult,
                                                retrace_min, retrace_max, max_hold, ec)
    pl, be = sweep_profit_lock(train, train_indices, train_atr, tp_mult, retrace_min, retrace_max,
                               max_hold, ec, use_trail, t_start, t_dist)
    spike_thresh = sweep_spike_threshold(train, train_atr, tp_mult, retrace_min, retrace_max,
                                         max_hold, ec, use_trail, t_start, t_dist, pl, be)

    # Step 6: Final combined run — fixed params on TRAIN (sanity check)
    print("\n" + "=" * 100)
    print("TRAIN SLICE — FIXED PARAMS (sanity, not the gate)")
    print("=" * 100)
    final_trades = backtest_fade_v2(train, train_indices, train_atr,
                                    sl_mult=0.4, tp_mult=tp_mult,
                                    retrace_min=retrace_min, retrace_max=retrace_max,
                                    max_hold_bars=max_hold, early_cut_r=ec,
                                    use_trail=use_trail, trail_start_r=t_start, trail_dist_r=t_dist,
                                    profit_lock_r=pl, breakeven_r=be)
    final_stats = trade_stats(final_trades, "BOOM 1000 FADE-TRAIN")
    print(f"\n  Trades: {final_stats['trades']}")
    print(f"  Win Rate: {final_stats['wr']}%")
    print(f"  Profit Factor: {final_stats['pf']}")
    print(f"  Expectancy: {final_stats['exp_r']:+.3f} R/trade")
    print(f"  Max Drawdown: {final_stats['max_dd_r']}R")
    print(f"  Trades/day: {final_stats['per_day']}")
    print(f"  Exits: {final_stats.get('exits', {})}")

    # Step 7: Crash 1000 mirror — fixed mirrored params evaluated on the crash
    # TEST tail only (no crash data participates in any parameter selection)
    print("\n" + "=" * 100)
    print("CRASH 1000 MIRROR (fixed mirrored params, crash TEST tail)")
    print("=" * 100)
    print("\n[mt5] Loading Crash 1000 M5 from terminal (shared mt5_data loader)...")
    try:
        crash_full = load_m5("Crash 1000 Index", "M5", 20000)
        crash_bars = slice_60d(crash_full, 60)
    except Exception as exc:
        print(f"[warn] Could not load Crash 1000 data: {exc}; skipping mirror test")
        crash_bars = []
    if crash_bars:
            _, crash_test = split_walk_forward(crash_bars)
            crash_spikes = detect_spikes(crash_test, threshold=spike_thresh)
            crash_indices = [s["idx"] for s in crash_spikes if s["is_spike"]]
            crash_atr = compute_atr(crash_test)
            crash_trades = backtest_fade_crash_v2(crash_test, crash_indices, crash_atr,
                                                  sl_mult=0.4, tp_mult=tp_mult,
                                                  retrace_min=retrace_min, retrace_max=retrace_max,
                                                  max_hold_bars=max_hold, early_cut_r=ec)
            crash_stats = trade_stats(crash_trades, "CRASH 1000 FADE")
            print(f"  Trades: {crash_stats['trades']}")
            print(f"  Win Rate: {crash_stats['wr']}%")
            print(f"  Profit Factor: {crash_stats['pf']}")
            print(f"  Expectancy: {crash_stats['exp_r']:+.3f} R/trade")
            print(f"  Max Drawdown: {crash_stats['max_dd_r']}R")

    # Step 8: Generate EA parameters
    print("\n" + "=" * 100)
    print("EA DEPLOYMENT PARAMETERS")
    print("=" * 100)
    ea_params = {
        "spike_threshold": spike_thresh,
        "fade_sl_mult": 0.4,
        "fade_tp_mult": tp_mult,
        "fade_r_entry": retrace_min,
        "fade_retrace_max": retrace_max,
        "post_spike_window": 5,
        "max_hold_bars": max_hold,
        "early_cut_r": ec,
        "use_trail": use_trail,
        "trail_start_r": t_start,
        "trail_dist_r": t_dist,
        "profit_lock_r": pl,
        "breakeven_r": be,
        "cooldown_bars": 1,
        "max_spike_prob": 0.70,
        "base_risk_pct": 0.5,
        "min_risk_pct": 0.15,
    }

    for k, v in ea_params.items():
        print(f"  {k}: {v}")

    print(f"\n  Recommended InpCBFadeSL = {ea_params['fade_sl_mult']}")
    print(f"  Recommended InpCBFadeTP = {ea_params['fade_tp_mult']}")
    print(f"  Recommended InpCBSpikeThreshold = {ea_params['spike_threshold']}")
    print(f"  Recommended InpCBMaxSpikeProb = {ea_params['max_spike_prob']}")
    print(f"  Recommended InpCBFadeR = {ea_params['fade_r_entry']}")
    print(f"  Recommended InpCBEnableGrind = false")

    # Evaluate the selected parameters on a chronological holdout.
    oos_stats = validate_out_of_sample(bars, ea_params)
    print("\n" + "=" * 100)
    print("OUT-OF-SAMPLE HOLDOUT (fixed parameters, final 18 days)")
    print("=" * 100)
    print(f"  Trades: {oos_stats.get('trades', 0)} | WR: {oos_stats.get('wr', 0)}% | "
          f"PF: {oos_stats.get('pf', 0)} | ExpR: {oos_stats.get('exp_r', 0):+.3f} | "
          f"DD: {oos_stats.get('max_dd_r', 0)}R")

    # Verdict — gated ONLY on the held-out tail (honest deployment gate)
    print("\n" + "=" * 100)
    if oos_stats.get("exp_r", 0) > 0.15 and oos_stats.get("pf", 0) > 1.3:
        print("[STRONG EDGE] Ready for Tier 1 deployment")
    elif oos_stats.get("exp_r", 0) > 0:
        print("[MARGINAL EDGE] Demo first, monitor closely")
    else:
        print("[NO EDGE] Do not deploy")
    print("=" * 100)

    # Save results
    out = {
        "window": {"start": t0, "end": t1, "days": round(actual_days, 1)},
        "spike_profiles": {
            "count": len(profiles),
            "max_retrace_mean": round(statistics.mean([p["max_retrace"] for p in profiles]), 3) if profiles else 0,
            "max_retrace_median": round(statistics.median([p["max_retrace"] for p in profiles]), 3) if profiles else 0,
        },
        "optimized_params": ea_params,
        "final_stats": final_stats,
        "out_of_sample_stats": oos_stats,
    }
    out_path = ART / "boom1000_fade_perfection.json"
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
