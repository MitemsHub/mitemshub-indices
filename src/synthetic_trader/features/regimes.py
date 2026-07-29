from __future__ import annotations

from synthetic_trader.domain import Candle, Regime
from synthetic_trader.features.indicators import candle_feature_set


def classify_regime(candles: list[Candle]) -> tuple[Regime, dict[str, float], tuple[str, ...]]:
    features = candle_feature_set(candles)
    if len(candles) < 5:
        return Regime.RANGE, features, ("cold start — defaulting to RANGE (safest assumption)",)

    slope = features.get("slope_20_atr", 0.0)
    atr_ratio = features.get("atr_ratio", 1.0)
    range_z = features.get("range_z_50", 0.0)
    ema_spread = features.get("ema_21_50_spread_atr", 0.0)
    hurst = features.get("hurst_exponent", 0.5)
    entropy = features.get("entropy", 0.0)
    vol_cluster = features.get("volatility_clustering", 1.0)
    atr_z = features.get("atr_z_20", 0.0)
    kc_pos = features.get("kc_position", 0.5)
    dc_pos = features.get("dc_position", 0.5)
    notes: list[str] = []

    if atr_ratio > 1.55 or range_z > 2.25 or atr_z > 2.0:
        notes.append("expanded volatility")
        return Regime.VOLATILE, features, tuple(notes)

    if atr_ratio < 0.72 and abs(slope) < 0.08 and range_z < -1.0:
        notes.append("compressed volatility")
        return Regime.COMPRESSION, features, tuple(notes)

    if hurst > 0.6 and slope > 0.12 and ema_spread > 0.10:
        notes.append("uptrend alignment (persistent)")
        return Regime.TREND_UP, features, tuple(notes)

    if hurst > 0.6 and slope < -0.12 and ema_spread < -0.10:
        notes.append("downtrend alignment (persistent)")
        return Regime.TREND_DOWN, features, tuple(notes)

    if hurst < 0.45 and entropy > 0.7:
        notes.append("mean-reverting noisy range")
        return Regime.RANGE, features, tuple(notes)

    if abs(slope) < 0.05 and entropy < 0.6:
        notes.append("low-entropy range")
        return Regime.RANGE, features, tuple(notes)

    notes.append("transitional regime")
    return Regime.RANGE, features, tuple(notes)
