"""Confidence decay mechanism for stale predictions.

On synthetic indices, when the model's confidence has been consistently
high for the same direction but the market hasn't moved, the model is
overconfident.  The generator doesn't care about the model's opinion —
it will produce whatever random numbers it wants regardless.

This module tracks prediction history and applies a decay factor when
the model has been consistently predicting the same direction without
the market confirming (moving in that direction).

Key insight: On synthetic indices, a model that has been predicting
"BUY" with 0.70 confidence for 50 consecutive observations without
the market moving up is almost certainly wrong.  The correct response
is to decay the confidence toward 0.50 (random).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PredictionRecord:
    """A single prediction with its context."""
    prediction: float  # model probability (0-1)
    direction: str     # "long" or "short"
    price: float       # price at prediction time
    timestamp: float   # observation number


@dataclass
class ConfidenceDecayState:
    """Current state of the confidence decay tracker."""
    # Tracking
    recent_predictions: list[PredictionRecord] = field(default_factory=list)
    # Decay parameters
    streak_window: int = 20          # how many predictions to look back
    max_streak_before_decay: int = 10  # predictions in same direction before decay starts
    decay_rate: float = 0.02         # how much to decay per extra streak observation
    min_confidence_floor: float = 0.35  # never decay below this
    price_move_threshold_pct: float = 0.5  # % move needed to "confirm" prediction
    lookback_for_move: int = 10      # how many observations to check for price move

    # Accumulated stats
    total_predictions: int = 0
    total_decays_applied: int = 0
    avg_decay_applied: float = 0.0

    def to_dict(self) -> dict:
        return {
            "streak_window": self.streak_window,
            "max_streak_before_decay": self.max_streak_before_decay,
            "decay_rate": self.decay_rate,
            "min_confidence_floor": self.min_confidence_floor,
            "price_move_threshold_pct": self.price_move_threshold_pct,
            "lookback_for_move": self.lookback_for_move,
            "total_predictions": self.total_predictions,
            "total_decays_applied": self.total_decays_applied,
            "avg_decay_applied": self.avg_decay_applied,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConfidenceDecayState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ConfidenceDecayTracker:
    """Tracks prediction history and applies confidence decay when the model
    is consistently predicting the same direction without market confirmation.

    The decay mechanism works as follows:

    1. Track the last N predictions (direction, price, confidence)
    2. Count how many consecutive predictions point the same direction
    3. Check if the price has actually moved in that direction
    4. If the streak is long AND price hasn't confirmed, decay the confidence

    This prevents the model from maintaining high confidence in a direction
    that the market isn't following — critical on synthetic indices where
    the generator has no memory of the model's predictions.

    Parameters
    ----------
    streak_window : int
        Number of recent predictions to track for streak detection.
    max_streak_before_decay : int
        How many same-direction predictions before decay kicks in.
    decay_rate : float
        Decrement per extra streak observation beyond the threshold.
    min_confidence_floor : float
        Minimum confidence after decay — never go below this.
    price_move_threshold_pct : float
        Minimum price move (%) to count as "confirmation".
    lookback_for_move : int
        How many observations back to check for price confirmation.
    """

    def __init__(
        self,
        streak_window: int = 20,
        max_streak_before_decay: int = 10,
        decay_rate: float = 0.02,
        min_confidence_floor: float = 0.35,
        price_move_threshold_pct: float = 0.5,
        lookback_for_move: int = 10,
    ) -> None:
        self.state = ConfidenceDecayState(
            streak_window=streak_window,
            max_streak_before_decay=max_streak_before_decay,
            decay_rate=decay_rate,
            min_confidence_floor=min_confidence_floor,
            price_move_threshold_pct=price_move_threshold_pct,
            lookback_for_move=lookback_for_move,
        )

    def record_prediction(
        self,
        prediction: float,
        price: float,
        timestamp: float,
    ) -> None:
        """Record a new prediction."""
        direction = "long" if prediction >= 0.5 else "short"
        record = PredictionRecord(
            prediction=prediction,
            direction=direction,
            price=price,
            timestamp=timestamp,
        )
        self.state.recent_predictions.append(record)

        # Maintain window
        if len(self.state.recent_predictions) > self.state.streak_window:
            self.state.recent_predictions.pop(0)

        self.state.total_predictions += 1

    def apply_decay(self, confidence: float, direction: str) -> float:
        """Apply confidence decay if the model is stale.

        Parameters
        ----------
        confidence : float
            The raw confidence score (0-1).
        direction : str
            "long" or "short" — the direction being scored.

        Returns
        -------
        float
            The potentially decayed confidence score.
        """
        if len(self.state.recent_predictions) < self.state.max_streak_before_decay:
            return confidence  # not enough data for decay

        # Count streak: how many recent predictions point in the same direction
        streak = 0
        for record in reversed(self.state.recent_predictions):
            if record.direction == direction:
                streak += 1
            else:
                break

        if streak < self.state.max_streak_before_decay:
            return confidence  # no decay needed

        # Check if price has confirmed the direction
        price_confirmed = self._check_price_confirmation(direction)

        if price_confirmed:
            return confidence  # market confirmed — no decay

        # Apply decay: longer streak = more decay
        excess_streak = streak - self.state.max_streak_before_decay
        decay_amount = excess_streak * self.state.decay_rate

        # Additional decay if the model's confidence has been very high
        # (the more confident, the more it needs to be humbled)
        if confidence > 0.70:
            extra_decay = (confidence - 0.70) * 0.15
            decay_amount += extra_decay

        decayed = max(self.state.min_confidence_floor, confidence - decay_amount)

        if decayed < confidence:
            self.state.total_decays_applied += 1
            self.state.avg_decay_applied = (
                (self.state.avg_decay_applied * (self.state.total_decays_applied - 1)
                 + (confidence - decayed))
                / self.state.total_decays_applied
            )

        return decayed

    def _check_price_confirmation(self, direction: str) -> bool:
        """Check if the price has moved in the predicted direction."""
        if len(self.state.recent_predictions) < self.state.lookback_for_move:
            return False

        # Compare current price to the price from lookback observations ago
        lookback_idx = max(0, len(self.state.recent_predictions) - self.state.lookback_for_move)
        past_price = self.state.recent_predictions[lookback_idx].price
        current_price = self.state.recent_predictions[-1].price

        if past_price <= 0:
            return False

        pct_move = (current_price - past_price) / past_price * 100.0

        if direction == "long":
            return pct_move >= self.state.price_move_threshold_pct
        else:
            return pct_move <= -self.state.price_move_threshold_pct

    def get_streak_info(self) -> dict:
        """Get current streak information for diagnostics."""
        if not self.state.recent_predictions:
            return {"streak": 0, "direction": "none", "price_confirmed": False}

        last_dir = self.state.recent_predictions[-1].direction
        streak = 0
        for record in reversed(self.state.recent_predictions):
            if record.direction == last_dir:
                streak += 1
            else:
                break

        return {
            "streak": streak,
            "direction": last_dir,
            "price_confirmed": self._check_price_confirmation(last_dir),
            "will_decay": streak >= self.state.max_streak_before_decay
                          and not self._check_price_confirmation(last_dir),
        }

    # ── Persistence ────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist state to JSON."""
        data = {
            "state": self.state.to_dict(),
            "predictions": [
                {"prediction": r.prediction, "direction": r.direction,
                 "price": r.price, "timestamp": r.timestamp}
                for r in self.state.recent_predictions
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> ConfidenceDecayTracker:
        """Restore state from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        tracker = cls()
        tracker.state = ConfidenceDecayState.from_dict(data["state"])
        tracker.state.recent_predictions = [
            PredictionRecord(**r) for r in data.get("predictions", [])
        ]
        return tracker
