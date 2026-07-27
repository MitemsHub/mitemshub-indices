from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.strategy.top_down_bias import TopDownBias


@dataclass(frozen=True)
class SetupDecision:
    state: str
    trade_direction: str
    trigger_zone_low: float | None
    trigger_zone_high: float | None
    reason: str


def classify_setup(*, bias: TopDownBias, setup_candles: list[Candle]) -> SetupDecision:
    recent = setup_candles[-12:]

    # Determine direction from bias, or fall back to recent candle structure
    direction = bias.direction
    if direction == "neutral" and len(setup_candles) >= 3:
        # Infer direction from recent setup candle closes when bias is neutral.
        # Use 2 of 5 (instead of 3 of 5) to be more responsive — synthetic
        # indices oscillate frequently and waiting for 3/5 consensus means
        # the setup is often already halfway through the move.
        closes = [c.close for c in setup_candles[-5:]]
        if len(closes) >= 2:
            ups = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
            if ups >= 2:
                direction = "bullish"
            elif ups <= 1:
                direction = "bearish"

    state = "continuation" if direction in {"bullish", "bearish"} else "none"
    trade_direction = "buy" if direction == "bullish" else "sell"

    # Build a more informative reason
    if bias.direction != "neutral":
        reason = f"1H setup aligns with {bias.direction} higher-timeframe bias"
    elif direction != "neutral":
        reason = f"1H setup inferred {direction} from recent candle structure (4H neutral)"
    else:
        reason = "1H setup has no clear direction yet"

    return SetupDecision(
        state=state,
        trade_direction=trade_direction,
        trigger_zone_low=min(candle.low for candle in recent),
        trigger_zone_high=max(candle.high for candle in recent),
        reason=reason,
    )
