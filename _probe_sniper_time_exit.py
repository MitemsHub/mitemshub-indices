#!/usr/bin/env python3
"""P10-E follow-up: the sniper grace/trail lanes under a FIXED 1h time exit.

The grace probe (_probe_sniper_grace.py) anchors each entry's time exit to
the REALIZED hold from the capture (o.closed_at - o.opened_at) — the horizon
is whatever the wick lane actually held.  This probe re-runs the same cached
sniper entry set with a FIXED 1h horizon for every position (the production
BAND_HOLD_SEC, and the horizon the paper journal's TIME exits are defined on),
keeping every other knob identical:

  lane WICK  : Python PaperBroker semantics (wick trade-throughs, no trail).
  lane GRACE : EA/phase-7 production management (closed-candle exits + BE
               trail at 0.3 x planned RR).

The question: once the lane is NOT anchored to the wick close time, do the
grace/trail conversions change?  (A fixed shorter horizon releases the slot
earlier on TIME exits — but the sniper lane is single-position and the
realized-hold anchor was itself driven by the wick lane, so the delta is
exactly the exit-policy x horizon interaction.)

Usage: python _probe_sniper_time_exit.py [--horizon-sec 3600]
"""

import argparse
import os
import pickle
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src"))
sys.path.insert(0, os.path.join(_HERE, "mql5"))

from synthetic_trader.backtest.engine import load_ticks_csv  # noqa: E402
from synthetic_trader.backtest.vol_reversion import dedupe_ticks  # noqa: E402
from synthetic_trader.domain import Direction  # noqa: E402
from tradequality_real_corpus_check import run_sniper_ticks_captured  # noqa: E402
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

TRAIL = 0.3   # BAND_TRAIL_FRAC — the EA/phase-7 production trail


def entry_set_from_capture(geometry, outcomes, bars, fixed_horizon_sec=None):
    """Same mapping as the grace probe, with the horizon optionally FIXED
    (None keeps the realized-hold anchor from the capture)."""
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
        hold = fixed_horizon_sec if fixed_horizon_sec else (
            int(o.closed_at - o.opened_at) if o.closed_at > o.opened_at else 12 * TF)
        entry_by_bar[nxt] = dict(
            i=nxt,
            epoch=float(entry_bucket + TF) * TF,
            close=entry,
            direction=Direction.LONG if d == 1 else Direction.SHORT,
            stop=stop,
            target=target,
            horizon_sec=hold,
        )
    return entry_by_bar


def run_lane(entries, bars, wick, trail_frac):
    pos = None
    outcomes = []
    armed = 0
    for i in range(len(bars)):
        if pos is not None:
            b = bars[i]
            reason, price = mql_update_bar(
                pos, b[2], b[3], b[4], int(b[0]) * TF, TF,
                wick, trail_frac, pos["hold_sec"],
            )
            if reason is not None:
                if pos["armed"]:
                    armed += 1
                outcomes.append((pos["i"], reason, price, realized_r(pos, price)))
                pos = None
        if pos is None and i in entries:
            pos = open_state(entries[i], bars[i])
            pos["hold_sec"] = entries[i]["horizon_sec"]
    return outcomes, armed


def conversions(wick_out, grace_out):
    wick_stop = {e for e, r, _p, _x in wick_out if r == "STOP_HIT"}
    grace_exits = {e: (r, _x) for e, r, _p, _x in grace_out}
    converted_be = 0
    converted_other = 0
    stayed = 0
    for e in wick_stop:
        if e not in grace_exits:
            continue
        gr, _gx = grace_exits[e]
        if gr == "BREAKEVEN_TRAIL":
            converted_be += 1
        elif gr in ("TARGET_HIT", "TIME_EXIT"):
            converted_other += 1
        else:
            stayed += 1
    return dict(wick_stop=len(wick_stop), converted_be=converted_be,
                converted_other=converted_other, stayed_stop=stayed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-sec", type=int, default=3600)
    args = ap.parse_args()

    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    print(f"  bars={len(bars)}")
    with open(os.path.join(_HERE, "_sniper_capture.pkl"), "rb") as f:
        outcomes, geometry, signals, rejected, model = pickle.load(f)
    print(f"  cached capture: signals={signals} rejected={rejected} closed={len(outcomes)} model={model.version}")

    base = entry_set_from_capture(geometry, outcomes, bars)
    fixed = entry_set_from_capture(geometry, outcomes, bars, fixed_horizon_sec=args.horizon_sec)
    print(f"  replayable entries: {len(base)} (fixed horizon {args.horizon_sec}s = {args.horizon_sec/3600:.1f}h)")

    # baseline: realized-hold anchor (the grace probe's numbers)
    b_w, b_wa = run_lane(base, bars, wick=True, trail_frac=0.0)
    b_g, b_ga = run_lane(base, bars, wick=False, trail_frac=TRAIL)
    b_c = conversions(b_w, b_g)

    # fixed-horizon lanes
    f_w, f_wa = run_lane(fixed, bars, wick=True, trail_frac=0.0)
    f_g, f_ga = run_lane(fixed, bars, wick=False, trail_frac=TRAIL)
    f_c = conversions(f_w, f_g)

    print("\n=== exit-reason split (fixed 1h horizon) ===")
    print_split("WICK (Python journal)", split_stats(f_w))
    print_split("GRACE (closed-candle + trail)", split_stats(f_g))

    print("\n=== grace accounting: realized-hold vs fixed-1h ===")
    print(f"  {'':<18} {'realized-hold':>13} {'fixed-1h':>9}")
    print(f"  {'wick STOP_HIT':<18} {b_c['wick_stop']:>13} {f_c['wick_stop']:>9}")
    print(f"  {'-> BREAKEVEN_TRAIL':<18} {b_c['converted_be']:>13} {f_c['converted_be']:>9}")
    print(f"  {'-> TARGET/TIME':<18} {b_c['converted_other']:>13} {f_c['converted_other']:>9}")
    print(f"  {'-> still stopped':<18} {b_c['stayed_stop']:>13} {f_c['stayed_stop']:>9}")
    print(f"  {'trail-armed':<18} {b_ga:>13} {f_ga:>9}")
    b_sum = sum(x for _e, _r, _p, x in b_g)
    f_sum = sum(x for _e, _r, _p, x in f_g)
    f_wsum = sum(x for _e, _r, _p, x in f_w)
    print(f"  sumR wick={f_wsum:+.2f} | grace realized-hold={b_sum:+.2f} | grace fixed-1h={f_sum:+.2f} "
          f"(delta={f_sum - b_sum:+.2f})")
    print(f"\n[P10E-SNIPER-TIMEEXIT] horizon={args.horizon_sec} wick_stop={f_c['wick_stop']} "
          f"converted_be={f_c['converted_be']} converted_other={f_c['converted_other']} "
          f"stayed_stop={f_c['stayed_stop']} armed={f_ga} "
          f"base_converted_be={b_c['converted_be']} base_converted_other={b_c['converted_other']} "
          f"base_stayed={b_c['stayed_stop']} base_armed={b_ga}")


if __name__ == "__main__":
    main()
