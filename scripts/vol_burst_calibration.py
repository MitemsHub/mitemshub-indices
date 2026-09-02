#!/usr/bin/env python3
"""Historical VB-BURST calibration on real broker tick history (no waiting).

Pulls N days of Volatility 100 ticks via mt5.copy_ticks_range (COPY_TICKS_INFO),
measures the tick-move distribution to pick threshold candidates, then replays
the EXACT v26.17 CVolBurstFade state machine (velocity arm -> peak extend ->
retrace window -> SL/TP in ATR(M5) units -> timeout/cooldown -> consume-once)
over the full history with spread charged on entry+exit.

Gates (same family as the strategy-tester protocol):
  trades >= 30 | PF >= 1.30 | expR >= +0.15 | maxDD <= 12R

Usage:
    .venv/Scripts/python.exe scripts/vol_burst_calibration.py [--days 30]
Writes artifacts/vol_burst_calibration_<SYMBOL>.json
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

# v26.17 module defaults (the state machine being calibrated)
LOOK_TICKS = 8
RETR_MIN, RETR_MAX = 0.30, 0.60
TIMEOUT_S = 600
COOLDOWN_S = 300
SL_ATR, TP_ATR = 0.3, 3.2
MIN_RR = 2.0
ATR_PERIOD = 14


def fetch_ticks(symbol: str, days: int):
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"mt5 init failed: {mt5.last_error()}")
    try:
        t_to = datetime.now()
        t_from = datetime.fromtimestamp(datetime.now().timestamp() - days * 86400)
        raw = mt5.copy_ticks_range(symbol, t_from, t_to, mt5.COPY_TICKS_INFO)
        if raw is None or len(raw) == 0:
            raise RuntimeError("no ticks returned")
        t = np.sort(raw, order="time")
        # dedupe by (time, bid)
        keep = np.ones(len(t), dtype=bool)
        keep[1:] = (t["time"][1:] != t["time"][:-1]) | (t["bid"][1:] != t["bid"][:-1])
        t = t[keep]
        return t["time"].astype(np.int64), t["bid"].astype(float), t["ask"].astype(float)
    finally:
        mt5.shutdown()


def build_m5(times: np.ndarray, bids: np.ndarray):
    """Aggregate ticks to closed M5 bars -> (epochs, high, low, close) arrays."""
    bucket = times // 300
    starts = np.flatnonzero(np.diff(bucket, prepend=bucket[0] - 1))
    ends = np.append(starts[1:], len(times))
    epochs, high, low, close = [], [], [], []
    for s, e in zip(starts[:-1], ends[:-1]):   # drop last (forming) bucket
        seg = bids[s:e]
        epochs.append(int(bucket[s] * 300))
        high.append(seg.max()); low.append(seg.min()); close.append(seg[-1])
    return (np.array(epochs, dtype=np.int64), np.array(high), np.array(low), np.array(close))


def atr_series(high, low, close, period=ATR_PERIOD):
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr = np.empty(len(tr)); w = None
    alpha = 2.0 / (period + 1)
    for i, x in enumerate(tr):
        w = x if w is None else alpha * x + (1 - alpha) * w
        atr[i] = w
    return np.concatenate(([atr[0]], atr))   # index aligned to times[:-1] bars


def replay(times, bids, asks, vel_pts: float, atr_by_bucket: dict,
           sl_atr: float = SL_ATR, mode: str = "fade") -> dict:
    """The v26.17 CVolBurstFade.OnTick state machine, runnable over millions of
    ticks. Burst detection and the pending lifecycle are mode-independent; only
    the traded side differs:
      fade: trade AGAINST the burst (SELL up-bursts, BUY down-bursts) — v26.17
      join: trade WITH the burst    (BUY up-bursts,  SELL down-bursts)
    Spread is charged by filling entries at bid (sell) / ask (buy) and requiring
    the OPPOSITE quote to hit SL/TP (sell: ask>=SL hit, bid<=TP hit; mirrored)."""
    n = len(times)
    _ok = asks > 0
    spread = float(np.median(asks[_ok] - bids[_ok])) if np.any(_ok) else 0.0
    trades, reasons = [], []
    state = 0; burst_dir = 0; pre = peak = 0.0; t0 = 0; last_fire = -10**9
    i = LOOK_TICKS
    while i < n:
        b = bids[i]; now = int(times[i])
        if state == 0:
            vel = b - bids[i - LOOK_TICKS]
            if abs(vel) >= vel_pts and (now - last_fire) >= COOLDOWN_S:
                atr = atr_by_bucket.get(times[i] // 300, 0.0)
                if atr > 0:
                    state = 1; burst_dir = 1 if vel > 0 else -1
                    pre = bids[i - LOOK_TICKS]; peak = b; t0 = now
            i += 1
            continue
        # pending burst: peak extends WITH the burst; retrace measured AGAINST it
        if burst_dir > 0:
            if b > peak: peak = b
            rng = peak - pre
            retrace = (peak - b) / max(rng, 1e-9)
            gone = b <= pre
        else:
            if b < peak: peak = b
            rng = pre - peak
            retrace = (b - peak) / max(rng, 1e-9)
            gone = b >= pre
        if rng <= 0 or gone or now - t0 > TIMEOUT_S:
            state = 0; i += 1; continue
        if retrace < RETR_MIN or retrace > RETR_MAX:
            i += 1; continue
        atr = atr_by_bucket.get(times[i] // 300, 0.0)
        if atr <= 0: i += 1; continue
        stop_d = sl_atr * atr; tp_d = TP_ATR * atr
        if tp_d <= MIN_RR * stop_d:
            state = 0; i += 1; continue
        side = burst_dir if mode == "join" else -burst_dir
        if side < 0:
            # SELL: fill at bid; stop judged on ask, target judged on bid
            entry = b; sl = entry + stop_d; tp = entry - tp_d
            j, out_r, reason = i, None, "TIME"
            while j < n and int(times[j]) - now <= TIMEOUT_S * 4:
                if asks[j] >= sl: out_r, reason = -1.0, "STOP"; break
                if bids[j] <= tp: out_r, reason = tp_d / stop_d, "TARGET"; break
                j += 1
            if out_r is None:
                out_r = (entry - bids[min(n - 1, j)]) / stop_d
        else:
            # BUY: fill at ask; stop judged on bid, target judged on ask
            entry = asks[i]; sl = entry - stop_d; tp = entry + tp_d
            j, out_r, reason = i, None, "TIME"
            while j < n and int(times[j]) - now <= TIMEOUT_S * 4:
                if bids[j] <= sl: out_r, reason = -1.0, "STOP"; break
                if asks[j] >= tp: out_r, reason = tp_d / stop_d, "TARGET"; break
                j += 1
            if out_r is None:
                out_r = (asks[min(n - 1, j)] - entry) / stop_d
        out_r -= spread / stop_d            # pay the spread once per round trip
        trades.append(out_r); reasons.append(reason)
        last_fire = now; state = 0
        i = j + 1                            # consume; resume after exit

    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t > 0]; losses = [-t for t in trades if t < 0]
    gw, gl = sum(wins), sum(losses)
    cum = peak_r = dd = 0.0
    for t in trades:
        cum += t; peak_r = max(peak_r, cum); dd = max(dd, peak_r - cum)
    rc = {k: reasons.count(k) for k in ("TARGET", "STOP", "TIME")}
    days = (times[-1] - times[0]) / 86400
    pf = gw / gl if gl > 0 else 99.0
    exp_r = sum(trades) / len(trades)
    fails = []
    if len(trades) < 30: fails.append("sample<30")
    if pf < 1.30: fails.append("PF<1.30")
    if exp_r < 0.15: fails.append("expR<0.15")
    if dd > 12.0: fails.append("DD>12R")
    return {
        "trades": len(trades), "per_day": round(len(trades) / max(days, 1), 2),
        "wr": round(100 * len(wins) / len(trades), 1),
        "pf": round(pf, 2), "exp_r": round(exp_r, 3), "max_dd_r": round(dd, 2),
        "exits": rc,        "spread_paid_r": round(spread / (sl_atr * 1.0), 3),
        "pass": not fails, "verdict": "PASS" if not fails else "FAIL(" + ",".join(fails) + ")",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="Volatility 100 Index")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--mode", choices=("fade", "join"), default="fade",
                    help="trade against (fade) or with (join) the burst")
    ap.add_argument("--sl-atr", type=float, default=SL_ATR,
                    help="stop distance in ATR units (default 0.3 = v26.17)")
    ap.add_argument("--vel", default=None,
                    help="comma-separated velocity thresholds; default = data percentiles")
    ap.add_argument("--sweep", action="store_true",
                    help="grid over mode x sl-atr x threshold candidates")
    args = ap.parse_args()

    print(f"fetching {args.days}d of {args.symbol} ticks ...")
    times, bids, asks = fetch_ticks(args.symbol, args.days)
    n = len(times)
    span_d = (times[-1] - times[0]) / 86400
    print(f"{n:,} ticks, {span_d:.1f} days")

    # coverage: worst gap
    gaps = np.diff(times)
    big = gaps[gaps > 600]
    print(f"gap check: {len(big)} gaps >10min; worst {int(gaps.max())}s")

    # tick-move distribution -> threshold candidates
    jumps = bids[LOOK_TICKS:] - bids[:-LOOK_TICKS]
    a = np.abs(jumps)
    qs = {p: float(np.percentile(a, p)) for p in (99, 99.5, 99.9, 99.95, 99.99)}
    print(f"|{LOOK_TICKS}-tick move| percentiles: " +
          ", ".join(f"p{p}={v:.2f}" for p, v in qs.items()))

    epochs, hi, lo, cl = build_m5(times, bids)
    atr = atr_series(hi, lo, cl)
    atr_by_bucket = {int(e // 300): float(v) for e, v in zip(epochs, atr)}
    print(f"{len(epochs):,} M5 bars rebuilt; median ATR={np.median(atr):.2f} units; "
          f"median spread={np.median(asks[asks>0]-bids):.2f}")

    # candidate thresholds: explicit --vel, else data-driven percentiles + default
    if args.vel:
        cands = [float(x) for x in args.vel.split(",")]
    else:
        cands = sorted({round(qs[99], 2), round(qs[99.5], 2), round(qs[99.9], 2),
                        round(qs[99.95], 2), round(qs[99.99], 2), 4.0})
    grid = ([(m, s) for m in ("fade", "join") for s in (0.3, 0.75, 1.0)]
            if args.sweep else [(args.mode, args.sl_atr)])
    results = {}
    for m, s in grid:
        for v in cands:
            r = replay(times, bids, asks, v, atr_by_bucket, sl_atr=s, mode=m)
            key = f"{m}|sl{s}|vel{v:g}"
            results[key] = r
            print(f"{key:26s}: {r.get('verdict','-'):30s} trades={r.get('trades'):4d} "
                  f"per_day={r.get('per_day')} pf={r.get('pf')} expR={r.get('exp_r')} "
                  f"dd={r.get('max_dd_r')}R exits={r.get('exits')}")

    passed = {k: v for k, v in results.items() if v.get("pass")}
    best = None
    if passed:
        best = max(passed.items(), key=lambda kv: kv[1]["exp_r"])
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol, "days": span_d, "ticks": n,
        "jump_percentiles": {str(k): v for k, v in qs.items()},
        "median_atr_m5": float(np.median(atr)),
        "candidates": results, "best": {"cell": best[0], **best[1]} if best else None,
        "recommendation": (f"Enable InpVolBurstFade with {best[0]}" if best else
                           "NO PASSING CELL — keep InpVolBurstFade=false"),
    }
    tag = args.symbol.lower().replace(" ", "_").replace("(", "").replace(")", "")
    (ART / f"vol_burst_calibration_{tag}.json").write_text(json.dumps(out, indent=1))
    print("\nrecommendation:", out["recommendation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
