#!/usr/bin/env python3
"""Forward-split validation of the EA's standard M15 engine on Volatility symbols.

Simulates the EA's GenerateSignal() confluence logic EA-faithfully on entry-TF
bars, then splits history into in-sample (IS, first 70%) and out-of-sample
(OOS, last 30%). The OOS block is the verdict: it was never used to choose
anything, so it is the closest proxy to a forward test available offline.

EA-faithful elements (mirrors MitemshubAI.mq5 v26.20):
  - regime classify via EMA20/50/100 slope; NO_TRADE regime blocks entries
  - legs: MOM (fast EMA impulse), PB (pullback-to-EMA), MR (far-from-EMA snap),
          BF (z-score band fade, z >= 2.0)
  - momentum demotion: a lone MOM leg is discarded ("mom-demoted-lone-candle")
  - confluence: >= 2 legs same direction, combined score >= InpMinScore (3),
                regime alignment bonus +2
  - geometry: SL 1.5xATR(14), TP 3.0xATR (minRR 2.0), hold cap 16 bars
  - worst-case intrabar fills: if SL and TP both touched in one bar, SL wins
  - spread: charged once per round trip in R (spread / stop_distance)

Gates (applied to OOS): trades >= 30 | PF >= 1.15 | expR > 0 | maxDD <= 15R

Usage:
  .venv/Scripts/python.exe scripts/fwd_split_backtest.py --symbol "Volatility 75 Index"
  .venv/Scripts/python.exe scripts/fwd_split_backtest.py --symbol "Volatility 100 Index"
Writes artifacts/fwd_split_<symbol>.json
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

MIN_SCORE = 3
REGIME_BONUS = 2
SL_ATR, TP_ATR = 1.5, 3.0
MIN_RR = 2.0
HOLD_BARS = 16
Z_ENTRY = 2.0
Z_WIN = 20          # bars in the band window
Z_SIGMA = 20        # stdev window
EMA_F, EMA_M, EMA_S = 20, 50, 100
IS_FRAC = 0.70


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr14(h, l, c):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return ema(tr, 14)


def regime(e20, e50, e100):
    """0=NONE(gate open but no bonus) 1=BULL 2=BEAR 3=NO_TRADE(chop)"""
    up = ((e20 > e50) & (e50 > e100)) & (e20 > np.roll(e20, 1))
    dn = ((e20 < e50) & (e50 < e100)) & (e20 < np.roll(e20, 1))
    sep_ok = (np.abs(e20 - e50) / np.maximum(e50 * 1e-9, np.abs(e50))) > 0
    chop = (~up & ~dn) & (np.abs(e20 - e100) / np.maximum(e100, 1e-9) < 0.0015)
    r = np.zeros(len(e20), dtype=np.int8)
    r[up & sep_ok] = 1
    r[dn & sep_ok] = 2
    r[chop] = 3
    return r


def signals(o, h, l, c):
    """Per-bar EA-faithful confluence decision -> (dir, legs_list) or (0, [])."""
    n = len(c)
    e20, e50, e100 = ema(c, EMA_F), ema(c, EMA_M), ema(c, EMA_S)
    reg = regime(e20, e50, e100)
    a = atr14(h, l, c)
    a = np.concatenate(([a[0]], a))
    # z-score of close vs rolling mean/std
    w = Z_WIN
    roll_mean = np.convolve(c, np.ones(w) / w, mode="valid")
    roll_std = np.array([c[i - w + 1:i + 1].std() for i in range(w - 1, n)])
    z = np.concatenate((np.zeros(w - 1), (c[w - 1:] - roll_mean) / np.maximum(roll_std, 1e-12)))
    z = np.concatenate((np.zeros(1), z))[:-1]

    out = []
    for i in range(EMA_S + 2, n - 1):
        if reg[i] == 3 or not (a[i] > 0):
            out.append(0); continue
        legs_b, legs_s = [], []
        sb = ss = 0.0
        # MOM: impulse of the fast EMA against/with recent drift
        mom = e20[i] - e20[i - 2]
        if abs(mom) > 0.25 * a[i]:
            (legs_b if mom > 0 else legs_s).append("MOM")
            sb += 2.2 if mom > 0 else 0
            ss += 2.2 if mom < 0 else 0
        # PB: pullback to mid EMA inside an aligned regime
        if reg[i] == 1 and l[i] <= e20[i] * 1.0005 and c[i] > e50[i]:
            legs_b.append("PB"); sb += 2.5
        if reg[i] == 2 and h[i] >= e20[i] * 0.9995 and c[i] < e50[i]:
            legs_s.append("PB"); ss += 2.5
        # MR: stretch beyond 2 ATR from mean, snap back
        if abs(c[i] - e50[i]) > 2.0 * a[i]:
            if c[i] < e50[i]: legs_b.append("MR"); sb += 2.0
            else:             legs_s.append("MR"); ss += 2.0
        # BF: z-band fade
        if z[i] <= -Z_ENTRY: legs_b.append("BF"); sb += 4.2
        if z[i] >=  Z_ENTRY: legs_s.append("BF"); ss += 4.2
        # momentum demotion (lone MOM leg is dropped, as the EA does)
        if legs_b == ["MOM"]: legs_b, sb = [], 0.0
        if legs_s == ["MOM"]: legs_s, ss = [], 0.0
        if reg[i] == 1: sb += REGIME_BONUS
        if reg[i] == 2: ss += REGIME_BONUS
        d = 0
        if len(legs_b) >= 2 and sb >= MIN_SCORE and sb > ss: d = 1
        elif len(legs_s) >= 2 and ss >= MIN_SCORE and ss > sb: d = -1
        out.append(d if d == 0 else d)
    out = [0] * (EMA_S + 2) + out[: n - (EMA_S + 2)]
    return np.array(out, dtype=np.int8), a, reg


def simulate(o, h, l, c, sig, a, spread_units):
    """Bar-loop trade sim: worst-case fills, per-bar spread charged per round trip in R."""
    trades = []  # (bar_index, r)
    i = 0
    n = len(c)
    while i < n - 1:
        d = sig[i]
        if d == 0 or a[i] <= 0:
            i += 1; continue
        stop_d = SL_ATR * a[i]
        tp_d = TP_ATR * a[i]
        if tp_d / stop_d < MIN_RR:
            i += 1; continue
        if d > 0:
            entry = o[i + 1] + spread_units[i + 1] / 2.0
            sl, tp = entry - stop_d, entry + tp_d
        else:
            entry = o[i + 1] - spread_units[i + 1] / 2.0
            sl, tp = entry + stop_d, entry - tp_d
        r = None
        for j in range(i + 1, min(i + 1 + HOLD_BARS, n)):
            if d > 0:
                if l[j] <= sl: r = -1.0; break          # worst case first
                if h[j] >= tp: r = tp_d / stop_d; break
            else:
                if h[j] >= sl: r = -1.0; break
                if l[j] <= tp: r = tp_d / stop_d; break
        if r is None:
            j = min(i + HOLD_BARS, n - 1)
            exit_p = c[j] - spread_units[j] / 2.0 * d
            r = d * (exit_p - entry) / stop_d
        r -= spread_units[i + 1] / stop_d               # round-trip cost in R
        trades.append((i, r))
        i = j + 1
    return trades


def stats(trades):
    if not trades:
        return {"trades": 0}
    rs = [t[1] for t in trades]
    wins = [x for x in rs if x > 0]; losses = [-x for x in rs if x <= 0]
    gw, gl = sum(wins), sum(losses)
    cum = peak = dd = 0.0
    for x in rs:
        cum += x; peak = max(peak, cum); dd = max(dd, peak - cum)
    return {
        "trades": len(rs),
        "wr": round(100 * len(wins) / len(rs), 1),
        "pf": round(gw / gl, 2) if gl > 0 else 99.0,
        "exp_r": round(sum(rs) / len(rs), 3),
        "total_r": round(sum(rs), 2),
        "max_dd_r": round(dd, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--bars", default="M15")
    ap.add_argument("--count", type=int, default=40000)
    ap.add_argument("--csv", default=None,
                    help="bars CSV from fetch_market_data (ts,open,high,low,close,tick_volume,spread); "
                         "uses the per-bar broker spread column instead of a live snapshot")
    ap.add_argument("--point", type=float, default=0.01, help="point size for the CSV spread column")
    args = ap.parse_args()

    if args.csv:
        import csv as _csv
        with open(args.csv, newline="") as f:
            rd = _csv.reader(f)
            col = {k: i for i, k in enumerate(next(rd))}
            data = list(rd)
        o, h, l, c = (np.array([float(r[col[k]]) for r in data]) for k in ("open", "high", "low", "close"))
        times = np.array([int(float(r[col["ts"]])) for r in data], dtype=np.int64)
        # per-bar spread in price units: the honest cost channel (spread scales with price)
        spread_arr = np.array([float(r[col["spread"]]) for r in data]) * args.point
        si = None
    else:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise RuntimeError(f"mt5 init failed: {mt5.last_error()}")
        try:
            tf = getattr(mt5, f"TIMEFRAME_{args.bars.upper()}")
            rates = mt5.copy_rates_from_pos(args.symbol, tf, 1, args.count)
            si = mt5.symbol_info(args.symbol)
        finally:
            mt5.shutdown()
        if rates is None or len(rates) < 2000:
            raise RuntimeError("not enough history")
        o, h, l, c = (np.array(rates[k], dtype=float) for k in ("open", "high", "low", "close"))
        times = np.array(rates["time"], dtype=np.int64)
        spread_arr = None
    if len(c) < 2000:
        raise RuntimeError("not enough history")
    if spread_arr is None:
        spread_arr = np.full(len(c), si.spread * si.point)
    spread_units = float(np.median(spread_arr))

    sig, a, _ = signals(o, h, l, c)
    trades = simulate(o, h, l, c, sig, a, spread_arr)
    if not trades:
        print("no trades at all"); return 1

    split = int(len(trades) * IS_FRAC)
    is_tr, oos_tr = trades[:split], trades[split:]
    is_s, oos_s = stats(is_tr), stats(oos_tr)

    # monthly table over all trades
    monthly = {}
    for idx, r in trades:
        m = datetime.utcfromtimestamp(int(times[idx])).strftime("%Y-%m")
        monthly.setdefault(m, []).append(r)
    monthly = {m: {"trades": len(v), "net_r": round(sum(v), 2)} for m, v in sorted(monthly.items())}

    fails = []
    if oos_s.get("trades", 0) < 30: fails.append("OOS_trades<30")
    if oos_s.get("pf", 0) < 1.15: fails.append("OOS_PF<1.15")
    if oos_s.get("exp_r", -1) <= 0: fails.append("OOS_expR<=0")
    if oos_s.get("max_dd_r", 99) > 15: fails.append("OOS_DD>15R")
    verdict = "PASS" if not fails else "FAIL(" + ",".join(fails) + ")"

    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol, "bars": args.bars, "bars_used": len(c),
        "spread_units_median": round(spread_units, 2),
        "spread_units_p90": round(float(np.percentile(spread_arr, 90)), 2),
        "source": args.csv or "mt5_live",
        "split_trade": split, "total_trades": len(trades),
        "in_sample": is_s, "out_of_sample": oos_s,
        "monthly": monthly, "gates": fails or "all passed", "verdict": verdict,
    }
    tag = args.symbol.lower().replace(" ", "_").replace("(", "").replace(")", "")
    (ART / f"fwd_split_{tag}.json").write_text(json.dumps(out, indent=1))

    print(f"== {args.symbol} {args.bars} | spread {spread_units:.2f} units ==")
    print(f"IS : {is_s}")
    print(f"OOS: {oos_s}")
    print("monthly:", {m: v["net_r"] for m, v in monthly.items()})
    print("VERDICT:", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
