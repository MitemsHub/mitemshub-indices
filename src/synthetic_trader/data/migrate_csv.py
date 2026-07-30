"""Migrate legacy 3-column CSV files to the enriched 6-column format.

Usage:
    python -m synthetic_trader.data.migrate_csv data/R_100_ticks.csv data/R_75_ticks.csv

Or call migrate_legacy_csv(path) from anywhere in the codebase.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def migrate_legacy_csv(path: str | Path) -> bool:
    """Upgrade a legacy 3-column CSV (epoch,symbol,price) to the 6-column enriched format.

    Returns True if the file was migrated, False if already enriched or empty.
    The original file is replaced atomically via a temp file.
    """
    target = Path(path)
    if not target.exists() or target.stat().st_size == 0:
        return False

    # Quick header check
    with target.open("r", encoding="utf-8") as f:
        header = f.readline().strip()
    if "spread" in header:
        return False  # already enriched

    # Read all lines and enrich
    with target.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) < 2:
        return False

    enriched: list[str] = ["epoch,symbol,price,spread,direction,vol_proxy\n"]
    prev_price: float | None = None
    prev_epoch: float | None = None

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            epoch = float(parts[0])
            symbol = parts[1]
            price = float(parts[2])
        except (ValueError, IndexError):
            continue

        spread = 0.0
        direction = 0
        vol_proxy = 0.0

        if prev_price is not None:
            delta = price - prev_price
            spread = abs(delta) / 2.0
            if delta > 0:
                direction = 1
            elif delta < 0:
                direction = -1

        if prev_epoch is not None:
            dt = epoch - prev_epoch
            if dt > 0:
                vol_proxy = 1.0 / dt

        enriched.append(f"{epoch},{symbol},{price},{spread},{direction},{vol_proxy}\n")
        prev_price = price
        prev_epoch = epoch

    # Atomic replace via temp file
    fd, tmp_path = tempfile.mkstemp(suffix=".csv", dir=target.parent, prefix=target.stem + "_")
    try:
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8", newline="") as fh:
            fh.writelines(enriched)
        os.replace(tmp_path, str(target))
        return True
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m synthetic_trader.data.migrate_csv <csv_path> [csv_path ...]")
        sys.exit(1)

    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"{arg}: not found, skipping")
            continue
        print(f"{arg}: migrating...")
        if migrate_legacy_csv(p):
            print(f"{arg}: migrated successfully")
        else:
            print(f"{arg}: already enriched or empty")
