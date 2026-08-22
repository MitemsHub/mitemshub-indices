#!/usr/bin/env python3
"""P10-E follow-up: quantify closed-candle grace on the SNIPER leg.

Captures the REAL sniper entry set via the production run_ticks path
(``run_sniper_ticks_captured`` — the exact leg the head-to-head runs), then
replays every captured entry over the same M5 bar series under TWO exit
policies, with the position geometry (entry/stop/target/horizon) unchanged:

  lane WICK  : the Python PaperBroker semantics (wick trade-throughs,
               stop-first, no trail) — the ``Python journal`` baseline.
  lane GRACE : the EA/phase-7 production management config (closed-candle
               exits + BE trail at 0.3 x planned RR) — the ``MQL5`` lane.

The ONLY difference between lanes is the exit policy, so the delta isolates
the grace: how many wick stop-outs convert to BREAKEVEN_TRAIL (or survive to
target/time) on the sniper's tighter-stop entries.  Reports the exit-reason
split, the conversion counts, and the sumR delta on the same entry set.
"""

import os
import pickle
import sys
from collections import Counter

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

TRAIL = 0.3   # BAND_TRAIL_FRAC (Constants.mqh) — the EA/phase-7 production trail


def entry_set_from_capture(geometry, outcomes, bars):
    """Build {entry_bar_index: geometry} from the captured sniper positions.

    Each captured outcome's position_id maps to geometry
    (entry, stop, target, dir).  The position opened at outcome.opened_at
    (the close of the entry bucket), so the first bar that can exit it is
    the NEXT bucket after entry — exactly the phase-7 lane lifecycle.
    """
    bucket_index = {b[0]: i for i, b in enumerate(bars)}   # bucket -> bars idx
    entry_by_bar = {}
    for o in outcomes:
        geo = geometry.get(o.position_id)
        if geo is None:
            continue
        entry, stop, target, d = geo
        entry_bucket = int(o.opened_at // TF)
        # The entry fires at the close of the entry bucket; the position is
        # 'open' starting the next bar.  Key by the NEXT bar index so the
        # lane opens it exactly one bar after the signal (same as the
        # phase-7 harness and PaperBroker: on_candle(primary) closes old,
        # then submit happens on the same candle — the exit checks then
        # begin on the following candle).
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


def run_lane(entries, bars, wick, trail_frac):
    """Phase-7 lane replay over the bar series for the captured entry set.

    Returns (outcomes, armed_count, stop_meta) where stop_meta maps each
    STOP_HIT entry bar -> bool: True when the EXIT BAR's close also traded
    through the stop (a close-through), False when only the wick touched it
    (a wick-only touch that closed back inside — the population the
    closed-candle grace could theoretically save).
    """
    pos = None
    outcomes = []                      # (entry_bar, reason, exit_price, r)
    armed = 0
    stop_meta = {}
    for i in range(len(bars)):
        if pos is not None:
            b = bars[i]
            reason, price = mql_update_bar(
                pos, b[2], b[3], b[4], int(b[0]) * TF, TF,
                wick, trail_frac, pos["hold_sec"],
            )
            if reason is not None:
                was_armed = pos["armed"]
                if was_armed:
                    armed += 1        # positions that ever crossed the arm line
                outcomes.append((pos["i"], reason, price, realized_r(pos, price)))
                if reason == "STOP_HIT":
                    long = pos["dir"] > 0
                    close_through = (b[4] <= pos["stop"]) if long else (b[4] >= pos["stop"])
                    stop_meta[pos["i"]] = close_through
                pos = None
        if pos is None and i in entries:
            pos = open_state(entries[i], bars[i])
            pos["hold_sec"] = entries[i]["horizon_sec"]
    return outcomes, armed, stop_meta


def main():
    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    print(f"  bars={len(bars)}")
    ticks = dedupe_ticks(load_ticks_csv(
        os.path.join(_HERE, "data", "backfill", "R_75_ticks.csv"),
        default_symbol="R_75",
    ))
    cache = os.path.join(_HERE, "_sniper_capture.pkl")
    if os.path.exists(cache):
        print("loading cached sniper capture ...")
        with open(cache, "rb") as f:
            outcomes, geometry, signals, rejected, model = pickle.load(f)
    else:
        print("capturing REAL sniper entry set (run_ticks production path)...")
        outcomes, broker, signals, rejected, model = run_sniper_ticks_captured(ticks, timeframe_sec=300)
        geometry = broker.geometry
        with open(cache, "wb") as f:
            pickle.dump((outcomes, geometry, signals, rejected, model), f)
        print(f"  capture cached -> {cache}")
    print(f"  captured: signals={signals} rejected={rejected} closed={len(outcomes)} model={model.version}")

    entries = entry_set_from_capture(geometry, outcomes, bars)
    print(f"  replayable entries: {len(entries)}")

    wick_out, wick_armed, wick_meta = run_lane(entries, bars, wick=True, trail_frac=0.0)
    grace_out, grace_armed, grace_meta = run_lane(entries, bars, wick=False, trail_frac=TRAIL)

    print("\n=== exit-reason split (same sniper entry set) ===")
    print_split("WICK (Python journal)", split_stats(wick_out))
    print_split("GRACE (EA closed-candle + trail)", split_stats(grace_out))

    # Conversion accounting: every wick STOP_HIT trade that the grace lane
    # did NOT stop out at the original stop either armed to breakeven or
    # survived to target/time.
    wick_stop_idx = {e for e, r, _p, _x in wick_out if r == "STOP_HIT"}
    grace_exits = {e: (r, _x) for e, r, _p, _x in grace_out}
    converted_be = 0
    converted_other = 0
    stayed_stop = 0
    for e in wick_stop_idx:
        if e not in grace_exits:
            continue
        gr, gx = grace_exits[e]
        if gr == "BREAKEVEN_TRAIL":
            converted_be += 1
        elif gr in ("TARGET_HIT", "TIME_EXIT"):
            converted_other += 1
        else:
            stayed_stop += 1

    # Mechanism: of the wick stop-outs, how many were wick-ONLY touches
    # (low/high crossed the stop but the close stayed inside) vs
    # close-throughs (the close itself violated the stop)?  Only the former
    # are even theoretically savable by the closed-candle grace.
    wick_only = sum(1 for e in wick_stop_idx if wick_meta.get(e) is False)
    close_through = sum(1 for e in wick_stop_idx if wick_meta.get(e) is True)
    # Of the wick-only touches, how many did the grace lane actually save?
    saved_of_wick_only = sum(1 for e in wick_stop_idx
                             if wick_meta.get(e) is False and e in grace_exits
                             and grace_exits[e][0] in ("BREAKEVEN_TRAIL", "TARGET_HIT", "TIME_EXIT"))

    wick_sum = sum(x for _e, _r, _p, x in wick_out)
    grace_sum = sum(x for _e, _r, _p, x in grace_out)
    print(f"\n=== grace accounting (wick stop-outs) ===")
    print(f"  wick STOP_HIT total       : {len(wick_stop_idx)}")
    print(f"    -> grace BREAKEVEN_TRAIL: {converted_be}  (converted -1R -> ~0R)")
    print(f"    -> grace TARGET/TIME    : {converted_other}  (converted -1R -> +RR/time)")
    print(f"    -> still stopped out    : {stayed_stop}")
    print(f"\n=== mechanism: wick-only touch vs close-through ===")
    print(f"  wick-only touches (grace-savable): {wick_only}")
    print(f"  close-throughs (grace cannot help) : {close_through}")
    print(f"  wick-only touches the grace SAVED  : {saved_of_wick_only}")
    print(f"\n=== trail arming (0.3 x planned RR = {0.3 * 1.9:.2f}R arm line) ===")
    print(f"  positions that armed (wick lane) : {wick_armed} / {len(wick_out)}")
    print(f"  positions that armed (grace lane): {grace_armed} / {len(grace_out)}")
    print(f"  (armed -> exit = BREAKEVEN_TRAIL unless target hit first)")
    print(f"  sumR wick={wick_sum:+.2f} | grace={grace_sum:+.2f} | delta={grace_sum - wick_sum:+.2f}")
    print(f"[P10E-SNIPER] wick_stop={len(wick_stop_idx)} converted_be={converted_be} "
          f"converted_other={converted_other} stayed_stop={stayed_stop} "
          f"wick_only={wick_only} close_through={close_through} saved_of_wick_only={saved_of_wick_only} "
          f"armed_w={wick_armed} armed_g={grace_armed} "
          f"sumR_wick={wick_sum:+.2f} sumR_grace={grace_sum:+.2f}")


if __name__ == "__main__":
    main()
