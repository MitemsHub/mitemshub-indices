from __future__ import annotations

from synthetic_trader.domain import Candle, FeatureSnapshot
from synthetic_trader.features.market_structure import market_structure_features
from synthetic_trader.features.regimes import classify_regime


def build_snapshot(
    symbol: str,
    timeframe_sec: int,
    candles: list[Candle],
    higher_timeframe_candles: list[Candle] | None = None,
    extra_timeframes: dict[str, list[Candle]] | None = None,
) -> FeatureSnapshot:
    regime, base_features, regime_notes = classify_regime(candles)
    structure = market_structure_features(candles)
    features = dict(base_features)
    features.update(structure)

    notes = list(regime_notes)
    if higher_timeframe_candles:
        higher_regime, higher_features, higher_notes = classify_regime(higher_timeframe_candles)
        higher_structure = market_structure_features(higher_timeframe_candles)
        features.update({f"htf_{key}": value for key, value in higher_features.items()})
        features.update({f"htf_{key}": value for key, value in higher_structure.items()})
        features[f"htf_regime_{higher_regime.value}"] = 1.0
        notes.extend(f"HTF {note}" for note in higher_notes)

    if extra_timeframes:
        for prefix, timeframe_candles in extra_timeframes.items():
            if not timeframe_candles:
                continue
            extra_regime, extra_features, extra_notes = classify_regime(timeframe_candles)
            extra_structure = market_structure_features(timeframe_candles)
            features.update({f"{prefix}_{key}": value for key, value in extra_features.items()})
            features.update({f"{prefix}_{key}": value for key, value in extra_structure.items()})
            features[f"{prefix}_regime_{extra_regime.value}"] = 1.0
            notes.extend(f"{prefix.upper()} {note}" for note in extra_notes)

    epoch = candles[-1].open_time + timeframe_sec if candles else 0.0
    return FeatureSnapshot(
        symbol=symbol,
        epoch=epoch,
        timeframe_sec=timeframe_sec,
        features=features,
        regime=regime,
        structure=structure,
        notes=tuple(notes),
    )
