#!/usr/bin/env python3
"""P10-E follow-up: the BAND's own stop-outs under the close-vs-wick split.

The sniper probes found the closed-candle grace converts ~nothing on the
sniper's tight stops, and the ~92R Model=2 (OHLC) swing was framed as the
BAND's wick-save ceiling.  This probe measures the band's OWN real-tick
stop-outs with the same close-vs-wick classification and checks whether the
asymmetry the narrative implies (band stop-outs mostly wick-only) actually
holds at the same-bar M5 level.

The classification is BROKER-TRUTH: the broker records closed_at = the exit
candle's close time, so the exit candle is known exactly (bucket
int(closed_at // TF)) and its CLOSE (from the corpus M5 bars) decides the
split.  A stop-out is wick-only when the exit candle's extreme crossed the
stop but its close stayed inside.  STOP_HIT is detected from the fill price
(with slippage absorbed by a 5%-of-risk band) plus the exit candle's extreme
crossing the ORIGINAL stop.

Note on the replay-based probes (_probe_sniper_grace.py and friends): their
lane opens positions one bar AFTER the broker's first exit-checkable candle,
so they classify a DIFFERENT (later) bar for the same trade and OVERSTATE
the same-bar close-through share.  The numbers here are the broker-truth
same-bar split; the replay family's conclusion (grace converts ~nothing on
the sniper) is unchanged — the wick-only touches close-cross within a bar or
two, and at the tester's 1-min close resolution 0-1 of 129 are saved
(_probe_sniper_ohlc.py).

Usage: python _probe_band_stop_class.py
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src"))
sys.path.insert(0, os.path.join(_HERE, "mql5"))

from tradequality_real_corpus_check import (  # noqa: E402
    CORPUS_PATHS,
    TF,
    VolBandStrategy,
    VolBandConfig,
    clear_assembler_caches,
    dedupe_ticks,
    load_calibrated_garch_state,
    load_ticks_csv,
    run_sniper_ticks_captured,
    run_strategy,
)
from phase7_real_corpus_check import load_m5_bars  # noqa: E402


def classify_stop_outs(name, outcomes, geometry, bars, bucket_index):
    """Broker-truth same-bar close-vs-wick split of the real-tick stop-outs."""
    stops = 0
    wick_only = 0
    close_through = 0
    unclass = 0
    for o in outcomes:
        geo = geometry.get(o.position_id)
        if geo is None:
            continue
        entry, stop, target, d = geo
        risk = abs(entry - stop) or entry * 0.001
        long = d > 0
        if abs(o.exit - stop) > 0.05 * risk:
            continue
        if abs(o.exit - entry) <= 0.05 * risk:
            continue   # armed BREAKEVEN_TRAIL fill, not a stop-out
        eb = int(o.closed_at // TF)
        bi = bucket_index.get(eb)
        if bi is None or bi >= len(bars):
            unclass += 1
            continue
        bar = bars[bi]
        crossed = (bar[3] <= stop) if long else (bar[2] >= stop)
        if not crossed:
            unclass += 1
            continue
        stops += 1
        ct = (bar[4] <= stop) if long else (bar[4] >= stop)
        if ct:
            close_through += 1
        else:
            wick_only += 1
    share = 100.0 * wick_only / max(1, stops)
    print(f"\n=== {name}: real-tick stop-outs (broker-truth same-bar split) ===")
    print(f"  STOP_HIT total   : {stops}")
    print(f"    wick-only      : {wick_only}  ({share:.1f}%)")
    print(f"    close-throughs : {close_through}  ({100.0 - share:.1f}%)")
    print(f"    (unclassified  : {unclass})")
    return stops, wick_only, close_through


def main():
    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    bucket_index = {b[0]: i for i, b in enumerate(bars)}
    print(f"  bars={len(bars)}")
    ticks = dedupe_ticks([
        t for p in CORPUS_PATHS if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    print(f"  ticks={len(ticks)}")

    # --- sniper comparison leg (fresh capture, same union corpus) -----------
    print("\n--- SNIPER (fresh capture, same corpus) ---")
    clear_assembler_caches()
    s_out, s_broker, _sig, _rej, _model = run_sniper_ticks_captured(ticks, 300)
    print(f"  capture: closed={len(s_out)}")
    s_stops, s_wo, s_ct = classify_stop_outs(
        "SNIPER", s_out, s_broker.geometry, bars, bucket_index)

    # --- band leg (production VolBandStrategy) ------------------------------
    print("\n--- BAND (production VolBandStrategy, real corpus) ---")
    clear_assembler_caches()
    garch_state = load_calibrated_garch_state("R_75")
    print(f"  calibrated R_75 garch: {'loaded' if garch_state else 'not_found (default priors)'}")
    outcomes, broker, trail_frac = run_strategy(
        "band", VolBandStrategy, VolBandConfig, ticks, garch_state)
    print(f"  capture: closed={len(outcomes)} trail_frac={trail_frac}")
    b_stops, b_wo, b_ct = classify_stop_outs(
        "BAND", outcomes, broker.geometry, bars, bucket_index)

    print(f"\n[P10E-BAND] sniper_stop={s_stops} sniper_wo={s_wo} sniper_ct={s_ct} "
          f"band_stop={b_stops} band_wo={b_wo} band_ct={b_ct} "
          f"band_wo_share={100.0 * b_wo / max(1, b_stops):.1f}")


if __name__ == "__main__":
    main()
