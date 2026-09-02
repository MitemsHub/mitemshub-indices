#!/usr/bin/env python3
"""PB-primary redesign search — pre-registered, single OOS shot.

Background: per-leg IS decomposition (artifacts/entry_filter_search_v75.json)
showed PB (pullback-with-trend) is the only leg with a positive structural
signature (+0.32R, PF 1.66) but fires ~1/week under confluence rules; the
BF+MR blend that dominates the engine bleeds ~-0.035R/trade.

Pre-registered variants (all solo-firing, preset-exact geometry):
  V4 pb_conf    : pullback-and-go — dip bar (i-1) then close back above EMA20 (i)
  V1 pb_solo    : PB condition alone (EMA20 touch, regime-aligned, close>EMA50)
  V3 pb_wide    : widened zone — low reaches EMA50, close holds above EMA100
  V2 deep_mr    : deep pullback — |c-EMA50| > 2xATR AGAINST the trend regime
  V5 pb_zguard  : pb_solo but blocked when z is stretched against the trade

Protocol:
  - IS gates (pre-registered): IS trades >= 100, IS expR >= +0.05, IS PF >= 1.10
  - The best IS variant by expR takes the SINGLE OOS shot (trades >= 60,
    PF >= 1.15, expR > 0, maxDD <= 15R). Fail = the idea is dead; no second shot.
  - OOS pass -> Monte-Carlo (150 x 30-day $30 windows, compounding engine).
Writes artifacts/pb_primary_search_v75.json
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
CSV_BARS = ART / "data" / "volatility_75_index_m15_40000bars.csv"
POINT = 0.01
SL_MULT, TP_MULT, HOLD = 1.7, 2.0, 20
IS_FRAC = 0.70

spec = importlib.util.spec_from_file_location(
    "fwd_split_backtest", ROOT / "scripts" / "fwd_split_backtest.py")
fsb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fsb)
spec2 = importlib.util.spec_from_file_location(
    "entry_filter_search", ROOT / "scripts" / "entry_filter_search.py")
efs = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(efs)


def load_bars():
    with open(CSV_BARS, newline="") as f:
        rd = csv.reader(f)
        col = {k: i for i, k in enumerate(next(rd))}
        data = list(rd)
    o, h, l, c = (np.array([float(r[col[k]]) for r in data])
                  for k in ("open", "high", "low", "close"))
    ts = np.array([int(float(r[col["ts"]])) for r in data], dtype=np.int64)
    spread = np.array([float(r[col["spread"]]) for r in data]) * POINT
    return o, h, l, c, ts, spread


def build_variants(o, h, l, c, reg, z):
    e20, e50, e100 = fsb.ema(c, 20), fsb.ema(c, 50), fsb.ema(c, 100)
    n = len(c)
    zpad = np.concatenate((np.zeros(20), z))[:n]  # safety pad (z already aligned)

    def blank():
        s = np.zeros(n, dtype=np.int8)
        return s

    V = {}

    # V1 pb_solo: dip to EMA20 in aligned regime, close holds beyond EMA50
    s = blank()
    s[(reg == 1) & (l <= e20 * 1.0005) & (c > e50)] = 1
    s[(reg == 2) & (h >= e20 * 0.9995) & (c < e50)] = -1
    V["V1_pb_solo"] = s

    # V4 pb_conf: dip bar then resumption close above EMA20
    s = blank()
    dip_b = (reg == 1) & (l <= e20 * 1.0005) & (c > e50)
    dip_s = (reg == 2) & (h >= e20 * 0.9995) & (c < e50)
    res_b = np.zeros(n, dtype=bool); res_b[1:] = c[1:] > e20[1:]
    res_s = np.zeros(n, dtype=bool); res_s[1:] = c[1:] < e20[1:]
    up1 = np.zeros(n, dtype=bool); up1[1:] = dip_b[:-1]
    dn1 = np.zeros(n, dtype=bool); dn1[1:] = dip_s[:-1]
    s[up1 & res_b] = 1
    s[dn1 & res_s] = -1
    V["V4_pb_conf"] = s

    # V3 pb_wide: low reaches EMA50, close holds above EMA100, regime aligned
    s = blank()
    s[(reg == 1) & (l <= e50 * 1.001) & (c > e100)] = 1
    s[(reg == 2) & (h >= e50 * 0.999) & (c < e100)] = -1
    V["V3_pb_wide"] = s

    # V2 deep_mr: stretch >2xATR from EMA50 AGAINST the regime = deep pullback
    a_base = np.zeros(n)
    s = blank()
    stretch = np.abs(c - e50)
    s[(reg == 1) & (c < e50) & (stretch > 2.0)] = 1     # needs ATR; filled below
    s[(reg == 2) & (c > e50) & (stretch > 2.0)] = -1
    V["V2_deep_mr_RAW"] = s   # ATR gate applied in main after atr computed

    # V5 pb_zguard: pb_solo but skip when z stretched against the trade
    s = blank()
    base = V["V1_pb_solo"].copy()
    s[(base == 1) & (zpad < 2.0)] = 1
    s[(base == -1) & (zpad > -2.0)] = -1
    V["V5_pb_zguard"] = s

    return V, e20, e50, e100


def main() -> int:
    o, h, l, c, ts, spread = load_bars()
    _, a, reg = fsb.signals(o, h, l, c)
    w = 20
    roll_mean = np.convolve(c, np.ones(w) / w, mode="valid")
    roll_std = np.array([c[k - w + 1:k + 1].std() for k in range(w - 1, len(c))])
    z = np.concatenate((np.zeros(w - 1), (c[w - 1:] - roll_mean) / np.maximum(roll_std, 1e-12)))
    z = np.concatenate((np.zeros(1), z))[:-1]

    V, e20, e50, e100 = build_variants(o, h, l, c, reg, z)
    # finish V2 with the ATR gate
    stretch = np.abs(c - e50)
    v2 = np.zeros(len(c), dtype=np.int8)
    v2[(reg == 1) & (c < e50) & (stretch > 2.0 * a)] = 1
    v2[(reg == 2) & (c > e50) & (stretch > 2.0 * a)] = -1
    V["V2_deep_mr"] = v2
    del V["V2_deep_mr_RAW"]

    # warmup mask: bars before EMA100+z window ready
    warm = np.zeros(len(c), dtype=bool)
    warm[110:] = True

    results = []
    feats = {}
    for name, sig in V.items():
        sig = sig.copy()
        sig[~warm] = 0
        trades = efs.build_trades(o, h, l, c, ts, spread, feats) if False else None
        # direct build (efs.build_trades recomputes fsb.signals internally; use own)
        trades = build_trades_for(o, h, l, c, ts, spread, sig, a)
        split = int(len(trades) * IS_FRAC)
        s_is, s_oos = efs.stats(trades[:split]), efs.stats(trades[split:])
        gate = (s_is.get("trades", 0) >= 100 and s_is.get("exp_r", -9) >= 0.05
                and s_is.get("pf", 0) >= 1.10)
        results.append({"variant": name, "is": s_is, "oos": s_oos, "is_gate": bool(gate)})
        print(f"{name:14s} IS: {s_is}")
        print(f"{'':14s} OOS(count only): {s_oos.get('trades', 0)} trades — "
              f"{'GATE PASS' if gate else 'gate fail'} (OOS stats sealed until the shot)")

    # rank by IS expR among gate-passers; single OOS shot
    passers = [r for r in results if r["is_gate"]]
    if not passers:
        print("\nNo variant cleared the pre-registered IS gates — idea dead at gate 1.")
        out = {"generated_utc": datetime.now(timezone.utc).isoformat(),
               "variants": results, "oos_shot": None, "verdict": "DEAD_AT_IS_GATES"}
        (ART / "pb_primary_search_v75.json").write_text(json.dumps(out, indent=1))
        return 1

    best = max(passers, key=lambda r: r["is"]["exp_r"])
    print(f"\nSingle OOS shot -> {best['variant']} (best IS expR {best['is']['exp_r']})")
    s_oos = best["oos"]
    fails = []
    if s_oos.get("trades", 0) < 60: fails.append("trades<60")
    if s_oos.get("pf", 0) < 1.15: fails.append("PF<1.15")
    if s_oos.get("exp_r", -1) <= 0: fails.append("expR<=0")
    if s_oos.get("max_dd_r", 99) > 15: fails.append("DD>15R")
    ok = not fails
    print(f"OOS: {s_oos}  -> {'PASS' if ok else 'FAIL(' + ','.join(fails) + ')'}")

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(),
           "variants": results, "oos_shot": {"variant": best["variant"], "oos": s_oos,
                                             "verdict": "PASS" if ok else "FAIL"},
           "verdict": None, "monte_carlo": None}
    if not ok:
        out["verdict"] = "DEAD_AT_OOS"
        (ART / "pb_primary_search_v75.json").write_text(json.dumps(out, indent=1))
        return 1

    out["verdict"] = "OOS_PASS"
    # ---------------- Monte-Carlo with the winning variant ----------------
    sig = V[best["variant"]].copy()
    sig[~warm] = 0
    tick, tv, equity0 = 0.01, 0.0001, 30.0
    n = len(c)
    rng = random.Random(7)
    starts = rng.sample(range(150, n - 30 * 96 - 2), 150)
    ends = []
    for s0 in starts:
        equity, consec, paused_day = equity0, 0, -1
        i = s0
        end_pos = min(n - 1, s0 + 30 * 96)
        while i < end_pos - 1:
            d = sig[i]
            if d == 0 or a[i] <= 0:
                i += 1; continue
            day = int(ts[i] // 86400)
            if day <= paused_day:
                i += 1; continue
            stop_d = SL_MULT * a[i]
            if d > 0:
                lo = l[max(0, i - 5):i].min()
                stop_d = max(stop_d, o[i + 1] - (lo - 0.15 * a[i]))
            else:
                hi = h[max(0, i - 5):i].max()
                stop_d = max(stop_d, (hi + 0.15 * a[i]) - o[i + 1])
            stop_d = max(stop_d, 0.5 * a[i]); stop_d = min(stop_d, c[i] * 0.03)
            tp_d = TP_MULT * stop_d
            sp = spread[i + 1]
            risk_money = equity * 0.005
            vol = math.floor(risk_money / ((stop_d / tick) * tv) / 0.01) * 0.01
            vol = max(vol, 0.01)
            if consec > 0:
                vol = max(math.floor(vol * max(0.75 ** consec, 0.30) / 0.01) * 0.01, 0.01)
            eff_risk = vol * (stop_d / tick) * tv
            if d > 0:
                entry = o[i + 1] + sp / 2.0
                sl, tp = entry - stop_d, entry + tp_d
            else:
                entry = o[i + 1] - sp / 2.0
                sl, tp = entry + stop_d, entry - tp_d
            r = None
            j_end = min(i + 1 + HOLD, end_pos)
            for j in range(i + 1, j_end):
                if d > 0:
                    if l[j] <= sl: r = -1.0; break
                    if h[j] >= tp: r = TP_MULT; break
                else:
                    if h[j] >= sl: r = -1.0; break
                    if l[j] <= tp: r = TP_MULT; break
            if r is None:
                j = j_end - 1
                r = d * (c[j] - (sp / 2.0) * d - entry) / stop_d
            r -= sp / stop_d
            equity += r * eff_risk
            consec = consec + 1 if r < 0 else 0
            if consec >= 3:
                paused_day = day; consec = 0
            i = j + 1
        ends.append(equity)
    ends = np.array(ends)
    mc = {"windows": len(ends), "median_end": round(float(np.median(ends)), 2),
          "pct_profitable": round(float((ends > equity0).mean() * 100), 1),
          "p5": round(float(np.percentile(ends, 5)), 2),
          "p95": round(float(np.percentile(ends, 95)), 2),
          "worst": round(float(ends.min()), 2), "best": round(float(ends.max()), 2)}
    out["monte_carlo"] = mc
    print(f"\nMonte-Carlo ({mc['windows']} x 30-day, $30, {best['variant']}):")
    print(f"  median ${mc['median_end']} | profitable {mc['pct_profitable']}% "
          f"| p5 ${mc['p5']} / p95 ${mc['p95']} | worst ${mc['worst']} / best ${mc['best']}")
    (ART / "pb_primary_search_v75.json").write_text(json.dumps(out, indent=1))
    return 0


def build_trades_for(o, h, l, c, ts, spread, sig, a):
    n = len(c)
    trades = []
    i = 0
    while i < n - 1:
        d = sig[i]
        if d == 0 or a[i] <= 0:
            i += 1
            continue
        stop_d = SL_MULT * a[i]
        if d > 0:
            lo = l[max(0, i - 5):i].min()
            stop_d = max(stop_d, o[i + 1] - (lo - 0.15 * a[i]))
        else:
            hi = h[max(0, i - 5):i].max()
            stop_d = max(stop_d, (hi + 0.15 * a[i]) - o[i + 1])
        stop_d = max(stop_d, 0.5 * a[i])
        stop_d = min(stop_d, c[i] * 0.03)
        tp_d = TP_MULT * stop_d
        sp = spread[i + 1]
        if d > 0:
            entry = o[i + 1] + sp / 2.0
            sl, tp = entry - stop_d, entry + tp_d
        else:
            entry = o[i + 1] - sp / 2.0
            sl, tp = entry + stop_d, entry - tp_d
        r = None
        j_end = min(i + 1 + HOLD, n)
        for j in range(i + 1, j_end):
            if d > 0:
                if l[j] <= sl: r = -1.0; break
                if h[j] >= tp: r = TP_MULT; break
            else:
                if h[j] >= sl: r = -1.0; break
                if l[j] <= tp: r = TP_MULT; break
        if r is None:
            j = j_end - 1
            r = d * (c[j] - (sp / 2.0) * d - entry) / stop_d
        r -= sp / stop_d
        trades.append({"i": i, "ts": int(ts[i]), "d": d, "r": r})
        i = j + 1
    return trades


if __name__ == "__main__":
    raise SystemExit(main())
