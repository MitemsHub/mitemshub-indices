#!/usr/bin/env python3
"""Time-exit horizon sweep on the sniper leg.

The harness's adopted time-exit uses ``signal.horizon_sec`` (= the profile's
band_hold_horizon_sec, 7200s / 2h — the "mean positive-drift horizon" the
journal's TIME exits measured at +0.394R).  This probe sweeps the EXIT
horizon while keeping every other knob identical (same 1R band stop, target
ignored by the time-exit broker, same UTC entry gate, fresh online model per
run): 4h, 3h, 2h (baseline), 1.5h, 1h.

Because the broker is single-position, a shorter horizon frees the slot
sooner -> more entries fit the corpus, so n grows as the horizon shrinks.
Per-trade net = gross - cost (0.05/0.10 R); TOTAL net = n*(gross - cost),
so if n differs the cost-optimum can move away from the gross-optimum.

Usage: python _probe_time_exit_sweep.py
"""
import os
import sys
from statistics import mean

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "mql5"))
sys.path.insert(0, os.path.join(_HERE, "src"))

import tradequality_real_corpus_check as tqc  # noqa: E402
from tradequality_real_corpus_check import (  # noqa: E402
    TimeExitCapturePaperBroker,
    clear_assembler_caches,
    dedupe_ticks,
    load_ticks_csv,
    run_sniper_ticks_captured,
    CORPUS_PATHS,
)
from synthetic_trader.domain import Direction  # noqa: E402

HORIZONS = [14400, 10800, 7200, 5400, 3600]  # 4h, 3h, 2h (baseline), 1.5h, 1h
COSTS = (0.05, 0.10)


class FixedHorizonBroker(TimeExitCapturePaperBroker):
    """Time-exit broker with a fixed horizon (parent uses signal.horizon_sec)."""

    def __init__(self, config, horizon_sec):
        super().__init__(config)
        self._fixed_horizon_sec = horizon_sec

    def _maybe_close(self, position, candle):
        pid = position.id
        self.paths[pid].append((candle.high, candle.low))
        signal = position.signal
        risk = abs(signal.entry - signal.stop_loss)
        if risk <= 0.0:
            risk = signal.entry * 0.001
        if signal.direction is Direction.LONG:
            mfe = (candle.high - signal.entry) / risk
        else:
            mfe = (signal.entry - candle.low) / risk
        self._own_mfe[pid] = max(self._own_mfe.get(pid, 0.0), mfe)
        expired = (candle.open_time + candle.timeframe_sec
                   >= signal.snapshot.epoch + self._fixed_horizon_sec)
        if signal.direction is Direction.LONG:
            stop_hit = candle.low <= signal.stop_loss
        else:
            stop_hit = candle.high >= signal.stop_loss
        outcome = None
        if stop_hit:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.stop_loss),
                candle.open_time + candle.timeframe_sec,
            )
        elif expired:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, candle.close),
                candle.open_time + candle.timeframe_sec,
            )
        if outcome is not None:
            self.mfe_at_close[pid] = self._own_mfe[pid]
        return outcome


def run_cell(ticks, horizon_sec):
    tqc.TimeExitCapturePaperBroker = (
        lambda config, h=horizon_sec: FixedHorizonBroker(config, h)
    )
    clear_assembler_caches()
    outcomes, broker, signals, rejected, model = run_sniper_ticks_captured(
        ticks, 300, time_exit=True)
    n = len(outcomes)
    hit = (sum(1 for o in outcomes if o.won) / n) if n else 0.0
    gross = mean(o.return_r for o in outcomes) if n else 0.0
    holds = []
    for o in outcomes:
        entry, stop, target, _ = broker.geometry[o.position_id]
        risk = abs(entry - stop) or entry * 0.001
        holds.append((o.closed_at - o.opened_at) / 3600.0)
    ordered = sorted(outcomes, key=lambda o: o.closed_at)
    peak = cum = max_dd = 0.0
    for o in ordered:
        cum += o.return_r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "h": horizon_sec,
        "n": n,
        "hit": hit,
        "gross": gross,
        "avg_hold_h": mean(holds) if holds else 0.0,
        "max_dd": max_dd,
    }


def main():
    ticks = dedupe_ticks([
        t for p in CORPUS_PATHS if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    span = (max(t.epoch for t in ticks) - min(t.epoch for t in ticks)) / 86400
    print(f"[TIMEEXIT] loaded {len(ticks)} R_75 ticks ({span:.2f} days)")
    print(f"[TIMEEXIT] horizon sweep (baseline 2h = adopted mean-drift horizon):")
    rows = []
    for h in HORIZONS:
        r = run_cell(ticks, h)
        rows.append(r)
        print(f"[TIMEEXIT] {h / 3600:.1f}h: n={r['n']:>4} hit={r['hit']*100:5.1f}% "
              f"gross={r['gross']:+.3f}R avg_hold={r['avg_hold_h']:.2f}h "
              f"maxDD={r['max_dd']:.1f}R", flush=True)

    print(f"\n[TIMEEXIT] per-trade AND total net (costs {COSTS}):")
    print(f"[TIMEEXIT] {'h':>4} {'n':>4} {'gross':>7} {'net@.05':>8} {'net@.10':>8} "
          f"{'tot@.05':>9} {'tot@.10':>9}")
    for r in rows:
        print(f"[TIMEEXIT] {r['h'] / 3600:>4.1f} {r['n']:>4} {r['gross']:>+7.3f} "
              f"{r['gross'] - COSTS[0]:>+8.3f} {r['gross'] - COSTS[1]:>+8.3f} "
              f"{r['n'] * (r['gross'] - COSTS[0]):>+9.1f} "
              f"{r['n'] * (r['gross'] - COSTS[1]):>+9.1f}")

    g_peak = max(rows, key=lambda r: r["gross"])
    n_peak = max(rows, key=lambda r: r["n"] * (r["gross"] - COSTS[0]))
    print(f"\n[TIMEEXIT] gross-optimum: {g_peak['h'] / 3600:.1f}h "
          f"(gross {g_peak['gross']:+.3f}R, n={g_peak['n']})")
    print(f"[TIMEEXIT] total-net@0.05 optimum: {n_peak['h'] / 3600:.1f}h "
          f"(tot {n_peak['n'] * (n_peak['gross'] - COSTS[0]):+.1f}R, "
          f"gross {n_peak['gross']:+.3f}R, n={n_peak['n']})")


if __name__ == "__main__":
    main()
