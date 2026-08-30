#!/usr/bin/env python3
"""Live tick monitor for Boom 1000 (MITEMSHUB tick CSVs).

Tails the newest MITEMSHUB_ticks_Boom_1000_Index_YYYYMMDD.csv (the EA v25.5+
writes with FILE_SHARE_READ so this can read it while it grows) and reports in
real time:
  * [SPIKE]    tick jump >= InpCBTickSpikePts (3.0 pts default)
  * [ARMED]    spike pending, tracking retrace toward the 30-60% fade window
  * [FADE!]    retrace inside the window -> the EA's tick fast-fade fires here
  * [EXPIRED]  window missed (overshot / full retrace / timeout)
  * hourly summary line: ticks seen, spikes, fades, avg jump

Same rules as the deployed v25.6 tick fast-fade:
    retrace window [InpCBFadeR 0.30, ceiling 0.60], timeout 900s,
    geometry SL 0.4xATR (last 60d ATR), TP 3.2xATR clamped below pre-spike,
    R:R >= 2.0.  Purely observational — places no orders.

Usage:
    .venv/Scripts/python.exe scripts/live_tick_monitor.py
    .venv/Scripts/python.exe scripts/live_tick_monitor.py --replay artifacts/ticks/MITEMSHUB_ticks_Boom_1000_Index_20260829.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mt5_data import load_m5                      # noqa: E402
from synthlib import slice_60d, compute_atr       # noqa: E402

TICK_DIR = ROOT / "artifacts" / "ticks"
TERM_FILES = Path(r"C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal"
                  r"\FB9A56D617EDDDFE29EE54EBEFFE96C1\MQL5\Files")

# Deployed v25.6 tick fast-fade parameters
SPIKE_PTS = 3.0
RE_LO, RE_HI = 0.30, 0.60
TIMEOUT_S = 900
SL_MULT, TP_MULT = 0.4, 3.2
MIN_RR = 2.0
POLL_S = 2.0


def current_atr():
    try:
        m5 = slice_60d(load_m5("Boom 1000 Index", "M5"), 60)
        atrs = [a for a in compute_atr(m5) if a > 0]
        return atrs[-1] if atrs else 7.0
    except Exception:
        return 7.0


def newest_file():
    cands = sorted(TICK_DIR.glob("MITEMSHUB_ticks_Boom_1000_Index_*.csv"))
    live = sorted(TERM_FILES.glob("MITEMSHUB_ticks_Boom_1000_Index_*.csv"))
    # prefer the terminal's live file; fall back to artifacts copies
    if live:
        return live[-1]
    return cands[-1] if cands else None


class Monitor:
    def __init__(self, atr):
        self.atr = atr
        self.sl_dist = SL_MULT * atr
        self.prev_bid = None
        self.pending = None          # dict(pre, peak, jump, t0)
        self.stats = {"ticks": 0, "spikes": 0, "fades": 0, "expired": 0,
                      "jumps": [], "ages": []}
        self.hour_mark = None

    def feed(self, ts, bid):
        s = self.stats
        s["ticks"] += 1
        now = datetime.fromtimestamp(ts, tz=timezone.utc)
        if self.hour_mark is None or ts - self.hour_mark >= 3600:
            if self.hour_mark is not None:
                j = s["jumps"]
                print(f"  ---- {now:%H:%M} UTC | ticks={s['ticks']} spikes={s['spikes']} "
                      f"fades={s['fades']} expired={s['expired']} "
                      f"avg_jump={statistics.mean(j):.1f}pts" if j else
                      f"  ---- {now:%H:%M} UTC | ticks={s['ticks']} spikes={s['spikes']} fades={s['fades']}")
                s["ticks"] = s["spikes"] = s["fades"] = s["expired"] = 0
                s["jumps"] = []          # NOTE: separate lists — chained assignment
                s["ages"] = []           # would alias them into one object
            self.hour_mark = ts
        if self.prev_bid is None:
            self.prev_bid = bid
            return
        jump = bid - self.prev_bid
        self.prev_bid = bid

        # spike detection / extension (Boom: UP jumps)
        if jump >= SPIKE_PTS:
            if self.pending and bid > self.pending["peak"]:
                self.pending["peak"] = bid
                self.pending["jump"] = bid - self.pending["pre"]
                self.pending["t0"] = ts
                print(f"[EXTEND] peak now {bid:.2f} (jump {self.pending['jump']:.1f}pts)")
            elif not self.pending:
                self.pending = {"pre": self.prev_bid_orig(bid, jump), "peak": bid,
                                "jump": jump, "t0": ts}
                self.stats["spikes"] += 1
                self.stats["jumps"].append(jump)
                print(f"[SPIKE ] UP +{jump:.1f}pts -> {bid:.2f}  "
                      f"({now:%H:%M:%S} UTC)  waiting retrace {RE_LO:.0%}-{RE_HI:.0%}")

        p = self.pending
        if not p:
            return
        if bid <= p["pre"]:
            print(f"[EXPIRED] full retrace after {ts - p['t0']}s")
            self.pending = None
            self.stats["expired"] += 1
            return
        retrace = (p["peak"] - bid) / p["jump"]
        if retrace > RE_HI:
            print(f"[EXPIRED] overshot retrace {retrace:.0%} after {ts - p['t0']}s")
            self.pending = None
            self.stats["expired"] += 1
            return
        if ts - p["t0"] > TIMEOUT_S:
            print(f"[EXPIRED] timeout {TIMEOUT_S}s — big spike still holding "
                  f"(retrace {retrace:.0%})")
            self.pending = None
            self.stats["expired"] += 1
            return
        if RE_LO <= retrace <= RE_HI:
            entry = bid
            sl = entry + self.sl_dist
            tp = min(entry - TP_MULT * self.atr, p["pre"] - 0.2 * self.atr)
            rr = (entry - tp) / self.sl_dist
            if rr < MIN_RR:
                print(f"[SKIP  ] RR {rr:.1f} < {MIN_RR} — TP clamped by pre-spike level")
                self.pending = None
                self.stats["expired"] += 1
                return
            self.stats["fades"] += 1
            self.stats["ages"].append(ts - p["t0"])
            print(f"[FADE! ] SELL @ {entry:.2f}  jump={p['jump']:.1f}pts  "
                  f"retrace={retrace:.0%}  t=+{ts - p['t0']}s  "
                  f"SL {sl:.2f} ({self.sl_dist:.2f})  TP {tp:.2f}  R:R {rr:.1f}")
            self.pending = None

    def prev_bid_orig(self, bid, jump):
        return bid - jump


def tail_forever(path, mon):
    print(f"[monitor] tailing {path}")
    with open(path, newline="") as fh:
        fh.seek(0, 2)                      # jump to end — only new ticks
        while True:
            line = fh.readline()
            if not line:
                time.sleep(POLL_S)
                continue
            line = line.strip()
            if not line or line.startswith("ts,"):
                continue
            try:
                parts = line.split(",")
                ts, bid = int(parts[0]), float(parts[1])
            except (ValueError, IndexError):
                continue
            mon.feed(ts, bid)


def replay(path, mon, speed=50.0):
    print(f"[replay ] {path} at ~{speed:.0f}x")
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        prev_ts = None
        for rec in reader:
            ts, bid = int(rec["ts"]), float(rec["bid"])
            if prev_ts is not None:
                dt = min(ts - prev_ts, 5)
                time.sleep(dt / speed)
            prev_ts = ts
            mon.feed(ts, bid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", metavar="CSV", help="replay a recorded CSV instead of tailing live")
    ap.add_argument("--speed", type=float, default=50.0, help="replay speed multiplier")
    args = ap.parse_args()

    atr = current_atr()
    print(f"[monitor] Boom 1000 tick fast-fade rules: spike>={SPIKE_PTS}pts  "
          f"window {RE_LO:.0%}-{RE_HI:.0%}  timeout {TIMEOUT_S}s  "
          f"SL {SL_MULT}xATR({atr:.2f})  TP {TP_MULT}xATR  (observational only)")
    mon = Monitor(atr)

    if args.replay:
        replay(Path(args.replay), mon, args.speed)
    else:
        f = newest_file()
        if f is None:
            print("No MITEMSHUB tick CSV found (artifacts/ticks or terminal Files).")
            return 1
        tail_forever(f, mon)
    s = mon.stats
    print(f"\n[summary] ticks={s['ticks']} spikes={s['spikes']} fades={s['fades']} "
          f"expired={s['expired']} "
          + (f"median_fade_age={statistics.median(s['ages']):.0f}s" if s["ages"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
