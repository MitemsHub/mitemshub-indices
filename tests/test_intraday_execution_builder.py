from __future__ import annotations

import pytest

from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle
from synthetic_trader.strategy.intraday_execution_builder import (
    build_intraday_execution,
    classify_trigger,
    select_execution_stop,
    select_primary_target,
)


def _execution_candle(
    *,
    symbol: str = "R_100",
    open_time: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe_sec=300,
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        tick_count=12,
    )


def execution_candles_for_buy_retest() -> list[Candle]:
    ranges = [2.6, 2.7, 2.8, 2.9, 3.0, 3.1, 3.2, 2.9, 3.0, 2.6, 2.6, 2.2]
    lows = [474.0, 475.0, 476.0, 477.0, 478.0, 479.0, 480.0, 481.0, 484.2, 484.1, 484.0, 483.8]
    closes = [476.0, 477.0, 478.0, 479.0, 480.0, 481.0, 482.1, 483.1, 486.0, 486.0, 486.1, 485.9]

    candles: list[Candle] = []
    for index, (range_size, low, close) in enumerate(zip(ranges, lows, closes)):
        high = low + range_size
        open_price = close - 0.4
        candles.append(
            _execution_candle(
                open_time=index * 300,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
            )
        )
    return candles


def execution_candles_with_wide_stop_and_short_travel() -> list[Candle]:
    ranges = [0.5, 0.6, 0.5, 0.6, 0.4, 0.5, 0.6, 0.4, 0.5, 0.5, 0.6, 0.5]
    lows = [483.0, 483.4, 483.8, 484.2, 484.6, 484.9, 485.2, 479.0, 479.2, 479.5, 479.8, 480.0]
    closes = [483.3, 483.7, 484.1, 484.5, 484.8, 485.1, 485.4, 479.2, 479.5, 479.9, 480.2, 480.3]

    candles: list[Candle] = []
    for index, (range_size, low, close) in enumerate(zip(ranges, lows, closes)):
        high = low + range_size
        open_price = close - 0.2
        candles.append(
            _execution_candle(
                open_time=index * 300,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
            )
        )
    return candles


def execution_candles_for_clean_continuation() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=480.2, high=481.1, low=479.8, close=480.8),
        _execution_candle(open_time=300, open_price=480.8, high=481.7, low=480.3, close=481.4),
        _execution_candle(open_time=600, open_price=481.4, high=482.3, low=480.9, close=482.0),
        _execution_candle(open_time=900, open_price=482.0, high=483.1, low=481.5, close=482.7),
        _execution_candle(open_time=1200, open_price=482.8, high=485.9, low=482.4, close=485.2),
        _execution_candle(open_time=1500, open_price=485.2, high=487.0, low=484.8, close=486.8),
    ]


def execution_candles_for_r75_clean_continuation() -> list[Candle]:
    return [
        _execution_candle(symbol="R_75", open_time=0, open_price=55155.0, high=55220.0, low=55120.0, close=55190.0),
        _execution_candle(symbol="R_75", open_time=300, open_price=55205.0, high=55280.0, low=55170.0, close=55240.0),
        _execution_candle(symbol="R_75", open_time=600, open_price=55255.0, high=55340.0, low=55220.0, close=55300.0),
        _execution_candle(symbol="R_75", open_time=900, open_price=55320.0, high=55420.0, low=55280.0, close=55370.0),
        _execution_candle(symbol="R_75", open_time=1200, open_price=55390.0, high=55480.0, low=55320.0, close=55420.0),
        _execution_candle(symbol="R_75", open_time=1500, open_price=55480.0, high=55540.0, low=55460.0, close=55530.0),
    ]


def execution_candles_for_r75_marginal_continuation() -> list[Candle]:
    return [
        _execution_candle(symbol="R_75", open_time=0, open_price=982.2, high=984.0, low=981.8, close=983.6),
        _execution_candle(symbol="R_75", open_time=300, open_price=983.6, high=985.7, low=983.1, close=985.0),
        _execution_candle(symbol="R_75", open_time=600, open_price=985.0, high=987.4, low=984.4, close=986.8),
        _execution_candle(symbol="R_75", open_time=900, open_price=986.8, high=989.8, low=986.2, close=989.1),
        _execution_candle(symbol="R_75", open_time=1200, open_price=989.1, high=992.4, low=988.6, close=991.7),
        _execution_candle(symbol="R_75", open_time=1500, open_price=992.1, high=995.0, low=990.0, close=994.9),
    ]


def execution_candles_for_r75_late_extension() -> list[Candle]:
    return [
        _execution_candle(symbol="R_75", open_time=0, open_price=55495.0, high=55540.0, low=55470.0, close=55525.0),
        _execution_candle(symbol="R_75", open_time=300, open_price=55520.0, high=55585.0, low=55500.0, close=55570.0),
        _execution_candle(symbol="R_75", open_time=600, open_price=55575.0, high=55620.0, low=55530.0, close=55605.0),
        _execution_candle(symbol="R_75", open_time=900, open_price=55600.0, high=55655.0, low=55560.0, close=55635.0),
        _execution_candle(symbol="R_75", open_time=1200, open_price=55630.0, high=55690.0, low=55590.0, close=55670.0),
        _execution_candle(symbol="R_75", open_time=1500, open_price=55640.0, high=55780.0, low=55610.0, close=55750.0),
    ]


def execution_candles_for_r75_balanced_target() -> list[Candle]:
    ranges = [520.0, 530.0, 540.0, 550.0, 560.0, 570.0, 580.0, 590.0, 600.0, 610.0, 600.0, 400.0]
    lows = [9840.0, 9950.0, 10070.0, 10200.0, 10340.0, 10490.0, 10650.0, 10820.0, 11000.0, 11190.0, 11390.0, 11640.0]
    closes = [10300.0, 10420.0, 10550.0, 10690.0, 10840.0, 11000.0, 11170.0, 11350.0, 11540.0, 11740.0, 11940.0, 12000.0]

    candles: list[Candle] = []
    for index, (range_size, low, close) in enumerate(zip(ranges, lows, closes)):
        high = low + range_size
        open_price = close - min(260.0, range_size * 0.7)
        candles.append(
            _execution_candle(
                symbol="R_75",
                open_time=index * 300,
                open_price=open_price,
                high=high,
                low=low,
                close=close,
            )
        )
    return candles


def execution_candles_for_reclaim_pullback() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=471.2, high=472.2, low=470.8, close=471.8),
        _execution_candle(open_time=300, open_price=471.8, high=473.0, low=471.4, close=472.6),
        _execution_candle(open_time=600, open_price=472.5, high=474.1, low=472.0, close=473.7),
        _execution_candle(open_time=900, open_price=473.8, high=475.4, low=475.2, close=475.3),
        _execution_candle(open_time=1200, open_price=475.1, high=476.0, low=475.0, close=475.5),
        _execution_candle(open_time=1500, open_price=475.4, high=477.0, low=474.6, close=476.8),
    ]


def execution_candles_for_weak_noisy_close() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=482.1, high=483.0, low=481.7, close=482.7),
        _execution_candle(open_time=300, open_price=482.7, high=483.6, low=482.3, close=483.2),
        _execution_candle(open_time=600, open_price=483.2, high=484.0, low=482.8, close=483.5),
        _execution_candle(open_time=900, open_price=483.5, high=484.3, low=483.0, close=483.8),
        _execution_candle(open_time=1200, open_price=483.8, high=485.4, low=483.3, close=485.0),
        _execution_candle(open_time=1500, open_price=485.3, high=486.1, low=484.9, close=485.4),
    ]


def execution_candles_for_break_retest_hold() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=476.0, high=477.3, low=475.5, close=476.6),
        _execution_candle(open_time=300, open_price=476.6, high=478.1, low=476.0, close=477.3),
        _execution_candle(open_time=600, open_price=477.3, high=479.0, low=476.8, close=478.0),
        _execution_candle(open_time=900, open_price=478.0, high=479.8, low=477.6, close=478.9),
        _execution_candle(open_time=1200, open_price=478.9, high=482.1, low=478.5, close=481.2),
        _execution_candle(open_time=1500, open_price=480.9, high=481.8, low=479.2, close=481.0),
        _execution_candle(open_time=1800, open_price=481.0, high=482.6, low=480.6, close=482.1),
        _execution_candle(open_time=2100, open_price=482.1, high=483.6, low=481.6, close=483.0),
        _execution_candle(open_time=2400, open_price=483.0, high=484.4, low=482.4, close=483.7),
        _execution_candle(open_time=2700, open_price=483.7, high=485.1, low=483.1, close=484.4),
        _execution_candle(open_time=3000, open_price=484.4, high=485.9, low=484.1, close=485.1),
        _execution_candle(open_time=3300, open_price=485.1, high=486.0, low=483.8, close=485.8),
    ]


def execution_candles_for_pattern_aware_continuation_stop() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=480.7, high=483.0, low=480.0, close=482.2),
        _execution_candle(open_time=300, open_price=481.6, high=484.2, low=481.0, close=483.6),
        _execution_candle(open_time=600, open_price=483.2, high=486.2, low=482.0, close=485.3),
        _execution_candle(open_time=900, open_price=484.0, high=486.8, low=482.4, close=485.9),
        _execution_candle(open_time=1200, open_price=484.7, high=486.4, low=481.6, close=485.8),
        _execution_candle(open_time=1500, open_price=485.3, high=487.2, low=484.7, close=486.9),
    ]


def execution_candles_for_pattern_aware_reclaim_stop() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=470.8, high=473.0, low=470.0, close=472.2),
        _execution_candle(open_time=300, open_price=472.0, high=474.3, low=471.0, close=473.4),
        _execution_candle(open_time=600, open_price=473.0, high=475.7, low=471.5, close=474.6),
        _execution_candle(open_time=900, open_price=475.0, high=477.2, low=475.1, close=476.2),
        _execution_candle(open_time=1200, open_price=476.0, high=479.0, low=475.0, close=475.6),
        _execution_candle(open_time=1500, open_price=475.5, high=477.4, low=474.8, close=476.9),
    ]


def execution_candles_for_balanced_liquidity_target() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=480.3, high=481.2, low=480.0, close=480.8),
        _execution_candle(open_time=300, open_price=480.8, high=482.0, low=480.7, close=481.5),
        _execution_candle(open_time=600, open_price=481.5, high=482.8, low=481.5, close=482.2),
        _execution_candle(open_time=900, open_price=482.2, high=483.6, low=482.2, close=483.0),
        _execution_candle(open_time=1200, open_price=483.0, high=484.4, low=483.0, close=483.7),
        _execution_candle(open_time=1500, open_price=483.7, high=485.2, low=483.7, close=484.6),
        _execution_candle(open_time=1800, open_price=485.0, high=487.6, low=484.0, close=484.8),
        _execution_candle(open_time=2100, open_price=484.8, high=485.4, low=484.4, close=484.9),
        _execution_candle(open_time=2400, open_price=484.9, high=485.0, low=484.0, close=484.6),
        _execution_candle(open_time=2700, open_price=484.6, high=485.3, low=484.3, close=484.9),
        _execution_candle(open_time=3000, open_price=484.9, high=485.7, low=484.7, close=485.3),
        _execution_candle(open_time=3300, open_price=485.4, high=486.4, low=485.5, close=486.2),
    ]


def execution_candles_for_late_extension() -> list[Candle]:
    return [
        _execution_candle(open_time=0, open_price=480.1, high=481.0, low=479.8, close=480.7),
        _execution_candle(open_time=300, open_price=480.7, high=481.7, low=480.4, close=481.3),
        _execution_candle(open_time=600, open_price=481.3, high=482.4, low=481.1, close=482.0),
        _execution_candle(open_time=900, open_price=482.0, high=483.2, low=481.8, close=482.8),
        _execution_candle(open_time=1200, open_price=482.8, high=484.0, low=482.7, close=483.5),
        _execution_candle(open_time=1500, open_price=483.5, high=484.8, low=483.4, close=484.2),
        _execution_candle(open_time=1800, open_price=484.2, high=485.2, low=484.0, close=484.9),
        _execution_candle(open_time=2100, open_price=484.9, high=485.8, low=484.7, close=485.5),
        _execution_candle(open_time=2400, open_price=485.5, high=486.4, low=485.3, close=486.1),
        _execution_candle(open_time=2700, open_price=486.1, high=487.0, low=485.9, close=486.8),
        _execution_candle(open_time=3000, open_price=486.8, high=487.7, low=486.7, close=487.5),
        _execution_candle(open_time=3300, open_price=487.5, high=488.6, low=487.7, close=488.4),
    ]


def test_symbol_profiles_expose_dual_symbol_intraday_calibration_fields() -> None:
    config = TraderConfig.default()

    r75 = config.symbols["R_75"]
    r100 = config.symbols["R_100"]

    assert r75.min_continuation_body_efficiency is not None
    assert r75.late_extension_rejection_ratio is not None
    assert r100.min_continuation_body_efficiency is not None
    assert r100.late_extension_rejection_ratio is not None
    assert r75.travel_budget_5m_bars != r100.travel_budget_5m_bars or (
        r75.min_continuation_body_efficiency != r100.min_continuation_body_efficiency
    )


def test_build_intraday_execution_uses_5m_swing_for_execution_stop() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_buy_retest(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.execution_stop > 440.67
    assert plan.execution_stop < plan.entry
    assert plan.thesis_invalidation == 440.67


def test_build_intraday_execution_chooses_reachable_primary_target_over_projected_far_target() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_buy_retest(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.primary_target == pytest.approx(488.7)
    assert plan.extended_target is None or plan.extended_target > plan.primary_target


def test_build_intraday_execution_rejects_bloated_geometry_when_reachable_target_cannot_pay_for_local_stop() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_with_wide_stop_and_short_travel(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is None


def test_build_intraday_execution_uses_continuation_failure_level_for_execution_stop() -> None:
    candles = execution_candles_for_pattern_aware_continuation_stop()
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=candles,
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.execution_stop == candles[-1].low
    assert plan.execution_stop > min(candle.low for candle in candles[-4:])


def test_build_intraday_execution_uses_reclaim_failure_level_for_execution_stop() -> None:
    candles = execution_candles_for_pattern_aware_reclaim_stop()
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=candles,
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.execution_stop == candles[-1].low
    assert plan.execution_stop > min(candle.low for candle in candles[-4:])


def test_build_intraday_execution_accepts_clean_r75_plan_with_realistic_primary_target() -> None:
    plan = build_intraday_execution(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_clean_continuation(),
        thesis_invalidation=54800.0,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.primary_target > plan.entry
    assert plan.primary_target != plan.thesis_invalidation


def test_build_intraday_execution_rejects_weak_r75_late_extension() -> None:
    plan = build_intraday_execution(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_late_extension(),
        thesis_invalidation=54800.0,
        config=TraderConfig.default(),
    )

    assert plan is None


def test_build_intraday_execution_accepts_clean_break_retest_hold() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_break_retest_hold(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is not None
    assert plan.execution_stop < plan.entry
    assert plan.primary_target > plan.entry


def test_build_intraday_execution_rejects_weak_noisy_close_after_helper_refactor() -> None:
    plan = build_intraday_execution(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_weak_noisy_close(),
        thesis_invalidation=440.67,
        config=TraderConfig.default(),
    )

    assert plan is None


def test_classify_trigger_identifies_clean_continuation_close() -> None:
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_clean_continuation(),
        config=TraderConfig.default(),
    )

    assert trigger is not None
    assert trigger.trigger_type == "continuation_close"
    assert trigger.quality_score > 0.7


def test_classify_trigger_accepts_clean_r75_continuation_under_r75_thresholds() -> None:
    trigger = classify_trigger(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_clean_continuation(),
        config=TraderConfig.default(),
    )

    assert trigger is not None
    assert trigger.trigger_type == "continuation_close"


def test_classify_trigger_rejects_marginal_r75_continuation_that_r100_would_allow() -> None:
    trigger = classify_trigger(
        symbol="R_75",
        direction="buy",
        execution_candles=execution_candles_for_r75_marginal_continuation(),
        config=TraderConfig.default(),
    )

    assert trigger is None


def test_classify_trigger_identifies_reclaim_pullback() -> None:
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_reclaim_pullback(),
        config=TraderConfig.default(),
    )

    assert trigger is not None
    assert trigger.trigger_type == "reclaim_pullback"
    assert trigger.quality_score > 0.65


def test_classify_trigger_rejects_weak_noisy_close() -> None:
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=execution_candles_for_weak_noisy_close(),
        config=TraderConfig.default(),
    )

    assert trigger is None


def test_select_primary_target_prefers_nearest_liquidity_inside_balanced_travel_budget() -> None:
    candles = execution_candles_for_balanced_liquidity_target()
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert trigger is not None

    target = select_primary_target(
        symbol="R_100",
        direction="buy",
        entry=trigger.entry,
        execution_stop=trigger.failure_level,
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert target == pytest.approx(487.6)


def test_select_primary_target_uses_r75_travel_budget_for_next_hour_objective() -> None:
    candles = execution_candles_for_r75_balanced_target()
    trigger = classify_trigger(
        symbol="R_75",
        direction="buy",
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert trigger is not None

    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=candles,
    )
    target = select_primary_target(
        symbol="R_75",
        direction="buy",
        entry=trigger.entry,
        execution_stop=stop,
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert target == pytest.approx(12600.0)
    assert target < trigger.entry + 800.0


def test_select_primary_target_rejects_r100_late_extension_using_symbol_ratio() -> None:
    candles = execution_candles_for_late_extension()
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert trigger is not None

    stop = select_execution_stop(
        direction="buy",
        trigger=trigger,
        execution_candles=candles,
    )
    target = select_primary_target(
        symbol="R_100",
        direction="buy",
        entry=trigger.entry,
        execution_stop=stop,
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert target is None


def test_select_primary_target_rejects_overextended_late_move() -> None:
    candles = execution_candles_for_late_extension()
    trigger = classify_trigger(
        symbol="R_100",
        direction="buy",
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert trigger is not None

    target = select_primary_target(
        symbol="R_100",
        direction="buy",
        entry=trigger.entry,
        execution_stop=trigger.failure_level,
        execution_candles=candles,
        config=TraderConfig.default(),
    )

    assert target is None
