#!/usr/bin/env python3
"""Copy fresh tick-session CSVs from the MT5 terminal Files dir into the repo.

The EA writes tick CSVs into MQL5/Files of the first terminal instance. This
script copies any file newer than its repo counterpart into artifacts/ticks so
the verdict tooling always sees the freshest sessions. Run it before
tick_fade_verdict.py, or on a schedule.

Usage:
  python scripts/sync_tick_sessions.py [--watch]
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_FILES = Path(
    r"C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal"
    r"\FB9A56D617EDDDFE29EE54EBEFFE96C1\MQL5\Files"
)
DEST = ROOT / "artifacts" / "ticks"
POLL_S = 60


def sync_once() -> int:
    if not TERMINAL_FILES.exists():
        print(f"[sync] terminal Files dir not found: {TERMINAL_FILES}")
        return 1
    DEST.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in TERMINAL_FILES.glob("MITEMSHUB_ticks_*.csv"):
        dst = DEST / src.name
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)
            copied += 1
            print(f"[sync] {src.name} -> {dst.relative_to(ROOT)}")
    print(f"[sync] {copied} file(s) updated")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="poll every 60s instead of one-shot")
    args = ap.parse_args()
    if not args.watch:
        return sync_once()
    while True:
        sync_once()
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
