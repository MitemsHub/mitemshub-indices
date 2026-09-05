# V75 Tick-Generator Fingerprint — how the machine actually works (2026-09-04)

**Data**: 1,295,215 ticks, 30 continuous days (2026-08-03 → 2026-09-02),
broker archive. Cadence cross-checked against broker-history probes: the feed
itself is one tick per ~2.000 s (0.5 Hz) — the recorder's 2s grid IS the feed.
Tool: `scripts/generator_fingerprint.py` → `artifacts/generator/fingerprint.json`.

## The machine, reverse-engineered

**The V75 generator is a deterministic 2-second step machine.** Every 2.000 s
(median = p05 = p95 = 2000 ms — zero jitter measured) it prints exactly one
new price. One step per tick, no intra-step information, no hidden cadence.

**The step engine is a memoryless Gaussian random walk with per-step
volatility targeting:**

| Property | Measured | Interpretation |
|---|---|---|
| Interval | 2000.0 ms sharp (p05=p95) | deterministic clock, 0.5 Hz |
| Jump distribution | σ≈9.44 pts, skew ≈ 0.00, kurtosis ≈ 0.01 | Gaussian steps, no fat tails |
| Up/Down balance | 0.4998 | fair coin |
| Tick ACF (lags 1–100) | max \|ρ\| = 0.0025, 5/100 in noise band | **no direction memory** |
| Run-length dist | observed = geometric(p_flip=0.499) to 4 decimals | **memoryless runs** — "spike runs" are just coin streaks |
| Variance ratio | 1.00 at 1s–1m, 0.97–0.98 at 15m–1h | random walk at every scale (tiny sub-1 sub-diffusivity ≈ TP/SL fence effects, no tradable signal) |
| Vol clustering (|r| ACF) | ≈ 0.002 at all lags | **no GARCH at tick scale** |
| Hour-of-day vol | max/min = 1.018 over 30 days | volatility targeting works: ~constant vol, flat diurnal profile |

## What this means (the honest engineering conclusions)

1. **"Working ahead of the generator" is mathematically impossible at tick
   level.** A memoryless step process carries zero information about its next
   step: P(up)=0.5 regardless of everything history shows. Any tick-level
   "pattern" (3 down-ticks → reversal, burst → continuation) is coin-flip
   noise by construction. This is now *proven on 1.3M real ticks*, not assumed.
2. **There is no tick-level "fast lane" to exploit — and nothing was left on
   the table by trading M15.** The only quantities that evolve are the slow
   ones (drift vs 2s-σ), which is exactly what the M15/H1 signal layer and the
   GARCH vol model already estimate. The split-second reflex edge the fast-fail
   study hunted does not exist in this feed.
3. **The 2s clock is an engineering gift, not a trading edge**: execution,
   monitoring, and paper-fill simulation can be event-exact (one decision per
   2s step). The EA's exit polling and the tick reconciler should treat 2s as
   the ground-truth clock.
4. **The generator's one deliberate "flaw" is the place edge CAN live**: its
   σ-per-step must be *set* by the controller, and it can only adapt slowly
   (measured: flat to 1.8%/hour-of-day). Regime shifts — the thing the EA's
   H1 classification and ATR-percentile gates already track — are the real
   signal. That is *where* the certified edge lives (M15 pullbacks in
   classified regimes), and this study confirms there is no faster layer
   underneath it.
5. **Strategy implications (tested, closed)**: spike-fade at tick level was
   already rejected with the same data (`tick_fade_verdict.json`); tick-momentum
   is now rejected by T3/T5; tick-mean-reversion is rejected by T4 ≈ 1.0.
   The M15 scale is not a compromise — it is the correct operating point.

## Status

Protocol: descriptive study, one look, closed. No EA config changes. The
standing research program (paper A/B → go-live gate) is unaffected; this
study settles the *direction* of all future effort: regime intelligence at
the bar scale, not tick-speed reflexes.
