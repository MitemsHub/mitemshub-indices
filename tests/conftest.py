"""Shared test fixtures for the synthetic_trader test suite.

Clears module-level assembler caches between tests to prevent state
pollution — the GARCH forecaster, session filter, and fingerprint
detector caches in ``assembler.py`` retain mutable state from previous
``run_ticks`` / ``build_snapshot`` calls which can poison subsequent
WFO folds or backtest runs.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_assembler_caches():
    """Auto-clear assembler caches before every test."""
    from synthetic_trader.features.assembler import clear_assembler_caches

    clear_assembler_caches()
    yield
    clear_assembler_caches()
