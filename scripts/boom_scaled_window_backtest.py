#!/usr/bin/env python3
"""Scaled retrace-window backtest: does scaling the fade entry threshold by
spike size raise the tick-path trade count without hurting expectancy?

Baseline (deployed v25.6): fixed window [0.30, 0.60], timeout 900s.
Candidates scale the LOWER bound by jump size (Boom fade SELL after UP spike):

  pts-anchor : lo = clamp(4.5/jump, 0.15, 0.45)   (~4.5 pts pullback for any spike)
  sqrt       : lo = clamp(0.30*sqrt(12/jump), 0.18, 0.40)
  linear     : lo = clamp(0.30*(12/jump), 0.12, 0.40)

Runs two evaluations:
  A. TICK path on the recorded live ticks (13 spikes, Aug 29) — the target.
  B. M5 path on the 60-day cache with the same scaling applied to spike BODY
     (statistical backing; the M5 fade sees body, the tick fade sees jump —
     same normalization idea).

Usage:
    .venv/Scripts/python.exe scripts/boom_scaled_window_backtest.py
"""
from __future__ import annotations

import bisect
import csv
import json
import math
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5
from synthlib import slice_60d, detect_spikes, compute_atr

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
TICK_DIR = ART / "ticks"

BAR = 300
SPIKE_PTS = 3.0
SL_MULT, TP_MULT = 0.4, 3.2
MIN_RR = 2.0
TIMEOUT_S = 900
EXIT_MIN = 40 * 60
WINDOW_BARS = 5
REF_JUMP = 12.0      # reference spike size (pts) for scaling


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def make_lo_fn(kind, hi):
    if kind == "fixed":
        return lambda size: 0.30
    if kind == "pts-anchor":
        return lambda size: clamp(4.5 / size, 0.15, 0.45)
    if kind == "sqrt":
        return lambda size: clamp(0.30 * math.sqrt(REF_JUMP / size), 0.18, 0.40)
    if kind == "linear":
        return lambda size: clamp(0.30 * (REF_JUMP / size), 0.12, 0.40)
    raise ValueError(kind)


# ---------------------------------------------------------------------------
def load_ticks():
    rows = []
    for f in sorted(TICK_DIR.glob("MITEMSHUB_ticks_Boom_1000_Index_*.csv")):
        with open(f, newline="") as fh:
            for rec in csv.DictReader(fh):
                try:
                    rows.append((int(rec["ts"]), float(rec["bid"])))
                except (ValueError, KeyError):
                    continue
    rows.sort(key=lambda r: r[0])
    return rows


def detect_tick_spikes(ticks):
    spikes, state, prev = [], None, ticks[0][1]
    for ts, bid in ticks[1:]:
        jump = bid - prev
        if jump >= SPIKE_PTS:
            if state and bid > state["peak"]:
                state["peak"], state["jump"], state["t0"] = bid, bid - state["pre"], ts
            elif not state:
                state = {"pre": prev, "peak": bid, "jump": bid - prev, "t0": ts}
        prev = bid
        if state:
            spikes.append(state)
            state = None
    return spikes


def plan_trade(entry, pre, atr):
    sl = entry + SL_MULT * atr
    tp = min(entry - TP_MULT * atr, pre - 0.2 * atr)
    r_tp = (entry - tp) / (sl - entry)
    if r_tp < MIN_RR:
        return None
    return sl, tp, r_tp


def tick_sim(ticks_ts, ticks_bid, spikes, atr, lo_fn, hi=0.60):
    trades = []
    for sp in spikes:
        i0 = bisect.bisect_right(ticks_ts, sp["t0"])
        lo = lo_fn(sp["jump"])
        for i in range(i0 + 1, len(ticks_ts)):
            ts, bid = ticks_ts[i], ticks_bid[i]
            if bid <= sp["pre"]:
                break
            r = (sp["peak"] - bid) / sp["jump"]
            if r > hi:
                break
            if ts - sp["t0"] > TIMEOUT_S:
                break
            if lo <= r <= hi:
                plan = plan_trade(bid, sp["pre"], atr)
                if plan:
                    # exits on ticks
                    j = bisect.bisect_right(ticks_ts, ts)
                    end = ts + EXIT_MIN
                    res, reason = None, "TIME"
                    for k in range(j, len(ticks_ts)):
                        t2, b2 = ticks_ts[k], ticks_bid[k]
                        if t2 > end:
                            res = (bid - b2) / (plan[0] - bid)
                            break
                        if b2 >= plan[0]:
                            res, reason = -1.0, "STOP"
                            break
                        if b2 <= plan[1]:
                            res, reason = plan[2], "TARGET"
                            break
                    if res is None:
                        res = (bid - ticks_bid[-1]) / (plan[0] - bid)
                    trades.append({"r": res, "reason": reason, "jump": sp["jump"]})
                break
    return trades


def m5_sim(bars, spikes, atr, lo_fn, hi=0.60):
    """M5 fade with body-scaled lo."""
    trades = []
    spike_by_idx = {s["idx"]: s for s in spikes if s["is_spike"]}
    cooldown = 0
    for sidx in sorted(spike_by_idx):
        sp = bars[sidx]
        spk = spike_by_idx[sidx]
        body = abs(sp["close"] - sp["open"])
        high, low = sp["high"], sp["low"]
        if body <= 0:
            continue
        lo = lo_fn(body)
        for j in range(sidx + 1, min(sidx + WINDOW_BARS + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue
            if j >= len(atr) or atr[j] <= 0:
                continue
            px = bars[j]["close"]
            if px >= high:
                continue
            retrace = (high - px) / body
            if retrace < lo:
                continue
            if retrace > hi:
                break
            entry = px
            sl = entry + SL_MULT * atr[j]
            tp = entry - TP_MULT * atr[j]
            if tp > low:
                tp = low - atr[j] * 0.2
            if (entry - tp) / max(sl - entry, 1e-9) < MIN_RR:
                continue
            result, reason = None, "TIME"
            for k in range(j + 1, min(j + 1 + 8, len(bars))):
                if bars[k]["high"] >= sl:
                    result, reason = -1.0, "STOP"
                    break
                if bars[k]["low"] <= tp:
                    result = (entry - tp) / (sl - entry)
                    reason = "TARGET"
                    break
            if result is None:
                k = min(j + 8, len(bars) - 1)
                result = (entry - bars[k]["close"]) / (sl - entry)
            trades.append({"r": result, "reason": reason, "body": body})
            cooldown = 1
            break
    return trades


def metrics(trades):
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
    return {"trades": len(trades),
            "wr": round(100 * len(wins) / len(trades), 1),
            "pf": round(gw / gl, 2) if gl > 0 else 99.0,
            "exp_r": round(sum(t["r"] for t in trades) / len(trades), 3),
            "total_r": round(sum(t["r"] for t in trades), 1),
            "max_dd": round(dd, 1)}


def main():
    print("=" * 96)
    print("BOOM 1000 — SCALED RETRACE-WINDOW BACKTEST (tick path focus)")
    print("=" * 96)

    ticks = load_ticks()
    ticks_ts = [t[0] for t in ticks]
    ticks_bid = [t[1] for t in ticks]
    m5 = slice_60d(load_m5("Boom 1000 Index", "M5"), 60)
    atr = [a for a in compute_atr(m5) if a > 0][-1]
    spikes = detect_tick_spikes(ticks)
    span_h = (ticks_ts[-1] - ticks_ts[0]) / 3600.0
    print(f"Ticks {len(ticks)} ({span_h:.1f}h) | spikes {len(spikes)} | ATR {atr:.2f} "
          f"| SL dist {SL_MULT*atr:.2f} | baseline [0.30-0.60] to={TIMEOUT_S}s")

    print("\n--- A. TICK PATH (live spikes) ---")
    res_a = {}
    for kind in ("fixed", "pts-anchor", "sqrt", "linear"):
        lo_fn = make_lo_fn(kind, 0.60)
        tr = tick_sim(ticks_ts, ticks_bid, spikes, atr, lo_fn)
        m = metrics(tr)
        m["lo_desc"] = ("0.30 fixed" if kind == "fixed" else
                        "4.5/jump clamped [.15,.45]" if kind == "pts-anchor" else
                        "0.30*sqrt(12/jump) clamped [.18,.40]" if kind == "sqrt" else
                        "0.30*(12/jump) clamped [.12,.40]")
        res_a[kind] = m
        print(f"  {kind:<11} ({m['lo_desc']:<32}) trades={m.get('trades',0)}  "
              f"WR={m.get('wr',0):>5}%  PF={m.get('pf',0):>6}  ExpR={m.get('exp_r',0):>+.3f}  "
              f"totalR={m.get('total_r',0):>6}")

    print("\n--- B. M5 PATH, body-scaled analog (60d, statistical backing) ---")
    spikes60 = detect_spikes(m5, 2.2)
    idx = [s["idx"] for s in spikes60 if s["is_spike"]]
    atr60 = compute_atr(m5)
    days = (m5[-1]["epoch"] - m5[0]["epoch"]) / 86400.0
    res_b = {}
    for kind in ("fixed", "pts-anchor", "sqrt", "linear"):
        lo_fn = make_lo_fn(kind, 0.60)
        tr = m5_sim(m5, spikes60, atr60, lo_fn)
        m = metrics(tr)
        res_b[kind] = m
        print(f"  {kind:<11} trades={m.get('trades',0):>4} ({m.get('trades',0)/days:>5.1f}/d)  "
              f"WR={m.get('wr',0):>5}%  PF={m.get('pf',0):>6}  ExpR={m.get('exp_r',0):>+.3f}  "
              f"totalR={m.get('total_r',0):>7}  DD={m.get('max_dd',0)}")

    out = {"tick": res_a, "m5_60d": res_b,
           "atr": round(atr, 2)}
    (ART / "boom_scaled_window_backtest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\n[wrote] artifacts/boom_scaled_window_backtest.json")

    print("\n" + "=" * 96)
    print("VERDICT")
    print("=" * 96)
    base_a, base_b = res_a["fixed"], res_b["fixed"]
    for kind in ("pts-anchor", "sqrt", "linear"):
        da, db = res_a[kind], res_b[kind]
        print(f"  {kind:<11} tick: {da.get('trades',0)-base_a.get('trades',0):+d} trades, "
              f"ExpR {da.get('exp_r',0):+.2f} (base {base_a.get('exp_r',0):+.2f}) | "
              f"60d: {db.get('trades',0)-base_b.get('trades',0):+d} trades, "
              f"ExpR {db.get('exp_r',0):+.3f} vs {base_b.get('exp_r',0):+.3f}, "
              f"totalR {db.get('total_r',0)-base_b.get('total_r',0):+.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
