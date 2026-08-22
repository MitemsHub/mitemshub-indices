#!/usr/bin/env python3
"""Forward-demo pass watchdog — alerts when the journal goes silent.

The forward-demo pass (mql5/forward_demo_pass.py) journals one record per
closed primary candle, so a gap in the journal stream means the pass is
stalled — the recurring dead-chunk / MT5-IPC pattern where the process stays
alive but stops journaling, silently missing the 18-24h (server) window.

This watchdog is meant to run from Task Scheduler every 15 minutes:

    python mql5/forward_demo_watchdog.py

Status is based on the journal FILE MTIME (wall clock — unlike record epochs,
which are broker server time and would bias the age by the server offset).
A pass that has legitimately finished its target number of closed trades is
reported as COMPLETE, not stalled.

Exit codes (so Task Scheduler records the failure):
    0  healthy or complete
    1  STALLED — journal silent beyond the threshold (alert written)
    2  journal missing/empty (pass never started, or was wiped)

One ALERT line is written per stall episode (deduped via a state file), so
the log doesn't spam every 15 minutes while a stall persists.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
DEFAULT_JOURNAL = ROOT / "journals" / "forward_demo_18_24.jsonl"
STATE_FILE = ROOT / ".freebuff" / "forward_demo_watchdog.state"
ALERT_LOG = ROOT / ".freebuff" / "forward_demo_watchdog.log"
DEFAULT_STALE_MIN = 30
DEFAULT_MAX_TRADES = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _count_outcomes(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    if json.loads(line).get("type") == "outcome":
                        n += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        return -1
    return n


def _pass_process_running() -> bool:
    """True when a python.exe whose command line mentions forward_demo_pass
    is alive (the pass driver)."""
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'forward_demo_pass' } | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True, text=True, timeout=20,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def _terminal_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
            capture_output=True, text=True, timeout=20,
        )
        return "terminal64.exe" in out.stdout
    except Exception:
        return False


def _write_alert(message: str) -> None:
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{_now_iso()}  {message}\n")


def _write_ok(message: str) -> None:
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{_now_iso()}  {message}\n")


def _last_alerted_mtime() -> float:
    try:
        return float(STATE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def _mark_alerted(mtime: float) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(f"{mtime}\n", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--journal", default=str(DEFAULT_JOURNAL),
                    help="forward-demo journal path")
    ap.add_argument("--stale-min", type=float, default=DEFAULT_STALE_MIN,
                    help="alert when the journal has been silent longer than this")
    ap.add_argument("--max-trades", type=int, default=DEFAULT_MAX_TRADES,
                    help="outcome count that means the pass finished (not stalled)")
    ap.add_argument("--force", action="store_true",
                    help="force an alert even if this stall episode was already alerted")
    args = ap.parse_args()

    journal = Path(args.journal)
    stale_sec = args.stale_min * 60.0

    # ── journal existence ─────────────────────────────────────────────
    if not journal.exists() or journal.stat().st_size == 0:
        msg = (f"ALERT forward-demo journal MISSING/EMPTY ({journal}) — "
               f"the pass is not journaling at all")
        if args.force or _last_alerted_mtime() != -1.0:
            _write_alert(msg)
            _mark_alerted(-1.0)
        print(f"[FWD-WATCHDOG] status=MISSING journal={journal}")
        print(msg)
        return 2

    mtime = journal.stat().st_mtime
    age = time.time() - mtime
    outcomes = _count_outcomes(journal)
    pass_alive = _pass_process_running()
    terminal_alive = _terminal_running()
    completed = outcomes >= args.max_trades

    # ── completion: a finished pass stops journaling by design ────────
    if completed:
        _write_ok(f"OK forward-demo pass COMPLETE: {outcomes} closed trades "
                  f"(last write {datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec='seconds')}Z)")
        print(f"[FWD-WATCHDOG] status=COMPLETE outcomes={outcomes} last_write_age_min={age / 60.0:.0f}")
        return 0

    # ── healthy vs stalled ─────────────────────────────────────────────
    if age <= stale_sec:
        _write_ok(f"OK forward-demo journal fresh: last write "
                  f"{datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec='seconds')}Z "
                  f"({age / 60.0:.0f} min ago, outcomes={outcomes})")
        print(f"[FWD-WATCHDOG] status=OK age_min={age / 60.0:.0f} outcomes={outcomes} "
              f"pass_alive={pass_alive} terminal={terminal_alive}")
        return 0

    # stalled — alert once per episode
    already = (not args.force and abs(_last_alerted_mtime() - mtime) < 1.0)
    last_write_utc = datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds")
    state_desc = "RUNNING but stalled (dead chunk)" if pass_alive else "NOT RUNNING"
    if already:
        print(f"[FWD-WATCHDOG] status=STALLED (already alerted) age_min={age / 60.0:.0f} "
              f"outcomes={outcomes} last_write={last_write_utc}Z")
        return 1
    msg = (f"ALERT forward-demo journal SILENT for {age / 60.0:.0f} min "
           f"(last write {last_write_utc}Z, {outcomes} closed trades, "
           f"pass {state_desc}, MT5 terminal {'up' if terminal_alive else 'down'}) — "
           f"a stalled pass will silently miss the 18-24h (server) window; "
           f"restart: python mql5/forward_demo_pass.py")
    _write_alert(msg)
    _mark_alerted(mtime)
    print(f"[FWD-WATCHDOG] status=STALLED age_min={age / 60.0:.0f} outcomes={outcomes} "
          f"pass_alive={pass_alive} terminal={terminal_alive} last_write={last_write_utc}Z")
    print(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
