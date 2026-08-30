#!/usr/bin/env python3
"""Crash 1000 — validate the Boom v25.6/v25.7 tune mirrored onto Crash.

The v25.7 strategy code is shared by both index paths, so the tune
(size-scaled retrace entry, 0.60 ceiling) already applies to Crash.  This
script validates it on Crash 1000's 60-day M5 cache with the Crash geometry
(TP 3.5xATR per the deployed CRASH1000_CB preset, fade = BUY after DOWN spike).

Configs compared:
  OLD baseline : thr 2.5, fixed window [0.30-0.50]   (pre-v25.6 deployment)
  thr 2.2 only : thr 2.2, fixed window [0.30-0.50]
  FULL v25.7   : thr 2.2, scaled lo, ceiling 0.60    (deployed code today)

Usage:
    .venv/Scripts/python.exe scripts/crash_tune_validate.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5
from synthlib import slice_60d, detect_spikes, compute_atr

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

SL_MULT = 0.4
TP_MULT = 3.5          # Crash deployed TP (InpCBFadeTP in CRASH1000_CB.set)
COOLDOWN = 1
WINDOW = 5
EXIT_BARS = 8


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def crash_fade(bars, spikes, atr, thr_used, lo_fn, hi):
    """Crash fade: spikes go DOWN -> fade by BUYING. Mirrors the EA branch."""
    trades = []
    spike_by_idx = {s["idx"]: s for s in spikes if s["is_spike"]}
    cooldown = 0
    for sidx in sorted(spike_by_idx):
        sp = bars[sidx]
        spk = spike_by_idx[sidx]
        body = abs(sp["close"] - sp["open"])
        signed = sp["close"] - sp["open"]
        low, high = sp["low"], sp["high"]
        if body <= 0 or signed >= 0:      # direction filter: crash spikes fall
            continue
        for j in range(sidx + 1, min(sidx + WINDOW + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue
            if j >= len(atr) or atr[j] <= 0:
                continue
            px = bars[j]["close"]
            if px <= low:
                continue
            retrace = (px - low) / body
            lo = lo_fn(body)
            if retrace < lo:
                continue
            if retrace > hi:
                break
            entry = px
            sl = entry - SL_MULT * atr[j]
            tp = entry + TP_MULT * atr[j]
            if tp < high:
                tp = high + atr[j] * 0.2
            if (tp - entry) / max(entry - sl, 1e-9) < 2.0:
                continue
            result, reason = None, "TIME"
            for k in range(j + 1, min(j + 1 + EXIT_BARS, len(bars))):
                if bars[k]["low"] <= sl:
                    result, reason = -1.0, "STOP"
                    break
                if bars[k]["high"] >= tp:
                    result = (tp - entry) / (entry - sl)
                    reason = "TARGET"
                    break
            if result is None:
                k = min(j + EXIT_BARS, len(bars) - 1)
                result = (bars[k]["close"] - entry) / (entry - sl)
            trades.append({"r": result, "reason": reason, "ratio": spk["body_ratio"],
                           "epoch": bars[j]["epoch"]})
            cooldown = COOLDOWN
            break
    return trades


def metrics(trades, days):
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(trades), "per_day": round(len(trades) / days, 1),
            "wr": round(100 * len(wins) / len(trades), 1),
            "pf": round(gw / gl, 2) if gl > 0 else 99.0,
            "exp_r": round(sum(t["r"] for t in trades) / len(trades), 3),
            "total_r": round(sum(t["r"] for t in trades), 1),
            "max_dd": round(dd, 1),
            "exits": {k: sum(1 for t in trades if t["reason"] == k)
                      for k in ("TARGET", "STOP", "TIME")}}


def main():
    print("=" * 96)
    print("CRASH 1000 — VALIDATE THE MIRRORED TUNE (60-day M5 cache)")
    print("=" * 96)

    m5 = slice_60d(load_m5("Crash 1000 Index", "M5"), 60)
    days = (m5[-1]["epoch"] - m5[0]["epoch"]) / 86400.0
    atr = compute_atr(m5)
    print(f"Window: {len(m5)} bars, {days:.0f}d | ATR(last)={max(atr):.2f}")

    configs = [
        ("OLD baseline  thr 2.5 fixed[0.30-0.50]", 2.5, lambda b: 0.30, 0.50),
        ("thr 2.2 only  fixed[0.30-0.50]",         2.2, lambda b: 0.30, 0.50),
        ("FULL v25.7    thr 2.2 scaled[?]-0.60",   2.2,
         lambda b: clamp(0.30 * math.sqrt(12.0 / max(b, 1.0)), 0.18, 0.40), 0.60),
    ]

    rows = []
    for label, thr, lo_fn, hi in configs:
        spikes = detect_spikes(m5, thr)
        tr = crash_fade(m5, spikes, atr, thr, lo_fn, hi)
        m = metrics(tr, days)
        m["config"] = label
        rows.append(m)
        ex = " ".join(f"{k}={v}" for k, v in m.get("exits", {}).items())
        print(f"\n  {label}")
        print(f"    spikes/d={m.get('spikes_per_day','')}  trades={m.get('trades',0)} "
              f"({m.get('per_day',0)}/d)  WR={m.get('wr',0)}%  PF={m.get('pf',0)}  "
              f"ExpR={m.get('exp_r',0):+.3f}  totalR={m.get('total_r',0)}  "
              f"maxDD={m.get('max_dd',0)}R  [{ex}]")

    base, full = rows[0], rows[2]
    print("\nDelta (FULL v25.7 vs OLD baseline):")
    print(f"  trades {full.get('trades',0) - base.get('trades',0):+d}  "
          f"totalR {full.get('total_r',0) - base.get('total_r',0):+.1f}  "
          f"ExpR {full.get('exp_r',0) - base.get('exp_r',0):+.3f}  "
          f"PF {full.get('pf',0)} vs {base.get('pf',0)}  "
          f"maxDD {full.get('max_dd',0)} vs {base.get('max_dd',0)}")

    (ART / "crash_tune_validate.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n[wrote] artifacts/crash_tune_validate.json")

    print("\n" + "=" * 96)
    print("VERDICT")
    print("=" * 96)
    ok = (full.get("exp_r", 0) >= base.get("exp_r", 0) * 0.95
          and full.get("pf", 0) >= 3.0 and full.get("total_r", 0) > base.get("total_r", 0))
    print(f"Mirrored tune on Crash: {'SAFE — adopt' if ok else 'REVIEW — expectancy/PF regression'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
