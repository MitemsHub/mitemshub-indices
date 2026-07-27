from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from synthetic_trader.domain import Candle, Direction
from synthetic_trader.features.indicators import atr, safe_div


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: str
    strength: float = 0.0


@dataclass(frozen=True)
class FairValueGap:
    index: int
    top: float
    bottom: float
    direction: str


@dataclass(frozen=True)
class StructureState:
    bias: float
    recent_high: float
    recent_low: float
    bos_up: bool
    bos_down: bool
    liquidity_sweep_up: bool
    liquidity_sweep_down: bool
    bullish_fvg: FairValueGap | None
    bearish_fvg: FairValueGap | None
    displacement_atr: float
    equal_highs: bool
    equal_lows: bool
    swing_highs: list[SwingPoint]
    swing_lows: list[SwingPoint]


def detect_swings(candles: list[Candle], left: int = 2, right: int = 2) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    if len(candles) < left + right + 1:
        return swings

    # Filter out price outliers — if any candle's price is more than
    # 5x the median price, exclude it from swing detection. This
    # prevents corrupt data (e.g. old Deriv prices mixed with
    # Blueberry MT5 prices) from creating impossible swing levels.
    all_prices = [c.high for c in candles] + [c.low for c in candles]
    sorted_prices = sorted(all_prices)
    median_price = sorted_prices[len(sorted_prices) // 2] if sorted_prices else 1.0
    outlier_threshold = median_price * 5.0

    for index in range(left, len(candles) - right):
        window = candles[index - left : index + right + 1]
        candle = candles[index]
        # Skip outlier candles whose prices are way outside the normal range
        if candle.high > outlier_threshold or candle.low < median_price / 5.0:
            continue
        if candle.high == max(item.high for item in window):
            left_range = max(c.high for c in candles[max(0, index - 10):index]) if index > 0 else 0
            right_range = max(c.high for c in candles[index + 1:min(len(candles), index + 11)]) if index + 1 < len(candles) else 0
            strength = safe_div(candle.high - max(left_range, right_range), candle.range, 0.0) if candle.range > 0 else 0.0
            swings.append(SwingPoint(index=index, price=candle.high, kind="high", strength=strength))
        if candle.low == min(item.low for item in window):
            left_range = min(c.low for c in candles[max(0, index - 10):index]) if index > 0 else float('inf')
            right_range = min(c.low for c in candles[index + 1:min(len(candles), index + 11)]) if index + 1 < len(candles) else float('inf')
            ref = min(left_range, right_range)
            strength = safe_div(ref - candle.low, candle.range, 0.0) if candle.range > 0 and ref != float('inf') else 0.0
            swings.append(SwingPoint(index=index, price=candle.low, kind="low", strength=strength))
    return swings


def detect_fvg(candles: list[Candle]) -> list[FairValueGap]:
    fvgs: list[FairValueGap] = []
    if len(candles) < 3:
        return fvgs
    for i in range(2, len(candles)):
        a = candles[i - 2]
        b = candles[i - 1]
        c = candles[i]
        if c.low > a.high and b.body > 0:
            fvgs.append(FairValueGap(index=i, top=c.low, bottom=a.high, direction="bullish"))
        if c.high < a.low and b.body < 0:
            fvgs.append(FairValueGap(index=i, top=a.low, bottom=c.high, direction="bearish"))
    return fvgs


def market_structure_features(candles: list[Candle]) -> dict[str, float]:
    if len(candles) < 5:
        return {
            "bos_up": 0.0, "bos_down": 0.0,
            "internal_bos_up": 0.0, "internal_bos_down": 0.0,
            "liquidity_sweep_up": 0.0, "liquidity_sweep_down": 0.0,
            "bullish_fvg": 0.0, "bearish_fvg": 0.0,
            "fvg_bullish_active": 0.0, "fvg_bearish_active": 0.0,
            "displacement_atr": 0.0, "structure_bias": 0.0,
            "equal_highs": 0.0, "equal_lows": 0.0,
            "swing_high_count": 0.0, "swing_low_count": 0.0,
            "internal_structure_shift": 0.0,
            "recent_swing_high": candles[-1].high if candles else 0.0,
            "recent_swing_low": candles[-1].low if candles else 0.0,
        }

    last = candles[-1]
    prior = candles[:-1]
    swings = detect_swings(candles[:-1])
    swing_highs = [swing for swing in swings if swing.kind == "high"]
    swing_lows = [swing for swing in swings if swing.kind == "low"]
    recent_high = swing_highs[-1].price if swing_highs else max(candle.high for candle in prior[-20:]) if len(prior) >= 20 else max(c.high for c in prior)
    recent_low = swing_lows[-1].price if swing_lows else min(candle.low for candle in prior[-20:]) if len(prior) >= 20 else min(c.low for c in prior)

    avg_range = atr(candles, 14)
    displacement_atr = safe_div(abs(last.body), avg_range)
    bos_up = 1.0 if last.close > recent_high else 0.0
    bos_down = 1.0 if last.close < recent_low else 0.0
    liquidity_sweep_up = 1.0 if last.high > recent_high and last.close < recent_high else 0.0
    liquidity_sweep_down = 1.0 if last.low < recent_low and last.close > recent_low else 0.0

    fvgs = detect_fvg(candles)
    bullish_fvg = next((f for f in reversed(fvgs) if f.direction == "bullish"), None)
    bearish_fvg = next((f for f in reversed(fvgs) if f.direction == "bearish"), None)
    fvg_bullish_active = 1.0 if bullish_fvg and last.close > bullish_fvg.bottom else 0.0
    fvg_bearish_active = 1.0 if bearish_fvg and last.close < bearish_fvg.top else 0.0

    equal_highs = 0.0
    equal_lows = 0.0
    if len(swing_highs) >= 2:
        equal_highs = 1.0 if abs(swing_highs[-1].price - swing_highs[-2].price) / max(swing_highs[-1].price, 1e-9) < 0.001 else 0.0
    if len(swing_lows) >= 2:
        equal_lows = 1.0 if abs(swing_lows[-1].price - swing_lows[-2].price) / max(swing_lows[-1].price, 1e-9) < 0.001 else 0.0

    internal_bos_up = 0.0
    internal_bos_down = 0.0
    if len(swings) >= 4:
        recent_swings = swings[-4:]
        internal_highs = [s for s in recent_swings if s.kind == "high"]
        internal_lows = [s for s in recent_swings if s.kind == "low"]
        if len(internal_highs) >= 2 and internal_highs[-1].price > internal_highs[-2].price:
            internal_bos_up = 1.0
        if len(internal_lows) >= 2 and internal_lows[-1].price < internal_lows[-2].price:
            internal_bos_down = 1.0

    last_two_highs = [swing.price for swing in swing_highs[-2:]]
    last_two_lows = [swing.price for swing in swing_lows[-2:]]
    higher_high = len(last_two_highs) == 2 and last_two_highs[-1] > last_two_highs[-2]
    higher_low = len(last_two_lows) == 2 and last_two_lows[-1] > last_two_lows[-2]
    lower_high = len(last_two_highs) == 2 and last_two_highs[-1] < last_two_highs[-2]
    lower_low = len(last_two_lows) == 2 and last_two_lows[-1] < last_two_lows[-2]

    if higher_high and higher_low:
        structure_bias = 0.7
    elif lower_high and lower_low:
        structure_bias = -0.7
    elif len(candles) >= 10:
        n = min(len(candles), 20)
        closes = [c.close for c in candles]
        price_change = (closes[-1] - closes[-n]) / max(closes[-n], 1e-9)
        avg_rng = atr(candles, min(14, len(candles)))
        if avg_rng > 0:
            normed = price_change / (avg_rng / closes[-n])
            structure_bias = max(-1.0, min(1.0, normed * 0.5))
        else:
            structure_bias = 0.0
    else:
        structure_bias = 0.0

    internal_structure_shift = internal_bos_up - internal_bos_down

    return {
        "recent_swing_high": recent_high,
        "recent_swing_low": recent_low,
        "bos_up": bos_up, "bos_down": bos_down,
        "internal_bos_up": internal_bos_up, "internal_bos_down": internal_bos_down,
        "liquidity_sweep_up": liquidity_sweep_up, "liquidity_sweep_down": liquidity_sweep_down,
        "bullish_fvg": 1.0 if bullish_fvg else 0.0,
        "bearish_fvg": 1.0 if bearish_fvg else 0.0,
        "fvg_bullish_active": fvg_bullish_active, "fvg_bearish_active": fvg_bearish_active,
        "displacement_atr": displacement_atr, "structure_bias": structure_bias,
        "equal_highs": equal_highs, "equal_lows": equal_lows,
        "swing_high_count": float(len(swing_highs)), "swing_low_count": float(len(swing_lows)),
        "internal_structure_shift": internal_structure_shift,
    }


def structural_direction(features: dict[str, float]) -> Direction:
    bullish_score = (
        features.get("bos_up", 0.0)
        + features.get("internal_bos_up", 0.0) * 0.5
        + features.get("liquidity_sweep_down", 0.0)
        + features.get("bullish_fvg", 0.0)
        + features.get("fvg_bullish_active", 0.0) * 0.5
        + max(features.get("structure_bias", 0.0), 0.0)
    )
    bearish_score = (
        features.get("bos_down", 0.0)
        + features.get("internal_bos_down", 0.0) * 0.5
        + features.get("liquidity_sweep_up", 0.0)
        + features.get("bearish_fvg", 0.0)
        + features.get("fvg_bearish_active", 0.0) * 0.5
        + abs(min(features.get("structure_bias", 0.0), 0.0))
    )
    if bullish_score > bearish_score:
        return Direction.LONG
    if bearish_score > bullish_score:
        return Direction.SHORT
    return Direction.FLAT
