from __future__ import annotations

import asyncio
import csv
import sys
import time
from collections.abc import Callable
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from synthetic_trader.config import ModelConfig, RiskConfig, SymbolProfile, TraderConfig
from synthetic_trader.data.collector import deriv_credentials_from_env
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import Tick, FeatureSnapshot
from synthetic_trader.execution.deriv_ws import DerivWebSocketClient
from synthetic_trader.execution.venues import MarketDataClient
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.live.live_symbol_watcher import PreparedSymbolState
from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine
from synthetic_trader.models.advanced import ConfidenceScorer
from synthetic_trader.data.tick_store import append_ticks_csv
from synthetic_trader.execution.mt5_data import Mt5TickClient, is_mt5_configured
from synthetic_trader.config import TraderConfig as _TraderConfig
from synthetic_trader.live.missed_trade_tracker import MissedTradeTracker


@dataclass(frozen=True)
class WatchState:
    call: str
    alert_type: str
    trade_status: str
    direction_bias: str
    regime: str
    confidence_bucket: str
    wait_for: str


DEFAULT_CONTEXT_ALERT_COOLDOWN = 2
DEFAULT_TICK_HISTORY_PAGE_SIZE = 5_000
MAX_BUFFER_TICKS = 10_000

# --- Trading mode presets ---------------------------------------------------
# Sniper mode is the original conservative configuration. Active Trader mode
# loosens the gates so the brain can surface more frequent, well-calculated
# opportunities instead of waiting for a near-perfect "clean" setup.
SNIPER_GUARDIAN_THRESHOLDS = GuardianThresholds(
    max_arming_ticks=30,
    max_confirmation_window_ticks=40,
    # Sniper mode is forward-looking — tolerate normal pullbacks.
    # 0.50 means price must move 50% against the stop before degrading.
    # On volatile synthetic indices, 0.25 was causing 'losing strength' within
    # seconds of entry — far too reactive for a sniper/swing signal.
    weakening_excursion_ratio=0.50,
    max_adverse_excursion_ratio=0.95,
    max_entry_drift_ratio=0.90,
    microstructure_window_ticks=16,
    min_persistence_ticks=1,
    min_impulse_ratio=0.02,
    max_pullback_ratio=0.85,
    rollover_warning_ratio=0.80,
    rollover_invalidation_ratio=0.95,
    adverse_cluster_window_ticks=12,
    max_adverse_cluster_count=8,
)

ACTIVE_TRADER_GUARDIAN_THRESHOLDS = GuardianThresholds(
    max_arming_ticks=16,
    max_confirmation_window_ticks=10,
    weakening_excursion_ratio=0.45,
    max_adverse_excursion_ratio=0.95,
    max_entry_drift_ratio=1.0,
    microstructure_window_ticks=8,
    min_persistence_ticks=3,
    min_impulse_ratio=0.08,
    max_pullback_ratio=0.32,
    rollover_warning_ratio=0.28,
    rollover_invalidation_ratio=0.45,
    adverse_cluster_window_ticks=6,
    max_adverse_cluster_count=3,
)

# Volatility Harvesting mode: fast reversion trades exploiting variance clustering.
# Tighter arming window since these are quick mean-reversion entries.
VOLATILITY_HARVEST_GUARDIAN_THRESHOLDS = GuardianThresholds(
    max_arming_ticks=8,
    max_confirmation_window_ticks=6,
    weakening_excursion_ratio=0.50,
    max_adverse_excursion_ratio=0.90,
    max_entry_drift_ratio=1.0,
    microstructure_window_ticks=6,
    min_persistence_ticks=2,
    min_impulse_ratio=0.10,
    max_pullback_ratio=0.25,
    rollover_warning_ratio=0.20,
    rollover_invalidation_ratio=0.35,
    adverse_cluster_window_ticks=4,
    max_adverse_cluster_count=2,
)

GUARDIAN_PRESETS = {
    "sniper": SNIPER_GUARDIAN_THRESHOLDS,
    "active_trader": ACTIVE_TRADER_GUARDIAN_THRESHOLDS,
    "volatility_harvest": VOLATILITY_HARVEST_GUARDIAN_THRESHOLDS,
}

DEFAULT_GUARDIAN_THRESHOLDS = SNIPER_GUARDIAN_THRESHOLDS

# ── Missed trade tracker ──────────────────────────────────────
# Records every NO_TRADE decision and resolves it after 1 hour.
# The resolved outcomes feed back into CalibrationState so the
# model improves its probability calibration over time.
_missed_trade_tracker = MissedTradeTracker()

# Module-level ConfidenceScorer for missed-trade learning.
# Updated when missed trades are resolved; feeds range-regime boost
# into future confidence scores so the engine becomes more willing
# to trade range-bound markets when it keeps missing opportunities.
_confidence_scorer = ConfidenceScorer(
    model=None,  # model not needed for range-boost learning
)


# Timestamp of the last missed-trade resolution attempt (module-level).
_last_missed_resolution_at: float = 0.0
_MISSED_RESOLUTION_INTERVAL_SEC = 60  # resolve once per minute


def _get_atr_14(features: dict[str, float]) -> float:
    """Extract ATR_14 from features, falling back to 1.0."""
    return features.get("atr_14", 1.0)


def _maybe_record_missed_trade(
    *,
    symbol: str,
    model_long_probability: float | None,
    confidence: float | None,
    regime: str,
    current_close: float | None,
    features: dict[str, float],
    bias_buy_threshold: float = 0.55,
    bias_sell_threshold: float = 0.45,
) -> None:
    """Record a NO_TRADE decision for missed-trade calibration.

    Called from analyze_live_snapshot when report.signal is None.
    The tracker will resolve these records after 1 hour by checking
    what the market actually did, and feed the results back into
    CalibrationState.
    """
    if current_close is None or current_close <= 0:
        return
    if model_long_probability is None:
        return
    atr_14 = _get_atr_14(features)
    direction_bias = _direction_bias_from_probability(
        model_long_probability,
        buy_threshold=bias_buy_threshold,
        sell_threshold=bias_sell_threshold,
    )
    _missed_trade_tracker.record(
        symbol=symbol,
        model_long_probability=model_long_probability,
        confidence=confidence,
        regime=regime,
        atr_14=atr_14,
        current_price=current_close,
        direction_bias=direction_bias,
        features_summary={
            k: features[k]
            for k in (
                "rsi_14", "slope_20_atr", "hurst_exponent",
                "displacement_atr", "atr_ratio",
            )
            if k in features
        },
    )


def _maybe_resolve_missed_trades(decision_engine: DecisionEngine) -> None:
    """Resolve pending missed trade records and feed into calibration.

    Runs at most once per _MISSED_RESOLUTION_INTERVAL_SEC to avoid
    hammering the CSV on every snapshot.
    """
    global _last_missed_resolution_at
    now = time.time()
    if (now - _last_missed_resolution_at) < _MISSED_RESOLUTION_INTERVAL_SEC:
        return
    if _missed_trade_tracker.pending_count == 0:
        return
    _last_missed_resolution_at = now

    def _price_lookup(symbol: str) -> list[tuple[float, float]]:
        ticks = _load_csv_ticks(symbol)
        if not ticks:
            return []
        return [(t.epoch, t.price) for t in ticks]

    def _update_calibration(prediction: float, outcome: int) -> None:
        decision_engine.update_calibration(prediction, outcome)

    result = _missed_trade_tracker.resolve(
        price_lookup=_price_lookup,
        update_calibration=_update_calibration,
    )
    if result.resolved_count > 0:
        # Feed missed trade stats into the ConfidenceScorer so it learns
        # to boost range-regime scores when the engine keeps missing.
        _confidence_scorer.update_missed_trade_stats(
            missed_opportunities=result.missed_opportunities,
            correct_stayouts=result.correct_stayouts,
        )
        boost = _confidence_scorer.missed_trade_boost
        logging.info(
            "[missed_trade] resolved %d records: %d missed opportunities, "
            "%d correct stay-outs, %d failed | range_boost=%.3f",
            result.resolved_count,
            result.missed_opportunities,
            result.correct_stayouts,
            result.failed_resolutions,
            boost,
        )


@dataclass(frozen=True)
class TradingModePreset:
    confidence_above: float
    confidence_near: float
    bias_buy_threshold: float
    bias_sell_threshold: float
    risk_min_confidence: float
    risk_min_reward_risk: float
    risk_max_volatility_z: float
    model_decision_threshold: float
    confidence_relaxation: float
    symbol_min_history_candles: int
    symbol_min_primary_reward_risk: float
    execution_mode: str = "intraday"
    swing_execution_timeframe_sec: int = 900
    swing_hold_horizon_minutes: int = 360
    swing_take_profit_rr: float = 3.0
    # Override per-symbol max_stop_distance_pct when set.  None keeps
    # the symbol-level default; a float forces a mode-specific cap.
    max_stop_distance_pct: float | None = None


TRADING_MODE_PRESETS = {
    "sniper": TradingModePreset(
        confidence_above=0.50,
        confidence_near=0.42,
        bias_buy_threshold=0.52,
        bias_sell_threshold=0.48,
        risk_min_confidence=0.42,
        risk_min_reward_risk=2.0,
        risk_max_volatility_z=3.0,
        model_decision_threshold=0.50,
        confidence_relaxation=0.10,
        symbol_min_history_candles=30,
        symbol_min_primary_reward_risk=2.0,
        execution_mode="swing",
        swing_execution_timeframe_sec=900,
        swing_hold_horizon_minutes=360,
        swing_take_profit_rr=3.5,
        max_stop_distance_pct=0.06,  # wider cap for swing trades
    ),
    "active_trader": TradingModePreset(
        confidence_above=0.34,
        confidence_near=0.28,
        bias_buy_threshold=0.50,
        bias_sell_threshold=0.50,
        risk_min_confidence=0.24,
        risk_min_reward_risk=0.85,
        risk_max_volatility_z=4.5,
        model_decision_threshold=0.43,
        confidence_relaxation=0.08,
        symbol_min_history_candles=15,
        symbol_min_primary_reward_risk=0.85,
        execution_mode="intraday",
        max_stop_distance_pct=0.03,  # tighter cap for faster exits
    ),
    # Volatility Harvesting: trades ONLY on GARCH mean-reversion signals.
    # Bypasses session filter, structure bias, and multi-TF alignment.
    # Relies solely on variance clustering — the ONE exploitable property.
    "volatility_harvest": TradingModePreset(
        confidence_above=0.30,
        confidence_near=0.24,
        bias_buy_threshold=0.50,
        bias_sell_threshold=0.50,
        risk_min_confidence=0.20,
        risk_min_reward_risk=1.0,
        risk_max_volatility_z=5.0,
        model_decision_threshold=0.40,
        confidence_relaxation=0.12,
        symbol_min_history_candles=10,
        symbol_min_primary_reward_risk=1.0,
        execution_mode="intraday",
        max_stop_distance_pct=0.04,
    ),
}


def build_mode_config(base: TraderConfig, preset: TradingModePreset) -> TraderConfig:
    symbols = {
        symbol: SymbolProfile(
            **{
                field: getattr(profile, field)
                for field in profile.__dataclass_fields__
                if field
                not in {
                    "symbol",
                    "min_history_candles",
                    "min_primary_reward_risk",
                    "confidence_relaxation",
                    "execution_timeframe_sec",
                    "hold_bars_setup",
                    "intraday_hold_horizon_minutes",
                    "take_profit_rr",
                    "max_stop_distance_pct",
                }
            },
            symbol=profile.symbol,
            min_history_candles=preset.symbol_min_history_candles,
            min_primary_reward_risk=preset.symbol_min_primary_reward_risk,
            confidence_relaxation=preset.confidence_relaxation,
            execution_timeframe_sec=preset.swing_execution_timeframe_sec,
            hold_bars_setup=profile.hold_bars_bias,
            intraday_hold_horizon_minutes=preset.swing_hold_horizon_minutes,
            take_profit_rr=preset.swing_take_profit_rr,
            max_stop_distance_pct=(
                preset.max_stop_distance_pct
                if preset.max_stop_distance_pct is not None
                else profile.max_stop_distance_pct
            ),
        )
        for symbol, profile in base.symbols.items()
    }
    return TraderConfig(
        symbols=symbols,
        risk=RiskConfig(
            starting_equity=base.risk.starting_equity,
            risk_per_trade=base.risk.risk_per_trade,
            max_daily_loss_fraction=base.risk.max_daily_loss_fraction,
            max_consecutive_losses=base.risk.max_consecutive_losses,
            max_open_positions=base.risk.max_open_positions,
            min_confidence=preset.risk_min_confidence,
            min_reward_risk=preset.risk_min_reward_risk,
            max_volatility_z=preset.risk_max_volatility_z,
            stake_floor=base.risk.stake_floor,
        ),
        model=ModelConfig(
            learning_rate=base.model.learning_rate,
            l2=base.model.l2,
            decision_threshold=preset.model_decision_threshold,
            feature_clip=base.model.feature_clip,
            version=base.model.version,
        ),
        paper=base.paper,
        mt5=base.mt5,
        features=base.features,
    )


def resolve_trading_mode(
    trading_mode: str,
) -> tuple[TraderConfig, GuardianThresholds, TradingModePreset]:
    mode = trading_mode if trading_mode in TRADING_MODE_PRESETS else "sniper"
    preset = TRADING_MODE_PRESETS[mode]
    return build_mode_config(TraderConfig.default(), preset), GUARDIAN_PRESETS[mode], preset


def _required_snapshot_history_ticks(
    *,
    symbol: str,
    warmup_count: int,
    config: TraderConfig,
) -> int:
    """
    Calculate minimum ticks to fetch from the live API.

    The warmup_count from the caller is authoritative — background CSV
    accumulation provides the long-range historical data for analysis.
    Cap at 10_000 to prevent excessive sequential API paging (5000 per page).
    """
    return min(warmup_count, 10_000)


def _merge_ticks_by_epoch(existing: list[Tick], page: list[Tick]) -> list[Tick]:
    if not page:
        return list(existing)
    by_epoch = {tick.epoch: tick for tick in existing}
    for tick in page:
        by_epoch[tick.epoch] = tick
    return sorted(by_epoch.values(), key=lambda item: item.epoch)


async def collect_live_snapshot_ticks(
    *,
    symbol: str,
    warmup_count: int,
    max_live_ticks: int,
    app_id: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> list[Tick]:
    credentials = deriv_credentials_from_env(app_id=app_id)

    # ── Data source selection ────────────────────────────────────────
    # Priority:
    # 1. MT5 — when credentials are configured (terminal likely running).
    #    Fast, local connection for live ticks.
    # 2. Deriv WebSocket — when app_id is provided or as fallback.
    #    No local terminal needed; connects to Deriv's servers directly.
    #
    # Both paths are tried when configured — if MT5 fails cleanly (via the
    # `timeout=8000` parameter), the system falls back to Deriv WebSocket.
    collected: list[Tick] = []
    config = TraderConfig.default()
    required_history_ticks = _required_snapshot_history_ticks(
        symbol=symbol,
        warmup_count=warmup_count,
        config=config,
    )

    if is_mt5_configured() and client_factory is None:
        try:
            async with Mt5TickClient() as client:
                collected = await _collect_from_client(
                    client, symbol, required_history_ticks, max_live_ticks
                )
            return sorted(collected, key=lambda item: item.epoch)
        except Exception as e:
            print(f"[market_snapshot] MT5 failed ({e}), falling back to Deriv WebSocket", file=sys.stderr, flush=True)
            collected = []

    # Deriv WebSocket (direct or fallback)
    factory = client_factory or (lambda: DerivWebSocketClient(credentials))
    async with factory() as client:
        collected = await _collect_from_client(
            client, symbol, required_history_ticks, max_live_ticks
        )
    return sorted(collected, key=lambda item: item.epoch)


def _extract_reason_value(reasons: list[str], pattern: str) -> float | None:
    matcher = re.compile(pattern)
    for reason in reasons:
        match = matcher.search(reason)
        if match:
            return float(match.group(1))
    return None


def _direction_bias_from_probability(
    model_long_probability: float | None,
    *,
    buy_threshold: float = 0.55,
    sell_threshold: float = 0.45,
) -> str:
    if model_long_probability is None:
        return "none"
    if model_long_probability >= buy_threshold:
        return "buy"
    if model_long_probability <= sell_threshold:
        return "sell"
    return "none"


def _summarize_structure(structure: dict[str, float] | object) -> str:
    if not isinstance(structure, dict):
        return "structure still forming"
    if structure.get("bos_up", 0.0):
        return "break of structure up"
    if structure.get("bos_down", 0.0):
        return "break of structure down"
    if structure.get("liquidity_sweep_down", 0.0):
        return "downside sweep reclaimed"
    if structure.get("liquidity_sweep_up", 0.0):
        return "upside sweep rejected"
    bias = structure.get("structure_bias", 0.0)
    if bias > 0:
        return "bullish structure bias"
    if bias < 0:
        return "bearish structure bias"
    return "structure is mixed"


def _wait_for_next(trade_status: str, direction_bias: str, reasons: list[str]) -> str:
    if trade_status == "valid":
        if direction_bias == "buy":
            return "wait for a clean bullish continuation close"
        if direction_bias == "sell":
            return "wait for a clean bearish continuation close"
        return "wait for the next aligned candle close"

    for reason in reasons:
        if "need " in reason and "candles" in reason:
            return "wait for more candle history before trusting the setup"
        if "confidence" in reason:
            return "wait for confidence above threshold and cleaner directional agreement"
        if "reward/risk" in reason:
            return "wait for a cleaner entry so reward outweighs the risk"
        if "volatility" in reason:
            return "wait for volatility to normalize before considering a trade"
    return "wait for clearer structure and stronger confirmation"


def _format_trade_areas(entry: float, stop_loss: float, take_profit: float) -> dict[str, str]:
    return {
        "entry_area": f"around {entry}",
        "stop_area": f"below {stop_loss}" if stop_loss < entry else f"above {stop_loss}",
        "target_area": f"toward {take_profit}",
    }


def _build_invalidation_text(direction_bias: str, stop_loss: float) -> str:
    if direction_bias == "buy":
        return f"price closes back below {stop_loss}"
    if direction_bias == "sell":
        return f"price closes back above {stop_loss}"
    return f"price invalidates around {stop_loss}"


def _format_hold_horizon(hold_horizon_minutes: int | None) -> str:
    if hold_horizon_minutes == 60:
        return "next hour"
    if hold_horizon_minutes is not None and hold_horizon_minutes > 0:
        return f"next {hold_horizon_minutes} minutes"
    return "planned intraday window"


def _build_execution_invalidation_text(
    direction_bias: str,
    execution_stop: float | None,
    trigger_type: str | None = None,
) -> str | None:
    if execution_stop is None:
        return None
    direction_word = "below" if direction_bias == "buy" else "above" if direction_bias == "sell" else "around"
    if trigger_type == "reclaim_pullback":
        return (
            f"5m close back {direction_word} the reclaimed shelf at {execution_stop} "
            "invalidates the reclaim setup"
        )
    if trigger_type == "break_retest_hold":
        return (
            f"5m close back {direction_word} the retest failure point at {execution_stop} "
            "invalidates the retest hold"
        )
    if trigger_type == "continuation_close":
        return (
            f"5m close back {direction_word} the continuation failure level at {execution_stop} "
            "invalidates the continuation setup"
        )
    if trigger_type in {"liquidity_sweep_reversal", "structure_continuation"}:
        if direction_bias == "buy":
            return f"15m close back below {execution_stop} invalidates the swing thesis"
        else:
            return f"15m close back above {execution_stop} invalidates the swing thesis"
    if direction_bias == "buy":
        return f"5m close back below {execution_stop} invalidates the execution attempt"
    if direction_bias == "sell":
        return f"5m close back above {execution_stop} invalidates the execution attempt"
    return f"5m close invalidates the execution attempt around {execution_stop}"


def _build_intraday_wait_for(
    *,
    trade_status: str,
    direction_bias: str,
    hold_horizon_minutes: int | None,
    reasons: list[str],
    trigger_type: str | None = None,
) -> str:
    if trade_status == "valid":
        horizon = _format_hold_horizon(hold_horizon_minutes)
        if trigger_type == "reclaim_pullback":
            return f"wait for the 5m reclaim to confirm, then manage toward the {horizon} objective"
        if trigger_type == "break_retest_hold":
            return f"wait for the 5m retest hold to confirm, then manage toward the {horizon} objective"
        if trigger_type == "liquidity_sweep_reversal":
            return f"wait for price retrace toward the entry area ({horizon} swing), then manage to target"
        if trigger_type == "structure_continuation":
            return f"hold for {horizon}; structural continuation is aligned with the thesis"
        return f"wait for the 5m continuation trigger to confirm, then manage toward the {horizon} objective"
    return _wait_for_next(trade_status, direction_bias, reasons)


def _excursion_window(
    *,
    direction_bias: str,
    entry: float | None,
    prices: list[float],
) -> tuple[float, float]:
    if entry is None or not prices:
        return 0.0, 0.0

    if direction_bias == "buy":
        favorable = max(0.0, max(price - entry for price in prices))
        adverse = max(0.0, max(entry - price for price in prices))
        return favorable, adverse

    if direction_bias == "sell":
        favorable = max(0.0, max(entry - price for price in prices))
        adverse = max(0.0, max(price - entry for price in prices))
        return favorable, adverse

    return 0.0, 0.0


def _guardian_prices_since_entry(
    *,
    direction_bias: str,
    entry: float | None,
    ticks: list[Tick],
    max_arming_ticks: int,
) -> list[float]:
    recent_prices = [tick.price for tick in ticks[-max_arming_ticks:]]
    if not recent_prices or entry is None:
        return recent_prices

    def _is_armed(price: float) -> bool:
        if direction_bias == "buy":
            return price >= entry
        if direction_bias == "sell":
            return price <= entry
        return False

    rearm_index: int | None = None
    previous_is_armed = False
    for index, price in enumerate(recent_prices):
        current_is_armed = _is_armed(price)
        if current_is_armed and not previous_is_armed:
            rearm_index = index
        previous_is_armed = current_is_armed

    if rearm_index is not None:
        return recent_prices[rearm_index:]

    return recent_prices[-1:]


# ── Guardian-based position sizing ──────────────────────────────
# The guardian monitors LIVE signal quality after a trade is generated.
# When the setup deteriorates, the guardian adjusts position_scale to
# automatically de-risk before the signal reaches the execution layer.
#
# Position scale mapping:
#   confirmed  → 1.0  (full size — setup is validated)
#   actionable → 0.5  (reduced size — waiting for confirmation)
#   forming    → 0.0  (no size — no data to evaluate)
#   failing    → 0.0  (no size — setup is deteriorating)
#   cancelled  → 0.0  (no size — thesis is broken)
#
# The guardian position_scale is applied AFTER the regime shift detector's
# position_scale, so the final scale is min(regime_scale, guardian_scale).
# This ensures that BOTH regime anomalies AND setup deterioration reduce
# position sizing — the most conservative signal wins.

GUARDIAN_POSITION_SCALES: dict[str, float] = {
    "confirmed": 1.0,
    "actionable": 0.5,
    "forming": 0.0,
    "failing": 0.0,
    "cancelled": 0.0,
}

# ── Confirmed lock tracking ────────────────────────────────────
# Per-symbol tracking of when the guardian first reached 'confirmed'.
# When the guardian state is 'confirmed', we record the tick count
# (ticks_since_armed) so we can hold that status for
# `confirmed_lock_ticks` ticks even if the entry gate no longer passes.
_guardian_confirmed_at_tick: dict[str, int] = {}


def _guardian_position_scale(guardian_state: str) -> float:
    """Map guardian state to a position scale multiplier (0.0–1.0).

    Returns the position scale for the given guardian state. Unknown
    states default to 0.0 (no position) for safety.
    """
    return GUARDIAN_POSITION_SCALES.get(guardian_state, 0.0)


def build_guardian_snapshot(
    snapshot: dict[str, object],
    ticks: list[Tick],
    guardian_thresholds: GuardianThresholds | None = None,
    trading_mode: str = "active_trader",
) -> dict[str, object]:
    current_close = ticks[-1].price if ticks else snapshot.get("current_close")
    enriched = dict(snapshot)
    enriched["current_close"] = current_close

    # ── Sniper mode: use full microstructure evaluation ──────────
    # Sniper mode previously used simple heuristics (checking entry/stop_loss
    # presence and signal_strength).  Now it uses the same microstructure
    # evaluation as active_trader and volatility_harvest modes, so sniper
    # users get detailed signal quality feedback (persistence, impulse,
    # pullback depth, adverse excursion) instead of just "actionable".
    #
    # The SNIPER_GUARDIAN_THRESHOLDS are tuned for conservative swing
    # entries: longer arming window (30 ticks), wider adverse excursion
    # tolerance (0.95), and relaxed pullback limits (0.85).

    thresholds = guardian_thresholds or DEFAULT_GUARDIAN_THRESHOLDS
    signal_snapshot = GuardianSnapshot(
        symbol=str(snapshot.get("symbol", "")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        entry=float(snapshot["entry"]) if snapshot.get("entry") is not None else None,
        stop_loss=float(snapshot["stop_loss"]) if snapshot.get("stop_loss") is not None else None,
        take_profit=float(snapshot["take_profit"]) if snapshot.get("take_profit") is not None else None,
        current_close=float(current_close) if current_close is not None else None,
    )
    prices = _guardian_prices_since_entry(
        direction_bias=signal_snapshot.direction_bias,
        entry=signal_snapshot.entry,
        ticks=ticks,
        max_arming_ticks=thresholds.max_arming_ticks,
    )
    max_favorable_excursion, max_adverse_excursion = _excursion_window(
        direction_bias=signal_snapshot.direction_bias,
        entry=signal_snapshot.entry,
        prices=prices,
    )
    # ── Confirmed lock: track previous state and first confirmation tick ──
    symbol_key = str(snapshot.get("symbol", ""))
    previous_guardian_state = str(snapshot.get("guardian_state", "")) or None
    first_confirmed_at_tick = _guardian_confirmed_at_tick.get(symbol_key)

    # Reset the confirmed tick tracker when the symbol or trade changes
    if previous_guardian_state is None or previous_guardian_state == "forming":
        _guardian_confirmed_at_tick.pop(symbol_key, None)
        first_confirmed_at_tick = None

    guardian = evaluate_signal_guardian(
        signal_snapshot,
        GuardianContext(
            tick_prices=prices,
            ticks_since_armed=len(prices),
            max_favorable_excursion=max_favorable_excursion,
            max_adverse_excursion=max_adverse_excursion,
            previous_guardian_state=previous_guardian_state,
            first_confirmed_at_tick=first_confirmed_at_tick,
        ),
        thresholds,
    )
    enriched["guardian_state"] = guardian.state
    enriched["guardian_reason"] = guardian.reason

    # Record the tick when the guardian first reaches 'confirmed'
    if guardian.state == "confirmed" and symbol_key not in _guardian_confirmed_at_tick:
        _guardian_confirmed_at_tick[symbol_key] = len(prices)

    # Clear the tracker when the guardian leaves confirmed/actionable
    if guardian.state in ("failing", "cancelled", "forming", "unavailable"):
        _guardian_confirmed_at_tick.pop(symbol_key, None)

    # ── Guardian-based position sizing ───────────────────────────
    # Adjust position_scale based on guardian state. The guardian monitors
    # LIVE signal quality — when the setup deteriorates (failing/cancelled),
    # it reduces position sizing to protect capital.
    #
    # The final position_scale is min(regime_scale, guardian_scale), so
    # BOTH regime anomalies AND setup deterioration reduce sizing.
    regime_scale = float(snapshot.get("position_scale", 1.0))
    guardian_scale = _guardian_position_scale(guardian.state)
    final_scale = min(regime_scale, guardian_scale)
    enriched["position_scale"] = final_scale
    enriched["guardian_position_scale"] = guardian_scale

    # Update position_sizing label to reflect the guardian's adjustment.
    if final_scale <= 0.0:
        enriched["position_sizing"] = "none"
    elif final_scale < 0.5:
        enriched["position_sizing"] = "minimal"
    elif final_scale < 0.8:
        enriched["position_sizing"] = "reduced"
    else:
        enriched["position_sizing"] = "full"

    return enriched


def build_decision_summary(alert: dict[str, object]) -> str | None:
    existing_summary = alert.get("decision_summary")
    if isinstance(existing_summary, str) and existing_summary.strip():
        existing_summary = existing_summary.strip()
        return existing_summary

    call = str(alert.get("call", ""))
    trade_status = str(alert.get("trade_status", ""))
    why = str(alert.get("why", "")).strip() or str(alert.get("briefing", "")).strip()
    wait_for = str(alert.get("wait_for", "")).strip()

    if trade_status != "valid" or call not in {"buy_candidate", "sell_candidate"}:
        return None

    direction = "buy" if call == "buy_candidate" else "sell"
    return f"{direction} setup valid; {why}; {wait_for}"


def classify_alert_type(alert: dict[str, object]) -> str:
    call = str(alert.get("call", ""))
    trade_status = str(alert.get("trade_status", ""))
    if trade_status == "valid" and call in {"buy_candidate", "sell_candidate"}:
        return "setup_candidate"
    return "context_update"


def build_watch_alert(snapshot: dict[str, object]) -> dict[str, object]:
    """Convert a raw snapshot dict into a JSON-serializable alert dict.

    This is the bridge between the Python engine and the Next.js frontend.
    It enriches the snapshot with alert_type and decision_summary fields
    that the frontend's ``mapLiveSnapshot`` function expects.

    Called by the engine bridge's ``executePythonSnapshot`` after
    ``run_live_snapshot`` returns.
    """
    alert = dict(snapshot)
    # Ensure 'why' is populated from 'briefing' for CLI renderers
    if not alert.get("why") and alert.get("briefing"):
        alert["why"] = alert["briefing"]
    # Ensure alert_type is always present
    if not alert.get("alert_type"):
        alert["alert_type"] = classify_alert_type(alert)
    # Build decision summary if missing
    if not alert.get("decision_summary"):
        summary = build_decision_summary(alert)
        if summary:
            alert["decision_summary"] = summary
    return alert


def build_watch_state(
    snapshot: dict[str, object],
    *,
    confidence_above: float = 0.58,
    confidence_near: float = 0.50,
) -> WatchState:
    confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    if confidence >= confidence_above:
        bucket = "above_threshold"
    elif confidence >= confidence_near:
        bucket = "near_threshold"
    else:
        bucket = "low_confidence"
    alert_type = str(snapshot.get("alert_type", "") or "")
    if not alert_type:
        alert_type = classify_alert_type(snapshot)
    return WatchState(
        call=str(snapshot.get("call", "stand_aside")),
        alert_type=alert_type,
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        regime=str(snapshot.get("regime", "unknown")),
        confidence_bucket=bucket,
        wait_for=str(snapshot.get("wait_for", "")),
    )


def has_material_context_change(previous: WatchState, current: WatchState) -> bool:
    return (
        previous.regime != current.regime
        or previous.direction_bias != current.direction_bias
        or previous.trade_status != current.trade_status
        or previous.wait_for != current.wait_for
    )


def should_emit_watch_alert(
    previous: WatchState | None,
    current: WatchState,
    *,
    context_cooldown_remaining: int = 0,
) -> bool:
    if previous is None:
        return False
    if previous == current:
        return False
    if current.alert_type == "setup_candidate":
        return True
    if not has_material_context_change(previous, current):
        return False
    return context_cooldown_remaining <= 0


async def _collect_from_client(
    client: MarketDataClient,
    symbol: str,
    required_history_ticks: int,
    max_live_ticks: int,
) -> list[Tick]:
    """Extracted tick collection logic shared by MT5 and Deriv WebSocket paths."""
    collected: list[Tick] = []
    if required_history_ticks > 0:
        history_end: str | int = "latest"
        oldest_history_epoch: float | None = None
        while len(collected) < required_history_ticks:
            page = await client.ticks_history(
                symbol=symbol,
                count=min(DEFAULT_TICK_HISTORY_PAGE_SIZE, required_history_ticks - len(collected)),
                end=history_end,
            )
            if not page:
                break
            merged = _merge_ticks_by_epoch(collected, page)
            if len(merged) == len(collected):
                break
            collected = merged
            oldest_in_page = min(tick.epoch for tick in page)
            if oldest_history_epoch is not None and oldest_in_page >= oldest_history_epoch:
                break
            oldest_history_epoch = oldest_in_page
            history_end = int(oldest_in_page) - 1
    if max_live_ticks > 0:
        seen_live_ticks = 0
        try:
            async for tick in client.subscribe_ticks(symbol, timeout=5.0):
                collected.append(tick)
                seen_live_ticks += 1
                if seen_live_ticks >= max_live_ticks:
                    break
        except Exception as e:
            print(f"[market_snapshot] subscribe_ticks error: {e}", file=sys.stderr, flush=True)
    return collected


async def watch_live_ticks(
    *,
    symbol: str,
    app_id: str | None = None,
    max_live_ticks: int | None = None,
    max_minutes: int | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> list[Tick]:
    credentials = deriv_credentials_from_env(app_id=app_id)

    # Same priority as collect_live_snapshot_ticks:
    # Try MT5 first when configured, fall back to Deriv WebSocket.
    if is_mt5_configured() and client_factory is None:
        try:
            async with Mt5TickClient() as client:
                collected = await _watch_collect_from_client(
                    client, symbol, max_live_ticks, max_minutes
                )
            return collected
        except Exception as e:
            print(f"[market_snapshot] watch MT5 failed ({e}), falling back to Deriv WebSocket", file=sys.stderr, flush=True)

    factory = client_factory or (lambda: DerivWebSocketClient(credentials))
    async with factory() as client:
        return await _watch_collect_from_client(
            client, symbol, max_live_ticks, max_minutes
        )


async def _watch_collect_from_client(
    client: MarketDataClient,
    symbol: str,
    max_live_ticks: int | None,
    max_minutes: int | None,
) -> list[Tick]:
    """Extracted watch collection logic shared by MT5 and Deriv WebSocket paths."""
    collected: list[Tick] = []
    deadline = None
    if max_minutes is not None:
        deadline = asyncio.get_running_loop().time() + max(0, max_minutes) * 60

    tick_iterator = client.subscribe_ticks(symbol).__aiter__()
    while True:
        try:
            if deadline is None:
                tick = await tick_iterator.__anext__()
            else:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                tick = await asyncio.wait_for(tick_iterator.__anext__(), timeout=remaining)
        except (StopAsyncIteration, TimeoutError):
            break

        collected.append(tick)
        if max_live_ticks is not None and len(collected) >= max_live_ticks:
            break
    return collected


# ── CSV tick cache ─────────────────────────────────────────────
# Avoids re-reading the CSV file from disk on every call.
# Keyed by symbol; invalidated when the file's mtime changes.
_csv_tick_cache: dict[str, tuple[Path, float, list[Tick]]] = {}

# Maximum age of CSV ticks considered valid for analysis.
# Ticks older than this threshold are filtered out in _load_csv_ticks().
# 6 hours = 21,600 seconds — more than enough for intraday analysis.
MAX_TICK_AGE_SECONDS = 86_400  # 24 hours — gives 4H bias timeframe enough candle history
# When the most recent tick is older than this, surface a "stale data" warning
# in the snapshot result. 5 minutes = 300 seconds.
STALE_TICK_WARNING_SECONDS = 300

# ── Regime-aware freshness thresholds ───────────────────────────
# Different market regimes require different data freshness.
# Volatile regimes need very recent ticks (2h), while calm range
# markets can tolerate older data (12h). These are used to compute
# the dynamic max_age_seconds in _load_csv_ticks() and to surface
# a regime-aware stale-data message in the guardian reason.
REGIME_MAX_AGE_SECONDS: dict[str, int] = {
    "volatile": 14_400,       # 4 hours — fast-moving, old data is misleading
    "trend_up": 43_200,       # 12 hours — trending, moderate freshness
    "trend_down": 43_200,     # 12 hours — trending, moderate freshness
    "range": 86_400,          # 24 hours — range-bound, older data still valid
    "compression": 28_800,    # 8 hours — compressing, could break either way
    "unknown": 43_200,        # 12 hours — default conservative
}

DEFAULT_REGIME_MAX_AGE = 43_200  # 12 hours — fallback when regime is unknown/missing


def _resolve_regime_max_age(regime: str | None) -> int:
    """Return the maximum tick age (seconds) for a given volatility regime.

    Volatile regimes need fresh data (2h), range markets can use older
    ticks (12h). Falls back to DEFAULT_REGIME_MAX_AGE (6h) when the
    regime is unknown or not in the map.
    """
    if regime is None:
        return DEFAULT_REGIME_MAX_AGE
    return REGIME_MAX_AGE_SECONDS.get(regime, DEFAULT_REGIME_MAX_AGE)


# ── Price sanity check ─────────────────────────────────────────
# Expected price ranges for each symbol on Blueberry Markets MT5.
# When tick prices fall outside these ranges, a warning is surfaced
# in the snapshot result. This catches the common case where the system
# falls back to the Deriv API (wrong prices) instead of MT5.
#
# These ranges are intentionally wide to avoid false positives during
# extreme volatility. The check flags gross mismatches (e.g. Vol 75 at
# ~7,000 from Deriv API instead of ~1,542 from Blueberry Markets).
EXPECTED_PRICE_RANGES: dict[str, tuple[float, float]] = {
    "R_75": (800.0, 4_000.0),     # Blueberry Volatility 75 trades ~1,200-1,800
    "R_100": (150.0, 600.0),      # Blueberry Volatility 100 trades ~250-350
}

# One-time warning flag — only warn once per process lifetime to avoid log spam
_PRICE_WARNING_SHOWN = False


def validate_tick_prices(
    symbol: str,
    ticks: list[Tick],
) -> dict[str, object] | None:
    """Check tick prices against expected ranges for the symbol.

    Returns a warning dict if prices are outside the expected range,
    or None if prices are within range. The dict contains:
      - "price_deviation": bool (True if prices are outside range)
      - "price_warning": str (human-readable warning message)
      - "expected_range": tuple[float, float]
      - "actual_min": float
      - "actual_max": float
    """
    if not ticks:
        return None

    price_range = EXPECTED_PRICE_RANGES.get(symbol)
    if price_range is None:
        return None  # No range defined for this symbol

    low, high = price_range
    prices = [t.price for t in ticks]
    actual_min = min(prices)
    actual_max = max(prices)

    # Check if the median price falls outside the expected range
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2]

    if median_price < low or median_price > high:
        # Calculate how far off we are
        if median_price > high:
            factor = median_price / high
            deviation_text = f"~{factor:.1f}x higher than expected"
        else:
            factor = low / median_price
            deviation_text = f"~{factor:.1f}x lower than expected"

        warning = (
            f"PRICE MISMATCH: {symbol} median price {median_price:.2f} is {deviation_text}. "
            f"Expected range: {low:.0f}-{high:.0f}. "
            f"This likely means the system is using Deriv API data instead of Blueberry Markets MT5. "
            f"Trade levels (entry/stop/target) will be WRONG."
        )
        global _PRICE_WARNING_SHOWN
        if not _PRICE_WARNING_SHOWN:
            _PRICE_WARNING_SHOWN = True
            print(f"[market_snapshot] {warning}", file=sys.stderr, flush=True)

        return {
            "price_deviation": True,
            "price_warning": warning,
            "expected_range": (low, high),
            "actual_min": actual_min,
            "actual_max": actual_max,
        }

    return None


# Trade-level keys that are cleaned from the alert dict for invalid/non-trade setups.
# These keys only have meaning when there's an actual trade signal with levels.
TRADE_LEVEL_KEYS: tuple[str, ...] = (
    "entry_area", "stop_area", "target_area",
    "entry", "stop_loss", "take_profit",
    "execution_stop", "thesis_invalidation",
    "primary_target", "extended_target",
    "hold_horizon_minutes", "reward_risk",
    "invalidates_if",
)


def _read_last_csv_epoch(symbol: str) -> float | None:
    """Read the newest (last) tick epoch from the CSV file for the given symbol.

    Returns None if the CSV doesn't exist or can't be read.
    This is used to surface "Data staleness" to the dashboard when
    all CSV ticks are older than MAX_TICK_AGE_SECONDS.
    """
    candidates = [
        Path(f"data/{symbol}_ticks.csv"),
        Path(f"data/{symbol.lower().replace('_', '')}_ticks.csv"),
        Path(f"data/{symbol.upper()}_ticks.csv"),
    ]
    csv_path = next((p for p in candidates if p.exists()), None)
    if csv_path is None:
        return None
    try:
        # Read the last data line efficiently (seek to near-end, grab one line)
        size = csv_path.stat().st_size
        if size == 0:
            return None
        with csv_path.open("rb") as f:
            # Read the last 512 bytes, find the last non-empty line
            read_start = max(0, size - 512)
            f.seek(read_start)
            data = f.read()
            lines = data.decode("utf-8", errors="replace").splitlines()
            for line in reversed(lines):
                line = line.strip()
                if line:
                    parts = line.split(",")
                    if parts:
                        return float(parts[0])
    except (ValueError, OSError):
        pass
    return None


def _rotate_csv(csv_path: Path | str, max_lines: int = 200_000) -> None:
    """Truncate a CSV file to keep only the last max_lines (header + max_lines-1 ticks).

    Uses a two-stage approach to avoid reading the entire file:
    1. Quick file-size heuristic: if the file is small, skip rotation entirely.
    2. Single-pass tail extraction: when rotation IS needed, read only the
       tail of the file to find the last max_lines lines.

    Called before every CSV read to prevent unbounded file growth.
    """
    if isinstance(csv_path, str):
        csv_path = Path(csv_path)
    try:
        file_size = csv_path.stat().st_size
        if file_size == 0:
            return

        # ── Stage 1: Quick heuristic ──────────────────────────────
        # A CSV line with typical tick data (epoch,symbol,price) is
        # ~25-40 bytes.  200K lines × 40 bytes ≈ 8 MB.  If the file
        # is under 6 MB, rotation is impossible — skip immediately.
        # This avoids the expensive line-count pass for the common case.
        HEURISTIC_BYTES_PER_LINE = 40
        estimated_lines = file_size // HEURISTIC_BYTES_PER_LINE
        if estimated_lines <= max_lines:
            return

        # ── Stage 2: Single-pass tail extraction ──────────────────
        # Read the tail of the file in chunks until we have enough lines.
        # We read from the end backwards, collecting full lines, then
        # prepend the header.  No separate line-count pass is needed.
        with csv_path.open('rb') as f:
            # Read tail chunks until we have enough lines
            chunk_size = 256 * 1024  # 256 KB chunks
            tail_chunks: list[bytes] = []
            lines_collected = 0
            pos = file_size
            while pos > 0 and lines_collected < max_lines:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                tail_chunks.append(chunk)
                # Count newlines in this chunk to estimate lines
                lines_collected += chunk.count(b'\n')

            # Reassemble the tail bytes and split into lines
            tail_bytes = b''.join(reversed(tail_chunks))
            all_lines = tail_bytes.split(b'\n')

            # Drop leading partial/empty lines from chunk boundaries.
            # When multiple chunks are read, the first element may be
            # a partial line or an empty bytes object (b'') from a
            # newline-aligned chunk boundary.
            if len(tail_chunks) > 1:
                if all_lines and all_lines[0] == b'':
                    all_lines = all_lines[1:]
                if all_lines and not all_lines[0].startswith(b'epoch'):
                    all_lines = all_lines[1:]

            # Keep the last max_lines lines (drop empty trailing line if present)
            if all_lines and all_lines[-1] == b'':
                all_lines = all_lines[:-1]
            keep = all_lines[-max_lines:]

            # Ensure the first line is the CSV header
            if keep and not keep[0].startswith(b'epoch'):
                # Read the header from file start
                f.seek(0)
                header = f.readline().strip()
                if header.startswith(b'epoch'):
                    keep = [header] + keep[1:]

            # Decode and write the trimmed file
            keep_text = b'\n'.join(keep)
            if not keep_text.endswith(b'\n'):
                keep_text += b'\n'

        csv_path.write_bytes(keep_text)
    except Exception:
        import traceback
        traceback.print_exc()

def _load_csv_ticks(
    symbol: str,
    max_ticks: int = 100000,
    max_age_seconds: int | None = None,
) -> list[Tick] | None:
    """Load ticks from the CSV file for the given symbol.

    Args:
        symbol: The symbol to load ticks for.
        max_ticks: Maximum number of ticks to read from the tail.
        max_age_seconds: Maximum age of ticks to keep. Ticks older than
            this are filtered out. Defaults to MAX_TICK_AGE_SECONDS.
            This is regime-aware — high-vol regimes use shorter max ages.

    Returns:
        A list of ticks, or None if no CSV file exists.
        Returns an empty list if all ticks are older than max_age_seconds.
    """
    if max_age_seconds is None:
        age_limit = MAX_TICK_AGE_SECONDS  # default: 6-hour filter
    elif max_age_seconds < 0:
        age_limit = float("inf")  # sentinel: negative = no filter (stale-data path)
    else:
        age_limit = max_age_seconds

    candidates = [
        Path(f"data/{symbol}_ticks.csv"),
        Path(f"data/{symbol.lower().replace('_', '')}_ticks.csv"),
        Path(f"data/{symbol.upper()}_ticks.csv"),
    ]
    csv_path = next((p for p in candidates if p.exists()), None)
    if csv_path is None:
        return None

    # Cache hit — same file, same mtime → use cached ticks
    # Note: cache is only valid for the same max_age_seconds threshold.
    # If the caller provides a different threshold, we skip the cache.
    cached = _csv_tick_cache.get(symbol)
    if cached is not None and max_age_seconds is None:
        cached_path, cached_mtime, cached_ticks = cached
        if cached_path == csv_path and csv_path.stat().st_mtime == cached_mtime:
            return cached_ticks

    # Rotate CSV if it exceeds the maximum line threshold (200K lines).
    # The analysis only reads the most recent 100K ticks from the tail, so
    # keeping more than 200K lines on disk is wasteful and slows down reads.
    _rotate_csv(csv_path, max_lines=200_000)

    try:
        ticks = _read_tail_ticks(csv_path, symbol, max_ticks)
        # ── Age filter (regime-aware) ────────────────────────────
        # Discard ticks older than the age limit. The limit can be
        # regime-aware — e.g., volatile regimes use 2h, range uses 12h.
        # This prevents the analysis from using stale data that no longer
        # reflects the current market microstructure.
        now = time.time()
        ticks = [t for t in ticks if now - t.epoch < age_limit]
        if not ticks:
            # All ticks were too old — clear the cache and treat as
            # "no valid CSV data" so the caller surfaces a stale-data
            # warning. Clearing the cache ensures the next call doesn't
            # return the old cached (stale) ticks via the mtime match.
            _csv_tick_cache.pop(symbol, None)
            return None
        _csv_tick_cache[symbol] = (csv_path, csv_path.stat().st_mtime, ticks)
        return ticks
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def _read_tail_ticks(csv_path: Path, symbol: str, max_count: int) -> list[Tick]:
    BUFFER_SIZE = 256 * 1024
    file_size = csv_path.stat().st_size
    if file_size <= 0:
        return []
    with csv_path.open("rb") as fh:
        fh.seek(0, 2)
        tail_chunks: list[bytes] = []
        accumulated = 0
        pos = file_size
        while pos > 0 and accumulated < BUFFER_SIZE * 20:
            read = min(BUFFER_SIZE, pos)
            pos -= read
            fh.seek(pos)
            data = fh.read(read)
            tail_chunks.append(data)
            accumulated += read
            if data.startswith(b"\n") and accumulated > BUFFER_SIZE * 18:
                break
    tail_bytes = b"".join(reversed(tail_chunks))
    if tail_bytes.startswith(b"\n"):
        tail_bytes = tail_bytes[1:]
    if not tail_bytes:
        return []
    first_newline = tail_bytes.find(b"\n")
    if first_newline > 0:
        tail_bytes = tail_bytes[first_newline + 1:]
    lines = tail_bytes.decode("utf-8", errors="replace").splitlines()
    ticks: list[Tick] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            # Support both legacy (3-col) and rich (6-col) CSV formats
            spread = float(parts[3]) if len(parts) > 3 else 0.0
            direction = int(parts[4]) if len(parts) > 4 else 0
            vol_proxy = float(parts[5]) if len(parts) > 5 else 0.0
            ticks.append(Tick(symbol=symbol, epoch=float(parts[0]), price=float(parts[2]), spread=spread, tick_direction=direction, volume_proxy=vol_proxy))
        except (ValueError, IndexError):
            continue
        if len(ticks) >= max_count:
            break
    ticks.reverse()
    return ticks


def _resolve_csv_path(symbol: str) -> Path:
    candidates = [
        Path(f"data/{symbol}_ticks.csv"),
        Path(f"data/{symbol.lower().replace('_', '')}_ticks.csv"),
        Path(f"data/{symbol.upper()}_ticks.csv"),
    ]
    existing = next((p for p in candidates if p.exists()), None)
    return existing if existing else candidates[0]


def analyze_live_snapshot(
    *,
    symbol: str,
    ticks: list[Tick],
    timeframe_sec: int,
    higher_timeframe_sec: int,
    config: TraderConfig | None = None,
    guardian_thresholds: GuardianThresholds | None = None,
    trading_mode: str = "sniper",
    model: OnlineLogisticModel | None = None,
) -> dict[str, object]:
    mode = trading_mode if trading_mode in TRADING_MODE_PRESETS else "sniper"
    preset = TRADING_MODE_PRESETS[mode]
    if config is None:
        config = build_mode_config(TraderConfig.default(), preset)
    if guardian_thresholds is None:
        guardian_thresholds = GUARDIAN_PRESETS[mode]
    profile = config.symbols[symbol]
    role_timeframes = {
        "bias": profile.bias_timeframe_sec,
        "setup": profile.setup_timeframe_sec,
        "confirmation": profile.confirmation_timeframe_sec,
        "execution": profile.execution_timeframe_sec,
    }
    requested_timeframes = sorted(set([timeframe_sec, higher_timeframe_sec, *role_timeframes.values()]))

    all_ticks = list(ticks)
    csv_ticks = _load_csv_ticks(symbol)
    if csv_ticks and len(csv_ticks) > len(all_ticks):
        epoch_set = {t.epoch for t in all_ticks}
        fresh = [t for t in csv_ticks if t.epoch not in epoch_set]
        all_ticks = all_ticks + fresh

    # ── Sort ticks by epoch ──────────────────────────────────────
    # CSV ticks can arrive out of chronological order (e.g. when
    # _read_tail_ticks reads the file tail and ticks were written
    # non-monotonically by MT5).  Out-of-order ticks cause the
    # CandleBuilder to create a new candle for each backward jump,
    # producing 4H candles with 481-point ranges on a 258-priced
    # instrument.  Sorting once here is O(n log n) vs the O(n²)
    # damage of per-tick candle creation.
    all_ticks.sort(key=lambda t: t.epoch)

    # ── Price sanity check ───────────────────────────────────────
    price_check = validate_tick_prices(symbol, all_ticks)

    builder = MultiTimeframeCandleBuilder(symbol, requested_timeframes)
    histories: dict[int, list[object]] = {tf: [] for tf in requested_timeframes}

    for tick in all_ticks:
        closed = builder.update(tick)
        for timeframe, candle in closed.items():
            histories.setdefault(timeframe, []).append(candle)

    flushed = builder.flush()
    for timeframe, candle in flushed.items():
        histories.setdefault(timeframe, []).append(candle)

    role_candles = {
        role: histories.get(role_timeframe, [])
        for role, role_timeframe in role_timeframes.items()
    }
    primary_candles = histories.get(timeframe_sec, [])
    higher_timeframe_candles = histories.get(higher_timeframe_sec, [])
    execution_candles = role_candles["execution"]
    confirmation_candles = role_candles["confirmation"]
    current_close = primary_candles[-1].close if primary_candles else (ticks[-1].price if ticks else None)

    regime = "unknown"
    regime_explanation = "need more candle history to classify the market"
    structure_summary = "structure still forming"
    model_long_probability = None

    decision_engine = DecisionEngine(config, model=model)

    if primary_candles:
        feature_snapshot = build_snapshot(
            symbol=symbol,
            timeframe_sec=timeframe_sec,
            candles=primary_candles,
            higher_timeframe_candles=higher_timeframe_candles,
            extra_timeframes={
                "bias": role_candles["bias"],
                "setup": role_candles["setup"],
                "confirmation": role_candles["confirmation"],
                "execution": role_candles["execution"],
            },
        )
        regime = feature_snapshot.regime.value
        regime_explanation = "; ".join(feature_snapshot.notes) or "regime is still neutral"
        structure_summary = _summarize_structure(dict(feature_snapshot.structure))
        # Inject missed-trade range boost into features so DecisionEngine
        # can read it in _regime_component for the RANGE case.
        _features_mut = dict(feature_snapshot.features)
        _features_mut["range_miss_boost"] = _confidence_scorer.missed_trade_boost
        feature_snapshot = FeatureSnapshot(
            symbol=feature_snapshot.symbol,
            epoch=feature_snapshot.epoch,
            timeframe_sec=feature_snapshot.timeframe_sec,
            features=_features_mut,
            regime=feature_snapshot.regime,
            structure=feature_snapshot.structure,
            notes=feature_snapshot.notes,
        )
        model_long_probability = round(
            decision_engine.model.predict_proba(dict(feature_snapshot.features)),
            3,
        )

    try:
        report = decision_engine.evaluate(
            symbol=symbol,
            candles=execution_candles,
            higher_timeframe_candles=confirmation_candles,
            role_candles=role_candles,
            trading_mode=mode,
        )
    except TypeError:
        report = decision_engine.evaluate(
            symbol=symbol,
            candles=execution_candles,
            higher_timeframe_candles=confirmation_candles,
            trading_mode=mode,
        )
    if report.signal is None:
        reasons = list(report.reasons)
        confidence = _extract_reason_value(reasons, r"confidence ([0-9.]+)")
        inferred_model_probability = _extract_reason_value(reasons, r"model long probability ([0-9.]+)")
        if inferred_model_probability is not None:
            model_long_probability = round(inferred_model_probability, 3)
        direction_bias = _direction_bias_from_probability(
            model_long_probability,
            buy_threshold=preset.bias_buy_threshold,
            sell_threshold=preset.bias_sell_threshold,
        )
        stale_max_age = _resolve_regime_max_age(regime)
        snapshot = {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": direction_bias,
        "signal_strength": "wait",
        "position_sizing": "none",
        "briefing": "current movement is active but not a clean setup yet",
            "symbol": symbol,
            "trading_mode": mode,
            "regime": regime,
            "regime_explanation": regime_explanation,
            "structure_summary": structure_summary,
            "confidence": confidence,
            "model_long_probability": model_long_probability,
            "current_close": current_close,
            "wait_for": _wait_for_next("not_valid", direction_bias, reasons),
            "reasons": reasons,
            "stale_data_max_age_seconds": stale_max_age,
            "risk_state": {
                "equity": config.risk.starting_equity,
                "open_positions": 0,
                "consecutive_losses": 0,
                "realized_pnl": 0.0,
                "trades_today": 0,
                "max_open_positions": config.risk.max_open_positions,
                "max_daily_loss_fraction": config.risk.max_daily_loss_fraction,
                "max_consecutive_losses": config.risk.max_consecutive_losses,
                "daily_drawdown_pct": 0.0,
            },
        }
        if primary_candles:
            snapshot["raw_features"] = dict(feature_snapshot.features)
            snapshot["snapshot_structure"] = dict(feature_snapshot.structure)
        # Attach price sanity check result
        if price_check:
            snapshot["price_deviation"] = price_check["price_deviation"]
            snapshot["price_warning"] = price_check["price_warning"]
            snapshot["expected_price_range"] = price_check["expected_range"]
        # ── Record missed trade for calibration feedback ────────
        # When the engine decides not to trade (signal is None), record the
        # decision so we can check later if the market moved in the predicted
        # direction.  This feeds back into CalibrationState so the model
        # learns from its conservatism over time.
        try:
            _maybe_record_missed_trade(
                symbol=symbol,
                model_long_probability=model_long_probability,
                confidence=confidence,
                regime=regime,
                current_close=current_close,
                features=dict(feature_snapshot.features) if primary_candles else {},
                bias_buy_threshold=preset.bias_buy_threshold,
                bias_sell_threshold=preset.bias_sell_threshold,
            )
            _maybe_resolve_missed_trades(decision_engine)
        except Exception:
            pass  # best-effort — never crash the snapshot
        return build_guardian_snapshot(snapshot, ticks, guardian_thresholds, trading_mode=mode)

    risk_engine = RiskEngine(config.risk)
    risk_decision = risk_engine.evaluate(report.signal)
    reasons = list(risk_decision.reasons or report.signal.rationale)
    direction_bias = "buy" if report.signal.direction.value == "long" else "sell"
    call = (
        "buy_candidate"
        if risk_decision.approved and direction_bias == "buy"
        else "sell_candidate"
        if risk_decision.approved and direction_bias == "sell"
        else "stand_aside"
    )
    snapshot_regime = report.signal.snapshot.regime.value
    stale_max_age = _resolve_regime_max_age(snapshot_regime)
    snapshot = {
        "call": call,
        "trade_status": "valid" if risk_decision.approved else "not_valid",
        "direction_bias": direction_bias,
        "signal_strength": getattr(report.signal, "signal_strength", "strong"),
        "position_sizing": getattr(report.signal, "position_sizing", "full"),
        "position_scale": getattr(report.signal, "position_scale", 1.0),
        "briefing": "; ".join(report.signal.rationale[:2]),
        "decision_summary": "; ".join(report.signal.rationale),
        "symbol": symbol,
        "trading_mode": mode,
        "regime": snapshot_regime,
        "regime_explanation": "; ".join(report.signal.snapshot.notes) or "regime is still neutral",
        "structure_summary": _summarize_structure(dict(report.signal.snapshot.structure)),
        "stale_data_max_age_seconds": stale_max_age,
        "confidence": round(report.signal.confidence, 3),
        "model_long_probability": round(
            decision_engine.model.predict_proba(dict(report.signal.snapshot.features)),
            3,
        ),
        "model_version": report.signal.model_version,
        "current_close": current_close,
        "entry": report.signal.entry,
        "execution_stop": report.signal.execution_stop,
        "thesis_invalidation": report.signal.thesis_invalidation,
        "primary_target": report.signal.primary_target,
        "extended_target": report.signal.extended_target,
        "hold_horizon_minutes": report.signal.hold_horizon_minutes,
        "stop_loss": report.signal.execution_stop if report.signal.execution_stop is not None else report.signal.stop_loss,
        "take_profit": report.signal.primary_target if report.signal.primary_target is not None else report.signal.take_profit,
        "reward_risk": round(report.signal.reward_risk, 3),
        "invalidates_if": (
            _build_execution_invalidation_text(
                direction_bias,
                report.signal.execution_stop,
                report.signal.execution_trigger_type,
            )
            or _build_invalidation_text(direction_bias, report.signal.stop_loss)
        ),
        "wait_for": _build_intraday_wait_for(
            trade_status="valid" if risk_decision.approved else "not_valid",
            direction_bias=direction_bias,
            hold_horizon_minutes=report.signal.hold_horizon_minutes,
            reasons=reasons,
            trigger_type=report.signal.execution_trigger_type,
        ),
        "reasons": reasons,
        "raw_features": dict(report.signal.snapshot.features),
        "snapshot_structure": dict(report.signal.snapshot.structure),
        "risk_state": {
            "equity": round(risk_engine.state.equity, 2),
            "open_positions": risk_engine.state.open_positions,
            "consecutive_losses": risk_engine.state.consecutive_losses,
            "realized_pnl": round(risk_engine.state.realized_pnl, 2),
            "trades_today": risk_engine.state.trades_today,
            "max_open_positions": config.risk.max_open_positions,
            "max_daily_loss_fraction": config.risk.max_daily_loss_fraction,
            "max_consecutive_losses": config.risk.max_consecutive_losses,
            "daily_drawdown_pct": round(risk_engine.daily_drawdown_fraction() * 100, 2),
        },
        **_format_trade_areas(
            report.signal.entry,
            report.signal.execution_stop if report.signal.execution_stop is not None else report.signal.stop_loss,
            report.signal.primary_target if report.signal.primary_target is not None else report.signal.take_profit,
        ),
    }
    # Attach price sanity check result
    if price_check:
        snapshot["price_deviation"] = price_check["price_deviation"]
        snapshot["price_warning"] = price_check["price_warning"]
        snapshot["expected_price_range"] = price_check["expected_range"]
    return build_guardian_snapshot(snapshot, ticks, guardian_thresholds, trading_mode=mode)


# ── Knowledge base daily cleanup ──────────────────────────────
# Runs KnowledgeBase.cleanup(max_days=90) once per day to prune old
# research notes and decisions. The time gate uses a module-level
# timestamp so it survives repeated warmup calls (every 45 seconds)
# without re-running cleanup.

_last_kb_cleanup_at: float | None = None
_KB_CLEANUP_INTERVAL_SEC = 86400  # 24 hours


def _maybe_cleanup_knowledge_base() -> None:
    """Run KnowledgeBase.cleanup(max_days=90) at most once per day."""
    global _last_kb_cleanup_at
    now = time.time()
    if _last_kb_cleanup_at is not None:
        if (now - _last_kb_cleanup_at) < _KB_CLEANUP_INTERVAL_SEC:
            return
    try:
        from synthetic_trader.research.knowledge import KnowledgeBase
        kb = KnowledgeBase(Path("data/research/knowledge"))
        result = kb.cleanup(max_days=90, archive_dir=Path("data/research/knowledge/archive"))
        total = sum(result.values())
        if total > 0:
            print(f"[knowledge] Cleanup: {result}", flush=True)
        _last_kb_cleanup_at = now
    except Exception:
        # Best-effort — cleanup failure must never crash the snapshot
        pass


# ── Trade journal daily cleanup ───────────────────────────────
# Prunes JSONL journal entries older than 90 days using the same
# daily time-gate pattern as the knowledge base cleanup.

_last_journal_cleanup_at: float | None = None
_JOURNAL_CLEANUP_INTERVAL_SEC = 86400
_JOURNAL_CLEANUP_MAX_DAYS = 90


def _extract_journal_entry_epoch(entry: dict[str, object]) -> float | None:
    """Extract a numeric epoch from a journal JSONL entry.

    Journal entries have different timestamp fields depending on type:
      - signal / outcome / rejection: 'epoch' (tick/close timestamp)
      - event records: no standard field — returns None (kept as-is)
    """
    epoch = entry.get("epoch")
    if isinstance(epoch, (int, float)) and epoch > 0:
        return float(epoch)
    return None


def _maybe_cleanup_journal() -> None:
    """Prune trade journal JSONL entries older than 90 days (once per day).

    Scans all `.jsonl` files under `journals/`, parses each entry to extract
    its epoch timestamp, and moves entries older than `max_days` into an
    archive file. Entries without a parseable timestamp are kept (we can't
    prune what we can't date).
    """
    global _last_journal_cleanup_at
    now = time.time()
    if _last_journal_cleanup_at is not None:
        if (now - _last_journal_cleanup_at) < _JOURNAL_CLEANUP_INTERVAL_SEC:
            return

    cutoff = now - _JOURNAL_CLEANUP_MAX_DAYS * 86400
    journals_dir = Path("journals")
    if not journals_dir.is_dir():
        _last_journal_cleanup_at = now
        return

    archive_dir = journals_dir / "archive"

    for jfile in sorted(journals_dir.glob("*.jsonl")):
        if jfile.parent != journals_dir:
            continue  # skip files already in subdirectories (e.g., archive/)
        try:
            lines = jfile.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue

            kept: list[str] = []
            pruned: list[dict[str, object]] = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    epoch = _extract_journal_entry_epoch(entry)
                    if epoch is not None and epoch < cutoff:
                        pruned.append(entry)
                    else:
                        kept.append(line)
                except json.JSONDecodeError:
                    # Malformed line — keep it rather than risk data loss
                    kept.append(line)

            if pruned:
                # Archive pruned entries
                archive_dir.mkdir(parents=True, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                archive_file = archive_dir / f"{jfile.stem}_archive_{ts}.jsonl"
                with archive_file.open("a", encoding="utf-8") as f:
                    for entry in pruned:
                        f.write(json.dumps(entry, sort_keys=True) + "\n")

                # Rewrite file with only recent entries
                jfile.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")

                print(
                    f"[journal] {jfile.name}: pruned {len(pruned)} entries, "
                    f"kept {len(kept)}",
                    flush=True,
                )
        except Exception:
            # Best-effort — cleanup failure must never crash the snapshot
            pass

    _last_journal_cleanup_at = now


async def run_live_snapshot(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    max_live_ticks: int,
    app_id: str | None = None,
    trading_mode: str = "sniper",
    model_path: str | None = None,
    skip_api: bool = False,
) -> dict[str, object]:
    # Once-per-day cleanup (best-effort, time-gated)
    _maybe_cleanup_knowledge_base()
    _maybe_cleanup_journal()

    _t_start = time.time()
    _phases: dict[str, float] = {}

    model = None
    if model_path:
        try:
            model = OnlineLogisticModel.load(model_path)
        except Exception:
            model = None

    if skip_api:
        _t_csv = time.time()
        ticks = _load_csv_ticks(symbol) or []
        _phases["csv_read_ms"] = int((time.time() - _t_csv) * 1000)

        # ── Stale-data handling ───────────────────────────────────
        # If the CSV file exists but _load_csv_ticks returned empty
        # (all ticks filtered by MAX_TICK_AGE_SECONDS), we still have
        # data on disk — just old data. Instead of returning a minimal
        # "stale" result, load ALL ticks without the age filter and run
        # the full analysis pipeline on them. The result is flagged with
        # stale_data_since so the frontend can surface the staleness,
        # but all the real analysis (candles → features → structure →
        # regime → decision engine) still runs on actual market data.
        _csv_exists = any(
            Path(f"data/{name}_ticks.csv").exists()
            for name in [symbol, symbol.lower().replace('_', ''), symbol.upper()]
        )
        if _csv_exists and not ticks:
            # Load ALL ticks from the CSV tail, bypassing the age filter.
            stale_epoch = _read_last_csv_epoch(symbol)
            stale_max_age = _resolve_regime_max_age(None)
            all_old_ticks = _load_csv_ticks(symbol, max_age_seconds=-1) or []
            if all_old_ticks:
                _t_analysis = time.time()
                result = analyze_live_snapshot(
                    symbol=symbol, ticks=all_old_ticks,
                    timeframe_sec=timeframe_sec,
                    higher_timeframe_sec=higher_timeframe_sec,
                    trading_mode=trading_mode, model=model,
                )
                # Flag the result as stale so the frontend can show
                # a "Data staleness: X hours" warning in the dashboard.
                result["stale_data_since"] = stale_epoch
                result["stale_data_max_age_seconds"] = stale_max_age
                _phases["analysis_ms"] = int((time.time() - _t_analysis) * 1000)
                _phases["total_ms"] = int((time.time() - _t_start) * 1000)
                result["phase_timing_ms"] = _phases
                return result

            # CSV exists but couldn't be parsed — return stale fallback.
            stale_hours = stale_max_age / 3600
            result = build_guardian_snapshot({
                "call": "stand_aside",
                "trade_status": "not_valid",
                "direction_bias": "none",
                "briefing": f"CSV tick data is stale — no fresh ticks in the last {stale_hours:.0f}h",
                "symbol": symbol,
                "trading_mode": trading_mode,
                "regime": "unknown",
                "regime_explanation": "Tick data is too old for reliable analysis",
                "structure_summary": "structure still forming",
                "confidence": None,
                "model_long_probability": None,
                "current_close": None,
                "wait_for": "wait for live tick collection to provide fresh data",
                "reasons": [f"CSV data is older than {stale_hours:.0f}h — live tick collection required"],
                "risk_state": {
                    "equity": 1000.0,
                    "open_positions": 0, "consecutive_losses": 0,
                    "realized_pnl": 0.0, "trades_today": 0,
                    "max_open_positions": 1,
                    "max_daily_loss_fraction": 0.02,
                    "max_consecutive_losses": 4, "daily_drawdown_pct": 0.0,
                },
                "stale_data_since": stale_epoch,
                "stale_data_max_age_seconds": stale_max_age,
            }, [], DEFAULT_GUARDIAN_THRESHOLDS, trading_mode=trading_mode)
            _phases["total_ms"] = int((time.time() - _t_start) * 1000)
            result["phase_timing_ms"] = _phases
            return result

        _t_analysis = time.time()
        result = analyze_live_snapshot(
            symbol=symbol, ticks=ticks, timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            trading_mode=trading_mode, model=model,
        )
        _phases["analysis_ms"] = int((time.time() - _t_analysis) * 1000)
        _phases["total_ms"] = int((time.time() - _t_start) * 1000)
        result["phase_timing_ms"] = _phases
        return result

    _t_csv = time.time()
    csv_ticks = _load_csv_ticks(symbol)
    _phases["csv_read_ms"] = int((time.time() - _t_csv) * 1000)

    try:
        _t_tick = time.time()
        ticks = await asyncio.wait_for(
            collect_live_snapshot_ticks(
                symbol=symbol, warmup_count=warmup_count,
                max_live_ticks=max_live_ticks, app_id=app_id,
            ),
            timeout=25.0,
        )
        _phases["tick_collect_ms"] = int((time.time() - _t_tick) * 1000)

        _t_append = time.time()
        try:
            csv_path = _resolve_csv_path(symbol)
            append_ticks_csv(csv_path, ticks)
        except Exception:
            pass
        _phases["append_csv_ms"] = int((time.time() - _t_append) * 1000)

        _t_analysis = time.time()
        result = analyze_live_snapshot(
            symbol=symbol, ticks=ticks, timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            trading_mode=trading_mode, model=model,
        )
        _phases["analysis_ms"] = int((time.time() - _t_analysis) * 1000)
        _phases["total_ms"] = int((time.time() - _t_start) * 1000)
        result["phase_timing_ms"] = _phases
        return result
    except Exception as e:
        print(f"[market_snapshot] live snapshot failed: {e}", file=sys.stderr, flush=True)
        _phases["total_ms"] = int((time.time() - _t_start) * 1000)

    if is_mt5_configured():
        stale_max_age = _resolve_regime_max_age(None)
        result = build_guardian_snapshot({
            "call": "stand_aside", "trade_status": "not_valid",
            "direction_bias": "none",
            "briefing": "MT5 connection in progress — waiting for fresh data",
            "symbol": symbol, "trading_mode": trading_mode,
            "regime": "unknown", "regime_explanation": "Connecting to MT5 broker",
            "structure_summary": "structure still forming",
            "confidence": None, "model_long_probability": None,
            "current_close": None,
            "wait_for": "give the broker connection a few more seconds, then refresh",
            "reasons": ["mt5 broker connection initialising, retry shortly"],
            "risk_state": {
                "equity": 1000.0, "open_positions": 0, "consecutive_losses": 0,
                "realized_pnl": 0.0, "trades_today": 0, "max_open_positions": 1,
                "max_daily_loss_fraction": 0.02, "max_consecutive_losses": 4,
                "daily_drawdown_pct": 0.0,
            },
            "stale_data_since": _read_last_csv_epoch(symbol),
            "stale_data_max_age_seconds": stale_max_age,
        }, [], DEFAULT_GUARDIAN_THRESHOLDS, trading_mode=trading_mode)
        result["phase_timing_ms"] = _phases
        return result

    if csv_ticks:
        _t_analysis = time.time()
        result = analyze_live_snapshot(
            symbol=symbol, ticks=csv_ticks, timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            trading_mode=trading_mode, model=model,
        )
        _phases["analysis_ms"] = int((time.time() - _t_analysis) * 1000)
        _phases["total_ms"] = int((time.time() - _t_start) * 1000)
        result["phase_timing_ms"] = _phases
        return result

    stale_max_age = _resolve_regime_max_age(None)
    result = build_guardian_snapshot({
        "call": "stand_aside", "trade_status": "not_valid",
        "direction_bias": "none", "briefing": "No data available",
        "symbol": symbol, "trading_mode": trading_mode,
        "regime": "unknown", "regime_explanation": "No tick data found",
        "structure_summary": "structure still forming",
        "confidence": None, "model_long_probability": None,
        "current_close": None, "wait_for": "wait for tick data to become available",
        "reasons": ["no tick data available"],
        "risk_state": {
            "equity": 1000.0, "open_positions": 0, "consecutive_losses": 0,
            "realized_pnl": 0.0, "trades_today": 0, "max_open_positions": 1,
            "max_daily_loss_fraction": 0.02, "max_consecutive_losses": 4,
            "daily_drawdown_pct": 0.0,
        },
        "stale_data_since": _read_last_csv_epoch(symbol),
        "stale_data_max_age_seconds": stale_max_age,
    }, [], DEFAULT_GUARDIAN_THRESHOLDS, trading_mode=trading_mode)
    _phases["total_ms"] = int((time.time() - _t_start) * 1000)
    result["phase_timing_ms"] = _phases
    return result


# ── Render helpers (CLI text output) ─────────────────────────

def render_live_snapshot_text(snapshot: dict[str, object]) -> str:
    """Render a snapshot dict as human-readable CLI text.

    Briefing is printed *before* structured fields so that the human
    operator sees the plain-English summary first.
    """
    lines = []
    if snapshot.get("briefing"):
        lines.append(f"briefing={snapshot['briefing']}")
    lines.append(f"symbol={snapshot.get('symbol', '?')}")
    lines.append(f"trading_mode={snapshot.get('trading_mode', 'sniper')}")
    lines.append(f"call={snapshot.get('call', 'unknown')}")
    lines.append(f"trade_status={snapshot.get('trade_status', 'unknown')}")
    lines.append(f"direction_bias={snapshot.get('direction_bias', 'none')}")
    lines.append(f"regime={snapshot.get('regime', 'unknown')}")
    if snapshot.get("regime_explanation"):
        lines.append(f"regime_explanation={snapshot['regime_explanation']}")
    lines.append(f"guardian_state={snapshot.get('guardian_state', 'unknown')}")
    lines.append(f"guardian_reason={snapshot.get('guardian_reason', 'no reason')}")
    if snapshot.get("current_close") is not None:
        lines.append(f"current_close={snapshot['current_close']}")
    if snapshot.get("entry") is not None:
        lines.append(f"entry={snapshot['entry']}")
    if snapshot.get("stop_loss") is not None:
        lines.append(f"stop_loss={snapshot['stop_loss']}")
    if snapshot.get("take_profit") is not None:
        lines.append(f"take_profit={snapshot['take_profit']}")
    if snapshot.get("confidence") is not None:
        lines.append(f"confidence={snapshot['confidence']}")
    if snapshot.get("wait_for"):
        lines.append(f"wait_for={snapshot['wait_for']}")
    if snapshot.get("reasons"):
        lines.append(f"reasons={snapshot['reasons']}")
    return "\n".join(lines)


def render_live_watch_alert_text(alert: dict[str, object]) -> str:
    """Render a live-watch alert dict as human-readable CLI text.

    Field ordering rules:
    - If *decision_summary* is present it goes first (operator headline).
    - Otherwise *alert_type* goes first.
    - Then *call*, *symbol*, and remaining fields in a natural order.
    """
    lines: list[str] = []
    if alert.get("decision_summary"):
        lines.append(f"decision_summary={alert['decision_summary']}")
        lines.append(f"alert_type={alert.get('alert_type', 'unknown')}")
    else:
        lines.append(f"alert_type={alert.get('alert_type', 'unknown')}")
    lines.append(f"call={alert.get('call', 'unknown')}")
    lines.append(f"symbol={alert.get('symbol', '?')}")
    if alert.get("why"):
        lines.append(f"why={alert['why']}")
    lines.append(f"direction_bias={alert.get('direction_bias', 'none')}")
    lines.append(f"trade_status={alert.get('trade_status', 'unknown')}")
    lines.append(f"regime={alert.get('regime', 'unknown')}")
    if alert.get("guardian_state"):
        lines.append(f"guardian_state={alert['guardian_state']}")
    if alert.get("wait_for"):
        lines.append(f"wait_for={alert['wait_for']}")
    if alert.get("current_close") is not None:
        lines.append(f"current_close={alert['current_close']}")
    if alert.get("entry") is not None:
        lines.append(f"entry={alert['entry']}")
    if alert.get("entry_area"):
        lines.append(f"entry_area={alert['entry_area']}")
    if alert.get("stop_area"):
        lines.append(f"stop_area={alert['stop_area']}")
    if alert.get("target_area"):
        lines.append(f"target_area={alert['target_area']}")
    if alert.get("stop_loss") is not None:
        lines.append(f"stop_loss={alert['stop_loss']}")
    if alert.get("take_profit") is not None:
        lines.append(f"take_profit={alert['take_profit']}")
    if alert.get("reward_risk") is not None:
        lines.append(f"reward_risk={alert['reward_risk']}")
    return "\n".join(lines)


# ── Live watch loop ──────────────────────────────────────────
# Context-update cooldown: suppress non-setup_candidate alerts
# that occur within CONTEXT_COOLDOWN_SEC of the previous emitted alert.
DEFAULT_CONTEXT_ALERT_COOLDOWN = 2


async def _build_watch_baseline(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    app_id: str | None,
) -> tuple[list, dict[str, object], WatchState]:
    """Collect warm-up ticks, build a snapshot, and return (ticks, alert, WatchState).

    This is the shared logic used for both the initial baseline and the
    post-reconnect baseline rebuild.
    """
    ticks = await collect_live_snapshot_ticks(
        symbol=symbol, warmup_count=warmup_count, max_live_ticks=0, app_id=app_id,
    )
    snapshot = analyze_live_snapshot(
        symbol=symbol,
        ticks=ticks,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
    )
    alert = build_watch_alert(snapshot)
    alert["symbol"] = symbol
    state = build_watch_state(alert)
    return ticks, alert, state


async def _handle_reconnect(
    *,
    exc: Exception,
    symbol: str,
    reconnects: int,
    max_reconnects: int,
    reconnect_backoff_sec: int,
    journal_file: Path,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    app_id: str | None,
    warmup_ticks: list,
    previous: WatchState | None,
) -> tuple[bool, int, list, WatchState | None]:
    """Handle a transport failure: journal, sleep, rebuild baseline.

    Returns ``(should_break, reconnects, warmup_ticks, previous)``.
    ``should_break`` is ``True`` when retries are exhausted.
    """
    reconnects += 1
    transport_record = {
        "record_type": "watch_transport",
        "event": "reconnect_attempt" if reconnects <= max_reconnects else "reconnect_failed",
        "symbol": symbol,
        "error": str(exc),
    }
    _append_journal(journal_file, transport_record)
    if reconnects > max_reconnects:
        return True, reconnects, warmup_ticks, previous
    await asyncio.sleep(reconnect_backoff_sec * reconnects)
    # Rebuild baseline after reconnect
    try:
        warmup_ticks, _, previous = await _build_watch_baseline(
            symbol=symbol,
            warmup_count=warmup_count,
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            app_id=app_id,
        )
        _append_journal(journal_file, {
            "record_type": "watch_transport",
            "event": "reconnect_rebaseline_ok",
            "symbol": symbol,
        })
    except Exception:
        pass
    return False, reconnects, warmup_ticks, previous


async def run_live_watch(
    *,
    symbol: str,
    warmup_count: int = 5000,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
    journal_path: str = "journals/live_watch_alerts.jsonl",
    emit_initial: bool = False,
    max_alerts: int | None = None,
    max_minutes: int | None = None,
    max_reconnects: int = 5,
    reconnect_backoff_sec: int = 1,
    app_id: str | None = None,
) -> list[dict[str, object]]:
    """Monitor a symbol and emit read-only operator calls on meaningful change.

    Uses ``collect_live_snapshot_ticks`` for warm-up history, then loops
    on ``watch_live_ticks`` to accumulate fresh ticks.  After each batch
    the snapshot is evaluated via ``analyze_live_snapshot`` and the
    resulting alert is compared against the previous one via
    ``has_material_context_change`` / ``should_emit_watch_alert``.
    """
    alert_log: list[dict[str, object]] = []
    journal_file = Path(journal_path)
    journal_file.parent.mkdir(parents=True, exist_ok=True)

    previous: WatchState | None = None
    reconnects = 0
    context_cooldown_remaining = 0

    # ── warm-up baseline ──────────────────────────────────────
    warmup_ticks, baseline_alert, previous = await _build_watch_baseline(
        symbol=symbol,
        warmup_count=warmup_count,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        app_id=app_id,
    )

    if emit_initial:
        alert_log.append(baseline_alert)
        _append_journal(journal_file, baseline_alert)
        if baseline_alert.get("alert_type") == "context_update":
            context_cooldown_remaining = DEFAULT_CONTEXT_ALERT_COOLDOWN

    # ── main watch loop ───────────────────────────────────────
    while reconnects <= max_reconnects:
        if max_alerts and len(alert_log) >= max_alerts:
            break
        try:
            fresh_ticks = await watch_live_ticks(
                symbol=symbol, app_id=app_id, max_minutes=max_minutes,
            )
            if not fresh_ticks:
                break

            all_ticks = list(warmup_ticks) + list(fresh_ticks)
            result = analyze_live_snapshot(
                symbol=symbol,
                ticks=all_ticks,
                timeframe_sec=timeframe_sec,
                higher_timeframe_sec=higher_timeframe_sec,
            )
            alert = build_watch_alert(result)
            alert["symbol"] = symbol
            current = build_watch_state(alert)

            # Decrement cooldown counter per iteration (bucket-based)
            if context_cooldown_remaining > 0:
                context_cooldown_remaining -= 1

            if should_emit_watch_alert(previous, current, context_cooldown_remaining=context_cooldown_remaining):
                alert_log.append(alert)
                _append_journal(journal_file, alert)
                if alert.get("alert_type") == "context_update":
                    context_cooldown_remaining = DEFAULT_CONTEXT_ALERT_COOLDOWN
                previous = current
            elif previous is not None and current != previous:
                # Context changed but cooldown blocked emission — journal the
                # suppression so the review command can show transport health.
                suppressed = dict(alert)
                suppressed["record_type"] = "suppressed_context"
                _append_journal(journal_file, suppressed)

            warmup_ticks = all_ticks
            if max_alerts and len(alert_log) >= max_alerts:
                break

        except StopIteration:
            # Exhausted snapshot source — clean exit
            break
        except Exception as exc:
            should_break, reconnects, warmup_ticks, previous = await _handle_reconnect(
                exc=exc,
                symbol=symbol,
                reconnects=reconnects,
                max_reconnects=max_reconnects,
                reconnect_backoff_sec=reconnect_backoff_sec,
                journal_file=journal_file,
                warmup_count=warmup_count,
                timeframe_sec=timeframe_sec,
                higher_timeframe_sec=higher_timeframe_sec,
                app_id=app_id,
                warmup_ticks=warmup_ticks,
                previous=previous,
            )
            if should_break:
                break

    return alert_log


def build_live_watch_review_snapshot(
    *,
    journal_path: Path,
    symbol: str | None = None,
    limit: int = 5,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> dict[str, object]:
    """Build a review snapshot from a live-watch journal JSONL file.

    Returns a flat dict with ``latest_*`` summary fields, ``alert_count``,
    ``suppressed_context_count``, ``transport_event_count``, and an
    ``alerts`` list with the filtered entries.
    """
    if not journal_path.exists():
        raise ValueError(f"Journal file not found: {journal_path}")

    all_records: list[dict[str, object]] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        all_records.append(entry)

    # If the file exists but has no content, return a safe empty state
    # (empty journal is valid — just no alerts yet)
    # But if lines were present but ALL failed to parse, that's invalid.
    raw_text = journal_path.read_text(encoding="utf-8")
    non_empty_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if non_empty_lines and not all_records:
        raise ValueError(f"No valid entries found in journal: {journal_path}")

    # Separate by record type
    alert_entries: list[dict[str, object]] = []
    suppressed_entries: list[dict[str, object]] = []
    transport_entries: list[dict[str, object]] = []
    for entry in all_records:
        rtype = entry.get("record_type", "")
        if rtype == "suppressed_context":
            suppressed_entries.append(entry)
        elif rtype == "watch_transport":
            transport_entries.append(entry)
        else:
            alert_entries.append(entry)

    # Apply filters to alert entries
    filtered: list[dict[str, object]] = []
    for entry in alert_entries:
        if symbol and entry.get("symbol") != symbol:
            continue
        if call_filter and entry.get("call") != call_filter:
            continue
        if valid_only and entry.get("trade_status") != "valid":
            continue
        filtered.append(entry)

    # Filter suppressed entries by the same criteria (except transport)
    filtered_suppressed: list[dict[str, object]] = []
    for entry in suppressed_entries:
        if symbol and entry.get("symbol") != symbol:
            continue
        if call_filter and entry.get("call") != call_filter:
            continue
        if valid_only and entry.get("trade_status") != "valid":
            continue
        filtered_suppressed.append(entry)

    filtered = filtered[-limit:]
    latest = filtered[-1] if filtered else None
    latest_suppressed = filtered_suppressed[-1] if filtered_suppressed else None
    latest_transport = transport_entries[-1] if transport_entries else None

    result: dict[str, object] = {
        "alert_count": len(filtered),
        "latest_call": latest.get("call") if latest else None,
        "latest_symbol": latest.get("symbol") if latest else None,
        "latest_trade_status": latest.get("trade_status") if latest else None,
        "latest_direction_bias": latest.get("direction_bias") if latest else None,
        "latest_regime": latest.get("regime") if latest else None,
        "latest_confidence": latest.get("confidence") if latest else None,
        "latest_current_close": latest.get("current_close") if latest else None,
        "latest_wait_for": latest.get("wait_for") if latest else None,
        "alerts": filtered,
        "suppressed_context_count": len(filtered_suppressed),
        "latest_suppressed_direction_bias": latest_suppressed.get("direction_bias") if latest_suppressed else None,
        "latest_suppressed_regime": latest_suppressed.get("regime") if latest_suppressed else None,
        "latest_suppressed_why": latest_suppressed.get("why", latest_suppressed.get("briefing")) if latest_suppressed else None,
        "latest_suppressed_wait_for": latest_suppressed.get("wait_for") if latest_suppressed else None,
        "transport_event_count": len(transport_entries),
        "latest_transport_event": latest_transport.get("event") if latest_transport else None,
        "latest_transport_reason": latest_transport.get("reason") if latest_transport else None,
        "latest_transport_attempt": latest_transport.get("attempt") if latest_transport else None,
        "latest_transport_attempts": latest_transport.get("attempts") if latest_transport else None,
        "latest_transport_regime": latest_transport.get("regime") if latest_transport else None,
        "latest_transport_direction_bias": latest_transport.get("direction_bias") if latest_transport else None,
        "latest_transport_trade_status": latest_transport.get("trade_status") if latest_transport else None,
        "latest_transport_confidence": latest_transport.get("confidence") if latest_transport else None,
    }
    return result


def render_live_watch_review_text(snapshot: dict[str, object]) -> str:
    """Render a live-watch review snapshot as CLI text."""
    lines: list[str] = []
    # Summary header
    lines.append(f"review_latest_call={snapshot.get('latest_call', 'none')}")
    lines.append(f"review_latest_symbol={snapshot.get('latest_symbol', 'none')}")
    lines.append(f"review_alert_count={snapshot.get('alert_count', 0)}")

    # Suppression summary
    suppressed_count = snapshot.get("suppressed_context_count", 0)
    if suppressed_count:
        lines.append(f"review_suppressed_context_count={suppressed_count}")
        if snapshot.get("latest_suppressed_direction_bias"):
            lines.append(f"review_latest_suppressed_direction_bias={snapshot['latest_suppressed_direction_bias']}")
        if snapshot.get("latest_suppressed_regime"):
            lines.append(f"review_latest_suppressed_regime={snapshot['latest_suppressed_regime']}")
        if snapshot.get("latest_suppressed_why"):
            lines.append(f"review_latest_suppressed_why={snapshot['latest_suppressed_why']}")

    # Transport summary
    transport_count = snapshot.get("transport_event_count", 0)
    if transport_count:
        lines.append(f"review_transport_event_count={transport_count}")
        if snapshot.get("latest_transport_event"):
            lines.append(f"review_latest_transport_event={snapshot['latest_transport_event']}")
        if snapshot.get("latest_transport_reason"):
            lines.append(f"review_latest_transport_reason={snapshot['latest_transport_reason']}")
        if snapshot.get("latest_transport_direction_bias"):
            lines.append(f"review_latest_transport_direction_bias={snapshot['latest_transport_direction_bias']}")

    # Individual alerts
    for entry in snapshot.get("alerts", []):
        if entry.get("decision_summary"):
            lines.append(f"decision_summary={entry['decision_summary']}")
        if entry.get("alert_type"):
            lines.append(f"alert_type={entry['alert_type']}")
        lines.append(f"call={entry.get('call', '?')}")
        lines.append(f"symbol={entry.get('symbol', '?')}")
        if entry.get("why"):
            lines.append(f"why={entry['why']}")
        if entry.get("wait_for"):
            lines.append(f"wait_for={entry['wait_for']}")
        if entry.get("entry_area"):
            lines.append(f"entry_area={entry['entry_area']}")
        if entry.get("stop_area"):
            lines.append(f"stop_area={entry['stop_area']}")
        if entry.get("target_area"):
            lines.append(f"target_area={entry['target_area']}")
        if entry.get("current_close") is not None:
            lines.append(f"current_close={entry['current_close']}")
    return "\n".join(lines)


def build_watch_alert_from_prepared_state(
    prepared: PreparedSymbolState,
) -> dict[str, object]:
    """Convert a PreparedSymbolState into a watch alert dict."""
    call = prepared.call
    direction_bias = (
        "buy" if call.startswith("buy")
        else "sell" if call.startswith("sell")
        else "none"
    )
    trade_status = "valid" if prepared.state in ("actionable", "confirmed") else "not_valid"
    alert: dict[str, object] = {
        "symbol": prepared.symbol,
        "call": call,
        "guardian_state": prepared.state,
        "direction_bias": direction_bias,
        "trade_status": trade_status,
        "confidence": prepared.confidence,
        "regime": prepared.regime,
        "briefing": prepared.market_thesis,
        "why": prepared.market_thesis,
        "entry": prepared.entry,
        "stop_loss": prepared.stop_loss,
        "take_profit": prepared.take_profit,
        "current_close": prepared.current_close,
        "reward_risk": prepared.reward_risk,
        "invalidates_if": prepared.invalidates_if,
        "wait_for": prepared.next_trigger,
        "call_age_seconds": prepared.call_age_seconds,
        "generated_at": prepared.generated_at,
    }
    return alert


def _append_journal(path: Path, record: dict[str, object]) -> None:
    """Append a single JSON record to a JSONL journal file.

    Logs a warning on disk-full or permission errors instead of failing silently
    so that production issues are diagnosable from logs.
    """
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        logging.warning(
            "[_append_journal] failed to write to %s: %s", path, exc,
        )
