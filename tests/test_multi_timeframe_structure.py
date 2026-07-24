from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.features.multi_timeframe_structure import build_structure_map
from tests.test_decision_engine import trending_candles


def test_build_structure_map_extracts_bias_and_invalidation_zones() -> None:
    structure = build_structure_map(
        bias_candles=trending_candles(symbol="R_75", count=120),
        setup_candles=trending_candles(symbol="R_75", count=90),
        confirmation_candles=trending_candles(symbol="R_75", count=60),
        execution_candles=trending_candles(symbol="R_75", count=40),
    )

    assert structure.bias_direction == "bullish"
    assert structure.bias_zone_low is not None
    assert structure.bias_zone_high is not None
    assert structure.invalidation_price is not None
    assert structure.target_one is not None
    assert structure.target_extended is not None


def test_build_snapshot_includes_multi_timeframe_feature_prefixes() -> None:
    snapshot = build_snapshot(
        symbol="R_75",
        timeframe_sec=300,
        candles=trending_candles(symbol="R_75", count=80),
        higher_timeframe_candles=trending_candles(symbol="R_75", count=60),
        extra_timeframes={
            "bias": trending_candles(symbol="R_75", count=120),
            "setup": trending_candles(symbol="R_75", count=90),
            "confirmation": trending_candles(symbol="R_75", count=70),
        },
    )

    assert "bias_structure_bias" in snapshot.features
    assert "setup_structure_bias" in snapshot.features
    assert "confirmation_structure_bias" in snapshot.features
