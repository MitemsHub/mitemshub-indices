from __future__ import annotations

from synthetic_trader.domain import Candle, Regime
from synthetic_trader.features.indicators import candle_feature_set


def classify_regime(candles: list[Candle]) -> tuple[Regime, dict[str, float], tuple[str, ...]]:
    features = candle_feature_set(candles)
    if len(candles) < 30:
        return Regime.UNKNOWN, features, ("insufficient regime history",)

    slope = features.get("slope_20_atr", 0.0)
    atr_ratio = features.get("atr_ratio", 1.0)
    range_z = features.get("range_z_50", 0.0)
    ema_spread = features.get("ema_21_50_spread_atr", 0.0)
    notes: list[str] = []

    if atr_ratio > 1.55 or range_z > 2.25:
        notes.append("expanded volatility")
        return Regime.VOLATILE, features, tuple(notes)

    if atr_ratio < 0.72 and abs(slope) < 0.08:
        notes.append("compressed volatility")
        return Regime.COMPRESSION, features, tuple(notes)

    if slope > 0.12 and ema_spread > 0.10:
        notes.append("uptrend alignment")
        return Regime.TREND_UP, features, tuple(notes)

    if slope < -0.12 and ema_spread < -0.10:
        notes.append("downtrend alignment")
        return Regime.TREND_DOWN, features, tuple(notes)

    notes.append("mean-reverting range")
    return Regime.RANGE, features, tuple(notes)
