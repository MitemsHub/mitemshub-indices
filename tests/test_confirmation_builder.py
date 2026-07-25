from synthetic_trader.domain import Candle
from synthetic_trader.strategy.confirmation_builder import confirm_setup
from synthetic_trader.strategy.setup_builder import SetupDecision
from tests.test_decision_engine import trending_candles


def _confirmation_candles(symbol: str, closes: list[float]) -> list[Candle]:
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_price = closes[index - 1] if index else close - 0.2
        high = max(open_price, close) + 0.05
        low = min(open_price, close) - 0.05
        candles.append(
            Candle(
                symbol=symbol,
                timeframe_sec=900,
                open_time=index * 900,
                open=open_price,
                high=high,
                low=low,
                close=close,
                tick_count=15,
            )
        )
    return candles


def test_confirm_setup_requires_lower_timeframe_alignment() -> None:
    result = confirm_setup(
        setup=SetupDecision(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=101.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        ),
        confirmation_candles=trending_candles(symbol="R_75", count=60),
    )

    assert result.state == "confirmed"
    assert "15m" in result.reason.lower()


def test_confirm_setup_allows_r100_bullish_continuation_through_small_counter_close() -> None:
    result = confirm_setup(
        setup=SetupDecision(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=101.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        ),
        confirmation_candles=_confirmation_candles(
            "R_100",
            [100.0, 100.8, 101.6, 101.35],
        ),
    )

    assert result.state == "confirmed"
    assert "15m" in result.reason.lower()


def test_confirm_setup_allows_r100_bearish_continuation_through_small_counter_close() -> None:
    result = confirm_setup(
        setup=SetupDecision(
            state="continuation",
            trade_direction="sell",
            trigger_zone_low=97.0,
            trigger_zone_high=99.0,
            reason="1H setup aligns with bearish higher-timeframe bias",
        ),
        confirmation_candles=_confirmation_candles(
            "R_100",
            [100.0, 99.2, 98.4, 98.65],
        ),
    )

    assert result.state == "confirmed"
    assert "15m" in result.reason.lower()
