#!/usr/bin/env python3
"""Backtest the EA v22 band-fade leg on REAL broker candle history.

This is the EA-faithful pipeline (identical math to MitemshubAI.mq5):
  per-bar sigma   = sample stdev of last-20 log closes
  baseline        = EMA(30) of that sigma (updated BEFORE the gate compares)
  expansion gate  = sigma_now > InpBandVolExtRatio * baseline
  entry           = |z_dev| >= z_entry, z = ln(close/sma20)/sigma_now -> fade
  geometry        = stop 0.10*sigma_h, target tgt*sigma_h, sigma_h=sigma*sqrt(hb)
  fills           = conservative (SL assumed hit before TP within a bar)
  management      = one position, cooldown after close, raw edge (no halts)

Input: artifacts/real_<symbol>_M5.csv written by scripts/mt5_probe.py.
Usage: python scripts/backtest_real_history.py [--tf M15] [--zlist 1.0,1.4,2.0]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

SYMBOLS = {
    # venue name: (target_sigma_mult, tuned z-entry list per deployed .set)
    "Volatility 75 Index": (1.20, [1.0, 1.4, 2.0]),
    "Volatility 100 Index": (0.80, [1.0, 1.4, 2.0]),
    "Volatility 75 (1s) Index": (1.20, [1.0, 1.4, 2.0]),
    # VOL10/25/50 parallel-profile tunes (UNVALIDATED -> being validated here)
    "Volatility 10 Index": (0.60, [2.3, 2.0]),
    "Volatility 25 Index": (0.70, [2.2, 2.0]),
    "Volatility 50 Index": (0.80, [2.0]),
}
GATE_RATIO, SIGMA_EMA_LEN, STOP_MULT, HOLD_SEC, WARMUP, COOLDOWN = 1.25, 30, 0.10, 3600, 60, 2


def load_m5(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({k: float(r[k]) for k in
                         ("epoch", "open", "high", "low", "close")})
    return rows


def aggregate(m5, factor):
    """Combine factor M5 bars into higher-TF OHLC bars."""
    out = []
    for i in range(0, len(m5) - factor + 1, factor):
        chunk = m5[i:i + factor]
        out.append({"epoch": chunk[0]["epoch"], "open": chunk[0]["open"],
                    "high": max(c["high"] for c in chunk),
                    "low": min(c["low"] for c in chunk),
                    "close": chunk[-1]["close"]})
    return out


def simulate(bars, z_entry, tgt_mult):
    n = len(bars)
    closes = [b["close"] for b in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    sigma_ema, trades, reasons, stop_widths = None, [], [], []
    i, cooldown = WARMUP, 0

    while i < n - 1:
        seg = rets[max(0, i - 19): i]
        if len(seg) >= 15 and i >= WARMUP:
            s_now = statistics.stdev(seg)
            a = 2.0 / (SIGMA_EMA_LEN + 1)
            sigma_ema = s_now if sigma_ema is None else a * s_now + (1 - a) * sigma_ema
            if s_now > GATE_RATIO * sigma_ema and cooldown <= 0:
                sma = sum(closes[i - 19: i + 1]) / 20.0
                if sma > 0 and closes[i] > 0:
                    z = math.log(closes[i] / sma) / s_now
                    d = -1 if z >= z_entry else (1 if z <= -z_entry else 0)
                    if d != 0:
                        hb = max(1, round(HOLD_SEC / ((bars[1]["epoch"] - bars[0]["epoch"]))))
                        sig_h = s_now * math.sqrt(hb)
                        stop_f, tgt_f = STOP_MULT * sig_h, tgt_mult * sig_h
                        entry = closes[i]
                        sl = entry - d * stop_f * entry
                        tp = entry + d * tgt_f * entry
                        stop_widths.append(stop_f)   # fraction of price
                        out_r, reason = None, "TIME"
                        for j in range(i + 1, min(n, i + 1 + hb + 2)):
                            hit_sl = bars[j]["low"] <= sl if d > 0 else bars[j]["high"] >= sl
                            hit_tp = bars[j]["high"] >= tp if d > 0 else bars[j]["low"] <= tp
                            if hit_sl:            # conservative: SL before TP
                                out_r, reason = -1.0, "STOP"
                                break
                            if hit_tp:
                                out_r, reason = tgt_f / stop_f, "TARGET"
                                break
                        if out_r is None:
                            jx = min(n - 1, i + hb)
                            out_r = d * (closes[jx] - entry) / entry / stop_f
                        trades.append(out_r)
                        reasons.append(reason)
                        cooldown = COOLDOWN
                        i += 1
                        continue
        cooldown = max(0, cooldown - 1)
        i += 1

    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t > 0]
    losses = [-t for t in trades if t < 0]
    gw, gl = sum(wins), sum(losses)
    dd = peak = cum = 0.0
    for t in trades:
        cum += t
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    rc = {k: reasons.count(k) for k in ("TARGET", "STOP", "TIME")}
    days = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400.0
    pf = gw / gl if gl > 0 else 99.0
    exp_r = sum(trades) / len(trades)
    time_share = rc["TIME"] / len(trades)
    res = {"trades": len(trades), "per_day": round(len(trades) / days, 2),
           "wr": round(100 * len(wins) / len(trades), 1),
           "pf": round(pf, 2), "exp_r": round(exp_r, 3),
           "max_dd_r": round(dd, 2), "exits": rc,
           "avg_stop_pct": round(100 * sum(stop_widths) / len(stop_widths), 4)}
    res["pass"] = bool(len(trades) >= 30 and pf >= 1.30 and exp_r >= 0.15
                       and dd <= 12.0 and time_share <= 0.40)
    return res


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="M15", choices=["M15", "H1"])
    ap.add_argument("--zlist", default=None,
                    help="override z grid (comma-separated); default = per-profile tunes")
    ap.add_argument("--only", default=None, help="substring filter on symbol name")
    a = ap.parse_args(argv)

    factor = {"M5": 1, "M15": 3, "H1": 12}[a.tf]
    print(f"EA-faithful band-fade on REAL broker history ({a.tf}, "
          f"gate>{GATE_RATIO}x, stop {STOP_MULT}sigma_h, conservative fills)")
    print("promotion gates: >=30 tr | PF>=1.30 | expR>=+0.15 | maxDD<=12R | TIME<=40%\n")
    all_rows = []
    for name, (tgt, z_list) in SYMBOLS.items():
        if a.only and a.only.lower() not in name.lower():
            continue
        p = ART / f"real_{name}_M5.csv"
        if not p.exists():
            print(f"[skip] missing {p.name}")
            continue
        bars = aggregate(load_m5(p), factor) if factor > 1 else load_m5(p)
        zs = [float(x) for x in a.zlist.split(",")] if a.zlist else z_list
        print(f"[{name}] {len(bars)} {a.tf} bars "
              f"({(bars[-1]['epoch']-bars[0]['epoch'])/86400:.0f}d, target={tgt}sig_h)")
        for z in zs:
            r = simulate(bars, z, tgt)
            r.update(symbol=name, tf=a.tf, z=z, tgt=tgt)
            all_rows.append(r)
            if r["trades"]:
                ex = r["exits"]
                print(f"   z={z:<4}: {r['trades']:>4} tr ({r['per_day']}/d) "
                      f"WR {r['wr']:>5}% PF {r['pf']:>5} expR {r['exp_r']:>+7.3f} "
                      f"maxDD {r['max_dd_r']:>5}R stop~{r['avg_stop_pct']:.3f}% "
                      f"T/S/Tm {ex['TARGET']}/{ex['STOP']}/{ex['TIME']} "
                      f"{'PASS' if r['pass'] else 'FAIL'}")
            else:
                print(f"   z={z:<4}: no trades")
        print()

    out = ART / f"bandfade_real_{a.tf}.json"
    # MERGE, never clobber (2026-08-25): an earlier `--only` run rewrote this
    # file with just its own rows and silently erased every other symbol's
    # results (the V75/V100 M15 cells were lost exactly this way). Key rows by
    # (symbol, tf, z, tgt): partial reruns update their own cells, keep the rest.
    def _row_key(r):
        return (r.get("symbol"), r.get("tf"), r.get("z"), r.get("tgt"))

    merged: dict = {}
    if out.exists():
        try:
            for prev in json.loads(out.read_text(encoding="utf-8")):
                merged[_row_key(prev)] = prev
        except (json.JSONDecodeError, OSError):
            pass  # unreadable history is not worth failing a fresh run over
    for row in all_rows:
        merged[_row_key(row)] = row
    all_rows = sorted(merged.values(),
                      key=lambda r: (str(r.get("symbol")), float(r.get("z") or 0)))
    out.write_text(json.dumps(all_rows, indent=1), encoding="utf-8")
    print(f"[wrote] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
