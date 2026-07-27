"""Integration layer for TickFlowEngine into the snapshot pipeline.

This module bridges TickFlowEngine's tick-level features into the
candle-based FeatureSnapshot so the decision engine and regime models
can use both candle-derived and tick-derived signals.
"""

from __future__ import annotations

from synthetic_trader.domain import Tick
from synthetic_trader.features.tick_flow import TickFlowEngine


def compute_tick_flow_features(ticks: list[Tick]) -> dict[str, float]:
    """Feed raw ticks into a fresh TickFlowEngine and return the features.

    This is the integration point called by the snapshot pipeline.
    We create a new engine per call (no persistent state) and feed
    all available ticks to build the full tick-flow profile.
    """
    if not ticks:
        engine = TickFlowEngine(window_size=200)
        return engine.features()

    # Feed ticks in chronological order
    engine = TickFlowEngine(window_size=min(200, len(ticks)))
    for tick in ticks:
        engine.update(tick.price)

    return engine.features()
