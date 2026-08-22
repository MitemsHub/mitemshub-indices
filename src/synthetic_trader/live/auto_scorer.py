"""Automatic live-call scoring service (target/stop/neither).

The Stage-3 empirical gate (``stage3_gate``) is only as honest as the scored
outcomes journal behind it.  This service keeps that journal current **without
manual intervention**: on a loop it scores every unresolved live call whose
hold horizon has elapsed, using the exact same market-data machinery as the
manual ``score-live-calibration`` command
(:func:`~synthetic_trader.live.calibration_scorer.run_score_unresolved_records_from_market`).

Together with the auto-logging in ``run_live_watch`` (every emitted alert is
appended to the calls journal), this closes the loop the per-call-type gate
needs:

    live call emitted  ->  calls journal  ->  auto-scorer sweeps  ->
    outcomes journal (target/stop/neither)  ->  gate surfaces/suppresses

Design:

- **Incremental and idempotent.**  ``score_unresolved_records_from_market``
  dedupes by ``(symbol, generated_at)`` against the existing outcomes journal,
  so overlapping sweeps and restarts never double-score.
- **Hold-window aware.**  A call is only scored once its hold horizon has
  elapsed (``hold_horizon_minutes``, default 60) — scoring early would measure
  an unfinished outcome.
- **Cron friendly.**  ``run_once=True`` performs a single sweep and exits —
  pair it with Task Scheduler / cron for a periodic scoring job without a
  resident process.
- **Status telemetry.**  A JSON status file (``data/auto_scorer.json``) is
  rewritten after every sweep so the operator can see per-sweep scored counts
  and the pending backlog.
- **Resilient.**  A failed sweep (Deriv unavailable, token missing) is recorded
  on the status and retried with backoff; after ``MAX_CONSECUTIVE_ERRORS`` the
  loop gives up rather than spin forever.

Usage::

    python -m synthetic_trader.cli score-live-loop                     # sweep every 5 min
    python -m synthetic_trader.cli score-live-loop --once              # single sweep (cron)
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from synthetic_trader.live.calibration_scorer import (
    run_score_unresolved_records_from_market,
)

# ── Defaults ────────────────────────────────────────────────────────────
DEFAULT_CALLS_PATH = "journals/live_calibration_calls.jsonl"
DEFAULT_OUTCOMES_PATH = "journals/live_calibration_outcomes.jsonl"

# Serializes concurrent sweeps: the live-watch auto-sweeper runs sweep_once
# via asyncio.to_thread, and on session exit run_live_watch runs one final
# inline sweep_once.  A cancelled to_thread worker keeps running to
# completion, so without this lock the final inline sweep could race an
# orphaned background sweep and interleave appends to the outcomes JSONL.
_SWEEP_LOCK = threading.Lock()
DEFAULT_STATUS_PATH = "data/auto_scorer.json"
# Sweep cadence.  Calls have a 60-minute hold horizon, so a 5-minute sweep is
# plenty responsive while staying cheap.
DEFAULT_INTERVAL_SEC = 300.0
# Back off between failed sweeps.
SWEEP_BACKOFF_SEC = 30.0
MAX_CONSECUTIVE_ERRORS = 5


@dataclass
class AutoScoreStats:
    """Outcome of one auto-scoring sweep for one symbol (or all symbols)."""

    symbol: str
    swept_at: float = 0.0
    calls_pending: int = 0
    calls_scored: int = 0
    calls_failed: int = 0
    calls_skipped: int = 0
    error: str | None = None
    # Non-fatal caveat surfaced to the operator.  Distinct from ``error``:
    # a warning never fails the sweep or the task.  (Kept for legacy status
    # files; new sweeps carry no warning — scoring without MT5 is a hard
    # error, not a caveat.)
    warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "swept_at": self.swept_at,
            "calls_pending": self.calls_pending,
            "calls_scored": self.calls_scored,
            "calls_failed": self.calls_failed,
            "calls_skipped": self.calls_skipped,
            "error": self.error,
            "warning": self.warning,
        }


def _count_pending_calls(calls_path: Path, outcomes_path: Path) -> int:
    """Number of calls in the journal not yet scored (rough, best-effort)."""
    try:
        from synthetic_trader.live.calibration_scorer import (
            _record_key,
            load_jsonl_records,
        )

        existing = {_record_key(r) for r in load_jsonl_records(outcomes_path)}
        calls = load_jsonl_records(calls_path)
        return sum(1 for r in calls if _record_key(r) not in existing)
    except Exception:
        return 0


def _write_status(stats: dict[str, AutoScoreStats], status_path: Path) -> None:
    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbols": {sym: s.to_dict() for sym, s in stats.items()},
        }
        tmp = status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(status_path)
    except Exception:  # pragma: no cover - best effort telemetry
        pass


class ScoringUnavailableError(RuntimeError):
    """Raised when no trusted market-data source is available for scoring.

    Scoring *requires* the Deriv MT5 terminal.  There is deliberately no
    Deriv fallback: Deriv's 1HZ75V/1HZ100V trade at a completely different
    price scale (R_75 ~7,000 on Deriv vs ~1,542 on Deriv SYN75), so
    outcomes measured through Deriv would be incomparable to the call levels
    and could never feed the Stage-3 gate honestly.
    """


def _resolve_scoring_client_factory() -> Callable:
    """Resolve the market-data client for scoring sweeps.

    Only the Deriv MT5 terminal (``Mt5TickClient``) is trusted: it serves
    the same SYN75/SYN100 price scale the calls' levels (entry/stop/target)
    are measured on.  Without MT5 the sweep fails loudly ("no fallback") so
    the operator never mistakes wrong-scale outcomes for real evidence.
    """
    from synthetic_trader.execution.mt5_data import Mt5TickClient, is_mt5_configured

    if is_mt5_configured():
        return Mt5TickClient
    raise ScoringUnavailableError(
        "MT5 not configured (SYNTHETIC_MT5_SERVER/LOGIN/PASSWORD unset) - "
        "scoring requires the Deriv MT5 terminal; the Deriv API fallback "
        "was removed because 1HZ75V/1HZ100V are on the WRONG price scale"
    )


def _sweep_once(
    *,
    calls_path: Path,
    outcomes_path: Path,
    symbol: str | None,
    window_minutes: int | None,
    app_id: str | None,
) -> AutoScoreStats:
    """Run one scoring sweep and return its stats (raises on hard failure)."""
    client_factory = _resolve_scoring_client_factory()
    result = run_score_unresolved_records_from_market(
        calls_path=calls_path,
        outcomes_path=outcomes_path,
        now=datetime.now(timezone.utc),
        symbol=symbol,
        window_minutes=window_minutes,
        app_id=app_id,
        client_factory=client_factory,
    )
    return AutoScoreStats(
        symbol=symbol or "ALL",
        swept_at=time.time(),
        calls_pending=_count_pending_calls(calls_path, outcomes_path),
        calls_scored=result.scored_records,
        calls_failed=result.failed_records,
        calls_skipped=result.skipped_records,
        warning=None,
    )


def sweep_once(
    *,
    calls_path: str | Path = DEFAULT_CALLS_PATH,
    outcomes_path: str | Path = DEFAULT_OUTCOMES_PATH,
    symbol: str | None = None,
    window_minutes: int | None = None,
    app_id: str | None = None,
    status_path: str | Path = DEFAULT_STATUS_PATH,
) -> AutoScoreStats:
    """Run a single scoring sweep and write the status telemetry file.

    Public single-sweep entry point shared by the ``score-live-loop --once``
    CLI path and the live-watch auto-scorer.  A failed sweep (MT5 terminal
    unavailable — scoring has no Deriv fallback) is recorded on the status
    file rather than raised — callers can check ``stats.error``.  Returns the
    sweep stats.
    """
    stats: dict[str, AutoScoreStats] = {}
    with _SWEEP_LOCK:
        try:
            result = _sweep_once(
                calls_path=Path(calls_path),
                outcomes_path=Path(outcomes_path),
                symbol=symbol,
                window_minutes=window_minutes,
                app_id=app_id,
            )
            stats[result.symbol] = result
        except Exception as exc:  # pragma: no cover - MT5 down / transport failure
            key = symbol or "ALL"
            stats[key] = AutoScoreStats(
                symbol=key,
                swept_at=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
    _write_status(stats, Path(status_path))
    return next(iter(stats.values()))


async def run_auto_score_loop(
    *,
    calls_path: str | Path = DEFAULT_CALLS_PATH,
    outcomes_path: str | Path = DEFAULT_OUTCOMES_PATH,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    symbol: str | None = None,
    window_minutes: int | None = None,
    app_id: str | None = None,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    run_once: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, AutoScoreStats]:
    """Sweep the calls journal and score resolved calls on a schedule.

    Runs forever (or until interrupted), sweeping every ``interval_sec``,
    unless ``run_once`` is set — then a single sweep is performed and the
    function returns.  After every sweep the status JSON is rewritten.  A
    sweep failure (MT5 terminal unavailable — scoring has no Deriv
    fallback) is recorded on the status and retried with backoff; after
    ``MAX_CONSECUTIVE_ERRORS`` consecutive failures the loop gives up.
    """
    stats: dict[str, AutoScoreStats] = {}
    consecutive_errors = 0
    while True:
        try:
            # The sweep itself is sync and internally runs its own event loop
            # (``asyncio.run`` inside run_score_unresolved_records_from_market),
            # so it must run on a worker thread — never on this loop.  This is
            # the same fix the live-watch auto-scorer uses for sweep_once.
            result = await asyncio.to_thread(
                _sweep_once,
                calls_path=Path(calls_path),
                outcomes_path=Path(outcomes_path),
                symbol=symbol,
                window_minutes=window_minutes,
                app_id=app_id,
            )
            stats[result.symbol] = result
            consecutive_errors = 0
            log(
                f"[auto-score:{result.symbol}] scored {result.calls_scored}, "
                f"failed {result.calls_failed}, skipped {result.calls_skipped}, "
                f"pending {result.calls_pending}"
            )
        except Exception as exc:  # pragma: no cover - MT5 down / transport failure
            consecutive_errors += 1
            key = symbol or "ALL"
            stats[key] = AutoScoreStats(
                symbol=key,
                swept_at=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
            log(f"[auto-score:{key}] error: {exc}")

        _write_status(stats, Path(status_path))
        if run_once:
            break
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            log(
                f"[auto-score] giving up after {consecutive_errors} consecutive "
                f"failed sweeps — start the Deriv MT5 terminal "
                f"(scoring has no Deriv fallback)"
            )
            break
        await asyncio.sleep(interval_sec if consecutive_errors == 0 else SWEEP_BACKOFF_SEC)
    return stats


if __name__ == "__main__":  # pragma: no cover - manual smoke entry
    import sys

    asyncio.run(run_auto_score_loop(run_once="--once" in sys.argv))
