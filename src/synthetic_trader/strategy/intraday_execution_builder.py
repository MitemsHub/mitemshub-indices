from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle
from synthetic_trader.features.indicators import atr
from synthetic_trader.strategy.stop_loss import smart_stop_loss


@dataclass(frozen=True)
class IntradayExecutionPlan:
    entry: float
    execution_stop: float
    thesis_invalidation: float
    primary_target: float
    extended_target: float | None
    hold_horizon_minutes: int
    trigger_type: str | None = None


@dataclass(frozen=True)
class TriggerSignal:
    trigger_type: str
    entry: float
    failure_level: float
    quality_score: float


def classify_trigger(
    *,
    symbol: str,
    direction: str,
    execution_candles: list[Candle],
    config: TraderConfig,
) -> TriggerSignal | None:
    if len(execution_candles) < 2:
        return None

    profile = config.symbols[symbol]
    recent = execution_candles[-6:]
    latest = recent[-1]
    prior = recent[-2]
    candle_range = max(latest.range, 1e-9)
    body_efficiency = latest.body_abs / candle_range
    close_location = (
        (latest.close - latest.low) / candle_range
        if direction == "buy"
        else (latest.high - latest.close) / candle_range
    )

    reclaimed = latest.close > prior.close and latest.low <= min(
        candle.low for candle in recent[-3:-1]
    )
    reclaim_quality_score = min(1.0, 0.45 + body_efficiency * 0.3 + close_location * 0.2)
    if (
        direction == "buy"
        and reclaimed
        and reclaim_quality_score >= profile.min_reclaim_quality_score
    ):
        shelf = min(candle.low for candle in recent[-3:])
        return TriggerSignal(
            trigger_type="reclaim_pullback",
            entry=latest.close,
            failure_level=shelf,
            quality_score=reclaim_quality_score,
        )

    if (
        direction == "buy"
        and latest.close > prior.high
        and body_efficiency > profile.min_continuation_body_efficiency
        and close_location > profile.min_close_location_strength
    ):
        return TriggerSignal(
            trigger_type="continuation_close",
            entry=latest.high,
            failure_level=latest.low,
            quality_score=min(1.0, 0.5 + body_efficiency * 0.3 + close_location * 0.2),
        )

    recent_closes = recent[:-2]
    if recent_closes:
        breakout_reference = (
            max(candle.close for candle in recent_closes)
            if direction == "buy"
            else min(candle.close for candle in recent_closes)
        )
        retest_hold = (
            latest.low <= prior.low and latest.close >= prior.close - candle_range * 0.15
            if direction == "buy"
            else latest.high >= prior.high and latest.close <= prior.close + candle_range * 0.15
        )
        if (
            direction == "buy"
            and prior.close >= breakout_reference
            and retest_hold
            and body_efficiency > 0.15
            and close_location > 0.8
        ):
            return TriggerSignal(
                trigger_type="break_retest_hold",
                entry=latest.close,
                failure_level=prior.low,
                quality_score=min(1.0, 0.4 + body_efficiency * 0.2 + close_location * 0.2),
            )

    return None


def select_execution_stop(
    *,
    direction: str,
    trigger: TriggerSignal,
    execution_candles: list[Candle],
    max_stop_distance_pct: float = 0.05,
    htf_candles: list[Candle] | None = None,
) -> float:
    """Select the execution stop using the professional 3-layer system.

    When htf_candles (higher-timeframe bias candles) are provided, uses
    the same 3-layer stop logic as the swing execution builder:
      Layer 1: Structural stop from HTF swing points
      Layer 2: Maximum Adverse Excursion from setup candles
      Layer 3: ATR volatility buffer (2.0x ATR)
    Final stop = WIDEST of the three candidates.

    When htf_candles is not provided, falls back to the legacy wick-based
    stop calculation for backward compatibility.
    """
    entry = trigger.entry

    # When HTF candles are available, use the professional 3-layer system.
    # The reference_level is the trigger's failure level (wick-based stop)
    # which serves as one candidate in the 3-layer comparison.
    if htf_candles and len(htf_candles) >= 10:
        atr_14 = atr(execution_candles, 14)
        if atr_14 <= 0:
            atr_14 = abs(entry - trigger.failure_level)
        # Minimum ATR guard: prevent degenerate stops when ATR is near zero
        atr_14 = max(atr_14, entry * 0.001)

        # Use the trigger failure level as the reference (wick-based candidate)
        reference_level = trigger.failure_level
        if reference_level is None:
            reference_level = entry * 0.99 if direction == "buy" else entry * 1.01

        stop = smart_stop_loss(
            htf_candles=htf_candles,
            ltf_candles=execution_candles,
            direction=direction,
            reference_level=reference_level,
            atr_14=atr_14,
            entry=entry,
        )
    else:
        # Legacy path: wick-based stop when no HTF data available
        recent = execution_candles[-6:]
        if trigger.trigger_type == "continuation_close":
            stop = trigger.failure_level
        elif trigger.trigger_type == "reclaim_pullback":
            if direction == "buy":
                stop = min(candle.low for candle in recent[-3:])
            else:
                stop = max(candle.high for candle in recent[-3:])
        elif trigger.trigger_type == "break_retest_hold":
            stop = trigger.failure_level
        elif direction == "buy":
            stop = min(candle.low for candle in recent[-4:])
        else:
            stop = max(candle.high for candle in recent[-4:])

    # Sanity cap: stop distance can never exceed max_stop_distance_pct of entry price.
    max_stop = entry * max_stop_distance_pct
    stop_distance = abs(entry - stop)
    if stop_distance > max_stop:
        if direction == "buy":
            stop = entry - max_stop
        else:
            stop = entry + max_stop

    return stop


def select_primary_target(
    *,
    symbol: str,
    direction: str,
    entry: float,
    execution_stop: float,
    execution_candles: list[Candle],
    config: TraderConfig,
) -> float | None:
    profile = config.symbols[symbol]
    recent = execution_candles[-profile.travel_budget_5m_bars:] if len(execution_candles) >= profile.travel_budget_5m_bars else execution_candles
    if not recent:
        return None

    risk = abs(entry - execution_stop)
    if risk <= 0:
        return None

    travel_window = recent[-profile.travel_budget_5m_bars :]
    travel_budget = sum(candle.range for candle in travel_window) / max(len(travel_window), 1)
    if travel_budget <= 0:
        return None

    # Sanity cap: travel budget can never exceed 5% of entry price.
    # Prevents broken candle data (e.g. 481-point ranges on a 258 instrument)
    # from producing impossible targets like TP=1,336.
    # NOTE: This is a data-quality safeguard, NOT a risk management tool.
    # Stop distance is capped separately via profile.max_stop_distance_pct.
    max_travel = entry * 0.05
    travel_budget = min(travel_budget, max_travel)

    latest = recent[-1]
    prior = recent[:-1]

    if direction == "buy":
        travel_target = entry + travel_budget
        liquidity_candidates = sorted(
            {
                candle.high
                for candle in prior
                if entry < candle.high <= travel_target
            }
        )
    else:
        travel_target = entry - travel_budget
        liquidity_candidates = sorted(
            {
                candle.low
                for candle in prior
                if travel_target <= candle.low < entry
            },
            reverse=True,
        )

    min_reward_risk = profile.min_primary_reward_risk
    for candidate in liquidity_candidates:
        reward = abs(candidate - entry)
        if reward / risk >= min_reward_risk:
            return candidate

    if prior:
        prior_extreme = max(candle.high for candle in prior) if direction == "buy" else min(candle.low for candle in prior)
        if (direction == "buy" and latest.close >= prior_extreme and not liquidity_candidates) or (
            direction == "sell" and latest.close <= prior_extreme and not liquidity_candidates
        ):
            if latest.range >= travel_budget * profile.late_extension_rejection_ratio:
                return None

    reward = abs(travel_target - entry)
    if reward / risk < min_reward_risk:
        return None
    return travel_target


def build_intraday_execution(
    *,
    symbol: str,
    direction: str,
    execution_candles: list[Candle],
    thesis_invalidation: float,
    config: TraderConfig,
    htf_candles: list[Candle] | None = None,
) -> IntradayExecutionPlan | None:
    profile = config.symbols[symbol]
    trigger = classify_trigger(
        symbol=symbol,
        direction=direction,
        execution_candles=execution_candles,
        config=config,
    )
    if trigger is None:
        return None

    execution_stop = select_execution_stop(
        direction=direction,
        trigger=trigger,
        execution_candles=execution_candles,
        max_stop_distance_pct=profile.max_stop_distance_pct,
        htf_candles=htf_candles,
    )

    primary_target = select_primary_target(
        symbol=symbol,
        direction=direction,
        entry=trigger.entry,
        execution_stop=execution_stop,
        execution_candles=execution_candles,
        config=config,
    )
    if primary_target is None:
        return None

    return IntradayExecutionPlan(
        entry=trigger.entry,
        execution_stop=execution_stop,
        thesis_invalidation=thesis_invalidation,
        primary_target=primary_target,
        extended_target=None,
        hold_horizon_minutes=profile.intraday_hold_horizon_minutes,
        trigger_type=trigger.trigger_type,
    )
