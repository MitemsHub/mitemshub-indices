"""Collector health reporting and legacy process monitor CLI."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_EVENTS_PATH = Path("logs/collector_events.jsonl")
STATUS_PATH = Path("data/live_tick_collector.json")
COLLECTOR_OUTPUT = Path("data/collector_output.log")
TICK_FILES = {"R_75": Path("data/backfill/R_75_ticks.csv"), "R_100": Path("data/backfill/R_100_ticks.csv")}
STALE_THRESHOLD_SEC = 120
DEAD_THRESHOLD_SEC = 300
CSV_MAX_AGE_SEC = 600
CHECK_INTERVAL_SEC = 30


def _read_events(engine_root: Path, hours: float, now: float) -> list[dict]:
    path = engine_root / DEFAULT_EVENTS_PATH
    if not path.exists():
        return []
    cutoff = now - hours * 3600
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            if float(event.get("ts", 0)) >= cutoff:
                events.append(event)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return events


def _corpus_report(engine_root: Path, now: float) -> dict[str, dict]:
    result = {}
    for symbol in ("R_75", "R_100"):
        path = engine_root / "data" / "backfill" / f"{symbol}_ticks.csv"
        report = {"out_of_scale_ticks": 0, "last_tick_age_sec": 0.0}
        if path.exists():
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split(",")
                if len(parts) < 3:
                    continue
                try:
                    rows.append((float(parts[0]), float(parts[2])))
                except ValueError:
                    continue
            if rows:
                report["last_tick_age_sec"] = max(0.0, now - max(t for t, _ in rows))
                lo, hi = ((1000, 3000) if symbol == "R_75" else (1000, 10000))
                report["out_of_scale_ticks"] = sum(1 for _, price in rows if not lo <= price <= hi)
        result[symbol] = report
    return result


def run_collector_health(*, engine_root: Path | str = Path("."), hours: float = 48, now: float | None = None) -> dict:
    root = Path(engine_root)
    current = time.time() if now is None else now
    events = _read_events(root, hours, current)
    ipc = sum("ipc timeout" in str(e.get("message", "")).lower() for e in events)
    feed_loss = sum(e.get("kind") == "feed_lost" for e in events)
    corpus = _corpus_report(root, current)
    leaks = [s for s, r in corpus.items() if r["out_of_scale_ticks"]]
    stale = [s for s, r in corpus.items() if r["last_tick_age_sec"] > 12 * 3600]
    if leaks:
        verdict, reason = "venue_leak", f"VENUE LEAK detected in {', '.join(leaks)}"
    elif ipc >= 3:
        verdict, reason = "needs_re_tune", "reconnect backoff needs re-tune after repeated IPC timeouts"
    elif ipc or feed_loss or stale:
        verdict, reason = "attention", "collector requires attention"
    else:
        verdict, reason = "ok", "single-flight guard is holding and no collector anomalies were found"
    return {
        "verdict": verdict,
        "verdict_reason": reason,
        "events": {"total": len(events), "ipc_timeouts": ipc, "feed_loss": feed_loss},
        "corpus": corpus,
    }


@dataclass
class HealthStatus:
    collector_running: bool = False
    data_fresh: bool = False
    csv_sizes: dict[str, int] = field(default_factory=dict)
    last_tick_age_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status_file_valid: bool = False

    @property
    def healthy(self) -> bool:
        return self.collector_running and self.data_fresh and not self.errors

    @property
    def status_emoji(self) -> str:
        return "OK" if self.healthy else ("WARN" if self.collector_running else "FAIL")

    def summary(self) -> str:
        lines = [f"Collector:  {'RUNNING' if self.collector_running else 'STOPPED'}", f"Data:       {'FRESH' if self.data_fresh else 'STALE'}", f"Status:     {self.status_emoji}"]
        lines.extend(f"  {sym}: {size:,} bytes" for sym, size in self.csv_sizes.items())
        if self.last_tick_age_sec > 0:
            lines.append(f"Last tick:  {self.last_tick_age_sec / 60:.1f} min ago")
        if self.errors:
            lines.append("ERRORS:\n" + "\n".join(f"  - {e}" for e in self.errors))
        if self.warnings:
            lines.append("WARNINGS:\n" + "\n".join(f"  - {w}" for w in self.warnings))
        return "\n".join(lines)


def check_collector_process() -> tuple[bool, list[str]]:
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"], capture_output=True, text=True, timeout=5)
            return any("python" in line.lower() for line in result.stdout.splitlines()), []
        result = subprocess.run(["pgrep", "-f", "collect-live-ticks"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0, []
    except Exception as exc:
        return False, [f"Process check failed: {exc}"]


def check_data_freshness() -> tuple[bool, dict[str, int], float, list[str]]:
    sizes, warnings, last_age, fresh = {}, [], 0.0, False
    for symbol, path in TICK_FILES.items():
        if not path.exists():
            warnings.append(f"{symbol}: CSV file not found")
            continue
        sizes[symbol] = path.stat().st_size
        age = time.time() - path.stat().st_mtime
        last_age = max(last_age, age)
        fresh |= age < STALE_THRESHOLD_SEC
        if age > CSV_MAX_AGE_SEC:
            warnings.append(f"{symbol}: CSV is {age / 60:.1f} min old")
    return fresh, sizes, last_age, warnings


def check_status_file() -> tuple[bool, list[str], list[str]]:
    if not STATUS_PATH.exists():
        return False, [], ["Status file not found"]
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        warnings = []
        if time.time() - data.get("updated_at", 0) > DEAD_THRESHOLD_SEC:
            warnings.append("Status file is stale")
        return True, [], warnings
    except Exception as exc:
        return False, [f"Status file parse error: {exc}"], []


def run_health_check() -> HealthStatus:
    status = HealthStatus()
    status.collector_running, status.errors = check_collector_process()
    status.data_fresh, status.csv_sizes, status.last_tick_age_sec, status.warnings = check_data_freshness()
    status.status_file_valid, errors, warnings = check_status_file()
    status.errors.extend(errors)
    status.warnings.extend(warnings)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Collector health check")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.watch:
        while True:
            print(run_health_check().summary())
            time.sleep(CHECK_INTERVAL_SEC)
    status = run_health_check()
    print(json.dumps(status.__dict__, indent=2) if args.json else status.summary())
    raise SystemExit(0 if status.healthy else 1)


if __name__ == "__main__":
    main()
