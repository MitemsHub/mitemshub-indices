"""Missed-trade tracker — record every NO_TRADE decision, check what the
market did 1 hour later, and feed the results back into calibration.

The quant trader's advice:
  "Professional quantitative systems have four states: STRONG BUY, WEAK BUY,
   WAIT, STRONG SELL.  Instead of thinking 'Should I trade?' it should think
   'What is the probability distribution of the next move?'"

  "Learn from every missed trade."

This module implements the "learn from every missed trade" loop:

1.  **Record**: When the decision engine produces a NO_TRADE (signal_strength
    == "wait" or report.signal is None), record a snapshot with:
      - model_long_probability (the engine's directional lean)
      - confidence at the time
      - current price
      - regime / features snapshot
      - timestamp

2.  **Resolve**: After a configurable resolution window (default 60 minutes),
    check the CSV tick history to see what the price actually did.

3.  **Feed back**: If the price moved ≥ 1 ATR in the direction the model
    predicted, that's a *missed opportunity* (outcome=1).  If the price
    moved against or didn't move, the engine was *correctly cautious*
    (outcome=0).  The (prediction, outcome) pair is fed into the
    CalibrationState so the model's probability calibration improves.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Default resolution window — 60 minutes after the NO_TRADE decision.
DEFAULT_RESOLUTION_MINUTES = 60

# Minimum ATR move to consider it a "missed opportunity".
# If the model was leaning long and price moved up by at least 1 ATR,
# that's a missed trade worth learning from.
MIN_ATR_MOVE_THRESHOLD = 1.0

# Cooldown between resolution cycles (seconds).
RESOLUTION_COOLDOWN_SEC = 30

# Maximum number of pending (unresolved) missed trades to keep in memory.
# Older ones are flushed to disk.
MAX_PENDING_RECORDS = 500

# File path for persisted missed trade records.
DEFAULT_MISSED_TRADES_PATH = Path("data/missed_trades.jsonl")

@dataclass
class MissedTradeRecord:
    """A single NO_TRADE snapshot that will be resolved later."""
    symbol: str
    recorded_at: float  # epoch seconds
    resolution_window_sec: int
    current_price: float
    model_long_probability: float
    confidence: float
    regime: str
    atr_14: float
    direction_bias: str  # "buy" / "sell" / "none"
    features_summary: dict[str, float] = field(default_factory=dict)
    resolved: bool = False
    outcome: int | None = None  # 0 = correctly stayed out, 1 = missed opportunity
    resolved_at: float | None = None
    resolved_price: float | None = None
    price_move_atr: float | None = None


@dataclass(frozen=True)
class ResolutionResult:
    resolved_count: int = 0
    missed_opportunities: int = 0
    correct_stayouts: int = 0
    failed_resolutions: int = 0


class MissedTradeTracker:
    """Track NO_TRADE decisions and resolve them after a time window.

    The tracker records every decision where the engine chose not to trade
    (signal_strength == "wait" or signal is None), then periodically checks
    what the market did.  When the market moves significantly in the
    predicted direction, that's a *missed opportunity* — the engine learns
    from it by feeding the (prediction, outcome) pair into CalibrationState.

    Usage::

        tracker = MissedTradeTracker(
            missed_trades_path=Path("data/missed_trades.jsonl"),
        )

        # On every NO_TRADE decision:
        tracker.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )

        # Periodically (e.g. every snapshot cycle):
        result = tracker.resolve(
            price_lookup=lambda sym: load_recent_prices(sym),
            update_calibration=lambda pred, outcome: engine.update_calibration(pred, outcome),
        )
    """

    def __init__(
        self,
        missed_trades_path: Path = DEFAULT_MISSED_TRADES_PATH,
        resolution_minutes: int = DEFAULT_RESOLUTION_MINUTES,
        min_atr_threshold: float = MIN_ATR_MOVE_THRESHOLD,
    ) -> None:
        self._path = missed_trades_path
        self._resolution_sec = resolution_minutes * 60
        self._min_atr_threshold = min_atr_threshold
        self._pending: list[MissedTradeRecord] = []
        self._last_resolution_attempt: float = 0.0
        self._load_pending()

    # ── Recording ────────────────────────────────────────────────

    def record(
        self,
        *,
        symbol: str,
        model_long_probability: float | None,
        confidence: float | None,
        regime: str,
        atr_14: float,
        current_price: float,
        direction_bias: str,
        features_summary: dict[str, float] | None = None,
        resolution_minutes: int | None = None,
    ) -> None:
        """Record a NO_TRADE decision for later resolution.

        Only records when there's enough information to make a meaningful
        judgment later: we need a non-None model probability, a price,
        and a positive ATR.
        """
        if model_long_probability is None or current_price is None or current_price <= 0:
            return
        if atr_14 <= 0:
            return
        # Don't record if we already have a very recent record for this symbol
        # (within 5 minutes) — avoids flooding with duplicate stand_aside records.
        now = time.time()
        for existing in self._pending:
            if (
                existing.symbol == symbol
                and not existing.resolved
                and (now - existing.recorded_at) < 300  # 5 minutes
            ):
                return

        window_sec = (resolution_minutes * 60) if resolution_minutes else self._resolution_sec
        record = MissedTradeRecord(
            symbol=symbol,
            recorded_at=now,
            resolution_window_sec=window_sec,
            current_price=current_price,
            model_long_probability=model_long_probability,
            confidence=confidence or 0.0,
            regime=regime,
            atr_14=atr_14,
            direction_bias=direction_bias,
            features_summary=features_summary or {},
        )
        self._pending.append(record)
        logger.debug(
            "[missed_trade] recorded %s price=%.4f model_long=%.3f conf=%.3f regime=%s",
            symbol, current_price, model_long_probability, confidence or 0.0, regime,
        )

    # ── Resolution ───────────────────────────────────────────────

    def resolve(
        self,
        price_lookup: Callable[[str], list[tuple[float, float]]],
        update_calibration: Callable[[float, int], None] | None = None,
    ) -> ResolutionResult:
        """Resolve pending missed trade records that are old enough.

        Args:
            price_lookup: Callable that returns (epoch, price) tuples for a symbol.
                Must include timestamps so only prices within the resolution
                window are evaluated.
            update_calibration: Callable to feed (prediction, outcome) into
                the calibration state.  prediction is the model's directional
                probability (transformed to represent the correct direction),
                outcome is 1 (missed opportunity) or 0 (correctly stayed out).

                Calibration transformation:
                  - If model leaned long (prob > 0.5): prediction = prob
                  - If model leaned short (prob < 0.5): prediction = 1-prob
                  - If neutral (prob == 0.5): prediction = 0.5 (neutral zone)

        Returns:
            ResolutionResult with counts of resolved/missed/correct records.
        """
        now = time.time()

        # Cooldown — don't resolve too frequently.
        if (now - self._last_resolution_attempt) < RESOLUTION_COOLDOWN_SEC:
            return ResolutionResult()
        self._last_resolution_attempt = now

        result = ResolutionResult()
        newly_resolved: list[MissedTradeRecord] = []

        for record in self._pending:
            if record.resolved:
                continue

            # Check if the resolution window has elapsed.
            elapsed = now - record.recorded_at
            if elapsed < record.resolution_window_sec:
                continue

            # Try to resolve.
            try:
                prices = price_lookup(record.symbol)
                if not prices:
                    result = ResolutionResult(
                        resolved_count=result.resolved_count,
                        missed_opportunities=result.missed_opportunities,
                        correct_stayouts=result.correct_stayouts,
                        failed_resolutions=result.failed_resolutions + 1,
                    )
                    continue

                outcome, price_move_atr = self._evaluate_outcome(
                    record=record,
                    prices=prices,
                )

                record.resolved = True
                record.outcome = outcome
                record.resolved_at = now
                record.resolved_price = prices[-1][1] if prices else None
                record.price_move_atr = price_move_atr
                newly_resolved.append(record)

                if outcome == 1:
                    result = ResolutionResult(
                        resolved_count=result.resolved_count + 1,
                        missed_opportunities=result.missed_opportunities + 1,
                        correct_stayouts=result.correct_stayouts,
                        failed_resolutions=result.failed_resolutions,
                    )
                    logger.info(
                        "[missed_trade] MISSED OPPORTUNITY %s: price moved %.2f ATR in predicted direction "
                        "(model_long=%.3f, price %.4f → %.4f)",
                        record.symbol, price_move_atr, record.model_long_probability,
                        record.current_price, record.resolved_price,
                    )
                else:
                    result = ResolutionResult(
                        resolved_count=result.resolved_count + 1,
                        missed_opportunities=result.missed_opportunities,
                        correct_stayouts=result.correct_stayouts + 1,
                        failed_resolutions=result.failed_resolutions,
                    )
                    logger.debug(
                        "[missed_trade] correct stay-out %s: price move %.2f ATR (model_long=%.3f)",
                        record.symbol, price_move_atr or 0.0, record.model_long_probability,
                    )

                # Feed into calibration.
                if update_calibration is not None:
                    # Calibration expects: (probability_of_long, actual_outcome).
                    # outcome=1 means the model's directional lean was correct.
                    # We must transform so the prediction aligns with the outcome:
                    #   - If model leaned long (prob > 0.5): prediction = prob, outcome as-is
                    #   - If model leaned short (prob < 0.5): prediction = 1-prob, outcome as-is
                    # This way, when we say "missed opportunity" (outcome=1), the prediction
                    # represents the probability of the correct direction.
                    model_lean_long = record.model_long_probability > 0.5
                    if model_lean_long:
                        cal_prediction = record.model_long_probability
                    else:
                        cal_prediction = 1.0 - record.model_long_probability
                    update_calibration(cal_prediction, outcome)

            except Exception as exc:
                logger.debug("[missed_trade] resolution failed for %s: %s", record.symbol, exc)
                result = ResolutionResult(
                    resolved_count=result.resolved_count,
                    missed_opportunities=result.missed_opportunities,
                    correct_stayouts=result.correct_stayouts,
                    failed_resolutions=result.failed_resolutions + 1,
                )

        # Flush resolved records from the pending list and persist.
        # Order matters: append outcomes FIRST (in case persist fails,
        # outcomes are still recorded), then persist the pending list.
        if newly_resolved:
            self._append_outcomes(newly_resolved)
            self._pending = [r for r in self._pending if not r.resolved]
            self._persist_pending()

        return result

    def _evaluate_outcome(
        self,
        record: MissedTradeRecord,
        prices: list[tuple[float, float]],
    ) -> tuple[int, float]:
        """Evaluate what the market did after the NO_TRADE decision.

        Args:
            record: The missed trade record.
            prices: List of (epoch, price) tuples from the CSV, sorted by epoch.
                    Only prices within the resolution window are considered.

        Returns:
            (outcome, price_move_atr) where:
            - outcome: 1 = missed opportunity (price moved in predicted direction),
                       0 = correctly stayed out (price moved against or didn't move)
            - price_move_atr: the price move in ATR units
        """
        if not prices:
            return 0, 0.0

        # Filter prices to only those within the resolution window.
        window_start = record.recorded_at
        window_end = record.recorded_at + record.resolution_window_sec
        window_prices = [
            price for epoch, price in prices
            if epoch >= window_start and epoch <= window_end
        ]

        if not window_prices:
            return 0, 0.0

        # Calculate the maximum move in each direction from the entry price.
        entry_price = record.current_price
        max_up = max(p - entry_price for p in window_prices)
        max_down = max(entry_price - p for p in window_prices)

        # The model's directional lean:
        # model_long_probability > 0.5 means the model was leaning long.
        # model_long_probability < 0.5 means the model was leaning short.
        model_lean_long = record.model_long_probability > 0.5
        atr = record.atr_14 if record.atr_14 > 0 else 1.0

        if model_lean_long:
            # Model was leaning long — did price go up?
            price_move_atr = max_up / atr
            if max_up >= atr * self._min_atr_threshold:
                return 1, price_move_atr  # missed opportunity
            return 0, price_move_atr  # correctly stayed out
        else:
            # Model was leaning short — did price go down?
            price_move_atr = max_down / atr
            if max_down >= atr * self._min_atr_threshold:
                return 1, price_move_atr  # missed opportunity
            return 0, price_move_atr  # correctly stayed out

    # ── Persistence ──────────────────────────────────────────────

    def _load_pending(self) -> None:
        """Load unresolved records from the JSONL file."""
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            now = time.time()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("resolved"):
                        continue  # skip already-resolved records
                    # Check if the record is still within its resolution window.
                    recorded_at = data.get("recorded_at", 0)
                    window_sec = data.get("resolution_window_sec", self._resolution_sec)
                    if (now - recorded_at) < window_sec:
                        self._pending.append(MissedTradeRecord(
                            symbol=data["symbol"],
                            recorded_at=recorded_at,
                            resolution_window_sec=window_sec,
                            current_price=data["current_price"],
                            model_long_probability=data["model_long_probability"],
                            confidence=data.get("confidence", 0.0),
                            regime=data.get("regime", "unknown"),
                            atr_14=data.get("atr_14", 1.0),
                            direction_bias=data.get("direction_bias", "none"),
                            features_summary=data.get("features_summary", {}),
                        ))
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as exc:
            logger.debug("[missed_trade] failed to load pending records: %s", exc)

    def _persist_pending(self) -> None:
        """Write unresolved records back to the JSONL file."""
        if not self._pending:
            # No pending records — don't create an empty file.
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            records_to_write = []
            for record in self._pending:
                records_to_write.append({
                    "symbol": record.symbol,
                    "recorded_at": record.recorded_at,
                    "resolution_window_sec": record.resolution_window_sec,
                    "current_price": record.current_price,
                    "model_long_probability": record.model_long_probability,
                    "confidence": record.confidence,
                    "regime": record.regime,
                    "atr_14": record.atr_14,
                    "direction_bias": record.direction_bias,
                    "features_summary": record.features_summary,
                })
            with self._path.open("w", encoding="utf-8") as f:
                for entry in records_to_write:
                    f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("[missed_trade] failed to persist pending records: %s", exc)

    def _append_outcomes(self, resolved: list[MissedTradeRecord]) -> None:
        """Append resolved outcomes to a separate outcomes file for analysis."""
        outcomes_path = self._path.parent / "missed_trade_outcomes.jsonl"
        try:
            outcomes_path.parent.mkdir(parents=True, exist_ok=True)
            with outcomes_path.open("a", encoding="utf-8") as f:
                for record in resolved:
                    f.write(json.dumps({
                        "symbol": record.symbol,
                        "recorded_at": record.recorded_at,
                        "resolved_at": record.resolved_at,
                        "current_price": record.current_price,
                        "resolved_price": record.resolved_price,
                        "model_long_probability": record.model_long_probability,
                        "confidence": record.confidence,
                        "regime": record.regime,
                        "atr_14": record.atr_14,
                        "direction_bias": record.direction_bias,
                        "outcome": record.outcome,
                        "price_move_atr": record.price_move_atr,
                    }) + "\n")
        except Exception as exc:
            logger.debug("[missed_trade] failed to append outcomes: %s", exc)

    # ── Introspection ────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """Number of unresolved missed trade records."""
        return len([r for r in self._pending if not r.resolved])

    def summary(self) -> dict[str, object]:
        """Return a summary of the missed trade tracker state."""
        pending = [r for r in self._pending if not r.resolved]
        return {
            "pending_count": len(pending),
            "symbols": list({r.symbol for r in pending}),
            "oldest_pending_age_sec": (
                max(time.time() - r.recorded_at for r in pending) if pending else 0
            ),
            "newest_pending_age_sec": (
                min(time.time() - r.recorded_at for r in pending) if pending else 0
            ),
        }
