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


def _calculate_mae(
    candles: list[Candle],
    direction: str,
    entry: float,
    lookback: int = 50,
) -> float:
    """Calculate Maximum Adverse Excursion from historical candles.

    Scans the last `lookback` candles to find the worst-case pullback
    that occurred during previous swings.  This is the "highest drop"
    concept — the largest adverse move the market made before reversing.

    A stop placed beyond the historical MAE ensures that normal
    pullbacks (which are well within historical norms) don't trigger
    premature stop-outs.

    For a buy trade, MAE is how far price dropped from entry before
    recovering.  We measure the largest candle-to-candle adverse move
    within the lookback window.
    """
    if not candles or len(candles) < 3:
        return 0.0

    window = candles[-min(lookback, len(candles)):]
    if direction == "buy":
        # Find the largest intra-candle adverse move (close-to-low)
        # and the largest multi-candle drawdown (peak-to-trough)
        max_wick_adverse = max(
            (candle.close - candle.low for candle in window if candle.close > candle.low),
            default=0.0,
        )
        # Peak-to-trough: find the largest drop between any two candles
        prices = [c.close for c in window]
        max_drawdown = 0.0
        peak = prices[0]
        for price in prices:
            if price > peak:
                peak = price
            drawdown = peak - price
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        return max(max_wick_adverse, max_drawdown)
    else:
        # For sell: find largest adverse move upward
        max_wick_adverse = max(
            (candle.high - candle.close for candle in window if candle.high > candle.close),
            default=0.0,
        )
        prices = [c.close for c in window]
        max_drawdown = 0.0
        trough = prices[0]
        for price in prices:
            if price < trough:
                trough = price
            drawdown = price - trough
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        return max(max_wick_adverse, max_drawdown)


def _find_structural_stop(
    candles: list[Candle],
    direction: str,
    entry: float,
    atr_14: float,
) -> float | None:
    """Find the structural stop loss from historical swing points.

    A professional trader places the stop at the structural level
    where the trade thesis is invalidated — NOT at the current
    candle's wick.  This function looks back across historical
    candles to find:

    1. The lowest swing low (for buys) or highest swing high (for sells)
       from the last 50 candles — this is the "highest drop" level
    2. The order block level where institutional demand/supply stepped in
    3. The structural invalidation point

    The stop is placed beyond the structural level with a buffer,
    ensuring it survives normal volatility while still protecting
    against genuine thesis breakage.
    """
    if len(candles) < 10:
        return None

    # Detect swings across the full lookback window (last 50 candles)
    lookback = candles[-min(50, len(candles)):]
    swings = detect_swings(lookback, left=3, right=3)
    swing_lows = sorted([s for s in swings if s.kind == "low"], key=lambda s: s.price)
    swing_highs = sorted([s for s in swings if s.kind == "high"], key=lambda s: s.price, reverse=True)

    buffer = atr_14 * 0.5

    if direction == "buy":
        # Structural stop: below the lowest swing low in the lookback
        # This represents the "highest drop" — the worst adverse move
        # the market has made in recent history
        if swing_lows:
            structural_low = swing_lows[0].price  # lowest swing low
            return structural_low - buffer
        # Fallback: find the lowest candle low in the lookback
        lowest_low = min(candle.low for candle in lookback)
        return lowest_low - buffer
    else:
        # Structural stop: above the highest swing high
        if swing_highs:
            structural_high = swing_highs[0].price  # highest swing high
            return structural_high + buffer
        highest_high = max(candle.high for candle in lookback)
        return highest_high + buffer


def _smart_stop_loss(
    htf_candles: list[Candle],
    ltf_candles: list[Candle],
    direction: str,
    sweep_level: float,
    atr_14: float,
    entry: float,
) -> float:
    """Calculate stop loss using the professional 3-layer approach.

    Instead of using the immediate candle, this function uses THREE
    layers of analysis (from the professional trading research):

    Layer 1: STRUCTURAL STOP — Historical swing points from the
    HIGHER TIMEFRAME (4H/daily).  The "last week's highest drop" level
    where institutional demand stepped in.  This is the PRIMARY stop
    for a professional trader.

    Layer 2: MAXIMUM ADVERSE EXCURSION (MAE) — The worst-case pullback
    from historical candles on the setup timeframe.  Measures both
    intra-candle wick adverse moves AND multi-candle peak-to-trough
    drawdowns.

    Layer 3: ATR VOLATILITY BUFFER — The current ATR * 2.0 provides a
    minimum stop distance based on current volatility.

    The FINAL STOP = WIDEST of the three candidates.
    We always use the most conservative stop to ensure the trade has
    enough room to breathe while still protecting against genuine
    thesis breakage.
    """
    # Layer 1: Structural stop from HIGHER TIMEFRAME swing points
    # This is the "last week's highest drop" — the user's key insight
    structural_stop = _find_structural_stop(htf_candles, direction, entry, atr_14)

    # Layer 2: Maximum Adverse Excursion from setup candles
    # Measures the largest pullback from recent price structure
    mae = _calculate_mae(ltf_candles, direction, entry, lookback=50)
    if direction == "buy":
        mae_stop = entry - mae - atr_14 * 0.25
    else:
        mae_stop = entry + mae + atr_14 * 0.25

    # Layer 3: ATR volatility buffer (2.0x ATR — professional standard)
    atr_stop_buffer = atr_14 * 2.0
    if direction == "buy":
        atr_stop = entry - atr_stop_buffer
    else:
        atr_stop = entry + atr_stop_buffer

    # Choose the WIDEST stop (most conservative)
    candidates = [sweep_level, mae_stop, atr_stop]
    if structural_stop is not None:
        candidates.append(structural_stop)

    if direction == "buy":
        # For buys, stop is BELOW entry — want the LOWEST (widest)
        final_stop = min(candidates)
    else:
        # For sells, stop is ABOVE entry — want the HIGHEST (widest)
        final_stop = max(candidates)

    return final_stop


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

    # Professional 3-layer stop loss: structural swing points + MAE + ATR
    # Uses bias_candles (4H) for structural analysis — this gives the
    # "last week's highest drop" view that professional traders use.
    # Falls back to setup_candles if 4H data isn't available.
    htf_candles = bias_candles if bias_candles and len(bias_candles) >= 10 else setup_candles
    stop_loss = _smart_stop_loss(htf_candles, setup_candles, direction, sweep_level, atr_14, entry)

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