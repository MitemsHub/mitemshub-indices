from __future__ import annotations

import asyncio
import contextlib
import csv
import os
import sys
import time
from datetime import datetime, timezone
from collections.abc import Callable
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from synthetic_trader.config import (
    MAX_FEATURE_HISTORY,
    ModelConfig,
    RiskConfig,
    SymbolProfile,
    TraderConfig,
)
from synthetic_trader.data.collector import deriv_credentials_from_env
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import Tick, FeatureSnapshot
from synthetic_trader.execution.deriv_ws import DerivWebSocketClient
from synthetic_trader.execution.venues import MarketDataClient
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.live.live_symbol_watcher import PreparedSymbolState
from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianEvaluation,
    GuardianSnapshot,
    GuardianThresholds,
    _effective_confirmed_lock_ticks,
    evaluate_signal_guardian,
)
from synthetic_trader.live.guardian_memory import (
    clear_guardian_memory as _clear_guardian_memory,
    load_guardian_memory as _load_guardian_memory,
    plan_matches as _plan_matches,
    save_guardian_memory as _save_guardian_memory,
)
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine
from synthetic_trader.models.advanced import ConfidenceScorer
from synthetic_trader.data.tick_store import append_ticks_csv
from synthetic_trader.execution.mt5_data import Mt5TickClient, is_mt5_configured
from synthetic_trader.config import TraderConfig as _TraderConfig
from synthetic_trader.live.missed_trade_tracker import MissedTradeTracker
from synthetic_trader.live.calibration_logger import append_call_record, build_call_record
from synthetic_trader.live.stage3_gate import apply_stage3_gate
from synthetic_trader.live.auto_scorer import (
    DEFAULT_OUTCOMES_PATH,
    DEFAULT_STATUS_PATH,
    MAX_CONSECUTIVE_ERRORS,
    SWEEP_BACKOFF_SEC,
    sweep_once,
)


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
# Sniper mode generates 4-6 hour swing trade plans.
SNIPER_GUARDIAN_THRESHOLDS = GuardianThresholds(
    # Sniper mode is a 4-6 HOUR swing trade.  The guardian must operate
    # on a swing-trade timescale.
    #
    # Key design principles:
    # 1. After confirmation, the guardian only checks thesis invalidation
    #    (stop hit) — NOT microstructure quality.  Normal pullbacks on
    #    volatile synthetics WILL trigger rollover/acceleration checks
    #    if we evaluate tick-level microstructure.
    # 2. Confirmed lock is 720 ticks (60 minutes) — a swing trade needs
    #    stability, not flickering states.
    # 3. Microstructure window is 120 ticks (10 minutes) — not 16 ticks
    #    (80 seconds).  This gives a meaningful view of price action.
    max_arming_ticks=360,           # 30 min arming window for swing trades
    max_confirmation_window_ticks=360,  # 30 min to confirm
    weakening_excursion_ratio=0.85,   # 85% — only degrade on near-stop moves
    max_adverse_excursion_ratio=0.95,
    max_entry_drift_ratio=0.95,      # 95% — tolerate large drift on swings
    microstructure_window_ticks=120,   # 120 ticks = 10 min (was 16)
    min_persistence_ticks=1,
    min_impulse_ratio=0.02,
    max_pullback_ratio=0.90,         # 90% — only invalidate on near-stop pullbacks
    rollover_warning_ratio=0.88,      # 88% — very tolerant of pullbacks
    rollover_invalidation_ratio=0.95,
    adverse_cluster_window_ticks=12,
    max_adverse_cluster_count=8,
    # Sniper confirmed lock: 720 ticks = 60 minutes.
    # A 4-6 hour swing trade needs at least 60 minutes of stability
    # after confirmation.  High-confidence setups get 900 ticks (75 min).
    confirmed_lock_ticks=720,
    confirmed_lock_ticks_high=900,
    confirmed_lock_ticks_low=360,
)

# ── Sniper-only mode ───────────────────────────────────────────
# Active trader and volatility harvest modes removed.
# The system now runs exclusively in sniper mode for 4-6 hour
# swing trades.  All guardian thresholds use SNIPER only.
GUARDIAN_PRESETS = {
    "sniper": SNIPER_GUARDIAN_THRESHOLDS,
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

# ── Persistent DecisionEngine singleton ────────────────────────
# CRITICAL FIX: Previously, every snapshot call created a brand-new
# DecisionEngine, which meant the OnlineLogisticModel started with
# random weights, the CalibrationState was empty, and the
# RegimeShiftDetector had no history.  The engine never learned.
#
# This module-level singleton persists across snapshot calls within
# the same Python process.  It is keyed by (symbol, trading_mode)
# so that switching modes creates separate engines without
# cross-contaminating their calibration buffers.
_decision_engines: dict[str, DecisionEngine] = {}

# ── Disk persistence path for DecisionEngine state ─────────────
# Model weights and calibration buffer are saved to JSON so learning
# survives Python process restarts.  Path: data/model_state/{symbol}_{mode}.json
_MODEL_STATE_DIR = Path("data/model_state")
_MODEL_STATE_SAVE_INTERVAL = 10  # save at most once every N snapshots
_snapshot_counter: dict[str, int] = {}


def _get_persistent_decision_engine(
    symbol: str,
    trading_mode: str,
    config: TraderConfig | None = None,
    model: OnlineLogisticModel | None = None,
) -> DecisionEngine:
    """Return a persistent DecisionEngine for (symbol, mode).

    On first call, creates and stores a new engine.  On subsequent
    calls with the same (symbol, mode), returns the cached engine
    so its CalibrationState, RegimeShiftDetector, and model weights
    persist across snapshots.

    On first creation, attempts to load saved state from
    ``data/model_state/{symbol}_{mode}.json`` so learning survives
    Python process restarts.
    """
    key = f"{symbol}_{trading_mode}"
    if key not in _decision_engines:
        engine = DecisionEngine(config, model=model)
        # Try to load saved state from disk
        state_path = _MODEL_STATE_DIR / f"{key}.json"
        if state_path.exists():
            loaded = engine.load_state(state_path)
            if loaded:
                logging.info(
                    "[market_snapshot] restored DecisionEngine state for %s from %s",
                    key, state_path,
                )
        _decision_engines[key] = engine
    return _decision_engines[key]


def _maybe_save_engine_state(key: str, engine: DecisionEngine) -> None:
    """Auto-save engine state to disk.

    Saves on the first snapshot of each process lifetime AND then every
    _MODEL_STATE_SAVE_INTERVAL snapshots thereafter.

    The first-save-per-process ensures that even short-lived subprocess
    calls (which reset _snapshot_counter to 0 each time) still persist
    at least one state file to disk, so the calibration-stats API has
    data to return.

    The save is fire-and-forget — errors are logged but never raised.
    """
    global _snapshot_counter
    count = _snapshot_counter.get(key, 0) + 1
    _snapshot_counter[key] = count
    # Save on the very first snapshot (count == 1) OR every Nth snapshot.
    is_first_snapshot = count == 1
    is_interval = count % _MODEL_STATE_SAVE_INTERVAL == 0
    if not is_first_snapshot and not is_interval:
        return
    state_path = _MODEL_STATE_DIR / f"{key}.json"
    try:
        engine.save_state(state_path)
        if is_first_snapshot:
            logging.info("[market_snapshot] saved engine state for %s (first snapshot of process)", key)
    except Exception as exc:
        logging.warning("[market_snapshot] failed to save engine state for %s: %s", key, exc)


def reset_persistent_engines() -> None:
    """Clear all cached DecisionEngines.  Called by tests to prevent
    state leakage between test cases that run in the same process.
    """
    _decision_engines.clear()
    _snapshot_counter.clear()



# Timestamp of the last missed-trade resolution attempt (module-level).
_last_missed_resolution_at: float = 0.0
_MISSED_RESOLUTION_INTERVAL_SEC = 60  # resolve once per minute

# ── MT5 deal history tracking ──────────────────────────────────
# On each snapshot, we check MT5's deal history for positions that
# were closed externally (broker TP/SL execution).  This catches
# closes that happen outside the Python process — the broker fills
# the TP/SL order directly and the Python process never sees it.
#
# The check is throttled to once per 30 seconds per symbol to avoid
# hammering the MT5 API on every Refresh click.
_last_mt5_deal_check: dict[str, float] = {}
_MT5_DEAL_CHECK_INTERVAL_SEC = 30
_MT5_DEAL_HISTORY_HOURS = 24  # look back 24 hours for closed deals

# ── Label source tracking ──────────────────────────────────────
# Counts how many replay buffer samples came from each priority source.
# This lets the Pipeline Diagnostics panel show whether the model is
# learning from real trades (feedback/outcome) vs price movement estimates.
_label_source_counts: dict[str, int] = {
    "feedback": 0,       # Priority 1: signal feedback tracker (tp_hit/sl_hit)
    "outcome": 0,        # Priority 2: missed trade tracker (resolved after 6h)
    "delayed_price": 0,  # Priority 3: CSV-derived ATR price movement
    "mt5_deal": 0,       # MT5 deal history (broker fills)
    "skipped": 0,        # No label available — sample skipped
}


def _check_mt5_deal_history() -> None:
    """Query MT5's deal history for recently closed positions.

    Catches positions that were closed externally by the broker
    (TP/SL execution) — the Python process never saw the close.
    Records the outcomes into calibration_outcomes.jsonl so the
    model learns from real trade results.

    Throttled to once per _MT5_DEAL_CHECK_INTERVAL_SEC per symbol.
    """
    global _last_mt5_deal_check
    now = time.time()
    if not is_mt5_configured():
        return

    # Check each symbol
    for symbol in ("R_75", "R_100"):
        last_check = _last_mt5_deal_check.get(symbol, 0.0)
        if (now - last_check) < _MT5_DEAL_CHECK_INTERVAL_SEC:
            continue
        _last_mt5_deal_check[symbol] = now

        try:
            _check_symbol_deal_history(symbol)
        except Exception as exc:
            logging.debug("[mt5_deal_history] Failed to check %s: %s", symbol, exc)


def _check_symbol_deal_history(symbol: str) -> None:
    """Check MT5 deal history for one symbol and record outcomes."""
    import MetaTrader5 as mt5
    from datetime import datetime, timedelta, timezone

    # Initialize MT5 briefly to query deal history
    from synthetic_trader.execution.mt5_data import (
        _resolve_mt5_terminal_path,
        mt5_config_from_env,
    )

    terminal_path = _resolve_mt5_terminal_path()
    if not terminal_path:
        return

    cfg = mt5_config_from_env()
    login = int(cfg["login"])
    password = cfg.get("password") or ""
    server = cfg.get("server") or ""

    # Quick init + login (reuse connection if already open)
    initialized = mt5.initialize(path=terminal_path, timeout=5000)
    if not initialized:
        return

    try:
        mt5.login(login, password=password, server=server)
    except Exception:
        pass  # may already be logged in

    try:
        # Resolve the MT5 venue symbol
        from synthetic_trader.execution.mt5_data import _resolve_mt5_symbol
        venue_symbol = _resolve_mt5_symbol(symbol, mt5)

        # Get deals from the last N hours
        date_from = datetime.now(timezone.utc) - timedelta(hours=_MT5_DEAL_HISTORY_HOURS)
        date_to = datetime.now(timezone.utc)

        deals = mt5.history_deals_get(
            date_from=date_from,
            date_to=date_to,
            group=f"*{venue_symbol}*",
        )
        if deals is None or len(deals) == 0:
            return

        # Filter for close deals (entry=False means it's an exit deal)
        close_deals = [d for d in deals if not d.get("entry", True)]
        if not close_deals:
            return

        # Read the signal feedback tracker to find matching executed signals
        tracker = _get_signal_feedback_tracker()
        all_signals = tracker.get_all_signals(limit=50)

        outcomes_path = Path("data/calibration_outcomes.jsonl")
        recorded_count = 0

        for deal in close_deals:
            deal_time = deal.get("time", 0)
            deal_price = float(deal.get("price", 0))
            deal_profit = float(deal.get("profit", 0))
            deal_volume = float(deal.get("volume", 0))
            deal_comment = str(deal.get("comment", ""))

            if deal_price <= 0 or deal_volume <= 0:
                continue

            # Find a matching executed signal (not yet resolved)
            matched_signal = None
            for sig in all_signals:
                if sig.symbol != symbol:
                    continue
                if sig.outcome is not None:
                    continue  # already resolved
                if sig.executed_at is None:
                    continue  # not executed yet

                # Match by time proximity (deal should be after execution)
                try:
                    exec_dt = datetime.fromisoformat(
                        sig.executed_at.replace("Z", "+00:00")
                    )
                    exec_epoch = exec_dt.timestamp()
                    # Deal should be within 12 hours of execution
                    if abs(deal_time - exec_epoch) > 12 * 3600:
                        continue
                except (ValueError, TypeError):
                    continue

                # Determine outcome from profit
                if deal_profit > 0:
                    outcome = "tp_hit"
                    label = 1
                elif deal_profit < 0:
                    outcome = "sl_hit"
                    label = 0
                else:
                    outcome = "manual_win" if deal_profit >= 0 else "manual_loss"
                    label = 1 if deal_profit >= 0 else 0

                # Record the outcome
                tracker.record_outcome(
                    signal_id=sig.signal_id,
                    outcome=outcome,
                    pnl_pips=deal_profit,
                )
                matched_signal = sig
                break

            # Also write directly to calibration_outcomes.jsonl
            # so the Python backend picks it up on next snapshot
            if matched_signal is not None or True:
                # Determine prediction from deal direction
                prediction = 0.7 if deal_profit > 0 else 0.3
                label = 1 if deal_profit > 0 else 0

                try:
                    with outcomes_path.open("a", encoding="utf-8") as f:
                        record = {
                            "signal_id": (
                                matched_signal.signal_id
                                if matched_signal
                                else f"mt5_deal_{deal.get('ticket', 'unknown')}"
                            ),
                            "symbol": symbol,
                            "prediction": prediction,
                            "label": label,
                            "outcome": "tp_hit" if deal_profit > 0 else "sl_hit",
                            "source": "mt5_deal_history",
                            "deal_ticket": deal.get("ticket"),
                            "deal_profit": deal_profit,
                            "deal_price": deal_price,
                            "recorded_at": time.strftime(
                                "%Y-%m-%dT%H:%M:%S", time.gmtime()
                            ),
                        }
                        f.write(json.dumps(record) + "\n")
                    recorded_count += 1
                except Exception:
                    pass

        if recorded_count > 0:
            logging.info(
                "[mt5_deal_history] Recorded %d closed deal outcomes for %s",
                recorded_count, symbol,
            )

    finally:
        # Don't shutdown — just let the process clean up
        pass


def _get_atr_14(features: dict[str, float]) -> float:
    """Extract ATR_14 from features, falling back to 1.0."""
    return features.get("atr_14", 1.0)


# ── Outcome-based replay buffer labeling ────────────────────────
# CRITICAL: Labels come ONLY from real trade outcomes — never from
# the model's own prediction.  The old approach used
# model_long_probability to determine direction, creating a
# self-reinforcing feedback loop where the model confirmed itself.
#
# Sources (in priority order):
# 1. Signal feedback tracker — tp_hit/manual_win → 1, sl_hit/manual_loss → 0
# 2. Missed trade tracker — resolved after 6 hours by checking CSV prices
# 3. MT5 deal history — broker fills caught by _check_mt5_deal_history()
#
# We intentionally do NOT use delayed price movement with model
# prediction as a fallback because that would reintroduce the
# self-reinforcing loop.

# Import here to avoid circular imports at module level
from synthetic_trader.journal.signal_feedback import (
    SignalFeedbackTracker,
    make_signal_id,
)

# Module-level signal feedback tracker
_signal_feedback_tracker: SignalFeedbackTracker | None = None


def _get_signal_feedback_tracker() -> SignalFeedbackTracker:
    """Get or create the signal feedback tracker singleton."""
    global _signal_feedback_tracker
    if _signal_feedback_tracker is None:
        from pathlib import Path
        _signal_feedback_tracker = SignalFeedbackTracker(
            feedback_path=Path("data/signal_feedback.jsonl"),
            outcomes_path=Path("data/signal_outcomes.jsonl"),
            resolution_minutes=360,  # 6 hours
        )
    return _signal_feedback_tracker


def _compute_outcome_label(
    *,
    symbol: str,
    features: dict[str, float] | None = None,
) -> tuple[int | None, str]:
    """Compute an outcome-based label for the replay buffer.

    Returns (label, source) where:
      - label is 1 (bullish), 0 (bearish), or None (skip)
      - source is one of: 'feedback', 'outcome', 'delayed_price', 'skipped'

    IMPORTANT: This function NEVER uses model_long_probability.
    Labels come exclusively from:
    1. Signal feedback tracker — tp_hit/manual_win → 1, sl_hit/manual_loss → 0
    2. Missed trade tracker — resolved after 6 hours
    3. Delayed price movement using CSV-derived ATR (not model prediction)

    The delayed price movement uses the ACTUAL ATR from the feature
    snapshot (CSV-derived), not a hardcoded default.  This ensures
    R_100 (ATR ~2.5) and R_75 (ATR ~15) both get correct labels
    based on their real volatility.
    """

    # ── Priority 1: Signal feedback tracker ───────────────────────
    # Check if we have a recent signal with user feedback
    tracker = _get_signal_feedback_tracker()
    recent_signals = tracker.get_all_signals(limit=10)

    for signal in recent_signals:
        if signal.symbol != symbol:
            continue
        if signal.outcome is None:
            continue

        # Use the outcome if it's recent (within 6 hours)
        from datetime import datetime
        try:
            gen_dt = datetime.fromisoformat(signal.generated_at.replace("Z", "+00:00"))
            elapsed_hours = (time.time() - gen_dt.timestamp()) / 3600
            if elapsed_hours > 6:
                continue  # Too old
        except (ValueError, TypeError):
            continue

        # Use user feedback if available, otherwise outcome
        if signal.user_feedback == "good" and signal.outcome in ("tp_hit", "manual_win"):
            return (1, "feedback")
        if signal.user_feedback == "bad" and signal.outcome in ("sl_hit", "manual_loss"):
            return (0, "feedback")
        if signal.outcome in ("tp_hit", "manual_win"):
            return (1, "feedback")
        if signal.outcome in ("sl_hit", "manual_loss"):
            return (0, "feedback")
        # Expired — use pnl direction
        if signal.pnl_pips is not None:
            return (1 if signal.pnl_pips > 0 else 0, "feedback")

    # ── Priority 2: Missed trade tracker ──────────────────────────
    # Check for recently resolved missed trades
    outcomes_path = Path("data/missed_trade_outcomes.jsonl")
    if outcomes_path.exists():
        try:
            import json
            for line in outcomes_path.read_text(encoding="utf-8").splitlines()[-20:]:
                if not line.strip():
                    continue
                outcome = json.loads(line)
                if outcome.get("symbol") != symbol:
                    continue
                resolved_at = outcome.get("resolved_at", 0)
                if time.time() - resolved_at > 3600:  # 1 hour max
                    continue
                # outcome=1 means missed opportunity (price moved in predicted direction)
                # outcome=0 means correctly stayed out
                return (outcome.get("outcome", 0), "outcome")
        except Exception:
            pass

    # ── Priority 3: Delayed price movement (CSV-derived ATR) ────
    # If no feedback or missed trade data, check whether price moved
    # significantly in EITHER direction using the real ATR from the
    # feature snapshot.  This is NOT self-reinforcing because we don't
    # use model_long_probability to determine direction — we check
    # BOTH directions and label based on actual movement.
    if features is None:
        return None
    atr = features.get("atr_14", 0.0)
    if atr <= 0:
        return None

    ticks = _load_csv_ticks(symbol, max_ticks=1000)
    if not ticks or len(ticks) < 100:
        return None

    # Use the last 6 hours of ticks
    now = time.time()
    six_hours_ago = now - 6 * 3600
    recent_ticks = [t for t in ticks if t.epoch >= six_hours_ago]
    if len(recent_ticks) < 50:
        return None

    start_price = recent_ticks[0].price
    end_price = recent_ticks[-1].price
    max_price = max(t.price for t in recent_ticks)
    min_price = min(t.price for t in recent_ticks)

    # Check BOTH directions — no model prediction involved
    max_up = max_price - start_price
    max_down = start_price - min_price

    # Strong directional move: price moved >= 1 ATR in one direction
    if max_up >= atr and max_up > max_down * 1.5:
        return (1, "delayed_price")  # Bullish — price moved up strongly
    if max_down >= atr and max_down > max_up * 1.5:
        return (0, "delayed_price")  # Bearish — price moved down strongly

    # Moderate directional move: price ended significantly different
    if end_price > start_price + atr * 0.5:
        return (1, "delayed_price")
    if end_price < start_price - atr * 0.5:
        return (0, "delayed_price")

    # No significant movement — skip this sample
    return (None, "skipped")


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


def _maybe_resolve_feedback_outcomes(decision_engine: DecisionEngine) -> None:
    """Resolve signal feedback outcomes and feed into calibration.

    Reads the calibration_outcomes.jsonl file written by the Next.js API
    and feeds each (prediction, label) pair into the decision engine's
    calibration buffer. This closes the learning loop:
    signal generated → user rates → outcome resolved → calibration updated.
    """
    outcomes_path = Path("data/calibration_outcomes.jsonl")
    if not outcomes_path.exists():
        return
    try:
        lines = outcomes_path.read_text(encoding="utf-8").splitlines()
        fed = 0
        new_lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("fed_to_calibration"):
                    new_lines.append(line)
                    continue
                prediction = record.get("prediction", 0.5)
                label = record.get("label")
                if label is None:
                    new_lines.append(line)
                    continue
                decision_engine.update_calibration(float(prediction), int(label))
                record["fed_to_calibration"] = True
                record["fed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
                new_lines.append(json.dumps(record))
                fed += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                new_lines.append(line)
                continue
        if fed > 0:
            outcomes_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            logging.info(
                "[feedback] Fed %d resolved outcomes into calibration buffer",
                fed,
            )
    except Exception as exc:
        logging.debug("[feedback] Failed to resolve feedback outcomes: %s", exc)


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

    # Also resolve signal feedback outcomes and feed into calibration
    _maybe_resolve_feedback_outcomes(decision_engine)

    # Also check MT5 deal history for external closes
    _check_mt5_deal_history()

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
    # Live call geometry: "band" (default — zero-drawdown stop/target from
    # the calibrated EGARCH band, 1-3h hold) or "sniper" (legacy SMC swing
    # levels, kept as a research mode).  The SMC sniper's 3-3.5R targets were
    # shown unreachable (9-18% moves vs ~3-5% calibrated 6h bands), so the
    # live default is band geometry; the guardian/cancel semantics of the
    # "sniper" trading mode itself are unchanged.
    geometry: str = "band"
    band_hold_horizon_sec: int = 7200
    # Override per-symbol max_stop_distance_pct when set.  None keeps
    # the symbol-level default; a float forces a mode-specific cap.
    max_stop_distance_pct: float | None = None


TRADING_MODE_PRESETS = {
    # Default live mode.  The trading-mode string stays "sniper" so the
    # guardian's cancel thresholds and the engine's swing branch are
    # unchanged, but the call GEOMETRY is now the zero-drawdown band
    # (target/stop from the calibrated EGARCH forecast over 1-3h) instead of
    # the SMC 3.5R levels that were provably unreachable.
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
        symbol_min_history_candles=20,
        symbol_min_primary_reward_risk=2.0,
        execution_mode="swing",
        # Band geometry runs on the 300s execution timeframe — the scale
        # where the fade entry + band levels were verified (21 trades,
        # +0.65R on the 9.5-day R_75 corpus).  The 900s scale had too few
        # bars for the vol-extension gate to fire.
        swing_execution_timeframe_sec=300,
        # Short-call horizon: the user trades 1-2h calls, not 4-6h swings.
        # The band signal's own hold is band_hold_horizon_sec (1h); this
        # profile field must match so no path leaks a 6h "hold" display.
        swing_hold_horizon_minutes=60,
        swing_take_profit_rr=3.5,
        geometry="band",
        band_hold_horizon_sec=3600,  # §38 sweep winner: 1h hold resolves calls 2x faster
        max_stop_distance_pct=0.06,  # wider cap for swing trades
    ),
    # Legacy SMC swing geometry (research only): the 3-3.5R structure
    # targets that motivated the band rebuild.  Keep available for
    # A/B research; do not trade it live until it proves positive
    # expectancy at the Stage-3 gate.
    "sniper_legacy": TradingModePreset(
        confidence_above=0.50,
        confidence_near=0.42,
        bias_buy_threshold=0.52,
        bias_sell_threshold=0.48,
        risk_min_confidence=0.42,
        risk_min_reward_risk=2.0,
        risk_max_volatility_z=3.0,
        model_decision_threshold=0.50,
        confidence_relaxation=0.10,
        symbol_min_history_candles=20,
        symbol_min_primary_reward_risk=2.0,
        execution_mode="swing",
        swing_execution_timeframe_sec=900,
        swing_hold_horizon_minutes=360,
        swing_take_profit_rr=3.5,
        geometry="sniper",
        max_stop_distance_pct=0.06,
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
                    "geometry",
                    "band_hold_horizon_sec",
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
            geometry=preset.geometry,
            band_hold_horizon_sec=preset.band_hold_horizon_sec,
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
    # Sniper-only mode: always use sniper preset regardless of input.
    preset = TRADING_MODE_PRESETS["sniper"]
    return build_mode_config(TraderConfig.default(), preset), GUARDIAN_PRESETS["sniper"], preset


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


def _resolve_venue() -> str:
    """Report the data venue the collectors will actually use.

    Mirrors the collectors' single-decision rule: MT5 when configured,
    Deriv otherwise.  The value is stamped onto every snapshot so the
    operator always knows which price scale the levels are on — there is
    deliberately no silent venue swap.
    """
    return "mt5" if is_mt5_configured() else "deriv"


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
    # The venue is chosen ONCE by configuration and is NEVER silently
    # swapped mid-flight:
    #   * MT5 configured  → MT5 ONLY.  A failure here is a hard error — the
    #     system refuses to hand back Deriv 1HZ-scale prices (~7,000 for
    #     R_75) as a "fallback" when the Blueberry terminal is down.  The
    #     caller (run_live_snapshot) turns the exception into an honest
    #     stand-aside so the operator knows the broker link is down.
    #   * MT5 not configured → Deriv WebSocket is the explicit venue.
    # The caller stamps the resulting snapshot with the venue so the
    # operator always knows which price scale the levels are on.
    config = TraderConfig.default()
    required_history_ticks = _required_snapshot_history_ticks(
        symbol=symbol,
        warmup_count=warmup_count,
        config=config,
    )

    if is_mt5_configured() and client_factory is None:
        async with Mt5TickClient() as client:
            collected = await _collect_from_client(
                client, symbol, required_history_ticks, max_live_ticks
            )
        return sorted(collected, key=lambda item: item.epoch)

    # Deriv WebSocket — the explicitly configured venue when MT5 is not.
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


def _stop_traded_on_closed_candle(
    *,
    direction_bias: str,
    stop: float | None,
    ticks: list[Tick],
    timeframe_sec: int,
    since_epoch: float | None = None,
    lookback_candles: int = 2,
) -> bool:
    """True when a CLOSED candle of the execution timeframe traded through the stop.

    Ticks are bucketed into ``timeframe_sec`` windows; the currently-forming
    (latest) bucket is EXCLUDED — only completed candles count.  This is the
    stop-lock grace: a spread/jitter wick inside the forming candle cannot
    cancel a confirmed swing plan.  The stop must be confirmed by a full
    closed candle before the plan is invalidated.

    When ``since_epoch`` is given (the plan's confirmation time), ALL closed
    candles that opened at or after it are considered — a genuine stop
    confirmed by any closed candle during the plan's life cancels, even if no
    evaluation ran for a while and price later recovered.  Without it, only
    the last ``lookback_candles`` closed candles are considered (for brand-new
    plans with no confirmation time yet).
    """
    if stop is None or not ticks or timeframe_sec <= 0:
        return False
    buckets: dict[int, list[float]] = {}
    for tick in ticks:
        key = int(tick.epoch // timeframe_sec)
        buckets.setdefault(key, []).append(tick.price)
    if len(buckets) < 2:
        return False  # no closed candle yet
    closed_keys = sorted(buckets.keys())[:-1]  # drop the forming candle
    if since_epoch is not None:
        # Only candles that OPENED after the plan was confirmed.  A candle
        # already forming before confirmation is given the benefit of the
        # doubt (its breach may predate the plan).
        recent = [key for key in closed_keys if key * timeframe_sec >= since_epoch]
    else:
        recent = closed_keys[-lookback_candles:]
    if direction_bias == "buy":
        return any(min(buckets[key]) <= stop for key in recent)
    if direction_bias == "sell":
        return any(max(buckets[key]) >= stop for key in recent)
    return False


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
    trading_mode: str = "sniper",
    guardian_memory_dir: str | Path | None = None,
) -> dict[str, object]:
    current_close = ticks[-1].price if ticks else snapshot.get("current_close")
    enriched = dict(snapshot)
    enriched["current_close"] = current_close

    # Sniper-only mode: full microstructure evaluation with
    # conservative swing-trade thresholds.

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

    # ── Guardian memory: carry confirmed plans across refreshes ──────────
    # Every /api/calls/run spawns a fresh subprocess, so the in-process
    # tracker above starts empty each refresh.  Restore the persisted
    # wall-clock state when the freshly regenerated plan is the SAME plan
    # (same direction + levels within tolerance): a confirmed swing plan
    # stays confirmed until its lock expires — it must not flip to a fresh
    # "actionable" evaluation (or worse, cancel on a transient dip) just
    # because the user hit refresh.
    memory = _load_guardian_memory(symbol_key, guardian_memory_dir)
    if previous_guardian_state in (None, "") and memory is not None:
        if memory.get("state") == "confirmed" and _plan_matches(
            memory,
            direction=signal_snapshot.direction_bias,
            entry=signal_snapshot.entry,
            stop=signal_snapshot.stop_loss,
            target=signal_snapshot.take_profit,
        ):
            confirmed_at = float(memory.get("first_confirmed_at_epoch") or 0.0)
            lock_seconds = float(memory.get("lock_seconds") or 0.0)
            if confirmed_at and (time.time() - confirmed_at) < lock_seconds:
                # Sentinels: the sniper-stable path only needs the previous
                # state to read 'confirmed' with a non-None confirmation tick.
                previous_guardian_state = "confirmed"
                _guardian_confirmed_at_tick[symbol_key] = 1
                first_confirmed_at_tick = 1

    # Reset the confirmed tick tracker when the symbol or trade changes
    if previous_guardian_state is None or previous_guardian_state == "forming":
        _guardian_confirmed_at_tick.pop(symbol_key, None)
        first_confirmed_at_tick = None

    # Read confidence from the snapshot for dynamic lock duration
    current_confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    confidence_at_confirmation: float | None = None
    if previous_guardian_state == "confirmed" and first_confirmed_at_tick is not None:
        # Preserve the confidence level from when the signal was first confirmed
        confidence_at_confirmation = float(snapshot.get("confidence_at_confirmation", 0.0) or 0.0) or None

    # ── Stop-lock grace: was the stop confirmed by a CLOSED execution candle?
    # Only completed execution-timeframe candles count — an intraday
    # spread/jitter wick inside the still-forming candle cannot stop out a
    # confirmed swing plan.  The evaluation consumes this flag so a stop
    # trade-through only cancels once a full candle confirms it.
    # The sniper execution timeframe is 900s (swing_execution_timeframe_sec);
    # the snapshot may carry an override.
    execution_tf = int(snapshot.get("execution_timeframe_sec") or 900)
    # Bound the closed-candle check by the plan's confirmation time when a
    # confirmed plan already exists (so a genuine stop confirmed by any closed
    # candle since confirmation cancels, even if no evaluation ran for a while).
    _since = None
    if memory is not None and memory.get("state") == "confirmed":
        try:
            _confirmed_at = float(memory.get("first_confirmed_at_epoch") or 0.0)
        except (TypeError, ValueError):
            _confirmed_at = 0.0
        if _confirmed_at > 0 and _plan_matches(
            memory,
            direction=signal_snapshot.direction_bias,
            entry=signal_snapshot.entry,
            stop=signal_snapshot.stop_loss,
            target=signal_snapshot.take_profit,
        ):
            _since = _confirmed_at
    stop_on_closed_candle = _stop_traded_on_closed_candle(
        direction_bias=signal_snapshot.direction_bias,
        stop=signal_snapshot.stop_loss,
        ticks=ticks,
        timeframe_sec=execution_tf,
        since_epoch=_since,
    )
    # Closed-candle trade-through of the ENTRY (breakeven) — used by the
    # guardian's breakeven trail once the plan has moved to breakeven.
    entry_on_closed_candle = (
        _stop_traded_on_closed_candle(
            direction_bias=signal_snapshot.direction_bias,
            stop=signal_snapshot.entry,
            ticks=ticks,
            timeframe_sec=execution_tf,
            since_epoch=_since,
        )
        if signal_snapshot.entry is not None
        else None
    )

    guardian = evaluate_signal_guardian(
        signal_snapshot,
        GuardianContext(
            tick_prices=prices,
            ticks_since_armed=len(prices),
            max_favorable_excursion=max_favorable_excursion,
            max_adverse_excursion=max_adverse_excursion,
            previous_guardian_state=previous_guardian_state,
            first_confirmed_at_tick=first_confirmed_at_tick,
            confidence_at_confirmation=confidence_at_confirmation,
            current_confidence=current_confidence,
            atr_14=snapshot.get("atr_14") if isinstance(snapshot.get("atr_14"), (int, float)) else None,
            trading_mode=trading_mode,
            execution_timeframe_sec=execution_tf,
            stop_traded_on_closed_candle=stop_on_closed_candle,
            entry_traded_on_closed_candle=entry_on_closed_candle,
        ),
        thresholds,
    )

    # ── Cancelled-stick: a stopped-out plan must not resurrect on refresh ─
    # If the SAME plan was cancelled earlier (stop trade-through), a refresh
    # must not re-issue it just because the evaluation loop would re-confirm
    # a recovered window.  The stick holds until the strategy produces a
    # materially different plan (signature mismatch → fresh state).
    if (
        guardian.state == "confirmed"
        and memory is not None
        and memory.get("state") == "cancelled"
        and _plan_matches(
            memory,
            direction=signal_snapshot.direction_bias,
            entry=signal_snapshot.entry,
            stop=signal_snapshot.stop_loss,
            target=signal_snapshot.take_profit,
        )
    ):
        guardian = GuardianEvaluation(
            "cancelled",
            "Previous cancellation stands — a stopped-out plan is not re-issued; wait for a fresh setup.",
        )

    enriched["guardian_state"] = guardian.state
    enriched["guardian_reason"] = guardian.reason
    # Wire trailing stop recommendation into the snapshot so the
    # execution layer can use it to modify orders on MT5.
    if guardian.recommended_stop is not None:
        enriched["recommended_stop"] = guardian.recommended_stop

    # Record the tick and confidence when the guardian first reaches 'confirmed'
    if guardian.state == "confirmed" and symbol_key not in _guardian_confirmed_at_tick:
        _guardian_confirmed_at_tick[symbol_key] = len(prices)
        # Store the confidence at confirmation time for dynamic lock duration
        enriched["confidence_at_confirmation"] = current_confidence

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

    # ── Persist guardian memory (wall-clock) ────────────────────────────
    # Only real live plans (snapshot carries a candidate call + levels) are
    # persisted, so test fixtures and stand_aside reads never write memory.
    # Confirmed plans survive refreshes; cancelled plans stick; anything else
    # (forming/unavailable/actionable with a different plan) clears the file
    # so a new plan starts fresh.
    if snapshot.get("call") in ("buy_candidate", "sell_candidate") and signal_snapshot.entry is not None:
        try:
            effective_lock_ticks = _effective_confirmed_lock_ticks(
                thresholds, current_confidence or confidence_at_confirmation
            )
            hold_horizon = float(snapshot.get("hold_horizon_minutes") or 60)
            now = time.time()
            trigger_type = str(
                snapshot.get("execution_trigger_type") or snapshot.get("alert_type") or ""
            )
            if guardian.state == "confirmed":
                existing = _load_guardian_memory(symbol_key, guardian_memory_dir)
                first_confirmed = now
                if existing and existing.get("state") == "confirmed":
                    try:
                        first_confirmed = float(existing.get("first_confirmed_at_epoch") or now)
                    except (TypeError, ValueError):
                        first_confirmed = now
                _save_guardian_memory(
                    symbol_key,
                    {
                        "symbol": symbol_key,
                        "direction": signal_snapshot.direction_bias,
                        "entry": signal_snapshot.entry,
                        "stop": signal_snapshot.stop_loss,
                        "target": signal_snapshot.take_profit,
                        "call": str(snapshot.get("call")),
                        "trigger_type": trigger_type,
                        "state": "confirmed",
                        "first_confirmed_at_epoch": first_confirmed,
                        "lock_seconds": effective_lock_ticks * 5,  # 5s ticks, matching the documented lock design
                        "confidence_at_confirmation": (
                            existing.get("confidence_at_confirmation")
                            if existing and existing.get("state") == "confirmed"
                            else current_confidence
                        ),
                        "issued_at_epoch": (
                            float(existing["issued_at_epoch"])
                            if existing and existing.get("issued_at_epoch")
                            else now
                        ),
                        "hold_horizon_minutes": hold_horizon,
                    },
                    guardian_memory_dir,
                )
            elif guardian.state == "cancelled":
                _save_guardian_memory(
                    symbol_key,
                    {
                        "symbol": symbol_key,
                        "direction": signal_snapshot.direction_bias,
                        "entry": signal_snapshot.entry,
                        "stop": signal_snapshot.stop_loss,
                        "target": signal_snapshot.take_profit,
                        "call": str(snapshot.get("call")),
                        "trigger_type": trigger_type,
                        "state": "cancelled",
                        "cancelled_at_epoch": now,
                        "hold_horizon_minutes": hold_horizon,
                    },
                    guardian_memory_dir,
                )
            else:
                # Only clear the previous plan when the strategy has actually
                # moved on to a DIFFERENT plan.  A same-plan evaluation that
                # is momentarily 'actionable' (not yet re-confirmed) must NOT
                # erase the memory — otherwise the 'stand by the call'
                # guarantee silently dies mid-hold for the next stand_aside.
                existing = _load_guardian_memory(symbol_key, guardian_memory_dir)
                if not _plan_matches(
                    existing,
                    direction=signal_snapshot.direction_bias,
                    entry=signal_snapshot.entry,
                    stop=signal_snapshot.stop_loss,
                    target=signal_snapshot.take_profit,
                ):
                    _clear_guardian_memory(symbol_key, guardian_memory_dir)
        except Exception as exc:
            logging.debug("[market_snapshot] guardian memory persist failed: %s", exc)

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


def build_watch_alert(
    snapshot: dict[str, object],
    *,
    guardian_memory_dir: str | Path | None = None,
) -> dict[str, object]:
    """Convert a raw snapshot dict into a JSON-serializable alert dict.

    This is the bridge between the Python engine and the Next.js frontend.
    It enriches the snapshot with alert_type and decision_summary fields
    that the frontend's ``mapLiveSnapshot`` function expects.

    Called by the engine bridge's ``executePythonSnapshot`` after
    ``run_live_snapshot`` returns.
    """
    alert = dict(snapshot)
    # Stage-3 gate FIRST: replace raw model confidence with the market-verified
    # target-hit rate + horizon verdict, and downgrade suppressed call types
    # to stand_aside (or annotate in ``annotate`` mode).  Best-effort; never
    # raises.  Runs before alert_type/decision_summary so those derived fields
    # reflect the gated call (e.g. a suppressed candidate renders as
    # stand_aside, not setup_candidate).
    alert = apply_stage3_gate(alert)
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
    # ── Stand by the call: restore a held confirmed plan ────────────────
    # When the fresh run produced no valid plan (stand_aside / context
    # update) but a confirmed plan is still alive in guardian memory — the
    # stop hasn't been traded through and the hold horizon hasn't expired —
    # keep showing the ORIGINAL call instead of dropping the plan.  The user
    # entered on this call and expects it to stand until invalidation.
    _restore_held_plan(alert, guardian_memory_dir)
    # ── EA handoff (opt-in): write the approved call to the MQL5 executor ──
    # When SYNTH_EA_EMIT=1, a proven buy/sell candidate is written to the MT5
    # Common Files folder where the SynthCallExecutor EA polls it and places
    # the order natively.  Best-effort and never raises — the dashboard must
    # not break because the EA folder is unreachable.
    _maybe_emit_ea_call(alert)
    return alert


def _maybe_emit_ea_call(alert: dict[str, object]) -> None:
    """Write a proven call to the EA folder when SYNTH_EA_EMIT=1.

    The call is emitted only when the Stage-3 gate says the call type is
    market-proven (``evidence_status == "proven"`` and
    ``execution_allowed``).  Volume comes from ``SYNTH_EA_VOLUME`` (default
    0.2) scaled by the empirical ``size_multiplier`` from the gate.  The
    venue symbol resolves through the same ``SYNTHETIC_MT5_SYMBOL_MAP`` env
    the collector uses (R_75 -> SYN75 on Blueberry).
    """
    if os.getenv("SYNTH_EA_EMIT") != "1":
        return
    try:
        from synthetic_trader.execution.ea_emitter import emit_call_from_alert

        symbol = str(alert.get("symbol") or "")
        if not symbol:
            return
        venue_symbol = _ea_venue_symbol(symbol)
        base_volume = float(os.getenv("SYNTH_EA_VOLUME", "0.2"))
        try:
            base_volume *= float(alert.get("size_multiplier") or 1.0)
        except (TypeError, ValueError):
            pass
        emit_call_from_alert(
            alert,
            symbol=symbol,
            venue_symbol=venue_symbol,
            volume=max(base_volume, 0.0),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logging.debug("[ea_emitter] live emit skipped: %s", exc)


def _ea_venue_symbol(symbol: str) -> str:
    """Resolve R_75/R_100 to the broker venue symbol (SYN75/SYN100)."""
    configured = os.getenv("SYNTHETIC_MT5_SYMBOL_MAP")
    if configured:
        try:
            mapping = dict(item.split(":", 1) for item in configured.split(","))
            if symbol in mapping:
                return mapping[symbol]
        except Exception:
            pass
    return "SYN75" if symbol == "R_75" else "SYN100"


def _band_gate_state(
    symbol: str,
    execution_candles: list[object],
    hold_horizon_sec: int,
) -> dict[str, object]:
    """Report why the live band strategy is standing aside (operator visibility).

    Mirrors ``decision_engine._live_band_signal`` exactly — same config
    kwargs, same re-validation overlays, same calibrated GARCH state — so the
    numbers shown are precisely what the live signal decision used.  Surfaced
    in the operator payload as ``band_gate`` so the dashboard can show "how
    close" the market is to a call (vol ratio, displacement, warmup) instead
    of a bare "No trade yet".
    """
    try:
        if not execution_candles or len(execution_candles) < 60:
            return {
                "candles": len(execution_candles) if execution_candles else 0,
                "needed_candles": 60,
                "warmup_ok": False,
                "vol_ratio": None,
                "vol_extended": False,
                "z_dev": None,
                "z_entry": 1.0,
                "waiting_on": "candle history",
            }
        from synthetic_trader.backtest.vol_band import VolBandConfig, VolBandStrategy
        from synthetic_trader.models.garch_calibration import load_calibrated_garch_state
        from synthetic_trader.research.band_revalidate import load_live_band_overrides

        band_kwargs: dict = {
            "max_hold_sec": hold_horizon_sec,
            "breakeven_trail_frac": 0.3,
        }
        overrides, _artifact = load_live_band_overrides(symbol)
        band_kwargs.update(overrides)

        strategy = VolBandStrategy(
            symbol,
            execution_candles[0].timeframe_sec,
            config=VolBandConfig(**band_kwargs),
            garch_state=load_calibrated_garch_state(symbol),
        )
        last: object | None = None
        for candle in execution_candles:
            emitted = strategy.on_candle(candle)
            if emitted is not None:
                last = emitted

        import math
        vol_ratio = None
        z_dev = None
        if strategy._sigma_ema and strategy._prev_sigma:
            vol_ratio = strategy._prev_sigma / strategy._sigma_ema
            if strategy._ema:
                z_dev = math.log(
                    execution_candles[-1].close / strategy._ema
                ) / strategy._prev_sigma
        cfg = strategy.config
        waiting = []
        if strategy._candles_seen < cfg.warmup_candles:
            waiting.append("candle history")
        if vol_ratio is not None and vol_ratio <= cfg.vol_extended_ratio:
            waiting.append("vol spike")
        if z_dev is not None and abs(z_dev) < cfg.z_entry:
            waiting.append("displacement")
        if not waiting:
            waiting.append("drift cooldown / confirmation")
        return {
            "candles": strategy._candles_seen,
            "needed_candles": cfg.warmup_candles,
            "warmup_ok": strategy._candles_seen >= cfg.warmup_candles,
            "vol_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
            "vol_extended_ratio": cfg.vol_extended_ratio,
            "vol_extended": vol_ratio is not None and vol_ratio > cfg.vol_extended_ratio,
            "z_dev": round(z_dev, 3) if z_dev is not None else None,
            "z_entry": cfg.z_entry,
            "signal_emitted": last is not None,
            "waiting_on": ", ".join(waiting),
        }
    except Exception:
        # Best-effort visibility — never crash the snapshot over it.
        return {}


# Re-anchor a held plan's entry when the market has moved this far beyond it
# in the call's favor (as a fraction of the stop distance).  Half a stop
# distance is far past spread/noise — the original limit is effectively
# unreachable, so the plan should offer an enter-at-market level instead of
# a stale entry the operator can never fill.
HELD_PLAN_REANCHOR_FRACTION = 0.5


def _restore_held_plan(alert: dict[str, object], memory_dir: str | Path | None = None) -> None:
    """Restore a persisted confirmed plan when the fresh alert has none.

    Only fires when ALL of the following hold:
      * the fresh alert carries a current price (fresh market data — a stale
        or MT5-down read can never resurrect a plan);
      * guardian memory holds a ``confirmed`` plan for the symbol;
      * the call type isn't suppressed by the Stage-3 gate;
      * the hold horizon hasn't expired;
      * price has NOT traded through the stop (the plan's own invalidation).
    """
    symbol = str(alert.get("symbol", "") or "")
    if not symbol:
        return
    call = str(alert.get("call", "stand_aside"))
    if str(alert.get("trade_status", "not_valid")) == "valid" and call in ("buy_candidate", "sell_candidate"):
        return  # fresh valid plan — nothing to restore
    current_close = alert.get("current_close")
    if current_close is None:
        return  # no fresh market data
    memory = _load_guardian_memory(symbol, memory_dir)
    if memory is None or memory.get("state") != "confirmed":
        return
    # Never resurrect a call type the Stage-3 gate currently suppresses.
    # The fresh stand_aside alert has no candidate block of its own, so
    # re-run the gate on the HELD plan's (symbol, trigger_type).
    try:
        _candidate = {
            "symbol": symbol,
            "call": "buy_candidate" if memory.get("direction") == "buy" else "sell_candidate",
            "alert_type": "setup_candidate",
            "trigger_type": memory.get("trigger_type"),
            "execution_trigger_type": memory.get("trigger_type"),
        }
        _block = (apply_stage3_gate(_candidate).get("stage3") or {})
        if isinstance(_block, dict) and (
            _block.get("state") == "suppressed"
            or _block.get("evidence_status") == "suppressed"
        ):
            return
    except Exception:
        pass  # best-effort — a gate failure must not crash the restore path
    stage3 = alert.get("stage3") or {}
    if isinstance(stage3, dict) and (
        stage3.get("state") == "suppressed"
        or stage3.get("evidence_status") == "suppressed"
    ):
        return  # never resurrect a suppressed call type
    direction = memory.get("direction")
    entry = memory.get("entry")
    stop = memory.get("stop")
    target = memory.get("target")
    if direction not in ("buy", "sell") or entry is None or stop is None or target is None:
        return
    try:
        entry = float(entry)
        stop = float(stop)
        target = float(target)
        price = float(current_close)
    except (TypeError, ValueError):
        return
    now = time.time()
    issued_at = float(memory.get("issued_at_epoch") or 0.0)
    horizon_min = float(memory.get("hold_horizon_minutes") or 60)
    if issued_at and (now - issued_at) > horizon_min * 60:
        return  # hold horizon expired — the plan is over
    # The CURRENT print is the invalidation line here (not closed-candle
    # confirmation): if the latest price is through the stop, a real position
    # would have been stopped out, so a dead plan must never be restored.  The
    # stop-lock grace lives in the guardian's cancel decision, which already
    # ran on this same read (and would have written 'cancelled' to memory).
    if direction == "buy" and price < stop:
        return  # stop traded through — genuinely invalidated
    if direction == "sell" and price > stop:
        return
    # ── Re-anchor a ran-away entry (enter-at-market) ─────────────────
    # The plan's entry is the price at emission.  When the market has moved
    # BEYOND that entry in the call's favor by more than half a stop-distance,
    # the original entry is no longer reachable — a sell limit at 1,865 never
    # fills while price trades at 1,820 and keeps falling.  The direction may
    # have been right, but the stale entry silently costs the operator the
    # trade.  Re-anchor the plan to the CURRENT market price with identical
    # risk geometry (same stop distance, same target distance -> same R:R), so
    # the operator can enter at market instead of waiting for a retrace that
    # may never come.  Guardian memory is re-written so stop-lock/breakeven
    # invalidation tracks the levels the operator actually holds.
    stop_distance = abs(entry - stop) if stop != entry else 0.0
    target_distance = abs(target - entry) if target != entry else 0.0
    target_reached = (
        (direction == "sell" and price <= target)
        if target_distance > 0
        else False
    ) or (
        (direction == "buy" and price >= target)
        if target_distance > 0
        else False
    )
    moved_beyond_entry = (
        (direction == "sell" and price < entry - HELD_PLAN_REANCHOR_FRACTION * stop_distance)
        if stop_distance > 0
        else False
    ) or (
        (direction == "buy" and price > entry + HELD_PLAN_REANCHOR_FRACTION * stop_distance)
        if stop_distance > 0
        else False
    )
    reanchored = (
        moved_beyond_entry
        and not target_reached
        and stop_distance > 0
        and target_distance > 0
    )
    original_entry = entry
    if reanchored:
        entry = price
        if direction == "sell":
            stop = entry + stop_distance
            target = entry - target_distance
        else:
            stop = entry - stop_distance
            target = entry + target_distance
    # Restore the held plan.
    alert["call"] = "buy_candidate" if direction == "buy" else "sell_candidate"
    alert["trade_status"] = "valid"
    alert["direction_bias"] = direction
    alert["entry"] = entry
    alert["stop_loss"] = stop
    alert["take_profit"] = target
    alert["guardian_state"] = "confirmed"
    alert["alert_type"] = "setup_candidate"
    alert["plan_held"] = True
    alert["plan_issued_at"] = issued_at
    if reanchored:
        alert["entry_chased"] = True
        alert["original_entry"] = original_entry
        alert["entry_instruction"] = "market"
        alert["guardian_reason"] = (
            f"Market ran beyond the original entry — {original_entry:g} is now "
            f"unreachable (price {price:g}). Entry re-anchored to the current "
            f"price; enter at MARKET with the same risk geometry."
        )
        # Re-write guardian memory so invalidation watches the re-anchored
        # levels (best-effort — a memory write failure must not crash restore).
        try:
            _save_guardian_memory(
                symbol,
                {
                    **memory,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "original_entry": original_entry,
                    "reanchored_at_epoch": now,
                    "state": "confirmed",
                },
                memory_dir,
            )
        except Exception:
            pass
    else:
        alert["guardian_reason"] = (
            "Standing by the original call — plan held; invalidates only on stop trade-through or horizon expiry."
        )
    if stop != entry:
        alert["reward_risk"] = round(abs(target - entry) / abs(entry - stop), 3)
    alert.update(
        _format_trade_areas(
            entry,
            stop,
            target,
        )
    )
    if not alert.get("why") and alert.get("briefing"):
        alert["why"] = alert["briefing"]
    if not alert.get("decision_summary"):
        summary = build_decision_summary(alert)
        if summary:
            alert["decision_summary"] = summary


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
        # Live phase is a FRESHNESS check: the history page above already
        # carries the recent ~minutes of ticks (copy_ticks_from is ~30ms for
        # 5000), so the live subscription only needs to bridge to "now" and
        # prove the feed is moving.  A 2s budget collects ~10-20 fresh ticks
        # (the MT5 poll yields on every price change) — far faster than the
        # old 5s wait that dominated every dashboard read.
        seen_live_ticks = 0
        try:
            async for tick in client.subscribe_ticks(symbol, timeout=2.0):
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

    # Same venue rule as collect_live_snapshot_ticks: MT5-only when
    # configured (a failure propagates to run_live_watch's reconnect
    # handler — never a silent Deriv swap onto the wrong price scale),
    # otherwise Deriv WebSocket is the explicit venue.
    if is_mt5_configured() and client_factory is None:
        async with Mt5TickClient() as client:
            return await _watch_collect_from_client(
                client, symbol, max_live_ticks, max_minutes
            )

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
# Value: (csv_path, csv_mtime, (ticks, backfill_mtime)).
_csv_tick_cache: dict[str, tuple[Path, float, tuple[list[Tick], float]]] = {}

# Maximum age of CSV ticks considered valid for analysis.
# Ticks older than this threshold are filtered out in _load_csv_ticks().
# The band strategy replays the last MAX_FEATURE_HISTORY (400) execution
# candles so its EGARCH forecaster settles to the realized scale — 400 ×
# 300s = ~33h.  A 24h window starved it (the regime-aware stale paths shrink
# it further), which is why live could never reproduce its own backtest and
# calls never fired.  48h (172,800s) guarantees the full warm-up whenever
# the merged backfill corpus has that much history; the engine trims to the
# last 400 candles anyway.
MAX_TICK_AGE_SECONDS = 172_800  # 48 hours — full band forecaster warm-up
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

def _backfill_csv_mtime(symbol: str) -> float:
    """Return the mtime of data/backfill/{symbol}_ticks.csv (0.0 if absent).

    Used as part of the CSV cache signature so a growing backfill corpus
    invalidates the cached merged ticks exactly when the file changes.
    """
    path = Path("data/backfill") / f"{symbol}_ticks.csv"
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        return 0.0


def _load_csv_ticks(
    symbol: str,
    max_ticks: int = 200_000,
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
    # The backfill corpus mtime is part of the signature so a growing
    # data/backfill corpus invalidates the cache exactly when it changes.
    cached = _csv_tick_cache.get(symbol)
    if cached is not None and max_age_seconds is None:
        cached_path, cached_mtime, cached_ticks = cached
        backfill_mtime = _backfill_csv_mtime(symbol)
        if (
            cached_path == csv_path
            and csv_path.stat().st_mtime == cached_mtime
            and backfill_mtime == cached_ticks[1]
        ):
            return cached_ticks[0]

    # Rotate CSV if it exceeds the maximum line threshold (200K lines).
    # The analysis reads up to 200K ticks from the tail, so
    # keeping more than 200K lines on disk is wasteful and slows down reads.
    _rotate_csv(csv_path, max_lines=200_000)

    try:
        ticks = _read_tail_ticks(csv_path, symbol, max_ticks)
        # ── Backfill corpus merge (only when the live CSV is sparse) ──
        # The live CSV (data/{symbol}_ticks.csv) only holds bursts written
        # by on-demand live reads — it is NOT a continuous record, so on a
        # quiet morning the engine saw "need 20 candles, have 19" despite
        # 7 days of clean history sitting in data/backfill/.  Merge the
        # continuous M1 corpus in (same Blueberry SYN scale — verified by
        # the price sanity check downstream) so analysis always has full
        # candle history.  The live CSV wins on epoch ties (it is fresher).
        #
        # Optimization: if the live CSV alone already spans the full age
        # window, the backfill merge only re-reads ~100k duplicate rows and
        # rebuilds a 200k-entry epoch dict for data the age filter drops
        # anyway — ~3-4s of pure waste on every dashboard read.  Skip the
        # merge in that case; fall back to it only when the live tail is
        # short (recent live reads are sparse), so the quiet-morning
        # "need 20 candles" fix still applies.
        backfill_path = Path("data/backfill") / f"{symbol}_ticks.csv"
        live_span = (
            ticks[-1].epoch - ticks[0].epoch
            if len(ticks) > 1
            else 0.0
        )
        live_covers_window = live_span >= age_limit * 0.9
        if (
            not live_covers_window
            and backfill_path.exists()
            and backfill_path.resolve() != csv_path.resolve()
        ):
            backfill_ticks = _read_tail_ticks(backfill_path, symbol, max_ticks)
            if backfill_ticks:
                by_epoch = {tick.epoch: tick for tick in backfill_ticks}
                for tick in ticks:
                    by_epoch[tick.epoch] = tick
                ticks = sorted(by_epoch.values(), key=lambda item: item.epoch)
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
        _csv_tick_cache[symbol] = (csv_path, csv_path.stat().st_mtime, (ticks, _backfill_csv_mtime(symbol)))
        return ticks
    except Exception:
        import traceback
        traceback.print_exc()
        return None


def _read_tail_ticks(csv_path: Path, symbol: str, max_count: int) -> list[Tick]:
    """Read the last ``max_count`` ticks from a CSV file.

    Uses a tail-read strategy: reads backward from the end of the file
    in 256 KB chunks until we have ``max_count`` valid tick lines.
    With a 2x safety margin for blank lines / parse failures, 200K ticks
    needs ~16 MB (63 chunks).  The early-stop logic reads only what's
    needed — for fewer ticks, it stops well before the full file.
    """
    BUFFER_SIZE = 256 * 1024  # 256 KB
    AVG_BYTES_PER_LINE = 40
    # Estimate how many bytes we need for max_count lines.
    # Add a 2× safety margin for parse failures / blank lines.
    # No cap — the CSV rotation at 200K lines limits file size already.
    estimated_bytes = max_count * AVG_BYTES_PER_LINE * 2
    file_size = csv_path.stat().st_size
    if file_size <= 0:
        return []
    with csv_path.open("rb") as fh:
        fh.seek(0, 2)
        tail_chunks: list[bytes] = []
        accumulated = 0
        pos = file_size
        while pos > 0 and accumulated < estimated_bytes:
            read = min(BUFFER_SIZE, pos)
            pos -= read
            fh.seek(pos)
            data = fh.read(read)
            tail_chunks.append(data)
            accumulated += read
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
        role: histories.get(role_timeframe, [])[-MAX_FEATURE_HISTORY:]
        for role, role_timeframe in role_timeframes.items()
    }
    primary_candles = histories.get(timeframe_sec, [])[-MAX_FEATURE_HISTORY:]
    higher_timeframe_candles = histories.get(higher_timeframe_sec, [])[-MAX_FEATURE_HISTORY:]
    execution_candles = role_candles["execution"]
    confirmation_candles = role_candles["confirmation"]
    current_close = primary_candles[-1].close if primary_candles else (ticks[-1].price if ticks else None)

    regime = "unknown"
    regime_explanation = "need more candle history to classify the market"
    structure_summary = "structure still forming"
    model_long_probability = None

    # Use persistent DecisionEngine so calibration, regime detector,
    # and model weights carry over between snapshot calls.
    decision_engine = _get_persistent_decision_engine(
        symbol, mode, config=config, model=model,
    )

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
    # ── Feed replay buffer from live analysis ──────────────────────
    # Every snapshot evaluation produces features and a prediction.
    # We store these in the replay buffer so the model can learn from
    # live market data — not just backtest/paper outcomes.
    #
    # CRITICAL FIX: Previously used self-reinforcing labels where the
    # model's own prediction determined the label (prob > 0.5 → label=1).
    # This created a closed feedback loop that never improved.
    #
    # Now uses OUTCOME-BASED labels:
    # 1. If we have a recent signal with user feedback → use that
    # 2. If we have a resolved missed trade → use that outcome
    # 3. Otherwise → use delayed price movement (1 ATR in 6 hours)
    if primary_candles:
        try:
            _live_label, _label_source = _compute_outcome_label(
                symbol=symbol,
                features=dict(feature_snapshot.features) if primary_candles else None,
            )
            _label_source_counts[_label_source] = _label_source_counts.get(_label_source, 0) + 1
            if _live_label is not None:
                decision_engine.model.replay_buffer.add(
                    dict(feature_snapshot.features), _live_label
                )
        except Exception:
            pass  # best-effort — never crash the snapshot

    # Auto-save engine state to disk (throttled to every N snapshots)
    _maybe_save_engine_state(f"{symbol}_{mode}", decision_engine)
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
            "geometry": preset.geometry,
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
        # ── Band gate state (operator visibility) ───────────────
        # Why no call?  Attach the live band strategy's gate readout so the
        # dashboard shows vol ratio / displacement / warmup instead of a bare
        # "No trade yet".  Mirrors decision_engine._live_band_signal exactly.
        try:
            snapshot["band_gate"] = _band_gate_state(
                symbol,
                execution_candles,
                hold_horizon_sec=preset.band_hold_horizon_sec,
            )
        except Exception:
            pass  # best-effort visibility
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
        "geometry": preset.geometry,
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

    # The venue is decided ONCE, before any collection, so the corpus
    # append below can never mix scales: Deriv 1HZ ticks (~7,000 for
    # R_75) must NOT be appended into the Blueberry MT5 corpus (~1,850).
    # A snapshot subprocess whose env lost the MT5 vars would otherwise
    # silently run the Deriv path and pollute the compounding corpus
    # with 3.7x-wrong prices.
    snapshot_venue = _resolve_venue()

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
                result["venue"] = "csv"
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
            result["venue"] = "csv"
            _phases["total_ms"] = int((time.time() - _t_start) * 1000)
            result["phase_timing_ms"] = _phases
            return result

        _t_analysis = time.time()
        result = analyze_live_snapshot(
            symbol=symbol, ticks=ticks, timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            trading_mode=trading_mode, model=model,
        )
        result["venue"] = "csv"
        _phases["analysis_ms"] = int((time.time() - _t_analysis) * 1000)
        _phases["total_ms"] = int((time.time() - _t_start) * 1000)
        result["phase_timing_ms"] = _phases
        return result

    # NOTE: the top-level CSV load used to happen here (5s+ of the read
    # budget) but its result is only used in the MT5-failure fallback below.
    # In the happy path analyze_live_snapshot re-reads the CSV itself, so
    # loading it up front wasted ~5s on every dashboard read.  It is now
    # loaded lazily inside the fallback branch.
    csv_ticks = None

    try:
        _t_tick = time.time()
        # The collect budget must cover the hardened MT5 init (up to 3 full
        # portable passes × 10s + backoff for IPC-timeout recovery) plus the
        # tick read itself.  A 25s window was too tight: a slow-but-recovering
        # init (terminal busy, previous subprocess wedged the IPC) would blow
        # the whole budget and surface as "Bridge Offline" even though MT5
        # recovered a moment later.
        ticks = await asyncio.wait_for(
            collect_live_snapshot_ticks(
                symbol=symbol, warmup_count=warmup_count,
                max_live_ticks=max_live_ticks, app_id=app_id,
            ),
            timeout=45.0,
        )
        _phases["tick_collect_ms"] = int((time.time() - _t_tick) * 1000)

        _t_append = time.time()
        try:
            # ONLY append MT5-sourced ticks to the MT5 corpus.  When this
            # subprocess ran the Deriv path (MT5 env not visible here), the
            # collected ticks are on the Deriv 1HZ scale (~7,000 for R_75) —
            # appending them would corrupt the compounding Blueberry corpus
            # with ~3.7x-wrong prices (the exact corruption seen in
            # data/R_75_ticks.csv).  The scale guard in append_ticks_csv is
            # defense-in-depth; the venue gate is the root fix.
            if snapshot_venue == "mt5":
                csv_path = _resolve_csv_path(symbol)
                append_ticks_csv(csv_path, ticks)
            else:
                print(
                    f"[market_snapshot] venue={snapshot_venue}: skipping corpus append "
                    f"({len(ticks)} Deriv-scale ticks must not enter the MT5 corpus)",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception:
            pass
        _phases["append_csv_ms"] = int((time.time() - _t_append) * 1000)

        _t_analysis = time.time()
        result = analyze_live_snapshot(
            symbol=symbol, ticks=ticks, timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            trading_mode=trading_mode, model=model,
        )
        result["venue"] = _resolve_venue()
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
            "briefing": "MT5 unavailable — no Deriv fallback; start the Blueberry MT5 terminal",
            "symbol": symbol, "trading_mode": trading_mode,
            "regime": "unknown", "regime_explanation": "Broker link down (no fallback)",
            "structure_summary": "structure still forming",
            "confidence": None, "model_long_probability": None,
            "current_close": None,
            "wait_for": "start the Blueberry MT5 terminal, then refresh",
            "reasons": ["mt5 terminal unavailable, no deriv fallback"],
            "risk_state": {
                "equity": 1000.0, "open_positions": 0, "consecutive_losses": 0,
                "realized_pnl": 0.0, "trades_today": 0, "max_open_positions": 1,
                "max_daily_loss_fraction": 0.02, "max_consecutive_losses": 4,
                "daily_drawdown_pct": 0.0,
            },
            "stale_data_since": _read_last_csv_epoch(symbol),
            "stale_data_max_age_seconds": stale_max_age,
        }, [], DEFAULT_GUARDIAN_THRESHOLDS, trading_mode=trading_mode)
        result["venue"] = "mt5"
        result["phase_timing_ms"] = _phases
        return result

    # Deriv WebSocket is the explicit venue when MT5 is not configured —
    # the lazy CSV-only analysis below is the fallback when that path
    # failed too.  Load the corpus only now (not at the top of the
    # function) so the happy path never pays the 5s CSV read twice.
    if csv_ticks is None:
        csv_ticks = _load_csv_ticks(symbol)
    if csv_ticks:
        _t_analysis = time.time()
        result = analyze_live_snapshot(
            symbol=symbol, ticks=csv_ticks, timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            trading_mode=trading_mode, model=model,
        )
        result["venue"] = "csv"
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
    result["venue"] = "csv"
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
    calls_journal_path: str | None = "journals/live_calibration_calls.jsonl",
    emit_initial: bool = False,
    max_alerts: int | None = None,
    max_minutes: int | None = None,
    max_reconnects: int = 5,
    reconnect_backoff_sec: int = 1,
    app_id: str | None = None,
    auto_score_interval_sec: float | None = None,
    auto_score_outcomes_path: str = DEFAULT_OUTCOMES_PATH,
    auto_score_status_path: str = DEFAULT_STATUS_PATH,
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
    calls_journal = Path(calls_journal_path) if calls_journal_path else None
    if calls_journal is not None:
        calls_journal.parent.mkdir(parents=True, exist_ok=True)

    previous: WatchState | None = None
    reconnects = 0
    context_cooldown_remaining = 0

    try:
        # ── warm-up baseline ──────────────────────────────────────
        # No fallback: when MT5 is configured but the terminal is down the
        # collector raises.  That must NOT crash the watch — journal a
        # transport record and start with an honest stand-aside baseline so
        # the reconnect machinery below can retry the broker link.
        try:
            warmup_ticks, baseline_alert, previous = await _build_watch_baseline(
                symbol=symbol,
                warmup_count=warmup_count,
                timeframe_sec=timeframe_sec,
                higher_timeframe_sec=higher_timeframe_sec,
                app_id=app_id,
            )
        except Exception as exc:
            _append_journal(journal_file, {
                "record_type": "watch_transport",
                "event": "baseline_failed",
                "symbol": symbol,
                "error": str(exc),
            })
            baseline_alert = build_guardian_snapshot({
                "call": "stand_aside", "trade_status": "not_valid",
                "direction_bias": "none",
                "briefing": f"MT5 unavailable ({exc}) — no Deriv fallback; start the Blueberry terminal",
                "symbol": symbol, "trading_mode": "sniper",
                "regime": "unknown", "regime_explanation": "Broker link down",
                "structure_summary": "structure still forming",
                "confidence": None, "model_long_probability": None,
                "current_close": None,
                "wait_for": "start the Blueberry MT5 terminal, then refresh",
                "reasons": [f"mt5 unavailable: {exc}"],                    "risk_state": {
                        "equity": 1000.0, "open_positions": 0, "consecutive_losses": 0,
                        "realized_pnl": 0.0, "trades_today": 0, "max_open_positions": 1,
                        "max_daily_loss_fraction": 0.02, "max_consecutive_losses": 4,
                        "daily_drawdown_pct": 0.0,
                    },
                }, [], DEFAULT_GUARDIAN_THRESHOLDS, trading_mode="sniper")
            baseline_alert["venue"] = "mt5"
            baseline_alert["symbol"] = symbol
            warmup_ticks, previous = [], None

        if emit_initial:
            alert_log.append(baseline_alert)
            _append_journal(journal_file, baseline_alert)
            if calls_journal is not None:
                _auto_log_call(calls_journal, baseline_alert)
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
                    if calls_journal is not None:
                        _auto_log_call(calls_journal, alert)
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
    finally:
        # ── automatic outcome scoring ────────────────────────────
        # When enabled, sweep the calls journal on a timer WHILE the watch
        # runs (``_auto_sweep_forever``), then perform one final sweep before
        # the process exits so calls logged during this session are scored
        # immediately (their hold horizon has likely elapsed).  The final
        # sweep is an unconditional inline call — it never depends on the
        # background task having started, so it runs on every exit path
        # (max-alerts, session end, transport error).  Keeps the outcomes
        # journal and the calibration health panel fresh without a separate
        # ``score-live-loop`` process or a manual CLI step.
        if auto_score_interval_sec is not None and calls_journal is not None:
            auto_sweep_task = asyncio.create_task(
                _auto_sweep_forever(
                    calls_path=calls_journal,
                    outcomes_path=Path(auto_score_outcomes_path),
                    status_path=Path(auto_score_status_path),
                    interval_sec=auto_score_interval_sec,
                    app_id=app_id,
                )
            )
            await asyncio.sleep(0)
            auto_sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await auto_sweep_task
            sweep_once(
                calls_path=calls_journal,
                outcomes_path=Path(auto_score_outcomes_path),
                symbol=None,
                window_minutes=None,
                app_id=app_id,
                status_path=Path(auto_score_status_path),
            )

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
        # The calls-journal logger (``build_call_record``) reads
        # ``execution_stop``/``primary_target`` as the canonical level keys;
        # mirror them here (same convention as ``build_watch_alert``) so live
        # calls emitted from the prepared-state path are always scorable.
        "execution_stop": prepared.stop_loss,
        "primary_target": prepared.take_profit,
        "hold_horizon_minutes": 60,
        "current_close": prepared.current_close,
        "reward_risk": prepared.reward_risk,
        "invalidates_if": prepared.invalidates_if,
        "wait_for": prepared.next_trigger,
        "call_age_seconds": prepared.call_age_seconds,
        "generated_at": prepared.generated_at,
    }
    # Stage-3 gate: same empirical gate as ``build_watch_alert`` so the
    # prepared-state path (used by live-watch emission) honors suppressed
    # call types and honest hit-rate confidence too.
    return apply_stage3_gate(alert)


def _auto_log_call(calls_journal: Path, alert: dict[str, object]) -> None:
    """Append one emitted live call to the calibration calls journal.

    Called for every alert the live-watch loop emits, so the auto-scoring
    loop (``score-live-loop`` / the live-watch auto-sweep) can measure its
    outcome (target/stop/neither) without a manual ``log-live-call`` step.
    ``build_call_record`` keeps the pre-suppression call intent
    (stage3.suppressed_call) so suppressed call types are still scored
    honestly.  Best-effort: never crashes the watch.
    """
    try:
        append_call_record(calls_journal, build_call_record(alert))
    except Exception as exc:
        logging.warning("[auto_log_call] failed to write %s: %s", calls_journal, exc)


async def _auto_sweep_forever(
    *,
    calls_path: Path,
    outcomes_path: Path,
    status_path: Path,
    interval_sec: float = 300.0,
    app_id: str | None = None,
    log: Callable[[str], None] = logging.info,
) -> None:
    """Sweep the calls journal on a schedule while the live watch runs.

    Runs one sweep immediately, then every ``interval_sec`` until cancelled
    (e.g. the live-watch loop exits).  Each sweep delegates to the shared
    ``auto_scorer.sweep_once`` (single source of truth for sweep + status
    telemetry), so this loop can never disagree with ``score-live-loop``.
    A failed sweep is recorded on the status file and retried with backoff;
    after ``MAX_CONSECUTIVE_ERRORS`` the loop gives up rather than spin
    forever.  The final sweep on session exit is performed by
    ``run_live_watch``'s ``finally`` block (unconditional), not here.
    """
    consecutive_errors = 0
    while True:
        # Run the sweep off the event loop — it does blocking market-data
        # fetches (Deriv websocket / MT5) that would otherwise stall the
        # live-watch tick loop for the duration of the sweep.
        result = await asyncio.to_thread(
            sweep_once,
            calls_path=calls_path,
            outcomes_path=outcomes_path,
            symbol=None,
            window_minutes=None,
            app_id=app_id,
            status_path=status_path,
        )
        if result.error is None:
            consecutive_errors = 0
            log(
                "[auto-score] swept %s: scored=%d failed=%d skipped=%d pending=%d",
                result.symbol,
                result.calls_scored,
                result.calls_failed,
                result.calls_skipped,
                result.calls_pending,
            )
        else:
            consecutive_errors += 1
            log("[auto-score] error: %s", result.error)
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            log(
                "[auto-score] giving up after %d consecutive failed sweeps "
                "- check DERIV_API_TOKEN / DERIV_APP_ID",
                consecutive_errors,
            )
            break
        await asyncio.sleep(interval_sec if consecutive_errors == 0 else SWEEP_BACKOFF_SEC)


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
