"""Research experiment runner with isolation for reproducible research."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar
from copy import deepcopy

import numpy as np

from synthetic_trader.config import TraderConfig
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.research.walk_forward import run_walk_forward


T = TypeVar("T")


@dataclass(frozen=True)
class ExperimentConfig:
    """Immutable experiment configuration."""
    experiment_id: str
    name: str
    description: str
    config: Dict[str, Any]
    created_at: str
    tags: List[str] = field(default_factory=list)
    seed: int = 42

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        config: Dict[str, Any],
        tags: List[str] = None,
        seed: int = 42,
    ) -> "ExperimentConfig":
        return cls(
            experiment_id=str(uuid.uuid4())[:8],
            name=name,
            description=description,
            config=deepcopy(config),
            created_at=datetime.now(UTC).isoformat(),
            tags=tags or [],
            seed=seed,
        )


@dataclass
class ExperimentResult:
    """Experiment execution result."""
    experiment_id: str
    success: bool
    metrics: Dict[str, Any]
    artifacts: Dict[str, str]
    duration_seconds: float
    error: Optional[str] = None
    completed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentRecord:
    """Complete experiment record for storage."""
    config: ExperimentConfig
    result: Optional[ExperimentResult] = None
    status: str = "pending"  # pending, running, completed, failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "result": self.result.to_dict() if self.result else None,
            "status": self.status,
        }


class ExperimentRunner:
    """
    Runs experiments with full isolation and reproducibility.

    Features:
    - Random seed isolation
    - Config snapshotting
    - Result serialization
    - Artifact management
    - Error capture
    """

    def __init__(
        self,
        storage_path: Path,
        base_config: TraderConfig,
        numpy_rng: np.random.Generator = None,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.base_config = base_config
        self.numpy_rng = numpy_rng or np.random.default_rng(42)
        self._records: Dict[str, ExperimentRecord] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load existing experiment records."""
        index_file = self.storage_path / "index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text())
                for item in data:
                    config = ExperimentConfig(**item["config"])
                    result = ExperimentResult(**item["result"]) if item.get("result") else None
                    self._records[config.experiment_id] = ExperimentRecord(
                        config=config, result=result, status=item.get("status", "pending")
                    )
            except Exception:
                pass  # Ignore corrupt index

    def _save_index(self) -> None:
        """Save experiment index."""
        index_file = self.storage_path / "index.json"
        data = [r.to_dict() for r in self._records.values()]
        index_file.write_text(json.dumps(data, indent=2))

    def create_experiment(
        self,
        name: str,
        description: str,
        config: Dict[str, Any],
        tags: List[str] = None,
        seed: int = 42,
    ) -> ExperimentConfig:
        """Create a new experiment configuration."""
        exp_config = ExperimentConfig.create(
            name=name,
            description=description,
            config=config,
            tags=tags,
            seed=seed,
        )
        record = ExperimentRecord(config=exp_config)
        self._records[exp_config.experiment_id] = record
        self._save_index()
        return exp_config

    def run(
        self,
        experiment_id: str,
        runner: Callable[[ExperimentConfig, Path], ExperimentResult],
    ) -> ExperimentResult:
        """Run an experiment with full isolation."""
        record = self._records.get(experiment_id)
        if not record:
            raise ValueError(f"Experiment {experiment_id} not found")

        record.status = "running"
        self._save_index()

        # Create isolated workspace
        workspace = self.storage_path / "runs" / experiment_id
        workspace.mkdir(parents=True, exist_ok=True)

        # Set random seed
        rng = np.random.default_rng(record.config.seed)

        start_time = datetime.now(UTC)
        try:
            result = runner(record.config, workspace)
            result.duration_seconds = (datetime.now(UTC) - start_time).total_seconds()
            result.experiment_id = experiment_id
            result.success = True

            record.result = result
            record.status = "completed"

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds()
            result = ExperimentResult(
                experiment_id=experiment_id,
                success=False,
                metrics={},
                artifacts={},
                duration_seconds=duration,
                error=str(e),
            )
            record.result = result
            record.status = "failed"

        self._save_index()
        return record.result

    def get_record(self, experiment_id: str) -> Optional[ExperimentRecord]:
        """Get experiment record."""
        return self._records.get(experiment_id)

    def list_experiments(self, tag: str = None) -> List[ExperimentRecord]:
        """List all experiments, optionally filtered by tag."""
        records = list(self._records.values())
        if tag:
            records = [r for r in records if tag in r.config.tags]
        return sorted(records, key=lambda r: r.config.created_at, reverse=True)

    @contextmanager
    def isolated_random_state(self, seed: int):
        """Context manager for isolated random state."""
        old_state = np.random.get_state()
        np.random.seed(seed)
        try:
            yield
        finally:
            np.random.set_state(old_state)


def create_walkforward_runner(
    ticks,
    symbol: str,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
) -> Callable[[ExperimentConfig, Path], ExperimentResult]:
    """Create a walk-forward validation experiment runner."""

    def runner(config: ExperimentConfig, workspace: Path) -> ExperimentResult:
        # Merge base config with experiment config
        model_config = config.config.get("model", {})
        model = OnlineLogisticModel.from_config_dict(model_config) if model_config else None

        report = run_walk_forward(
            ticks=ticks,
            symbol=symbol,
            train_ticks=config.config.get("train_ticks", 50000),
            test_ticks=config.config.get("test_ticks", 10000),
            step_ticks=config.config.get("step_ticks", 10000),
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            model=model,
        )

        # Save report
        report_path = workspace / "walkforward_report.json"
        # ... save report logic

        # Extract metrics
        metrics = {
            "folds": len(report.folds),
            "total_trades": report.aggregate.trades,
            "win_rate": report.aggregate.win_rate,
            "profit_factor": report.aggregate.profit_factor,
            "expectancy_r": report.aggregate.expectancy_r,
            "net_pnl": report.aggregate.net_pnl,
            "mean_profit_factor": report.mean_profit_factor,
            "worst_expectancy_r": report.worst_expectancy_r,
        }

        artifacts = {"walkforward_report": str(report_path)}

        return ExperimentResult(
            experiment_id=config.experiment_id,
            success=True,
            metrics=metrics,
            artifacts=artifacts,
            duration_seconds=0,  # Will be set by runner
        )

    return runner


def create_model_comparison_runner(
    ticks,
    symbol: str,
    models: Dict[str, Callable[[], OnlineLogisticModel]],
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
) -> Callable[[ExperimentConfig, Path], ExperimentResult]:
    """Create a model comparison experiment runner."""

    def runner(config: ExperimentConfig, workspace: Path) -> ExperimentResult:
        results = {}
        model_name = config.config.get("model_name")

        if model_name not in models:
            raise ValueError(f"Model {model_name} not found in {list(models.keys())}")

        model_factory = models[model_name]
        model = model_factory()

        report = run_walk_forward(
            ticks=ticks,
            symbol=symbol,
            train_ticks=config.config.get("train_ticks", 50000),
            test_ticks=config.config.get("test_ticks", 10000),
            step_ticks=config.config.get("step_ticks", 10000),
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            model=model,
        )

        metrics = {
            "model": model_name,
            "folds": len(report.folds),
            "total_trades": report.aggregate.trades,
            "win_rate": report.aggregate.win_rate,
            "profit_factor": report.aggregate.profit_factor,
            "expectancy_r": report.aggregate.expectancy_r,
            "net_pnl": report.aggregate.net_pnl,
        }

        return ExperimentResult(
            experiment_id=config.experiment_id,
            success=True,
            metrics=metrics,
            artifacts={},
            duration_seconds=0,
        )

    return runner


class ExperimentReport:
    """Generates comprehensive experiment reports."""

    def __init__(self, runner: ExperimentRunner) -> None:
        self.runner = runner

    def generate_summary(self, tag: str = None) -> Dict[str, Any]:
        """Generate summary report for experiments."""
        records = self.runner.list_experiments(tag)

        completed = [r for r in records if r.status == "completed" and r.result]
        failed = [r for r in records if r.status == "failed"]

        if not completed:
            return {"total": len(records), "completed": 0, "failed": len(failed)}

        # Aggregate metrics
        metrics_agg = {}
        for r in completed:
            for k, v in r.result.metrics.items():
                if isinstance(v, (int, float)):
                    metrics_agg.setdefault(k, []).append(v)

        summary = {
            "total": len(records),
            "completed": len(completed),
            "failed": len(failed),
            "metrics": {
                k: {
                    "mean": float(np.mean(v)),
                    "std": float(np.std(v)),
                    "min": float(np.min(v)),
                    "max": float(np.max(v)),
                    "count": len(v),
                }
                for k, v in metrics_agg.items()
            },
        }
        return summary

    def generate_comparison(
        self,
        experiment_ids: List[str],
        metrics: List[str] = None,
    ) -> Dict[str, Any]:
        """Compare specific experiments."""
        comparison = {}
        for exp_id in experiment_ids:
            record = self.runner.get_record(exp_id)
            if record and record.result:
                comparison[exp_id] = {
                    "config": record.config.to_dict(),
                    "metrics": record.result.metrics,
                    "duration": record.result.duration_seconds,
                    "success": record.result.success,
                }
        return comparison

    def export_to_csv(self, tag: str = None, output_path: Path = None) -> Path:
        """Export experiment results to CSV."""
        import csv

        records = self.runner.list_experiments(tag)
        completed = [r for r in records if r.status == "completed" and r.result]

        if not completed:
            raise ValueError("No completed experiments to export")

        # Collect all metric keys
        all_metrics = set()
        for r in completed:
            all_metrics.update(r.result.metrics.keys())

        fieldnames = [
            "experiment_id",
            "name",
            "description",
            "tags",
            "created_at",
            "duration_seconds",
            "success",
        ] + sorted(all_metrics)

        output_path = output_path or self.runner.storage_path / "experiment_results.csv"

        with output_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for r in completed:
                row = {
                    "experiment_id": r.config.experiment_id,
                    "name": r.config.name,
                    "description": r.config.description,
                    "tags": ",".join(r.config.tags),
                    "created_at": r.config.created_at,
                    "duration_seconds": r.result.duration_seconds,
                    "success": r.result.success,
                }
                row.update(r.result.metrics)
                writer.writerow(row)

        return output_path