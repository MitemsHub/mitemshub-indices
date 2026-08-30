#!/usr/bin/env python3
"""Tick-triggered vs M5-close fade entry timing backtest (Boom 1000).

Quantifies how much entry price the v25.4 tick fast-fade captures earlier
than the M5-close fade path, using the EA's own recorded tick CSV.

Two comparisons:
  A. MATCHED RULE  — identical retrace rule ((peak-price)/jump in [0.40, 0.50]),
     identical exits; the ONLY difference is sampling (every tick vs bar close).
     Isolates the pure timing advantage.
  B. DEPLOYED RULES — M5 path needs a spike BAR (body >= 2.2x body-EMA) and
     divides by bar body; tick path needs jump >= 3 pts and divides by jump.
     Quantifies extra trades the tick path catches that M5 never sees.

Geometry (deployed): SL = 0.4*ATR, TP = 3.2*ATR clamped below the pre-spike
price, min R:R 2.0, exits simulated tick-by-tick (SL -1R, TP +8R, time exit
after 40 min at the prevailing bid).

Usage:
    .venv/Scripts/python.exe scripts/boom_fade_timing_backtest.py
"""
from __future__ import annotations

import bisect
import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5
from synthlib import slice_60d, detect_spikes, compute_atr

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
TICK_DIR = ART / "ticks"

# Deployed EA parameters
TICK_SPIKE_PTS = 3.0      # InpCBTickSpikePts
FADE_R_ENTRY = 0.40       # InpCBFadeR (retrace entry window low)
RETRACE_MAX = 0.50        # fade retrace quality ceiling
SL_MULT = 0.4             # InpCBFadeSL x ATR
TP_MULT = 3.2             # InpCBFadeTP x ATR
M5_SPIKE_THRESHOLD = 2.2  # InpCBSpikeThreshold (v25.3)
POST_SPIKE_BARS = 5       # M5 fade window
TIME_EXIT_BARS = 8        # 8 M5 bars = 40 min
SPIKE_TIMEOUT_S = 600     # InpCBTickFadeTOSec
BAR = 300                 # M5 seconds


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
    """EA-style tick spike events with extension merging."""
    spikes = []
    state = None  # dict(pre, peak, jump, t0)
    prev = ticks[0][1]
    for ts, bid in ticks[1:]:
        jump = bid - prev
        if jump >= TICK_SPIKE_PTS:
            if state and state["peak"] < bid:
                state["peak"] = bid          # extension: new extreme
                state["jump"] = state["peak"] - state["pre"]
                state["t0"] = ts
            elif not state:
                state = {"pre": prev, "peak": bid, "jump": bid - prev, "t0": ts}
        prev = bid
        if state:
            spikes.append(state)
            state = None
    return spikes


def plan_trade(entry, pre, atr):
    """Deployed geometry: SL 0.4xATR, TP 3.2xATR clamped past pre-spike price,
    min R:R 2.0. Returns (sl, tp, r_at_tp) or None when R:R gate fails."""
    sl = entry + SL_MULT * atr
    tp = min(entry - TP_MULT * atr, pre - 0.2 * atr)
    r_at_tp = (entry - tp) / (sl - entry)
    if r_at_tp < 2.0:
        return None
    return sl, tp, r_at_tp


def run_tick_path(ticks, spike, atr):
    """Tick fast-fade: fire when (peak-bid)/jump enters [0.40, 0.50]."""
    t0, peak, jump, pre = spike["t0"], spike["peak"], spike["jump"], spike["pre"]
    start = next(i for i, (ts, _) in enumerate(ticks) if ts >= t0)
    for i in range(start + 1, len(ticks)):
        ts, bid = ticks[i]
        if bid <= pre:                      # full retrace — window gone
            return None, "FULL-RETRACE"
        retrace = (peak - bid) / jump
        if retrace > RETRACE_MAX:
            return None, "OVERSHOT"
        if ts - t0 > SPIKE_TIMEOUT_S:
            return None, "TIMEOUT"
        if FADE_R_ENTRY <= retrace <= RETRACE_MAX:
            plan = plan_trade(bid, pre, atr)
            if plan is None:
                return None, "RR-LOW"
            return {"entry": bid, "t": ts, "age": ts - t0, "retrace": retrace,
                    "sl": plan[0], "tp": plan[1], "r_tp": plan[2]}, "FIRED"
    return None, "END-OF-DATA"


def run_m5_path(ticks, spike, atr, m5_bars):
    """M5-close fade with the SAME retrace rule, sampled only at bar closes."""
    t0, peak, jump, pre = spike["t0"], spike["peak"], spike["jump"], spike["pre"]
    spike_bar = t0 - t0 % BAR
    for k in range(1, POST_SPIKE_BARS + 1):
        bt = spike_bar + k * BAR
        closes = [bid for ts, bid in ticks if spike_bar + (k - 1) * BAR < ts <= bt]
        if not closes:
            continue
        px = closes[-1]                      # bar close price
        retrace = (peak - px) / jump
        if retrace > RETRACE_MAX:
            return None, "OVERSHOT"
        if FADE_R_ENTRY <= retrace <= RETRACE_MAX:
            plan = plan_trade(px, pre, atr)
            if plan is None:
                return None, "RR-LOW"
            return {"entry": px, "t": bt, "age": bt - t0, "retrace": retrace,
                    "sl": plan[0], "tp": plan[1], "r_tp": plan[2]}, "FIRED"
    return None, "NO-WINDOW"


def exit_r(ticks, entry_ts, entry, sl, tp, r_at_tp):
    """Walk ticks forward: SL -> -1R, TP -> actual clamped R, else time exit."""
    start_i = bisect.bisect_right([t[0] for t in ticks], entry_ts)
    end_t = entry_ts + TIME_EXIT_BARS * BAR
    for i in range(start_i, len(ticks)):
        ts, bid = ticks[i]
        if ts > end_t:
            return (entry - bid) / (sl - entry), "TIME"
        if bid >= sl:
            return -1.0, "STOP"
        if bid <= tp:
            return r_at_tp, "TARGET"          # actual R at the clamped TP
    return (entry - ticks[-1][1]) / (sl - entry), "END"


def trade_metrics(trades):
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
    return {
        "trades": len(trades),
        "wr": round(100 * len(wins) / len(trades), 1),
        "pf": round(gw / gl, 2) if gl > 0 else 99.0,
        "exp_r": round(sum(t["r"] for t in trades) / len(trades), 3),
        "total_r": round(sum(t["r"] for t in trades), 2),
        "max_dd": round(dd, 2),
        "exits": {k: sum(1 for t in trades if t["reason"] == k)
                  for k in ("TARGET", "STOP", "TIME")},
    }


def main():
    print("=" * 92)
    print("BOOM 1000 — TICK-TRIGGERED vs M5-CLOSE FADE ENTRY TIMING")
    print(f"Rule: retrace {FADE_R_ENTRY:.0%}-{RETRACE_MAX:.0%} | SL {SL_MULT}xATR | "
          f"TP {TP_MULT}xATR | tick spike >={TICK_SPIKE_PTS}pts | timeout {SPIKE_TIMEOUT_S}s")
    print("=" * 92)

    ticks = load_ticks()
    if len(ticks) < 500:
        print("Need more tick data in artifacts/ticks/")
        return 1
    t0, t1 = ticks[0][0], ticks[-1][0]
    span_days = max((t1 - t0) / 86400.0, 0.2)
    print(f"\nTicks: {len(ticks)}  {datetime.fromtimestamp(t0, tz=timezone.utc):%m-%d %H:%M}"
          f" -> {datetime.fromtimestamp(t1, tz=timezone.utc):%m-%d %H:%M} UTC  ({span_days:.1f}d span)")

    # ATR from the 60-day M5 cache (most recent regime value)
    m5 = slice_60d(load_m5("Boom 1000 Index", "M5"), 60)
    atr_vals = [a for a in compute_atr(m5) if a > 0]
    atr = atr_vals[-1]
    sl_dist = SL_MULT * atr
    print(f"ATR(14, last 60d value) = {atr:.2f} pts  -> SL dist = {sl_dist:.2f} pts")

    # Typical body-EMA scale (for deployed-rule M5 visibility classification)
    spikes60 = detect_spikes(m5, M5_SPIKE_THRESHOLD)
    emas = [s["body_ema"] for s in spikes60 if s["body_ema"] > 0]
    body_ema_typ = statistics.median(emas) if emas else 2.5
    print(f"Typical M5 body-EMA (60d median) = {body_ema_typ:.2f} pts "
          f"-> M5 spike bar needs body >= {M5_SPIKE_THRESHOLD * body_ema_typ:.2f} pts")

    # M5 bars rebuilt from ticks (for bar-close sampling and spike-bar bodies)
    bars = {}
    for ts, bid in ticks:
        k = ts - ts % BAR
        b = bars.setdefault(k, {"open": bid, "high": bid, "low": bid, "close": bid})
        b["high"] = max(b["high"], bid)
        b["low"] = min(b["low"], bid)
        b["close"] = bid
    m5_bars = [bars[k] for k in sorted(bars)]

    tick_spikes = detect_tick_spikes(ticks)
    print(f"\nTick spikes: {len(tick_spikes)} "
          f"(jumps {min(s['jump'] for s in tick_spikes):.1f}-{max(s['jump'] for s in tick_spikes):.1f} pts)")

    rows_a, rows_b_tick, rows_b_m5 = [], [], []
    detail = []
    for sp in tick_spikes:
        tick_tr, tick_status = run_tick_path(ticks, sp, atr)
        m5_tr, m5_status = run_m5_path(ticks, sp, atr, m5_bars)
        spike_bar_body = None
        bt = sp["t0"] - sp["t0"] % BAR
        if bt in bars:
            spike_bar_body = abs(bars[bt]["close"] - bars[bt]["open"])
        m5_visible = spike_bar_body is not None and spike_bar_body >= M5_SPIKE_THRESHOLD * body_ema_typ

        row = {"jump": round(sp["jump"], 2), "m5_visible": m5_visible,
               "tick": tick_status, "m5": m5_status}
        if tick_tr:
            row["tick_entry_age_s"] = tick_tr["age"]
            r, reason = exit_r(ticks, tick_tr["t"], tick_tr["entry"], tick_tr["sl"],
                               tick_tr["tp"], tick_tr["r_tp"])
            row.update(tick_r=round(r, 2), tick_exit=reason)
            rows_b_tick.append({"r": r, "reason": reason})
        if m5_tr:
            row["m5_entry_age_s"] = m5_tr["age"]
            r, reason = exit_r(ticks, m5_tr["t"], m5_tr["entry"], m5_tr["sl"],
                               m5_tr["tp"], m5_tr["r_tp"])
            row.update(m5_r=round(r, 2), m5_exit=reason)
            rows_b_m5.append({"r": r, "reason": reason})
            if tick_tr:   # matched pair — pure timing comparison
                d_pts = m5_tr["entry"] - tick_tr["entry"]          # + = tick entered lower
                d_r = d_pts / sl_dist
                d_s = m5_tr["age"] - tick_tr["age"]
                row.update(d_pts=round(d_pts, 2), d_r=round(d_r, 3), d_s=d_s)
                rows_a.append({"d_r": d_r, "d_pts": d_pts, "d_s": d_s})
        detail.append(row)

    # ---- Report -----------------------------------------------------------
    both = [r for r in detail if r.get("tick") == "FIRED" and r.get("m5") == "FIRED"]
    tick_only = [r for r in detail if r.get("tick") == "FIRED" and r.get("m5") != "FIRED"]
    m5_only = [r for r in detail if r.get("m5") == "FIRED" and r.get("tick") != "FIRED"]

    print("\n--- A. MATCHED RULE (same retrace definition; sampling only) ---")
    print(f"  Spikes with BOTH entries: {len(both)}")
    if rows_a:
        d_rs = [x["d_r"] for x in rows_a]
        d_ptss = [x["d_pts"] for x in rows_a]
        d_ss = [x["d_s"] for x in rows_a]
        print(f"  Entry price edge: median {statistics.median(d_ptss):+.2f} pts "
              f"= {statistics.median(d_rs):+.2f}R  (mean {statistics.mean(d_ptss):+.2f} pts / "
              f"{statistics.mean(d_rs):+.2f}R)")
        print(f"  Entry time edge:  median {statistics.median(d_ss):+d}s earlier "
              f"(mean {statistics.mean(d_ss):+.0f}s)")
        print(f"  Per-spike: tick ages {[r.get('tick_entry_age_s') for r in both]}")
        print(f"             m5  ages {[r.get('m5_entry_age_s') for r in both]}")

    print("\n--- B. DEPLOYED RULES (M5 body-EMA gate vs tick jump gate) ---")
    m5_vis = [r for r in detail if r["m5_visible"]]
    print(f"  M5-visible spike bars: {len(m5_vis)}/{len(detail)}  "
          f"(tick-only events the M5 gate never sees: {len(detail) - len(m5_vis)})")
    tick_ages = [r["tick_entry_age_s"] for r in detail if r.get("tick") == "FIRED"]
    m5_ages = [r["m5_entry_age_s"] for r in detail if r.get("m5") == "FIRED"]
    miss = {}
    for r in detail:
        if r.get("tick") == "FIRED" and r.get("m5") != "FIRED":
            miss[r["m5"]] = miss.get(r["m5"], 0) + 1
    print(f"  Entry age after spike: tick median {statistics.median(tick_ages) if tick_ages else 0:.0f}s "
          f"vs M5-close median {statistics.median(m5_ages) if m5_ages else 0:.0f}s")
    print(f"  M5-close missed events the tick path traded: {json.dumps(miss)}")
    mt = trade_metrics(rows_b_tick)
    mm = trade_metrics(rows_b_m5)
    print(f"  TICK path:  {json.dumps(mt)}")
    print(f"  M5-CLOSE:   {json.dumps(mm)}")
    if mt.get("trades") and mm.get("trades"):
        print(f"  Extra trades/day from tick path: "
              f"{(mt['trades'] - mm['trades']) / span_days:+.1f}  |  "
              f"extra R/day: {(mt['total_r'] - mm['total_r']) / span_days:+.2f}")
    elif mt.get("trades"):
        print(f"  Tick path caught {mt['trades']} trades the M5 path never entered.")

    out = {"atr": round(atr, 2), "sl_dist": round(sl_dist, 2),
           "body_ema_typ": round(body_ema_typ, 2), "spikes": len(detail),
           "matched": rows_a, "tick_metrics": mt, "m5_metrics": mm,
           "detail": detail}
    out_path = ART / "boom_fade_timing_backtest.json"
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")

    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    if rows_a:
        med = statistics.median(d_rs)
        print(f"Matched spikes: tick entry is {statistics.median(d_ss):+d}s earlier and "
              f"{med:+.2f}R on entry price ({statistics.median(d_ptss):+.1f} pts; "
              f"positive = tick price better).  n={len(both)} - small sample.")
        sign = "better" if med > 0 else "WORSE - the M5 close sampled a deeper retrace"
        print(f"Interpretation: on matched events the earlier tick entry priced {med:+.2f}R "
              f"{sign} per trade; the real fast-fade edge is opportunity capture, not price.")
    if mt.get("trades"):
        print(f"Deployed rules: tick path entered {mt['trades']} trades vs {mm.get('trades', 0)} for M5 — "
              f"total R {mt['total_r']} vs {mm.get('total_r', 0)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
