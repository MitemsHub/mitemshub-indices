from __future__ import annotations

from dataclasses import dataclass

# Number of ticks to suppress 'failing' after a plan is first generated.
# On volatile synthetic indices, the price often moves against the entry
# within the first few ticks while the candle is still forming.
GRACE_PERIOD_TICKS = 8

# Minimum ticks after confirmation before the guardian re-evaluates
# microstructure for sniper mode.  Sniper trades target 4-6 hour holds,
# so re-checking microstructure every 5 seconds is counterproductive —
# normal pullbacks on volatile synthetics will always trigger "failing".
# After confirmation, the guardian should only check thesis invalidation
# (stop hit) on sniper mode.
SNIPER_MICRO_REEVAL_INTERVAL_TICKS = 0  # Immediately skip microstructure after confirmation for sniper mode
# Sniper trades target 4-6 hour holds.  Once confirmed, the guardian should
# ONLY check thesis invalidation (stop hit / max adverse excursion).
# Normal pullbacks on volatile synthetics will ALWAYS trigger "failing"
# via pullback_ratio or acceleration_shift checks — this is the root cause
# of "Plan is losing strength" appearing within seconds of a confirmed call.


@dataclass(frozen=True)
class GuardianThresholds:
    max_arming_ticks: int
    max_confirmation_window_ticks: int
    weakening_excursion_ratio: float
    max_adverse_excursion_ratio: float
    max_entry_drift_ratio: float
    microstructure_window_ticks: int
    min_persistence_ticks: int
    min_impulse_ratio: float
    max_pullback_ratio: float
    rollover_warning_ratio: float
    rollover_invalidation_ratio: float
    adverse_cluster_window_ticks: int
    max_adverse_cluster_count: int
    # Once a signal reaches 'confirmed', lock it for this many ticks
    # before allowing downgrade to 'failing'.  Confirmed signals are
    # validated setups that shouldn't flip on normal price noise.
    # The actual lock duration scales dynamically with confidence:
    #   confidence >= 0.75 → confirmed_lock_ticks_high (extended)
    #   confidence <  0.50 → confirmed_lock_ticks_low  (shortened)
    #   otherwise         → confirmed_lock_ticks       (default)
    # Once confirmed, hold that status for at least 60 ticks (5 minutes)
    # on a 5-second tick chart.  This gives the user time to execute
    # on their phone without the setup flickering to 'failing'.
    # High-confidence setups get 90 ticks (7.5 minutes), low-confidence
    # get 30 ticks (2.5 minutes).
    confirmed_lock_ticks: int = 60
    confirmed_lock_ticks_high: int = 90
    confirmed_lock_ticks_low: int = 30
    # Breakeven trail (band geometry): once the position's max favorable
    # excursion reaches this fraction of the TARGET distance, the effective
    # stop moves to ENTRY — the trade is risk-free and only dies if price
    # trades all the way back through the breakeven level (confirmed by a
    # closed execution candle, matching the stop-lock grace).  0 disables.
    # This is what made the band geometry positive-expectancy in backtest:
    # without it, losing streaks tripped the risk engine and the strategy
    # netted -0.84R instead of +0.65R.
    breakeven_trail_frac: float = 0.3


@dataclass(frozen=True)
class GuardianSnapshot:
    symbol: str
    direction_bias: str
    trade_status: str
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    current_close: float | None


@dataclass(frozen=True)
class GuardianContext:
    tick_prices: list[float]
    ticks_since_armed: int
    max_favorable_excursion: float
    max_adverse_excursion: float
    # Previous guardian state from the last evaluation.  Used to detect
    # confirmed->failing transitions so we can apply the lock.
    previous_guardian_state: str | None = None
    # Tick number when the signal was first confirmed.  Set by the
    # caller when previous_guardian_state == "confirmed".
    first_confirmed_at_tick: int | None = None
    # Confidence level at the time of first confirmation.  Used to
    # scale the confirmed lock duration dynamically.
    confidence_at_confirmation: float | None = None
    # Current confidence level from the decision engine.  Used to
    # determine the effective lock duration for re-evaluation.
    current_confidence: float | None = None
    # Real ATR_14 from features — used for trailing stop calculations.
    # Avoids approximating ATR from stop_distance which is fragile.
    atr_14: float | None = None
    # Trading mode (sniper only).
    # After confirmation, skip microstructure re-evaluation;
    # only check thesis invalidation (stop hit).  Swing trades target
    # 4-6 hour holds so tick-level microstructure noise is irrelevant.
    trading_mode: str | None = None
    # Execution timeframe in seconds for the swing plan (sniper: 900 = 15m).
    # Used by the stop-lock grace: a stop trade-through only cancels the
    # plan when it is confirmed by a CLOSED candle of this timeframe, so
    # spread/jitter wicks inside the still-forming candle cannot stop out
    # a valid plan.
    execution_timeframe_sec: int = 900
    # Precomputed by the caller (``build_guardian_snapshot``): True when a
    # closed execution-timeframe candle has traded through the stop.  None
    # means the caller provided no candle data — treated as not confirmed
    # (conservative: intraday wicks alone never cancel a swing plan).
    stop_traded_on_closed_candle: bool | None = None
    # True when a CLOSED execution-timeframe candle traded through the ENTRY
    # (the breakeven level).  Only meaningful once the breakeven trail is
    # armed — used to cancel a trailed plan without letting a wick flap it.
    # None means no candle data (fall back to the current print).
    entry_traded_on_closed_candle: bool | None = None


@dataclass(frozen=True)
class GuardianEvaluation:
    state: str
    reason: str
    # When the guardian detects that the stop should be moved (trailing stop
    # / breakeven protection), it sets recommended_stop to the new stop level.
    # The execution layer can use this to modify the order on MT5.
    # - None: no stop modification recommended
    # - float: new stop level (breakeven + buffer, or trailed stop)
    recommended_stop: float | None = None


@dataclass(frozen=True)
class MicrostructureAssessment:
    persistence_ticks: int
    impulse_ratio: float
    pullback_ratio: float
    rejection_imbalance: float
    acceleration_shift: float
    adverse_cluster_count: int


def _stop_distance(snapshot: GuardianSnapshot) -> float | None:
    if snapshot.entry is None or snapshot.stop_loss is None:
        return None
    return abs(snapshot.entry - snapshot.stop_loss)


def _current_adverse_excursion(snapshot: GuardianSnapshot) -> float:
    """Adverse excursion measured from the CURRENT price, not the window max.

    The window max (``context.max_adverse_excursion``) is a monotonic
    accumulator over the whole re-armed window: a single transient wick near
    the stop marks it permanently, even after price recovers.  For swing
    plans that metric alone would cancel a plan on noise.  The current price
    tells us whether the adverse move is *sustained right now*.
    """
    if snapshot.current_close is None or snapshot.entry is None:
        return 0.0
    if snapshot.direction_bias == "buy":
        return max(0.0, snapshot.entry - snapshot.current_close)
    if snapshot.direction_bias == "sell":
        return max(0.0, snapshot.current_close - snapshot.entry)
    return 0.0


def _effective_confirmed_lock_ticks(
    thresholds: GuardianThresholds,
    confidence: float | None,
) -> int:
    """Return the lock duration in ticks, scaled by confidence.

    High-confidence setups (>= 0.75) get a longer lock (90 ticks / 7.5 min)
    because they're more likely to be genuine.  Low-confidence setups
    (< 0.50) get a shorter lock (30 ticks / 2.5 min) so they can degrade
    faster if the setup proves weak.  Middle-range uses the default
    (60 ticks / 5 min).
    """
    if confidence is None:
        return thresholds.confirmed_lock_ticks
    if confidence >= 0.75:
        return thresholds.confirmed_lock_ticks_high
    if confidence < 0.50:
        return thresholds.confirmed_lock_ticks_low
    return thresholds.confirmed_lock_ticks


def _directional_deltas(prices: list[float], direction_bias: str) -> list[float]:
    raw = [right - left for left, right in zip(prices, prices[1:])]
    if direction_bias == "buy":
        return raw
    if direction_bias == "sell":
        return [-delta for delta in raw]
    return [0.0 for _ in raw]


def _count_persistence_ticks(direction_deltas: list[float], minimum_tick_move: float) -> int:
    return sum(1 for delta in direction_deltas if delta >= minimum_tick_move)


def _count_adverse_clusters(direction_deltas: list[float]) -> int:
    clusters = 0
    previous_was_adverse = False
    for delta in direction_deltas:
        is_adverse = delta < 0
        if is_adverse and not previous_was_adverse:
            clusters += 1
        previous_was_adverse = is_adverse
    return clusters


def _assess_microstructure(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
    stop_distance: float,
) -> MicrostructureAssessment:
    prices = context.tick_prices[-thresholds.microstructure_window_ticks :]
    direction_deltas = _directional_deltas(prices, snapshot.direction_bias)
    meaningful_tick_floor = (
        stop_distance * thresholds.min_impulse_ratio / max(thresholds.min_persistence_ticks, 1)
        if stop_distance
        else 0.0
    )
    positive = [delta for delta in direction_deltas if delta > 0]
    adverse = [abs(delta) for delta in direction_deltas if delta < 0]
    recent_direction_deltas = direction_deltas[-thresholds.adverse_cluster_window_ticks :]
    impulse_ratio = sum(positive) / stop_distance if stop_distance else 0.0
    pullback_ratio = max(adverse, default=0.0) / stop_distance if stop_distance else 0.0
    rejection_imbalance = sum(positive) - sum(adverse)
    acceleration_shift = (
        direction_deltas[-1] - direction_deltas[0] if len(direction_deltas) >= 2 else 0.0
    )
    return MicrostructureAssessment(
        persistence_ticks=_count_persistence_ticks(direction_deltas, meaningful_tick_floor),
        impulse_ratio=impulse_ratio,
        pullback_ratio=pullback_ratio,
        rejection_imbalance=rejection_imbalance,
        acceleration_shift=acceleration_shift,
        adverse_cluster_count=_count_adverse_clusters(recent_direction_deltas),
    )


def _entry_drift_ratio(snapshot: GuardianSnapshot, stop_distance: float) -> float:
    if snapshot.current_close is None or snapshot.entry is None or stop_distance <= 0:
        return 0.0
    return abs(snapshot.current_close - snapshot.entry) / stop_distance


def _passes_entry_gate(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
    stop_distance: float,
    micro: MicrostructureAssessment,
) -> tuple[bool, str]:
    if context.ticks_since_armed < thresholds.min_persistence_ticks:
        return (
            False,
            "The setup is actionable, but live continuation still needs more persistence.",
        )
    # Sniper-only mode: persistence and impulse checks relaxed.
    # For a 4-6 hour swing trade, the structural analysis (setup +
    # confirmation) is what matters — not tick-level persistence.
    # The price will naturally fluctuate on volatile synthetics.
    # These checks are only relevant for intraday scalping.
    if micro.pullback_ratio > thresholds.max_pullback_ratio:
        return (
            False,
            "The setup is actionable, but pullback depth is still too large for confirmation.",
        )
    if _entry_drift_ratio(snapshot, stop_distance) > thresholds.max_entry_drift_ratio:
        return (
            False,
            "The setup is actionable, but price drift is too large to trust the old entry.",
        )
    if context.ticks_since_armed > thresholds.max_confirmation_window_ticks:
        return (
            False,
            "The setup is actionable, but the confirmation window has already gone stale.",
        )
    # Sniper-only mode: rejection_imbalance check REMOVED.
    # On volatile synthetic indices, the microstructure window often has
    # more adverse ticks than positive ticks even when the overall trend
    # is bullish.  For a 4-6 hour swing trade, the structural analysis
    # (setup + confirmation) is what matters — not tick-level noise.
    return True, ""


def _detect_rollover(
    micro: MicrostructureAssessment,
    thresholds: GuardianThresholds,
) -> tuple[str | None, str | None]:
    if (
        micro.adverse_cluster_count >= thresholds.max_adverse_cluster_count
        and micro.acceleration_shift < 0
        and micro.persistence_ticks < thresholds.min_persistence_ticks
    ):
        return (
            "cancelled",
            "The original trade thesis is broken and should not be used.",
        )
    if (
        micro.adverse_cluster_count >= thresholds.max_adverse_cluster_count
        and micro.pullback_ratio >= thresholds.rollover_warning_ratio
    ):
        return (
            "cancelled",
            "The original trade thesis is broken and should not be used.",
        )
    if micro.pullback_ratio >= thresholds.rollover_invalidation_ratio:
        return (
            "cancelled",
            "The original trade thesis is broken after pullback depth breached the rollover guardrail.",
        )
    if micro.pullback_ratio >= thresholds.rollover_warning_ratio:
        return (
            "failing",
            "The setup is deteriorating and the old plan is no longer fresh.",
        )
    # Only trigger 'failing' on acceleration shift when there are MULTIPLE
    # adverse clusters (not just one).  A single adverse cluster with negative
    # acceleration is normal price action on volatile synthetic indices — it
    # does NOT mean the thesis is broken.  Require at least 2 clusters to
    # signal genuine deterioration.
    if micro.acceleration_shift < 0 and micro.adverse_cluster_count >= 2:
        return (
            "failing",
            "The setup is deteriorating and the old plan is no longer fresh.",
        )
    return None, None


def _compute_trailing_stop(
    snapshot: GuardianSnapshot,
    stop_distance: float,
    favorable_ratio: float,
    atr: float,
) -> float | None:
    """Compute trailing stop / breakeven recommendation.

    When the trade moves in our favor, recommend moving the stop to
    lock in profits.  This prevents winning trades from turning into
    losers — the #1 cause of premature trade closures.

    Logic:
      - 1x ATR in favor → move stop to breakeven + 0.25 ATR
      - 2x ATR in favor → trail stop at 1x ATR behind price
      - 3x ATR in favor → trail stop at 1.5x ATR behind price
    """
    if favorable_ratio < 1.0:
        return None
    if snapshot.entry is None or snapshot.stop_loss is None:
        return None

    recommended_stop = None
    if favorable_ratio >= 3.0:
        if snapshot.direction_bias == "buy" and snapshot.current_close is not None:
            recommended_stop = snapshot.current_close - atr * 1.5
        elif snapshot.direction_bias == "sell" and snapshot.current_close is not None:
            recommended_stop = snapshot.current_close + atr * 1.5
    elif favorable_ratio >= 2.0:
        if snapshot.direction_bias == "buy" and snapshot.current_close is not None:
            recommended_stop = snapshot.current_close - atr
        elif snapshot.direction_bias == "sell" and snapshot.current_close is not None:
            recommended_stop = snapshot.current_close + atr
    elif favorable_ratio >= 1.0:
        if snapshot.direction_bias == "buy":
            recommended_stop = snapshot.entry + atr * 0.25
        else:
            recommended_stop = snapshot.entry - atr * 0.25

    # Ensure recommended stop never moves against the trade
    if recommended_stop is not None and snapshot.stop_loss is not None:
        if snapshot.direction_bias == "buy" and recommended_stop < snapshot.stop_loss:
            return None  # don't move stop backward
        elif snapshot.direction_bias == "sell" and recommended_stop > snapshot.stop_loss:
            return None  # don't move stop backward

    return recommended_stop


def evaluate_signal_guardian(
    snapshot: GuardianSnapshot,
    context: GuardianContext,
    thresholds: GuardianThresholds,
) -> GuardianEvaluation:
    if snapshot.trade_status != "valid" or snapshot.direction_bias not in {"buy", "sell"}:
        return GuardianEvaluation("forming", "No directional thesis — waiting for market data.")

    stop_distance = _stop_distance(snapshot)
    if not stop_distance or stop_distance <= 0:
        return GuardianEvaluation(
            "unavailable",
            "Live guard cannot score the setup without levels.",
        )

    adverse_ratio = context.max_adverse_excursion / stop_distance
    if context.trading_mode == "sniper":
        # Sniper mode is a 4-6 hour swing trade.  A plan is only cancelled
        # beyond reasonable doubt when:
        #   1. price has actually TRADED THROUGH the stop AND a CLOSED
        #      execution-timeframe candle confirms it (stop-lock grace).  An
        #      intraday spread/jitter wick inside the still-forming candle is
        #      NOT enough — the stop must be confirmed by a full closed
        #      candle before the plan dies; or
        #   2. the adverse excursion reached the near-stop threshold AND the
        #      price is STILL sitting at or beyond the weakening line right
        #      now (sustained, not a transient wick that already recovered).
        # A window-max wick to 95% of the stop that then recovers is normal
        # price action on volatile synthetics and must NOT cancel the plan.
        current_adverse = _current_adverse_excursion(snapshot)
        current_ratio = current_adverse / stop_distance
        sustained = current_ratio >= thresholds.weakening_excursion_ratio
        stop_confirmed_on_candle = bool(context.stop_traded_on_closed_candle)

        # ── Breakeven trail (band geometry) ──────────────────────
        # Once MFE reaches breakeven_trail_frac of the target distance the
        # effective stop is ENTRY: the plan is risk-free and only dies if
        # price trades all the way back through breakeven (confirmed by a
        # closed execution candle — same grace as the stop-lock).
        trail_armed = (
            thresholds.breakeven_trail_frac > 0.0
            and snapshot.take_profit is not None
            and snapshot.entry is not None
            and context.max_favorable_excursion
            >= thresholds.breakeven_trail_frac * abs(snapshot.take_profit - snapshot.entry)
        )
        if trail_armed and snapshot.current_close is not None and snapshot.entry is not None:
            entry_through_now = (
                snapshot.current_close <= snapshot.entry
                if snapshot.direction_bias == "buy"
                else snapshot.current_close >= snapshot.entry
            )
            entry_confirmed = bool(context.entry_traded_on_closed_candle)
            no_candle_data = context.entry_traded_on_closed_candle is None
            if entry_through_now and (entry_confirmed or no_candle_data):
                return GuardianEvaluation(
                    "cancelled",
                    "Breakeven trail hit — price traded back through the entry after "
                    "the plan moved to breakeven; the position is closed at ~0R.",
                )

        if (
            adverse_ratio >= 1.0 and stop_confirmed_on_candle
        ) or (
            adverse_ratio >= thresholds.max_adverse_excursion_ratio and sustained
        ):
            timeframe_min = max(1, int(context.execution_timeframe_sec or 0) // 60)
            return GuardianEvaluation(
                "cancelled",
                "The original trade thesis is broken after the stop traded through on a "
                f"closed {timeframe_min}m candle — the position would have been stopped out.",
            )
    else:
        if adverse_ratio >= thresholds.max_adverse_excursion_ratio:
            return GuardianEvaluation(
                "cancelled",
                "The original trade thesis is broken and should not be used.",
            )

    micro = _assess_microstructure(snapshot, context, thresholds, stop_distance)

    # ── Confirmed lock: hold confirmed status through normal noise ──
    # Once a setup has been validated as 'confirmed', the guardian holds
    # that status for at least `confirmed_lock_ticks` ticks even if
    # microstructure temporarily weakens (rollover detection, adverse
    # excursion).  This prevents validated setups from flickering to
    # 'failing' on normal price noise.
    #
    # The lock does NOT protect against 'cancelled' — genuine thesis
    # breakage (max adverse excursion) must always override the lock.
    _in_confirmed_lock = False
    _effective_lock_ticks = _effective_confirmed_lock_ticks(
        thresholds, context.current_confidence or context.confidence_at_confirmation
    )
    if (
        context.previous_guardian_state == "confirmed"
        and context.first_confirmed_at_tick is not None
    ):
        ticks_since_confirmation = context.ticks_since_armed - context.first_confirmed_at_tick
        if ticks_since_confirmation < _effective_lock_ticks:
            _in_confirmed_lock = True

    # ── Sniper mode: skip microstructure re-evaluation after confirmation ──
    # Sniper trades target 4-6 hour holds.  Re-checking microstructure
    # every 5 seconds is counterproductive — normal pullbacks on volatile
    # synthetics will ALWAYS trigger "failing" via pullback_ratio or
    # acceleration_shift checks.  After confirmation, the sniper guardian
    # should ONLY check thesis invalidation (stop hit / max adverse excursion).
    #
    # This is the root cause of "Plan is losing strength" appearing within
    # minutes of a confirmed call: the guardian was evaluating 16-tick
    # microstructure for a multi-hour swing trade.
    _is_sniper = context.trading_mode == "sniper"
    _sniper_confirmed_and_stable = (
        _is_sniper
        and context.previous_guardian_state == "confirmed"
        and context.first_confirmed_at_tick is not None
        and (context.ticks_since_armed - context.first_confirmed_at_tick)
            >= SNIPER_MICRO_REEVAL_INTERVAL_TICKS
    )

    # For sniper mode after the stabilization window, skip ALL microstructure
    # degradation checks AND the entry gate.  The only way to fail is via
    # max adverse excursion (stop hit), which is checked at the top of the
    # function.  After stabilization, return 'confirmed' directly — the
    # trade is validated and should not flicker back to 'actionable' or
    # 'failing' on normal price noise.
    if _sniper_confirmed_and_stable:
        favorable_ratio = context.max_favorable_excursion / stop_distance if stop_distance else 0.0
        atr = context.atr_14 if context.atr_14 and context.atr_14 > 0 else stop_distance * 0.3
        _trail = _compute_trailing_stop(snapshot, stop_distance, favorable_ratio, atr)
        ticks_since = context.ticks_since_armed - context.first_confirmed_at_tick
        return GuardianEvaluation(
            "confirmed",
            f"Sniper setup confirmed and stable ({ticks_since}t since confirmation) — thesis intact, only stop-hit invalidates.",
            recommended_stop=_trail,
        )

    if not _sniper_confirmed_and_stable:
        # For sniper mode, skip _detect_rollover entirely when the setup
        # is still "actionable" (not yet confirmed).  The rollover check
        # evaluates pullback_ratio against the stop distance, but on
        # volatile synthetics the price often pulls back 50-70% of the
        # stop distance WHILE the setup is forming — this is normal price
        # action, not thesis deterioration.  The entry gate (below) is
        # the proper gatekeeper for confirmation.
        _skip_rollover_for_sniper = (
            _is_sniper
            and context.previous_guardian_state != "confirmed"
        )
        if not _skip_rollover_for_sniper:
            rollover_state, rollover_reason = _detect_rollover(micro, thresholds)
            if rollover_state == "failing":
                # During confirmed lock, suppress 'failing' — the setup was
                # validated and normal pullbacks shouldn't downgrade it.
                if _in_confirmed_lock:
                    rollover_state = None
                    rollover_reason = None
                else:
                    # ── Grace period: don't degrade during the first few ticks ──
                    in_grace_period = context.ticks_since_armed <= GRACE_PERIOD_TICKS
                    orderly_early_post_entry_move = (
                        context.ticks_since_armed <= thresholds.min_persistence_ticks + 2
                        and adverse_ratio < thresholds.rollover_warning_ratio
                        and micro.pullback_ratio < thresholds.rollover_warning_ratio
                        and micro.rejection_imbalance > 0
                    )
                    if in_grace_period or orderly_early_post_entry_move:
                        rollover_state = None
                        rollover_reason = None
            if rollover_state:
                return GuardianEvaluation(
                    rollover_state,
                    rollover_reason or "Setup is weakening.",
                )

        # For sniper mode during actionable phase, skip adverse excursion
        # check — same logic as rollover skip above.  The price moving
        # against the entry is normal on volatile synthetics.
        if adverse_ratio >= thresholds.weakening_excursion_ratio and not _skip_rollover_for_sniper:
            # During confirmed lock, suppress 'failing' from adverse excursion
            # unless it's genuinely severe (approaching max).
            if _in_confirmed_lock and adverse_ratio < thresholds.max_adverse_excursion_ratio * 0.8:
                pass  # hold confirmed — excursion is within tolerable range
            elif context.ticks_since_armed <= GRACE_PERIOD_TICKS:
                # ── Grace period for new plans ────────────────────────────
                # A brand-new plan should NOT immediately fail on adverse
                # excursion.  On volatile synthetic indices, the price often
                # moves against the entry within the first few ticks while
                # the candle is still forming.  Allow 8 ticks (~40 seconds)
                # before the adverse excursion check becomes active.
                pass
            else:
                return GuardianEvaluation(
                    "failing",
                    "The setup is deteriorating and the old plan is no longer fresh.",
                )

    # ── Trailing stop / breakeven protection (all return paths) ───
    # Compute once and attach to every return — confirmed signals
    # are the ones most likely in profit, so they need trailing stops too.
    favorable_ratio = context.max_favorable_excursion / stop_distance if stop_distance else 0.0
    atr = context.atr_14 if context.atr_14 and context.atr_14 > 0 else stop_distance * 0.3
    _trail = _compute_trailing_stop(snapshot, stop_distance, favorable_ratio, atr)

    passes_entry_gate, gate_reason = _passes_entry_gate(
        snapshot,
        context,
        thresholds,
        stop_distance,
        micro,
    )
    if passes_entry_gate:
        return GuardianEvaluation(
            "confirmed",
            f"{snapshot.direction_bias.capitalize()} confirmation received after strong reclaim and controlled pullback.",
            recommended_stop=_trail,
        )

    # ── Confirmed lock fallback: hold 'confirmed' when entry gate lapses ──
    # If the entry gate no longer passes (e.g. brief pullback reduced
    # impulse) but the setup was recently confirmed, hold 'confirmed'
    # until the lock expires.
    if _in_confirmed_lock:
        ticks_since_confirmation = context.ticks_since_armed - context.first_confirmed_at_tick
        remaining = _effective_lock_ticks - ticks_since_confirmation
        return GuardianEvaluation(
            "confirmed",
            f"Confirmation locked ({_effective_lock_ticks}t) — setup validated, {remaining} ticks remaining.",
            recommended_stop=_trail,
        )

    return GuardianEvaluation(
        "actionable",
        gate_reason or "The setup is actionable with caution.",
        recommended_stop=_trail,
    )
