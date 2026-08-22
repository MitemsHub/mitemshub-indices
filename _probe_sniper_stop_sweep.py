#!/usr/bin/env python3
"""P10-E follow-up: stop-distance sweep + still-stopped MFE on the sniper leg.

Uses the CACHED sniper capture (_sniper_capture.pkl — the real captured
entry set via run_ticks) and the same lane machinery as _probe_sniper_grace.py:

  lane WICK  : Python PaperBroker semantics (wick trade-throughs, no trail).
  lane GRACE : EA/phase-7 production management (closed-candle exits + BE
               trail at 0.3 x planned RR).

Section A (MFE): on the BASE geometry (1R stop, RR 1.9, realized-hold
horizon), how close did the GRACE lane's still-stopped trades come to the
0.57R arm line before dying?  All of them peaked BELOW 0.57R (a trade that
armed would exit BREAKEVEN_TRAIL, never STOP_HIT), so the question is the
gap distribution — how much tighter the trail would need to arm to catch them.

Section B (stop sweep): scale the stop distance from 1R out to 2R (the stop
moves to entry -/+ m*R0) with the target scaled to keep RR in 3-4, and re-run
both lanes per cell.  Reports where wick-stop conversions first appear and
where the wick-only-touch share of stop-outs rises enough for the closed-
candle grace to convert meaningful trades.

Usage: python _probe_sniper_stop_sweep.py [--rr 3.0,3.5,4.0]
"""

import argparse
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

TRAIL = 0.3          # BAND_TRAIL_FRAC — the EA/phase-7 production trail
BASE_RR = 1.9        # sniper capture's realized planned RR (arm line 0.57R)
ARM_LINE_R = TRAIL * BASE_RR   # 0.57R — the base-geometry trail arm line


def entry_set_from_capture(geometry, outcomes, bars):
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


def scale_entries(entries, stop_mult, rr):
    """Return new entry dicts with the stop moved to stop_mult*R0 and the
    target scaled to keep the planned RR == rr.  Geometry of the other knobs
    (horizon, entry, direction) is unchanged."""
    out = {}
    for k, e in entries.items():
        risk0 = abs(e["close"] - e["stop"])
        if risk0 <= 0.0:
            risk0 = e["close"] * 0.001
        d = 1 if e["direction"] == Direction.LONG else -1
        new = dict(e)
        new["stop"] = e["close"] - d * stop_mult * risk0
        new["target"] = e["close"] + d * stop_mult * risk0 * rr
        out[k] = new
    return out


def run_lane_full(entries, bars, wick, trail_frac):
    """Lane replay that ALSO records MFE/MAE (in R) and the exit bar index.

    Returns (outcomes, armed, stop_meta) where outcomes entries are
    (entry, reason, exit_price, r, mfe_r, mae_r, exit_bar) and stop_meta maps
    STOP_HIT entry -> True when the exit bar's CLOSE also violated the stop
    (a close-through) vs False (a wick-only touch that closed back inside).
    """
    pos = None
    outcomes = []
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
                if pos["armed"]:
                    armed += 1
                mfe_r = pos["mfe"] / pos["risk"] if pos["risk"] > 0.0 else 0.0
                mae_r = pos["mae"] / pos["risk"] if pos["risk"] > 0.0 else 0.0
                outcomes.append((pos["i"], reason, price, realized_r(pos, price),
                                 mfe_r, mae_r, i))
                if reason == "STOP_HIT":
                    long = pos["dir"] > 0
                    close_through = (b[4] <= pos["stop"]) if long else (b[4] >= pos["stop"])
                    stop_meta[pos["i"]] = close_through
                pos = None
        if pos is None and i in entries:
            pos = open_state(entries[i], bars[i])
            pos["hold_sec"] = entries[i]["horizon_sec"]
    return outcomes, armed, stop_meta


def conversion_accounting(wick_out, grace_out, wick_meta):
    """Wick stop-outs -> grace conversions + the wick-only mechanism split."""
    wick_stop = {e for e, _r, _p, _x, _mf, _ma, _i in wick_out if _r == "STOP_HIT"}
    grace_exits = {e: (r, x) for e, r, x, _p, _mf, _ma, _i in grace_out}
    converted_be = 0
    converted_other = 0
    stayed_stop = 0
    for e in wick_stop:
        if e not in grace_exits:
            continue
        gr, _gx = grace_exits[e]
        if gr == "BREAKEVEN_TRAIL":
            converted_be += 1
        elif gr in ("TARGET_HIT", "TIME_EXIT"):
            converted_other += 1
        else:
            stayed_stop += 1
    wick_only = sum(1 for e in wick_stop if wick_meta.get(e) is False)
    close_through = sum(1 for e in wick_stop if wick_meta.get(e) is True)
    saved_of_wick_only = sum(1 for e in wick_stop
                             if wick_meta.get(e) is False and e in grace_exits
                             and grace_exits[e][0] in ("BREAKEVEN_TRAIL", "TARGET_HIT", "TIME_EXIT"))
    return dict(wick_stop=len(wick_stop), converted_be=converted_be,
                converted_other=converted_other, stayed_stop=stayed_stop,
                wick_only=wick_only, close_through=close_through,
                saved_of_wick_only=saved_of_wick_only)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rr", default="3.0,3.5,4.0", help="comma-separated planned RR values for the target scaling")
    ap.add_argument("--stop-mults", default="1.0,1.25,1.5,1.75,2.0")
    args = ap.parse_args()
    rrs = [float(x) for x in args.rr.split(",") if x.strip()]
    stop_mults = [float(x) for x in args.stop_mults.split(",") if x.strip()]

    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    print(f"  bars={len(bars)}")
    cache = os.path.join(_HERE, "_sniper_capture.pkl")
    with open(cache, "rb") as f:
        outcomes, geometry, signals, rejected, model = pickle.load(f)
    print(f"  cached capture: signals={signals} rejected={rejected} closed={len(outcomes)} model={model.version}")

    entries = entry_set_from_capture(geometry, outcomes, bars)
    print(f"  replayable entries: {len(entries)}")

    # ── Section A: MFE of the grace lane's still-stopped trades (base geometry)
    print("\n=== A. MFE distribution of still-stopped trades (base geometry: 1R stop, "
          f"RR {BASE_RR}, arm line {ARM_LINE_R:.2f}R) ===")
    wick_out, _a, wick_meta = run_lane_full(entries, bars, wick=True, trail_frac=0.0)
    grace_out, grace_armed, _m = run_lane_full(entries, bars, wick=False, trail_frac=TRAIL)
    print_split("WICK (Python journal)", split_stats([(e, r, p, x) for e, r, p, x, _mf, _ma, _i in wick_out]))
    print_split("GRACE (closed-candle + trail)", split_stats([(e, r, p, x) for e, r, p, x, _mf, _ma, _i in grace_out]))

    stopped = [(e, mfe_r) for e, r, _p, _x, mfe_r, _ma, _i in grace_out if r == "STOP_HIT"]
    n_stopped = len(stopped)
    if n_stopped:
        mfes = sorted(m for _e, m in stopped)
        n_quart = len(mfes)
        q = lambda pct: mfes[min(n_quart - 1, int(pct * n_quart))]
        peak = max(mfes)
        mean = sum(mfes) / n_quart
        print(f"  grace still-stopped: {n_stopped} (wick lane stop-outs: "
              f"{sum(1 for _e, r, *_ in wick_out if r == 'STOP_HIT')})")
        print(f"  peak-MFE: p25={q(0.25):.3f}R p50={q(0.50):.3f}R p75={q(0.75):.3f}R "
              f"max={peak:.3f}R mean={mean:.3f}R (all below the {ARM_LINE_R:.2f}R arm line by construction)")
        # How much tighter the trail would need to arm to catch them: the
        # share of stopped trades that peaked within X of the arm line.
        for frac in (0.90, 0.75, 0.50, 0.25):
            thresh = ARM_LINE_R * frac
            caught = sum(1 for _e, m in stopped if m >= thresh)
            print(f"    would-arm at {thresh:.3f}R ({frac*100:.0f}% of arm line): catches {caught}/{n_stopped} "
                  f"({100.0*caught/n_stopped:.1f}%)")
        arm_gap = [ARM_LINE_R - m for _e, m in stopped]
        print(f"    arm-line gap (how much tighter): median {sorted(arm_gap)[n_quart//2]:.3f}R, "
              f"p25 {sorted(arm_gap)[int(0.25*n_quart)]:.3f}R, min {min(arm_gap):.3f}R")
    else:
        print("  no still-stopped trades on the base geometry")

    # ── Section B: stop-distance sweep under the closed-candle grace lane
    print("\n=== B. stop-distance sweep (1R -> 2R, target scaled to keep RR "
          f"{min(rrs)}-{max(rrs)}) ===")
    print(f"  {'m':>4} {'rr':>4} {'wick_n':>6} {'wick_stop':>8} {'wick_only':>9} "
          f"{'close_thr':>9} {'wo_share':>8} {'conv_be':>7} {'conv_other':>10} "
          f"{'stayed':>6} {'saved_wo':>8}")
    onset = None
    first_meaningful = None
    rows = []
    for m in stop_mults:
        scaled = scale_entries(entries, m, rrs[0] if len(rrs) == 1 else BASE_RR)  # placeholder, replaced below
        for rr in rrs:
            scaled = scale_entries(entries, m, rr)
            w_o, _a, w_m = run_lane_full(scaled, bars, wick=True, trail_frac=0.0)
            g_o, _a2, _m2 = run_lane_full(scaled, bars, wick=False, trail_frac=TRAIL)
            acct = conversion_accounting(w_o, g_o, w_m)
            wo_share = (100.0 * acct["wick_only"] / acct["wick_stop"]) if acct["wick_stop"] else 0.0
            rows.append((m, rr, acct))
            converted = acct["converted_be"] + acct["converted_other"]
            if converted > 0 and onset is None:
                onset = (m, rr, converted)
            if converted >= 5 and first_meaningful is None:
                first_meaningful = (m, rr, converted, wo_share)
            print(f"  {m:>4.2f} {rr:>4.1f} {len(w_o):>6} {acct['wick_stop']:>8} "
                  f"{acct['wick_only']:>9} {acct['close_through']:>9} {wo_share:>7.1f}% "
                  f"{acct['converted_be']:>7} {acct['converted_other']:>10} "
                  f"{acct['stayed_stop']:>6} {acct['saved_of_wick_only']:>8}")
    print(f"\n  wick-stop conversions first appear at: "
          f"{onset if onset else 'NONE in the swept range'}")
    print(f"  first cell with >=5 conversions (meaningful): "
          f"{first_meaningful if first_meaningful else 'NONE in the swept range'}")
    if onset:
        print(f"  -> at m={onset[0]:.2f} (RR {onset[1]:.1f}) the closed-candle grace starts converting "
              f"{onset[2]} wick stop-out(s); before that the sniper's stop-outs are close-throughs the grace cannot help.")

    # Machine lines for the gate/journal (tokens sign-optional, $NumTok-safe).
    if n_stopped:
        arm_gap_sorted = sorted(arm_gap)
        print(f"\n[P10E-SNIPER-MFE] still_stopped={n_stopped} arm_line={ARM_LINE_R:.2f} "
              f"peak_p25={q(0.25):.3f} peak_med={q(0.50):.3f} peak_max={peak:.3f} "
              f"catch_at_90={sum(1 for _e, m in stopped if m >= ARM_LINE_R*0.90)} "
              f"gap_med={arm_gap_sorted[n_quart//2]:.3f} gap_min={min(arm_gap_sorted):.3f}")
    for (m, rr, acct) in rows:
        print(f"[P10E-SNIPER-SWEEP] m={m:.2f} rr={rr:.1f} wick_stop={acct['wick_stop']} "
              f"wick_only={acct['wick_only']} close_through={acct['close_through']} "
              f"converted_be={acct['converted_be']} converted_other={acct['converted_other']} "
              f"stayed_stop={acct['stayed_stop']} saved_of_wick_only={acct['saved_of_wick_only']}")


if __name__ == "__main__":
    main()
