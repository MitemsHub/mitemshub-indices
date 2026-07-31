from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from synthetic_trader.domain import Candle
from synthetic_trader.features.indicators import atr, clamp, safe_div
from synthetic_trader.strategy.setup_builder import SetupDecision


class CallState(str, Enum):
    FORMING = "forming"
    ACTIONABLE = "actionable"
    CONFIRMED = "confirmed"
    FAILING = "failing"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ConfirmationDecision:
    state: str
    reason: str
    confidence: float = 0.0
    triggers: tuple[str, ...] = ()


def _is_r100_counter_close_continuation(
    *,
    setup: SetupDecision,
    confirmation_candles: list[Candle],
) -> bool:
    if len(confirmation_candles) < 3 or confirmation_candles[-1].symbol != "R_100":
        return False

    anchor_close = confirmation_candles[-3].close
    previous_close = confirmation_candles[-2].close
    latest_close = confirmation_candles[-1].close

    if setup.trade_direction == "buy":
        impulse = previous_close - anchor_close
        pullback = previous_close - latest_close
        return impulse > 0 and latest_close > anchor_close and 0.0 <= pullback <= impulse * 0.5

    impulse = anchor_close - previous_close
    pullback = latest_close - previous_close
    return impulse > 0 and latest_close < anchor_close and 0.0 <= pullback <= impulse * 0.5


def _assess_confirmation_quality(
    setup: SetupDecision,
    confirmation_candles: list[Candle],
) -> tuple[float, tuple[str, ...]]:
    if len(confirmation_candles) < 3:
        return 0.0, ("insufficient confirmation candles",)

    latest = confirmation_candles[-1]
    prev = confirmation_candles[-2]
    anchor = confirmation_candles[-3]
    atr_val = atr(confirmation_candles[-14:], 14) if len(confirmation_candles) >= 14 else max(c.range for c in confirmation_candles[-5:])

    triggers = []
    quality = 0.0

    body_efficiency = safe_div(abs(latest.body), latest.range, 0.0)
    close_location = (
        (latest.close - latest.low) / latest.range
        if setup.trade_direction == "buy" and latest.range > 0
        else (latest.high - latest.close) / latest.range
        if latest.range > 0
        else 0.5
    )

    impulse = prev.close - anchor.close if setup.trade_direction == "buy" else anchor.close - prev.close
    pullback = prev.close - latest.close if setup.trade_direction == "buy" else latest.close - prev.close

    if impulse > 0:
        pullback_ratio = safe_div(pullback, impulse, 1.0)
        if pullback_ratio <= 0.3:
            quality += 0.3
            triggers.append("shallow_pullback")
        elif pullback_ratio <= 0.5:
            quality += 0.2
            triggers.append("controlled_pullback")
        else:
            triggers.append("deep_pullback")

    if body_efficiency > 0.6:
        quality += 0.2
        triggers.append("strong_body")
    elif body_efficiency > 0.4:
        quality += 0.1
        triggers.append("decent_body")

    if close_location > 0.7:
        quality += 0.2
        triggers.append("strong_close_location")
    elif close_location > 0.5:
        quality += 0.1
        triggers.append("moderate_close_location")

    if latest.close > prev.close and setup.trade_direction == "buy":
        quality += 0.15
        triggers.append("continuation_close")
    elif latest.close < prev.close and setup.trade_direction == "sell":
        quality += 0.15
        triggers.append("continuation_close")

    atr_mult = safe_div(latest.range, atr_val, 1.0) if atr_val > 0 else 1.0
    if 0.5 <= atr_mult <= 2.0:
        quality += 0.1
        triggers.append("normal_volatility")

    return clamp(quality, 0.0, 1.0), tuple(triggers)



def _evaluate_call_lifecycle(
    setup: SetupDecision,
    confirmation_candles: list[Candle],
    previous_state: str | None = None,
) -> CallState:
    if len(confirmation_candles) < 2:
        return CallState.FORMING
    immediate_alignment = (
        confirmation_candles[-1].close >= confirmation_candles[-2].close
        if setup.trade_direction == "buy"
        else confirmation_candles[-1].close <= confirmation_candles[-2].close
    )
    relaxed_r100_alignment = _is_r100_counter_close_continuation(
        setup=setup,
        confirmation_candles=confirmation_candles,
    )

    quality, _ = _assess_confirmation_quality(setup, confirmation_candles)

    if previous_state == CallState.CONFIRMED:
        # ── Confirmed→Failing: require STRONG evidence ──────────
        # A confirmed signal represents a validated setup.  On volatile
        # synthetic indices, a single candle where the close doesn't
        # continue direction is NORMAL — it's consolidation, not
        # deterioration.  Only fail when:
        #   1. quality drops below 0.2 (very weak — not just "below 0.4"), AND
        #   2. there is no immediate alignment (close against direction)
        #
        # Quality 0.2 means almost no quality triggers fired — the candle
        # is genuinely broken, not just a normal consolidation bar.
        if not immediate_alignment and quality < 0.2:
            return CallState.FAILING
        return CallState.CONFIRMED

    if previous_state == CallState.ACTIONABLE:
        if immediate_alignment and quality >= 0.5:
            return CallState.CONFIRMED
        if quality < 0.3:
            return CallState.FAILING
        return CallState.ACTIONABLE

    if immediate_alignment or relaxed_r100_alignment:
        if quality >= 0.40 or relaxed_r100_alignment:
            return CallState.CONFIRMED
        return CallState.ACTIONABLE

    # Lowered from 0.3 to 0.2 — with volatile synthetic indices the
    # quality score often lands at 0.15-0.25, which is still meaningful.
    # Allowing ACTIONABLE at 0.2 lets the trade plan surface faster
    # while still filtering out noise (quality < 0.15).
    if quality >= 0.2:
        return CallState.ACTIONABLE

    return CallState.FORMING


def confirm_setup(
    *, setup: SetupDecision, confirmation_candles: list[Candle], previous_state: str | None = None
) -> ConfirmationDecision:
    state = _evaluate_call_lifecycle(setup, confirmation_candles, previous_state)
    quality, triggers = _assess_confirmation_quality(setup, confirmation_candles)

    reasons = {
        CallState.FORMING: "15m confirmation still forming; waiting for directional alignment",
        CallState.ACTIONABLE: "15m confirmation actionable; setup aligned but needs stronger close",
        CallState.CONFIRMED: "15m confirmation received; strong directional alignment with quality",
        CallState.FAILING: "15m confirmation failing; structure weakening against setup",
        CallState.CANCELLED: "15m confirmation cancelled; setup invalidated by adverse structure",
    }

    return ConfirmationDecision(
        state=state.value,
        reason=reasons.get(state, "unknown state"),
        confidence=quality,
        triggers=triggers,
    )
