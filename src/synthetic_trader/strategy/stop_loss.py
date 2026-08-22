"""Professional 5-layer stop loss system shared across execution builders.

Sniper (swing) mode uses this module
to calculate stop losses based on:

Layer 0: ORDER BLOCK STOP — ICT/SMC institutional stop placement.
         Finds the last opposing candle before an impulsive move that
         broke market structure.  Place stop below/above its wick.

Layer 1: STRUCTURAL STOP — Historical swing points from the higher
         timeframe (4H/daily).  The "last week's highest drop" level
         where institutional demand stepped in.

Layer 2: MAXIMUM ADVERSE EXCURSION (MAE) — The worst-case pullback
         from historical candles on the setup timeframe.

Layer 3: ATR VOLATILITY BUFFER — The current ATR * 2.0 provides a
         minimum stop distance based on current volatility.

Layer 4: LIQUIDITY ZONE STOP — Detects equal highs/lows where retail
         stops cluster and places our stop BEHIND the zone, not at it.

FINAL STOP = WIDEST of the five candidates.
"""

from __future__ import annotations

from synthetic_trader.domain import Candle
from synthetic_trader.features.market_structure import detect_swings


def _detect_bos_index(
    candles: list[Candle],
    direction: str,
    lookback: int = 50,
) -> int | None:
    """Detect the index of the most recent Break of Structure (BOS).

    Scans the last `lookback` candles to find where price forcefully
    broke a validated swing high (for sells) or swing low (for buys)
    via strong displacement.

    Returns the index of the candle that completed the BOS, or None
    if no BOS was found.
    """
    if len(candles) < 10:
        return None

    window = candles[-min(lookback, len(candles)):]
    swings = detect_swings(window, left=3, right=3)

    if direction == "buy":
        # Sort by index (time) to find the most recent swing highs.
        # BOS = price closes above the most recent swing high (highs[-1]).
        highs = sorted(
            [s for s in swings if s.kind == "high"],
            key=lambda s: s.index,
        )
        if not highs:
            return None
        # The most recent swing high is the structural level being broken.
        most_recent_high = highs[-1].price
        for i in range(len(window) - 1, -1, -1):
            if window[i].close > most_recent_high:
                return len(candles) - len(window) + i
        return None
    else:
        # Sort by index (time) to find the most recent swing lows.
        # BOS = price closes below the most recent swing low (lows[-1]).
        lows = sorted(
            [s for s in swings if s.kind == "low"],
            key=lambda s: s.index,
        )
        if not lows:
            return None
        most_recent_low = lows[-1].price
        for i in range(len(window) - 1, -1, -1):
            if window[i].close < most_recent_low:
                return len(candles) - len(window) + i
        return None


def find_order_block_stop(
    candles: list[Candle],
    direction: str,
    atr_14: float,
    smc_order_blocks: list[dict] | None = None,
) -> float | None:
    """Find order block-based stop using ICT/SMC institutional logic.

    An Order Block is the last opposing candle before an impulsive move
    that broke market structure (BOS).  Institutional traders place stops
    beyond the order block's wick because:

    1. If price returns to the order block and closes through it, the
       institutional thesis is invalid.
    2. The order block represents where smart money accumulated — once
       mitigated, the zone has served its purpose.

    If smc_order_blocks is provided (from smc_enhanced.detect_smc_order_blocks),
    those are used first — they use the smartmoneyconcepts library's
    institutional-grade OB detection.  Otherwise, falls back to custom
    detection by scanning for opposing candles before BOS.

    For a bullish trade (buy):
    - Find bullish OB zone (bottom of the OB)
    - Stop = OB bottom - ATR buffer

    For a bearish trade (sell):
    - Find bearish OB zone (top of the OB)
    - Stop = OB top + ATR buffer
    """
    if len(candles) < 15:
        return None

    # ── Priority 1: Use SMC-detected Order Blocks (institutional-grade) ──
    # If smc_order_blocks is provided from smc_enhanced.detect_smc_order_blocks,
    # use those for the most accurate OB-based stop placement.
    if smc_order_blocks:
        buffer = atr_14 * 0.5
        current_price = candles[-1].close

        if direction == "buy":
            # Find bullish OBs BELOW current price (demand zones)
            bullish_obs = [
                ob for ob in smc_order_blocks
                if ob.get("direction") == "bullish"
                and ob.get("bottom", 0) < current_price
            ]
            if bullish_obs:
                # Use the most recent bullish OB (highest index = most recent)
                # Place stop below the OB's bottom with ATR buffer
                most_recent = max(bullish_obs, key=lambda ob: ob.get("index", 0))
                return float(most_recent["bottom"]) - buffer

        elif direction == "sell":
            # Find bearish OBs ABOVE current price (supply zones)
            bearish_obs = [
                ob for ob in smc_order_blocks
                if ob.get("direction") == "bearish"
                and ob.get("top", 0) > current_price
            ]
            if bearish_obs:
                # Use the most recent bearish OB (highest index = most recent)
                # Place stop above the OB's top with ATR buffer
                most_recent = max(bearish_obs, key=lambda ob: ob.get("index", 0))
                return float(most_recent["top"]) + buffer

    # ── Priority 2: Fallback to custom BOS-based detection ──
    bos_index = _detect_bos_index(candles, direction, lookback=50)
    if bos_index is None or bos_index < 2:
        return None

    # Scan backwards from the BOS candle to find the order block
    # The order block is the last OPPOSING candle before the impulsive move
    buffer = atr_14 * 0.5  # volatility buffer beyond the OB wick

    if direction == "buy":
        # Bullish OB: last bearish candle (Close < Open) before BOS
        for i in range(bos_index - 1, max(bos_index - 12, -1), -1):
            if i < 0 or i >= len(candles):
                continue
            ob_candle = candles[i]
            if ob_candle.close < ob_candle.open:  # bearish candle
                return ob_candle.low - buffer
        # Fallback: use the lowest low in the 5 candles before BOS
        lookback_candles = candles[max(0, bos_index - 5):bos_index]
        if lookback_candles:
            return min(c.low for c in lookback_candles) - buffer
    else:
        # Bearish OB: last bullish candle (Close > Open) before BOS
        for i in range(bos_index - 1, max(bos_index - 12, -1), -1):
            if i < 0 or i >= len(candles):
                continue
            ob_candle = candles[i]
            if ob_candle.close > ob_candle.open:  # bullish candle
                return ob_candle.high + buffer
        lookback_candles = candles[max(0, bos_index - 5):bos_index]
        if lookback_candles:
            return max(c.high for c in lookback_candles) + buffer

    return None


def calculate_mae(
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
    """
    if not candles or len(candles) < 3:
        return 0.0

    window = candles[-min(lookback, len(candles)):]
    if direction == "buy":
        max_wick_adverse = max(
            (candle.close - candle.low for candle in window if candle.close > candle.low),
            default=0.0,
        )
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


def find_structural_stop(
    candles: list[Candle],
    direction: str,
    entry: float,
    atr_14: float,
) -> float | None:
    """Find the structural stop loss from historical swing points.

    A professional trader places the stop at the structural level
    where the trade thesis is invalidated — NOT at the current
    candle's wick.  This function looks back across historical
    candles to find the lowest swing low (for buys) or highest
    swing high (for sells) from the last 50 candles.

    The stop is placed beyond the structural level with a buffer,
    ensuring it survives normal volatility while still protecting
    against genuine thesis breakage.
    """
    if len(candles) < 10:
        return None

    lookback = candles[-min(50, len(candles)):]
    swings = detect_swings(lookback, left=3, right=3)
    swing_lows = sorted([s for s in swings if s.kind == "low"], key=lambda s: s.price)
    swing_highs = sorted([s for s in swings if s.kind == "high"], key=lambda s: s.price, reverse=True)

    buffer = atr_14 * 0.5

    if direction == "buy":
        if swing_lows:
            structural_low = swing_lows[0].price
            return structural_low - buffer
        lowest_low = min(candle.low for candle in lookback)
        return lowest_low - buffer
    else:
        if swing_highs:
            structural_high = swing_highs[0].price
            return structural_high + buffer
        highest_high = max(candle.high for candle in lookback)
        return highest_high + buffer


def find_liquidity_zone_stop(
    candles: list[Candle],
    direction: str,
    atr_14: float,
) -> float | None:
    """Find stop placement that avoids obvious liquidity zones.

    Retail traders cluster stop losses at equal highs/lows — these are
    obvious levels where smart money hunts liquidity.  If we place our
    stop AT these levels, we get hunted too.

    This function:
    1. Detects equal highs/lows (swing points within 0.1% of each other)
    2. Filters to only zones on the correct side of current price
    3. Returns a stop level BEHIND the zone (further from current price)
       with an ATR buffer to survive the next sweep.

    For a buy trade:
    - Find equal lows BELOW current price (retail stop cluster below)
    - Place stop below the equal low zone - ATR buffer

    For a sell trade:
    - Find equal highs ABOVE current price (retail stop cluster above)
    - Place stop above the equal high zone + ATR buffer
    """
    if len(candles) < 20:
        return None

    lookback = candles[-min(50, len(candles)):]
    swings = detect_swings(lookback, left=3, right=3)
    swing_highs = sorted([s for s in swings if s.kind == "high"], key=lambda s: s.index)
    swing_lows = sorted([s for s in swings if s.kind == "low"], key=lambda s: s.index)

    current_price = candles[-1].close
    buffer = atr_14 * 0.75  # 0.75x ATR buffer beyond the liquidity zone

    if direction == "buy":
        # Find equal lows BELOW current price — retail stop clusters
        if len(swing_lows) < 2:
            return None

        # Sort by price, scan for consecutive lows within 0.1%
        sorted_lows = sorted([s.price for s in swing_lows])
        equal_low_zones = []
        for i in range(len(sorted_lows) - 1):
            if (abs(sorted_lows[i + 1] - sorted_lows[i]) / max(sorted_lows[i], 1e-9) < 0.001
                    and sorted_lows[i] < current_price):  # only zones below price
                equal_low_zones.append(sorted_lows[i])

        if not equal_low_zones:
            return None

        deepest_zone = min(equal_low_zones)
        return deepest_zone - buffer

    else:  # sell
        # Find equal highs ABOVE current price — retail stop clusters
        if len(swing_highs) < 2:
            return None

        sorted_highs = sorted([s.price for s in swing_highs])
        equal_high_zones = []
        for i in range(len(sorted_highs) - 1):
            if (abs(sorted_highs[i + 1] - sorted_highs[i]) / max(sorted_highs[i], 1e-9) < 0.001
                    and sorted_highs[i] > current_price):  # only zones above price
                equal_high_zones.append(sorted_highs[i])

        if not equal_high_zones:
            return None

        highest_zone = max(equal_high_zones)
        return highest_zone + buffer


def smart_stop_loss(
    htf_candles: list[Candle],
    ltf_candles: list[Candle],
    direction: str,
    reference_level: float,
    atr_14: float,
    entry: float,
    smc_order_blocks: list[dict] | None = None,
) -> float:
    """Calculate stop loss using the professional 5-layer approach.

    Instead of using the immediate candle, this function uses FIVE
    layers of analysis:

    Layer 0: ORDER BLOCK STOP — ICT/SMC institutional stop placement.
    Finds the last opposing candle before an impulsive BOS and places
    the stop beyond its wick.  Uses SMC-detected order blocks when
    available (from smc_enhanced.detect_smc_order_blocks).

    Layer 1: STRUCTURAL STOP — Historical swing points from the
    higher timeframe (4H/daily).

    Layer 2: MAXIMUM ADVERSE EXCURSION (MAE) — The worst-case pullback
    from historical candles on the setup timeframe.

    Layer 3: ATR VOLATILITY BUFFER — The current ATR * 2.0 provides a
    minimum stop distance based on current volatility.

    Layer 4: LIQUIDITY ZONE STOP — Detects equal highs/lows where retail
    stops cluster and places our stop BEHIND the zone, not at it.

    The FINAL STOP = WIDEST of the five candidates.
    """
    # Layer 0: Order block stop from ICT/SMC institutional logic
    ob_stop = find_order_block_stop(htf_candles, direction, atr_14, smc_order_blocks)

    # Layer 1: Structural stop from higher timeframe swing points
    structural_stop = find_structural_stop(htf_candles, direction, entry, atr_14)

    # Layer 2: Maximum Adverse Excursion from setup candles
    mae = calculate_mae(ltf_candles, direction, entry, lookback=50)
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

    # Layer 4: Liquidity zone stop — avoid equal highs/lows where
    # retail stops cluster.  Place BEHIND the zone, not at it.
    liq_stop = find_liquidity_zone_stop(ltf_candles, direction, atr_14)

    # Choose the WIDEST stop from all candidates
    candidates = [reference_level, mae_stop, atr_stop]
    if ob_stop is not None:
        candidates.append(ob_stop)
    if structural_stop is not None:
        candidates.append(structural_stop)
    if liq_stop is not None:
        candidates.append(liq_stop)

    if direction == "buy":
        final_stop = min(candidates)
    else:
        final_stop = max(candidates)

    return final_stop
