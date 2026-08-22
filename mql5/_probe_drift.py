#!/usr/bin/env python3
"""Measure the Python band's drift-gate behavior on the R_75 corpus.

Answers the P10-A parity question: does the strategy's always-on ADWIN drift
cooldown (steps_since_last_drift >= 10) ever veto a band candidate?  If it
never vetoes (or only vetoes candidates that never trade anyway), the EA can
match the reference entry set with any detector that fires equally rarely.

Replicates VolBandStrategy.on_candle exactly (same forecaster, same drift
detector, same gate order) with drift-veto counting.
"""
import math
import sys
sys.path.insert(0, "src")

from synthetic_trader.backtest.vol_band import VolBandConfig, VolBandStrategy
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.models.garch_calibration import load_calibrated_garch_state
from synthetic_trader.execution.paper import PaperBroker  # noqa: F401 (import graph)
from synthetic_trader.domain import Direction, Regime
from synthetic_trader.strategy.band_geometry import band_levels, BandGeometryConfig
from synthetic_trader.backtest.vol_reversion import dedupe_ticks

TF = 300
SYM = "R_75"
config = VolBandConfig(
    z_entry=1.0,
    vol_extended_ratio=1.3,
    min_revert_signal=0.02,
    stop_sigma_mult=0.20,
    target_sigma_mult=0.80,
    max_hold_sec=3600,
    breakeven_trail_frac=0.3,
)

ticks = dedupe_ticks(load_ticks_csv("data/backfill/R_75_ticks.csv", default_symbol=SYM))
garch_state = load_calibrated_garch_state(SYM)
print("garch_state:", "loaded" if garch_state else "NONE")
strategy = VolBandStrategy(SYM, TF, config=config, garch_state=garch_state)

builders = MultiTimeframeCandleBuilder(SYM, [TF])
signals = 0
drift_vetoed = 0
candidate_bars = 0
drift_events = []
steps_at_signal = []
last_drift_step = None

for tick in sorted(ticks, key=lambda item: item.epoch):
    for tf, candle in builders.update(tick).items():
        if tf != TF:
            continue
        # Snapshot the entry-gate state BEFORE on_candle advances it
        prev_sigma = getattr(strategy, "_prev_sigma", None)
        ema = strategy._ema
        sigma_ema = strategy._sigma_ema
        n_before = strategy.drift.n_observations
        steps_before = strategy.drift.steps_since_last_drift(n_before)
        sig = strategy.on_candle(candle)
        if sig is not None:
            signals += 1
            steps_at_signal.append(steps_before)
        # candidate = a bar whose gate conditions would have passed the
        # vol/z gates with the PRE-bar state (revert filter not re-checked;
        # it can only reduce candidates, so veto counting stays conservative)
        if prev_sigma is None or ema is None or sigma_ema is None:
            continue
        if not (prev_sigma > config.vol_extended_ratio * sigma_ema):
            continue
        z_dev = math.log(candle.close / ema) / prev_sigma
        if abs(z_dev) < config.z_entry:
            continue
        candidate_bars += 1
        if steps_before < config.drift_cooldown_bars:
            drift_vetoed += 1

print(f"candidate_bars={candidate_bars} drift_vetoed={drift_vetoed} signals={signals}")
print(f"drift_events={strategy.drift.drift_events} n_obs={strategy.drift.n_observations}")
print(f"steps_at_signal min={min(steps_at_signal) if steps_at_signal else '-'} max={max(steps_at_signal) if steps_at_signal else '-'}")
