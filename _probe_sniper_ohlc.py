#!/usr/bin/env python3
"""P10-E follow-up: quantify the SNIPER leg under the OHLC price model.

The integrated EA (band geometry) FLIPPED sign under the tester's OHLC model
(P10-E, 2026-08-16): same window/config, -36.964R on real ticks (Model=1) vs
+55.502R under 1-min OHLC (Model=2) — a ~92R stop wick-grace value on the
band's wide geometry.  There is NO sniper EA in the tester (the sniper is
Python research via run_ticks), so the equivalent experiment is a replay of
the REAL captured sniper entry set under OHLC-model exit resolution:

  lane WICK-M5 : the Python journal baseline — wick trade-throughs on real
                 M5 bars (a candle low/high crossing the stop/target), the
                 exact PaperBroker semantics the four-leg reference runs.
  lane CLOSE-M5: OHLC-equivalent at the strategy's native resolution — exits
                 only when a CANDLE CLOSE violates stop/target (no intrabar
                 wick trade-throughs, the documented P10-E mechanism).
  lane CLOSE-M1: the true TestModel=2 analog — the same close-based exit
                 resolution on 1-MINUTE bars (the tester's 1-min OHLC cache).
  lane WICK-M1 : the EXTREME-based M1 bracket — the tester's synthesized
                 ticks see the 1-min high/low, so a stop outside the close but
                 inside the M1 extreme is a real trade-through there.  This
                 brackets the interpretation between CLOSE-M1 (nothing
                 intrabar) and WICK-M5 (every real-tick touch).

The ONLY difference between lanes is the price model / exit resolution; the
entry set, geometry (entry/stop/target), horizon and no-trail policy are
identical.  Reports the exit splits, sumR/expectancy, and whether the sniper
FLIPS sign like the band did — or stays put because its stop-outs are
close-throughs, not wick-only touches.

2026-08-18 finding: WICK-M1 == CLOSE-M1 in sumR (+86.75 both) — only 4/129
stop-outs resolve a few minutes later under close semantics and NONE are
saved by the closed-candle grace at the tester's 1-min resolution.  The
closed-candle grace is therefore BAND-GEOMETRY-SPECIFIC (wide stops, ~92R
Model=2 swing); the sniper's tight 1R stops convert ~nothing, so the
wick-save ceiling must never be misread as sniper-harvestable.
"""

import csv
import os
import pickle
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src"))
sys.path.insert(0, os.path.join(_HERE, "mql5"))

from phase7_real_corpus_check import (  # noqa: E402
    TF,
    load_m5_bars,
    open_state,
    mql_update_bar,
    realized_r,
    split_stats,
    print_split,
    CORPUS_PATHS,
)
from synthetic_trader.domain import Direction  # noqa: E402

M1 = 60

# Gate threshold: the sniper's OHLC-model sumR delta (max across the close-/
# wick-M1 and close-M5 lanes) must stay under this many R.  Measured 2026-08-18:
# 1.4-2.3R (vs the band's +92.5R Model=2 flip) — the model-robustness finding.
SNIPER_OHLC_DELTA_MAX_R = 5.0


def load_m1_bars(paths):
    """Mirror of phase7 load_m5_bars at 1-minute buckets (the tester's 1-min
    OHLC cache granularity).  Same tick cleaning/dedup rules."""
    ticks = []
    seen = set()
    for p in paths:
        if not os.path.exists(p):
            print(f"  (missing corpus: {p})", file=sys.stderr)
            continue
        with open(p, newline="", encoding="utf-8") as f:
            next(f, None)
            prev = None
            for row in csv.reader(f):
                try:
                    epoch = float(row[0])
                    price = float(row[2])
                    spread = float(row[3]) if len(row) > 3 else 0.0
                except (ValueError, IndexError):
                    continue
                if not (100.0 <= price <= 5000.0):
                    continue
                if prev is not None and abs(price - prev) / prev > 0.30:
                    continue
                k = round(epoch, 6)
                if k in seen:
                    continue
                seen.add(k)
                ticks.append((epoch, price, spread))
                prev = price
    ticks.sort(key=lambda t: t[0])
    bars = []
    for epoch, price, spread in ticks:
        bucket = int(epoch // M1)
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            bars[-1] = (bucket, b[1], max(b[2], price), min(b[3], price), price,
                        max(b[5], spread))
        else:
            bars.append((bucket, price, price, price, price, spread))
    return bars


def load_capture():
    with open(os.path.join(_HERE, "_sniper_capture.pkl"), "rb") as f:
        outcomes, geometry, signals, rejected, model = pickle.load(f)
    return outcomes, geometry


def entry_set(geometry, outcomes, bars):
    """Same mapping as the grace probe: {next-M5-bar-index: geometry}."""
    bucket_index = {b[0]: i for i, b in enumerate(bars)}
    entry_by_bar = {}
    for o in outcomes:
        geo = geometry.get(o.position_id)
        if geo is None:
            continue
        entry, stop, target, d = geo
        entry_bucket = int(o.opened_at // TF)
        nxt = bucket_index.get(entry_bucket + TF)
        if nxt is None:
            continue
        entry_by_bar[nxt] = dict(
            i=nxt,
            epoch=float(entry_bucket + TF) * TF,
            close=entry,
            direction=Direction.LONG if d == 1 else Direction.SHORT,
            stop=stop,
            target=target,
            horizon_sec=int(o.closed_at - o.opened_at) if o.closed_at > o.opened_at else 12 * TF,
        )
    return entry_by_bar


def run_lane_m5(entries, bars, wick):
    """WICK-M5 / CLOSE-M5 replay over the M5 series (no trail).

    Returns (entry_id, exit_bar_index, reason, exit_price, realized_r) — the
    bar index is what lets the accounting distinguish touch-before-close from
    same-bar close-throughs."""
    pos = None
    outcomes = []
    for i in range(len(bars)):
        if pos is not None:
            b = bars[i]
            reason, price = mql_update_bar(
                pos, b[2], b[3], b[4], int(b[0]) * TF, TF,
                wick, 0.0, pos["hold_sec"],
            )
            if reason is not None:
                outcomes.append((pos["i"], i, reason, price, realized_r(pos, price)))
                pos = None
        if pos is None and i in entries:
            pos = open_state(entries[i], bars[i])
            pos["hold_sec"] = entries[i]["horizon_sec"]
    return outcomes


def run_lane_m1(entries, m1_bars, wick=False):
    """CLOSE-M1 replay: the same positions on 1-minute bars, close exits.

    A position opens at the first M1 bar at/after its M5-boundary epoch (the
    same instant the M5 lane opens it one bucket after the signal) and exits
    on M1 closes — the tester's 1-min-OHLC granularity.
    """
    m1_bucket = {b[0]: i for i, b in enumerate(m1_bars)}
    entry_by_m1 = {}
    for e in entries.values():
        idx = m1_bucket.get(int(e["epoch"]) // M1)   # bars store bucket NUMBERS
        if idx is not None:
            entry_by_m1[idx] = e
    pos = None
    outcomes = []
    for i in range(len(m1_bars)):
        if pos is not None:
            b = m1_bars[i]
            reason, price = mql_update_bar(
                pos, b[2], b[3], b[4], b[0] * M1, M1,
                wick, 0.0, pos["hold_sec"],
            )
            if reason is not None:
                outcomes.append((pos["i"], i, reason, price, realized_r(pos, price)))
                pos = None
        if pos is None and i in entry_by_m1:
            pos = open_state(entry_by_m1[i], m1_bars[i])
            pos["hold_sec"] = entry_by_m1[i]["horizon_sec"]
    return outcomes


def main():
    print("loading bars (M5 + M1) ...")
    m5_bars = load_m5_bars(CORPUS_PATHS)
    m1_bars = load_m1_bars(CORPUS_PATHS)
    print(f"  M5 bars={len(m5_bars)}  M1 bars={len(m1_bars)}")

    outcomes, geometry = load_capture()
    entries = entry_set(geometry, outcomes, m5_bars)
    print(f"  replayable entries: {len(entries)}")

    wick = run_lane_m5(entries, m5_bars, wick=True)
    close5 = run_lane_m5(entries, m5_bars, wick=False)
    close1 = run_lane_m1(entries, m1_bars, wick=False)
    # WICK-M1: extreme-based at the tester's 1-min granularity — the tester's
    # synthesized ticks see the M1 high/low, so a stop OUTSIDE the close but
    # INSIDE the high/low is a real trade-through there (the P10-E mechanism
    # on the 1-min cache).  Brackets the result between CLOSE-M1 (nothing
    # intrabar) and WICK-M5 (every real-tick touch).
    wick1 = run_lane_m1(entries, m1_bars, wick=True)

    def st4(lane):  # 5-tuple lane -> 4-tuple for the phase7 split_stats
        return [(e, r, p, x) for e, _i, r, p, x in lane]

    print("\n=== exit-reason split (same sniper entry set, no trail) ===")
    print_split("WICK-M5 (real ticks)", split_stats(st4(wick)))
    print_split("CLOSE-M5 (OHLC-equiv)", split_stats(st4(close5)))
    print_split("CLOSE-M1 (1-min close)", split_stats(st4(close1)))
    print_split("WICK-M1 (1-min extreme)", split_stats(st4(wick1)))

    wick_by = {e: (r, x) for e, _i, r, _p, x in wick}
    wick_stop = {e for e, _i, r, _p, x in wick if r == "STOP_HIT"}
    wick_sum = sum(x for _e, _i, _r, _p, x in wick)

    for name, lane in (("CLOSE-M5", close5), ("CLOSE-M1", close1), ("WICK-M1", wick1)):
        lane_exits = {e: (r, x) for e, _i, r, _p, x in lane}
        conv_be = sum(1 for e in wick_stop if lane_exits.get(e, ("", 0))[0] == "BREAKEVEN_TRAIL")
        conv_other = sum(1 for e in wick_stop
                         if lane_exits.get(e, ("", 0))[0] in ("TARGET_HIT", "TIME_EXIT"))
        stayed = sum(1 for e in wick_stop if lane_exits.get(e, ("", 0))[0] == "STOP_HIT")
        lane_sum = sum(x for _e, _i, _r, _p, x in lane)
        print(f"\n=== {name} vs WICK-M5 (grace accounting) ===")
        print(f"  wick STOP_HIT total       : {len(wick_stop)}")
        print(f"    -> {name} BREAKEVEN_TRAIL : {conv_be}")
        print(f"    -> {name} TARGET/TIME     : {conv_other}")
        print(f"    -> still stopped out     : {stayed}")
        print(f"  sumR wick={wick_sum:+.2f} | {name}={lane_sum:+.2f} | "
              f"delta={lane_sum - wick_sum:+.2f}")

    # WICK-first vs close-first: of the wick-lane stop-outs, how many did the
    # close lane stop LATER (touch happened before the close crossed — the
    # grace-relevant population) vs how many were never stopped at all in the
    # close lane (the closed-candle grace would have SAVED these outright).
    def touch_before_close(stops, close_lane):
        # stops: {(entry, bar)} from the wick lane; close_lane: {(entry, bar):
        # reason}.  A stop is touch-before-close when the close lane stopped
        # the same entry at a LATER bar.  close_bar maps entry -> first bar.
        close_bar = {}
        for (e, i), r in close_lane.items():
            if r == "STOP_HIT" and e not in close_bar:
                close_bar[e] = i
        n = len(stops)
        later = sum(1 for (e, i) in stops if close_bar.get(e, -1) > i)
        saved = sum(1 for e, _i in stops if e not in close_bar)
        return n, later, saved

    wk5_map = {(e, i): 1 for e, i, r, _p, _x in wick if r == "STOP_HIT"}
    cl5_map = {(e, i): r for e, i, r, _p, _x in close5}
    wk1_map = {(e, i): 1 for e, i, r, _p, _x in wick1 if r == "STOP_HIT"}
    cl1_map = {(e, i): r for e, i, r, _p, _x in close1}
    n5, l5, s5 = touch_before_close(wk5_map, cl5_map)
    n1, l1, s1 = touch_before_close(wk1_map, cl1_map)
    print(f"\n=== touch-before-close (grace-relevant, of the wick stop-outs) ===")
    print(f"  WICK-M5 stops: {n5} | close stopped LATER: {l5} | "
          f"close never stopped (grace SAVES): {s5}")
    print(f"  WICK-M1 stops: {n1} | close stopped LATER: {l1} | "
          f"close never stopped (grace SAVES): {s1}")

    c5 = sum(x for _e, _i, _r, _p, x in close5)
    c1 = sum(x for _e, _i, _r, _p, x in close1)
    w1 = sum(x for _e, _i, _r, _p, x in wick1)
    d5 = c5 - wick_sum
    d1 = c1 - wick_sum
    d1w = w1 - wick_sum
    band_flip = 55.502 - (-36.964)   # the P10-E band delta under Model=2
    print(f"\n[P10E-SNIPER] wick_sum={wick_sum:+.2f} close5_delta={d5:+.2f} "
          f"close1_delta={d1:+.2f} wick1_delta={d1w:+.2f} band_ohlc_delta={band_flip:+.2f} "
          f"tbc5={l5}/{n5} saved5={s5} tbc1={l1}/{n1} saved1={s1} "
          f"flip5={'YES' if c5 < 0 != (wick_sum < 0) else 'NO'} "
          f"flip1={'YES' if c1 < 0 != (wick_sum < 0) else 'NO'} "
          f"flip1w={'YES' if w1 < 0 != (wick_sum < 0) else 'NO'}")

    # Machine line for the verify_all.ps1 sniper-OHLC gate (model-robustness
    # lock, mirrors the P10-E sign gate).  delta_max = the largest model-
    # induced sumR swing across the three OHLC lanes; the gate fails the loop
    # when it exceeds the threshold (~5R — the measured deltas are 1.4-2.3R,
    # the band's flip is ~92R, so 5R is an order-of-magnitude tripwire with
    # headroom).  Tokens are sign-optional numbers (the $NumTok contract).
    delta_max = max(abs(d5), abs(d1), abs(d1w))
    verdict = "OK" if delta_max <= SNIPER_OHLC_DELTA_MAX_R else "FLIP"
    print(f"[SNIPER-OHLC] delta_max={delta_max:.2f} threshold={SNIPER_OHLC_DELTA_MAX_R:.2f} "
          f"verdict={verdict} wick_sumR={wick_sum:+.2f} "
          f"close5_delta={d5:+.2f} close1_delta={d1:+.2f} wick1_delta={d1w:+.2f} "
          f"band_ohlc_delta={band_flip:+.2f}")


if __name__ == "__main__":
    main()
