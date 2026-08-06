"""Tests for the continuous live tick collection service."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from synthetic_trader.data.continuous_collector import (
    MAX_CONSECUTIVE_ERRORS,
    RolloverCalendar,
    TickCollector,
    collect_live_ticks,
)
from synthetic_trader.data.tick_store import inspect_ticks
from synthetic_trader.domain import Tick


class RolloverCalendarTests(unittest.TestCase):
    def _epoch_utc(self, hour: int, minute: int = 0, second: int = 0) -> float:
        return datetime(2026, 8, 3, hour, minute, second, tzinfo=timezone.utc).timestamp()

    def test_inside_rollover_window(self) -> None:
        cal = RolloverCalendar(rollover_hour_utc=0, grace_sec=120.0)
        # 00:00:00 and 00:01:30 are inside the ±2min window.
        self.assertTrue(cal.in_rollover(self._epoch_utc(0, 0, 0)))
        self.assertTrue(cal.in_rollover(self._epoch_utc(0, 1, 30)))

    def test_just_outside_rollover_window(self) -> None:
        cal = RolloverCalendar(rollover_hour_utc=0, grace_sec=120.0)
        self.assertFalse(cal.in_rollover(self._epoch_utc(0, 3, 0)))
        self.assertFalse(cal.in_rollover(self._epoch_utc(12, 0, 0)))

    def test_window_wraps_across_midnight(self) -> None:
        cal = RolloverCalendar(rollover_hour_utc=0, grace_sec=120.0)
        # 23:59:00 is 60s before midnight → inside the window (wraps).
        self.assertTrue(cal.in_rollover(self._epoch_utc(23, 59, 0)))
        # 23:55 is 5 min before → outside.
        self.assertFalse(cal.in_rollover(self._epoch_utc(23, 55, 0)))

    def test_custom_rollover_hour(self) -> None:
        cal = RolloverCalendar(rollover_hour_utc=2, grace_sec=60.0)
        self.assertTrue(cal.in_rollover(self._epoch_utc(2, 0, 30)))
        self.assertFalse(cal.in_rollover(self._epoch_utc(0, 0, 0)))


class FakeClient:
    """Async MT5 client double that yields a scripted tick stream."""

    def __init__(self, ticks: list[Tick] | None = None, errors_before_ticks: int = 0) -> None:
        self._queue = list(ticks or [])
        self._errors_before_ticks = errors_before_ticks
        self.read_calls = 0

    def mt5_symbol(self, symbol: str) -> str:
        return f"SYN{symbol.split('_')[1]}"

    async def latest_tick(self, symbol: str) -> Tick | None:
        self.read_calls += 1
        if self.read_calls <= self._errors_before_ticks:
            raise ConnectionError("simulated terminal error")
        return self._queue.pop(0) if self._queue else None


class TickCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def _drain_then_stop(self, client: FakeClient, stop: asyncio.Event) -> None:
        """Wait until the fake client's queue is exhausted, then signal stop.

        Deterministic under Windows' coarse timer granularity (where
        ``asyncio.sleep`` of small values can sleep ~15ms) — we stop based on
        queue exhaustion, not wall-clock time.
        """
        while client._queue:
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.02)  # let the collector observe the drained state
        stop.set()

    async def test_collects_and_dedupes_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            client = FakeClient(
                ticks=[
                    Tick(symbol="R_75", epoch=1000.0, price=1500.0),
                    Tick(symbol="R_75", epoch=1000.5, price=1500.5),
                    Tick(symbol="R_75", epoch=1001.0, price=1501.0),
                    Tick(symbol="R_75", epoch=1001.0, price=1501.0),  # dup epoch
                ]
            )
            collector = TickCollector(
                "R_75",
                output,
                poll_interval_sec=0.001,
                flush_interval_sec=0.0,
                flush_batch_size=10,
            )
            stop = asyncio.Event()
            await asyncio.gather(
                collector.run(client, stop_event=stop),
                self._drain_then_stop(client, stop),
            )

            self.assertEqual(collector.stats.ticks_collected, 3)
            self.assertGreaterEqual(collector.stats.duplicates_skipped, 0)
            csv_path = output / "R_75_ticks.csv"
            self.assertTrue(csv_path.exists())
            ticks = inspect_ticks(
                [Tick(symbol="R_75", epoch=float(p[0]), price=float(p[2])) for p in self._read_csv(csv_path)],
                symbol="R_75",
            )
            self.assertEqual(ticks.ticks, 3)

    async def test_stall_raises_outside_rollover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(ticks=[Tick(symbol="R_75", epoch=1000.0, price=1500.0)])
            collector = TickCollector(
                "R_75",
                Path(tmp),
                poll_interval_sec=0.001,
                flush_interval_sec=0.0,
                stall_warn_sec=0.01,
                stall_reconnect_sec=0.02,
            )
            with self.assertRaisesRegex(RuntimeError, "no fresh tick"):
                await collector.run(client)

    async def test_rollover_suppresses_reconnect(self) -> None:
        """A stall inside the rollover window must NOT raise."""
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(ticks=[Tick(symbol="R_75", epoch=1000.0, price=1500.0)])
            rollover = RolloverCalendar(rollover_hour_utc=0, grace_sec=86400.0)  # whole day = rollover
            collector = TickCollector(
                "R_75",
                Path(tmp),
                poll_interval_sec=0.001,
                flush_interval_sec=0.0,
                stall_warn_sec=0.005,
                stall_reconnect_sec=0.01,
                rollover=rollover,
            )
            stop = asyncio.Event()
            await asyncio.gather(
                collector.run(client, stop_event=stop),
                self._drain_then_stop(client, stop),
            )
            self.assertEqual(collector.stats.ticks_collected, 1)
            self.assertEqual(collector.stats.stalls_warned, 0)

    async def test_repeated_read_errors_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(
                ticks=[Tick(symbol="R_75", epoch=1000.0, price=1500.0)],
                errors_before_ticks=MAX_CONSECUTIVE_ERRORS + 1,
            )
            collector = TickCollector("R_75", Path(tmp), poll_interval_sec=0.001, flush_interval_sec=0.0)
            with self.assertRaisesRegex(RuntimeError, "consecutive read errors"):
                await collector.run(client)

    async def test_flush_batch_size_triggers_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            client = FakeClient(
                ticks=[
                    Tick(symbol="R_75", epoch=float(2000 + i), price=1500.0 + i * 0.1)
                    for i in range(15)
                ]
            )
            collector = TickCollector(
                "R_75",
                output,
                poll_interval_sec=0.001,
                flush_interval_sec=9999.0,  # no time-based flush
                flush_batch_size=5,
            )
            stop = asyncio.Event()
            await asyncio.gather(
                collector.run(client, stop_event=stop),
                self._drain_then_stop(client, stop),
            )

            csv_path = output / "R_75_ticks.csv"
            self.assertTrue(csv_path.exists())
            rows = self._read_csv(csv_path)
            self.assertEqual(len(rows), 15)
            self.assertGreaterEqual(collector.stats.batches_flushed, 3)

    def _read_csv(self, path: Path) -> list[list[str]]:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:  # skip header
            if line.strip():
                rows.append(line.split(","))
        return rows


if __name__ == "__main__":
    unittest.main()
