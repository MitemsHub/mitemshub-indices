"""Continuous live tick collection service (Deriv MT5 terminal).

Deriv synthetic indices (SYN75 / SYN100 — the instruments the user actually
trades on Deriv) trade **24/7/365 with no weekend close**, but there is
one scheduled pause: the **daily rollover** around 00:00 broker server time
(UTC), typically a short stall while the index resets its epoch counter.

This service collects real ticks continuously from the Deriv MT5
terminal and appends them to the standard tick CSV (``data/backfill/``),
reusing :func:`append_ticks_csv` so every write is deduplicated against the
file tail, enriched with derived columns, and pruned at the size cap — the
same storage path the walk-forward optimizer and horizon-forecast dashboard
already read.

Design:

- **Correct source.** MT5 (Deriv) only. The Deriv WebSocket fallback
  trades at a different price scale (1HZ75V ~7,000 vs SYN75 ~1,500) and
  would corrupt the corpus — so this service refuses to run without a
  reachable terminal.
- **Rollover-aware stalls.** Ticks normally arrive ~1/sec on a 1s index.
  A ``RolloverCalendar`` marks the daily rollover window (configurable,
  default 00:00 UTC ± 2 min); stalls *inside* that window are expected and
  never trigger reconnect.  Stalls *outside* it warn after
  ``stall_warn_sec`` and force a reconnect after ``stall_reconnect_sec``
  (the terminal may have lost the feed).
- **Mutual pause with the verify loop.** ``mql5/verify_all.ps1`` writes a
  marker (``.data/verify_pause.flag``) before it closes the live terminal
  for tester runs and removes it after restoring it.  While the marker is
  fresh, the collector stands down completely — no tick polling (the
  Python client could otherwise attach to the *tester* instance and
  pollute the corpus with modeled ticks), no stall warnings, no
  reconnects — and restarts its stall timer on resume.  A marker older
  than ``VERIFY_PAUSE_STALE_SEC`` is ignored, so a crashed verify
  self-heals.
- **Session-safe appends.** ``append_ticks_csv`` dedupes by ``(epoch,
  price)`` against the file tail, so overlapping poll windows and restarts
  never double-write.
- **Status telemetry.** A JSON status file (``data/live_tick_collector.json``)
  is written periodically so the operator dashboard can surface collection
  health, mirroring the ``mt5_last_error.json`` pattern.

Usage::

    python -m synthetic_trader.cli collect-live-ticks --symbols R_75,R_100
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from synthetic_trader.data.tick_store import append_ticks_csv
from synthetic_trader.domain import Tick
from synthetic_trader.execution.mt5_data import Mt5TickClient

# ── Defaults ────────────────────────────────────────────────────────────
# Rollover: the daily pause at 00:00 broker server time (UTC).  Stalls
# inside this window are expected and do not trigger reconnect logic.
ROLLOVER_HOUR_UTC = 0
ROLLOVER_GRACE_SEC = 120.0  # ±2 minutes around 00:00 UTC

# Poll cadence.  A 1s synthetic index produces ~1 tick/sec; 0.5s polling
# catches every tick with margin while staying cheap.
POLL_INTERVAL_SEC = 0.5
# How often accumulated ticks are flushed to CSV (time-based) …
FLUSH_INTERVAL_SEC = 30.0
# … and/or tick-count based, whichever comes first.
FLUSH_BATCH_SIZE = 500

# Stall watchdog (seconds without a fresh tick, outside the rollover window).
STALL_WARN_SEC = 120.0
STALL_RECONNECT_SEC = 600.0

# Reconnect/backoff policy.
MAX_CONSECUTIVE_ERRORS = 5
RECONNECT_BACKOFF_SEC = 5.0
MAX_RECONNECTS = 50  # give up after ~50 reconnect attempts (terminal closed)

# Status telemetry.
STATUS_PATH = "data/live_tick_collector.json"
STATUS_INTERVAL_SEC = 10.0

# Persistent MT5 event log (JSONL): every reconnect/init-failure/feed-loss
# is appended here with a timestamp so the 48h health analysis (and the
# IPC-timeout recurrence verdict) has a full history instead of the last few
# errors in the status file.  cwd-relative like the status path.
MT5_EVENTS_PATH = Path(".data") / "mt5_events.jsonl"

# Mutual pause with the verify loop.  ``mql5/verify_all.ps1`` writes this
# marker (absolute ``<repo>/.data/verify_pause.flag``) right before it closes
# the live terminal for tester runs and removes it after restoring it.  While
# the marker is present and fresh the collector stands down completely — no
# tick polling (the Python client could otherwise attach to the *tester*
# instance and pollute the corpus with modeled ticks), no stall warnings, no
# reconnects.  A crashed verify leaves the file behind, so a marker older
# than ``VERIFY_PAUSE_STALE_SEC`` is treated as expired and ignored.
VERIFY_PAUSE_PATH = Path(".data") / "verify_pause.flag"
VERIFY_PAUSE_STALE_SEC = 7200.0  # a full verify run is <= ~30 min; 2h covers a crash


# ── MT5 event telemetry ─────────────────────────────────────────────────
def _classify_mt5_event(message: str) -> str:
    """Bucket a reconnect error into a measurable kind."""
    low = message.lower()
    if "initialize failed" in low or "ipc timeout" in low or "connection failed" in low:
        return "init_failed"
    if "feed lost" in low:
        return "feed_lost"
    if "consecutive read errors" in low:
        return "read_errors"
    return "reconnect"


def _append_mt5_event(kind: str, message: str) -> None:
    """Append one timestamped event line; best-effort (never crash the
    collector over logging)."""
    try:
        MT5_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MT5_EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, "message": message}) + "\n")
    except Exception:
        pass


def _verify_pause_state(
    path: str | Path = VERIFY_PAUSE_PATH, now: float | None = None
) -> str | None:
    """Return the pauser's ``reason`` while the verify pause is active, else None.

    Active when the marker exists and its ``started`` epoch is newer than
    ``VERIFY_PAUSE_STALE_SEC`` — a crashed verify run leaves the file behind
    and the pause must self-heal.  Any malformed/unreadable marker is treated
    as inactive (fail-open: never let a broken file stand the collector down
    forever).
    """
    if now is None:
        now = time.time()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8").strip())
        started = float(data.get("started", 0))
        if now - started > VERIFY_PAUSE_STALE_SEC:
            return None
        return str(data.get("reason", "verify"))
    except Exception:
        return None

DEFAULT_OUTPUT_DIR = "data/backfill"


@dataclass(frozen=True)
class RolloverCalendar:
    """Defines the daily rollover pause window for synthetic indices.

    ``in_rollover(epoch)`` is True inside ``rollover_hour_utc:00 ±
    grace_sec`` (wrapping across midnight).  Stalls in this window are
    expected maintenance and must not be treated as a broken feed.
    """

    rollover_hour_utc: int = ROLLOVER_HOUR_UTC
    grace_sec: float = ROLLOVER_GRACE_SEC

    def in_rollover(self, epoch: float) -> bool:
        # Grace covering the whole day (or more) means every epoch is rollover.
        if self.grace_sec >= 86400.0:
            return True
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        seconds_into_day = dt.hour * 3600 + dt.minute * 60 + dt.second
        center = (self.rollover_hour_utc % 24) * 3600
        half = self.grace_sec
        low = (center - half) % 86400.0
        high = (center + half) % 86400.0
        if low <= high:
            return low <= seconds_into_day <= high
        # Window wraps across midnight (e.g. 23:58 → 00:02).
        return seconds_into_day >= low or seconds_into_day <= high


@dataclass
class CollectorStats:
    """Running totals for one symbol's collection session."""

    symbol: str
    venue_symbol: str
    output_path: str
    started_at: float = 0.0
    ticks_collected: int = 0
    duplicates_skipped: int = 0
    batches_flushed: int = 0
    reconnect_attempts: int = 0
    stalls_warned: int = 0
    last_tick_epoch: float | None = None
    last_price: float | None = None
    errors: list[str] = field(default_factory=list)
    # Verify-loop mutual pause: non-None while standing down (reason string)
    # plus cumulative pause time, surfaced in status telemetry.
    paused_by: str | None = None
    paused_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "venue_symbol": self.venue_symbol,
            "output_path": self.output_path,
            "started_at": self.started_at,
            "ticks_collected": self.ticks_collected,
            "duplicates_skipped": self.duplicates_skipped,
            "batches_flushed": self.batches_flushed,
            "reconnect_attempts": self.reconnect_attempts,
            "stalls_warned": self.stalls_warned,
            "last_tick_epoch": self.last_tick_epoch,
            "last_price": self.last_price,
            "errors": self.errors,
            "paused_by": self.paused_by,
            "paused_sec": self.paused_sec,
        }

    def summary(self) -> str:
        return (
            f"symbol={self.symbol}\n"
            f"venue_symbol={self.venue_symbol}\n"
            f"output={self.output_path}\n"
            f"ticks={self.ticks_collected}\n"
            f"duplicates_skipped={self.duplicates_skipped}\n"
            f"batches_flushed={self.batches_flushed}\n"
            f"reconnect_attempts={self.reconnect_attempts}\n"
            f"stalls_warned={self.stalls_warned}\n"
            f"last_tick_epoch={self.last_tick_epoch}\n"
            f"last_price={self.last_price}\n"
            f"paused_by={self.paused_by}\n"
            f"paused_sec={self.paused_sec:.1f}\n"
        )


class TickCollector:
    """Collect real ticks from the MT5 terminal into a tick CSV.

    Polls ``symbol_info_tick`` for the *latest* real tick (with the
    terminal's true ``time_msc`` epoch), batches new ticks, and appends
    through :func:`append_ticks_csv` (dedup + derived columns + prune).

    Rollover-aware: no fresh tick inside the rollover window is expected
    and never triggers a reconnect; a stall outside it eventually forces a
    fresh client connection.
    """

    def __init__(
        self,
        symbol: str,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
        *,
        venue_symbol: str | None = None,
        poll_interval_sec: float = POLL_INTERVAL_SEC,
        flush_interval_sec: float = FLUSH_INTERVAL_SEC,
        flush_batch_size: int = FLUSH_BATCH_SIZE,
        stall_warn_sec: float = STALL_WARN_SEC,
        stall_reconnect_sec: float = STALL_RECONNECT_SEC,
        rollover: RolloverCalendar | None = None,
        pause_path: str | Path = VERIFY_PAUSE_PATH,
        log: Callable[[str], None] = print,
    ) -> None:
        self.symbol = symbol
        self.venue_symbol = venue_symbol
        self.output_dir = Path(output_dir)
        self.poll_interval_sec = poll_interval_sec
        self.flush_interval_sec = flush_interval_sec
        self.flush_batch_size = flush_batch_size
        self.stall_warn_sec = stall_warn_sec
        self.stall_reconnect_sec = stall_reconnect_sec
        self.rollover = rollover or RolloverCalendar()
        self._log = log
        self._pause_path = Path(pause_path)
        self._paused_since: float | None = None
        self.output_path = self.output_dir / f"{symbol}_ticks.csv"
        self.stats = CollectorStats(
            symbol=symbol,
            venue_symbol=venue_symbol or "",
            output_path=str(self.output_path),
        )
        self._pending: list[Tick] = []
        self._last_epoch: float | None = None
        self._last_flush_epoch: float | None = None
        self._last_tick_wall: float | None = None
        self._last_flush_wall: float | None = None

    # ── Core loop ─────────────────────────────────────────────────────

    async def run(
        self,
        client: Mt5TickClient,
        *,
        duration_sec: float | None = None,
        stop_event: asyncio.Event | None = None,
        mt5_lock: asyncio.Lock | None = None,
    ) -> CollectorStats:
        """Run collection against an open client until stopped/errored.

        Returns the updated stats.  Raises :class:`RuntimeError` when the
        terminal feed is lost (stall outside rollover, repeated read
        errors) so the caller can reconnect and call :meth:`run` again —
        the file-level dedupe keeps reconnects safe.
        """
        self.stats.started_at = self.stats.started_at or time.time()
        if self.venue_symbol:
            self.stats.venue_symbol = self.venue_symbol
        else:
            try:
                self.stats.venue_symbol = client.mt5_symbol(self.symbol)
            except Exception:  # pragma: no cover - defensive
                pass
        self.output_dir.mkdir(parents=True, exist_ok=True)

        started = time.time()
        consecutive_errors = 0
        stall_warned = False
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                if duration_sec is not None and time.time() - started >= duration_sec:
                    break

                # Mutual pause with the verify loop (see VERIFY_PAUSE_PATH):
                # while verify_all.ps1's marker is fresh, the tester owns the
                # terminal and the live one is closed.  Stand down completely
                # — no tick polling (the Python client could attach to the
                # *tester* instance and pollute the corpus with modeled
                # ticks), no stall warnings, no reconnects.
                pause = _verify_pause_state(self._pause_path)
                if pause:
                    if self._paused_since is None:
                        self._paused_since = time.time()
                        self.stats.paused_by = pause
                        self._last_tick_wall = None
                        stall_warned = False
                        self._log(
                            f"[collector:{self.symbol}] paused by {pause} "
                            f"(tester run owns the terminal) - standing down"
                        )
                    self.stats.paused_sec = time.time() - self._paused_since
                    await asyncio.sleep(self.poll_interval_sec)
                    continue
                if self._paused_since is not None:
                    self._log(
                        f"[collector:{self.symbol}] {self.stats.paused_by} cleared "
                        f"- resuming collection"
                    )
                    self._paused_since = None
                    self.stats.paused_by = None
                    self.stats.paused_sec = 0.0
                    # Restart the stall timer from scratch — the pre-pause
                    # last-tick age can be hours old and must not trigger an
                    # immediate stall/reconnect on resume.
                    self._last_tick_wall = None
                    stall_warned = False

                try:
                    if mt5_lock is not None:
                        # The MT5 Python package is not thread-safe; serialize
                        # all terminal calls when collectors share one client.
                        async with mt5_lock:
                            tick = await client.latest_tick(self.symbol)
                    else:
                        tick = await client.latest_tick(self.symbol)
                    consecutive_errors = 0
                except Exception as exc:  # pragma: no cover - depends on terminal
                    consecutive_errors += 1
                    self._log(
                        f"[collector:{self.symbol}] read error {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}: {exc}"
                    )
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        raise RuntimeError(
                            f"{self.symbol}: {consecutive_errors} consecutive read errors from MT5"
                        ) from exc
                    await asyncio.sleep(self.poll_interval_sec)
                    continue

                now = time.time()
                if tick is not None and (
                    self._last_epoch is None or tick.epoch > self._last_epoch
                ):
                    self._pending.append(tick)
                    self.stats.ticks_collected += 1
                    self._last_epoch = tick.epoch
                    self._last_tick_wall = now
                    self.stats.last_tick_epoch = tick.epoch
                    self.stats.last_price = tick.price
                    stall_warned = False
                elif tick is not None:
                    self.stats.duplicates_skipped += 1

                # Flush policy: time-based and/or batch-size based.
                elapsed_since_flush = (
                    now - self._last_flush_wall if self._last_flush_wall is not None else now - started
                )
                if self._pending and (
                    len(self._pending) >= self.flush_batch_size
                    or elapsed_since_flush >= self.flush_interval_sec
                ):
                    self._flush()

                # Stall watchdog (outside rollover).
                if self._last_tick_wall is not None:
                    idle = now - self._last_tick_wall
                    in_rollover = self.rollover.in_rollover(now)
                    if idle >= self.stall_reconnect_sec and not in_rollover:
                        raise RuntimeError(
                            f"{self.symbol}: no fresh tick for {idle:.0f}s outside rollover "
                            f"(feed lost) — reconnect"
                        )
                    if idle >= self.stall_warn_sec and not in_rollover and not stall_warned:
                        stall_warned = True
                        self.stats.stalls_warned += 1
                        self._log(
                            f"[collector:{self.symbol}] WARN: no fresh tick for {idle:.0f}s "
                            f"(outside rollover window)"
                        )

                await asyncio.sleep(self.poll_interval_sec)
        finally:
            # Never lose collected ticks: flush on every exit path, including
            # the stall/read-error raises that trigger a reconnect.
            self._flush()
        return self.stats

    # ── Flush ─────────────────────────────────────────────────────────

    def _flush(self) -> None:
        if not self._pending:
            return
        before = len(self._pending)
        append_ticks_csv(self.output_path, self._pending)
        self.stats.batches_flushed += 1
        # append_ticks_csv dedupes against the file tail; count what actually
        # landed by diffing against the flushed batch lengths is not exact,
        # so duplicates_skipped stays a best-effort in-memory counter.
        self._pending = []
        self._last_flush_wall = time.time()


def _shutdown_mt5_best_effort() -> None:
    """Shutdown the MT5 module so a fresh client can re-initialize.

    ``Mt5TickClient.__aexit__`` intentionally skips ``mt5.shutdown()`` (it
    keeps a warm local connection for the subprocess lifetime), but a
    reconnect after feed loss needs a clean slate — the MT5 Python package
    allows only one connection per process.
    """
    try:
        import MetaTrader5 as mt5

        mt5.shutdown()
    except Exception:
        pass
    # Clear the symbol resolution cache so symbols are re-resolved on reconnect
    try:
        from synthetic_trader.execution.mt5_data import clear_symbol_resolution_cache
        clear_symbol_resolution_cache()
    except Exception:
        pass


async def _run_session(
    collectors: dict[str, TickCollector],
    *,
    duration_sec: float | None,
    stop_event: asyncio.Event,
) -> None:
    """Run all symbol collectors against ONE shared MT5 client.

    The MT5 Python package supports a single connection per process, so all
    symbols share one ``Mt5TickClient`` and every terminal call is
    serialized through a lock.  Raises the first collector error (feed
    loss) so the caller can reconnect; other collectors are cancelled.
    """
    mt5_lock = asyncio.Lock()
    async with Mt5TickClient() as client:
        tasks = {
            asyncio.create_task(
                collector.run(
                    client,
                    duration_sec=duration_sec,
                    stop_event=stop_event,
                    mt5_lock=mt5_lock,
                )
            ): collector
            for collector in collectors.values()
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc


async def collect_live_ticks(
    symbols: list[str],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    duration_sec: float | None = None,
    status_path: str | Path = STATUS_PATH,
    log: Callable[[str], None] = print,
) -> dict[str, CollectorStats]:
    """Collect live ticks for one or more symbols into ``output_dir``.

    One shared ``Mt5TickClient`` (single connection per process) feeds all
    symbol collectors concurrently with terminal calls serialized through
    a lock.  On feed loss the client is re-established with backoff; an
    initial connect failure fails fast with the terminal's own error.
    Writes a periodic status JSON so the operator dashboard can show
    collection health.  Returns per-symbol stats after ``duration_sec`` or
    when interrupted.
    """
    rollover = RolloverCalendar()
    collectors = {
        symbol: TickCollector(symbol, output_dir, rollover=rollover, log=log)
        for symbol in symbols
    }
    results = {symbol: collectors[symbol].stats for symbol in symbols}
    stop_event = asyncio.Event()
    status_task = asyncio.create_task(
        _status_writer(results, status_path, interval_sec=STATUS_INTERVAL_SEC, log=log)
    )
    reconnect_attempts = 0
    started = time.time()
    try:
        while True:
            if duration_sec is not None and time.time() - started >= duration_sec:
                break
            remaining = (
                duration_sec - (time.time() - started)
                if duration_sec is not None
                else None
            )
            try:
                await _run_session(
                    collectors, duration_sec=remaining, stop_event=stop_event
                )
                break  # completed cleanly (duration reached or interrupted)
            except asyncio.CancelledError:
                raise
            except RuntimeError as exc:
                reconnect_attempts += 1
                _append_mt5_event(_classify_mt5_event(str(exc)), str(exc))
                for collector in collectors.values():
                    collector.stats.reconnect_attempts = reconnect_attempts
                    collector.stats.errors.append(str(exc))
                if reconnect_attempts == 1 and all(
                    c.stats.ticks_collected == 0 for c in collectors.values()
                ):
                    # Initial connect failed (terminal not available) — fail
                    # fast with the terminal's own error instead of spinning
                    # through the whole backoff budget.
                    raise RuntimeError(f"MT5 connection failed: {exc}") from exc
                log(
                    f"[collector] feed lost ({exc}) — "
                    f"reconnect {reconnect_attempts}/{MAX_RECONNECTS}"
                )
                if reconnect_attempts >= MAX_RECONNECTS:
                    raise RuntimeError(
                        f"gave up after {reconnect_attempts} reconnects — "
                        f"check the MT5 terminal is open and logged in"
                    ) from exc
                _shutdown_mt5_best_effort()
                await asyncio.sleep(RECONNECT_BACKOFF_SEC)
    finally:
        stop_event.set()
        status_task.cancel()
        await _write_status(results, status_path)
    return results


async def _status_writer(
    results: dict[str, CollectorStats],
    status_path: str | Path,
    *,
    interval_sec: float,
    log: Callable[[str], None],
) -> None:
    while True:
        await _write_status(results, status_path)
        await asyncio.sleep(interval_sec)


async def _write_status(
    results: dict[str, CollectorStats], status_path: str | Path
) -> None:
    try:
        path = Path(status_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "collectors": {sym: stats.to_dict() for sym, stats in results.items()},
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # pragma: no cover - best effort
        pass


if __name__ == "__main__":  # pragma: no cover - manual smoke entry
    symbols = [s.strip() for s in sys.argv[1].split(",")] if len(sys.argv) > 1 else ["R_75"]
    asyncio.run(collect_live_ticks(symbols))
