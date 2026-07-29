from __future__ import annotations

from synthetic_trader.domain import Candle, Regime, Tick, FeatureSnapshot
from synthetic_trader.features.market_structure import market_structure_features
from synthetic_trader.features.regimes import classify_regime
from synthetic_trader.features.tick_integration import compute_tick_flow_features


def build_snapshot(
    symbol: str,
    timeframe_sec: int,
    candles: list[Candle],
    higher_timeframe_candles: list[Candle] | None = None,
    extra_timeframes: dict[str, list[Candle]] | None = None,
    ticks: list[Tick] | None = None,
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
                # No candles at all — only inherit the parent regime so the
                # frontend shows a meaningful value instead of "unknown".
                # Do NOT copy primary-TF features (slope, atr, etc.) because
                # they belong to a different timeframe and would be misleading
                # if labeled as bias_*/setup_*.  Only set the regime key and
                # explicitly zero-out the unknown flag.
                features[f"{prefix}_regime_{regime.value}"] = 1.0
                features[f"{prefix}_regime_unknown"] = 0.0
                notes.append(f"{prefix.upper()} inherited parent regime ({regime.value}) — no candles yet")
                continue
            extra_regime, extra_features, extra_notes = classify_regime(timeframe_candles)
            extra_structure = market_structure_features(timeframe_candles)
            features.update({f"{prefix}_{key}": value for key, value in extra_features.items()})
            features.update({f"{prefix}_{key}": value for key, value in extra_structure.items()})
            # When the regime classifier returns UNKNOWN (too few candles),
            # inherit the parent timeframe's regime instead of showing "unknown".
            effective_regime = extra_regime if extra_regime != Regime.UNKNOWN else regime
            features[f"{prefix}_regime_{effective_regime.value}"] = 1.0
            if extra_regime == Regime.UNKNOWN:
                notes.append(f"{prefix.upper()} regime inherited from primary ({regime.value}) — {len(timeframe_candles)} candles insufficient")
            else:
                notes.extend(f"{prefix.upper()} {note}" for note in extra_notes)

    # ── Tick-level features ───────────────────────────────────────
    # Feed raw ticks into TickFlowEngine to capture micro-structure
    # dynamics (velocity, acceleration, impulse/retrace, exhaustion)
    # that candle-derived features miss.
    if ticks:
        tick_features = compute_tick_flow_features(ticks)
        features.update(tick_features)
        if any(v != 0.0 for k, v in tick_features.items() if k != "tick_total"):
            notes.append(f"tick_flow: vel={tick_features.get('tick_velocity', 0):.4f} accel={tick_features.get('tick_acceleration', 0):.4f}")

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
