"""Research automation - plugin architecture for new ideas."""

from synthetic_trader.research.automation.module import (
    PluginManager,
    ResearchWorkflow,
    ExperimentTemplate,
    FeaturePlugin,
    ModelPlugin,
    RegimePlugin,
    ExecutionPlugin,
    AnalysisPlugin,
)

__all__ = [
    "PluginManager",
    "ResearchWorkflow",
    "ExperimentTemplate",
    "FeaturePlugin",
    "ModelPlugin",
    "RegimePlugin",
    "ExecutionPlugin",
    "AnalysisPlugin",
]