from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class GuardianEvaluation:
    state: str
    reason: str


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
    if micro.persistence_ticks < thresholds.min_persistence_ticks:
        return (
            False,
            "The setup is actionable, but persistence is still too weak for confirmation.",
        )
    if micro.impulse_ratio < thresholds.min_impulse_ratio:
        return (
            False,
            "The setup is actionable, but impulse quality is still too weak for confirmation.",
        )
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
    if micro.rejection_imbalance <= 0:
        return (
            False,
            "The setup is actionable, but rejection quality is still too mixed for confirmation.",
        )
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
    if adverse_ratio >= thresholds.max_adverse_excursion_ratio:
        return GuardianEvaluation(
            "cancelled",
            "The original trade thesis is broken and should not be used.",
        )

    micro = _assess_microstructure(snapshot, context, thresholds, stop_distance)
    rollover_state, rollover_reason = _detect_rollover(micro, thresholds)
    if rollover_state == "failing":
        # ── Grace period: don't degrade during the first few ticks ──
        # After a signal is generated, the market needs time to develop.
        # Treating every adverse tick as 'deterioration' within the first
        # 8 ticks is far too reactive — especially on volatile synthetic
        # indices where normal price action includes rapid back-and-forth.
        in_grace_period = context.ticks_since_armed <= 8

        # Structure-led plans can print an orderly early pullback without losing the thesis.
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

    if adverse_ratio >= thresholds.weakening_excursion_ratio:
        return GuardianEvaluation(
            "failing",
            "The setup is deteriorating and the old plan is no longer fresh.",
        )

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
        )

    return GuardianEvaluation(
        "actionable",
        gate_reason or "The setup is actionable with caution.",
    )
