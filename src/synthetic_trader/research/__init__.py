"""Research package - quantitative research framework."""

from synthetic_trader.research.walk_forward import run_walk_forward, render_walk_forward_report, save_walk_forward_report
from synthetic_trader.research.knowledge import KnowledgeBase
from synthetic_trader.research.experiments.runner import ExperimentConfig, ExperimentResult, ExperimentRunner
from synthetic_trader.research.improvement.monitor import ContinuousImprovementMonitor, ImprovementSignal, ModelHealthReport
from synthetic_trader.research.automation import PluginManager, ResearchWorkflow, ExperimentTemplate, FeaturePlugin, ModelPlugin, RegimePlugin, ExecutionPlugin, AnalysisPlugin

__all__ = [
    "run_walk_forward",
    "render_walk_forward_report",
    "save_walk_forward_report",
    "KnowledgeBase",
    "ExperimentConfig",
    "ExperimentResult",
    "ExperimentRunner",
    "ContinuousImprovementMonitor",
    "ImprovementSignal",
    "ModelHealthReport",
    "PluginManager",
    "ResearchWorkflow",
    "ExperimentTemplate",
    "FeaturePlugin",
    "ModelPlugin",
    "RegimePlugin",
    "ExecutionPlugin",
    "AnalysisPlugin",
]