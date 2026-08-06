"""Persistent guardian + plan memory across refreshes.

Every ``/api/calls/run`` spawns a fresh Python subprocess, so the in-process
guardian state (``_guardian_confirmed_at_tick``) is lost on every dashboard
refresh.  That is the root cause of the flip-flop the operator reported:

    plan = BUY confirmed → market dips a little → plan CANCELLED
    → refresh (new subprocess, state forgotten) → plan re-confirmed → repeat.

This module persists the guardian's wall-clock state per symbol to
``data/guardian_memory/{symbol}.json`` so a confirmed swing plan survives
process restarts, and so a genuinely cancelled plan cannot be resurrected by
a refresh.

The record doubles as the "current plan" store: ``build_watch_alert`` can
restore the original confirmed call when a fresh run momentarily produces a
stand_aside, standing by the call until the stop is traded through or the
hold horizon expires.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

# Override with SYNTH_GUARDIAN_MEMORY_DIR so the test suite can redirect
# writes away from the real data/guardian_memory directory (tests that run
# the full live pipeline would otherwise write live-plan state into the
# operator's data dir and leak it into the dashboard).
DEFAULT_MEMORY_DIR = Path("data/guardian_memory")


def _resolve_default_dir() -> Path:
    """Resolve the memory directory lazily at CALL time.

    Resolving at import time is fragile: whichever test module imports
    ``guardian_memory`` first (alphabetical order in a full-suite run) pins
    the default before ``test_live_market_snapshot`` can set the env var.
    Call-time resolution means ``SYNTH_GUARDIAN_MEMORY_DIR`` always takes
    effect no matter the import order.
    """
    return Path(os.environ.get("SYNTH_GUARDIAN_MEMORY_DIR", "data/guardian_memory"))


def memory_path(symbol: str, memory_dir: str | Path | None = None) -> Path:
    """Return the memory file path for a symbol."""
    base = Path(memory_dir) if memory_dir is not None else _resolve_default_dir()
    return base / f"{symbol}.json"

# Levels must match within this fraction of the stored entry for a freshly
# regenerated plan to be treated as "the same plan".  The strategy re-derives
# levels each run with small drift (observed ~0.5% on R_100); 1.5% separates
# a re-issued plan from a genuinely new setup while tolerating normal drift.
PLAN_MATCH_TOLERANCE = 0.015


def load_guardian_memory(
    symbol: str,
    memory_dir: str | Path | None = None,
) -> dict | None:
    """Load the persisted guardian/plan record for a symbol, or None."""
    path = memory_path(symbol, memory_dir)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # corrupt/partial write — treat as no memory
        logging.debug("[guardian_memory] failed to load %s: %s", path, exc)
        return None


def save_guardian_memory(
    symbol: str,
    record: dict,
    memory_dir: str | Path | None = None,
) -> None:
    """Persist the guardian/plan record for a symbol (best-effort)."""
    path = memory_path(symbol, memory_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {k: v for k, v in record.items() if v is not None}
        record.setdefault("updated_at_epoch", time.time())
        path.write_text(json.dumps(record), encoding="utf-8")
    except Exception as exc:
        logging.debug("[guardian_memory] failed to save %s: %s", path, exc)


def clear_guardian_memory(symbol: str, memory_dir: str | Path | None = None) -> None:
    """Delete the memory record for a symbol (best-effort)."""
    path = memory_path(symbol, memory_dir)
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:
        logging.debug("[guardian_memory] failed to clear %s: %s", path, exc)


def plan_matches(
    memory: dict | None,
    *,
    direction: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
    tolerance: float = PLAN_MATCH_TOLERANCE,
) -> bool:
    """True when a freshly generated plan is "the same plan" as the memory.

    Matching requires the same direction and all three levels within a
    tolerance of the stored entry.  A materially different setup (new entry,
    new stop, new target) does not match and starts fresh guardian state.
    """
    if not memory:
        return False
    if memory.get("direction") != direction:
        return False
    m_entry = memory.get("entry")
    m_stop = memory.get("stop")
    m_target = memory.get("target")
    if m_entry is None or m_stop is None or m_target is None:
        return False
    if entry is None or stop is None or target is None:
        return False
    try:
        m_entry = float(m_entry)
        m_stop = float(m_stop)
        m_target = float(m_target)
        entry = float(entry)
        stop = float(stop)
        target = float(target)
    except (TypeError, ValueError):
        return False
    if m_entry <= 0:
        return False
    tol = max(tolerance * abs(m_entry), 1e-9)
    return (
        abs(entry - m_entry) <= tol
        and abs(stop - m_stop) <= tol
        and abs(target - m_target) <= tol
    )
