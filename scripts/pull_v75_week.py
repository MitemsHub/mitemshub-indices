"""Pull recent Volatility 75 Index candles from the local MT5 terminal.

Usage: python scripts/pull_v75_week.py

Writes:
  artifacts/v75_replay/m15.csv   (bar time = bar OPEN time, MT5 server tz)
  artifacts/v75_replay/h1.csv

Columns: time iso, open, high, low, close, tick_volume
"""
from __future__ import annotations

import csv
import datetime as dt
import os

import MetaTrader5 as mt5

OUT_DIR = os.path.join("artifacts", "v75_replay")
LOOKBACK_DAYS = 12  # extra margin for indicator warmup before the 7-day window


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    if not mt5.initialize():
        print("MT5 initialize failed:", mt5.last_error())
        raise SystemExit(1)
    try:
        symbols = [s.name for s in mt5.symbols_get("*Volatility 75*")]
        print("Terminal symbols matching 'Volatility 75':", symbols)
        if not symbols:
            print("No Volatility 75 symbol found in terminal.")
            raise SystemExit(2)
        symbol = symbols[0]
        print("Using symbol:", symbol)

        utc_to = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
        utc_from = utc_to - dt.timedelta(days=LOOKBACK_DAYS)
        for tf_name, tf in (("m15", mt5.TIMEFRAME_M15), ("h1", mt5.TIMEFRAME_H1)):
            bars = mt5.copy_rates_range(symbol, tf, utc_from, utc_to)
            if bars is None or len(bars) == 0:
                print(f"copy_rates_range failed for {tf_name}:", mt5.last_error())
                raise SystemExit(3)
            path = os.path.join(OUT_DIR, f"{tf_name}.csv")
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time", "open", "high", "low", "close", "tick_volume"])
                for b in bars:
                    t = dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).isoformat()
                    w.writerow([t, b["open"], b["high"], b["low"], b["close"], b["tick_volume"]])
            first = dt.datetime.fromtimestamp(bars[0]["time"], tz=dt.timezone.utc)
            last = dt.datetime.fromtimestamp(bars[-1]["time"], tz=dt.timezone.utc)
            print(f"{tf_name}: {len(bars)} bars -> {path} (first {first.isoformat()}, last {last.isoformat()})")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
