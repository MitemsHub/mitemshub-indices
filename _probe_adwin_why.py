#!/usr/bin/env python3
"""Why ADWIN never fires on R_75 M5 returns — and is the error-based
detector a usable regime/entry-timing signal instead?

Part A — return stream (the band/reversion drift gate feeds |log_return|*100
through DriftDetector(delta=0.002)):
  * count fires on the full corpus (docs: 0 in 2,338 bars on 9.5 days)
  * stream stats (mean/std/p99 of |r|%, rolling-mean range = the real
    vol-regime signal magnitude)
  * the ADWIN detectability floor: at sampled bars, for equal adjacent
    halves of size m, compare the observed |mean shift| against the
    standard cutoff eps = sqrt((2*sigma2/m)*ln(2/delta)) + (2/(3m))*ln(2/delta)
    using the window's actual variance — the margin shows HOW FAR from
    firing the stream sits.

Part B — the model's error stream (OnlineLogisticModel feeds
abs(label - p) to its own DriftDetector on every taken-trade update):
  * run the real sniper capture with a recording model; report drift
    events / resets / fire-rate vs the return stream
  * split trades by steps-since-last-drift at entry (cooldown vs stable)
    and compare hit / expectancy — is the post-drift window a usable
    "stand aside" entry filter?

Usage: python _probe_adwin_why.py [--timeframe 300]
"""
import argparse
import math
import os
import sys
from statistics import mean, pstdev

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "mql5"))
sys.path.insert(0, os.path.join(_HERE, "src"))

import tradequality_real_corpus_check as tqc  # noqa: E402
from tradequality_real_corpus_check import (  # noqa: E402
    clear_assembler_caches,
    dedupe_ticks,
    load_ticks_csv,
    run_sniper_ticks_captured,
    CORPUS_PATHS,
)
from synthetic_trader.data.candles import CandleBuilder  # noqa: E402
from synthetic_trader.models.drift import DriftDetector  # noqa: E402
from synthetic_trader.models.online import OnlineLogisticModel  # noqa: E402

DRIFT_PCT_SCALE = 100.0  # same as vol_band / vol_reversion
DELTA = 0.002


def adwin_eps(sigma2, m, n, delta=DELTA):
    """Standard ADWIN cutoff for a split of size m in a window of size n."""
    ln_ = math.log(4.0 * n / delta) if n > 0 else math.log(2.0 / delta)
    return math.sqrt(2.0 * sigma2 / m * ln_) + (2.0 / (3.0 * m)) * ln_


def part_a(ticks):
    """Return-stream ADWIN: fires, stats, and the detectability margin."""
    builder = CandleBuilder(symbol="R_75", timeframe_sec=300)
    candles = []
    for t in ticks:
        c = builder.update(t)
        if c is not None:
            candles.append(c)
    c = builder.flush()
    if c is not None:
        candles.append(c)

    det = DriftDetector(delta=DELTA)
    stream = []
    fires = 0
    fire_bars = []
    prev_close = None
    for i, candle in enumerate(candles):
        if prev_close is None or prev_close <= 0.0:
            prev_close = candle.close
            continue
        lr = math.log(candle.close / prev_close)
        prev_close = candle.close
        v = abs(lr) * DRIFT_PCT_SCALE
        stream.append(v)
        if det.observe(v):
            fires += 1
            fire_bars.append(i)

    n = len(stream)
    s_mean = mean(stream)
    s_std = pstdev(stream)
    s_p99 = sorted(stream)[int(n * 0.99)] if n else 0.0
    roll = [mean(stream[max(0, i - 249): i + 1]) for i in range(249, n, 25)]
    print(f"\n[ADWIN-A] return stream: {n} M5 bars, fires={fires} "
          f"({', '.join(str(b) for b in fire_bars[:10]) or 'none'})")
    print(f"[ADWIN-A] |r|%%: mean={s_mean:.3f} std={s_std:.3f} p99={s_p99:.3f} "
          f"(pct units, x100)")
    if roll:
        print(f"[ADWIN-A] rolling 250-bar mean |r|%%: range "
              f"{min(roll):.3f} .. {max(roll):.3f} "
              f"(the vol-regime signal ADWIN must catch is ~{max(roll) - min(roll):.2f})")

    # Detectability margin: at sampled bars, adjacent equal halves of size m.
    sigma2_hat = s_std ** 2
    print(f"[ADWIN-A] cutoff eps(m) with window sigma={s_std:.3f}, delta={DELTA}:")
    margins = {}
    for m in (10, 25, 50, 100, 250):
        eps_m = adwin_eps(sigma2_hat, m, n)
        # Max observed shift over the corpus for equal adjacent halves of size m.
        best = 0.0
        for i in range(249 + m, n, 25):
            a = mean(stream[i - m: i])
            b = mean(stream[i: i + m])
            best = max(best, abs(a - b))
        margins[m] = best / eps_m if eps_m > 0 else float("inf")
        print(f"[ADWIN-A]   m={m:>4}: eps={eps_m:.3f}  max observed "
              f"shift={best:.3f}  ratio={margins[m]:.2f} "
              f"({'BELOW floor' if margins[m] < 1.0 else 'ABOVE floor!'})")
    return {"n": n, "fires": fires, "margins": margins}


class RecordingModel(OnlineLogisticModel):
    """Records the error stream and drift-fire update indices."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_stream = []          # abs(label - p) per update
        self.drift_fire_updates = []    # self.updates when a drift fired

    def update(self, features, label, sample_weight=1.0, *, observe_drift=True):
        proba = self.predict_proba(features)
        err = abs(float(label) - proba)
        before = self.drift_detector.drift_events
        result = super().update(features, label, sample_weight=sample_weight,
                                observe_drift=observe_drift)
        self.error_stream.append(err)
        if self.drift_detector.drift_events > before:
            self.drift_fire_updates.append(self.updates)
        return result


def part_b(ticks, tf):
    """Error-stream ADWIN: fires, fire-rate, and cooldown-vs-stable split."""
    model = RecordingModel()
    clear_assembler_caches()
    outcomes, broker, signals, rejected, model2 = run_sniper_ticks_captured(
        ticks, tf, model=model)
    model = model2
    det = model.drift_detector
    n_upd = model.updates
    errs = model.error_stream
    fires = model.drift_fire_updates
    print(f"\n[ADWIN-B] model error stream: {n_upd} updates ({len(errs)} recorded), "
          f"drift_events={det.drift_events} drift_resets={model.drift_resets}")
    print(f"[ADWIN-B] drift fire update indices: {fires}")
    if errs:
        print(f"[ADWIN-B] |error|: mean={mean(errs):.3f} std={pstdev(errs):.3f} "
              f"max={max(errs):.3f} (bounded stream [0.08, 0.92])")
    # Per-trade attribution: model update k corresponds to the k-th CLOSED
    # outcome; a trade entered at opened_at sees the model state with all
    # updates whose close happened before it.
    closed = sorted(outcomes, key=lambda o: o.closed_at)
    fire_upd = set(model.drift_fire_updates)

    def steps_at_entry(o):
        k = sum(1 for c in closed if c.closed_at < o.opened_at)
        last = max([u for u in fire_upd if u <= k], default=None)
        return None if last is None else (k - last)

    rows = []
    for o in outcomes:
        s = steps_at_entry(o)
        rows.append({"r": o.return_r, "won": o.won, "steps": s})

    def stats(rs):
        n = len(rs)
        if n == 0:
            return (0, 0.0, 0.0)
        hit = sum(1 for r in rs if r["won"]) / n
        exp = mean(r["r"] for r in rs)
        return (n, hit * 100.0, exp)

    print(f"\n[ADWIN-B] trade split by steps-since-last-drift at entry "
          f"(fires={len(fire_upd)}):")
    for k in (0, 10, 30, 100, 500):
        cd = [r for r in rows if r["steps"] is not None and r["steps"] <= k]
        st = [r for r in rows if r["steps"] is None or r["steps"] > k]
        n1, h1, e1 = stats(cd)
        n2, h2, e2 = stats(st)
        print(f"[ADWIN-B]   steps<={k:>4}: n={n1:>4} hit={h1:5.1f}% exp={e1:+.3f}R  |  "
              f"stable: n={n2:>4} hit={h2:5.1f}% exp={e2:+.3f}R")
    alln, allh, alle = stats(rows)
    print(f"[ADWIN-B]   ALL    : n={alln:>4} hit={allh:5.1f}% exp={alle:+.3f}R")
    return {"n_upd": n_upd, "fires": len(fires), "events": det.drift_events}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", type=int, default=300)
    args = ap.parse_args()

    ticks = dedupe_ticks([
        t for p in CORPUS_PATHS if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    span = (max(t.epoch for t in ticks) - min(t.epoch for t in ticks)) / 86400
    print(f"[ADWIN] loaded {len(ticks)} R_75 ticks ({span:.2f} days)")

    a = part_a(ticks)
    b = part_b(ticks, args.timeframe)
    days = (max(t.epoch for t in ticks) - min(t.epoch for t in ticks)) / 86400
    print(f"\n[ADWIN] fire rates: return-stream {a['fires']}/{a['n']} bars "
          f"({a['fires'] / a['n'] * 100:.4f}%) vs error-stream {b['fires']}/"
          f"{b['n_upd']} model updates ({b['fires'] / b['n_upd'] * 100:.2f}% "
          f"= {b['events'] / days:.2f}/day)")
    worst = max(a["margins"].values())
    print(f"[ADWIN] worst return-stream ratio (observed shift / cutoff) = "
          f"{worst:.2f} — {'never reaches the floor → structurally cannot fire' if worst < 1.0 else 'crosses the floor at some m'}")


if __name__ == "__main__":
    main()
