"""SHAP-based feature importance monitoring for online logistic models.

For a linear logistic model, SHAP values are equivalent to:
    contribution_i = weight_i × normalized_feature_value_i

This module tracks rolling averages of these contributions per feature
and flags drift when:
1. A feature's rolling average contribution drops below a threshold
2. A feature's weight sign flips (positive → negative or vice versa)

No external SHAP library is required — the monitor leverages the model's
linear structure directly.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from synthetic_trader.features.indicators import clamp


@dataclass
class FeatureSnapshot:
    """Point-in-time feature importance observation."""

    feature: str
    weight: float
    mean_abs_contribution: float
    rolling_avg: float
    sign: int  # +1 or -1 (0 if weight is zero)
    drift_detected: bool = False
    drift_type: str | None = None  # "threshold_drop", "sign_flip", or None


@dataclass
class DriftAlert:
    """A detected feature importance drift event."""

    feature: str
    drift_type: str  # "threshold_drop" | "sign_flip"
    old_value: float
    new_value: float
    weight: float
    rolling_avg: float
    timestamp_updates: int  # model.update count when detected


class FeatureImportanceMonitor:
    """Tracks per-feature SHAP contribution importance over time.

    For a linear logistic model, the SHAP contribution of feature *i* for
    a single sample is::

        contribution_i = weight_i × normalized_feature_i

    The monitor maintains a rolling window of the *absolute* mean contribution
    per feature across recent samples, and raises drift alerts when:

    * **Threshold drop** — a feature's rolling average absolute contribution
      falls below ``importance_floor`` (the feature has become uninformative).
    * **Sign flip** — a feature's weight changes sign between consecutive
      monitoring snapshots (the feature's directional relationship with the
      target has reversed).

    Parameters
    ----------
    window_size : int
        Number of recent observations to keep per feature for rolling stats.
    importance_floor : float
        Minimum rolling-average absolute contribution to consider a feature
        still informative.  Features below this threshold are flagged.
    sign_flip_sensitivity : int
        How many consecutive same-sign observations are required before a
        sign flip is confirmed (prevents jitter-induced false positives).
    min_samples_before_alert : int
        Minimum total monitoring observations before any drift alerts fire.
    """

    def __init__(
        self,
        window_size: int = 200,
        importance_floor: float = 1e-4,
        sign_flip_sensitivity: int = 3,
        min_samples_before_alert: int = 50,
    ) -> None:
        self.window_size = window_size
        self.importance_floor = importance_floor
        self.sign_flip_sensitivity = sign_flip_sensitivity
        self.min_samples_before_alert = min_samples_before_alert

        # Rolling contribution history per feature: deque of abs(mean_contribution)
        self._contribution_history: dict[str, deque[float]] = {}
        # Rolling weight history per feature: deque of weight values
        self._weight_history: dict[str, deque[float]] = {}
        # Total observations processed
        self._observations: int = 0
        # Alerts raised
        self._alerts: list[DriftAlert] = []
        # Features currently flagged
        self._flagged_features: set[str] = set()

    # ── Core API ──────────────────────────────────────────────────

    def observe(
        self,
        features: dict[str, float],
        model_weights: dict[str, float],
    ) -> list[DriftAlert]:
        """Record a single observation and check for drift.

        Parameters
        ----------
        features : dict[str, float]
            The *raw* feature values for this observation (will be normalized internally).
        model_weights : dict[str, float]
            Current model weights (``model.weights``).

        Returns
        -------
        list[DriftAlert]
            Any new drift alerts raised by this observation (empty if stable).
        """
        self._observations += 1
        new_alerts: list[DriftAlert] = []

        # Compute per-feature contributions for this observation
        for name, weight in model_weights.items():
            raw_value = features.get(name, 0.0)
            # Normalize like the model does
            value = clamp(float(raw_value), -30.0, 30.0)

            contribution = abs(weight * value)

            # Update contribution history (deque auto-evicts oldest when full)
            if name not in self._contribution_history:
                self._contribution_history[name] = deque(maxlen=self.window_size)
            self._contribution_history[name].append(contribution)

            # Update weight history (deque auto-evicts oldest when full)
            if name not in self._weight_history:
                self._weight_history[name] = deque(maxlen=self.window_size)
            self._weight_history[name].append(weight)

        # Check for drift
        if self._observations >= self.min_samples_before_alert:
            alerts = self._check_drift(model_weights)
            new_alerts.extend(alerts)
            self._alerts.extend(alerts)

        return new_alerts

    def get_snapshots(self, model_weights: dict[str, float]) -> list[FeatureSnapshot]:
        """Get current importance snapshot for all tracked features."""
        # Build a map of flagged features to their last drift type
        flagged_types: dict[str, str] = {}
        for alert in reversed(self._alerts):
            if alert.feature not in flagged_types:
                flagged_types[alert.feature] = alert.drift_type

        snapshots = []
        for name in sorted(self._contribution_history.keys()):
            history = self._contribution_history[name]
            weight = model_weights.get(name, 0.0)
            rolling_avg = sum(history) / len(history) if history else 0.0
            sign = 1 if weight > 0 else (-1 if weight < 0 else 0)
            is_flagged = name in self._flagged_features

            snapshots.append(FeatureSnapshot(
                feature=name,
                weight=weight,
                mean_abs_contribution=history[-1] if history else 0.0,
                rolling_avg=rolling_avg,
                sign=sign,
                drift_detected=is_flagged,
                drift_type=flagged_types.get(name) if is_flagged else None,
            ))

        return snapshots

    def get_rolling_importance(self) -> dict[str, float]:
        """Get current rolling average absolute contribution per feature."""
        result = {}
        for name, history in self._contribution_history.items():
            if history:
                result[name] = sum(history) / len(history)
        return result

    def get_ranked_features(self, model_weights: dict[str, float]) -> list[tuple[str, float, int]]:
        """Get features ranked by rolling importance.

        Returns list of (feature_name, rolling_avg_contribution, sign) tuples
        sorted by descending importance.
        """
        ranked = []
        for name in sorted(self._contribution_history.keys()):
            history = self._contribution_history[name]
            rolling_avg = sum(history) / len(history) if history else 0.0
            weight = model_weights.get(name, 0.0)
            sign = 1 if weight > 0 else (-1 if weight < 0 else 0)
            ranked.append((name, rolling_avg, sign))

        return sorted(ranked, key=lambda x: x[1], reverse=True)

    @property
    def alerts(self) -> list[DriftAlert]:
        """All drift alerts raised so far."""
        return list(self._alerts)

    @property
    def flagged_features(self) -> set[str]:
        """Features currently flagged for drift."""
        return self._flagged_features.copy()

    @property
    def observations(self) -> int:
        """Total observations processed."""
        return self._observations

    # ── Drift Detection ───────────────────────────────────────────

    def _check_drift(self, model_weights: dict[str, float]) -> list[DriftAlert]:
        """Check all features for drift conditions."""
        alerts = []

        for name in self._contribution_history:
            # Check threshold drop
            alert = self._check_threshold_drop(name, model_weights)
            if alert:
                alerts.append(alert)

            # Check sign flip
            alert = self._check_sign_flip(name, model_weights)
            if alert:
                alerts.append(alert)

        return alerts

    def _check_threshold_drop(
        self, feature: str, model_weights: dict[str, float]
    ) -> DriftAlert | None:
        """Check if a feature's rolling importance dropped below the floor."""
        history = self._contribution_history.get(feature, [])
        if len(history) < self.min_samples_before_alert:
            return None

        rolling_avg = sum(history) / len(history)
        weight = model_weights.get(feature, 0.0)

        if rolling_avg < self.importance_floor:
            if feature not in self._flagged_features:
                self._flagged_features.add(feature)
                return DriftAlert(
                    feature=feature,
                    drift_type="threshold_drop",
                    old_value=history[0] if history else 0.0,
                    new_value=rolling_avg,
                    weight=weight,
                    rolling_avg=rolling_avg,
                    timestamp_updates=self._observations,
                )

        # Clear flag if it recovers
        elif feature in self._flagged_features:
            self._flagged_features.discard(feature)

        return None

    def _check_sign_flip(
        self, feature: str, model_weights: dict[str, float]
    ) -> DriftAlert | None:
        """Check if a feature's weight sign has flipped."""
        weight_history = self._weight_history.get(feature)
        if weight_history is None or len(weight_history) < self.sign_flip_sensitivity + 1:
            return None

        # Check last N observations for consistent new sign (deque doesn't support slicing)
        recent = list(weight_history)[-self.sign_flip_sensitivity :]
        old_sign_weight = list(weight_history)[-(self.sign_flip_sensitivity + 1)]

        if old_sign_weight == 0 or all(w == 0 for w in recent):
            return None

        old_sign = 1 if old_sign_weight > 0 else -1
        new_sign = 1 if recent[-1] > 0 else -1

        if old_sign != new_sign:
            # Check if the flip is consistent (all recent same sign)
            consistent = all(
                (1 if w > 0 else -1) == new_sign for w in recent if w != 0
            )
            if consistent:
                weight = model_weights.get(feature, 0.0)
                rolling_avg_history = self._contribution_history.get(feature, [])
                rolling_avg = (
                    sum(rolling_avg_history) / len(rolling_avg_history)
                    if rolling_avg_history
                    else 0.0
                )
                return DriftAlert(
                    feature=feature,
                    drift_type="sign_flip",
                    old_value=old_sign_weight,
                    new_value=recent[-1],
                    weight=weight,
                    rolling_avg=rolling_avg,
                    timestamp_updates=self._observations,
                )

        return None

    # ── Persistence ───────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist monitor state to JSON."""
        data = {
            "window_size": self.window_size,
            "importance_floor": self.importance_floor,
            "sign_flip_sensitivity": self.sign_flip_sensitivity,
            "min_samples_before_alert": self.min_samples_before_alert,
            "observations": self._observations,
            "contribution_history": {k: list(v) for k, v in self._contribution_history.items()},
            "weight_history": {k: list(v) for k, v in self._weight_history.items()},
            "flagged_features": list(self._flagged_features),
            "alerts": [
                {
                    "feature": a.feature,
                    "drift_type": a.drift_type,
                    "old_value": a.old_value,
                    "new_value": a.new_value,
                    "weight": a.weight,
                    "rolling_avg": a.rolling_avg,
                    "timestamp_updates": a.timestamp_updates,
                }
                for a in self._alerts
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "FeatureImportanceMonitor":
        """Restore monitor state from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        monitor = cls(
            window_size=data["window_size"],
            importance_floor=data["importance_floor"],
            sign_flip_sensitivity=data["sign_flip_sensitivity"],
            min_samples_before_alert=data["min_samples_before_alert"],
        )
        monitor._observations = data["observations"]
        monitor._contribution_history = {k: deque(v, maxlen=monitor.window_size) for k, v in data["contribution_history"].items()}
        monitor._weight_history = {k: deque(v, maxlen=monitor.window_size) for k, v in data["weight_history"].items()}
        monitor._flagged_features = set(data["flagged_features"])
        monitor._alerts = [
            DriftAlert(
                feature=a["feature"],
                drift_type=a["drift_type"],
                old_value=a["old_value"],
                new_value=a["new_value"],
                weight=a["weight"],
                rolling_avg=a["rolling_avg"],
                timestamp_updates=a["timestamp_updates"],
            )
            for a in data["alerts"]
        ]
        return monitor
