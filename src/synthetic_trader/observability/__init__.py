"""Observability and monitoring for the research platform."""

from __future__ import annotations

import json
import sys
import threading
import time
import warnings
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import numpy as np

from synthetic_trader.models.advanced import ModelMonitor, ModelMetrics

# Lazy imports — these research modules may not exist in all environments
# (e.g. CI, minimal installs, or when research deps are stripped).  Import
# them at module level but wrap in try/except so observability itself
# never crashes on import.
try:
    from synthetic_trader.research.experiments.runner import (
        ExperimentRunner,
        ExperimentResult,
    )
except Exception as exc:
    ExperimentRunner = None  # type: ignore[assignment,misc]
    ExperimentResult = None  # type: ignore[assignment,misc]
    warnings.warn(f"research.experiments.runner unavailable: {exc}", ImportWarning, stacklevel=2)

try:
    from synthetic_trader.research.improvement.monitor import (
        ContinuousImprovementMonitor,
    )
except Exception as exc:
    ContinuousImprovementMonitor = None  # type: ignore[assignment,misc]
    warnings.warn(f"research.improvement.monitor unavailable: {exc}", ImportWarning, stacklevel=2)


@dataclass
class SystemHealth:
    """System health snapshot."""
    timestamp: str
    status: str  # healthy, degraded, critical
    components: Dict[str, Dict[str, Any]]
    alerts: List[Dict[str, Any]]
    metrics: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceSnapshot:
    """Performance snapshot at a point in time."""
    timestamp: str
    model_metrics: ModelMetrics
    system_metrics: Dict[str, float]
    experiment_metrics: Dict[str, float]
    resource_usage: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "model_metrics": self.model_metrics.to_dict(),
            "system_metrics": self.system_metrics,
            "experiment_metrics": self.experiment_metrics,
            "resource_usage": self.resource_usage,
        }


class MetricsCollector:
    """Collects and aggregates metrics from all components."""

    def __init__(self, window_size: int = 1000) -> None:
        self.window_size = window_size
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1, tags: Dict[str, str] = None) -> None:
        """Increment a counter."""
        key = self._make_key(name, tags)
        with self._lock:
            self._counters[key] += value

    def gauge(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Set a gauge value."""
        key = self._make_key(name, tags)
        with self._lock:
            self._gauges[key] = value

    def histogram(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Record a histogram value."""
        key = self._make_key(name, tags)
        with self._lock:
            self._histograms[key].append(value)
            if len(self._histograms[key]) > self.window_size:
                self._histograms[key] = self._histograms[key][-self.window_size:]

    def timing(self, name: str, duration_ms: float, tags: Dict[str, str] = None) -> None:
        """Record a timing."""
        self.histogram(f"{name}_duration_ms", duration_ms, tags)

    def _make_key(self, name: str, tags: Dict[str, str] = None) -> str:
        if not tags:
            return name
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}{{{tag_str}}}"

    def get_counter(self, name: str, tags: Dict[str, str] = None) -> int:
        key = self._make_key(name, tags)
        return self._counters.get(key, 0)

    def get_gauge(self, name: str, tags: Dict[str, str] = None) -> Optional[float]:
        key = self._make_key(name, tags)
        return self._gauges.get(key)

    def get_histogram_stats(self, name: str, tags: Dict[str, str] = None) -> Dict[str, float]:
        key = self._make_key(name, tags)
        values = self._histograms.get(key, [])
        if not values:
            return {}
        arr = np.array(values)
        return {
            "count": len(arr),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
        }

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics as a snapshot."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: {
                        "count": len(v),
                        "mean": float(np.mean(v)) if v else 0,
                        "std": float(np.std(v)) if len(v) > 1 else 0,
                    }
                    for k, v in self._histograms.items()
                },
            }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._metrics.clear()
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


class SystemMonitor:
    """
    Comprehensive system monitoring.

    Tracks:
    - Model performance and health
    - Experiment execution
    - System resources
    - Research velocity
    - Decision quality
    """

    def __init__(
        self,
        storage_path: Path,
        model_monitor: ModelMonitor,
        experiment_runner: ExperimentRunner,
        improvement_monitor: ContinuousImprovementMonitor,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.model_monitor = model_monitor
        self.experiment_runner = experiment_runner
        self.improvement_monitor = improvement_monitor

        self.metrics = MetricsCollector()
        self._health_checks: List[Callable[[], Dict[str, Any]]] = []
        self._snapshots: deque = deque(maxlen=1000)
        self._alerts: List[Dict[str, Any]] = []
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

        # Register default health checks
        self.register_health_check("model", self._check_model_health)
        self.register_health_check("experiments", self._check_experiment_health)
        self.register_health_check("improvement", self._check_improvement_health)

    def register_health_check(self, name: str, check_fn: Callable[[], Dict[str, Any]]) -> None:
        """Register a health check function."""
        self._health_checks.append((name, check_fn))

    def _check_model_health(self) -> Dict[str, Any]:
        """Check model health."""
        metrics = self.model_monitor.get_performance()
        drift = self.model_monitor.check_drift()

        return {
            "status": "healthy" if metrics.expectancy_r > 0.1 else "degraded",
            "expectancy_r": metrics.expectancy_r,
            "profit_factor": metrics.profit_factor,
            "ece": metrics.ece,
            "prediction_drift": drift.get("prediction_drift", 0),
        }

    def _check_experiment_health(self) -> Dict[str, Any]:
        """Check experiment system health."""
        records = self.experiment_runner.list_experiments()
        running = [r for r in records if r.status == "running"]
        failed = [r for r in records if r.status == "failed"]

        return {
            "status": "healthy" if len(failed) == 0 else "warning",
            "total": len(records),
            "running": len(running),
            "completed": len([r for r in records if r.status == "completed"]),
            "failed": len(failed),
        }

    def _check_improvement_health(self) -> Dict[str, Any]:
        """Check improvement monitor health."""
        signals = self.improvement_monitor.get_active_signals()
        critical = [s for s in signals if s.severity.value == "critical"]

        return {
            "status": "critical" if critical else "healthy",
            "total_signals": len(signals),
            "critical": len(critical),
            "warning": len([s for s in signals if s.severity.value == "warning"]),
        }

    def run_health_checks(self) -> SystemHealth:
        """Run all health checks."""
        components = {}
        all_alerts = []

        for name, check_fn in self._health_checks:
            try:
                result = check_fn()
                components[name] = result
                if result.get("status") == "critical":
                    all_alerts.append({
                        "component": name,
                        "severity": "critical",
                        "message": f"{name} health check failed",
                        "details": result,
                    })
                elif result.get("status") == "warning":
                    all_alerts.append({
                        "component": name,
                        "severity": "warning",
                        "message": f"{name} health check warning",
                        "details": result,
                    })
            except Exception as e:
                components[name] = {"status": "error", "error": str(e)}
                all_alerts.append({
                    "component": name,
                    "severity": "critical",
                    "message": f"{name} health check error: {e}",
                })

        # Overall status
        if any(c.get("status") == "critical" for c in components.values()):
            status = "critical"
        elif any(c.get("status") in ("warning", "degraded") for c in components.values()):
            status = "degraded"
        else:
            status = "healthy"

        # System metrics
        metrics = {
            "uptime_seconds": time.time() - self._start_time if hasattr(self, '_start_time') else 0,
            "total_experiments": sum(1 for r in self.experiment_runner.list_experiments() if r.status == "completed"),
            "active_signals": len(self.improvement_monitor.get_active_signals()),
            "model_ece": self.model_monitor.get_performance().ece,
            "model_expectancy": self.model_monitor.get_performance().expectancy_r,
        }

        health = SystemHealth(
            timestamp=datetime.utcnow().isoformat() + "Z",
            status=status,
            components=components,
            alerts=all_alerts,
            metrics=metrics,
        )

        # Store snapshot
        self._snapshots.append({
            "timestamp": health.timestamp,
            "status": status,
            "components": components,
        })

        return health

    def record_metric(self, name: str, value: float, tags: Dict[str, str] = None) -> None:
        """Record a metric."""
        self.metrics.gauge(name, value, tags)

    def record_timing(self, name: str, duration_ms: float, tags: Dict[str, str] = None) -> None:
        """Record a timing."""
        self.metrics.timing(name, duration_ms, tags)

    def record_counter(self, name: str, value: int = 1, tags: Dict[str, str] = None) -> None:
        """Record a counter increment."""
        self.metrics.increment(name, value, tags)

    @contextmanager
    def timer(self, name: str, tags: Dict[str, str] = None):
        """Context manager for timing."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.record_timing(name, duration_ms, tags)

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get comprehensive metrics summary."""
        return self.metrics.get_all_metrics()

    def export_metrics(self, output_path: Path) -> Path:
        """Export all metrics to JSON."""
        data = self.metrics.get_all_metrics()
        output_path.write_text(json.dumps(data, indent=2))
        return output_path


class ResearchDashboard:
    """
    Generates research dashboard data for visualization.

    Provides data for:
    - Model performance trends
    - Experiment results
    - Feature importance evolution
    - Regime distribution
    - Decision quality
    - Research velocity
    """

    def __init__(
        self,
        experiment_runner: ExperimentRunner,
        knowledge_base: Any,
        model_monitor: ModelMonitor,
        improvement_monitor: ContinuousImprovementMonitor,
    ) -> None:
        self.experiment_runner = experiment_runner
        self.knowledge_base = knowledge_base
        self.model_monitor = model_monitor
        self.improvement_monitor = improvement_monitor

    def get_model_performance_data(self, days: int = 30) -> Dict[str, Any]:
        """Get model performance trend data."""
        metrics = self.model_monitor.get_performance()

        return {
            "current": {
                "expectancy_r": metrics.expectancy_r,
                "profit_factor": metrics.profit_factor,
                "win_rate": metrics.win_rate,
                "ece": metrics.ece,
                "brier_score": metrics.brier_score,
                "accuracy": metrics.accuracy,
                "trades": metrics.n_samples,
            },
            "trend": "improving",  # Would calculate from history
        }

    def get_experiment_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get experiment summary."""
        records = self.experiment_runner.list_experiments()

        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [
            r for r in records
            if datetime.fromisoformat(r.config.created_at.replace("Z", "+00:00")) > cutoff
        ]

        completed = [r for r in recent if r.status == "completed" and r.result]

        return {
            "total": len(recent),
            "completed": len(completed),
            "running": len([r for r in recent if r.status == "running"]),
            "failed": len([r for r in recent if r.status == "failed"]),
            "success_rate": len([r for r in completed if r.result.success]) / len(completed) if completed else 0,
            "avg_duration_seconds": np.mean([r.result.duration_seconds for r in completed]) if completed else 0,
            "by_type": self._group_by_tag(recent),
        }

    def get_feature_importance_trends(self, days: int = 30) -> Dict[str, Any]:
        """Get feature importance evolution."""
        return {
            "top_features": [],
            "stability_scores": {},
            "new_features": [],
            "degraded_features": [],
        }

    def get_regime_distribution(self, days: int = 30) -> Dict[str, Any]:
        """Get regime distribution."""
        return {
            "regimes": {},
            "transitions": [],
        }

    def get_decision_quality(self, days: int = 30) -> Dict[str, Any]:
        """Get decision quality metrics."""
        return {
            "avg_confidence": 0.0,
            "calibration_error": 0.0,
            "invalidation_rate": 0.0,
            "evidence_quality": 0.0,
        }

    def get_research_velocity(self, days: int = 30) -> Dict[str, Any]:
        """Get research velocity metrics."""
        return {
            "experiments_per_week": 0.0,
            "hypotheses_tested": 0,
            "features_deployed": 0,
            "models_promoted": 0,
            "time_to_insight_hours": 0.0,
        }

    def get_active_signals(self) -> List[Dict[str, Any]]:
        """Get active improvement signals."""
        signals = self.improvement_monitor.get_active_signals()
        return [s.to_dict() for s in signals]

    def _group_by_tag(self, records) -> Dict[str, int]:
        """Group records by tag."""
        groups = defaultdict(int)
        for r in records:
            for tag in r.config.tags:
                groups[tag] += 1
        return dict(groups)

    def generate_dashboard_data(self) -> Dict[str, Any]:
        """Generate complete dashboard data."""
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model_performance": self.get_model_performance_data(),
            "experiment_summary": self.get_experiment_summary(),
            "feature_importance": self.get_feature_importance_trends(),
            "regime_distribution": self.get_regime_distribution(),
            "decision_quality": self.get_decision_quality(),
            "research_velocity": self.get_research_velocity(),
            "active_signals": self.get_active_signals(),
        }

    def export_dashboard(self, output_path: Path) -> Path:
        """Export dashboard data as JSON."""
        data = self.generate_dashboard_data()
        output_path.write_text(json.dumps(data, indent=2))
        return output_path


class AlertManager:
    """Manages alerts and notifications."""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._alerts: List[Dict[str, Any]] = []
        self._rules: List[Dict[str, Any]] = []
        self._handlers: List[Callable[[Dict], None]] = []

    def add_rule(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
        severity: str,
        message_template: str,
        cooldown_seconds: int = 300,
    ) -> None:
        """Add an alert rule."""
        self._rules.append({
            "name": name,
            "condition": condition,
            "severity": severity,
            "message_template": message_template,
            "cooldown_seconds": cooldown_seconds,
            "last_triggered": None,
        })

    def add_handler(self, handler: Callable[[Dict], None]) -> None:
        """Add an alert handler."""
        self._handlers.append(handler)

    def check(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check all rules against metrics."""
        triggered = []
        now = time.time()

        for rule in self._rules:
            if rule["last_triggered"] and (now - rule["last_triggered"]) < rule["cooldown_seconds"]:
                continue

            try:
                if rule["condition"](metrics):
                    alert = {
                        "rule_name": rule["name"],
                        "severity": rule["severity"],
                        "message": rule["message_template"].format(**metrics),
                        "metrics": metrics,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    triggered.append(alert)
                    rule["last_triggered"] = now
            except Exception:
                pass

        # Dispatch to handlers
        for alert in triggered:
            for handler in self._handlers:
                try:
                    handler(alert)
                except Exception:
                    pass

        self._alerts.extend(triggered)
        return triggered

    def get_active_alerts(self, severity: str = None) -> List[Dict[str, Any]]:
        """Get active alerts."""
        alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]
        return sorted(alerts, key=lambda a: a["timestamp"], reverse=True)

    def resolve_alert(self, alert: Dict[str, Any]) -> None:
        """Mark alert as resolved."""
        alert["resolved"] = True
        alert["resolved_at"] = datetime.utcnow().isoformat() + "Z"


class ResearchReportGenerator:
    """Generates comprehensive research reports."""

    def __init__(
        self,
        experiment_runner: ExperimentRunner,
        knowledge_base: Any,
        model_monitor: ModelMonitor,
        improvement_monitor: ContinuousImprovementMonitor,
    ) -> None:
        self.experiment_runner = experiment_runner
        self.knowledge_base = knowledge_base
        self.model_monitor = model_monitor
        self.improvement_monitor = improvement_monitor

    def generate_weekly_report(self) -> Dict[str, Any]:
        """Generate weekly research report."""
        dashboard = ResearchDashboard(
            self.experiment_runner,
            self.knowledge_base,
            self.model_monitor,
            self.improvement_monitor,
        )

        return {
            "period": "weekly",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "executive_summary": self._generate_executive_summary(),
            "model_performance": dashboard.get_model_performance_data(),
            "experiments": dashboard.get_experiment_summary(days=7),
            "feature_evolution": dashboard.get_feature_importance_trends(days=7),
            "regime_analysis": dashboard.get_regime_distribution(days=7),
            "decision_quality": dashboard.get_decision_quality(days=7),
            "active_signals": dashboard.get_active_signals(),
            "knowledge_base": self._summarize_knowledge_base(),
        }

    def _generate_executive_summary(self) -> Dict[str, Any]:
        """Generate executive summary."""
        records = self.experiment_runner.list_experiments()
        completed = [r for r in records if r.status == "completed" and r.result]

        return {
            "total_experiments": len(records),
            "completed": len(completed),
            "successful": len([r for r in completed if r.result.success]),
            "key_insights": [
                "Add key insights from recent experiments"
            ],
            "recommendations": [
                "Add recommendations"
            ],
        }

    def _summarize_knowledge_base(self) -> Dict[str, int]:
        return {
            "notes": len(self.knowledge_base._notes),
            "decisions": len(self.knowledge_base._decisions),
            "rejected_ideas": len(self.knowledge_base._rejected),
            "future_ideas": len(self.knowledge_base._future),
            "experiments": len(self.knowledge_base._experiments),
        }

    def export_report(self, report: Dict[str, Any], output_path: Path) -> Path:
        """Export report as JSON and Markdown."""
        # JSON
        json_path = output_path.with_suffix(".json")
        json_path.write_text(json.dumps(report, indent=2))

        # Markdown
        md_path = output_path.with_suffix(".md")
        md_content = self._to_markdown(report)
        md_path.write_text(md_content)

        return json_path

    def _to_markdown(self, report: Dict[str, Any]) -> str:
        """Convert report to Markdown."""
        lines = [
            f"# Weekly Research Report",
            f"**Generated:** {report['generated_at']}",
            "",
            "## Executive Summary",
            f"- Total Experiments: {report['executive_summary']['total_experiments']}",
            f"- Completed: {report['executive_summary']['completed']}",
            f"- Successful: {report['executive_summary']['successful']}",
            "",
            "## Model Performance",
            f"- Expectancy: {report['model_performance']['current']['expectancy_r']:.3f}R",
            f"- Profit Factor: {report['model_performance']['current']['profit_factor']:.2f}",
            f"- Win Rate: {report['model_performance']['current']['win_rate']:.1%}",
            f"- ECE: {report['model_performance']['current']['ece']:.4f}",
            "",
            "## Experiments (Last 7 Days)",
            f"- Total: {report['experiments']['total']}",
            f"- Completed: {report['experiments']['completed']}",
            f"- Success Rate: {report['experiments']['success_rate']:.1%}",
            "",
            "## Active Signals",
        ]

        for signal in report["active_signals"]:
            lines.append(f"- **{signal['title']}** ({signal['severity']}): {signal['description']}")

        return "\n".join(lines)
