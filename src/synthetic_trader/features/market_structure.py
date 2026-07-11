from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle, Direction
from synthetic_trader.features.indicators import atr, safe_div


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: str


def detect_swings(candles: list[Candle], left: int = 2, right: int = 2) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    if len(candles) < left + right + 1:
        return swings

    for index in range(left, len(candles) - right):
        window = candles[index - left : index + right + 1]
        candle = candles[index]
        if candle.high == max(item.high for item in window):
            swings.append(SwingPoint(index=index, price=candle.high, kind="high"))
        if candle.low == min(item.low for item in window):
            swings.append(SwingPoint(index=index, price=candle.low, kind="low"))
    return swings


def market_structure_features(candles: list[Candle]) -> dict[str, float]:
    if len(candles) < 10:
        return {
            "bos_up": 0.0,
            "bos_down": 0.0,
            "liquidity_sweep_up": 0.0,
            "liquidity_sweep_down": 0.0,
            "bullish_fvg": 0.0,
            "bearish_fvg": 0.0,
            "displacement_atr": 0.0,
            "structure_bias": 0.0,
        }

    last = candles[-1]
    previous = candles[-2]
    prior = candles[:-1]
    swings = detect_swings(candles[:-1])
    swing_highs = [swing for swing in swings if swing.kind == "high"]
    swing_lows = [swing for swing in swings if swing.kind == "low"]
    recent_high = swing_highs[-1].price if swing_highs else max(candle.high for candle in prior[-20:])
    recent_low = swing_lows[-1].price if swing_lows else min(candle.low for candle in prior[-20:])

    avg_range = atr(candles, 14)
    displacement_atr = safe_div(abs(last.body), avg_range)
    bos_up = 1.0 if last.close > recent_high else 0.0
    bos_down = 1.0 if last.close < recent_low else 0.0
    liquidity_sweep_up = 1.0 if last.high > recent_high and last.close < recent_high else 0.0
    liquidity_sweep_down = 1.0 if last.low < recent_low and last.close > recent_low else 0.0

    bullish_fvg = 0.0
    bearish_fvg = 0.0
    if len(candles) >= 3:
        a = candles[-3]
        c = candles[-1]
        bullish_fvg = 1.0 if c.low > a.high and previous.body > 0 else 0.0
        bearish_fvg = 1.0 if c.high < a.low and previous.body < 0 else 0.0

    last_two_highs = [swing.price for swing in swing_highs[-2:]]
    last_two_lows = [swing.price for swing in swing_lows[-2:]]
    higher_high = len(last_two_highs) == 2 and last_two_highs[-1] > last_two_highs[-2]
    higher_low = len(last_two_lows) == 2 and last_two_lows[-1] > last_two_lows[-2]
    lower_high = len(last_two_highs) == 2 and last_two_highs[-1] < last_two_highs[-2]
    lower_low = len(last_two_lows) == 2 and last_two_lows[-1] < last_two_lows[-2]

    if higher_high and higher_low:
        structure_bias = 1.0
    elif lower_high and lower_low:
        structure_bias = -1.0
    else:
        structure_bias = 0.0

    return {
        "recent_swing_high": recent_high,
        "recent_swing_low": recent_low,
        "bos_up": bos_up,
        "bos_down": bos_down,
        "liquidity_sweep_up": liquidity_sweep_up,
        "liquidity_sweep_down": liquidity_sweep_down,
        "bullish_fvg": bullish_fvg,
        "bearish_fvg": bearish_fvg,
        "displacement_atr": displacement_atr,
        "structure_bias": structure_bias,
    }


def structural_direction(features: dict[str, float]) -> Direction:
    bullish_score = (
        features.get("bos_up", 0.0)
        + features.get("liquidity_sweep_down", 0.0)
        + features.get("bullish_fvg", 0.0)
        + max(features.get("structure_bias", 0.0), 0.0)
    )
    bearish_score = (
        features.get("bos_down", 0.0)
        + features.get("liquidity_sweep_up", 0.0)
        + features.get("bearish_fvg", 0.0)
        + abs(min(features.get("structure_bias", 0.0), 0.0))
    )
    if bullish_score > bearish_score:
        return Direction.LONG
    if bearish_score > bullish_score:
        return Direction.SHORT
    return Direction.FLAT
