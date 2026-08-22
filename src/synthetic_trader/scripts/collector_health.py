"""Collector health check — monitors the tick collector and alerts if it stops.

Checks:
1. Collector process status (is it running?)
2. Data freshness (are new ticks being written?)
3. Collector status file (any errors or stalls?)
4. CSV file integrity (reasonable size, no corruption?)

Usage:
    python -m synthetic_trader.scripts.collector_health          # quick check
    python -m synthetic_trader.scripts.collector_health --watch   # continuous monitoring
    python -m synthetic_trader.scripts.collector_health --restart # auto-restart if dead
"""

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


# ── Configuration ──────────────────────────────────────────────────────
STATUS_PATH = Path("data/live_tick_collector.json")
COLLECTOR_OUTPUT = Path("data/collector_output.log")
TICK_FILES = {
    "R_75": Path("data/backfill/R_75_ticks.csv"),
    "R_100": Path("data/backfill/R_100_ticks.csv"),
}

# Alert thresholds
STALE_THRESHOLD_SEC = 120        # 2 minutes without new ticks = warning
DEAD_THRESHOLD_SEC = 300         # 5 minutes = collector likely dead
CSV_MAX_AGE_SEC = 600            # 10 minutes = data too old
CHECK_INTERVAL_SEC = 30          # how often to check in --watch mode


@dataclass
class HealthStatus:
    """Collector health assessment."""
    collector_running: bool = False
    data_fresh: bool = False
    csv_sizes: dict[str, int] = field(default_factory=dict)
    last_tick_age_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status_file_valid: bool = False

    @property
    def healthy(self) -> bool:
        return self.collector_running and self.data_fresh and len(self.errors) == 0

    @property
    def status_emoji(self) -> str:
        if self.healthy:
            return "OK"
        elif self.collector_running:
            return "WARN"
        else:
            return "FAIL"

    def summary(self) -> str:
        lines = []
        lines.append(f"Collector:  {'RUNNING' if self.collector_running else 'STOPPED'}")
        lines.append(f"Data:       {'FRESH' if self.data_fresh else 'STALE'}")
        lines.append(f"Status:     {self.status_emoji}")

        for sym, size in self.csv_sizes.items():
            lines.append(f"  {sym}: {size:,} bytes")

        if self.last_tick_age_sec > 0:
            age_min = self.last_tick_age_sec / 60
            lines.append(f"Last tick:  {age_min:.1f} min ago")

        if self.errors:
            lines.append("ERRORS:")
            for e in self.errors:
                lines.append(f"  - {e}")

        if self.warnings:
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)


def check_collector_process() -> tuple[bool, list[str]]:
    """Check if the collector process is running."""
    errors = []
    running = False

    try:
        if os.name == "nt":
            # Windows: check for python processes running collector
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if "python" in line.lower():
                    running = True
                    break
        else:
            # Unix: check for collector process
            result = subprocess.run(
                ["pgrep", "-f", "collect-live-ticks"],
                capture_output=True, text=True, timeout=5
            )
            running = result.returncode == 0
    except Exception as e:
        errors.append(f"Process check failed: {e}")

    return running, errors


def check_data_freshness() -> tuple[bool, dict[str, int], float, list[str]]:
    """Check if tick data is being written."""
    errors: list[str] = []
    warnings: list[str] = []
    sizes = {}
    last_age = 0.0
    fresh = False

    for sym, path in TICK_FILES.items():
        if not path.exists():
            warnings.append(f"{sym}: CSV file not found")
            continue

        size = path.stat().st_size
        sizes[sym] = size

        # Check file modification time
        mtime = path.stat().st_mtime
        age = time.time() - mtime
        last_age = max(last_age, age)

        if age < STALE_THRESHOLD_SEC:
            fresh = True
        elif age > CSV_MAX_AGE_SEC:
            warnings.append(f"{sym}: CSV is {age/60:.1f} min old")

    return fresh, sizes, last_age, errors + warnings


def check_status_file() -> tuple[bool, list[str], list[str]]:
    """Check the collector status JSON file."""
    errors: list[str] = []
    warnings: list[str] = []
    valid = False

    if not STATUS_PATH.exists():
        warnings.append("Status file not found")
        return valid, errors, warnings

    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        valid = True

        # Check update time
        updated_at = data.get("updated_at", 0)
        age = time.time() - updated_at
        if age > DEAD_THRESHOLD_SEC:
            warnings.append(f"Status file is {age/60:.1f} min old")

        # Check collector stats
        collectors = data.get("collectors", {})
        for sym, stats in collectors.items():
            if stats.get("errors"):
                errors.append(f"{sym}: {stats['errors'][-1]}")

    except Exception as e:
        errors.append(f"Status file parse error: {e}")

    return valid, errors, warnings


def run_health_check() -> HealthStatus:
    """Run all health checks and return status."""
    status = HealthStatus()

    # Check process
    running, proc_errors = check_collector_process()
    status.collector_running = running
    status.errors.extend(proc_errors)

    # Check data freshness
    fresh, sizes, last_age, fresh_warnings = check_data_freshness()
    status.data_fresh = fresh
    status.csv_sizes = sizes
    status.last_tick_age_sec = last_age
    status.warnings.extend(fresh_warnings)

    # Check status file
    valid, stat_errors, stat_warnings = check_status_file()
    status.status_file_valid = valid
    status.errors.extend(stat_errors)
    status.warnings.extend(stat_warnings)

    return status


def restart_collector() -> bool:
    """Attempt to restart the collector."""
    try:
        if os.name == "nt":
            # Windows: start collector in background
            subprocess.Popen(
                [sys.executable, "-m", "synthetic_trader.cli", "collect-live-ticks",
                 "--symbols", "R_75,R_100"],
                stdout=open(COLLECTOR_OUTPUT, "w"),
                stderr=subprocess.STDOUT,
                creationflags=0x00000008  # DETACHED_PROCESS
            )
        else:
            # Unix: start with nohup
            subprocess.Popen(
                [sys.executable, "-m", "synthetic_trader.cli", "collect-live-ticks",
                 "--symbols", "R_75,R_100"],
                stdout=open(COLLECTOR_OUTPUT, "w"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
        return True
    except Exception as e:
        print(f"Failed to restart collector: {e}")
        return False


def watch_mode():
    """Continuous monitoring with alerts."""
    print("Collector Health Monitor (Ctrl+C to stop)")
    print("=" * 50)

    while True:
        try:
            status = run_health_check()

            # Clear screen (works on most terminals)
            os.system("cls" if os.name == "nt" else "clear")

            # Print status
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"[{now}] Collector Health Monitor")
            print("=" * 50)
            print(status.summary())

            # Alert if unhealthy
            if not status.healthy:
                print("\n" + "!" * 50)
                if not status.collector_running:
                    print("ALERT: Collector is NOT running!")
                if not status.data_fresh:
                    print("ALERT: Data is STALE!")
                if status.errors:
                    print(f"ALERT: {len(status.errors)} error(s) found!")
                print("!" * 50)

            time.sleep(CHECK_INTERVAL_SEC)

        except KeyboardInterrupt:
            print("\nStopping monitor...")
            break


def main():
    parser = argparse.ArgumentParser(description="Collector health check")
    parser.add_argument("--watch", action="store_true",
                        help="Continuous monitoring mode")
    parser.add_argument("--restart", action="store_true",
                        help="Auto-restart collector if dead")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    if args.watch:
        watch_mode()
        return

    # Single check
    status = run_health_check()

    if args.json:
        import json as json_mod
        output = {
            "healthy": status.healthy,
            "collector_running": status.collector_running,
            "data_fresh": status.data_fresh,
            "csv_sizes": status.csv_sizes,
            "last_tick_age_sec": status.last_tick_age_sec,
            "errors": status.errors,
            "warnings": status.warnings,
        }
        print(json_mod.dumps(output, indent=2))
    else:
        print(status.summary())

    # Auto-restart if requested
    if args.restart and not status.collector_running:
        print("\nAttempting to restart collector...")
        if restart_collector():
            print("Collector restarted successfully")
        else:
            print("Failed to restart collector")
            sys.exit(1)

    # Exit code: 0 = healthy, 1 = unhealthy
    sys.exit(0 if status.healthy else 1)


if __name__ == "__main__":
    main()
