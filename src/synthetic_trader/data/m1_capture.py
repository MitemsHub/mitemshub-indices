"""Continuous M1-rate capture loop for compounding the tick corpus.

The walk-forward optimizer and horizon-forecast dashboard only learn as
much as the data allows, and the historical corpus stops growing the
moment nobody runs ``backfill-mt5`` by hand.  This service keeps
``data/backfill/{symbol}_ticks.csv`` compounding **in the background** by
reusing the exact machinery that powers ``backfill-mt5``
(:func:`~synthetic_trader.calibration.mt5_collector.fetch_m1_candles` —
server-backed M1 OHLC from the Deriv MT5 terminal, at the CORRECT
SYN75/SYN100 price scale).

Design:

- **Incremental, not re-fetch.**  Each sweep fetches only the M1 candles
  since the newest candle already in the file (minus a small overlap so a
  candle that was still forming last sweep is picked up), expands them to
  OHLC-exact ticks via ``candles_to_ticks``, and merges with the existing
  corpus.  ``normalize_ticks`` dedupes by ``(symbol, epoch, price)``, so
  overlap re-fetches never double-write.
- **Forming-candle safe.**  ``fetch_m1_candles`` excludes the still-forming
  minute candle; the overlap window is what catches it on the next sweep
  once its OHLC is final.  A re-fetched final candle has identical OHLC and
  dedupes cleanly, so the corpus never contains two versions of a bucket.
- **First-run seeding.**  A symbol with no file yet is seeded from
  ``initial_days`` (default 7) of history — identical to a one-shot
  ``backfill-mt5``.  After that every sweep only adds what is new.
- **Rollover/downtime tolerant.**  An empty fetch (daily rollover pause,
  terminal closed) is not an error — the sweep just records zero added and
  retries next interval.  Gaps between candles are measured and reported as
  ``max_gap_sec`` so you can see where history is missing.
- **Status telemetry.**  A JSON status file (``data/m1_capture.json``) is
  rewritten after every sweep, mirroring the live-tick collector pattern,
  so the operator can see per-symbol growth.
- **Cron friendly.**  ``run_once=True`` performs a single sweep and exits —
  pair it with Task Scheduler / cron for a daily compounding job without a
  resident process.

Usage::

    python -m synthetic_trader.cli capture-m1 --symbols R_75,R_100          # hourly sweep loop
    python -m synthetic_trader.cli capture-m1 --symbols R_75,R_100 --once    # single sweep (cron)

.. note::
    Do not run this loop and the live tick collector
    (``collect-live-ticks``) against the SAME symbol file at the same time
    — both rewrite ``{symbol}_ticks.csv``.  They are complements: run the
    live collector while you are watching the terminal, and this loop (or a
    daily ``--once`` cron) as the always-on compounding backstop.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from synthetic_trader.calibration.mt5_collector import (
    fetch_m1_candles,
    get_venue_symbol,
)
from synthetic_trader.data.collector import candles_to_ticks
from synthetic_trader.data.tick_store import (
    MAX_TICKS_PER_CSV,
    normalize_ticks,
    read_ticks_csv,
    write_ticks_csv,
)
from synthetic_trader.domain import Tick

# ── Defaults ────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = "data/backfill"
DEFAULT_STATUS_PATH = "data/m1_capture.json"
# How often the loop sweeps the terminal for new M1 candles.  M1 data only
# changes per completed minute, so an hourly sweep is plenty and cheap.
DEFAULT_INTERVAL_SEC = 3600.0
# Re-fetch overlap: candles in the last `overlap_sec` are fetched again so a
# candle that was forming during the previous sweep is captured once final.
DEFAULT_OVERLAP_SEC = 300.0
# First capture of a symbol seeds this much history (matches the default
# `--days` of `backfill-mt5`).
DEFAULT_INITIAL_DAYS = 7.0
# The MT5 terminal can be slow to start; back off between failed sweeps.
SWEEP_BACKOFF_SEC = 30.0
MAX_CONSECUTIVE_ERRORS = 5  # give up after this many failed sweeps in a row

# Warn when the corpus approaches the tick-store cap (the live-tick
# collector prunes at MAX_TICKS_PER_CSV; M1 capture never prunes but flags it).
CAP_WARN_FRACTION = 0.8


@dataclass
class M1CaptureStats:
    """Outcome of one incremental M1 capture for one symbol."""

    symbol: str
    venue_symbol: str
    output_path: str
    captured_at: float = 0.0
    since_epoch: float | None = None
    first_epoch: float | None = None  # oldest closed candle fetched
    last_epoch: float | None = None  # newest closed candle fetched
    candles_fetched: int = 0
    ticks_before: int = 0
    ticks_after: int = 0
    ticks_added: int = 0
    max_gap_sec: float = 0.0
    error: str | None = None
    warning: str | None = None  # non-fatal (e.g. corpus near size cap)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "venue_symbol": self.venue_symbol,
            "output_path": self.output_path,
            "captured_at": self.captured_at,
            "since_epoch": self.since_epoch,
            "first_epoch": self.first_epoch,
            "last_epoch": self.last_epoch,
            "candles_fetched": self.candles_fetched,
            "ticks_before": self.ticks_before,
            "ticks_after": self.ticks_after,
            "ticks_added": self.ticks_added,
            "max_gap_sec": self.max_gap_sec,
            "error": self.error,
            "warning": self.warning,
        }

    def summary(self) -> str:
        return (
            f"symbol={self.symbol}\n"
            f"venue_symbol={self.venue_symbol}\n"
            f"output={self.output_path}\n"
            f"captured_at={self.captured_at}\n"
            f"since_epoch={self.since_epoch}\n"
            f"first_epoch={self.first_epoch}\n"
            f"last_epoch={self.last_epoch}\n"
            f"candles_fetched={self.candles_fetched}\n"
            f"ticks_before={self.ticks_before}\n"
            f"ticks_after={self.ticks_after}\n"
            f"ticks_added={self.ticks_added}\n"
            f"max_gap_sec={self.max_gap_sec:.1f}\n"
            f"error={self.error}\n"
            f"warning={self.warning}"
        )


def _max_candle_gap_sec(candles: list[dict[str, float]]) -> float:
    """Largest gap (beyond the 60s cadence) between consecutive candles."""
    if len(candles) < 2:
        return 0.0
    largest = 0.0
    for prev, curr in zip(candles[:-1], candles[1:]):
        gap = float(curr["epoch"]) - float(prev["epoch"]) - 60.0
        largest = max(largest, max(0.0, gap))
    return largest


def _atomic_write_ticks_csv(path: Path, ticks: list[Tick]) -> None:
    """Write the merged corpus atomically (temp file + rename).

    The compounding corpus must never be left half-written if the process
    is killed mid-sweep — a corrupt file would poison every downstream
    reader (WFO, horizon dashboard) until manually repaired.
    """
    if not ticks:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".csv", dir=path.parent, prefix=path.stem + "_"
    )
    os.close(fd)
    try:
        write_ticks_csv(tmp_path, ticks, append=False)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def capture_m1_incremental(
    symbol: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    since_epoch: float | None = None,
    initial_days: float = DEFAULT_INITIAL_DAYS,
    overlap_sec: float = DEFAULT_OVERLAP_SEC,
    terminal_path: str | None = None,
    venue_symbol: str | None = None,
) -> M1CaptureStats:
    """Capture new M1 candles for *symbol* and merge them into the corpus.

    - First run (no file): seeds ``initial_days`` of history.
    - Later runs: fetches only candles since the newest candle in the file,
      minus ``overlap_sec``, and merges (dedupe by epoch+price).
    - The still-forming minute candle is excluded by
      :func:`fetch_m1_candles`; the overlap window picks it up next sweep.

    Returns per-symbol stats.  An empty fetch (rollover pause / terminal
    closed) is NOT an error — ``candles_fetched == 0`` and the caller retries
    next sweep.  MT5 connection failures raise :class:`RuntimeError`.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{symbol}_ticks.csv"
    venue = venue_symbol or get_venue_symbol(symbol)

    existing = read_ticks_csv(output_path, symbol)
    last_epoch = existing[-1].epoch if existing else None

    if since_epoch is None:
        if last_epoch is not None:
            since_epoch = last_epoch - overlap_sec
        else:
            since_epoch = time.time() - initial_days * 86400.0
    else:
        since_epoch = since_epoch - overlap_sec

    stats = M1CaptureStats(
        symbol=symbol,
        venue_symbol=venue,
        output_path=str(output_path),
        captured_at=time.time(),
        since_epoch=since_epoch,
        ticks_before=len(existing),
    )

    candles = fetch_m1_candles(
        symbol,
        since_epoch=since_epoch,
        venue_symbol=venue_symbol,
        terminal_path=terminal_path,
    )
    # Belt-and-braces: never merge the still-forming minute candle, even if
    # the fetch layer returns it (clock skew, future fetch variants).
    if candles:
        now_bucket = int(time.time()) // 60 * 60
        candles = [c for c in candles if float(c["epoch"]) < now_bucket]

    stats.candles_fetched = len(candles)
    if candles:
        stats.first_epoch = float(candles[0]["epoch"])
        stats.last_epoch = float(candles[-1]["epoch"])
        stats.max_gap_sec = _max_candle_gap_sec(candles)

    if candles:
        new_ticks = candles_to_ticks(symbol, candles, timeframe_sec=60)
        merged = existing + new_ticks
        normalized, _ = normalize_ticks(merged)
        _atomic_write_ticks_csv(output_path, normalized)
        stats.ticks_after = len(normalized)
        stats.ticks_added = stats.ticks_after - stats.ticks_before
    else:
        stats.ticks_after = len(existing)

    if stats.ticks_after >= MAX_TICKS_PER_CSV * CAP_WARN_FRACTION:
        stats.warning = (
            f"corpus near tick-store cap ({stats.ticks_after}/{MAX_TICKS_PER_CSV}); "
            "consider archiving old history"
        )
    return stats


async def run_m1_capture_loop(
    symbols: list[str],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    initial_days: float = DEFAULT_INITIAL_DAYS,
    overlap_sec: float = DEFAULT_OVERLAP_SEC,
    terminal_path: str | None = None,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    run_once: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, M1CaptureStats]:
    """Sweep M1 rates for *symbols* into the corpus on a schedule.

    Runs forever (or until interrupted), sweeping every ``interval_sec``,
    unless ``run_once`` is set — then a single sweep is performed and the
    function returns.  After every sweep the status JSON is rewritten.  A
    sweep failure (MT5 connection error) is recorded on the symbol's stats
    and retried with backoff; after ``MAX_CONSECUTIVE_ERRORS`` consecutive
    failures the loop gives up rather than spin forever.
    """
    stats: dict[str, M1CaptureStats] = {}
    consecutive_errors = 0
    while True:
        for symbol in symbols:
            try:
                result = capture_m1_incremental(
                    symbol,
                    output_dir,
                    initial_days=initial_days,
                    overlap_sec=overlap_sec,
                    terminal_path=terminal_path,
                )
                stats[symbol] = result
                consecutive_errors = 0
                log(
                    f"[m1-capture:{symbol}] +{result.ticks_added} ticks "
                    f"({result.ticks_before} -> {result.ticks_after}, "
                    f"{result.candles_fetched} candles)"
                )
            except RuntimeError as exc:
                consecutive_errors += 1
                stats[symbol] = M1CaptureStats(
                    symbol=symbol,
                    venue_symbol=get_venue_symbol(symbol),
                    output_path=str(Path(output_dir) / f"{symbol}_ticks.csv"),
                    captured_at=time.time(),
                    error=str(exc),
                )
                log(f"[m1-capture:{symbol}] error: {exc}")
            except Exception as exc:  # pragma: no cover - defensive
                consecutive_errors += 1
                stats[symbol] = M1CaptureStats(
                    symbol=symbol,
                    venue_symbol=get_venue_symbol(symbol),
                    output_path=str(Path(output_dir) / f"{symbol}_ticks.csv"),
                    captured_at=time.time(),
                    error=f"{type(exc).__name__}: {exc}",
                )
                log(f"[m1-capture:{symbol}] unexpected error: {exc}")

        await _write_status(stats, status_path)
        if run_once:
            break
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            log(
                f"[m1-capture] giving up after {consecutive_errors} consecutive "
                f"failed sweeps — check the MT5 terminal is open and logged in"
            )
            break
        await asyncio.sleep(interval_sec)
    return stats


async def _write_status(
    stats: dict[str, M1CaptureStats], status_path: str | Path
) -> None:
    try:
        path = Path(status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbols": {sym: s.to_dict() for sym, s in stats.items()},
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # pragma: no cover - best effort telemetry
        pass
