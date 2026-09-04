"""Tick-level fast-fail study: does cutting stalled trades early pay on REAL ticks?

Replays the certified VOL75 trade lists (artifacts/v75_replay/cert_report_*.json)
through the broker's recorded V75 tick stream (data/v75_ticks_cert_window.csv),
simulating the full EA exit ladder tick-by-tick at real bid/ask:
  SL/TP fills at the touching tick's price (gap-through honest),
  BE at hw>=1.0R, trail from 1.0R at 0.7R, PLOCK at hw>=1.0 & 0<r<=0.5,
  ECUT (6 bars, r<=-0.4, hw<0.3), TIME at bar 30 (extend to 45 / runner rule),
all evaluated intrabar at tick precision (the EA runs per-tick too).

Then overlays tick-level fast-fail (FF) arms that differ ONLY in an early-cut:
  giveback arms: once peak gain >= G (R), cut when price retraces F of that
                 peak from its high-water (e.g. G=0.5, F=0.7).
  stall arms:    no new high-water for M minutes AND r <= floor -> cut.

Arms are compared PAIRED (identical entries), with a bootstrap CI on the mean
R delta. Fills cross the real recorded spread: BUY entries at ask, closes at
bid; SELL entries at bid, closes at ask. The spread paid is therefore the
broker's actual spread at each moment -- no modeled conservatism needed.

Usage: python scripts/study_fastfail_ticks.py
Writes: artifacts/v75_replay/fastfail_tick_study.json
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import random
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
TICKS = os.path.join(HERE, "..", "data", "v75_ticks_cert_window.csv")

BAR = 900_000          # M15 in ms
MAX_BARS = 96          # hard cap: 24h
PLOCK_HW, PLOCK_Z = 1.0, 0.5
BE_TRIG, TRAIL_START, TRAIL_DIST = 1.0, 1.0, 0.7
ECUT_BARS, ECUT_R, ECUT_HW = 6, -0.4, 0.3
TIME_BARS, TIME_EXT_BARS = 30, 45


def load_ticks():
    ts, bid, ask = [], [], []
    with open(TICKS) as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            ts.append(int(row[0])); bid.append(float(row[1])); ask.append(float(row[2]))
    return ts, bid, ask


def load_trades(report, tp_r):
    with open(os.path.join(DATA, report)) as f:
        rep = json.load(f)
    out = []
    for t in rep["trades"]:
        out.append({
            "t0": int(datetime.fromisoformat(t["t"]).timestamp() * 1000),
            "dir": 1 if t["dir"] == "BUY" else -1,
            "entry": t["entry"], "sd": t["sd"], "tp_r": tp_r,
        })
    return rep.get("config", {}), out


def simulate(tr, ts, bid, ask, ff=None):
    """ff = None | ("giveback", G, F) | ("stall", minutes, floor_r). Returns (r, reason)."""
    d = tr["dir"]; sd = tr["sd"]; tp_r = tr["tp_r"]
    i = bisect.bisect_left(ts, tr["t0"])
    if i >= len(ts):
        return None, "no-ticks"
    if d > 0:
        entry = ask[i]; sl = entry - sd; tp = entry + sd * tp_r
    else:
        entry = bid[i]; sl = entry + sd; tp = entry - sd * tp_r
    t_end = tr["t0"] + MAX_BARS * BAR
    hw = 0.0
    t_last_hw = tr["t0"]          # O(1) stall tracking: when hw last made a new high
    while i < len(ts) and ts[i] <= t_end:
        px_close = bid[i] if d > 0 else ask[i]        # price you can exit at now
        px_fav = bid[i] if d > 0 else ask[i]          # favorable excursion source
        rc = (px_close - entry) * d / sd
        fav = (px_fav - entry) * d / sd
        if fav > hw:
            hw = fav; t_last_hw = ts[i]
        hit_sl = (bid[i] <= sl) if d > 0 else (ask[i] >= sl)
        hit_tp = (bid[i] >= tp) if d > 0 else (ask[i] <= tp)
        if ff is not None:
            kind = ff[0]
            if kind == "giveback" and hw >= ff[1] and fav <= hw - ff[2] * hw and rc < hw - ff[2] * hw:
                return rc, "FF-giveback"
            if kind == "stall":
                mins, floor_r = ff[1], ff[2]
                if ts[i] - t_last_hw >= mins * 60_000 and rc <= floor_r:
                    return rc, "FF-stall"
        if hit_sl and not hit_tp:
            return (px_close - entry) * d / sd, ("BE" if abs((sl - entry) * d / sd) < 1e-9 and abs(rc) < 0.05 else "SL")
        if hit_tp and not hit_sl:
            return tp_r, "TP"
        if hit_sl and hit_tp:
            return (px_close - entry) * d / sd, "SL(ambig)"
        bars_held = (ts[i] - tr["t0"]) // BAR
        if hw >= PLOCK_HW and 0 < rc <= PLOCK_Z:
            return rc, "PLOCK"
        if hw >= BE_TRIG:
            ns = entry
            if (d > 0 and ns > sl) or (d < 0 and ns < sl):
                sl = ns
        if hw >= TRAIL_START:
            ns = px_close - d * TRAIL_DIST * sd
            if (d > 0 and ns > sl) or (d < 0 and ns < sl):
                sl = ns
        if bars_held >= ECUT_BARS and rc <= ECUT_R and hw < ECUT_HW:
            return rc, "ECUT"
        if bars_held >= TIME_BARS and rc <= 0.2:
            return rc, "TIME" if bars_held < TIME_EXT_BARS else "TIME_EXT"
        i += 1
    return (bid[-1] - entry) * d / sd if d > 0 else (entry - ask[-1]) * d / sd, "EOD"


def run_arm(trades, ts, bid, ask, ff=None):
    rs, reasons = [], []
    for tr in trades:
        r, why = simulate(tr, ts, bid, ask, ff)
        rs.append(r); reasons.append(why)
    return rs, reasons


def boot_ci(deltas, n=10000, seed=7):
    rnd = random.Random(seed)
    m = len(deltas)
    means = sorted(sum(rnd.choices(deltas, k=m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def summarize(name, rs, reasons):
    n = len(rs)
    wins = sum(1 for r in rs if r > 0)
    return {"arm": name, "n": n, "total_r": round(sum(rs), 2),
            "mean_r": round(sum(rs) / n, 3),
            "wr": round(wins / n * 100, 1),
            "reasons": {k: v for k, v in sorted((x, reasons.count(x)) for x in set(reasons))}}


def main():
    ts, bid, ask = load_ticks()
    print(f"ticks loaded: {len(ts):,}")

    # fidelity check vs broker bars (same validation the junk recording failed)
    sys.path.insert(0, HERE)
    from replay_v75_week import load
    m15 = load("m15.csv")
    import statistics
    tb = {}
    for i, t in enumerate(ts):
        k = t // BAR
        b = tb.get(k)
        if b is None:
            tb[k] = [bid[i], bid[i], bid[i], bid[i]]
        else:
            b[1] = max(b[1], bid[i]); b[2] = min(b[2], bid[i]); b[3] = bid[i]
    pairs = [(tb[t // BAR], b) for b in m15
             if (t := int(b["t"].timestamp() * 1000)) in tb]
    if len(pairs) > 100:
        ct = [((p[0][3] - p[0][0]) / p[0][0] * 1e4) for p in pairs]
        cb = [((p[1]["c"] - p[1]["o"]) / p[1]["o"] * 1e4) for p in pairs]
        print(f"fidelity: {len(pairs)} overlapping M15 bars, return corr = "
              f"{statistics.correlation(ct, cb):.3f} (must be ~1)")

    sets = {
        "v2629 (deployed stack, n=56)": ("cert_report_v2629_cert200.json", 1.8),
        "honest baseline (n=65)": ("cert_report_cand_honest.json", 2.4),
    }
    arms = [
        ("ladder", None),
        ("ff-giveback G0.3 F0.7", ("giveback", 0.3, 0.7)),
        ("ff-giveback G0.5 F0.7", ("giveback", 0.5, 0.7)),
        ("ff-giveback G0.8 F0.7", ("giveback", 0.8, 0.7)),
        ("ff-giveback G0.5 F0.5", ("giveback", 0.5, 0.5)),
        ("ff-stall 45m r<=0", ("stall", 45, 0.0)),
        ("ff-stall 90m r<=0", ("stall", 90, 0.0)),
        ("ff-stall 90m r<=-0.2", ("stall", 90, -0.2)),
    ]
    out = {"fidelity_note": "broker COPY_TICKS_INFO stream, real spread fills",
           "sets": {}}
    for set_name, (report, tp_r) in sets.items():
        cfg, trades = load_trades(report, tp_r)
        base_rs, base_why = run_arm(trades, ts, bid, ask, None)
        res = {"config": cfg, "arms": [summarize("ladder", base_rs, base_why)]}
        print(f"\n== {set_name} ==")
        print(f"  ladder: total={sum(base_rs):+7.2f}R mean={sum(base_rs)/len(base_rs):+.3f} "
              f"WR={sum(1 for r in base_rs if r>0)/len(base_rs)*100:.0f}%")
        for name, ff in arms[1:]:
            rs, why = run_arm(trades, ts, bid, ask, ff)
            deltas = [a - b for a, b in zip(rs, base_rs)]
            lo, hi = boot_ci(deltas)
            s = summarize(name, rs, why)
            s["delta_mean_r"] = round(sum(deltas) / len(deltas), 3)
            s["delta_ci95"] = [round(lo, 3), round(hi, 3)]
            res["arms"].append(s)
            print(f"  {name:24s} total={sum(rs):+7.2f}R d={s['delta_mean_r']:+.3f} "
                  f"CI[{lo:+.2f},{hi:+.2f}] WR={s['wr']:.0f}% {s['reasons']}")
        out["sets"][set_name] = res

    path = os.path.join(DATA, "fastfail_tick_study.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nartifact: {path}")


if __name__ == "__main__":
    main()
