from synthetic_trader.strategy.setup_builder import classify_setup
from synthetic_trader.strategy.top_down_bias import TopDownBias
from tests.test_decision_engine import trending_candles


def test_classify_setup_marks_pullback_continuation_when_bias_and_setup_align() -> None:
    setup = classify_setup(
        bias=TopDownBias(
            direction="bullish",
            reason="4H structure is bullish",
            invalidation_price=98.0,
        ),
        setup_candles=trending_candles(symbol="R_75", count=100),
    )

    assert setup.state == "continuation"
    assert setup.trade_direction == "buy"
    assert setup.trigger_zone_low is not None
    assert setup.trigger_zone_high is not None
