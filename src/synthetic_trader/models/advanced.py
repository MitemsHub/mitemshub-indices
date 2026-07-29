from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from synthetic_trader.config import ModelConfig
from synthetic_trader.features.indicators import clamp
from synthetic_trader.models.online import OnlineLogisticModel


@dataclass
class FeatureImportance:
    """Feature importance with stability tracking."""

    name: str
    weight: float
    abs_weight: float
    rank: int
    stability_score: float = 0.0
    contribution: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureImportanceReport:
    """Complete feature importance report."""

    features: list[FeatureImportance]
    total_features: int
    top_k: int
    cumulative_importance: float
    unused_features: list[str]
    redundant_pairs: list[tuple[str, str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": [f.to_dict() for f in self.features],
            "total_features": self.total_features,
            "top_k": self.top_k,
            "cumulative_importance": self.cumulative_importance,
            "unused_features": self.unused_features,
            "redundant_pairs": self.redundant_pairs,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


class FeatureSelector:
    """
    Feature selection and importance ranking for online models.

    Tracks weight magnitudes over time to identify stable, important features
    and detect redundant or unused features.
    """

    def __init__(
        self,
        min_weight_magnitude: float = 1e-4,
        stability_window: int = 100,
        correlation_threshold: float = 0.95,
        top_k: int | None = None,
    ) -> None:
        self.min_weight_magnitude = min_weight_magnitude
        self.stability_window = stability_window
        self.correlation_threshold = correlation_threshold
        self.top_k = top_k

        self._weight_history: list[dict[str, float]] = []
        self._feature_names: list[str] = []
        self._selected_features: set[str] = set()

    def update(self, model: OnlineLogisticModel) -> None:
        """Update feature importance from model weights."""
        weights = model.weights
        self._weight_history.append(weights.copy())
        if len(self._weight_history) > self.stability_window:
            self._weight_history.pop(0)

        # Update feature names
        for name in weights:
            if name not in self._feature_names:
                self._feature_names.append(name)

    def get_importance(self, model: OnlineLogisticModel) -> FeatureImportanceReport:
        """Generate feature importance report."""
        weights = model.weights
        if not weights:
            return FeatureImportanceReport(
                features=[],
                total_features=0,
                top_k=0,
                cumulative_importance=0.0,
                unused_features=[],
                redundant_pairs=[],
            )

        # Calculate absolute weights and rank
        abs_weights = {k: abs(v) for k, v in weights.items()}
        sorted_features = sorted(abs_weights.items(), key=lambda x: x[1], reverse=True)

        total_abs_weight = sum(abs_weights.values()) or 1.0
        cumulative = 0.0
        features: list[FeatureImportance] = []
        unused: list[str] = []

        for rank, (name, abs_w) in enumerate(sorted_features, 1):
            weight = weights[name]
            contribution = abs_w / total_abs_weight
            cumulative += contribution

            # Calculate stability score from history
            stability = self._calculate_stability(name)

            fi = FeatureImportance(
                name=name,
                weight=weight,
                abs_weight=abs_w,
                rank=rank,
                stability_score=stability,
                contribution=contribution,
            )
            features.append(fi)

            if abs_w < self.min_weight_magnitude:
                unused.append(name)

        # Detect redundant pairs (high correlation in weight patterns)
        redundant = self._detect_redundant_pairs()

        # Determine top_k
        top_k = self.top_k or len(features)
        selected = {f.name for f in features[:top_k]}
        self._selected_features = selected

        return FeatureImportanceReport(
            features=features,
            total_features=len(features),
            top_k=top_k,
            cumulative_importance=cumulative,
            unused_features=unused,
            redundant_pairs=redundant,
        )

    def _calculate_stability(self, feature_name: str) -> float:
        """Calculate stability score based on weight history."""
        if len(self._weight_history) < 2:
            return 1.0

        values = [w.get(feature_name, 0.0) for w in self._weight_history]
        if all(v == 0 for v in values):
            return 0.0

        # Coefficient of variation (lower = more stable)
        mean_val = np.mean(values)
        if mean_val == 0:
            return 0.0
        std_val = np.std(values)
        cv = std_val / abs(mean_val) if mean_val != 0 else 1.0

        # Convert to stability score (1 = perfectly stable)
        return clamp(1.0 - min(cv, 1.0), 0.0, 1.0)

    def _detect_redundant_pairs(self) -> list[tuple[str, str, float]]:
        """Detect feature pairs with highly correlated weight trajectories."""
        if len(self._weight_history) < 10 or len(self._feature_names) < 2:
            return []

        # Build weight matrix: features x time
        matrix = np.array(
            [[w.get(name, 0.0) for w in self._weight_history] for name in self._feature_names]
        )

        redundant: list[tuple[str, str, float]] = []
        n = len(self._feature_names)

        for i in range(n):
            for j in range(i + 1, n):
                # Skip if either feature has near-zero variance
                if np.std(matrix[i]) < 1e-6 or np.std(matrix[j]) < 1e-6:
                    continue

                corr = np.corrcoef(matrix[i], matrix[j])[0, 1]
                if not np.isnan(corr) and abs(corr) > self.correlation_threshold:
                    redundant.append((self._feature_names[i], self._feature_names[j], float(corr)))

        return redundant

    def get_selected_features(self) -> set[str]:
        """Get currently selected features."""
        return self._selected_features.copy()

    def filter_features(self, features: dict[str, float], model: OnlineLogisticModel | None = None) -> dict[str, float]:
        """Filter features to only selected ones (by top_k and threshold).

        If model is provided, uses model weights for threshold checking.
        """
        if model is not None:
            weights = model.weights
            return {
                k: v
                for k, v in features.items()
                if k in self._selected_features and abs(weights.get(k, 0)) >= self.min_weight_magnitude
            }
        return {k: v for k, v in features.items() if k in self._selected_features}


@dataclass
class CalibrationResult:
    """Result of calibration."""

    method: str
    calibrated_probs: np.ndarray
    original_probs: np.ndarray
    ece_before: float
    ece_after: float
    brier_before: float
    brier_after: float
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "ece_before": self.ece_before,
            "ece_after": self.ece_after,
            "brier_before": self.brier_before,
            "brier_after": self.brier_after,
            "parameters": self.parameters,
        }


class ModelCalibrator:
    """
    Probability calibration for online models.

    Supports Platt scaling (sigmoid) and isotonic regression.
    Designed for online updates with streaming data.
    """

    def __init__(
        self,
        method: str = "platt",
        min_samples: int = 50,
        max_samples: int = 5000,
    ) -> None:
        self.method = method
        self.min_samples = min_samples
        self.max_samples = max_samples

        self._probs: list[float] = []
        self._labels: list[int] = []

        # Platt scaling parameters
        self._platt_A: float = 0.0
        self._platt_B: float = 0.0

        # Isotonic regression
        self._isotonic_x: np.ndarray | None = None
        self._isotonic_y: np.ndarray | None = None

        self._fitted = False

    def add_sample(self, prob: float, label: int) -> None:
        """Add a sample for calibration."""
        if label not in (0, 1):
            raise ValueError("Label must be 0 or 1")

        prob = clamp(prob, 1e-7, 1 - 1e-7)
        self._probs.append(prob)
        self._labels.append(label)

        if len(self._probs) > self.max_samples:
            self._probs.pop(0)
            self._labels.pop(0)

    def fit(self) -> CalibrationResult | None:
        """Fit calibrator on collected samples."""
        if len(self._probs) < self.min_samples:
            return None

        probs = np.array(self._probs)
        labels = np.array(self._labels)

        # Calculate metrics before
        ece_before = self._expected_calibration_error(probs, labels)
        brier_before = np.mean((probs - labels) ** 2)

        if self.method == "platt":
            calibrated_probs, params = self._fit_platt(probs, labels)
        elif self.method == "isotonic":
            calibrated_probs, params = self._fit_isotonic(probs, labels)
        else:
            raise ValueError(f"Unknown method: {self.method}")

        # Calculate metrics after
        ece_after = self._expected_calibration_error(calibrated_probs, labels)
        brier_after = np.mean((calibrated_probs - labels) ** 2)

        self._fitted = True

        return CalibrationResult(
            method=self.method,
            calibrated_probs=calibrated_probs,
            original_probs=probs,
            ece_before=ece_before,
            ece_after=ece_after,
            brier_before=brier_before,
            brier_after=brier_after,
            parameters=params,
        )

    def _fit_platt(self, probs: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, dict]:
        """Fit Platt scaling (sigmoid calibration)."""
        # Convert to logits
        logits = np.log(probs / (1 - probs))

        # Simple gradient descent for A, B
        # Minimize: -sum(y_i * log(p_i) + (1-y_i) * log(1-p_i))
        # where p_i = 1 / (1 + exp(A * logit_i + B))

        A, B = 0.0, 0.0
        lr = 0.01

        for _ in range(100):
            z = A * logits + B
            p = 1.0 / (1.0 + np.exp(-z))

            # Gradients
            grad_A = np.mean((p - labels) * logits)
            grad_B = np.mean(p - labels)

            A -= lr * grad_A
            B -= lr * grad_B

        self._platt_A, self._platt_B = float(A), float(B)
        calibrated = 1.0 / (1.0 + np.exp(-(A * logits + B)))

        return calibrated, {"A": self._platt_A, "B": self._platt_B}

    def _fit_isotonic(self, probs: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, dict]:
        """Fit isotonic regression using PAVA (Pool Adjacent Violators Algorithm)."""
        # Sort by probability
        order = np.argsort(probs)
        x = probs[order]
        y = labels[order].astype(float)

        # PAVA
        n = len(x)
        blocks = [(x[i], y[i], 1) for i in range(n)]  # (x, y_avg, count)

        i = 0
        while i < len(blocks) - 1:
            if blocks[i][1] > blocks[i + 1][1]:
                # Pool adjacent violators
                x1, y1, n1 = blocks[i]
                x2, y2, n2 = blocks[i + 1]
                new_x = (x1 * n1 + x2 * n2) / (n1 + n2)
                new_y = (y1 * n1 + y2 * n2) / (n1 + n2)
                blocks[i] = (new_x, new_y, n1 + n2)
                blocks.pop(i + 1)
                if i > 0:
                    i -= 1
            else:
                i += 1

        # Create piecewise constant function
        self._isotonic_x = np.array([b[0] for b in blocks])
        self._isotonic_y = np.array([b[1] for b in blocks])

        # Apply to original probabilities
        calibrated = np.interp(probs, self._isotonic_x, self._isotonic_y, left=0.0, right=1.0)

        return calibrated, {
            "x": self._isotonic_x.tolist(),
            "y": self._isotonic_y.tolist(),
        }

    def _expected_calibration_error(self, probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
        """Calculate Expected Calibration Error (ECE)."""
        bin_edges = np.linspace(0, 1, n_bins + 1)
        ece = 0.0

        for i in range(n_bins):
            mask = (probs >= bin_edges[i]) & (probs < bin_edges[i + 1])
            if i == n_bins - 1:
                mask = (probs >= bin_edges[i]) & (probs <= bin_edges[i + 1])

            if not np.any(mask):
                continue

            bin_probs = probs[mask]
            bin_labels = labels[mask]
            bin_confidence = np.mean(bin_probs)
            bin_accuracy = np.mean(bin_labels)
            bin_weight = len(bin_probs) / len(probs)

            ece += bin_weight * abs(bin_confidence - bin_accuracy)

        return float(ece)

    def calibrate(self, prob: float) -> float:
        """Calibrate a single probability."""
        if not self._fitted:
            return prob

        prob = clamp(prob, 1e-7, 1 - 1e-7)

        if self.method == "platt":
            logit = math.log(prob / (1 - prob))
            return 1.0 / (1.0 + math.exp(-(self._platt_A * logit + self._platt_B)))
        elif self.method == "isotonic":
            if self._isotonic_x is not None:
                return float(np.interp(prob, self._isotonic_x, self._isotonic_y, left=0.0, right=1.0))
        return prob

    def save(self, path: str | Path) -> None:
        """Save calibrator state."""
        data = {
            "method": self.method,
            "platt_A": self._platt_A,
            "platt_B": self._platt_B,
            "isotonic_x": self._isotonic_x.tolist() if self._isotonic_x is not None else None,
            "isotonic_y": self._isotonic_y.tolist() if self._isotonic_y is not None else None,
            "fitted": self._fitted,
        }
        Path(path).write_text(json.dumps(data))

    @classmethod
    def load(cls, path: str | Path) -> "ModelCalibrator":
        """Load calibrator state."""
        data = json.loads(Path(path).read_text())
        cal = cls(method=data["method"])
        cal._platt_A = data["platt_A"]
        cal._platt_B = data["platt_B"]
        cal._isotonic_x = np.array(data["isotonic_x"]) if data["isotonic_x"] else None
        cal._isotonic_y = np.array(data["isotonic_y"]) if data["isotonic_y"] else None
        cal._fitted = data["fitted"]
        return cal


class ConfidenceScorer:
    """
    Enhanced confidence scoring combining model probability with
    regime awareness, structural alignment, and calibration.
    """

    def __init__(
        self,
        model: OnlineLogisticModel,
        calibrator: ModelCalibrator | None = None,
        feature_selector: FeatureSelector | None = None,
    ) -> None:
        self.model = model
        self.calibrator = calibrator
        self.feature_selector = feature_selector
        # Missed-trade learning: when the engine frequently misses opportunities
        # in range-bound markets, it becomes more willing to trade them.
        self._missed_opportunities: int = 0
        self._correct_stayouts: int = 0
        self._range_miss_boost: float = 0.0  # cached boost for range regime

    def score(
        self,
        features: dict[str, float],
        regime: str,
        structure_bias: float,
        displacement: float,
    ) -> float:
        """
        Compute calibrated confidence score.

        Combines:
        - Model probability (calibrated)
        - Regime alignment
        - Structural bias alignment
        - Displacement quality
        """
        # Base model probability
        prob = self.model.predict_proba(features)

        # Calibrate if available
        if self.calibrator and self.calibrator._fitted:
            prob = self.calibrator.calibrate(prob)

        # Directional probability (long vs short)
        long_prob = prob
        short_prob = 1.0 - prob

        # Regime adjustment
        regime_boost = self._regime_alignment(regime, long_prob > 0.5)

        # Structure alignment
        structure_boost = self._structure_alignment(structure_bias, long_prob > 0.5)

        # Displacement quality
        disp_boost = min(displacement / 2.0, 1.0) * 0.1

        # Combine with weights
        base_conf = max(long_prob, short_prob)
        confidence = (
            0.6 * base_conf
            + 0.15 * regime_boost
            + 0.15 * structure_boost
            + 0.1 * disp_boost
        )

        return clamp(confidence, 0.0, 1.0)

    def update_missed_trade_stats(
        self,
        missed_opportunities: int,
        correct_stayouts: int,
    ) -> None:
        """Update missed trade statistics from MissedTradeTracker resolution.

        When the engine frequently misses opportunities (outcome=1), it means
        the engine is too conservative in range-bound markets. This increases
        the range regime boost so future scores are more favorable.

        The boost decays over time — if the engine starts getting things right
        (outcome=0), the boost decreases.
        """
        self._missed_opportunities += missed_opportunities
        self._correct_stayouts += correct_stayouts

        total = self._missed_opportunities + self._correct_stayouts
        if total < 5:
            # Need at least 5 resolved trades to form a pattern
            self._range_miss_boost = 0.0
            return

        # Missed rate: what fraction of resolutions were missed opportunities
        miss_rate = self._missed_opportunities / total

        # Map miss rate to boost: 0% miss rate -> 0 boost, 50%+ -> max boost of 0.15
        # This is a sigmoid-like curve: slow at first, then accelerating
        # At 30% miss rate -> ~0.05 boost (mild willingness)
        # At 50% miss rate -> ~0.12 boost (strong willingness)
        # At 70%+ miss rate -> ~0.15 cap (aggressive in ranges)
        self._range_miss_boost = min(miss_rate * 0.22, 0.15)

    def _regime_alignment(self, regime: str, is_long: bool) -> float:
        """Score regime alignment."""
        regime_scores = {
            "trend_up": 0.8 if is_long else 0.2,
            "trend_down": 0.2 if is_long else 0.8,
            "range": 0.5 + self._range_miss_boost,
            "volatile": 0.3,
            "compression": 0.4,
            "unknown": 0.5,
        }
        return regime_scores.get(regime, 0.5)

    @property
    def missed_trade_boost(self) -> float:
        """Current range-regime boost from missed trade learning."""
        return self._range_miss_boost

    @property
    def missed_trade_stats(self) -> dict[str, int]:
        """Current missed trade statistics."""
        return {
            "missed_opportunities": self._missed_opportunities,
            "correct_stayouts": self._correct_stayouts,
            "total_resolved": self._missed_opportunities + self._correct_stayouts,
        }

    def _structure_alignment(self, bias: float, is_long: bool) -> float:
        """Score structure alignment."""
        aligned = (bias > 0 and is_long) or (bias < 0 and not is_long)
        strength = min(abs(bias), 1.0)
        return 0.8 * strength if aligned else 0.2 * strength


@dataclass
class ModelMetrics:
    """Comprehensive model performance metrics."""

    # Classification metrics
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    # Probabilistic metrics
    brier_score: float = 0.0
    log_loss: float = 0.0
    ece: float = 0.0  # Expected Calibration Error
    mce: float = 0.0  # Maximum Calibration Error

    # Trading metrics
    expectancy_r: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0

    # Sample counts
    n_samples: int = 0
    n_positive: int = 0
    n_negative: int = 0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


class ModelMonitor:
    """
    Model monitoring for drift detection and performance tracking.

    Tracks:
    - Prediction distribution drift
    - Feature distribution drift
    - Performance degradation
    - Calibration quality
    """

    def __init__(
        self,
        window_size: int = 1000,
        drift_threshold: float = 0.1,
        performance_window: int = 100,
    ) -> None:
        self.window_size = window_size
        self.drift_threshold = drift_threshold
        self.performance_window = performance_window

        self._predictions: list[float] = []
        self._labels: list[int] = []
        self._features: list[dict[str, float]] = []
        self._feature_means: dict[str, float] = {}
        self._feature_stds: dict[str, float] = {}
        self._initialized = False

    def record(self, features: dict[str, float], prediction: float, label: int | None = None) -> None:
        """Record a prediction (and optional label)."""
        self._predictions.append(prediction)
        self._features.append(features)

        if label is not None:
            self._labels.append(label)

        # Update feature statistics BEFORE maintaining window
        self._update_feature_stats(features)

        # Maintain window
        if len(self._predictions) > self.window_size:
            self._predictions.pop(0)
            self._features.pop(0)
            if self._labels:
                self._labels.pop(0)

        if not self._initialized and len(self._predictions) >= 100:
            self._initialized = True

    def _update_feature_stats(self, features: dict[str, float]) -> None:
        """Update running feature statistics (Welford's algorithm)."""
        for name, value in features.items():
            if name not in self._feature_means:
                self._feature_means[name] = value
                self._feature_stds[name] = 0.0
            else:
                n = len(self._predictions)
                old_mean = self._feature_means[name]
                new_mean = old_mean + (value - old_mean) / n
                self._feature_stds[name] = (
                    (n - 2) / (n - 1) * self._feature_stds[name] ** 2
                    + (value - old_mean) * (value - new_mean) / n
                ) ** 0.5
                self._feature_means[name] = new_mean

    def check_drift(self) -> dict[str, Any]:
        """Check for prediction and feature drift."""
        if not self._initialized:
            return {"drift_detected": False, "reason": "insufficient_data"}

        # Prediction distribution drift (KS test approximation)
        recent_preds = np.array(self._predictions[-100:])
        older_preds = np.array(self._predictions[-200:-100]) if len(self._predictions) >= 200 else recent_preds

        pred_drift = self._ks_statistic(recent_preds, older_preds)

        # Feature drift
        feature_drifts = {}
        for name, mean in self._feature_means.items():
            recent_vals = [f.get(name, 0) for f in self._features[-100:]]
            older_vals = [f.get(name, 0) for f in self._features[-200:-100]] if len(self._features) >= 200 else recent_vals
            if recent_vals and older_vals:
                feature_drifts[name] = self._ks_statistic(np.array(recent_vals), np.array(older_vals))

        max_feature_drift = max(feature_drifts.values()) if feature_drifts else 0.0
        drift_detected = pred_drift > self.drift_threshold or max_feature_drift > self.drift_threshold

        return {
            "drift_detected": drift_detected,
            "prediction_drift": float(pred_drift),
            "max_feature_drift": float(max_feature_drift),
            "feature_drifts": feature_drifts,
            "threshold": self.drift_threshold,
        }

    def _ks_statistic(self, sample1: np.ndarray, sample2: np.ndarray) -> float:
        """Approximate KS statistic."""
        if len(sample1) == 0 or len(sample2) == 0:
            return 0.0
        combined = np.sort(np.concatenate([sample1, sample2]))
        cdf1 = np.searchsorted(sample1, combined, side="right") / len(sample1)
        cdf2 = np.searchsorted(sample2, combined, side="right") / len(sample2)
        return float(np.max(np.abs(cdf1 - cdf2)))

    def get_performance(self) -> ModelMetrics:
        """Calculate performance metrics on labeled samples."""
        if not self._labels:
            return ModelMetrics()

        preds = np.array(self._predictions[-len(self._labels) :])
        labels = np.array(self._labels)

        # Binary predictions at 0.5 threshold
        bin_preds = (preds > 0.5).astype(int)

        # Classification metrics
        tp = np.sum((bin_preds == 1) & (labels == 1))
        fp = np.sum((bin_preds == 1) & (labels == 0))
        tn = np.sum((bin_preds == 0) & (labels == 0))
        fn = np.sum((bin_preds == 0) & (labels == 1))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = (tp + tn) / len(labels)

        # Probabilistic metrics
        brier = float(np.mean((preds - labels) ** 2))
        log_loss = float(-np.mean(labels * np.log(preds + 1e-7) + (1 - labels) * np.log(1 - preds + 1e-7)))

        # ECE
        ece = self._expected_calibration_error(preds, labels)

        # Trading metrics (simplified)
        returns = labels * 2 - 1  # +1 for win, -1 for loss
        expectancy = float(np.mean(returns))
        win_rate = float(np.mean(labels))

        profits = returns[returns > 0]
        losses = -returns[returns < 0]
        profit_factor = float(np.sum(profits) / np.sum(losses)) if len(losses) > 0 else float("inf")

        return ModelMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1=f1,
            brier_score=brier,
            log_loss=log_loss,
            ece=ece,
            mce=0.0,  # Would need binning
            expectancy_r=expectancy,
            profit_factor=profit_factor,
            win_rate=win_rate,
            sharpe=0.0,  # Would need equity curve
            max_drawdown=0.0,
            n_samples=len(labels),
            n_positive=int(np.sum(labels)),
            n_negative=int(np.sum(1 - labels)),
        )

    def _expected_calibration_error(self, probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> float:
        """Calculate ECE."""
        bin_edges = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        for i in range(n_bins):
            mask = (probs >= bin_edges[i]) & (probs < bin_edges[i + 1])
            if i == n_bins - 1:
                mask = (probs >= bin_edges[i]) & (probs <= bin_edges[i + 1])
            if not np.any(mask):
                continue
            bin_conf = np.mean(probs[mask])
            bin_acc = np.mean(labels[mask])
            bin_weight = len(probs[mask]) / len(probs)
            ece += bin_weight * abs(bin_conf - bin_acc)
        return float(ece)

    def save_state(self, path: str | Path) -> None:
        """Save monitor state."""
        data = {
            "predictions": self._predictions,
            "labels": self._labels,
            "feature_means": self._feature_means,
            "feature_stds": self._feature_stds,
        }
        Path(path).write_text(json.dumps(data))

    @classmethod
    def load_state(cls, path: str | Path) -> "ModelMonitor":
        """Load monitor state."""
        data = json.loads(Path(path).read_text())
        monitor = cls()
        monitor._predictions = data["predictions"]
        monitor._labels = data["labels"]
        monitor._feature_means = data["feature_means"]
        monitor._feature_stds = data["feature_stds"]
        monitor._initialized = len(monitor._predictions) >= 100
        return monitor


class EnsembleModel:
    """
    Ensemble of multiple models for improved robustness.

    Combines predictions from multiple models using weighted averaging.
    Supports online updates to all constituent models.
    """

    def __init__(
        self,
        models: list[OnlineLogisticModel],
        weights: list[float] | None = None,
        calibrator: ModelCalibrator | None = None,
    ) -> None:
        if not models:
            raise ValueError("At least one model required")
        self.models = models
        self.weights = weights or [1.0 / len(models)] * len(models)
        self.calibrator = calibrator

        if len(self.weights) != len(self.models):
            raise ValueError("Weights must match number of models")

        # Normalize weights
        total = sum(self.weights)
        self.weights = [w / total for w in self.weights]

    def predict_proba(self, features: dict[str, float]) -> float:
        """Predict probability using weighted ensemble."""
        probs = [model.predict_proba(features) for model in self.models]
        ensemble_prob = sum(p * w for p, w in zip(probs, self.weights))

        if self.calibrator and self.calibrator._fitted:
            ensemble_prob = self.calibrator.calibrate(ensemble_prob)

        return clamp(ensemble_prob, 1e-7, 1 - 1e-7)

    def update(self, features: dict[str, float], label: int, sample_weight: float = 1.0) -> list[float]:
        """Update all models in ensemble using experience replay.

        Each constituent model is updated via ``update_with_replay`` so
        that past experiences are replayed alongside the new sample,
        preventing catastrophic forgetting across the ensemble.
        """
        probs = []
        for model in self.models:
            prob = model.update_with_replay(features, label, sample_weight)
            probs.append(prob)
        return probs

    def update_weights(self, new_weights: list[float]) -> None:
        """Update ensemble weights."""
        if len(new_weights) != len(self.models):
            raise ValueError("Weights must match number of models")
        total = sum(new_weights)
        self.weights = [w / total for w in new_weights]

    def get_individual_predictions(self, features: dict[str, float]) -> list[float]:
        """Get predictions from each model."""
        return [model.predict_proba(features) for model in self.models]

    def clone(self) -> "EnsembleModel":
        """Create a copy of the ensemble."""
        return EnsembleModel(
            models=[m.clone() for m in self.models],
            weights=self.weights.copy(),
            calibrator=self.calibrator,
        )