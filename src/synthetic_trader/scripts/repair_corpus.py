"""Repair a sparse tick corpus by backfilling missing M5 buckets from the
Deriv terminal's M1 history.

The continuous collector appends real ticks to ``data/backfill/{symbol}_ticks.csv``,
but when it is down (restarts, IPC timeouts, gaps) whole M5 buckets go missing —
the corpus becomes ~50% dense while the terminal's SYN75/SYN100 cache is
full-density.  That makes the P10-A strict-parity gate unenforceable (the
gate's corpus-density branch stays in "data mismatch" mode) and starves the
live engine's vol-extension gate, which needs contiguous bars to fire.

Repair = **merge**, not replace: every real tick already in the corpus is kept
verbatim (including its derived spread/direction/vol_proxy columns), and for
every M5 bucket that cannot form a valid OHLC candle (fewer than
``min_ticks_per_bucket`` existing ticks) the script injects 4 OHLC-exact ticks
per M1 candle reconstructed from the terminal's ``copy_rates_range`` — the
SAME server data the tester cache is built from, so the repaired corpus and the
tester see the same M5 bars.

Example:
    python -m synthetic_trader.scripts.repair_corpus --symbol R_75
    python -m synthetic_trader.scripts.repair_corpus --symbol R_100 --backup
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from synthetic_trader.data.collector import candles_to_ticks
from synthetic_trader.data.tick_store import CSV_FIELDNAMES, normalize_ticks, write_ticks_csv
from synthetic_trader.domain import Tick

# M5 bucket size — the corpus's candle granularity for the band/sniper engines.
BUCKET_SEC = 300
# A bucket with fewer ticks than this cannot represent a real OHLC candle
# (open/high/low/close needs 4 distinct touches), so it is treated as missing.
MIN_TICKS_PER_BUCKET = 4
# Expected M5 buckets per full day (24h / 5m).
BUCKETS_PER_DAY = 288


def _read_ticks_with_columns(path: Path, symbol: str) -> list[Tick]:
    """Read a tick CSV keeping the derived columns (unlike load_ticks_csv)."""
    ticks: list[Tick] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first = handle.readline()
        handle.seek(0)
        has_header = first.strip().lower().startswith(("epoch", "symbol", "price"))
        if has_header:
            reader: Any = csv.DictReader(handle)
            for row in reader:
                try:
                    epoch = float(row["epoch"])
                    price = float(row["price"])
                except (TypeError, ValueError, KeyError):
                    continue
                ticks.append(
                    Tick(
                        symbol=row.get("symbol") or symbol,
                        epoch=epoch,
                        price=price,
                        spread=float(row.get("spread") or 0.0),
                        tick_direction=int(float(row.get("direction") or 0)),
                        volume_proxy=float(row.get("vol_proxy") or 0.0),
                    )
                )
        else:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                try:
                    if len(row) == 2:
                        epoch, price = float(row[0]), float(row[2 - 1])
                    elif len(row) > 2:
                        epoch, price = float(row[0]), float(row[2])
                    else:
                        continue
                except (TypeError, ValueError):
                    continue
                sym = row[1].strip() if len(row) > 1 and row[1].strip() else symbol
                ticks.append(Tick(symbol=sym, epoch=epoch, price=price))
    return ticks


def compute_density(ticks: list[Tick], bucket_sec: int = BUCKET_SEC) -> tuple[float, int, float]:
    """Unique-bucket density over the span, matching the P10-A gate's formula."""
    buckets: set[int] = set()
    lo: float | None = None
    hi: float | None = None
    for t in ticks:
        buckets.add(int(t.epoch // bucket_sec) * bucket_sec)
        if lo is None or t.epoch < lo:
            lo = t.epoch
        if hi is None or t.epoch > hi:
            hi = t.epoch
    if not buckets or lo is None or hi is None:
        return 0.0, 0, 0.0
    days = (hi - lo) / 86400.0 + 1.0
    return len(buckets) / (days * BUCKETS_PER_DAY), len(buckets), days


def repair_corpus(symbol: str, csv_path: str | Path, *, backup: bool = False) -> dict[str, object]:
    """Backfill missing M5 buckets in ``csv_path`` from the terminal's M1 history.

    Returns a report dict with before/after density and bucket counts.
    """
    from synthetic_trader.calibration.mt5_collector import fetch_m1_candles

    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"corpus not found: {path}")

    existing = _read_ticks_with_columns(path, symbol)
    if not existing:
        raise RuntimeError(f"corpus {path} has no parseable ticks")

    dens_before, buckets_before, days = compute_density(existing)
    print(f"[repair] {symbol}: {len(existing)} existing ticks, "
          f"density {dens_before:.3f} ({buckets_before} buckets over {days:.1f} days)")

    # --- per-bucket existing tick counts (only symbol-matching rows) ----------
    by_bucket: dict[int, int] = defaultdict(int)
    for t in existing:
        if t.symbol != symbol:
            continue
        by_bucket[int(t.epoch // BUCKET_SEC) * BUCKET_SEC] += 1

    # --- fetch terminal M1 history over the corpus span -----------------------
    lo = min(t.epoch for t in existing)
    hi = max(t.epoch for t in existing)
    # +6h tail so the still-forming edge is included; fetch_m1_candles drops the
    # unclosed current minute itself.
    candles = fetch_m1_candles(symbol, since_epoch=lo - 3600)
    if not candles:
        raise RuntimeError(f"no M1 rates returned for {symbol} — terminal history unavailable")
    print(f"[repair] terminal returned {len(candles)} M1 candles "
          f"({candles[0]['epoch']:.0f} -> {candles[-1]['epoch']:.0f})")

    recon = candles_to_ticks(symbol, candles, timeframe_sec=60)

    # --- keep reconstructed ticks ONLY for buckets that need filling ----------
    # NOTE: the bucket gate reads by_bucket (the EXISTING tick count) and must
    # never mutate it — otherwise the first injected tick would bump the count
    # past MIN_TICKS_PER_BUCKET and starve the remaining ~19 ticks out of the
    # same bucket, leaving degenerate single-price M5 candles.  The report
    # counter uses a separate set.
    fill: list[Tick] = []
    counted: set[int] = set()
    for t in recon:
        b = int(t.epoch // BUCKET_SEC) * BUCKET_SEC
        if by_bucket.get(b, 0) < MIN_TICKS_PER_BUCKET:
            fill.append(t)
            if b not in counted:
                counted.add(b)
    print(f"[repair] injecting {len(fill)} reconstructed ticks into "
          f"{len(counted)} previously-missing buckets")

    merged, _ = normalize_ticks(existing + fill)
    dens_after, buckets_after, _ = compute_density(merged)

    if backup:
        bak = path.with_suffix(".csv.pre-repair")
        import shutil

        shutil.copy2(path, bak)
        print(f"[repair] backup written: {bak}")

    write_ticks_csv(path, merged, append=False)
    print(f"[repair] wrote {len(merged)} ticks -> {path}")
    print(f"[repair] density {dens_before:.3f} -> {dens_after:.3f} "
          f"(buckets {buckets_before} -> {buckets_after})")

    return {
        "symbol": symbol,
        "existing_ticks": len(existing),
        "injected_ticks": len(fill),
        "filled_buckets": len(counted),
        "density_before": dens_before,
        "density_after": dens_after,
        "buckets_before": buckets_before,
        "buckets_after": buckets_after,
        "path": str(path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill missing M5 buckets in a tick corpus")
    parser.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    parser.add_argument("--csv", help="corpus path (default: data/backfill/{symbol}_ticks.csv)")
    parser.add_argument("--backup", action="store_true", help="copy the pre-repair corpus to .pre-repair")
    args = parser.parse_args(argv)

    csv_path = args.csv or f"data/backfill/{args.symbol}_ticks.csv"
    report = repair_corpus(args.symbol, csv_path, backup=args.backup)
    if float(str(report["density_after"])) < 0.80:
        print(f"[repair] WARNING: density {report['density_after']:.3f} still below "
              "the 0.80 strict-parity threshold", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
