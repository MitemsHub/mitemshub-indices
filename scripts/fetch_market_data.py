#!/usr/bin/env python3
"""fetch_market_data.py — the post-recorder data pipeline (v26.20+).

The EA's tick recorder was retired in v26.19: the broker serves the full tick
history on demand, so nothing needs to be captured live. This script is the
replacement: it pulls history AT A GO and writes the SAME schema the recorder
used, so every existing analysis tool keeps working unchanged.

Tick schema (identical to MITEMSHUB_ticks_<Sym>_<date>.csv):
    ts,bid,ask,mid          ts = unix epoch seconds, prices = %.5f

Known fidelity caveat (measured 2026-09-02, 8-row spot check):
  * Volatility family: broker ticks == live-recorded ticks EXACTLY (bid+ask).
  * Boom/Crash: bid/mid match exactly; the broker's STORED ask channel carries
    a compressed spread (~1/10 of live). Use --verify against any legacy
    recording before trusting stored Boom/Crash spreads for cost studies.

Usage:
  python scripts/fetch_market_data.py --symbol "Volatility 100 Index" \
      --from 2026-08-03 --to 2026-09-02                 # ticks -> artifacts/data/
  python scripts/fetch_market_data.py --symbol "Volatility 75 Index" \
      --bars M15 --days 208                             # OHLCV -> artifacts/data/
  python scripts/fetch_market_data.py --symbol "Volatility 100 Index" \
      --from 2026-09-02 --to 2026-09-02 \
      --verify "C:/.../MITEMSHUB_ticks_Volatility_100_Index_20260902.csv"
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "data"


def _init_mt5():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    return mt5


def fetch_ticks(mt5, symbol: str, t_from: datetime, t_to: datetime) -> np.ndarray:
    raw = mt5.copy_ticks_range(symbol, t_from, t_to, mt5.COPY_TICKS_INFO)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"no ticks returned for {symbol} {t_from}..{t_to}")
    t = np.sort(raw, order="time")
    # dedupe by (time, bid) — same rule the recorder applied
    keep = np.ones(len(t), dtype=bool)
    keep[1:] = (t["time"][1:] != t["time"][:-1]) | (t["bid"][1:] != t["bid"][:-1])
    return t[keep]


def write_ticks(path: Path, t: np.ndarray) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "bid", "ask", "mid"])
        for ts, bid, ask in zip(t["time"], t["bid"], t["ask"]):
            b, a = float(bid), float(ask)
            w.writerow([int(ts), f"{b:.5f}", f"{a:.5f}", f"{(b + a) / 2:.5f}"])
            n += 1
    return n


def write_bars(path: Path, rates: np.ndarray) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
        for r in rates:
            w.writerow([int(r["time"]), r["open"], r["high"], r["low"], r["close"],
                        r["tick_volume"], r["spread"], r["real_volume"]])
    return len(rates)


def verify_against_recording(mt5, symbol: str, recorded: Path, max_rows: int = 500) -> None:
    """Compare broker history with a legacy recorder CSV over its own window."""
    rec = []
    with open(recorded) as f:
        rd = csv.reader(f)
        header = next(rd)
        if header[:4] != ["ts", "bid", "ask", "mid"]:
            raise RuntimeError(f"unexpected header in {recorded}: {header}")
        for row in rd:
            rec.append((int(row[0]), float(row[1]), float(row[2])))
    rec = rec[:max_rows]
    t0 = datetime.fromtimestamp(rec[0][0])
    t1 = datetime.fromtimestamp(rec[-1][0] + 2)
    t = fetch_ticks(mt5, symbol, t0, t1)
    mid_ok = spread_ok = missing = compared = 0
    first_diff = None
    for ts, bid, ask in rec:
        m = t[t["time"] == ts]
        if len(m) == 0:
            missing += 1
            continue
        b, a = float(m["bid"][0]), float(m["ask"][0])
        rec_mid, rec_spread = (bid + ask) / 2.0, ask - bid
        store_mid, store_spread = (b + a) / 2.0, a - b
        compared += 1
        # price path = mid (spread-channel independent); spread channel separately
        if abs(store_mid - rec_mid) < 1e-9:
            mid_ok += 1
            if abs(store_spread - rec_spread) < 1e-9:
                spread_ok += 1
            elif first_diff is None:
                first_diff = (ts, rec_spread, store_spread)
        elif first_diff is None:
            first_diff = (ts, rec_spread, store_spread)
    if compared and mid_ok == compared and spread_ok == compared and missing == 0:
        verdict = "broker reproduces this recording EXACTLY (price path AND spread)"
    elif compared and mid_ok == compared and missing == 0:
        verdict = ("price path (mid) reproduces EXACTLY; live-spread channel does NOT "
                   "(known Boom/Crash store limitation — bid/mid-based replay is safe; "
                   "re-enable the recorder for live-spread studies)")
    else:
        verdict = f"MISMATCH — price path differs ({mid_ok}/{compared} mids match), inspect before use"
    print(f"verify {recorded.name}: mid {mid_ok}/{compared} exact, spread {spread_ok}/{compared} exact, "
          f"{missing} missing-tick seconds")
    if first_diff:
        ts, rec_spread, store_spread = first_diff
        print(f"  first diff @ {ts}: recorded spread {rec_spread:.5f} vs store spread {store_spread:.5f}")
    print("VERDICT:", verdict)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--from", dest="t_from", default=None, help="YYYY-MM-DD (server time)")
    ap.add_argument("--to", dest="t_to", default=None, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--days", type=int, default=None, help="alt to --from: last N days up to now")
    ap.add_argument("--bars", default=None, help="e.g. M5, M15, H1 — fetch OHLCV bars instead of ticks")
    ap.add_argument("--count", type=int, default=60000, help="bar count for --bars mode")
    ap.add_argument("--verify", default=None, help="legacy recorder CSV to prove equivalence against")
    ap.add_argument("--out", default=None, help="override output path")
    args = ap.parse_args()

    mt5 = _init_mt5()
    try:
        if args.verify:
            verify_against_recording(mt5, args.symbol, Path(args.verify))
            return 0

        tag = args.symbol.lower().replace(" ", "_")
        if args.bars:
            tf = getattr(mt5, f"TIMEFRAME_{args.bars.upper()}", None)
            if tf is None:
                ap.error(f"unknown timeframe {args.bars}")
            rates = mt5.copy_rates_from_pos(args.symbol, tf, 1, args.count)  # skip forming bar
            if rates is None or len(rates) == 0:
                raise RuntimeError("no bars returned")
            out = Path(args.out) if args.out else OUT / f"{tag}_{args.bars.lower()}_{len(rates)}bars.csv"
            n = write_bars(out, rates)
            print(f"wrote {n} {args.bars} bars -> {out}")
        elif args.days is not None or args.t_from:
            if args.days is not None:
                t_to = datetime.now()
                t_from = t_to - timedelta(days=args.days)
            else:
                t_from = datetime.fromisoformat(args.t_from)
                t_to = datetime.fromisoformat(args.t_to) + timedelta(days=1) if args.t_to else datetime.now()
            t = fetch_ticks(mt5, args.symbol, t_from, t_to)
            span = (int(t["time"][-1]) - int(t["time"][0])) / 86400
            out = (Path(args.out) if args.out else
                   OUT / f"{tag}_ticks_{t_from:%Y%m%d}_{t_to:%Y%m%d}.csv")
            n = write_ticks(out, t)
            gaps = np.diff(t["time"])
            print(f"wrote {n:,} ticks ({span:.1f} days, worst gap {int(gaps.max())}s) -> {out}")
        else:
            ap.error("need --from/--to or --days (for ticks) or --bars (for OHLCV)")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
