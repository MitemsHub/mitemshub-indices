#!/usr/bin/env python3
"""60-day backtest analysis across all symbols on real broker M5 candle history.

Slices the most recent 60 days of real broker M5 data for each symbol and runs
the EA-faithful band-fade backtest. Reports per-symbol and aggregate metrics.

Usage:
    .venv/Scripts/python.exe scripts/60day_analysis.py
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5  # shared loader: terminal + .npy cache
from synthlib import slice_60d

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

# Same symbol profiles as backtest_real_history.py
SYMBOLS = {
    "Volatility 75 Index": (1.20, [1.0, 1.4, 2.0]),
    "Volatility 100 Index": (0.80, [1.0, 1.4, 2.0]),
    "Volatility 75 (1s) Index": (1.20, [1.0, 1.4, 2.0]),
    "Volatility 10 Index": (0.60, [2.3, 2.0]),
    "Volatility 25 Index": (0.70, [2.2, 2.0]),
    "Volatility 50 Index": (0.80, [2.0]),
}

GATE_RATIO = 1.25
SIGMA_EMA_LEN = 30
STOP_MULT = 0.10
HOLD_SEC = 3600
WARMUP = 60
COOLDOWN = 2
DAYS = 60


def aggregate(m5, factor):
    out = []
    for i in range(0, len(m5) - factor + 1, factor):
        chunk = m5[i:i + factor]
        out.append({
            "epoch": chunk[0]["epoch"],
            "open": chunk[0]["open"],
            "high": max(c["high"] for c in chunk),
            "low": min(c["low"] for c in chunk),
            "close": chunk[-1]["close"],
        })
    return out


def simulate(bars, z_entry, tgt_mult):
    n = len(bars)
    closes = [b["close"] for b in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    sigma_ema = None
    trades, reasons, stop_widths = [], [], []
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
                        hb = max(1, round(HOLD_SEC / (bars[1]["epoch"] - bars[0]["epoch"])))
                        sig_h = s_now * math.sqrt(hb)
                        stop_f = STOP_MULT * sig_h
                        tgt_f = tgt_mult * sig_h
                        entry = closes[i]
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
    days_span = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400.0
    pf = gw / gl if gl > 0 else 99.0
    exp_r = sum(trades) / len(trades)
    time_share = rc["TIME"] / len(trades)
    passes = bool(len(trades) >= 30 and pf >= 1.30 and exp_r >= 0.15 and dd <= 12.0 and time_share <= 0.40)

    # Equity curve
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t)

    return {
        "trades": len(trades),
        "per_day": round(len(trades) / max(days_span, 1), 2),
        "wr": round(100 * len(wins) / len(trades), 1),
        "pf": round(pf, 2),
        "exp_r": round(exp_r, 3),
        "max_dd_r": round(dd, 2),
        "exits": rc,
        "avg_stop_pct": round(100 * sum(stop_widths) / len(stop_widths), 4),
        "pass": passes,
        "equity_curve": equity,
        "days_span": round(days_span, 1),
    }


def print_monthly_breakdown(equity_curve, trades_list, bars, reasons_list):
    """Print month-by-month breakdown of results."""
    from collections import defaultdict
    monthly = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "r": 0.0, "exits": defaultdict(int)})

    # We need to map trade index back to epoch. Re-run the trade generation
    # with date tracking. For now, use equity curve deltas.
    # Actually let's just do aggregate since we don't have per-trade epochs in simulate.
    pass


def main():
    print("=" * 100)
    print("60-DAY BACKTEST ANALYSIS - EA-Faithful Band-Fade on Real Broker M5 History")
    print(f"Gate>{GATE_RATIO}x sigma_ema | Stop {STOP_MULT}sigma_h | Conservative fills | Cooldown={COOLDOWN}")
    print(f"Promotion gates: >=30 trades | PF>=1.30 | expR>=+0.15 | maxDD<=12R | TIME<=40%")
    print("=" * 100)

    all_results = []

    for symbol, (tgt_mult, z_list) in SYMBOLS.items():
        # Shared loader: pulls from the MT5 terminal (fresh) with .npy cache.
        full_m5 = load_m5(symbol, "M5")
        m5_60d = slice_60d(full_m5, DAYS)

        if not m5_60d:
            print(f"\n[{symbol}] SKIP - no data in 60d window")
            continue

        # Convert to timestamps for display
        t_start = datetime.fromtimestamp(m5_60d[0]["epoch"], timezone.utc).strftime("%Y-%m-%d")
        t_end = datetime.fromtimestamp(m5_60d[-1]["epoch"], timezone.utc).strftime("%Y-%m-%d")
        actual_days = (m5_60d[-1]["epoch"] - m5_60d[0]["epoch"]) / 86400

        print("\n" + "-" * 100)
        print(f"[{symbol}]  {len(m5_60d)} M5 bars  |  {t_start} to {t_end}  ({actual_days:.0f}d)  |  target={tgt_mult}sig_h")
        print("-" * 100)
        print(f"{'  z':>5} | {'Trades':>6} {'PerD':>5} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} | {'T':>3} {'S':>3} {'Tm':>3} | {'Stop%':>6} | {'Pass':>5}")
        print("  -----+------+------+-----+-----+-----+-------+------+----+-----+-----+------+------")

        for z in z_list:
            # Aggregate M5 to M15 for backtest
            bars = aggregate(m5_60d, 3)
            result = simulate(bars, z, tgt_mult)
            result["symbol"] = symbol
            result["tf"] = "M15"
            result["z"] = z
            result["tgt"] = tgt_mult
            all_results.append(result)

            if result["trades"]:
                ex = result["exits"]
                print(
                    f"  {z:<5} | {result['trades']:>6} {result['per_day']:>5} "
                    f"{result['wr']:>5} {result['pf']:>5} {result['exp_r']:>+7.3f} "
                    f"{result['max_dd_r']:>6} | {ex.get('TARGET',0):>3} {ex.get('STOP',0):>3} "
                    f"{ex.get('TIME',0):>3} | {result['avg_stop_pct']:>5.3f}% | "
                    f"{'PASS' if result['pass'] else 'FAIL':>5}"
                )
            else:
                print(f"  {z:<5} | no trades")

    # -- Aggregate summary --
    print("\n" + "=" * 100)
    print("AGGREGATE SUMMARY (best z per symbol)")
    print("=" * 100)
    print(f"{'Symbol':<32} {'Best z':>6} {'Trades':>6} {'PerD':>5} {'WR%':>5} {'PF':>5} {'ExpR':>7} {'MaxDD':>6} {'Pass':>5}")
    print("--------------------------------+------+--------+-----+-----+-----+-------+------+------")

    total_trades = 0
    total_wins = 0
    total_losses = 0
    pass_count = 0
    symbol_count = 0

    seen_syms = {}
    for r in all_results:
        sym = r["symbol"]
        if sym not in seen_syms or (r["trades"] >= 30 and r.get("pass") and not seen_syms[sym].get("pass")):
            seen_syms[sym] = r
        elif sym not in seen_syms:
            seen_syms[sym] = r

    for sym in sorted(seen_syms):
        r = seen_syms[sym]
        symbol_count += 1
        total_trades += r["trades"]
        w = int(r["wr"] * r["trades"] / 100)
        total_wins += w
        total_losses += (r["trades"] - w)
        if r["pass"]:
            pass_count += 1
        print(
            f"{sym:<32} {r['z']:>6} {r['trades']:>6} {r['per_day']:>5} "
            f"{r['wr']:>5} {r['pf']:>5} {r['exp_r']:>+7.3f} "
            f"{r['max_dd_r']:>6} {'PASS' if r['pass'] else 'FAIL':>5}"
        )

    print("-" * 117)
    overall_wr = round(100 * total_wins / total_trades, 1) if total_trades else 0
    print(f"{'TOTAL':<32} {'':>6} {total_trades:>6} {'':>5} {overall_wr:>5} {'':>5} {'':>7} {'':>6} {pass_count}/{symbol_count} pass")

    # -- Save results --
    out_path = ART / "analysis_60day.json"
    # Strip equity curves for the saved JSON (too large)
    saved = [{k: v for k, v in r.items() if k != "equity_curve"} for r in all_results]
    out_path.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")

    print("\n" + "=" * 100)
    print("INTERPRETATION")
    print("=" * 100)
    if pass_count == symbol_count and symbol_count > 0:
        print("ALL symbols pass the 60-day window - strong candidate for live deployment sizing.")
    elif pass_count > 0:
        print(f"WARNING: {pass_count}/{symbol_count} symbols pass. Review failing symbols for regime fit.")
    else:
        print("FAIL: No symbols pass in the 60-day window. Market regime may be unfavorable or sizing needs adjustment.")
    print()


if __name__ == "__main__":
    main()
