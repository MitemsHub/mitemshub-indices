#!/usr/bin/env python3
"""weekly_refresh.py — keep research datasets current without any recorder.

Pulls fresh broker history ON DEMAND via fetch_market_data (v26.19+ replaced
the EA tick recorder with broker fetches) and refreshes:

  artifacts/data/volatility_75_index_ticks_<from>_<to>.csv   (30-day window)
  artifacts/data/volatility_75_index_m15_<n>bars.csv         (bar history)
  artifacts/data/volatility_100_index_m15_<n>bars.csv        (bar history)

Design:
  * idempotent: re-running the same week replaces the old tick window file
  * retention: keeps the newest KEEP_WINDOWS tick files, deletes older
  * writes MANIFEST.json with row counts and windows for quick auditing
  * logs to artifacts/data/refresh.log (one line per run)
  * ensures the MT5 terminal is running (starts it if needed); MT5 will
    resolve its own data folder since no explicit path is given

Usage:
  .venv/Scripts/python.exe scripts/weekly_refresh.py            # full refresh
  .venv/Scripts/python.exe scripts/weekly_refresh.py --dry-run  # show plan
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_market_data import OUT, fetch_ticks, write_bars, write_ticks  # noqa: E402

DATA = ROOT / "artifacts" / "data"
LOG = DATA / "refresh.log"
MANIFEST = DATA / "MANIFEST.json"
KEEP_WINDOWS = 3          # tick windows to retain
TICK_DAYS = 30
BAR_COUNT = 40000         # ~14 months of M15

SYMBOLS_BARS = ["Volatility 75 Index", "Volatility 100 Index"]
TICK_SYMBOL = "Volatility 75 Index"

TERMINAL_EXE = Path(r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe")


def log_line(msg: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}Z] {msg}\n")
    print(msg)


def ensure_terminal() -> None:
    """MT5 python API needs a running terminal; start it detached if absent."""
    probe = mt5.initialize()
    if probe:
        mt5.shutdown()
        return
    log_line("terminal not running — starting terminal64.exe ...")
    subprocess.Popen(
        [str(TERMINAL_EXE)],
        cwd=str(TERMINAL_EXE.parent),
        creationflags=0x00000008,            # DETACHED_PROCESS
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import time
    for _ in range(30):                       # wait up to ~60s for the API
        time.sleep(2)
        if mt5.initialize():
            mt5.shutdown()
            log_line("terminal is up")
            return
    raise RuntimeError("terminal did not come up within 60s")


def refresh_ticks(mt5, symbol: str, days: int) -> dict:
    t_to = datetime.now()
    t_from = t_to - timedelta(days=days)
    t = fetch_ticks(mt5, symbol, t_from, t_to)
    tag = symbol.lower().replace(" ", "_")
    out = DATA / f"{tag}_ticks_{t_from:%Y%m%d}_{t_to:%Y%m%d}.csv"
    n = write_ticks(out, t)
    gaps = np_diff_max(t["time"])
    return {"file": out.name, "rows": n, "window_days": days, "worst_gap_s": gaps}


def np_diff_max(times) -> int:
    import numpy as np
    d = np.diff(times)
    return int(d.max()) if len(d) else 0


def refresh_bars(mt5, symbol: str, tf_name: str, count: int) -> dict:
    tf = getattr(mt5, f"TIMEFRAME_{tf_name.upper()}")
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)   # skip forming bar
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no bars for {symbol}")
    tag = symbol.lower().replace(" ", "_")
    out = DATA / f"{tag}_{tf_name.lower()}_{len(rates)}bars.csv"
    n = write_bars(out, rates)
    # remove the previous bar file for this symbol/tf (count changes over time)
    for old in DATA.glob(f"{tag}_{tf_name.lower()}_*bars.csv"):
        if old.name != out.name:
            old.unlink()
    return {"file": out.name, "rows": int(n)}


def prune_tick_windows() -> list:
    kept = sorted(DATA.glob("volatility_75_index_ticks_*.csv"))[-KEEP_WINDOWS:]
    removed = []
    for f in sorted(DATA.glob("volatility_75_index_ticks_*.csv")):
        if f not in kept:
            f.unlink()
            removed.append(f.name)
    return removed


def build_manifest(entries: list) -> None:
    import json
    import numpy as np
    man = {"updated_utc": datetime.now(timezone.utc).isoformat(), "datasets": []}
    for e in entries:
        p = DATA / e["file"]
        rows = sum(1 for _ in open(p, "rb")) - 1
        man["datasets"].append({**e, "bytes": p.stat().st_size, "rows_on_disk": rows})
    MANIFEST.write_text(json.dumps(man, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        print("would refresh:")
        print(f"  ticks : {TICK_SYMBOL} last {TICK_DAYS} days -> "
              f"{DATA}/volatility_75_index_ticks_*.csv (keep {KEEP_WINDOWS})")
        for s in SYMBOLS_BARS:
            print(f"  bars  : {s} {BAR_COUNT} M15")
        return 0

    log_line("=== weekly refresh starting ===")
    ensure_terminal()
    if not mt5.initialize():
        raise RuntimeError(f"mt5 init failed: {mt5.last_error()}")

    entries = []
    try:
        entries.append({"kind": "ticks", "symbol": TICK_SYMBOL,
                        **refresh_ticks(mt5, TICK_SYMBOL, TICK_DAYS)})
        for s in SYMBOLS_BARS:
            entries.append({"kind": "bars", "symbol": s,
                            **refresh_bars(mt5, s, "M15", BAR_COUNT)})
    finally:
        mt5.shutdown()

    removed = prune_tick_windows()
    if removed:
        log_line("retention removed: " + ", ".join(removed))
    build_manifest(entries)
    for e in entries:
        log_line(f"refreshed {e['kind']}: {e['file']} ({e['rows']:,} rows)")
    log_line("=== weekly refresh done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
