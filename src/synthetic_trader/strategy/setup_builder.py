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
    return SetupDecision(
        state="continuation" if bias.direction in {"bullish", "bearish"} else "none",
        trade_direction="buy" if bias.direction == "bullish" else "sell",
        trigger_zone_low=min(candle.low for candle in recent),
        trigger_zone_high=max(candle.high for candle in recent),
        reason=f"1H setup aligns with {bias.direction} higher-timeframe bias",
    )
