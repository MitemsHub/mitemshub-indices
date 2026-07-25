"""Tests for Phase 5 - Research Framework components."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from synthetic_trader.config import TraderConfig
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.models.advanced import FeatureSelector
from synthetic_trader.research.knowledge import (
    KnowledgeBase,
    ResearchNote,
    DecisionRecord,
    ExperimentSummary,
    RejectedIdea,
    FutureIdea,
)
from synthetic_trader.research.experiments.runner import ExperimentConfig, ExperimentRunner
from synthetic_trader.research.improvement.monitor import ContinuousImprovementMonitor, ModelMonitor
from synthetic_trader.research.automation import PluginManager, ResearchWorkflow, ExperimentTemplate


def test_knowledge_base_notes() -> None:
    """Test knowledge base research notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(Path(tmpdir))

        # Add note
        note = kb.add_note(
            title="Feature Test",
            content="Testing feature importance",
            category="feature",
            tags=["test", "importance"],
            experiment_ids=["exp_001"],
            confidence=0.8,
        )

        assert note.note_id is not None
        assert note.title == "Feature Test"
        assert note.category == "feature"
        assert note.confidence == 0.8

        # Search notes
        results = kb.search_notes(category="feature")
        assert len(results) == 1

        results = kb.search_notes(query="importance")
        assert len(results) == 1

        results = kb.search_notes(min_confidence=0.9)
        assert len(results) == 0

        results = kb.search_notes(min_confidence=0.7)
        assert len(results) == 1


def test_knowledge_base_decisions() -> None:
    """Test knowledge base decision recording."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(Path(tmpdir))

        decision = kb.add_decision(
            title="Use Isotonic Calibration",
            context="Model ECE was 0.12 with Platt scaling",
            decision="Switch to isotonic regression",
            rationale="Better calibration for non-linear probability distortions",
            alternatives=["Platt scaling", "No calibration"],
            tradeoffs={"pros": "Better ECE", "cons": "Requires more samples"},
            experiment_ids=["exp_001"],
        )

        assert decision.decision_id is not None
        assert decision.status == "active"

        # Supersede
        new_decision = kb.add_decision(
            title="Use Temperature Scaling",
            context="Isotonic overfits on small samples",
            decision="Switch to temperature scaling",
            rationale="More robust with fewer samples",
            experiment_ids=["exp_002"],
        )

        kb.supersede_decision(decision.decision_id, new_decision.decision_id)
        assert decision.status == "superseded"
        assert new_decision.status == "active"


def test_knowledge_base_experiments() -> None:
    """Test experiment summaries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(Path(tmpdir))

        kb.summarize_experiment(
            experiment_id="exp_001",
            name="Feature Ablation Test",
            hypothesis="Removing feature X improves performance",
            result="rejected",
            key_findings=["Feature X contributes 15% to expectancy"],
            metrics={"expectancy_r": 0.12, "profit_factor": 1.4},
            lessons_learned="Feature X is important for regime detection",
            follow_up=["Test feature X with different window sizes"],
        )

        exp = kb.get_experiment("exp_001")
        assert exp is not None
        assert exp.result == "rejected"
        assert exp.key_findings[0] == "Feature X contributes 15% to expectancy"

        # List experiments
        experiments = kb.list_experiments(result="rejected")
        assert len(experiments) == 1


def test_knowledge_base_rejected_ideas() -> None:
    """Test rejected ideas tracking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(Path(tmpdir))

        kb.record_rejection(
            title="Add RSI Feature",
            description="Add RSI(14) as feature",
            reason_rejected="No improvement in walk-forward",
            experiment_id="exp_001",
            notes="RSI correlated with existing momentum features",
        )

        rejected = kb.was_rejected(description="RSI")
        assert len(rejected) == 1
        assert rejected[0].reason_rejected == "No improvement in walk-forward"


def test_knowledge_base_future_ideas() -> None:
    """Test future ideas backlog."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(Path(tmpdir))

        kb.add_future_idea(
            title="Transformer Model",
            description="Test transformer architecture for sequence modeling",
            category="model",
            priority="high",
            estimated_effort="high",
            dependencies=["data_pipeline", "feature_store"],
        )

        ideas = kb.list_future_ideas(category="model", priority="high")
        assert len(ideas) == 1
        assert ideas[0].title == "Transformer Model"


def test_knowledge_base_export() -> None:
    """Test knowledge base export to markdown."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = KnowledgeBase(Path(tmpdir))

        kb.add_note("Test Note", "Content here", "feature", tags=["test"])
        kb.add_decision("Decision", "Context", "Decision", "Rationale")
        kb.summarize_experiment("exp1", "Test", "Hypothesis", "confirmed", ["Finding"], {"metric": 1.0}, "Lesson")

        output = Path(tmpdir) / "report.md"
        kb.export_knowledge_report(output)

        content = output.read_text()
        assert "Test Note" in content
        assert "Decision" in content
        assert "exp1" in content


def test_experiment_runner() -> None:
    """Test experiment runner basic functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = TraderConfig.default()
        runner = ExperimentRunner(Path(tmpdir) / "experiments", config)

        exp_config = runner.create_experiment(
            name="Test Experiment",
            description="Test hypothesis",
            config={"train_ticks": 1000, "test_ticks": 200},
            tags=["test"],
            seed=42,
        )

        assert exp_config.experiment_id is not None
        assert exp_config.name == "Test Experiment"

        record = runner.get_record(exp_config.experiment_id)
        assert record is not None
        assert record.status == "pending"


def test_feature_selector() -> None:
    """Test feature selector functionality."""
    model = OnlineLogisticModel()
    model.weights = {
        "feature_a": 0.5,
        "feature_b": -0.3,
        "feature_c": 0.0005,  # below threshold
        "feature_d": 0.0,
    }

    selector = FeatureSelector(min_weight_magnitude=1e-3)
    selector.update(model)
    report = selector.get_importance(model)

    assert report.total_features == 4
    assert "feature_c" in report.unused_features
    assert "feature_d" in report.unused_features

    # Filter features - pass model to use model weights for threshold
    features = {"feature_a": 1.0, "feature_b": 2.0, "feature_c": 3.0}
    filtered = selector.filter_features(features, model)
    assert "feature_c" not in filtered
    assert "feature_a" in filtered


def test_model_monitor() -> None:
    """Test model monitor basic functionality."""
    monitor = ModelMonitor(window_size=100)

    for _ in range(150):
        features = {"feat_1": np.random.randn(), "feat_2": np.random.randn()}
        pred = 0.3 + 0.4 * np.random.random()
        label = np.random.binomial(1, 0.5)
        monitor.record(features, pred, label)

    assert monitor._initialized

    # Check drift
    drift = monitor.check_drift()
    assert "drift_detected" in drift
    assert "prediction_drift" in drift

    # Get performance
    metrics = monitor.get_performance()
    assert metrics.n_samples > 0


def test_experiment_templates() -> None:
    """Test experiment template creation."""
    # Feature ablation
    template = ExperimentTemplate.feature_ablation(
        name="Feature Ablation Test",
        base_features=["f1", "f2", "f3"],
        test_features=["f4", "f5"],
    )
    assert template["type"] == "feature_ablation"
    assert template["base_features"] == ["f1", "f2", "f3"]

    # Regime specific
    template = ExperimentTemplate.regime_specific(
        name="Trend Regime Test",
        regime="trend_up",
    )
    assert template["regime"] == "trend_up"

    # Model comparison
    template = ExperimentTemplate.model_comparison(
        name="Model Comparison",
        models=["model_a", "model_b"],
    )
    assert template["models"] == ["model_a", "model_b"]

    # Parameter sweep
    template = ExperimentTemplate.parameter_sweep(
        name="LR Sweep",
        param_name="learning_rate",
        values=[0.01, 0.05, 0.1],
        fixed_config={"l2": 0.001},
    )
    assert template["param_name"] == "learning_rate"
    assert template["values"] == [0.01, 0.05, 0.1]

    # Feature interaction
    template = ExperimentTemplate.feature_interaction(
        name="Interaction Test",
        feature_pairs=[("f1", "f2"), ("f2", "f3")],
    )
    assert template["feature_pairs"] == [("f1", "f2"), ("f2", "f3")]


def test_plugin_manager() -> None:
    """Test plugin manager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PluginManager(Path(tmpdir) / "plugins")

        # Register a plugin
        pm.register(
            name="test_feature",
            version="1.0",
            description="Test feature plugin",
            author="test",
            category="feature",
            entry_point="test_module:TestPlugin",
            config_schema={"param1": {"type": "float"}},
        )

        # List plugins
        plugins = pm.list_plugins(category="feature")
        assert len(plugins) == 1
        assert plugins[0].name == "test_feature"


def test_research_workflow() -> None:
    """Test research workflow orchestration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = TraderConfig.default()
        ticks = []  # Empty for testing

        from synthetic_trader.research.knowledge import KnowledgeBase
        kb = KnowledgeBase(Path(tmpdir) / "knowledge")

        workflow = ResearchWorkflow(
            storage_path=Path(tmpdir) / "research",
            base_config=config,
            ticks=ticks,
            symbol="R_75",
            knowledge_base=kb,
        )

        # Propose hypothesis
        exp_config = workflow.propose_hypothesis(
            title="Test Hypothesis",
            hypothesis="Feature X improves expectancy",
            category="feature",
            experiment_type="feature_ablation",
            experiment_config={"train_ticks": 1000, "test_ticks": 200},
        )

        assert exp_config.experiment_id is not None

        # Check timeline
        timeline = workflow.get_research_timeline()
        assert len(timeline) >= 1
        assert timeline[0]["type"] == "experiment"


if __name__ == "__main__":
    test_knowledge_base_notes()
    test_knowledge_base_decisions()
    test_knowledge_base_experiments()
    test_knowledge_base_rejected_ideas()
    test_knowledge_base_future_ideas()
    test_knowledge_base_export()
    test_experiment_runner()
    test_feature_selector()
    test_continuous_improvement_monitor()
    test_model_monitor()
    test_experiment_templates()
    test_plugin_manager()
    test_research_workflow()
    print("All Phase 5 tests passed!")