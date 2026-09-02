#!/usr/bin/env python3
"""Strategy-tester validation protocol (Pass A equivalent) on REAL broker bars:
Volatility 100 Index — does M5 entry frequency keep the band-fade edge vs M15?

Methodology (mirrors scripts/60day_analysis.py, which produced
artifacts/analysis_60day.json, plus two realism upgrades the protocol asks for):
  - sigma: stdev of the last 20 entry-TF log-returns, EMA-30 smoothed
  - expansion gate: s_now > 1.25 x sigma_ema
  - fade |z| >= z_entry vs SMA-20 (d = -sign(z))
  - geometry: stop = 0.10 x sigma_h, target = tgt x sigma_h, hold = 3600s
    (sigma_h rescales per timeframe via sqrt(hold_bars), exactly as the EA's
    band geometry scales with horizon)
  - cooldown 2 bars between trades

Realism upgrades vs the old 60-day sim:
  1. SPREAD CHARGED: every trade pays spread_in_r = spread_price / stop_price
     deducted from its R (this is the dominant friction at M5, where the stop
     is ~half as wide in sigma terms). Spread is the live bar-column mean,
     cross-checked against today's recorded ticks.
  2. SPREAD STRESS: the whole run repeats at 2x spread (protocol gate #6).

Pass gates (STRATEGY_TESTER_VALIDATION.md, per variant):
  trades >= 30 | PF >= 1.30 | expR >= +0.15 | maxDD <= 12R | TIME-exits <= 40%
  stress: PF >= 1.10 at 2x spread

Usage:
    .venv/Scripts/python.exe scripts/m5_vs_m15_validation.py [--bars 60000]
Writes artifacts/m5_vs_m15_vol100.json and prints a verdict table.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5  # shared loader: terminal + .npy cache

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

SYMBOL = "Volatility 100 Index"
POINT = 0.01  # price value of one point for the spread column
GATE_RATIO = 1.25
SIGMA_EMA_LEN = 30
STOP_MULT = 0.10
HOLD_SEC = 3600
WARMUP = 60
COOLDOWN = 2
# Protocol sweep: z x target grid (analysis_60day cells), per timeframe.
GRID = [(1.0, 1.2), (1.4, 1.2), (2.0, 1.2), (1.0, 0.8), (1.4, 0.8), (2.0, 0.8)]


def aggregate(bars, factor: int):
    """Clock-anchored aggregation into a higher timeframe (M5 -> M15 = x3).

    Buckets are keyed on epoch // (factor*300) so the partition is INVARIANT
    to where the data window starts/ends. A position-based partition silently
    re-groups every bucket when the terminal window slides by one bar, which
    showed up as PF swinging 1.32 -> 0.85 between two runs minutes apart.
    The last (still-forming) bar of the source series is dropped first so the
    result depends only on CLOSED bars.
    """
    sec = factor * 300
    buckets = {}
    order = []
    for b in list(bars)[:-1]:   # drop forming bar
        key = int(b["epoch"] // sec)
        if key not in buckets:
            buckets[key] = {"epoch": key * sec, "open": b["open"],
                            "high": b["high"], "low": b["low"], "close": b["close"]}
            order.append(key)
        else:
            c = buckets[key]
            c["high"] = max(c["high"], b["high"])
            c["low"] = min(c["low"], b["low"])
            c["close"] = b["close"]
    # discard the final (possibly partial) bucket so every bucket is complete
    if order:
        order = order[:-1]
    return [buckets[k] for k in order]


def simulate(bars, z_entry: float, tgt_mult: float, spread_price: float) -> dict:
    n = len(bars)
    closes = [b["close"] for b in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    sigma_ema = None
    trades, reasons, stop_widths = [], [], []
    spread_costs = []
    i, cooldown = WARMUP, 0

    while i < n - 1:
        seg = rets[max(0, i - 20): i]
        if len(seg) >= 15:
            s_now = statistics.stdev(seg)
            a = 2.0 / (SIGMA_EMA_LEN + 1)
            sigma_ema = s_now if sigma_ema is None else a * s_now + (1 - a) * sigma_ema
            if s_now > GATE_RATIO * sigma_ema and cooldown <= 0:
                sma = sum(closes[i - 19: i + 1]) / 20.0
                if sma > 0 and closes[i] > 0:
                    z = math.log(closes[i] / sma) / s_now
                    d = -1 if z >= z_entry else (1 if z <= -z_entry else 0)
                    if d != 0:
                        bar_sec = max(1, int(bars[1]["epoch"] - bars[0]["epoch"]))
                        hb = max(1, round(HOLD_SEC / bar_sec))
                        sig_h = s_now * math.sqrt(hb)
                        stop_f = STOP_MULT * sig_h
                        tgt_f = tgt_mult * sig_h
                        entry = closes[i]
                        if stop_f <= 0:
                            cooldown = COOLDOWN
                            i += 1
                            continue
                        sl = entry - d * stop_f * entry
                        tp = entry + d * tgt_f * entry
                        stop_widths.append(stop_f)
                        out_r, reason = None, "TIME"
                        for j in range(i + 1, min(n, i + 1 + hb + 2)):
                            hit_sl = bars[j]["low"] <= sl if d > 0 else bars[j]["high"] >= sl
                            hit_tp = bars[j]["high"] >= tp if d > 0 else bars[j]["low"] <= tp
                            if hit_sl:
                                out_r, reason = -1.0, "STOP"
                                break
                            if hit_tp:
                                out_r, reason = tgt_f / stop_f, "TARGET"
                                break
                        if out_r is None:
                            jx = min(n - 1, i + hb)
                            out_r = d * (closes[jx] - entry) / entry / stop_f
                        # realism: pay the spread on entry+exit, in R units
                        sprd_r = (spread_price / entry) / stop_f
                        out_r -= sprd_r
                        spread_costs.append(sprd_r)
                        trades.append(out_r)
                        reasons.append(reason)
                        cooldown = COOLDOWN
                        i += 1
                        continue
        cooldown = max(0, cooldown - 1)
        i += 1

    if not trades:
        return {"trades": 0, "pass": False, "verdict": "NO TRADES"}

    wins = [t for t in trades if t > 0]
    losses = [-t for t in trades if t < 0]
    gw, gl = sum(wins), sum(losses)
    dd = peak = cum = 0.0
    for t in trades:
        cum += t
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    rc = {k: reasons.count(k) for k in ("TARGET", "STOP", "TIME")}
    days_span = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400.0
    pf = gw / gl if gl > 0 else 99.0
    exp_r = sum(trades) / len(trades)
    time_share = rc["TIME"] / len(trades)
    fails = []
    if len(trades) < 30:
        fails.append("sample<30")
    if pf < 1.30:
        fails.append("PF<1.30")
    if exp_r < 0.15:
        fails.append("expR<0.15")
    if dd > 12.0:
        fails.append("DD>12R")
    if time_share > 0.40:
        fails.append("TIME>40%")
    return {
        "trades": len(trades),
        "per_day": round(len(trades) / max(days_span, 1), 2),
        "wr": round(100 * len(wins) / len(trades), 1),
        "pf": round(pf, 2),
        "exp_r": round(exp_r, 3),
        "max_dd_r": round(dd, 2),
        "exits": rc,
        "avg_stop_pct": round(100 * sum(stop_widths) / len(stop_widths), 4),
        "time_share": round(time_share, 3),
        "spread_cost_r": round(statistics.mean(spread_costs), 3) if spread_costs else 0.0,
        "exp_r_gross": round(exp_r + (statistics.mean(spread_costs) if spread_costs else 0.0), 3),
        "pass": not fails,
        "verdict": "PASS" if not fails else "FAIL(" + ",".join(fails) + ")",
    }


def main() -> int:
    global SYMBOL, POINT
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=60000)
    ap.add_argument("--symbol", type=str, default=SYMBOL)
    ap.add_argument("--point", type=float, default=0.01)
    args = ap.parse_args()
    SYMBOL = args.symbol
    POINT = args.point

    m5 = load_m5(SYMBOL, timeframe="M5", bars=args.bars)
    n5 = len(m5)
    days = (m5[n5 - 1]["epoch"] - m5[0]["epoch"]) / 86400.0
    print(f"loaded {n5} M5 bars, {days:.0f} days "
          f"({datetime.fromtimestamp(m5[0]['epoch'], timezone.utc):%Y-%m-%d} -> "
          f"{datetime.fromtimestamp(m5[n5-1]['epoch'], timezone.utc):%Y-%m-%d})")

    spreads = [b.get("spread", 0.0) for b in m5 if b.get("spread")]
    sp_pts = statistics.median(spreads) if spreads else 0.0
    spread_price = sp_pts * POINT  # point size per symbol
    print(f"median bar spread: {sp_pts:.1f} pts = {spread_price:.2f} price units")

    m15 = aggregate(list(iter(m5)), 3)
    print(f"aggregated {len(m15)} M15 bars")

    results = {}
    for tf_name, bars in (("M5", list(iter(m5))), ("M15", m15)):
        for z, tgt in GRID:
            base = simulate(bars, z, tgt, spread_price)
            stress = simulate(bars, z, tgt, spread_price * 2)
            stress_ok = stress["trades"] >= 30 and stress.get("pf", 0) >= 1.10
            base["stress_pf"] = stress.get("pf")
            base["stress_pass"] = stress_ok
            if base["pass"] and not stress_ok:
                base["pass"] = False
                base["verdict"] = "FAIL(stress)"
            results[f"{tf_name}_z{z}_tgt{tgt}"] = base
            print(f"{tf_name} z={z} tgt={tgt}: {base['verdict']} | "
                  f"trades={base['trades']} per_day={base.get('per_day')} "
                  f"pf={base.get('pf')} expR={base.get('exp_r')} "
                  f"dd={base.get('max_dd_r')}R stressPF={base.get('stress_pf')}")

    best = {}
    for tf_name in ("M5", "M15"):
        cands = [(k, v) for k, v in results.items() if k.startswith(tf_name + "_")]
        passed = [(k, v) for k, v in cands if v["pass"]]
        pool = passed if passed else cands
        best[tf_name] = max(pool, key=lambda kv: kv[1].get("exp_r", -9))[0]

    m5b, m15b = results[best["M5"]], results[best["M15"]]
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL,
        "bars_m5": n5,
        "days": round(days, 1),
        "spread_points": sp_pts,
        "grid": GRID,
        "results": results,
        "best_cell": best,
        "comparison": {
            "m5": m5b, "m15": m15b,
            "freq_ratio": round(m5b.get("per_day", 0) / max(m15b.get("per_day", 1e-9), 1e-9), 2),
        },
    }
    ART.mkdir(exist_ok=True)
    tag = SYMBOL.lower().replace(" ", "_").replace("(", "").replace(")", "")
    out = ART / f"m5_vs_m15_{tag}.json"
    out.write_text(json.dumps(summary, indent=1))
    print(f"\nartifact -> {out}")
    print(f"BEST: M5={best['M5']} vs M15={best['M15']}")
    print(f"  M5 : trades={m5b['trades']} per_day={m5b.get('per_day')} pf={m5b.get('pf')} expR={m5b.get('exp_r')} -> {m5b['verdict']}")
    print(f"  M15: trades={m15b['trades']} per_day={m15b.get('per_day')} pf={m15b.get('pf')} expR={m15b.get('exp_r')} -> {m15b['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
