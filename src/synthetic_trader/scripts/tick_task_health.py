"""Daily tick-collector task health check.

Reads the artifacts the Windows Task Scheduler job
(``SyntheticIndicesLiveTickCollector``, §25) leaves behind and reports
whether the tick corpus is actually compounding:

- ``.data/live_tick_task.log`` — the task's own log (one timestamped line per
  action; ``coverage R_75 (N ticks, ...)`` lines carry the per-symbol tick
  count at each task run).
- ``.data/live_tick_task_verify.json`` — the latest ``tick-coverage --json``
  snapshot the task wrote (per-symbol ticks/span, generated_at).
- ``.data/live_tick_task_setup_baseline.json`` — the snapshot taken at task
  registration, used to prove growth over a multi-day window.
- ``data/backfill/{symbol}_ticks.csv`` — the actual CSV the collector appends
  to (ground truth: mtime + tick count).

The headline warning is **corpus stopped growing**: per-symbol tick count
flat for ``flat_hours`` (default 48) across the verify snapshot and the log's
coverage lines, while the CSV mtime also stopped advancing.  Secondary
warnings cover a stale task (last ``task action`` older than
``task_stale_hours``, default 26 for a daily 00:30 job) and a verify
snapshot older than ``verify_stale_hours``.

Exit code is 0 when healthy, 1 when any warning fires — so a scheduled
email/desktop alert can gate on the process exit code directly.

Usage::

    python -m synthetic_trader.scripts.tick_task_health [--engine-root .] \\
        [--json] [--flat-hours 48] [--task-stale-hours 26]

or via the CLI::

    python -m synthetic_trader.cli tick-task-health --engine-root .
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Task artifacts (relative to engine root).
TASK_LOG_REL = ".data/live_tick_task.log"
VERIFY_JSON_REL = ".data/live_tick_task_verify.json"
BASELINE_JSON_REL = ".data/live_tick_task_setup_baseline.json"
CSV_DIR_REL = "data/backfill"

SYMBOLS = ("R_75", "R_100")

# Task log line formats:
#   [2026-08-05 04:20:51] coverage R_75 (40080 ticks, 7.0 days): ...
#   [2026-08-05 04:20:51] task action starting (daily collector restart + scoring sweep)
#   [2026-08-05 15:02:27] task action complete
_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$")
_COVERAGE_RE = re.compile(r"coverage\s+([A-Za-z0-9_]+)\s+\((\d+)\s+ticks")


@dataclass
class LogPoint:
    """One timestamped observation of a symbol's tick count from the log."""

    at: float  # epoch seconds
    ticks: int


@dataclass
class SymbolHealth:
    symbol: str
    ticks_latest: int | None = None
    span_days: float | None = None
    csv_mtime_ts: float | None = None
    csv_ticks: int | None = None
    log_points: list[LogPoint] = field(default_factory=list)
    flat_hours: float = 0.0
    flat: bool = False
    flat_reason: str | None = None


@dataclass
class TaskHealthReport:
    healthy: bool
    checked_at: float
    flat_hours: float
    task_stale_hours: float
    verify_stale_hours: float
    last_task_action_ts: float | None
    last_task_action_age_hours: float | None
    task_stale: bool
    verify_ts: float | None
    verify_age_hours: float | None
    verify_stale: bool
    symbols: list[SymbolHealth]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "checked_at": round(self.checked_at, 3),
            "flat_hours": self.flat_hours,
            "task_stale_hours": self.task_stale_hours,
            "verify_stale_hours": self.verify_stale_hours,
            "task": {
                "last_action_ts": self.last_task_action_ts,
                "last_action_age_hours": (
                    round(self.last_task_action_age_hours, 2)
                    if self.last_task_action_age_hours is not None
                    else None
                ),
                "stale": self.task_stale,
            },
            "verify": {
                "ts": self.verify_ts,
                "age_hours": (
                    round(self.verify_age_hours, 2)
                    if self.verify_age_hours is not None
                    else None
                ),
                "stale": self.verify_stale,
            },
            "symbols": [
                {
                    "symbol": s.symbol,
                    "ticks_latest": s.ticks_latest,
                    "span_days": round(s.span_days, 2) if s.span_days is not None else None,
                    "csv_ticks": s.csv_ticks,
                    "csv_mtime_ts": s.csv_mtime_ts,
                    "flat": s.flat,
                    "flat_hours": round(s.flat_hours, 2),
                    "flat_reason": s.flat_reason,
                    "log_points": [
                        {"at": p.at, "ticks": p.ticks} for p in s.log_points
                    ],
                }
                for s in self.symbols
            ],
            "warnings": self.warnings,
        }


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_ts(text: str) -> float | None:
    """Parse a log timestamp like 2026-08-05 04:20:51 (local, task log is
    local time) into epoch seconds."""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        # The task log timestamps are local time (Write-TaskLog uses Get-Date).
        # Attach the local timezone so epoch math against UTC now() is sane.
        return dt.astimezone().timestamp()
    except (ValueError, OSError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _parse_task_log(path: Path) -> tuple[list[dict[str, Any]], float | None]:
    """Parse the task log into structured entries and the last action ts.

    Returns (entries, last_action_ts).  Entries carry ``at`` (epoch),
    ``text`` (stripped), and ``ticks_by_symbol`` for coverage lines.
    """
    entries: list[dict[str, Any]] = []
    last_action_ts: float | None = None
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                m = _TS_RE.match(raw)
                if not m:
                    continue
                ts = _parse_ts(m.group(1))
                text = m.group(2)
                entry: dict[str, Any] = {"at": ts, "text": text}
                if "coverage" in text:
                    ticks: dict[str, int] = {}
                    for cm in _COVERAGE_RE.finditer(text):
                        ticks[cm.group(1)] = int(cm.group(2))
                    entry["ticks_by_symbol"] = ticks
                if "task action" in text:
                    last_action_ts = ts
                entries.append(entry)
    except OSError:
        return [], None
    return entries, last_action_ts


def _csv_ticks_and_mtime(path: Path) -> tuple[int | None, float | None]:
    """Count rows (ticks) and mtime of a collector CSV — ground truth."""
    if not path.exists():
        return None, None
    try:
        mtime = path.stat().st_mtime
        # Fast row count; the collector writes headerless epoch,symbol,price.
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            count = sum(1 for _ in handle)
        return count, mtime
    except OSError:
        return None, None


def check_task_health(
    engine_root: str | Path = ".",
    *,
    flat_hours: float = 48.0,
    task_stale_hours: float = 26.0,
    verify_stale_hours: float = 26.0,
) -> TaskHealthReport:
    """Assess whether the tick corpus is still compounding.

    The headline check is per-symbol: the corpus stopped growing when (a) the
    latest verify snapshot's tick count equals every coverage line's tick
    count over the log window, (b) the CSV mtime stopped advancing, and (c)
    both have been flat for at least ``flat_hours``.  A task that never wrote
    a verify snapshot or a log is reported stale, not healthy.
    """
    root = Path(engine_root)
    now = _now()
    warnings: list[str] = []

    log_path = root / TASK_LOG_REL
    verify_path = root / VERIFY_JSON_REL
    baseline_path = root / BASELINE_JSON_REL

    entries, last_action_ts = _parse_task_log(log_path)
    verify = _read_json(verify_path)
    baseline = _read_json(baseline_path)

    # ── Task-level staleness ─────────────────────────────────────────────
    last_action_age = (
        (now - last_action_ts) / 3600.0 if last_action_ts is not None else None
    )
    task_stale = last_action_ts is None or (
        last_action_age is not None and last_action_age > task_stale_hours
    )
    if task_stale:
        reason = (
            "no task action lines in the log (task never ran?)"
            if last_action_ts is None
            else f"last task action {last_action_age:.1f}h ago (> {task_stale_hours:g}h)"
        )
        warnings.append(f"task stale: {reason}")

    # ── Verify-snapshot staleness ────────────────────────────────────────
    verify_ts = None
    verify_age = None
    verify_stale = False
    if verify is not None:
        generated = verify.get("generated_at")
        if isinstance(generated, (int, float)) and generated > 0:
            verify_ts = float(generated)
            verify_age = (now - verify_ts) / 3600.0
            verify_stale = verify_age > verify_stale_hours
            if verify_stale:
                warnings.append(
                    f"verify snapshot stale: written {verify_age:.1f}h ago "
                    f"(> {verify_stale_hours:g}h)"
                )
    else:
        verify_stale = True
        warnings.append("verify snapshot missing (.data/live_tick_task_verify.json)")

    # ── Per-symbol corpus growth ─────────────────────────────────────────
    # Baseline ticks: the snapshot taken at task registration.
    baseline_ticks: dict[str, int] = {}
    if baseline is not None:
        for sym_entry in baseline.get("symbols", []):
            sym = sym_entry.get("symbol")
            ticks = sym_entry.get("ticks")
            if sym and isinstance(ticks, (int, float)):
                baseline_ticks[sym] = int(ticks)

    # Latest verify ticks: the most recent snapshot.
    latest_verify_ticks: dict[str, int] = {}
    if verify is not None:
        for sym_entry in verify.get("symbols", []):
            sym = sym_entry.get("symbol")
            ticks = sym_entry.get("ticks")
            if sym and isinstance(ticks, (int, float)):
                latest_verify_ticks[sym] = int(ticks)

    # Coverage lines from the log: per-symbol (at, ticks) history.
    log_series: dict[str, list[LogPoint]] = {s: [] for s in SYMBOLS}
    for entry in entries:
        for sym, ticks in (entry.get("ticks_by_symbol") or {}).items():
            if entry["at"] is not None:
                log_series.setdefault(sym, []).append(
                    LogPoint(at=entry["at"], ticks=ticks)
                )

    symbols_health: list[SymbolHealth] = []
    for symbol in SYMBOLS:
        sh = SymbolHealth(symbol=symbol)
        sh.ticks_latest = latest_verify_ticks.get(symbol)
        sh.log_points = log_series.get(symbol, [])

        # CSV ground truth.
        csv_path = root / CSV_DIR_REL / f"{symbol}_ticks.csv"
        sh.csv_ticks, sh.csv_mtime_ts = _csv_ticks_and_mtime(csv_path)

        # Span days from the latest verify snapshot.
        if verify is not None:
            for sym_entry in verify.get("symbols", []):
                if sym_entry.get("symbol") == symbol:
                    span = sym_entry.get("span_days")
                    if isinstance(span, (int, float)):
                        sh.span_days = float(span)
                    break

        # ── The flat-detection core ──────────────────────────────────────
        # The CSV mtime is the decisive liveness signal: the collector appends
        # to the file, so mtime stops advancing when appending stops.  A fresh
        # mtime (within flat_hours) means data is arriving — the verify/log
        # snapshots merely lag because they only update on the daily task run
        # — so a fresh CSV is NOT flat even if the snapshot counts look frozen.
        #
        # Only when the CSV is old/missing do we corroborate with count
        # evidence: every timestamp that PROVES the count was already at its
        # current value (baseline registration, oldest coverage line, and the
        # CSV mtime itself, which last held this count).  The OLDEST such
        # evidence bounds the flat window (the count cannot have grown since
        # any of them).  Row count tolerates +1 for the backfill's header row.
        baseline_ts = None
        if baseline is not None:
            bg = baseline.get("generated_at")
            if isinstance(bg, (int, float)) and bg > 0:
                baseline_ts = float(bg)
        same_as_baseline = (
            baseline_ts is not None
            and symbol in baseline_ticks
            and sh.ticks_latest is not None
            and baseline_ticks[symbol] == sh.ticks_latest
        )
        csv_evidence_ts = sh.csv_mtime_ts
        csv_fresh = csv_evidence_ts is not None and (
            (now - csv_evidence_ts) / 3600.0 < flat_hours
        )
        if csv_fresh:
            # The collector is still appending (or wrote within flat_hours);
            # verify/log snapshots merely lag the daily task run.
            sh.flat = False
            sh.flat_hours = (now - csv_evidence_ts) / 3600.0
        elif csv_evidence_ts is not None:
            # CSV exists but is old: its mtime is ground truth for the last
            # append, so the flat window starts there.  This also covers a
            # symbol missing from the verify snapshot (mtime-only evidence)
            # and a snapshot count that lags a recent growth (the mtime stays
            # the honest last-growth time either way — no min() overstatement
            # from the older registration/log timestamps).
            sh.flat_hours = (now - csv_evidence_ts) / 3600.0
            if sh.flat_hours >= flat_hours:
                sh.flat = True
                reasons = [
                    f"CSV not written for {sh.flat_hours:.1f}h "
                    f"(mtime {_fmt_ts(csv_evidence_ts)})"
                ]
                if same_as_baseline:
                    reasons.append(
                        f"tick count unchanged since task registration "
                        f"({baseline_ticks.get(symbol)} ticks)"
                    )
                if sh.ticks_latest is not None:
                    reasons.append(f"latest snapshot {sh.ticks_latest} ticks")
                sh.flat_reason = "; ".join(reasons)
                warnings.append(
                    f"{symbol}: corpus stopped growing - {sh.flat_reason}"
                )
        else:
            # No CSV at all: corroborate count evidence (baseline registration
            # or the oldest coverage line already at the latest count).
            evidence_starts: list[float] = []
            if same_as_baseline and baseline_ts is not None:
                evidence_starts.append(baseline_ts)
            points = sh.log_points
            if points and sh.ticks_latest is not None:
                oldest_same = next(
                    (p for p in points if p.ticks == sh.ticks_latest), None
                )
                if oldest_same is not None:
                    evidence_starts.append(oldest_same.at)
            if evidence_starts:
                flat_window_start = min(evidence_starts)
                sh.flat_hours = (now - flat_window_start) / 3600.0
                if sh.flat_hours >= flat_hours:
                    sh.flat = True
                    reasons = []
                    if same_as_baseline:
                        reasons.append(
                            f"tick count unchanged since task registration "
                            f"({baseline_ticks.get(symbol)} ticks)"
                        )
                    if not reasons:
                        reasons.append(
                            f"tick count flat at {sh.ticks_latest} for "
                            f"{sh.flat_hours:.1f}h"
                        )
                    sh.flat_reason = "; ".join(reasons)
                    warnings.append(
                        f"{symbol}: corpus stopped growing - {sh.flat_reason}"
                    )

        symbols_health.append(sh)

    healthy = not warnings
    return TaskHealthReport(
        healthy=healthy,
        checked_at=now,
        flat_hours=flat_hours,
        task_stale_hours=task_stale_hours,
        verify_stale_hours=verify_stale_hours,
        last_task_action_ts=last_action_ts,
        last_task_action_age_hours=last_action_age,
        task_stale=task_stale,
        verify_ts=verify_ts,
        verify_age_hours=verify_age,
        verify_stale=verify_stale,
        symbols=symbols_health,
        warnings=warnings,
    )


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "n/a"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return "n/a"


def render_report(report: TaskHealthReport) -> str:
    """Human-readable digest for a morning email / desktop alert."""
    lines: list[str] = []
    lines.append(
        "TICK-COLLECTOR HEALTH "
        + ("OK" if report.healthy else "** WARNINGS **")
    )
    lines.append(f"checked {datetime.fromtimestamp(report.checked_at):%Y-%m-%d %H:%M}")
    task_age = (
        f"{report.last_task_action_age_hours:.1f}h"
        if report.last_task_action_age_hours is not None
        else "never"
    )
    lines.append(f"task: last action {task_age} ago (stale > {report.task_stale_hours:g}h)")
    verify_age = (
        f"{report.verify_age_hours:.1f}h"
        if report.verify_age_hours is not None
        else "missing"
    )
    lines.append(f"verify: {verify_age} old (stale > {report.verify_stale_hours:g}h)")
    lines.append(f"flat threshold: {report.flat_hours:g}h")
    for sh in report.symbols:
        csv_info = (
            f"csv {sh.csv_ticks} ticks (mtime {_fmt_ts(sh.csv_mtime_ts)})"
            if sh.csv_ticks is not None
            else "csv missing"
        )
        state = "FLAT" if sh.flat else "growing/ok"
        span = f"{sh.span_days:.1f}d" if sh.span_days is not None else "n/a"
        head = f"{sh.symbol}: latest {sh.ticks_latest} ticks ({span})"
        if sh.flat:
            lines.append(f"{head}")
            lines.append(f"  -> {state}: {sh.flat_reason} ({sh.flat_hours:.1f}h flat)")
        else:
            lines.append(f"{head} -> {state}; {csv_info}")
    if report.warnings:
        lines.append("")
        lines.append("WARNINGS:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("")
        lines.append("All checks passed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: 0 = healthy, 1 = any warning fired."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Health check for the daily tick-collector task."
    )
    parser.add_argument("--engine-root", default=".", help="project root (default: cwd)")
    parser.add_argument(
        "--flat-hours", type=float, default=48.0,
        help="warn when a symbol's tick count is flat for this many hours (default 48)",
    )
    parser.add_argument(
        "--task-stale-hours", type=float, default=26.0,
        help="warn when the last task action is older than this (default 26)",
    )
    parser.add_argument(
        "--verify-stale-hours", type=float, default=26.0,
        help="warn when the verify snapshot is older than this (default 26)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    args = parser.parse_args(argv)

    # Windows consoles default to cp1252 and crash printing non-ASCII glyphs;
    # force UTF-8 the same way the tick-coverage handler does.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    report = check_task_health(
        args.engine_root,
        flat_hours=args.flat_hours,
        task_stale_hours=args.task_stale_hours,
        verify_stale_hours=args.verify_stale_hours,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_report(report))
    return 0 if report.healthy else 1


if __name__ == "__main__":
    sys.exit(main())
