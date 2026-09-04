"""Pull Volatility 75 Index ticks from the local MT5 terminal (broker history).

Usage:
  python scripts/pull_v75_ticks.py --from 2026-08-01 --to 2026-09-05 [--out FILE]
  python scripts/pull_v75_ticks.py --probe            # how deep does tick history go?

Output CSV: epoch_ms,bid,ask  (UTC, ascending)

Why: the tick-level fast-fail study (see scripts/study_fastfail_ticks.py) needs
the broker's REAL tick path through each certified trade's lifetime. The old
data/R_75_ticks.csv recording is NOT V75 (return correlation 0.011 vs broker
bars over 835 overlapping M15 bars) and must not be used for instrument
research. Broker tick history was validated as the research source in v26.19
(InpTickRecordEnabled retired for exactly this reason).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os

import MetaTrader5 as mt5


def pick_symbol() -> str:
    symbols = [s.name for s in mt5.symbols_get("*Volatility 75*")]
    if not symbols:
        raise SystemExit("No Volatility 75 symbol found in terminal.")
    return symbols[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="t_from", default="2026-08-01",
                    help="UTC date YYYY-MM-DD (default 2026-08-01)")
    ap.add_argument("--to", dest="t_to", default="2026-09-05",
                    help="UTC date YYYY-MM-DD, exclusive end")
    ap.add_argument("--out", default="data/v75_ticks.csv")
    ap.add_argument("--probe", action="store_true",
                    help="just report how far back tick history goes")
    args = ap.parse_args()

    if not mt5.initialize():
        print("MT5 initialize failed:", mt5.last_error())
        raise SystemExit(1)
    try:
        symbol = pick_symbol()
        print("symbol:", symbol)
        if not mt5.symbol_select(symbol, True):
            print("symbol_select failed:", mt5.last_error())
            raise SystemExit(2)

        if args.probe:
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            depth = None
            for days in (7, 14, 30, 60, 90, 180, 365):
                t0 = now - dt.timedelta(days=days)
                ticks = mt5.copy_ticks_range(symbol, t0, now, mt5.COPY_TICKS_INFO)
                if ticks is None or len(ticks) == 0:
                    print(f"  {days:>4}d back: NO DATA")
                    break
                first = dt.datetime.fromtimestamp(ticks[0]["time_msc"] / 1000, dt.timezone.utc)
                print(f"  {days:>4}d back: {len(ticks):>9,} ticks, earliest={first:%Y-%m-%d %H:%M}")
                depth = days
            print("probe done; deepest with data:", depth, "days")
            return

        t_from = dt.datetime.fromisoformat(args.t_from).replace(tzinfo=dt.timezone.utc)
        t_to = dt.datetime.fromisoformat(args.t_to).replace(tzinfo=dt.timezone.utc)
        # request naive datetimes (MT5 treats them as server tz); V75 server ~ UTC
        ticks = mt5.copy_ticks_range(symbol, t_from.replace(tzinfo=None),
                                     t_to.replace(tzinfo=None), mt5.COPY_TICKS_INFO)
        if ticks is None or len(ticks) == 0:
            print("no ticks returned:", mt5.last_error())
            raise SystemExit(3)

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        n = 0
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["epoch_ms", "bid", "ask"])
            for t in ticks:
                bid, ask = float(t["bid"]), float(t["ask"])
                if bid <= 0 or ask <= 0:
                    continue  # COPY_TICKS_INFO rows can include non-quote records
                w.writerow((int(t["time_msc"]), bid, ask))
                n += 1
        first = dt.datetime.fromtimestamp(ticks[0]["time_msc"] / 1000, dt.timezone.utc)
        last = dt.datetime.fromtimestamp(ticks[-1]["time_msc"] / 1000, dt.timezone.utc)
        print(f"wrote {n:,} quotes -> {args.out}")
        print(f"span: {first:%Y-%m-%d %H:%M:%S} -> {last:%Y-%m-%d %H:%M:%S} UTC")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
