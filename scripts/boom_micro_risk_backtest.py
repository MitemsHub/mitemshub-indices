#!/usr/bin/env python3
"""Micro-fade risk-scaling backtest on 60-day Boom 1000 M5 data.

Runs the deployed fade (threshold 2.2, retrace window 0.30-0.60, SL 0.4xATR,
TP 3.2xATR, cooldown 1) and builds equity curves under different per-trade
risk weights, keyed by the spike's body ratio (spike body / rolling body EMA):

  uniform   : every trade risks 1.0              (current deployed baseline)
  step 2.5  : 0.5x below 2.5x, 1.0x at/above     (user's requested variant)
  linear    : 0.5x at 2.2x -> 1.0x at 3.0x       (what the EA implements)
  step 3.0  : 0.75x below 3.0x, 1.0x at/above
  floor only: 0.5x below 2.2x (never triggers)   (sanity check)

Reports total R, max drawdown (R), R/DD efficiency, and the equity curve at
weekly resolution.  Trade SET is identical across schemes - only weighting
changes - so differences isolate the effect of the micro-fade tier.

Usage:
    .venv/Scripts/python.exe scripts/boom_micro_risk_backtest.py
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5
from synthlib import slice_60d, detect_spikes, compute_atr

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

THR = 2.2            # InpCBSpikeThreshold (v25.3)
RE_LO, RE_HI = 0.30, 0.60   # v25.6 tuned window
SL_MULT, TP_MULT = 0.4, 3.2
COOLDOWN = 1
WINDOW = 5
EXIT_BARS = 8

SCHEMES = {
    "uniform (deployed)":       lambda ratio: 1.0,
    "step 0.5x <2.5 (requested)": lambda ratio: 0.5 if ratio < 2.5 else 1.0,
    "linear 0.5x@2.2 (EA v25.3)": lambda ratio: 0.5 + 0.5 * min(max((ratio - 2.2) / 0.8, 0), 1),
    "step 0.75x <3.0":          lambda ratio: 0.75 if ratio < 3.0 else 1.0,
    "linear 0.5x@2.5->1.0@3.5": lambda ratio: 0.5 + 0.5 * min(max((ratio - 2.5) / 1.0, 0), 1),
}


def fade_trades(bars, spikes, atr):
    """Deployed fade sim; each trade carries its spike body ratio."""
    trades = []
    spike_by_idx = {s["idx"]: s for s in spikes if s["is_spike"]}
    cooldown = 0
    for sidx in sorted(spike_by_idx):
        sp = bars[sidx]
        body = abs(sp["close"] - sp["open"])
        high, low = sp["high"], sp["low"]
        if body <= 0:
            continue
        spk = spike_by_idx[sidx]
        ratio = spk["body_ratio"] or (body / max(spk["body_ema"], 1e-9))
        for j in range(sidx + 1, min(sidx + WINDOW + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue
            if j >= len(atr) or atr[j] <= 0:
                continue
            px = bars[j]["close"]
            if px >= high:
                continue
            retrace = (high - px) / body
            if retrace < RE_LO:
                continue
            if retrace > RE_HI:
                break
            entry = px
            sl = entry + SL_MULT * atr[j]
            tp = entry - TP_MULT * atr[j]
            if tp > low:
                tp = low - atr[j] * 0.2
            if (entry - tp) / max(sl - entry, 1e-9) < 2.0:
                continue
            result, reason = None, "TIME"
            for k in range(j + 1, min(j + 1 + EXIT_BARS, len(bars))):
                if bars[k]["high"] >= sl:
                    result, reason = -1.0, "STOP"
                    break
                if bars[k]["low"] <= tp:
                    result = (entry - tp) / (sl - entry)
                    reason = "TARGET"
                    break
            if result is None:
                k = min(j + EXIT_BARS, len(bars) - 1)
                result = (entry - bars[k]["close"]) / (sl - entry)
            trades.append({"r": result, "reason": reason, "ratio": ratio,
                           "epoch": bars[j]["epoch"], "spike_body": body})
            cooldown = COOLDOWN
            break
    return trades


def equity_stats(trades, weight_fn, label):
    eq, peak, max_dd = 0.0, 0.0, 0.0
    curve = [0.0]
    for t in trades:
        eq += weight_fn(t["ratio"]) * t["r"]
        curve.append(eq)
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    total = eq
    # worst 7-day R stretch (rolling min of weekly sums)
    daily = {}
    for t in trades:
        day = datetime.fromtimestamp(t["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
        daily[day] = daily.get(day, 0.0) + weight_fn(t["ratio"]) * t["r"]
    days = sorted(daily)
    worst7 = 0.0
    for i in range(len(days)):
        w = sum(daily[d] for d in days[i:i + 7])
        worst7 = min(worst7, w)
    micro = [t for t in trades if t["ratio"] < 2.5]
    micro_r = sum(weight_fn(t["ratio"]) * t["r"] for t in micro)
    micro_r_full = sum(t["r"] for t in micro)
    print(f"  {label:<30} total {total:>8.1f}R  maxDD {max_dd:>6.1f}R  "
          f"R/DD {total / max_dd if max_dd else 99:>5.2f}  worst7d {worst7:>7.1f}R  "
          f"micro-trades {len(micro):>3} ({micro_r_full:+.1f}R full-weight -> {micro_r:+.1f}R scaled)")
    return {"label": label, "total_r": round(total, 1), "max_dd": round(max_dd, 1),
            "r_per_dd": round(total / max_dd, 2) if max_dd else 99.0,
            "worst_7d": round(worst7, 1), "micro_trades": len(micro),
            "micro_r_scaled": round(micro_r, 1), "micro_r_full": round(micro_r_full, 1),
            "curve_sample": [round(curve[i], 1) for i in range(0, len(curve), max(1, len(curve) // 24))]}


def main():
    print("=" * 100)
    print("BOOM 1000 — MICRO-FADE RISK SCALING BACKTEST (60d, thr 2.2, window 0.30-0.60)")
    print("=" * 100)

    m5 = slice_60d(load_m5("Boom 1000 Index", "M5"), 60)
    days = (m5[-1]["epoch"] - m5[0]["epoch"]) / 86400.0
    spikes = detect_spikes(m5, THR)
    atr = compute_atr(m5)
    trades = fade_trades(m5, spikes, atr)
    n = len(trades)
    if not trades:
        print("No trades produced — check data/threshold.")
        return 1

    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    print(f"\nTrade set: {n} trades ({n / days:.1f}/day)  WR {100 * len(wins) / n:.1f}%  "
          f"PF {gw / gl:.2f}  ExpR {sum(t['r'] for t in trades) / n:+.3f}")
    ratios = sorted(t["ratio"] for t in trades)
    print(f"Spike body-ratio of taken trades: p10 {ratios[len(ratios) // 10]:.2f}  "
          f"median {statistics.median(ratios):.2f}  p90 {ratios[9 * len(ratios) // 10]:.2f}")
    n_micro = sum(1 for r in ratios if r < 2.5)
    n_norm = n - n_micro
    print(f"Micro band (<2.5x): {n_micro} trades ({100 * n_micro / n:.0f}%)  |  "
          f"normal band: {n_norm} trades")

    print("\nEquity curves by risk scheme (1R = InpCBBaseRisk 0.30% of equity):")
    results = []
    for label, fn in SCHEMES.items():
        results.append(equity_stats(trades, fn, label))

    base = results[0]
    print("\nDelta vs uniform (deployed baseline):")
    for r in results[1:]:
        print(f"  {r['label']:<30} total {r['total_r'] - base['total_r']:+7.1f}R  "
              f"maxDD {r['max_dd'] - base['max_dd']:+6.1f}R  "
              f"R/DD {r['r_per_dd'] - base['r_per_dd']:+.2f}")

    (ART / "boom_micro_risk_backtest.json").write_text(
        json.dumps({"trade_set": {"trades": n, "per_day": round(n / days, 2)},
                    "schemes": results}, indent=1), encoding="utf-8")
    print("\n[wrote] artifacts/boom_micro_risk_backtest.json")

    print("\n" + "=" * 100)
    best = max(results, key=lambda r: r["r_per_dd"])
    print("VERDICT")
    print("=" * 100)
    for r in results:
        mark = "  <-- best R/DD" if r is best else ""
        print(f"  {r['label']:<30} {r['total_r']:>7.1f}R  DD {r['max_dd']:>5.1f}R  "
              f"R/DD {r['r_per_dd']:.2f}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
