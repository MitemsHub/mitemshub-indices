from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.features.indicators import atr, safe_div
from synthetic_trader.features.market_structure import detect_swings, StructureState


@dataclass(frozen=True)
class StructureMap:
    bias_direction: str
    bias_zone_low: float | None
    bias_zone_high: float | None
    invalidation_price: float | None
    target_one: float | None
    target_extended: float | None
    bias_regime: str = "unknown"
    setup_regime: str = "unknown"
    confirmation_regime: str = "unknown"
    execution_regime: str = "unknown"
    confluence_score: float = 0.0
    structure_notes: tuple[str, ...] = ()


def _latest_swing(candles: list[Candle], kind: str) -> float | None:
    swings = [swing for swing in detect_swings(candles, left=2, right=2) if swing.kind == kind]
    if swings:
        return swings[-1].price
    if not candles:
        return None
    if kind == "high":
        return max(candle.high for candle in candles)
    return min(candle.low for candle in candles)


def _bias_direction_from_candles(candles: list[Candle]) -> str:
    if len(candles) < 3:
        return "neutral"
    n = min(len(candles), 30)
    closes = [c.close for c in candles]
    start_price = closes[-n] if len(closes) >= n else closes[0]
    end_price = closes[-1]
    pct_change = (end_price - start_price) / max(start_price, 1e-9)

    atr_val = atr(candles, min(14, len(candles)))
    if atr_val <= 0:
        return "neutral"
    atr_pct = atr_val / end_price if end_price > 0 else 0

    if pct_change > atr_pct * 0.5:
        return "bullish"
    if pct_change < -atr_pct * 0.5:
        return "bearish"
    return "neutral"


def _regime_from_candles(candles: list[Candle]) -> str:
    if len(candles) < 3:
        return "unknown"
    n = min(len(candles), 20)
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    atr_val = atr(candles, min(14, len(candles)))
    slope = (closes[-1] - closes[-n]) / (n * max(atr_val, 1e-9)) if atr_val > 0 else 0
    range_n = max(highs[-n:]) - min(lows[-n:])
    atr_longer = atr(candles, min(50, len(candles)))
    atr_ratio = safe_div(atr_val, atr_longer, 1.0)

    if atr_ratio > 1.5:
        return "volatile"
    if atr_ratio < 0.7 and abs(slope) < 0.1:
        return "compression"
    if slope > 0.15:
        return "trend_up"
    if slope < -0.15:
        return "trend_down"
    return "range"


def build_structure_map(
    *,
    bias_candles: list[Candle],
    setup_candles: list[Candle],
    confirmation_candles: list[Candle],
    execution_candles: list[Candle],
) -> StructureMap:
    bias_high = _latest_swing(bias_candles, "high")
    bias_low = _latest_swing(bias_candles, "low")
    bias_direction = _bias_direction_from_candles(bias_candles)

    if bias_direction == "bullish":
        invalidation = bias_low
        target_one = bias_high
        target_extended = max(c.high for c in bias_candles[-20:]) if len(bias_candles) >= 20 else max(c.high for c in bias_candles) if bias_candles else None
    elif bias_direction == "bearish":
        invalidation = bias_high
        target_one = bias_low
        target_extended = min(c.low for c in bias_candles[-20:]) if len(bias_candles) >= 20 else min(c.low for c in bias_candles) if bias_candles else None
    else:
        invalidation = None
        target_one = None
        target_extended = None

    bias_regime = _regime_from_candles(bias_candles)
    setup_regime = _regime_from_candles(setup_candles)
    confirmation_regime = _regime_from_candles(confirmation_candles)
    execution_regime = _regime_from_candles(execution_candles)

    regime_hierarchy = [bias_regime, setup_regime, confirmation_regime, execution_regime]
    trend_regimes = {"trend_up", "trend_down"}
    range_regimes = {"range", "compression"}
    volatile_regime = "volatile"

    trend_count = sum(1 for r in regime_hierarchy if r in trend_regimes)
    range_count = sum(1 for r in regime_hierarchy if r in range_regimes)
    volatile_count = sum(1 for r in regime_hierarchy if r == volatile_regime)

    if trend_count >= 3:
        confluence_score = 0.9
    elif trend_count == 2 and range_count <= 1:
        confluence_score = 0.75
    elif trend_count == 2:
        confluence_score = 0.65
    elif trend_count == 1 and range_count >= 2:
        confluence_score = 0.4
    else:
        confluence_score = 0.5

    notes = [
        f"4H bias: {bias_direction} ({bias_regime})",
        f"1H setup: {setup_regime}",
        f"15m confirmation: {confirmation_regime}",
        f"5m execution: {execution_regime}",
        f"confluence: {confluence_score:.2f}",
    ]

    if bias_regime == setup_regime == confirmation_regime == execution_regime:
        notes.append("full timeframe alignment")
    elif bias_regime == setup_regime == confirmation_regime:
        notes.append("bias-setup-confirmation alignment")

    return StructureMap(
        bias_direction=bias_direction,
        bias_zone_low=min(candle.low for candle in setup_candles[-10:]),
        bias_zone_high=max(candle.high for candle in setup_candles[-10:]),
        invalidation_price=invalidation,
        target_one=target_one,
        target_extended=target_extended,
        bias_regime=bias_regime,
        setup_regime=setup_regime,
        confirmation_regime=confirmation_regime,
        execution_regime=execution_regime,
        confluence_score=confluence_score,
        structure_notes=tuple(notes),
    )
