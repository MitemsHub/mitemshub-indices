from types import SimpleNamespace
from unittest.mock import patch

from synthetic_trader.config import TraderConfig
from tests.test_decision_engine import trending_candles


def test_default_symbol_profile_exposes_top_down_timeframes() -> None:
    config = TraderConfig.default()
    r75 = config.symbols["R_75"]

    assert r75.bias_timeframe_sec == 14_400
    assert r75.setup_timeframe_sec == 3_600
    assert r75.confirmation_timeframe_sec == 900
    assert r75.execution_timeframe_sec == 300
    assert r75.monitoring_timeframe_sec == 60
    assert r75.hold_bars_bias >= 6


def test_infer_top_down_bias_prefers_higher_timeframe_structure() -> None:
    from synthetic_trader.strategy.top_down_bias import infer_top_down_bias

    bias = infer_top_down_bias(
        symbol="R_75",
        bias_candles=trending_candles(symbol="R_75", count=150),
        setup_candles=trending_candles(symbol="R_75", count=100),
    )

    assert bias.direction == "bullish"
    assert "4h" in bias.reason.lower()
    assert bias.invalidation_price is not None


def test_infer_top_down_bias_forwards_named_role_candles_to_structure_map() -> None:
    from synthetic_trader.strategy.top_down_bias import infer_top_down_bias

    bias_candles = trending_candles(symbol="R_75", count=150)
    setup_candles = trending_candles(symbol="R_75", count=100)
    confirmation_candles = trending_candles(symbol="R_75", count=60)
    execution_candles = trending_candles(symbol="R_75", count=40)

    with patch(
        "synthetic_trader.strategy.top_down_bias.build_structure_map",
        return_value=SimpleNamespace(
            bias_direction="bullish",
            invalidation_price=101.0,
            structure_notes=("test note",),
            confluence_score=0.5,
            bias_regime="trend_up",
            setup_regime="trend_up",
            confirmation_regime="trend_up",
            execution_regime="trend_up",
        ),
    ) as build_map:
        infer_top_down_bias(
            symbol="R_75",
            bias_candles=bias_candles,
            setup_candles=setup_candles,
            confirmation_candles=confirmation_candles,
            execution_candles=execution_candles,
        )

    build_map.assert_called_once_with(
        bias_candles=bias_candles,
        setup_candles=setup_candles,
        confirmation_candles=confirmation_candles,
        execution_candles=execution_candles,
    )
