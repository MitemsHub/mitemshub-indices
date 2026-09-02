#!/usr/bin/env python3
"""Simulate a $30 account trading the V75 preset (VOL75_FINAL) for 30 days.

Equity engine mirrors MitemshubAI.mq5 v26.21 OpenTrade() sizing exactly:
  risk_money   = equity * 0.5% (InpRiskPerTrade) * 1.0 (no meta table)
  stop_dist    = band ? sig_sl_atr*ATR : 1.7*ATR widened to 5-bar swing
                 (floor 0.5*ATR, floor stops-level, cap 3% of price)
  tp_dist      = band ? sig_tp_atr*ATR : 2.4 * stop_dist
  vol          = floor(risk_money/((stop/tick)*tv), 0.01) -> min lot 0.01
  eff_risk     = vol * (stop/tick) * tv      (what the ledger records)
  after loss   : vol *= 0.75^n (floor 0.30) ; pause for the rest of the
                 calendar day after 3 consecutive losses (InpMaxConsecLoss=3)
  worst-case fills: SL wins intrabar ties; spread paid per round trip in R

The signal engine is the validated fwd_split_backtest.py implementation
(regime classify, 5 legs, momentum demotion, confluence >= 2 legs / score 3).

Equity compounds: risk_money derives from CURRENT equity each trade.

Usage:
  .venv/Scripts/python.exe scripts/simulate_30day_v75.py [--equity 30] [--mc 200]
Writes artifacts/sim30d_v75.json and prints the equity curve table.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

# --- preset / engine constants (VOL75_FINAL + v26.21 defaults) ---
RISK_PER_TRADE = 0.005
TP_MULT = 2.4
SL_ATR_MULT = 1.7
SWING_WIDEN = True
MAX_HOLD_BARS = 20
SCALE_AFTER_LOSS, SCALE_FACTOR, MIN_VOL_SCALE = True, 0.75, 0.30
MAX_CONSEC_LOSS = 3
MIN_LOT = 0.01
VOL_STEP = 0.01


def sim_window(rates, si, equity0: float, start_pos: int, n_days: int = 30):
    """One 30-day equity-curve simulation starting at bar `start_pos`."""
    o = rates["open"]; h = rates["high"]; l = rates["low"]; c = rates["close"]
    times = rates["time"]
    end_pos = min(len(c) - 1, start_pos + n_days * 96)  # 96 M15 bars/day
    seg = {k: rates[k][start_pos:end_pos] for k in ("open", "high", "low", "close", "time")}
    return run_engine(seg, si, equity0)


def run_engine(seg, si, equity0: float):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fwd", ROOT / "scripts" / "fwd_split_backtest.py")
    fwd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fwd)

    o, h, l, c = (np.array(seg[k], dtype=float) for k in ("open", "high", "low", "close"))
    times = np.array(seg["time"], dtype=np.int64)
    sig, a, _ = fwd.signals(o, h, l, c)
    spread = si.spread * si.point
    tick = si.trade_tick_size
    tv = si.trade_tick_value
    stops_u = si.trade_stops_level * si.point

    equity = equity0
    consec = 0
    paused_until_day = -1
    curve = []          # (bar_index, equity) after each close
    trades = []         # (ts, r, eff_risk, vol)
    i = 0
    n = len(c)
    while i < n - 1:
        d = sig[i]
        if d == 0 or a[i] <= 0:
            i += 1
            continue
        day = int(times[i] // 86400)
        if day <= paused_until_day:
            i += 1
            continue
        # ---- geometry (OpenTrade) ----
        stop_d = SL_ATR_MULT * a[i]
        if SWING_WIDEN:
            if d > 0:
                lo = l[max(0, i - 5):i].min()
                stop_d = max(stop_d, o[i + 1] - (lo - 0.15 * a[i]))
            else:
                hi = h[max(0, i - 5):i].max()
                stop_d = max(stop_d, (hi + 0.15 * a[i]) - o[i + 1])
        stop_d = max(stop_d, 0.5 * a[i], stops_u)
        stop_d = min(stop_d, c[i] * 0.03)
        tp_d = TP_MULT * stop_d

        # ---- sizing (OpenTrade) ----
        risk_money = equity * RISK_PER_TRADE
        vol = risk_money / ((stop_d / tick) * tv)
        vol = math.floor(vol / VOL_STEP) * VOL_STEP
        vol = max(vol, MIN_LOT)
        if SCALE_AFTER_LOSS and consec > 0:
            vol = vol * max(SCALE_FACTOR ** consec, MIN_VOL_SCALE)
            vol = math.floor(vol / VOL_STEP) * VOL_STEP
            vol = max(vol, MIN_LOT)
        eff_risk = vol * (stop_d / tick) * tv

        # ---- fill (worst case) ----
        if d > 0:
            entry = o[i + 1] + spread / 2.0
            sl, tp = entry - stop_d, entry + tp_d
        else:
            entry = o[i + 1] - spread / 2.0
            sl, tp = entry + stop_d, entry - tp_d
        r = None
        j_end = min(i + 1 + MAX_HOLD_BARS, n)
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
            exit_p = c[j] - (spread / 2.0) * d
            r = d * (exit_p - entry) / stop_d
        r -= spread / stop_d

        # ---- bookkeeping ----
        equity += r * eff_risk
        consec = consec + 1 if r < 0 else 0
        if consec >= MAX_CONSEC_LOSS:
            paused_until_day = day          # rest of THIS server day
            consec = 0
        trades.append((int(times[i]), round(r, 3), round(eff_risk, 4), vol))
        curve.append((int(times[i]), round(equity, 2)))
        i = j + 1

    return equity, curve, trades


def stats_line(curve, trades, equity0):
    eq = [e for _, e in curve]
    peak, dd = equity0, 0.0
    for e in eq:
        peak = max(peak, e)
        dd = max(dd, peak - e)
    rs = [t[1] for t in trades]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x <= 0]
    gw, gl = sum(wins), sum(losses)
    return {
        "trades": len(rs),
        "wins": len(wins),
        "wr_pct": round(100 * len(wins) / len(rs), 1) if rs else 0.0,
        "pf": round(gw / gl, 2) if gl else None,
        "total_r": round(sum(rs), 2),
        "end_equity": round(eq[-1], 2) if eq else equity0,
        "max_dd_usd": round(dd, 2),
        "max_dd_pct": round(100 * dd / equity0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=30.0)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--mc", type=int, default=200, help="Monte-Carlo start dates")
    args = ap.parse_args()

    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"mt5 init failed: {mt5.last_error()}")
    try:
        rates = mt5.copy_rates_from_pos("Volatility 75 Index", mt5.TIMEFRAME_M15, 1, 40000)
        si = mt5.symbol_info("Volatility 75 Index")
    finally:
        mt5.shutdown()

    # primary window: the most recent `days` days (the live-equivalent test)
    n = len(rates["time"])
    last_pos = n - args.days * 96 - 2
    eq_end, curve, trades = sim_window(rates, si, args.equity, last_pos, args.days)
    st = stats_line(curve, trades, args.equity)

    print(f"== ${args.equity:.0f} account, V75, last {args.days} days "
          f"({datetime.fromtimestamp(int(rates['time'][last_pos]), tz=timezone.utc):%Y-%m-%d} "
          f"-> {datetime.fromtimestamp(int(rates['time'][-1]), tz=timezone.utc):%Y-%m-%d}) ==")
    print(f"trades={st['trades']}  WR={st['wr_pct']}%  PF={st['pf']}  "
          f"totalR={st['total_r']:+.1f}")
    print(f"equity: ${args.equity:.2f} -> ${st['end_equity']:.2f} "
          f"({100 * (st['end_equity'] / args.equity - 1):+.1f}%)  "
          f"maxDD ${st['max_dd_usd']:.2f} ({st['max_dd_pct']}%)")
    print("\nequity curve (per trade, every 5th shown):")
    for k, (ts, e) in enumerate(curve):
        if k % 5 == 0 or k == len(curve) - 1:
            print(f"  {datetime.fromtimestamp(ts, tz=timezone.utc):%m-%d %H:%M}  ${e:7.2f}")

    # Monte-Carlo over start dates: 30-day windows anywhere in the 40000 bars
    ends = []
    rng = random.Random(7)
    starts = rng.sample(range(150, last_pos - 1), min(args.mc, last_pos - 151))
    for s in starts:
        e, _, tr = sim_window(rates, si, args.equity, s, args.days)
        ends.append(e)
    ends = np.array(ends)
    mc = {
        "windows": len(ends),
        "median_end": round(float(np.median(ends)), 2),
        "pct_profitable": round(float((ends > args.equity).mean() * 100), 1),
        "p5": round(float(np.percentile(ends, 5)), 2),
        "p95": round(float(np.percentile(ends, 95)), 2),
        "worst": round(float(ends.min()), 2),
        "best": round(float(ends.max()), 2),
    }
    print(f"\nMonte-Carlo over {mc['windows']} random 30-day windows:")
    print(f"  median end ${mc['median_end']:.2f} | profitable windows {mc['pct_profitable']}%")
    print(f"  p5 ${mc['p5']:.2f} / p95 ${mc['p95']:.2f} | worst ${mc['worst']:.2f} / best ${mc['best']:.2f}")

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": "Volatility 75 Index", "equity0": args.equity,
        "window_days": args.days,
        "window": [int(rates["time"][last_pos]), int(rates["time"][-1])],
        "primary": st,
        "curve": curve,
        "trades": trades,
        "monte_carlo": mc,
    }
    (ART / "sim30d_v75.json").write_text(json.dumps(out, indent=1))
    print("\nartifact -> artifacts/sim30d_v75.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
