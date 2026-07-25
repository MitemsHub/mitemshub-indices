"""Continuous improvement monitoring for autonomous research."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import numpy as np

from synthetic_trader.models.advanced import ModelMonitor, ModelMetrics
from synthetic_trader.research.knowledge.knowledge_base import KnowledgeBase


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ImprovementSignal:
    """A detected signal that something needs improvement."""
    signal_id: str
    signal_type: str  # feature_drift, performance_degradation, concept_drift, confidence_degradation
    severity: AlertSeverity
    title: str
    description: str
    evidence: Dict[str, Any]
    suggested_actions: List[str]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    acknowledged: bool = False
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FeatureHealthReport:
    """Health report for a specific feature."""
    feature_name: str
    importance_rank: int
    importance_score: float
    stability_score: float
    drift_detected: bool
    drift_magnitude: float
    correlation_with_target: float
    recent_importance: List[float]
    status: str  # healthy, degrading, drifted, unused
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelHealthReport:
    """Comprehensive model health report."""
    model_id: str
    timestamp: str
    overall_status: str  # healthy, warning, critical

    # Performance
    metrics: ModelMetrics

    # Calibration
    ece: float
    ece_trend: str  # improving, stable, degrading
    calibration_samples: int

    # Drift
    prediction_drift: float
    feature_drifts: Dict[str, float]
    max_feature_drift: float

    # Feature health
    feature_health: List[FeatureHealthReport]

    # Signals
    active_signals: List[ImprovementSignal]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "timestamp": self.timestamp,
            "overall_status": self.overall_status,
            "metrics": self.metrics.to_dict(),
            "ece": self.ece,
            "ece_trend": self.ece_trend,
            "calibration_samples": self.calibration_samples,
            "prediction_drift": self.prediction_drift,
            "feature_drifts": self.feature_drifts,
            "max_feature_drift": self.max_feature_drift,
            "feature_health": [f.to_dict() for f in self.feature_health],
            "active_signals": [s.to_dict() for s in self.active_signals],
        }


class ContinuousImprovementMonitor:
    """
    Monitors system health and generates actionable improvement signals.

    Detects:
    - Feature importance degradation
    - Model performance decline
    - Concept drift (regime changes)
    - Confidence calibration degradation
    - Signal quality deterioration
    """

    def __init__(
        self,
        storage_path: Path,
        knowledge_base: KnowledgeBase,
        model_monitor: ModelMonitor,
        feature_selector: Any = None,
        calibrator: Any = None,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_base = knowledge_base
        self.model_monitor = model_monitor
        self.feature_selector = feature_selector
        self.calibrator = calibrator

        self._signals: List[ImprovementSignal] = []
        self._feature_history: Dict[str, List[Dict]] = defaultdict(list)
        self._performance_history: List[Dict] = []
        self._last_check: Optional[datetime] = None

        # Thresholds
        self.thresholds = {
            "performance_drop_pct": 0.15,  # 15% drop in expectancy
            "ece_increase_pct": 0.50,  # 50% increase in ECE
            "prediction_drift": 0.15,  # KS statistic
            "feature_drift": 0.10,  # KS statistic per feature
            "stability_drop": 0.20,  # 20% drop in stability score
            "confidence_gap": 0.20,  # confidence vs actual outcome gap
        }

    def check_model_health(
        self,
        model_id: str,
        features_sample: List[Dict[str, float]],
    ) -> ModelHealthReport:
        """
        Comprehensive model health check.

        Args:
            model_id: Identifier for the model
            features_sample: Recent feature vectors for drift detection
        """
        # Get performance metrics
        metrics = self.model_monitor.get_performance()

        # Check drift
        drift = self.model_monitor.check_drift()
        prediction_drift = drift.get("prediction_drift", 0.0)
        feature_drifts = drift.get("feature_drifts", {})
        max_feature_drift = max(feature_drifts.values()) if feature_drifts else 0.0

        # Calibration check
        ece = metrics.ece
        ece_trend = self._calculate_ece_trend()

        # Feature health
        feature_health = self._assess_feature_health(features_sample, feature_drifts)

        # Generate signals
        signals = self._generate_signals(
            model_id, metrics, ece, prediction_drift, feature_drifts, feature_health
        )

        # Determine overall status
        overall_status = self._determine_overall_status(signals, metrics, ece)

        report = ModelHealthReport(
            model_id=model_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
            overall_status=overall_status,
            metrics=metrics,
            ece=ece,
            ece_trend=ece_trend,
            calibration_samples=len(self.model_monitor._labels) if hasattr(self.model_monitor, '_labels') else 0,
            prediction_drift=prediction_drift,
            feature_drifts=feature_drifts,
            max_feature_drift=max_feature_drift,
            feature_health=feature_health,
            active_signals=[s for s in signals if not s.resolved],
        )

        self._store_report(report)
        return report

    def _assess_feature_health(
        self,
        features_sample: List[Dict[str, float]],
        feature_drifts: Dict[str, float],
    ) -> List[FeatureHealthReport]:
        """Assess health of each feature."""
        if not self.feature_selector:
            return []

        report = self.feature_selector.get_importance(
            self.feature_selector.base_model
        ) if hasattr(self.feature_selector, 'base_model') else None

        if not report:
            return []

        health_reports = []
        for fi in report.features:
            drift = feature_drifts.get(fi.name, 0.0)
            stability = fi.stability_score

            # Determine status
            if fi.abs_weight < 1e-4:
                status = "unused"
            elif drift > self.thresholds["feature_drift"]:
                status = "drifted"
            elif stability < 0.3:
                status = "degrading"
            else:
                status = "healthy"

            health_reports.append(FeatureHealthReport(
                feature_name=fi.name,
                importance_rank=fi.rank,
                importance_score=fi.abs_weight,
                stability_score=stability,
                drift_detected=drift > self.thresholds["feature_drift"],
                drift_magnitude=drift,
                correlation_with_target=fi.contribution,
                recent_importance=[fi.abs_weight],  # Would track history
                status=status,
            ))

        return health_reports

    def _calculate_ece_trend(self) -> str:
        """Calculate ECE trend from history."""
        if len(self._performance_history) < 5:
            return "unknown"

        recent_ece = [h.get("ece", 0) for h in self._performance_history[-5:]]
        if len(recent_ece) < 2:
            return "unknown"

        trend = np.polyfit(range(len(recent_ece)), recent_ece, 1)[0]
        if trend < -0.001:
            return "improving"
        elif trend > 0.001:
            return "degrading"
        return "stable"

    def _generate_signals(
        self,
        model_id: str,
        metrics: ModelMetrics,
        ece: float,
        prediction_drift: float,
        feature_drifts: Dict[str, float],
        feature_health: List[FeatureHealthReport],
    ) -> List[ImprovementSignal]:
        """Generate improvement signals based on health checks."""
        signals = []

        # Performance degradation
        if metrics.expectancy_r < 0.1:
            signals.append(ImprovementSignal(
                signal_id=f"{model_id}_perf_{datetime.utcnow().timestamp()}",
                signal_type="performance_degradation",
                severity=AlertSeverity.WARNING if metrics.expectancy_r < 0 else AlertSeverity.CRITICAL,
                title="Model Expectancy Below Threshold",
                description=f"Model expectancy ({metrics.expectancy_r:.3f}R) is below minimum threshold",
                evidence={"expectancy_r": metrics.expectancy_r, "profit_factor": metrics.profit_factor},
                suggested_actions=[
                    "Review feature set for relevance",
                    "Check for regime change",
                    "Consider retraining with recent data",
                    "Evaluate alternative model architectures",
                ],
            ))

        # Calibration degradation
        if ece > 0.1:
            signals.append(ImprovementSignal(
                signal_id=f"{model_id}_cal_{datetime.utcnow().timestamp()}",
                signal_type="confidence_degradation",
                severity=AlertSeverity.WARNING,
                title="Calibration Quality Degraded",
                description=f"Expected Calibration Error ({ece:.4f}) exceeds threshold",
                evidence={"ece": ece, "brier_score": metrics.brier_score},
                suggested_actions=[
                    "Recalibrate with recent data",
                    "Increase calibration window",
                    "Consider isotonic regression over Platt",
                    "Check for distribution shift in predictions",
                ],
            ))

        # Prediction drift
        if prediction_drift > self.thresholds["prediction_drift"]:
            signals.append(ImprovementSignal(
                signal_id=f"{model_id}_drift_{datetime.utcnow().timestamp()}",
                signal_type="concept_drift",
                severity=AlertSeverity.WARNING,
                title="Prediction Distribution Drift Detected",
                description=f"KS statistic ({prediction_drift:.3f}) indicates distribution shift",
                evidence={"ks_statistic": prediction_drift, "threshold": self.thresholds["prediction_drift"]},
                suggested_actions=[
                    "Investigate market regime change",
                    "Retrain with recent data",
                    "Consider ensemble with adaptive weighting",
                    "Add regime-aware features",
                ],
            ))

        # Feature drift
        drifted_features = [name for name, drift in feature_drifts.items()
                           if drift > self.thresholds["feature_drift"]]
        if drifted_features:
            signals.append(ImprovementSignal(
                signal_id=f"{model_id}_featdrift_{datetime.utcnow().timestamp()}",
                signal_type="feature_drift",
                severity=AlertSeverity.WARNING,
                title=f"Feature Drift Detected: {len(drifted_features)} features",
                description=f"Features with significant drift: {', '.join(drifted_features)}",
                evidence={"drifted_features": drifted_features, "drifts": feature_drifts},
                suggested_actions=[
                    "Review feature engineering pipeline",
                    "Consider feature refresh/recalculation",
                    "Check data source quality",
                    "Evaluate feature robustness",
                ],
            ))

        # Unused/degrading features
        unhealthy_features = [f for f in feature_health if f.status in ("drifted", "degrading", "unused")]
        if unhealthy_features:
            signals.append(ImprovementSignal(
                signal_id=f"{model_id}_feathealth_{datetime.utcnow().timestamp()}",
                signal_type="feature_degradation",
                severity=AlertSeverity.INFO,
                title=f"{len(unhealthy_features)} Features Need Attention",
                description="Features are unused, drifted, or losing stability",
                evidence={
                    "unhealthy": [f.feature_name for f in unhealthy_features],
                    "details": {f.feature_name: f.status for f in unhealthy_features},
                },
                suggested_actions=[
                    "Prune unused features from model",
                    "Refresh drifted features",
                    "Investigate stability loss",
                    "Consider feature selection refresh",
                ],
            ))

        # Performance trend
        if len(self._performance_history) >= 10:
            recent_expectancy = [h.get("expectancy_r", 0) for h in self._performance_history[-10:]]
            trend = np.polyfit(range(len(recent_expectancy)), recent_expectancy, 1)[0]
            if trend < -0.01:
                signals.append(ImprovementSignal(
                    signal_id=f"{model_id}_trend_{datetime.utcnow().timestamp()}",
                    signal_type="performance_degradation",
                    severity=AlertSeverity.WARNING,
                    title="Negative Performance Trend",
                    description=f"Expectancy declining over last 10 periods (trend: {trend:.4f})",
                    evidence={"trend": trend, "recent_expectancy": recent_expectancy},
                    suggested_actions=[
                        "Analyze recent trades for pattern changes",
                        "Check for increased competition/regime shift",
                        "Consider model refresh",
                        "Review risk parameters",
                    ],
                ))

        return signals

    def _determine_overall_status(
        self,
        signals: List[ImprovementSignal],
        metrics: ModelMetrics,
        ece: float,
    ) -> str:
        """Determine overall model health status."""
        critical = any(s.severity == AlertSeverity.CRITICAL for s in signals)
        warning = any(s.severity == AlertSeverity.WARNING for s in signals)

        if critical:
            return "critical"
        if warning or metrics.expectancy_r < 0.15 or ece > 0.08:
            return "warning"
        return "healthy"

    def _store_report(self, report: ModelHealthReport) -> None:
        """Store health report for history."""
        file = self.storage_path / f"health_{report.model_id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        # Append to daily file
        reports = []
        if file.exists():
            try:
                reports = json.loads(file.read_text())
            except Exception:
                pass
        reports.append(report.to_dict())
        file.write_text(json.dumps(reports, indent=2))

    def get_active_signals(self) -> List[ImprovementSignal]:
        """Get all unresolved signals."""
        return [s for s in self._signals if not s.resolved]

    def acknowledge_signal(self, signal_id: str) -> bool:
        """Acknowledge a signal."""
        for s in self._signals:
            if s.signal_id == signal_id:
                s.acknowledged = True
                return True
        return False

    def resolve_signal(self, signal_id: str, resolution_note: str = "") -> bool:
        """Mark signal as resolved."""
        for s in self._signals:
            if s.signal_id == signal_id:
                s.resolved = True
                return True
        return False

    def generate_improvement_plan(self, model_id: str) -> Dict[str, Any]:
        """Generate actionable improvement plan based on current signals."""
        signals = [s for s in self._signals if not s.resolved and model_id in s.signal_id]

        plan = {
            "model_id": model_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "priority_actions": [],
            "investigations": [],
            "maintenance": [],
        }

        for signal in signals:
            action = {
                "signal_id": signal.signal_id,
                "type": signal.signal_type,
                "severity": signal.severity.value,
                "title": signal.title,
                "actions": signal.suggested_actions,
            }

            if signal.severity == AlertSeverity.CRITICAL:
                plan["priority_actions"].append(action)
            elif signal.severity == AlertSeverity.WARNING:
                plan["investigations"].append(action)
            else:
                plan["maintenance"].append(action)

        # Sort by severity
        plan["priority_actions"].sort(key=lambda a: a["severity"], reverse=True)

        return plan

    def record_performance_snapshot(self, metrics: ModelMetrics) -> None:
        """Record performance for trend analysis."""
        snapshot = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "expectancy_r": metrics.expectancy_r,
            "profit_factor": metrics.profit_factor,
            "win_rate": metrics.win_rate,
            "ece": metrics.ece,
            "brier_score": metrics.brier_score,
            "accuracy": metrics.accuracy,
        }
        self._performance_history.append(snapshot)

        # Keep last 1000
        if len(self._performance_history) > 1000:
            self._performance_history = self._performance_history[-1000:]

    def export_signals(self, output_path: Path) -> Path:
        """Export all signals to JSON."""
        data = [s.to_dict() for s in self._signals]
        output_path.write_text(json.dumps(data, indent=2))
        return output_path