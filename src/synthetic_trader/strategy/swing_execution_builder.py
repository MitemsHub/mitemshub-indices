from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle, Direction
from synthetic_trader.features.indicators import atr, safe_div
from synthetic_trader.features.market_structure import detect_swings


@dataclass(frozen=True)
class SwingSignal:
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    invalidation: float
    sweep_level: float
    setup_type: str
    confidence_grade: str
    target_source: str
    hold_hours: int
    risk_atr: float


def find_liquidity_sweep(
    candles: list[Candle],
    direction: str,
    swing_highs: list[float],
    swing_lows: list[float],
) -> tuple[float, int] | None:
    recent = candles[-8:]
    if direction == "buy":
        if not swing_lows:
            return None
        for i, candle in enumerate(reversed(recent)):
            if candle.low < swing_lows[-1] and candle.close > swing_lows[-1]:
                return swing_lows[-1], len(recent) - 1 - i
    else:
        if not swing_highs:
            return None
        for i, candle in enumerate(reversed(recent)):
            if candle.high > swing_highs[-1] and candle.close < swing_highs[-1]:
                return swing_highs[-1], len(recent) - 1 - i
    return None


def detect_market_structure_shift(
    candles: list[Candle],
    direction: str,
    swings: list,
) -> bool:
    if direction == "buy":
        lows = [s for s in swings if s.kind == "low"]
        if len(lows) < 2:
            return False
        prior_low = lows[-2].price
        for candle in candles[lows[-1].index :]:
            if candle.close > prior_low:
                return True
        return False
    else:
        highs = [s for s in swings if s.kind == "high"]
        if len(highs) < 2:
            return False
        prior_high = highs[-2].price
        for candle in candles[highs[-1].index :]:
            if candle.close < prior_high:
                return True
        return False


def find_order_block(
    candles: list[Candle],
    sweep_candle_index: int,
    direction: str,
) -> float | None:
    if sweep_candle_index < 1:
        return None
    ob_candle = candles[sweep_candle_index - 1]
    if direction == "buy":
        if ob_candle.close > ob_candle.open:
            return ob_candle.open
        if sweep_candle_index >= 2:
            prev = candles[sweep_candle_index - 2]
            if prev.close > prev.open:
                return prev.open
    else:
        if ob_candle.close < ob_candle.open:
            return ob_candle.open
        if sweep_candle_index >= 2:
            prev = candles[sweep_candle_index - 2]
            if prev.close < prev.open:
                return prev.open
    return None


def find_external_liquidity(
    candles: list[Candle],
    direction: str,
    swing_highs: list[float],
    swing_lows: list[float],
    entry: float,
    stop_loss: float,
) -> float | None:
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None

    if direction == "buy":
        candidates = [
            level
            for level in swing_highs
            if level > entry + risk * 1.5
        ]
        if candidates:
            return min(candidates)
        prev_highs = sorted([c.high for c in candles[-30:]], reverse=True)
        for level in prev_highs:
            if level > entry + risk * 1.5:
                return level
    else:
        candidates = [
            level
            for level in swing_lows
            if level < entry - risk * 1.5
        ]
        if candidates:
            return max(candidates)
        prev_lows = sorted([c.low for c in candles[-30:]])
        for level in prev_lows:
            if level < entry - risk * 1.5:
                return level
    return None


def build_swing_execution(
    symbol: str,
    direction: str,
    setup_candles: list[Candle],
    confirmation_candles: list[Candle],
    bias_candles: list[Candle],
    max_stop_distance_pct: float = 0.05,
) -> SwingSignal | None:
    if len(setup_candles) < 20:
        return None

    atr_14 = atr(setup_candles, 14)
    if atr_14 <= 0:
        return None

    swings = detect_swings(setup_candles, left=3, right=3)
    swing_highs = sorted([s.price for s in swings if s.kind == "high"])
    swing_lows = sorted([s.price for s in swings if s.kind == "low"])

    if not swing_highs or not swing_lows:
        return None

    sweep_result = find_liquidity_sweep(setup_candles, direction, swing_highs, swing_lows)
    if sweep_result is None:
        last_close = setup_candles[-1].close
        if direction == "buy":
            sweep_level = swing_lows[-1]
            sweep_index = len(setup_candles) - 1
            if last_close <= sweep_level:
                return None
        else:
            sweep_level = swing_highs[-1]
            sweep_index = len(setup_candles) - 1
            if last_close >= sweep_level:
                return None
    else:
        sweep_level, sweep_index = sweep_result

    has_mss = detect_market_structure_shift(setup_candles, direction, swings)

    entry = find_order_block(setup_candles, sweep_index, direction)
    if entry is None:
        entry = setup_candles[-1].close

    stop_loss = sweep_level

    risk = abs(entry - stop_loss)
    if risk <= 0 or risk < atr_14 * 0.5:
        return None

    if atr_14 > 0 and risk > atr_14 * 6:
        return None

    # Sanity cap: stop distance can never exceed max_stop_distance_pct of entry price.
    # Prevents broken candle data from producing impossible TP/SL levels.
    max_stop = entry * max_stop_distance_pct
    if risk > max_stop:
        # Re-center stop_loss within the cap
        if direction == "buy":
            stop_loss = entry - max_stop
        else:
            stop_loss = entry + max_stop
        risk = abs(entry - stop_loss)

    bias_swings = detect_swings(bias_candles, left=3, right=3) if bias_candles else []
    bias_highs = sorted([s.price for s in bias_swings if s.kind == "high"]) if bias_swings else []
    bias_lows = sorted([s.price for s in bias_swings if s.kind == "low"]) if bias_swings else []

    take_profit = find_external_liquidity(
        bias_candles or setup_candles,
        direction,
        bias_highs or swing_highs,
        bias_lows or swing_lows,
        entry,
        stop_loss,
    )
    if take_profit is None:
        take_profit = entry + risk * 3.0 if direction == "buy" else entry - risk * 3.0

    rr = abs(take_profit - entry) / risk if risk > 0 else 0
    if rr < 2.0:
        return None

    confidence_grade = "high" if has_mss else "medium"

    if direction == "buy" and setup_candles[-1].close > stop_loss:
        invalidation = stop_loss
    elif direction == "sell" and setup_candles[-1].close < stop_loss:
        invalidation = stop_loss
    else:
        invalidation = stop_loss

    return SwingSignal(
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        invalidation=invalidation,
        sweep_level=sweep_level,
        setup_type="liquidity_sweep_reversal" if sweep_result else "structure_continuation",
        confidence_grade=confidence_grade,
        target_source="external_liquidity",
        hold_hours=6,
        risk_atr=round(risk / atr_14, 1) if atr_14 > 0 else 0,
    )