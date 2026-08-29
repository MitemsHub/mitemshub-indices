#!/usr/bin/env python3
"""Boom 1000 FADE-ONLY optimization: sweep TP multipliers and trailing stop configs.

Pulls Boom 1000 M5 bars straight from the MT5 terminal (shared mt5_data
loader, .npy cache + staleness check) and runs parameter sweeps to find:
  1. Optimal FADE_TP multiplier (1.5 to 2.5)
  2. Optimal trailing stop config (start, distance)
  3. Combined best parameters

Usage:
    .venv/Scripts/python.exe scripts/boom1000_fade_optimize.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.mt5_data import load_m5
from scripts.synthlib import slice_60d, get_spike_indices as detect_spikes, compute_atr, trade_stats

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

# Fixed params
SPIKE_THRESHOLD = 2.5
FADE_SL_MULT = 0.4
COOLDOWN_BARS = 1
POST_SPIKE_WINDOW = 5
ATR_PERIOD = 14





def backtest_fade(bars, spike_indices, atr_vals, tp_mult, sl_mult=FADE_SL_MULT,
                  use_trail=False, trail_start_r=0.0, trail_dist_r=0.0,
                  max_hold_bars=8, early_cut_r=None):
    """Fade backtest with configurable TP, trailing, and risk management."""
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

            if current_price < spike_high:
                retrace = (spike_high - current_price) / spike_body if spike_body > 0 else 0

                if 0.30 <= retrace <= 0.70:
                    entry = current_price
                    sl = entry + sl_mult * atr
                    tp = entry - tp_mult * atr
                    if tp > spike_low:
                        tp = spike_low - atr * 0.2

                    risk_dist = sl - entry  # positive for sell
                    result = None
                    reason = "TIME"
                    highest_since_entry = entry  # track best price for trailing

                    for k in range(j + 1, min(j + max_hold_bars + 5, len(bars))):
                        bar = bars[k]

                        # Update trailing stop
                        if use_trail and result is None:
                            if bar["low"] < highest_since_entry:
                                highest_since_entry = bar["low"]
                            profit_r = (entry - highest_since_entry) / risk_dist if risk_dist > 0 else 0
                            if profit_r >= trail_start_r:
                                new_sl = entry - (profit_r - trail_dist_r) * risk_dist
                                if new_sl < sl:
                                    sl = new_sl

                        hit_sl = bar["high"] >= sl
                        hit_tp = bar["low"] <= tp

                        if hit_sl:
                            result = -(sl - entry) / risk_dist if risk_dist > 0 else -1.0
                            reason = "STOP" if sl >= entry + sl_mult * atr * 0.5 else "TRAIL"
                            break
                        if hit_tp:
                            result = tp_mult / sl_mult
                            reason = "TARGET"
                            break

                        # Early cut check
                        if early_cut_r is not None:
                            current_r = (entry - bar["close"]) / risk_dist if risk_dist > 0 else 0
                            if current_r < early_cut_r:
                                result = current_r
                                reason = "EARLY-CUT"
                                break

                    if result is None:
                        exit_idx = min(j + max_hold_bars + 4, len(bars) - 1)
                        result = (entry - bars[exit_idx]["close"]) / risk_dist if risk_dist > 0 else 0

                    trades.append({
                        "entry_idx": j,
                        "entry_epoch": bars[j]["epoch"],
                        "r": result,
                        "reason": reason,
                        "tp_mult": tp_mult,
                    })
                    cooldown = COOLDOWN_BARS
                    break

    return trades


def main():
    print("\n[mt5] Loading Boom 1000 M5 from terminal (shared mt5_data loader)...")
    try:
        bars_full = load_m5("Boom 1000 Index", "M5", 20000)
    except Exception as exc:
        print(f"ERROR: could not load Boom 1000 data: {exc}")
        return 1

    bars = slice_60d(bars_full, 60)
    print(f"Loaded {len(bars)} M5 bars (60-day window)")

    spike_indices = detect_spikes(bars)
    atr_vals = compute_atr(bars)
    print(f"Detected {len(spike_indices)} spikes\n")

    # ================================================================
    # SWEEP 1: FADE_TP multiplier (1.5 to 2.5)
    # ================================================================
    print("=" * 90)
    print("SWEEP 1: FADE_TP MULTIPLIER (SL fixed at 0.4x ATR, no trailing)")
    print("=" * 90)
    print(f"{'TP':>5} | {'Trades':>6} {'PerD':>5} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} | {'Pass':>5}")
    print(f"{'-'*5}-+{'-'*37}-+{'-'*11}-+{'-'*6}")

    tp_results = []
    for tp in [1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0, 2.2, 2.5, 3.0]:
        trades = backtest_fade(bars, spike_indices, atr_vals, tp_mult=tp)
        s = trade_stats(trades, f"TP={tp}")
        tp_results.append(s)
        ex = s.get("exits", {})
        pass_ok = s["trades"] >= 30 and s.get("pf", 0) >= 1.3 and s.get("exp_r", 0) >= 0.15 and s.get("max_dd_r", 99) <= 15
        print(f"{tp:>5} | {s['trades']:>6} {s.get('per_day',0):>5} {s.get('wr',0):>5} {s.get('pf',0):>5} "
              f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
              f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} | "
              f"{'PASS' if pass_ok else 'FAIL':>5}")

    best_tp = max(tp_results, key=lambda x: x.get("exp_r", 0))
    print(f"\n  Best TP: {best_tp['label']} -> ExpR {best_tp.get('exp_r',0):+.3f}, PF {best_tp.get('pf',0)}, "
          f"WR {best_tp.get('wr',0)}%, DD {best_tp.get('max_dd_r',0)}R")

    # ================================================================
    # SWEEP 2: Trailing stop configs (at best TP)
    # ================================================================
    best_tp_val = float(best_tp["label"].split("=")[1])
    print(f"\n{'=' * 90}")
    print(f"SWEEP 2: TRAILING STOP (TP fixed at {best_tp_val}x, SL at 0.4x)")
    print("=" * 90)
    print(f"{'Config':<25} | {'Trades':>6} {'PerD':>5} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} {'Trl':>3}")
    print(f"{'-'*25}-+{'-'*48}")

    trail_results = []
    configs = [
        ("No trail", False, 0, 0),
        ("Start@0.5R Dist@0.3R", True, 0.5, 0.3),
        ("Start@0.6R Dist@0.3R", True, 0.6, 0.3),
        ("Start@0.8R Dist@0.3R", True, 0.8, 0.3),
        ("Start@0.8R Dist@0.5R", True, 0.8, 0.5),
        ("Start@1.0R Dist@0.3R", True, 1.0, 0.3),
        ("Start@1.0R Dist@0.5R", True, 1.0, 0.5),
        ("Start@1.2R Dist@0.5R", True, 1.2, 0.5),
        ("Start@1.5R Dist@0.5R", True, 1.5, 0.5),
    ]

    for name, use_trail, t_start, t_dist in configs:
        trades = backtest_fade(bars, spike_indices, atr_vals, tp_mult=best_tp_val,
                               use_trail=use_trail, trail_start_r=t_start, trail_dist_r=t_dist)
        s = trade_stats(trades, name)
        trail_results.append(s)
        ex = s.get("exits", {})
        trail_count = ex.get("TRAIL", 0)
        print(f"{name:<25} | {s['trades']:>6} {s.get('per_day',0):>5} {s.get('wr',0):>5} {s.get('pf',0):>5} "
              f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
              f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} {trail_count:>3}")

    best_trail = max(trail_results, key=lambda x: x.get("exp_r", 0))
    print(f"\n  Best trail: {best_trail['label']} -> ExpR {best_trail.get('exp_r',0):+.3f}, PF {best_trail.get('pf',0)}")

    # ================================================================
    # SWEEP 3: Early cut + max hold at best TP + best trail
    # ================================================================
    use_trail_best = best_trail["label"] != "No trail"
    trail_parts = best_trail["label"].split()
    t_start_best = 0.8
    t_dist_best = 0.3
    if use_trail_best and len(trail_parts) >= 3:
        for p in trail_parts:
            if p.startswith("Start@"):
                t_start_best = float(p.replace("Start@", "").replace("R", ""))
            if p.startswith("Dist@"):
                t_dist_best = float(p.replace("Dist@", "").replace("R", ""))

    print(f"\n{'=' * 90}")
    print(f"SWEEP 3: EARLY CUT + MAX HOLD (TP={best_tp_val}, trail={'ON' if use_trail_best else 'OFF'})")
    print("=" * 90)
    print(f"{'MaxHold':>8} {'EarlyCut':>9} | {'Trades':>6} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} {'EC':>3}")
    print(f"{'-'*8}-{'-'*9}-+{'-'*48}")

    hold_results = []
    for max_hold in [5, 6, 8, 10, 12, 15]:
        for early_cut in [None, -0.30, -0.35, -0.40, -0.50]:
            trades = backtest_fade(bars, spike_indices, atr_vals, tp_mult=best_tp_val,
                                   use_trail=use_trail_best, trail_start_r=t_start_best,
                                   trail_dist_r=t_dist_best, max_hold_bars=max_hold,
                                   early_cut_r=early_cut)
            s = trade_stats(trades, f"H{max_hold}/EC{early_cut}")
            hold_results.append(s)
            ex = s.get("exits", {})
            ec_str = f"{early_cut}" if early_cut is not None else "None"
            print(f"{max_hold:>8} {ec_str:>9} | {s['trades']:>6} {s.get('wr',0):>5} {s.get('pf',0):>5} "
                  f"{s.get('exp_r',0):>+7.3f} {s.get('max_dd_r',0):>6} | "
                  f"{ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} {ex.get('TIME',0):>3} {ex.get('EARLY-CUT',0):>3}")

    best_hold = max(hold_results, key=lambda x: x.get("exp_r", 0))
    print(f"\n  Best hold config: {best_hold['label']} -> ExpR {best_hold.get('exp_r',0):+.3f}")

    # ================================================================
    # FINAL RECOMMENDATION
    # ================================================================
    # Find overall best by combining exp_r and max_dd
    all_candidates = []
    for max_hold in [5, 6, 8, 10, 12]:
        for early_cut in [None, -0.30, -0.35, -0.40]:
            for tp in [best_tp_val, best_tp_val - 0.2, best_tp_val + 0.2]:
                for t_s, t_d in [(t_start_best, t_dist_best), (0, 0)]:
                    use_t = t_s > 0
                    trades = backtest_fade(bars, spike_indices, atr_vals, tp_mult=tp,
                                           use_trail=use_t, trail_start_r=t_s, trail_dist_r=t_d,
                                           max_hold_bars=max_hold, early_cut_r=early_cut)
                    s = trade_stats(trades)
                    if s["trades"] >= 20:
                        # Score: exp_r weighted by sqrt(trades) - penalty for DD
                        score = s.get("exp_r", 0) * math.sqrt(s["trades"]) - s.get("max_dd_r", 0) * 0.05
                        all_candidates.append({
                            "tp": tp, "trail": use_t, "t_start": t_s, "t_dist": t_d,
                            "max_hold": max_hold, "early_cut": early_cut,
                            "stats": s, "score": score,
                        })

    all_candidates.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'=' * 90}")
    print("TOP 5 RECOMMENDED CONFIGURATIONS")
    print("=" * 90)
    for i, c in enumerate(all_candidates[:5]):
        s = c["stats"]
        trail_str = f"trail@{c['t_start']}R/{c['t_dist']}R" if c["trail"] else "no-trail"
        ec_str = f"EC={c['early_cut']}" if c["early_cut"] is not None else "no-EC"
        print(f"  #{i+1}: TP={c['tp']:.1f} {trail_str} hold={c['max_hold']} {ec_str}")
        print(f"      {s['trades']} trades  WR {s['wr']}%  PF {s['pf']}  ExpR {s['exp_r']:+.3f}  DD {s['max_dd_r']}R  "
              f"score={c['score']:.2f}")

    winner = all_candidates[0]
    ws = winner["stats"]
    print(f"\n{'=' * 90}")
    print("WINNER RECOMMENDATION")
    print("=" * 90)
    print(f"  FADE_TP = {winner['tp']:.1f}")
    print(f"  FADE_SL = {FADE_SL_MULT} (unchanged)")
    print(f"  Trailing: {'ON' if winner['trail'] else 'OFF'}" +
          (f"  Start@{winner['t_start']}R  Dist@{winner['t_dist']}R" if winner["trail"] else ""))
    print(f"  Max Hold: {winner['max_hold']} bars")
    print(f"  Early Cut: {winner['early_cut']}" if winner["early_cut"] is not None else "  Early Cut: None")
    print(f"  -> {ws['trades']} trades, WR {ws['wr']}%, PF {ws['pf']}, ExpR {ws['exp_r']:+.3f}, DD {ws['max_dd_r']}R")

    # Save
    out = {
        "tp_sweep": tp_results,
        "trail_sweep": trail_results,
        "hold_sweep": [{"label": h["label"], **{k: v for k, v in h.items() if k != "label"}} for h in hold_results[:20]],
        "winner": {
            "tp": winner["tp"],
            "sl": FADE_SL_MULT,
            "trail_enabled": winner["trail"],
            "trail_start_r": winner["t_start"] if winner["trail"] else 0,
            "trail_dist_r": winner["t_dist"] if winner["trail"] else 0,
            "max_hold_bars": winner["max_hold"],
            "early_cut_r": winner["early_cut"],
            "stats": ws,
        },
    }
    out_path = ART / "boom1000_fade_optimize.json"
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
