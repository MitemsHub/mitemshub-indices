"""Research automation - plugin architecture for new ideas."""

from __future__ import annotations

import importlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

import numpy as np

from synthetic_trader.config import TraderConfig
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.research.experiments.runner import (
    ExperimentConfig,
    ExperimentResult,
    ExperimentRunner,
)
from synthetic_trader.research.knowledge import KnowledgeBase


@dataclass
class ResearchPlugin:
    """A research plugin that can be dynamically loaded."""
    name: str
    version: str
    description: str
    author: str
    category: str  # feature, model, regime, execution, analysis
    entry_point: str  # module:function
    config_schema: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    enabled: bool = True


class PluginInterface(ABC):
    """Base interface for all research plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Plugin description."""

    @property
    @abstractmethod
    def category(self) -> str:
        """Plugin category."""

    @property
    def config_schema(self) -> Dict[str, Any]:
        """JSON schema for plugin configuration."""
        return {}

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate plugin configuration. Returns (valid, errors)."""
        pass

    @abstractmethod
    def run(
        self,
        config: Dict[str, Any],
        context: "PluginContext",
    ) -> "PluginResult":
        """Run the plugin. Returns PluginResult."""
        pass


@dataclass
class PluginContext:
    """Context provided to plugins during execution."""
    storage_path: Path
    base_config: TraderConfig
    ticks: Any
    symbol: str
    timeframe_sec: int
    knowledge_base: KnowledgeBase
    rng: np.random.Generator
    artifacts: Dict[str, Path] = field(default_factory=dict)


@dataclass
class PluginResult:
    """Result of plugin execution."""
    success: bool
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Path] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class FeaturePlugin(PluginInterface):
    """Base class for feature engineering plugins."""

    @property
    def category(self) -> str:
        return "feature"

    @abstractmethod
    def compute(
        self,
        candles: List[Any],
        config: Dict[str, Any],
    ) -> Dict[str, float]:
        """Compute feature values from candles."""
        pass


class ModelPlugin(PluginInterface):
    """Base class for model plugins."""

    @property
    def category(self) -> str:
        return "model"

    @abstractmethod
    def create_model(self, config: Dict[str, Any]) -> OnlineLogisticModel:
        """Create a new model instance."""
        pass

    @abstractmethod
    def train(
        self,
        model: OnlineLogisticModel,
        features: List[Dict[str, float]],
        labels: List[int],
    ) -> None:
        """Train the model."""
        pass


class RegimePlugin(PluginInterface):
    """Base class for regime detection plugins."""

    @property
    def category(self) -> str:
        return "regime"

    @abstractmethod
    def classify(
        self,
        candles: List[Any],
        config: Dict[str, Any],
    ) -> Tuple[str, Dict[str, float], List[str]]:
        """Classify regime. Returns (regime_name, features, notes)."""
        pass


class ExecutionPlugin(PluginInterface):
    """Base class for execution strategy plugins."""

    @property
    def category(self) -> str:
        return "execution"

    @abstractmethod
    def build_plan(
        self,
        signal: Any,
        candles: List[Any],
        config: Dict[str, Any],
    ) -> Any:
        """Build execution plan from signal."""
        pass


class AnalysisPlugin(PluginInterface):
    """Base class for analysis/reporting plugins."""

    @property
    def category(self) -> str:
        return "analysis"

    @abstractmethod
    def analyze(
        self,
        data: Any,
        config: Dict[str, Any],
    ) -> PluginResult:
        """Analyze data and return result."""
        pass


class PluginManager:
    """
    Manages research plugins - discovery, loading, validation, execution.
    """

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._plugins: Dict[str, PluginInterface] = {}
        self._manifest: Dict[str, ResearchPlugin] = {}
        self._load_manifest()

    def _load_manifest(self) -> None:
        """Load plugin manifest."""
        manifest_file = self.plugins_dir / "manifest.json"
        if manifest_file.exists():
            try:
                data = json.loads(manifest_file.read_text())
                for item in data:
                    plugin = ResearchPlugin(**item)
                    self._manifest[plugin.name] = plugin
            except Exception:
                pass

    def _save_manifest(self) -> None:
        """Save plugin manifest."""
        manifest_file = self.plugins_dir / "manifest.json"
        data = [asdict(p) for p in self._manifest.values()]
        manifest_file.write_text(json.dumps(data, indent=2))

    def register(
        self,
        name: str,
        version: str,
        description: str,
        author: str,
        category: str,
        entry_point: str,
        config_schema: Dict[str, Any] = None,
        dependencies: List[str] = None,
    ) -> ResearchPlugin:
        """Register a new plugin."""
        plugin = ResearchPlugin(
            name=name,
            version=version,
            description=description,
            author=author,
            category=category,
            entry_point=entry_point,
            config_schema=config_schema or {},
            dependencies=dependencies or [],
        )
        self._manifest[name] = plugin
        self._save_manifest()
        return plugin

    def load_plugin(self, name: str) -> Optional[PluginInterface]:
        """Load a plugin by name."""
        if name in self._plugins:
            return self._plugins[name]

        if name not in self._manifest:
            return None

        plugin_info = self._manifest[name]
        if not plugin_info.enabled:
            return None

        # Load from entry point
        try:
            module_path, class_name = plugin_info.entry_point.rsplit(":", 1)
            module = importlib.import_module(module_path)
            plugin_class = getattr(module, class_name)
            plugin = plugin_class()
            self._plugins[name] = plugin
            return plugin
        except Exception as e:
            print(f"Failed to load plugin {name}: {e}")
            return None

    def load_all(self) -> Dict[str, PluginInterface]:
        """Load all enabled plugins."""
        for name, info in self._manifest.items():
            if info.enabled:
                self.load_plugin(name)
        return self._plugins

    def get_plugin(self, name: str) -> Optional[PluginInterface]:
        """Get loaded plugin."""
        return self._plugins.get(name)

    def list_plugins(self, category: str = None) -> List[ResearchPlugin]:
        """List registered plugins."""
        plugins = list(self._manifest.values())
        if category:
            plugins = [p for p in plugins if p.category == category]
        return plugins

    def validate_all(self) -> Dict[str, List[str]]:
        """Validate all plugin configurations."""
        results = {}
        for name, info in self._manifest.items():
            if not info.enabled:
                continue
            plugin = self.load_plugin(name)
            if plugin:
                valid, errors = plugin.validate_config({})
                if not valid:
                    results[name] = errors
        return results


class ExperimentTemplate:
    """
    Template for common experiment patterns.
    Allows quick creation of standard experiment types.
    """

    @staticmethod
    def feature_ablation(
        name: str,
        base_features: List[str],
        test_features: List[str],
        target_metric: str = "expectancy_r",
    ) -> Dict[str, Any]:
        """Create feature ablation experiment config."""
        return {
            "name": name,
            "type": "feature_ablation",
            "base_features": base_features,
            "test_features": test_features,
            "target_metric": target_metric,
            "config": {
                "train_ticks": 50000,
                "test_ticks": 10000,
                "step_ticks": 10000,
            },
        }

    @staticmethod
    def regime_specific(
        name: str,
        regime: str,
        train_ticks: int = 30000,
    ) -> Dict[str, Any]:
        """Create regime-specific training experiment."""
        return {
            "name": name,
            "type": "regime_specific",
            "regime": regime,
            "config": {
                "train_ticks": train_ticks,
                "test_ticks": 10000,
                "step_ticks": 5000,
                "regime_filter": regime,
            },
        }

    @staticmethod
    def model_comparison(
        name: str,
        models: List[str],
        train_ticks: int = 50000,
    ) -> Dict[str, Any]:
        """Create model comparison experiment."""
        return {
            "name": name,
            "type": "model_comparison",
            "models": models,
            "config": {
                "train_ticks": train_ticks,
                "test_ticks": 10000,
                "step_ticks": 10000,
            },
        }

    @staticmethod
    def parameter_sweep(
        name: str,
        param_name: str,
        values: List[Any],
        fixed_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create parameter sweep experiment."""
        return {
            "name": name,
            "type": "parameter_sweep",
            "param_name": param_name,
            "values": values,
            "fixed_config": fixed_config,
        }

    @staticmethod
    def feature_interaction(
        name: str,
        feature_pairs: List[Tuple[str, str]],
    ) -> Dict[str, Any]:
        """Create feature interaction experiment."""
        return {
            "name": name,
            "type": "feature_interaction",
            "feature_pairs": feature_pairs,
            "config": {
                "train_ticks": 50000,
                "test_ticks": 10000,
                "step_ticks": 10000,
            },
        }


class ResearchWorkflow:
    """
    Orchestrates end-to-end research workflow.

    1. Ideation -> Hypothesis
    2. Experiment Design
    3. Execution
    4. Analysis
    4. Knowledge Capture
    5. Decision/Iteration
    """

    def __init__(
        self,
        storage_path: Path,
        base_config: TraderConfig,
        ticks: Any,
        symbol: str,
        knowledge_base: KnowledgeBase,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.base_config = base_config
        self.ticks = ticks
        self.symbol = symbol
        self.knowledge_base = knowledge_base

        self.runner = ExperimentRunner(
            storage_path=self.storage_path / "experiments",
            base_config=base_config,
        )
        self.plugin_manager = PluginManager(self.storage_path / "plugins")
        self.plugin_manager.load_all()

    def propose_hypothesis(
        self,
        title: str,
        hypothesis: str,
        category: str,
        experiment_type: str,
        experiment_config: Dict[str, Any],
    ) -> ExperimentConfig:
        """Propose a new hypothesis and create experiment."""
        # Check if similar was rejected
        rejected = self.knowledge_base.was_rejected(description=hypothesis)
        if rejected:
            print(f"⚠️ Similar idea was rejected: {rejected[0].reason_rejected}")

        # Create experiment
        exp_config = self.runner.create_experiment(
            name=title,
            description=hypothesis,
            config=experiment_config,
            tags=[category, experiment_type],
        )

        # Summarize experiment in knowledge base
        self.knowledge_base.summarize_experiment(
            experiment_id=exp_config.experiment_id,
            name=title,
            hypothesis=hypothesis,
            result="pending",
            key_findings=[],
            metrics={},
            lessons_learned="",
            follow_up=[],
        )

        # Log hypothesis
        self.knowledge_base.add_note(
            title=f"Hypothesis: {title}",
            content=hypothesis,
            category="hypothesis",
            tags=[category, experiment_type],
            experiment_ids=[exp_config.experiment_id],
            confidence=0.5,
        )

        return exp_config

    def run_experiment(
        self,
        experiment_id: str,
        runner_fn: Callable[[ExperimentConfig, Path], ExperimentResult],
    ) -> ExperimentResult:
        """Run an experiment."""
        result = self.runner.run(experiment_id, runner_fn)
        return result

    def analyze_results(
        self,
        experiment_id: str,
        analysis_fn: Callable[[ExperimentResult], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze experiment results."""
        record = self.runner.get_record(experiment_id)
        if not record or not record.result:
            raise ValueError(f"Experiment {experiment_id} not found or not completed")

        return analysis_fn(record.result)

    def conclude_experiment(
        self,
        experiment_id: str,
        result: str,
        key_findings: List[str],
        lessons_learned: str,
        follow_up: List[str] = None,
    ) -> None:
        """Conclude experiment and capture knowledge."""
        record = self.runner.get_record(experiment_id)
        if not record:
            raise ValueError(f"Experiment {experiment_id} not found")

        metrics = record.result.metrics if record.result else {}

        self.knowledge_base.summarize_experiment(
            experiment_id=experiment_id,
            name=record.config.name,
            hypothesis=record.config.description,
            result=result,
            key_findings=key_findings,
            metrics=metrics,
            lessons_learned=lessons_learned,
            follow_up=follow_up or [],
        )

        # Record rejection if applicable
        if result == "rejected":
            self.knowledge_base.record_rejection(
                title=record.config.name,
                description=record.config.description,
                reason_rejected="Experiment did not confirm hypothesis",
                experiment_id=experiment_id,
            )

        # Record lessons
        if lessons_learned:
            self.knowledge_base.create_lesson(
                title=f"Lesson from {record.config.name}",
                situation=f"Experiment {experiment_id} ({record.config.name})",
                lesson=lessons_learned,
                action="Apply to future experiments",
                experiment_ids=[experiment_id],
            )

    def iterate(
        self,
        experiment_id: str,
        modifications: Dict[str, Any],
    ) -> ExperimentConfig:
        """Create next iteration based on previous experiment."""
        record = self.runner.get_record(experiment_id)
        if not record:
            raise ValueError(f"Experiment {experiment_id} not found")

        # Merge modifications with previous config
        new_config = {**record.config.config, **modifications}

        # Create new experiment
        return self.propose_hypothesis(
            title=f"{record.config.name} (v{len(self.runner.list_experiments()) + 1})",
            hypothesis=f"Refined from {experiment_id}: {record.config.description}",
            category=record.config.tags[0] if record.config.tags else "iteration",
            experiment_type="iteration",
            experiment_config=new_config,
        )

    def get_research_timeline(self) -> List[Dict[str, Any]]:
        """Get timeline of all research activities."""
        timeline = []

        # Experiments
        for exp in self.knowledge_base.list_experiments():
            timeline.append({
                "type": "experiment",
                "id": exp.experiment_id,
                "name": exp.name,
                "result": exp.result,
                "date": exp.created_at,
            })

        # Decisions
        for dec in self.knowledge_base.list_decisions("active"):
            timeline.append({
                "type": "decision",
                "id": dec.decision_id,
                "title": dec.title,
                "date": dec.created_at,
            })

        # Notes
        for note in self.knowledge_base.search_notes():
            timeline.append({
                "type": "note",
                "id": note.note_id,
                "title": note.title,
                "category": note.category,
                "date": note.updated_at,
            })

        # Sort by date ascending (oldest first), with type priority as tiebreaker
        # Order: experiment (0) < decision (1) < note (2)
        type_priority = {"experiment": 0, "decision": 1, "note": 2}
        return sorted(timeline, key=lambda x: (x["date"], type_priority.get(x["type"], 3)))