"""Signal feedback tracker — records user feedback (thumbs up/down) on every
trade signal and resolves outcomes automatically.

This closes the learning loop:
1. User sees a signal → gives feedback (good/bad/neutral)
2. System tracks whether TP or SL was hit
3. Feedback + outcome are fed back into calibration so the model learns
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import logging

logger = logging.getLogger(__name__)

DEFAULT_FEEDBACK_PATH = Path("data/signal_feedback.jsonl")
DEFAULT_OUTCOMES_PATH = Path("data/signal_outcomes.jsonl")

# How long to wait before auto-resolving an outcome (default: 6 hours)
DEFAULT_RESOLUTION_MINUTES = 360


@dataclass
class SignalFeedback:
    """A single signal with user feedback and tracked outcome."""
    # Identity
    signal_id: str  # unique ID based on symbol + generated_at
    symbol: str
    direction: str  # "buy" or "sell"
    generated_at: str  # ISO timestamp

    # Signal details
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    regime: str
    signal_strength: str  # "strong_buy", "weak_buy", etc.

    # User feedback
    user_feedback: str | None = None  # "good", "bad", "skipped", None
    feedback_at: str | None = None
    feedback_notes: str | None = None  # optional user notes

    # Auto-tracked outcome
    outcome: str | None = None  # "tp_hit", "sl_hit", "expired", "manual_win", "manual_loss"
    outcome_price: float | None = None
    outcome_at: str | None = None
    pnl_pips: float | None = None
    r_multiple: float | None = None

    # Learning metadata
    fed_to_calibration: bool = False
    fed_at: str | None = None


def make_signal_id(symbol: str, generated_at: str) -> str:
    """Create a deterministic signal ID from symbol + timestamp."""
    return f"{symbol}_{generated_at.replace(':', '-').replace('.', '-')}"


class SignalFeedbackTracker:
    """Track user feedback on signals and resolve outcomes.

    Usage::

        tracker = SignalFeedbackTracker(
            feedback_path=Path("data/signal_feedback.jsonl"),
        )

        # When a signal is generated:
        tracker.record_signal(
            signal_id="R_100_2026-08-01T12-00-00",
            symbol="R_100",
            direction="buy",
            generated_at="2026-08-01T12:00:00",
            entry=345.0,
            stop_loss=343.0,
            take_profit=351.0,
            confidence=0.58,
            regime="trend_up",
            signal_strength="strong_buy",
        )

        # When user gives feedback:
        tracker.record_feedback(
            signal_id="R_100_2026-08-01T12-00-00",
            feedback="good",
            notes="Entry was clean, TP hit perfectly",
        )

        # When outcome is known:
        tracker.record_outcome(
            signal_id="R_100_2026-08-01T12-00-00",
            outcome="tp_hit",
            outcome_price=351.2,
        )

        # Feed into learning:
        tracker.feed_to_calibration(
            signal_id="R_100_2026-08-01T12-00-00",
            update_calibration=lambda pred, label: engine.update_calibration(pred, label),
        )
    """

    def __init__(
        self,
        feedback_path: Path = DEFAULT_FEEDBACK_PATH,
        outcomes_path: Path = DEFAULT_OUTCOMES_PATH,
        resolution_minutes: int = DEFAULT_RESOLUTION_MINUTES,
    ) -> None:
        self._feedback_path = feedback_path
        self._outcomes_path = outcomes_path
        self._resolution_minutes = resolution_minutes
        self._signals: dict[str, SignalFeedback] = {}
        self._load()

    # ── Recording ────────────────────────────────────────────────

    def record_signal(
        self,
        *,
        signal_id: str,
        symbol: str,
        direction: str,
        generated_at: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        regime: str,
        signal_strength: str,
    ) -> None:
        """Record a new signal for tracking."""
        if signal_id in self._signals:
            return  # Already tracked

        self._signals[signal_id] = SignalFeedback(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            generated_at=generated_at,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            regime=regime,
            signal_strength=signal_strength,
        )
        self._persist()

    def record_feedback(
        self,
        *,
        signal_id: str,
        feedback: str,
        notes: str | None = None,
    ) -> bool:
        """Record user feedback on a signal.

        feedback: "good", "bad", or "skipped"
        Returns True if the signal was found and updated.
        """
        signal = self._signals.get(signal_id)
        if signal is None:
            return False

        signal.user_feedback = feedback
        signal.feedback_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        signal.feedback_notes = notes
        self._persist()
        return True

    def record_outcome(
        self,
        *,
        signal_id: str,
        outcome: str,
        outcome_price: float | None = None,
        pnl_pips: float | None = None,
        r_multiple: float | None = None,
    ) -> bool:
        """Record the outcome of a signal.

        outcome: "tp_hit", "sl_hit", "expired", "manual_win", "manual_loss"
        """
        signal = self._signals.get(signal_id)
        if signal is None:
            return False

        signal.outcome = outcome
        signal.outcome_price = outcome_price
        signal.outcome_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        signal.pnl_pips = pnl_pips
        signal.r_multiple = r_multiple
        self._persist()
        return True

    # ── Auto-resolution ──────────────────────────────────────────

    def resolve_outcomes(
        self,
        price_lookup: Callable[[str], list[tuple[float, float]]] | None = None,
    ) -> int:
        """Auto-resolve signals that have passed their hold horizon.

        If price_lookup is provided, checks whether TP or SL was hit.
        Otherwise, marks as "expired" after the resolution window.

        Returns the number of newly resolved signals.
        """
        now = time.time()
        resolved = 0

        for signal_id, signal in self._signals.items():
            if signal.outcome is not None:
                continue  # Already resolved

            # Check if enough time has passed
            from datetime import datetime
            try:
                gen_dt = datetime.fromisoformat(signal.generated_at.replace("Z", "+00:00"))
                elapsed = now - gen_dt.timestamp()
            except (ValueError, TypeError):
                continue

            resolution_sec = self._resolution_minutes * 60
            if elapsed < resolution_sec:
                continue  # Not yet time to resolve

            if price_lookup is not None:
                # Check actual price history for TP/SL hits
                try:
                    prices = price_lookup(signal.symbol)
                    if prices:
                        # Filter to prices after signal generation
                        gen_epoch = gen_dt.timestamp()
                        post_signal = [(e, p) for e, p in prices if e >= gen_epoch]

                        if post_signal:
                            if signal.direction == "buy":
                                hit_tp = any(p >= signal.take_profit for _, p in post_signal)
                                hit_sl = any(p <= signal.stop_loss for _, p in post_signal)
                            else:
                                hit_tp = any(p <= signal.take_profit for _, p in post_signal)
                                hit_sl = any(p >= signal.stop_loss for _, p in post_signal)

                            if hit_tp and not hit_sl:
                                signal.outcome = "tp_hit"
                                signal.outcome_price = signal.take_profit
                                r_mult = abs(signal.take_profit - signal.entry) / max(abs(signal.entry - signal.stop_loss), 0.01)
                                signal.r_multiple = r_mult
                                signal.pnl_pips = abs(signal.take_profit - signal.entry)
                            elif hit_sl and not hit_tp:
                                signal.outcome = "sl_hit"
                                signal.outcome_price = signal.stop_loss
                                signal.r_multiple = -1.0
                                signal.pnl_pips = -abs(signal.stop_loss - signal.entry)
                            elif hit_tp and hit_sl:
                                # Both hit — assume SL hit first (conservative)
                                signal.outcome = "sl_hit"
                                signal.outcome_price = signal.stop_loss
                                signal.r_multiple = -1.0
                                signal.pnl_pips = -abs(signal.stop_loss - signal.entry)
                            else:
                                signal.outcome = "expired"
                                # Use last known price as exit
                                last_price = post_signal[-1][1]
                                signal.outcome_price = last_price
                                move = last_price - signal.entry if signal.direction == "buy" else signal.entry - last_price
                                signal.pnl_pips = move
                                signal.r_multiple = move / max(abs(signal.entry - signal.stop_loss), 0.01)
                except Exception as exc:
                    logger.debug("[signal_feedback] resolution failed for %s: %s", signal_id, exc)
                    signal.outcome = "expired"
            else:
                signal.outcome = "expired"

            signal.outcome_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            resolved += 1

        if resolved > 0:
            self._persist()
            self._append_outcomes()

        return resolved

    # ── Feeding into calibration ─────────────────────────────────

    def feed_to_calibration(
        self,
        signal_id: str,
        update_calibration: Callable[[float, int], None],
    ) -> bool:
        """Feed a signal's outcome into the calibration buffer.

        The label is:
        - 1 if user said "good" AND outcome was tp_hit/manual_win
        - 0 if user said "bad" AND outcome was sl_hit/manual_loss
        - 1/0 based on outcome alone if no user feedback

        Returns True if successfully fed.
        """
        signal = self._signals.get(signal_id)
        if signal is None or signal.outcome is None or signal.fed_to_calibration:
            return False

        # Determine the label
        if signal.user_feedback == "good" and signal.outcome in ("tp_hit", "manual_win"):
            label = 1
        elif signal.user_feedback == "bad" and signal.outcome in ("sl_hit", "manual_loss"):
            label = 0
        elif signal.outcome in ("tp_hit", "manual_win"):
            label = 1
        elif signal.outcome in ("sl_hit", "manual_loss"):
            label = 0
        else:
            # Expired — use direction vs price movement
            if signal.pnl_pips is not None:
                label = 1 if signal.pnl_pips > 0 else 0
            else:
                return False  # Can't determine label

        # The prediction should be the confidence of the correct direction
        prediction = signal.confidence

        try:
            update_calibration(prediction, label)
            signal.fed_to_calibration = True
            signal.fed_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            self._persist()
            return True
        except Exception as exc:
            logger.debug("[signal_feedback] calibration feed failed for %s: %s", signal_id, exc)
            return False

    # ── Querying ─────────────────────────────────────────────────

    def get_signal(self, signal_id: str) -> SignalFeedback | None:
        return self._signals.get(signal_id)

    def get_pending_feedback(self) -> list[SignalFeedback]:
        """Get signals that have an outcome but no user feedback yet."""
        return [
            s for s in self._signals.values()
            if s.outcome is not None and s.user_feedback is None
        ]

    def get_unresolved(self) -> list[SignalFeedback]:
        """Get signals that have no outcome yet."""
        return [
            s for s in self._signals.values()
            if s.outcome is None
        ]

    def get_all_signals(self, limit: int = 50) -> list[SignalFeedback]:
        """Get all signals, most recent first."""
        sorted_signals = sorted(
            self._signals.values(),
            key=lambda s: s.generated_at,
            reverse=True,
        )
        return sorted_signals[:limit]

    def get_stats(self) -> dict[str, object]:
        """Get summary statistics of all tracked signals."""
        all_signals = list(self._signals.values())
        resolved = [s for s in all_signals if s.outcome is not None]
        with_feedback = [s for s in resolved if s.user_feedback is not None]

        total = len(all_signals)
        tp_hits = sum(1 for s in resolved if s.outcome == "tp_hit")
        sl_hits = sum(1 for s in resolved if s.outcome == "sl_hit")
        expired = sum(1 for s in resolved if s.outcome == "expired")
        good_feedback = sum(1 for s in with_feedback if s.user_feedback == "good")
        bad_feedback = sum(1 for s in with_feedback if s.user_feedback == "bad")

        win_rate = tp_hits / max(len(resolved), 1)
        avg_r = (
            sum(s.r_multiple or 0 for s in resolved) / max(len(resolved), 1)
        )

        return {
            "total_signals": total,
            "resolved": len(resolved),
            "pending_resolution": total - len(resolved),
            "tp_hits": tp_hits,
            "sl_hits": sl_hits,
            "expired": expired,
            "win_rate": round(win_rate, 3),
            "avg_r_multiple": round(avg_r, 3),
            "with_feedback": len(with_feedback),
            "good_feedback": good_feedback,
            "bad_feedback": bad_feedback,
            "pending_feedback": len(resolved) - len(with_feedback),
            "fed_to_calibration": sum(1 for s in resolved if s.fed_to_calibration),
        }

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        """Load signals from the feedback JSONL file."""
        if not self._feedback_path.exists():
            return
        try:
            for line in self._feedback_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    sig = SignalFeedback(**data)
                    self._signals[sig.signal_id] = sig
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue
        except Exception as exc:
            logger.debug("[signal_feedback] failed to load: %s", exc)

    def _persist(self) -> None:
        """Write all signals to the feedback JSONL file."""
        try:
            self._feedback_path.parent.mkdir(parents=True, exist_ok=True)
            with self._feedback_path.open("w", encoding="utf-8") as f:
                for signal in sorted(self._signals.values(), key=lambda s: s.generated_at):
                    f.write(json.dumps(asdict(signal), sort_keys=True) + "\n")
        except Exception as exc:
            logger.debug("[signal_feedback] failed to persist: %s", exc)

    def _append_outcomes(self) -> None:
        """Append newly resolved outcomes to the outcomes file."""
        try:
            self._outcomes_path.parent.mkdir(parents=True, exist_ok=True)
            with self._outcomes_path.open("a", encoding="utf-8") as f:
                for signal in self._signals.values():
                    if signal.outcome is not None and signal.outcome_at:
                        # Only append if not already in outcomes file
                        f.write(json.dumps(asdict(signal), sort_keys=True) + "\n")
        except Exception as exc:
            logger.debug("[signal_feedback] failed to append outcomes: %s", exc)
