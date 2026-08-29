#!/usr/bin/env python3
"""Boom 1000 60-day analysis: spike stats, grind patterns, fade/grind strategy backtest.

Pulls M5 history from MT5, then analyzes:
  1. Spike frequency, size distribution, inter-spike gaps
  2. Grind direction/duration patterns
  3. Post-spike fade profitability (EA-faithful logic)
  4. Grind continuation profitability
  5. Time-of-day spike distribution

Usage:
    .venv/Scripts/python.exe scripts/boom1000_60day_analysis.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5  # shared loader: terminal + .npy cache
from synthlib import (
    slice_60d, detect_spikes, get_spike_indices,
    compute_atr, compute_body_ema, detect_grinds, trade_stats,
)

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

# EA parameters (from SymbolCalibration.mqh for Boom 1000)
SPIKE_THRESHOLD = 2.5      # body >= 2.5x avg = spike
FADE_SL_MULT = 0.4         # stop = 0.4 * ATR
FADE_TP_MULT = 1.8         # tp = 1.8 * ATR
COOLDOWN_BARS = 1          # bars after spike before entry
POST_SPIKE_WINDOW = 5      # bars after spike that fade is valid
GRIND_SL_MULT = 2.0        # stop = 2.0 * avg_body
GRIND_MIN_BARS = 2         # min grind duration to enter
GRIND_MAX_BARS = 20        # max grind duration (spike imminent beyond this)
MAX_SPIKE_PROB = 0.70      # block entries above this
ATR_PERIOD = 14


def backtest_fade(bars, spike_indices, atr_vals):
    """Post-spike fade backtest (Boom 1000: spikes go UP -> fade by SELLING)."""
    trades = []
    cooldown = 0

    for sidx in spike_indices:
        spike_bar = bars[sidx]
        spike_body = abs(spike_bar["close"] - spike_bar["open"])
        spike_high = spike_bar["high"]
        spike_low = spike_bar["low"]

        # Check bars after spike for fade opportunity
        for j in range(sidx + 1, min(sidx + POST_SPIKE_WINDOW + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue

            current = bars[j]
            if j >= len(atr_vals) or atr_vals[j] <= 0:
                continue

            atr = atr_vals[j]
            current_price = current["close"]

            # Boom: spike went UP, fade by SELLING
            if current_price < spike_high:
                retrace = (spike_high - current_price) / spike_body if spike_body > 0 else 0

                if 0.30 <= retrace <= 0.70:
                    entry = current_price
                    sl = entry + FADE_SL_MULT * atr
                    tp = entry - FADE_TP_MULT * atr

                    # TP should be below spike low
                    if tp > spike_low:
                        tp = spike_low - atr * 0.2

                    # Simulate forward
                    result = None
                    reason = "TIME"
                    for k in range(j + 1, min(j + 8, len(bars))):
                        hit_sl = bars[k]["high"] >= sl
                        hit_tp = bars[k]["low"] <= tp
                        if hit_sl:
                            result = -1.0
                            reason = "STOP"
                            break
                        if hit_tp:
                            result = FADE_TP_MULT / FADE_SL_MULT
                            reason = "TARGET"
                            break

                    if result is None:
                        # Time exit at current close
                        result = (entry - bars[min(j + 7, len(bars) - 1)]["close"]) / (sl - entry) if sl != entry else 0

                    trades.append({
                        "entry_idx": j,
                        "entry_epoch": bars[j]["epoch"],
                        "dir": -1,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "r": result,
                        "reason": reason,
                        "signal_type": "CB-FADE",
                        "spike_idx": sidx,
                        "retrace_pct": retrace,
                    })
                    cooldown = COOLDOWN_BARS
                    break

    return trades


def backtest_grind(bars, grinds, atr_vals, spike_indices_set):
    """Grind continuation backtest (Boom 1000: grind DOWN -> SELL)."""
    trades = []
    cooldown = 0

    for grind in grinds:
        if grind["duration"] < GRIND_MIN_BARS or grind["duration"] > GRIND_MAX_BARS:
            continue

        # Entry at end of grind
        entry_idx = grind["end"]
        if entry_idx + 1 >= len(bars):
            continue
        if cooldown > 0:
            cooldown -= 1
            continue

        # Check no spike nearby
        nearby_spike = any(abs(s - entry_idx) <= 2 for s in spike_indices_set)
        if nearby_spike:
            continue

        if entry_idx >= len(atr_vals) or atr_vals[entry_idx] <= 0:
            continue

        current_price = bars[entry_idx + 1]["open"] if entry_idx + 1 < len(bars) else bars[entry_idx]["close"]
        body_avg = grind["avg_body"]

        # Boom grind DOWN -> SELL
        if grind["direction"] < 0:
            entry = current_price
            sl = entry + GRIND_SL_MULT * body_avg
            tp = entry - GRIND_SL_MULT * body_avg * 2.0

            result = None
            reason = "TIME"
            for k in range(entry_idx + 2, min(entry_idx + 10, len(bars))):
                hit_sl = bars[k]["high"] >= sl
                hit_tp = bars[k]["low"] <= tp
                if hit_sl:
                    result = -1.0
                    reason = "STOP"
                    break
                if hit_tp:
                    result = 2.0
                    reason = "TARGET"
                    break

            if result is None:
                exit_idx = min(entry_idx + 9, len(bars) - 1)
                result = (entry - bars[exit_idx]["close"]) / (sl - entry) if sl != entry else 0

            trades.append({
                "entry_idx": entry_idx + 1,
                "entry_epoch": bars[entry_idx + 1]["epoch"] if entry_idx + 1 < len(bars) else bars[entry_idx]["epoch"],
                "dir": -1,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "r": result,
                "reason": reason,
                "signal_type": "CB-GRIND",
                "grind_dir": grind["direction"],
                "grind_dur": grind["duration"],
            })
            cooldown = COOLDOWN_BARS

        # Boom grind UP -> BUY (with trend, but less reliable for Boom)
        elif grind["direction"] > 0:
            entry = current_price
            sl = entry - GRIND_SL_MULT * body_avg
            tp = entry + GRIND_SL_MULT * body_avg * 2.0

            result = None
            reason = "TIME"
            for k in range(entry_idx + 2, min(entry_idx + 10, len(bars))):
                hit_sl = bars[k]["low"] <= sl
                hit_tp = bars[k]["high"] >= tp
                if hit_sl:
                    result = -1.0
                    reason = "STOP"
                    break
                if hit_tp:
                    result = 2.0
                    reason = "TARGET"
                    break

            if result is None:
                exit_idx = min(entry_idx + 9, len(bars) - 1)
                result = (bars[exit_idx]["close"] - entry) / (entry - sl) if entry != sl else 0

            trades.append({
                "entry_idx": entry_idx + 1,
                "entry_epoch": bars[entry_idx + 1]["epoch"] if entry_idx + 1 < len(bars) else bars[entry_idx]["epoch"],
                "dir": 1,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "r": result,
                "reason": reason,
                "signal_type": "CB-GRIND",
                "grind_dir": grind["direction"],
                "grind_dur": grind["duration"],
            })
            cooldown = COOLDOWN_BARS

    return trades


def analyze_spikes(spikes, bars):
    """Analyze spike patterns."""
    spike_indices = [s["idx"] for s in spikes if s["is_spike"]]
    spike_bodies = [s["body"] for s in spikes if s["is_spike"]]
    spike_ratios = [s["body_ratio"] for s in spikes if s["is_spike"]]

    # Inter-spike gaps
    gaps = []
    for i in range(1, len(spike_indices)):
        gap_bars = spike_indices[i] - spike_indices[i - 1]
        gap_min = gap_bars * 5  # M5 = 5 min each
        gaps.append({"bars": gap_bars, "minutes": gap_min})

    # Body distribution
    if spike_bodies:
        pcts = [25, 50, 75, 90, 95]
        sorted_bodies = sorted(spike_bodies)
        print(f"\n  Spike count: {len(spike_indices)}")
        print(f"  Body size: median={statistics.median(spike_bodies):.2f} "
              f"mean={statistics.mean(spike_bodies):.2f} "
              f"std={statistics.stdev(spike_bodies):.2f}" if len(spike_bodies) > 1 else "")
        for p in pcts:
            idx = int(len(sorted_bodies) * p / 100)
            print(f"    P{p}: {sorted_bodies[min(idx, len(sorted_bodies)-1)]:.2f}")

        print(f"  Body ratio (vs avg): median={statistics.median(spike_ratios):.1f}x "
              f"mean={statistics.mean(spike_ratios):.1f}x")

    # Gap distribution
    if gaps:
        gap_mins = [g["minutes"] for g in gaps]
        print(f"\n  Inter-spike gap: median={statistics.median(gap_mins):.0f}min "
              f"mean={statistics.mean(gap_mins):.0f}min "
              f"std={statistics.stdev(gap_mins):.0f}min" if len(gap_mins) > 1 else "")
        pcts = [25, 50, 75]
        sorted_gaps = sorted(gap_mins)
        for p in pcts:
            idx = int(len(sorted_gaps) * p / 100)
            print(f"    P{p}: {sorted_gaps[min(idx, len(sorted_gaps)-1)]:.0f}min")

    # Spikes per day
    total_days = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400
    spikes_per_day = len(spike_indices) / total_days if total_days > 0 else 0
    print(f"\n  Spikes/day: {spikes_per_day:.2f}  (~1 per {86400/spikes_per_day/60:.0f}min)" if spikes_per_day > 0 else "")

    # Time-of-day distribution
    spike_hours = defaultdict(int)
    for sidx in spike_indices:
        ts = datetime.fromtimestamp(bars[sidx]["epoch"], tz=timezone.utc)
        spike_hours[ts.hour] += 1
    print(f"\n  Spike hours (UTC):")
    for h in range(24):
        count = spike_hours.get(h, 0)
        bar = "#" * count
        print(f"    {h:02d}:00  {count:>3} {bar}")

    return spike_indices


def main():
    print("=" * 100)
    print("BOOM 1000 INDEX - 60-DAY ANALYSIS")
    print("EA-Faithful: Post-Spike Fade + Grind Continuation")
    print(f"Params: spike_thresh={SPIKE_THRESHOLD}x | fade SL={FADE_SL_MULT}xATR TP={FADE_TP_MULT}xATR | "
          f"grind SL={GRIND_SL_MULT}xBody | cooldown={COOLDOWN_BARS} bars")
    print("=" * 100)

    # Step 1: Fetch or load data — shared loader (terminal first, .npy cache fallback)
    bars_full = load_m5("Boom 1000 Index", "M5")

    # Slice to 60 days
    bars_60d = slice_60d(bars_full, 60)
    if not bars_60d:
        print("ERROR: No data in 60-day window")
        return 1

    t0 = datetime.fromtimestamp(bars_60d[0]["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
    t1 = datetime.fromtimestamp(bars_60d[-1]["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
    actual_days = (bars_60d[-1]["epoch"] - bars_60d[0]["epoch"]) / 86400
    print(f"\n60-day window: {t0} -> {t1}  ({actual_days:.0f}d)  ({len(bars_60d)} M5 bars)")

    # Step 2: Compute indicators
    print("\n" + "-" * 80)
    print("STEP 1: SPIKE ANALYSIS")
    print("-" * 80)
    spikes = detect_spikes(bars_60d, SPIKE_THRESHOLD)
    spike_indices = analyze_spikes(spikes, bars_60d)

    # Step 3: Grind analysis
    print("\n" + "-" * 80)
    print("STEP 2: GRIND ANALYSIS")
    print("-" * 80)
    grinds = detect_grinds(bars_60d)
    print(f"  Total grinds (>=3 bars): {len(grinds)}")
    if grinds:
        up_grinds = [g for g in grinds if g["direction"] > 0]
        down_grinds = [g for g in grinds if g["direction"] < 0]
        print(f"  UP grinds: {len(up_grinds)}  avg_dur={statistics.mean([g['duration'] for g in up_grinds]):.1f} bars")
        print(f"  DOWN grinds: {len(down_grinds)}  avg_dur={statistics.mean([g['duration'] for g in down_grinds]):.1f} bars")

        # Grind duration distribution
        durations = [g["duration"] for g in grinds]
        print(f"  Duration: median={statistics.median(durations):.0f} mean={statistics.mean(durations):.1f} "
              f"max={max(durations)}")

        # Grinds that reach entry criteria
        eligible = [g for g in grinds if GRIND_MIN_BARS <= g["duration"] <= GRIND_MAX_BARS]
        print(f"  Eligible for trade (dur {GRIND_MIN_BARS}-{GRIND_MAX_BARS}): {len(eligible)}")

    # Step 4: ATR
    atr_vals = compute_atr(bars_60d, ATR_PERIOD)

    # Step 5: Backtest FADE
    print("\n" + "-" * 80)
    print("STEP 3: POST-SPIKE FADE BACKTEST")
    print("-" * 80)
    fade_trades = backtest_fade(bars_60d, spike_indices, atr_vals)
    fade_stats = trade_stats(fade_trades, "CB-FADE (sell after spike)")

    # Step 6: Backtest GRIND
    print("\n" + "-" * 80)
    print("STEP 4: GRIND CONTINUATION BACKTEST")
    print("-" * 80)
    spike_set = set(spike_indices)
    grind_trades = backtest_grind(bars_60d, grinds, atr_vals, spike_set)
    grind_stats = trade_stats(grind_trades, "CB-GRIND (trade with grind)")

    # Step 7: Combined
    print("\n" + "-" * 80)
    print("STEP 5: COMBINED STRATEGY")
    print("-" * 80)
    all_trades = sorted(fade_trades + grind_trades, key=lambda t: t["entry_epoch"])
    combined_stats = trade_stats(all_trades, "COMBINED (fade + grind)")

    # Step 8: Weekly breakdown
    print("\n" + "-" * 80)
    print("STEP 6: WEEKLY BREAKDOWN")
    print("-" * 80)
    from collections import OrderedDict
    weekly = OrderedDict()
    for t in all_trades:
        dt = datetime.fromtimestamp(t["entry_epoch"], tz=timezone.utc)
        iso = dt.isocalendar()
        wk = f"{iso.year}-W{iso.week:02d}"
        if wk not in weekly:
            weekly[wk] = {"trades": 0, "wins": 0, "r": 0.0}
        weekly[wk]["trades"] += 1
        if t["r"] > 0:
            weekly[wk]["wins"] += 1
        weekly[wk]["r"] += t["r"]

    for wk, v in weekly.items():
        wr = 100 * v["wins"] / v["trades"] if v["trades"] > 0 else 0
        print(f"  {wk}: {v['trades']:>3} trades  WR {wr:>5.1f}%  R {v['r']:>+7.2f}")

    # Step 9: Save
    out = {
        "window": {"start": t0, "end": t1, "days": round(actual_days, 1), "bars": len(bars_60d)},
        "spikes": {
            "count": len(spike_indices),
            "per_day": round(len(spike_indices) / max(actual_days, 1), 2),
            "bodies": {
                "median": round(statistics.median([s["body"] for s in spikes if s["is_spike"]]), 2) if spike_indices else 0,
                "mean": round(statistics.mean([s["body"] for s in spikes if s["is_spike"]]), 2) if spike_indices else 0,
            },
        },
        "grinds": {
            "count": len(grinds),
            "eligible": len([g for g in grinds if GRIND_MIN_BARS <= g["duration"] <= GRIND_MAX_BARS]),
        },
        "fade": fade_stats,
        "grind": grind_stats,
        "combined": combined_stats,
        "weekly": dict(weekly),
    }

    out_path = ART / "boom1000_60day_analysis.json"
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")

    # Step 10: Verdict
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    if combined_stats.get("exp_r", 0) > 0.10 and combined_stats.get("pf", 0) > 1.3:
        print("STRONG EDGE: Combined strategy shows positive expectancy with acceptable PF.")
        print("Recommendation: Deploy with conservative sizing (Tier 1).")
    elif combined_stats.get("exp_r", 0) > 0:
        print("MARGINAL EDGE: Positive expectancy but thin. Monitor closely.")
        print("Recommendation: Demo only until edge strengthens.")
    else:
        print("NEGATIVE EDGE: Strategy loses in this 60-day window.")
        print("Recommendation: Do not deploy. Re-examine parameters or wait for favorable regime.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
