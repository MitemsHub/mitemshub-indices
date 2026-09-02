#!/usr/bin/env python3
"""Scalp-geometry sweep for the governor-coordination build (v26.22).

Question: does a tighter, achievable TP (little profits, often) beat the
legacy 2.4x-stop target on V75 M15 — after real per-bar spread, worst-case
fills, on the same EA-faithful 5-leg signal engine as fwd_split_backtest?

Reuses signals() from fwd_split_backtest (importlib) so the entry engine is
byte-identical to the validated baseline. Sweeps:
  TP mult   x stop_dist : 0.6 0.8 1.0 1.2 1.5 2.0 2.4(legacy)
  SL mult   x ATR       : 1.0 1.5 2.0
  hold cap  bars        : 6 12 20

Metrics per cell: trades, WR, PF, expR, trades/day, R/day, plus the 70/30
in-sample/out-of-sample split (OOS is the referee, same as the baseline).
Writes artifacts/scalp_sweep_volatility_75_index.json
"""
from __future__ import annotations

import csv
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
CSV_BARS = ART / "data" / "volatility_75_index_m15_40000bars.csv"
POINT = 0.01

# load the EA-faithful engine from the baseline script
spec = importlib.util.spec_from_file_location(
    "fwd_split_backtest", ROOT / "scripts" / "fwd_split_backtest.py")
fsb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fsb)


def simulate(o, h, l, c, sig, a, spread, sl_mult, tp_mult, hold_bars):
    """Bar-loop sim, worst-case fills, per-bar spread, parametrized geometry."""
    trades = []  # (bar_index, r)
    i = 0
    n = len(c)
    while i < n - 1:
        d = sig[i]
        if d == 0 or a[i] <= 0:
            i += 1
            continue
        stop_d = sl_mult * a[i]
        tp_d = tp_mult * stop_d
        sp = spread[i + 1]
        if d > 0:
            entry = o[i + 1] + sp / 2.0
            sl, tp = entry - stop_d, entry + tp_d
        else:
            entry = o[i + 1] - sp / 2.0
            sl, tp = entry + stop_d, entry - tp_d
        r = None
        j_end = min(i + 1 + hold_bars, n)
        for j in range(i + 1, j_end):
            if d > 0:
                if l[j] <= sl:
                    r = -1.0
                    break
                if h[j] >= tp:
                    r = tp_d / stop_d
                    break
            else:
                if h[j] >= sl:
                    r = -1.0
                    break
                if l[j] <= tp:
                    r = tp_d / stop_d
                    break
        if r is None:
            j = j_end - 1
            exit_p = c[j] - sp / 2.0 * d
            r = d * (exit_p - entry) / stop_d
        r -= sp / stop_d
        trades.append((i, r))
        i = j + 1
    return trades


def stats(trades):
    if not trades:
        return {"trades": 0}
    rs = [t[1] for t in trades]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x <= 0]
    gw, gl = sum(wins), sum(losses)
    cum = peak = dd = 0.0
    for x in rs:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {
        "trades": len(rs),
        "wr": round(100 * len(wins) / len(rs), 1),
        "pf": round(gw / gl, 2) if gl > 0 else 99.0,
        "exp_r": round(sum(rs) / len(rs), 3),
        "total_r": round(sum(rs), 2),
        "max_dd_r": round(dd, 2),
    }


def main() -> int:
    with open(CSV_BARS, newline="") as f:
        rd = csv.reader(f)
        col = {k: i for i, k in enumerate(next(rd))}
        data = list(rd)
    o, h, l, c = (np.array([float(r[col[k]]) for r in data])
                  for k in ("open", "high", "low", "close"))
    times = np.array([int(float(r[col["ts"]])) for r in data], dtype=np.int64)
    spread = np.array([float(r[col["spread"]]) for r in data]) * POINT
    days = (times[-1] - times[0]) / 86400.0

    sig, a, _ = fsb.signals(o, h, l, c)

    TP_GRID = [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.4]
    SL_GRID = [1.0, 1.5, 2.0]
    HOLD_GRID = [6, 12, 20]

    rows = []
    for sl_m in SL_GRID:
        for tp_m in TP_GRID:
            for hold in HOLD_GRID:
                tr = simulate(o, h, l, c, sig, a, spread, sl_m, tp_m, hold)
                if not tr:
                    continue
                s = stats(tr)
                split = int(len(tr) * fsb.IS_FRAC)
                oos = stats(tr[split:])
                # activity metrics on the OOS window
                oos_idx = [t[0] for t in tr[split:]]
                oos_days = (times[oos_idx[-1]] - times[oos_idx[0]]) / 86400.0 if oos_idx else 1
                tpd = oos["trades"] / max(oos_days, 1e-9)
                rows.append({
                    "sl": sl_m, "tp": tp_m, "hold": hold,
                    "all": s, "oos": oos,
                    "oos_trades_per_day": round(tpd, 2),
                    "oos_r_per_day": round(oos.get("exp_r", 0) * tpd, 3),
                })

    rows.sort(key=lambda r: -r["oos_r_per_day"])
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": "Volatility 75 Index", "bars": len(c), "days": round(days, 1),
        "spread_median": round(float(np.median(spread)), 2),
        "baseline_oos_r_per_day": None,
        "cells": rows,
    }
    (ART / "scalp_sweep_volatility_75_index.json").write_text(json.dumps(out, indent=1))

    print(f"== scalp sweep V75 M15 | {len(c)} bars | spread med {out['spread_median']} ==")
    print(f"{'SL':>4} {'TP':>4} {'HOLD':>4} | {'OOS_tr':>6} {'WR':>5} {'PF':>5} {'expR':>6} {'tr/day':>6} {'R/day':>6}")
    for r in rows[:18]:
        oo = r["oos"]
        print(f"{r['sl']:>4} {r['tp']:>4} {r['hold']:>4} | {oo.get('trades',0):>6} "
              f"{oo.get('wr',0):>5} {oo.get('pf',0):>5} {oo.get('exp_r',0):>6} "
              f"{r['oos_trades_per_day']:>6} {r['oos_r_per_day']:>6}")
    print(f"... {len(rows)} cells total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
