#!/usr/bin/env python3
"""Read-only MT5 Deriv terminal probe: ground-truth symbol names & specs.

Answers the questions the codebase kept guessing at:
  * Which volatility/synthetic symbols actually exist (SYN-series? display names?)
  * Their trade mode, min lot / step, tick value/size -> real min-lot risk math
  * How much M5 history the terminal will give us (saved to the shared .npy cache)

No orders are sent. Safe to run while the terminal is open.

Usage:
  python scripts/mt5_probe.py                # enumerate + specs + fetch history
  python scripts/mt5_probe.py --no-history   # enumeration only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mt5_data import _write_cache

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 package not installed. pip install MetaTrader5")
    sys.exit(2)

PATTERN = re.compile(r"volatil|syn\d+|boom|crash|jump|step", re.IGNORECASE)
HISTORY_SYMBOLS = ["SYN75", "SYN100"]  # extended dynamically by matches


def _sanitize_name(symbol: str) -> str:
    return symbol.replace(" ", "_").replace("(", "").replace(")", "")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--bars", type=int, default=60000,
                    help="max M5 bars to fetch per symbol (default 60000 ~= 208 wks)")
    ap.add_argument("--timeframe", default="M5",
                    choices=["M1", "M5", "M15", "M30", "H1"])
    a = ap.parse_args(argv)

    if not mt5.initialize():
        print(f"mt5.initialize() failed: {mt5.last_error()}")
        return 1
    try:
        term = mt5.terminal_info()
        acct = mt5.account_info()
        print(f"terminal: connected={term.connected if term else '?'} "
              f"trade_allowed={term.trade_allowed if term else '?'}")
        if acct:
            print(f"account: login={acct.login} balance={acct.balance:.2f} "
                  f"equity={acct.equity:.2f} leverage=1:{acct.leverage}")

        all_syms = mt5.symbols_total()
        print(f"symbols_total={all_syms}")
        matches = []
        for s in mt5.symbols_get():
            if PATTERN.search(s.name):
                matches.append(s)
        print(f"\n=== MATCHING SYMBOLS ({len(matches)}) ===")
        print(f"{'name':<28} {'vis':>3} {'trade_mode':>10} {'vol_min':>8} "
              f"{'step':>6} {'tick_val':>9} {'digits':>6}")
        for s in sorted(matches, key=lambda x: x.name):
            tm = {0: 'DISABLED', 1: 'LONGONLY', 2: 'SHORTONLY', 4: 'FULL'}.get(
                s.trade_mode, str(s.trade_mode))
            print(f"{s.name:<28} {int(s.visible):>3} {tm:>10} {s.volume_min:>8} "
                  f"{s.volume_step:>6} {s.trade_tick_value:>9.4g} {s.digits:>6}")

        # min-lot risk math for the tiny-account question
        print("\n=== MIN-LOT RISK AT STOP SIZES (equity $30 reference) ===")
        print(f"{'name':<28} {'px':>10} {'$@0.5%':>8} {'$@1.0%':>8} {'$@1.7%':>8} {'%eq@1.7%':>9}")
        for s in sorted(matches, key=lambda x: x.name):
            if s.trade_mode != 4 or s.volume_min <= 0:
                continue
            info = mt5.symbol_info(s.name)
            if info is None:
                continue
            px = info.bid or info.ask or 0
            if px <= 0 or s.trade_tick_size <= 0:
                continue
            vals = []
            for pct in (0.005, 0.01, 0.017):
                dist = px * pct
                n_ticks = dist / s.trade_tick_size
                vals.append(s.volume_min * s.trade_tick_value * n_ticks)
            eq = acct.equity if acct else 30.0
            print(f"{s.name:<28} {px:>10.3f} {vals[0]:>8.2f} {vals[1]:>8.2f} "
                  f"{vals[2]:>8.2f} {vals[2]/eq*100:>8.0f}%")

        if a.no_history:
            return 0

        tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                  "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                  "H1": mt5.TIMEFRAME_H1}
        tf = tf_map[a.timeframe]
        want = HISTORY_SYMBOLS + [m.name for m in matches
                                  if re.match(r"(?i)^(syn|volatility)\s*?(10|25|50)\b|^syn(10|25|50)$",
                                              m.name)]
        seen = set()
        print(f"\n=== HISTORY FETCH ({a.timeframe}, up to {a.bars} bars) ===")
        for name in want:
            if name in seen:
                continue
            seen.add(name)
            try:
                rates = mt5.copy_rates_from_pos(name, tf, 0, a.bars)
            except Exception as exc:
                print(f"  {name}: fetch failed ({exc})")
                continue
            if rates is None or len(rates) == 0:
                print(f"  {name}: no history ({mt5.last_error()})")
                continue
            import numpy as _np
            from scripts.mt5_data import DTYPE as _DTYPE, CACHE_DIR as _CACHE_DIR, _write_cache as _wc
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            out = _np.zeros(len(rates), dtype=_DTYPE)
            out["epoch"] = rates["time"].astype("f8")
            out["open"] = rates["open"]
            out["high"] = rates["high"]
            out["low"] = rates["low"]
            out["close"] = rates["close"]
            out["spread"] = rates["spread"]
            out["volume"] = rates["tick_volume"]
            _wc(out, name, a.timeframe)
            import datetime as _dt
            d0 = _dt.datetime.fromtimestamp(rates[0]['time'],
                                            tz=_dt.timezone.utc)
            d1 = _dt.datetime.fromtimestamp(rates[-1]['time'],
                                            tz=_dt.timezone.utc)
            days = (rates[-1]['time'] - rates[0]['time']) / 86400.0
            print(f"  {name}: {len(rates)} bars  {d0:%Y-%m-%d} -> {d1:%Y-%m-%d} "
                  f"({days:.0f}d)  -> npy cache ({_sanitize_name(name)}_{a.timeframe}.npy)")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
