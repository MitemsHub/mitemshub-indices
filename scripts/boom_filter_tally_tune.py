#!/usr/bin/env python3
"""Which filter blocks the most fade entries? Evidence-based tally + tuning sweep.

Part 1 — FILTER TALLY on live tick spikes (Aug 29 recording):
    Simulates the deployed M5 fade path filter-by-filter for every tick-level
    spike and counts which gate kills each opportunity (detection, direction,
    cooldown, retrace-low, retrace-high/overshoot, timeout).
Part 2 — RETRACE-WINDOW SWEEP on the 60-day M5 cache (threshold 2.2):
    Scores candidate entry windows (lo, hi) with the deployed geometry and
    ranks them by PF / expectancy / trade count.
Part 3 — TICK-PATH TIMEOUT/THRESHOLD SWEEP on the tick data:
    Finds the timeout and retrace-lo that capture the most of the big-spike
    TIMEOUT losses observed in boom_fade_timing_backtest.

Usage:
    .venv/Scripts/python.exe scripts/boom_filter_tally_tune.py
"""
from __future__ import annotations

import bisect
import csv
import json
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
TICK_SPIKE_PTS = 3.0
SL_MULT, TP_MULT = 0.4, 3.2
DEPLOYED_LO, DEPLOYED_HI = 0.30, 0.50   # actual deployed (.set: InpCBFadeR=0.3, max=0.50)
M5_THRESH = 2.2
WINDOW_BARS = 5
TIME_EXIT_BARS = 8
SWEEP_WINDOWS = [(0.25, 0.50), (0.30, 0.50), (0.30, 0.60), (0.35, 0.55),
                 (0.40, 0.50), (0.40, 0.60), (0.30, 0.70), (0.25, 0.60)]
TIMEOUTS = [600, 900, 1200, 1800]
TICK_LOS = [0.20, 0.25, 0.30, 0.40]


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
        if jump >= TICK_SPIKE_PTS:
            if state and state["peak"] < bid:
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
    r_at_tp = (entry - tp) / (sl - entry)
    if r_at_tp < 2.0:
        return None
    return sl, tp, r_at_tp


def exit_r(ticks_ts, ticks_bid, entry_ts, entry, sl, tp, r_tp, horizon_s):
    i = bisect.bisect_right(ticks_ts, entry_ts)
    end_t = entry_ts + horizon_s
    while i < len(ticks_ts):
        ts, bid = ticks_ts[i], ticks_bid[i]
        if ts > end_t:
            return (entry - bid) / (sl - entry), "TIME"
        if bid >= sl:
            return -1.0, "STOP"
        if bid <= tp:
            return r_tp, "TARGET"
        i += 1
    return (entry - ticks_bid[-1]) / (sl - entry), "END"


def fade_sim(bars, spike_idx, atr, lo, hi, window=WINDOW_BARS):
    """Deployed M5 fade sim with configurable retrace window."""
    trades = []
    cooldown = 0
    for sidx in spike_idx:
        sp = bars[sidx]
        body = abs(sp["close"] - sp["open"])
        high, low = sp["high"], sp["low"]
        if body <= 0:
            continue
        for j in range(sidx + 1, min(sidx + window + 1, len(bars))):
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
                break                      # overshot for this spike
            entry = px
            sl = entry + SL_MULT * atr[j]
            tp = entry - TP_MULT * atr[j]
            if tp > low:
                tp = low - atr[j] * 0.2
            if (entry - tp) / max(sl - entry, 1e-9) < 2.0:
                continue
            result, reason = None, "TIME"
            for k in range(j + 1, min(j + 1 + TIME_EXIT_BARS, len(bars))):
                if bars[k]["high"] >= sl:
                    result, reason = -1.0, "STOP"
                    break
                if bars[k]["low"] <= tp:
                    result = (entry - tp) / (sl - entry)
                    reason = "TARGET"
                    break
            if result is None:
                k = min(j + TIME_EXIT_BARS, len(bars) - 1)
                result = (entry - bars[k]["close"]) / (sl - entry)
            trades.append({"r": result, "reason": reason})
            cooldown = 1
            break
    return trades


def metrics(trades):
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    return {"trades": len(trades),
            "wr": round(100 * len(wins) / len(trades), 1),
            "pf": round(gw / gl, 2) if gl > 0 else 99.0,
            "exp_r": round(sum(t["r"] for t in trades) / len(trades), 3),
            "total_r": round(sum(t["r"] for t in trades), 1)}


def main():
    print("=" * 92)
    print("BOOM 1000 — FILTER TALLY (live spikes) + RETRACE-WINDOW / TIMEOUT SWEEPS")
    print("=" * 92)

    ticks = load_ticks()
    ticks_ts = [t[0] for t in ticks]
    ticks_bid = [t[1] for t in ticks]

    m5 = slice_60d(load_m5("Boom 1000 Index", "M5"), 60)
    atr60 = [a for a in compute_atr(m5) if a > 0]
    atr = atr60[-1]
    spikes60 = detect_spikes(m5, M5_THRESH)
    emas = [s["body_ema"] for s in spikes60 if s["body_ema"] > 0]
    body_ema_typ = statistics.median(emas) if emas else 2.5
    print(f"ATR={atr:.2f} | SL dist={SL_MULT*atr:.2f} | body-EMA~{body_ema_typ:.2f} "
          f"(M5 spike bar needs body>={M5_THRESH*body_ema_typ:.2f})")

    # --- PART 1: filter tally on live tick spikes ---------------------------
    spikes = detect_tick_spikes(ticks)
    bars = {}
    for ts, bid in ticks:
        k = ts - ts % BAR
        b = bars.setdefault(k, {"open": bid, "high": bid, "low": bid, "close": bid})
        b["high"] = max(b["high"], bid)
        b["low"] = min(b["low"], bid)
        b["close"] = bid
    tally = {}
    tick_out = {}
    for sp in spikes:
        bt = sp["t0"] - sp["t0"] % BAR
        bar = bars.get(bt)
        body = abs(bar["close"] - bar["open"]) if bar else 0
        # filter 1: M5 detection
        if body < M5_THRESH * body_ema_typ:
            tally["NO-DETECT (body<%.1f)" % (M5_THRESH * body_ema_typ)] = \
                tally.get("NO-DETECT (body<%.1f)" % (M5_THRESH * body_ema_typ), 0) + 1
            tick_out.setdefault("m5_no_detect", []).append(round(sp["jump"], 1))
            continue
        # filters 2-3: direction (Boom spike up -> passes), cooldown (1 bar, skipped)
        fired = False
        for k in range(1, WINDOW_BARS + 1):
            bt2 = bt + k * BAR
            b2 = bars.get(bt2)
            if not b2:
                continue
            px = b2["close"]
            if px >= sp["peak"]:
                continue
            retrace = (sp["peak"] - px) / body
            if retrace < DEPLOYED_LO:
                tally.setdefault("RETRACE-LOW (below window-lo at every sampled close)", 0)
                continue
            if retrace > DEPLOYED_HI:
                tally["RETRACE-HIGH/OVERSHOT (window crossed between closes)"] = \
                    tally.get("RETRACE-HIGH/OVERSHOT (window crossed between closes)", 0) + 1
                break
            fired = True
            tally["ENTRY (M5 path)"] = tally.get("ENTRY (M5 path)", 0) + 1
            break
        if not fired and "RETRACE-HIGH/OVERSHOT (window crossed between closes)" not in tally.get("_", {}):
            if all((bars.get(bt + k * BAR) or {}).get("close", 9e9) >= sp["peak"]
                   for k in range(1, WINDOW_BARS + 1) if bars.get(bt + k * BAR)):
                tally["NO-RETRACE (price never pulled back)"] = \
                    tally.get("NO-RETRACE (price never pulled back)", 0) + 1
            else:
                tally.setdefault("RETRACE-LOW (below window-lo at every sampled close)", 0)
                tally["RETRACE-LOW (below window-lo at every sampled close)"] += 1

        # tick-path outcome (deployed params)
        i0 = bisect.bisect_right(ticks_ts, sp["t0"])
        res = "END"
        for i in range(i0 + 1, len(ticks_ts)):
            ts, bid = ticks_ts[i], ticks_bid[i]
            if bid <= sp["pre"]:
                res = "FULL-RETRACE"
                break
            r = (sp["peak"] - bid) / sp["jump"]
            if r > DEPLOYED_HI:
                res = "OVERSHOT"
                break
            if ts - sp["t0"] > 600:
                res = "TIMEOUT"
                break
            if DEPLOYED_LO <= r <= DEPLOYED_HI:
                res = "FIRED"
                break
        tick_out.setdefault("tick_" + res, []).append(round(sp["jump"], 1))
        tally["TICKPATH-" + res] = tally.get("TICKPATH-" + res, 0) + 1

    print("\n--- PART 1: FILTER TALLY (13 live spikes, Aug 29) ---")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>3}  {k}")
    for k, v in sorted(tick_out.items()):
        print(f"      {k}: jumps={v}")

    # --- PART 2: retrace-window sweep on 60d data ---------------------------
    days = (m5[-1]["epoch"] - m5[0]["epoch"]) / 86400.0
    idx = [s["idx"] for s in spikes60 if s["is_spike"]]
    print(f"\n--- PART 2: RETRACE-WINDOW SWEEP (60d, thr {M5_THRESH}, "
          f"sl {SL_MULT}xATR tp {TP_MULT}xATR) ---")
    rows = []
    for lo, hi in SWEEP_WINDOWS:
        tr = fade_sim(m5, idx, compute_atr(m5), lo, hi)
        m = metrics(tr)
        m["window"] = f"{lo:.2f}-{hi:.2f}"
        rows.append(m)
        print(f"  {lo:.2f}-{hi:.2f}: trades={m.get('trades',0):>4} ({m.get('trades',0)/days:>4.1f}/d)  "
              f"WR={m.get('wr',0):>5}%  PF={m.get('pf',0):>5}  ExpR={m.get('exp_r',0):>+.3f}  "
              f"totalR={m.get('total_r',0):>7}")
    best = max((r for r in rows if r.get("trades", 0) >= 50),
               key=lambda r: r.get("total_r", 0), default=None)

    # --- PART 3: tick timeout / retrace-lo sweep ----------------------------
    print("\n--- PART 3: TICK-PATH SWEEP (live spikes, exits on ticks) ---")
    rows3 = []
    for to in TIMEOUTS:
        for lo in TICK_LOS:
            trades = []
            for sp in spikes:
                i0 = bisect.bisect_right(ticks_ts, sp["t0"])
                for i in range(i0 + 1, len(ticks_ts)):
                    ts, bid = ticks_ts[i], ticks_bid[i]
                    if bid <= sp["pre"]:
                        break
                    r = (sp["peak"] - bid) / sp["jump"]
                    if r > DEPLOYED_HI:
                        break
                    if ts - sp["t0"] > to:
                        break
                    if lo <= r <= DEPLOYED_HI:
                        plan = plan_trade(bid, sp["pre"], atr)
                        if plan:
                            rr, reason = exit_r(ticks_ts, ticks_bid, ts, bid,
                                                plan[0], plan[1], plan[2], TIME_EXIT_BARS * BAR)
                            trades.append({"r": rr, "reason": reason})
                        break
            m = metrics(trades)
            m["cfg"] = f"to={to}s lo={lo:.2f}"
            rows3.append(m)
    rows3.sort(key=lambda m: -m.get("total_r", 0))
    for m in rows3[:8]:
        print(f"  {m['cfg']}: trades={m.get('trades',0)}  WR={m.get('wr',0)}%  "
              f"PF={m.get('pf',0)}  ExpR={m.get('exp_r',0):+.2f}  totalR={m.get('total_r',0)}")

    out = {"tally": tally, "window_sweep": rows, "tick_sweep_top": rows3[:12]}
    (ART / "boom_filter_tally_tune.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\n[wrote] artifacts/boom_filter_tally_tune.json")

    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    if best:
        print(f"Best 60d window: {best['window']} -> PF {best.get('pf')} "
              f"ExpR {best.get('exp_r')} totalR {best.get('total_r')} "
              f"({best.get('trades', 0)} trades)")
    top3 = rows3[:3]
    if top3:
        print(f"Best tick-path cfgs: " + " | ".join(m["cfg"] for m in top3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
