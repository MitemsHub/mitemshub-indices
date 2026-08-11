#!/usr/bin/env python3
"""Distribution of prev_sigma / EMA30(sigma) for the FIXED calibrated R_75
EGARCH on the real corpus — picks the vol-gate ratio the production
estimator can actually cross."""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src"))

from synthetic_trader.backtest.engine import load_ticks_csv  # noqa: E402
from synthetic_trader.backtest.vol_reversion import dedupe_ticks  # noqa: E402
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder  # noqa: E402

TF = 300
OMEGA, ALPHA, GAMMA, BETA = -1.115, 0.077, 0.011, 0.918
EZ = 0.7979
LR_VAR_INIT = math.log(0.0004)

ticks = dedupe_ticks([
    t
    for p in ["data/backfill/R_75_ticks.csv", "data/R_75_ticks.csv"]
    if os.path.exists(p)
    for t in load_ticks_csv(p, default_symbol="R_75")
])
builder = MultiTimeframeCandleBuilder("R_75", [TF])
closes = []
for tick in sorted(ticks, key=lambda t: t.epoch):
    closed = builder.update(tick)
    c = closed.get(TF)
    if c is not None:
        closes.append(c.close)

log_var = LR_VAR_INIT
sigma = math.exp(log_var / 2.0)
ema = None
prev_sigma = None
prev_close = closes[0]
price_ema = closes[0]
ratios = []
z_at_ratio = []
n = 0
alpha_ema = 2.0 / 21.0  # InpEmaPeriod=20

# --- ADWIN-lite drift detector, line-for-line from the tester --------------
DRIFT_CAP = 20
DRIFT_DELTA = 0.002
DRIFT_COOLDOWN = 10
drift_win = []
cooldown = 0
entries = []


def observe_drift(log_ret):
    global cooldown, drift_win
    v = abs(log_ret) * 100.0
    if len(drift_win) < DRIFT_CAP:
        drift_win.append(v)
        if len(drift_win) < DRIFT_CAP:
            return
    else:
        drift_win = drift_win[1:] + [v]
    m0 = sum(drift_win[:10]) / 10.0
    m1 = sum(drift_win[10:]) / 10.0
    s = 0.0
    for i in range(20):
        s += (drift_win[i] - (m0 if i < 10 else m1)) ** 2
    pooled_std = math.sqrt(s / 20.0)
    thr = math.sqrt(2.0 * math.log(2.0 / DRIFT_DELTA) / 10.0) * pooled_std
    if abs(m0 - m1) > thr:
        cooldown = 0
        drift_win = []


for i in range(1, len(closes)):
    c = closes[i]
    log_ret = math.log(c / prev_close)
    prev_close = c
    n += 1
    sigma_t = math.exp(max(-30.0, min(5.0, log_var)) / 2.0)
    z = log_ret / max(sigma_t, 1e-10)
    shock = abs(z) - EZ
    log_var = max(-30.0, min(5.0, OMEGA + ALPHA * shock + GAMMA * z + BETA * log_var))
    sigma = math.exp(log_var / 2.0)
    if n < 30:
        continue
    observe_drift(log_ret)
    if cooldown < DRIFT_COOLDOWN:
        cooldown += 1
    if ema is None:
        ema = sigma
    else:
        ema = ema * (29.0 / 30.0) + sigma * (1.0 / 30.0)
    price_ema = price_ema * (1.0 - alpha_ema) + c * alpha_ema
    if prev_sigma is not None and ema > 0.0:
        ratio = prev_sigma / ema
        ratios.append(ratio)
        z_dev = math.log(c / price_ema) / prev_sigma
        z_at_ratio.append((ratio, z_dev))
        # --- tester entry gates, in tester order -------------------------
        drift_clear = cooldown >= DRIFT_COOLDOWN
        vol_cross = ratio > 1.10
        z_pass = abs(z_dev) >= 1.0
        entry = drift_clear and vol_cross and z_pass
        if entry:
            entries.append((ratio, z_dev))
    prev_sigma = sigma

ratios.sort()
print(f"bars (post-warmup): {len(ratios)}")
print(f"ratio mean={sum(ratios)/len(ratios):.3f} median={ratios[len(ratios)//2]:.3f} "
      f"p90={ratios[int(0.90*len(ratios))]:.3f} p95={ratios[int(0.95*len(ratios))]:.3f} "
      f"p99={ratios[int(0.99*len(ratios))]:.3f} max={ratios[-1]:.3f}")
print(f"TRIUE ENTRY BARS (drift-clear AND ratio>1.10 AND |z|>=1.0): {len(entries)}")
print("--- vol-crossing bars that ALSO pass the z gate (|z| >= z_entry) ---")
for thr in (1.05, 1.10, 1.15, 1.20, 1.30, 1.60):
    cross = [(r, z) for r, z in z_at_ratio if r > thr]
    for ze in (0.7, 1.0, 1.3):
        passes = sum(1 for _, z in cross if abs(z) >= ze)
        print(f"  ratio > {thr}: {len(cross):4d} crossings, |z|>=0.7: {sum(1 for _,z in cross if abs(z)>=0.7):4d}, "
              f"|z|>=1.0: {sum(1 for _,z in cross if abs(z)>=1.0):4d}, |z|>=1.3: {sum(1 for _,z in cross if abs(z)>=1.3):4d}")
