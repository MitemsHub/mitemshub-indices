"""Tests for the continuous M1-rate capture loop (data/m1_capture.py)."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from synthetic_trader.data.m1_capture import capture_m1_incremental, run_m1_capture_loop

# 24h in the past, aligned to the 60s grid — safely below the current
# now-bucket so the forming-candle filter keeps every test candle.
_M1_BASE_EPOCH = float((int(time.time()) - 86400) // 60 * 60)


def _candle(epoch: float, o: float, h: float, l: float, c: float) -> dict[str, float]:
    return {"epoch": epoch, "open": o, "high": h, "low": l, "close": c}


def _candles(start_epoch: float, n: int, base: float = 100.0) -> list[dict[str, float]]:
    """n consecutive M1 candles (60s apart) with deterministic OHLC."""
    return [
        _candle(start_epoch + i * 60, base + i, base + i + 2, base + i - 1, base + i + 1)
        for i in range(n)
    ]


def _read_rows(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:  # skip header
        if line.strip():
            rows.append(line.split(","))
    return rows


class CaptureIncrementalTests(unittest.TestCase):
    def test_first_capture_seeds_initial_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=_candles(_M1_BASE_EPOCH, 5),
            ) as fetch:
                stats = capture_m1_incremental("R_75", tmp, initial_days=7.0)

            # No file yet -> since_epoch = now - 7 days (no overlap applied).
            fetch.assert_called_once()
            kwargs = fetch.call_args.kwargs
            expected = time.time() - 7.0 * 86400.0
            self.assertAlmostEqual(kwargs["since_epoch"], expected, delta=5.0)
            self.assertEqual(stats.candles_fetched, 5)
            self.assertEqual(stats.ticks_before, 0)
            self.assertEqual(stats.ticks_after, 20)  # 5 candles x 4 ticks
            self.assertEqual(stats.ticks_added, 20)
            self.assertIsNone(stats.error)

            csv_path = Path(tmp) / "R_75_ticks.csv"
            self.assertTrue(csv_path.exists())
            rows = _read_rows(csv_path)
            self.assertEqual(len(rows), 20)
            # All rows share the corpus symbol and are strictly ascending.
            self.assertTrue(all(row[1] == "R_75" for row in rows))
            epochs = [float(row[0]) for row in rows]
            self.assertEqual(epochs, sorted(epochs))

    def test_second_capture_is_incremental_and_dedupes_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first_candles = _candles(_M1_BASE_EPOCH, 5)  # epochs 1000..1240
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=first_candles,
            ):
                capture_m1_incremental("R_75", tmp)

            # Second sweep refetches the 5 old candles (identical OHLC) plus
            # 2 new ones (1300, 1360).  Overlap must dedupe cleanly.
            second_candles = first_candles + _candles(_M1_BASE_EPOCH + 5 * 60, 2)
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=second_candles,
            ) as fetch:
                stats = capture_m1_incremental("R_75", tmp, overlap_sec=300.0)

            # since_epoch = newest tick epoch (last bucket + 0.76) - overlap.
            self.assertAlmostEqual(
                fetch.call_args.kwargs["since_epoch"],
                _M1_BASE_EPOCH + 4 * 60 + 0.76 - 300.0,
                places=2,
            )
            self.assertEqual(stats.ticks_before, 20)
            self.assertEqual(stats.candles_fetched, 7)
            self.assertEqual(stats.ticks_added, 8)  # only the 2 new candles
            self.assertEqual(stats.ticks_after, 28)
            self.assertEqual(stats.max_gap_sec, 0.0)

            rows = _read_rows(Path(tmp) / "R_75_ticks.csv")
            self.assertEqual(len(rows), 28)
            keys = {(row[0], row[2]) for row in rows}
            self.assertEqual(len(keys), 28)  # zero duplicates

    def test_forming_candle_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = _candles(_M1_BASE_EPOCH, 5)
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=old,
            ):
                capture_m1_incremental("R_75", tmp)

            # Fetch returns a forming candle at the current minute bucket.
            now_bucket = int(time.time()) // 60 * 60
            forming = _candle(now_bucket, 999.0, 1001.0, 998.0, 1000.0)
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=old + [forming],
            ):
                stats = capture_m1_incremental("R_75", tmp)

            self.assertEqual(stats.candles_fetched, 5)  # forming dropped
            rows = _read_rows(Path(tmp) / "R_75_ticks.csv")
            buckets = {int(float(row[0])) for row in rows}
            self.assertNotIn(now_bucket, buckets)

    def test_empty_fetch_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=[],
            ):
                stats = capture_m1_incremental("R_75", tmp)
            self.assertEqual(stats.candles_fetched, 0)
            self.assertEqual(stats.ticks_added, 0)
            self.assertIsNone(stats.error)

    def test_header_only_file_seeds_from_initial_days(self) -> None:
        """A pre-existing header-only (empty) CSV must not crash or stall."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "R_75_ticks.csv"
            csv_path.write_text("epoch,symbol,price,spread,direction,vol_proxy\n", encoding="utf-8")
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=_candles(_M1_BASE_EPOCH, 3),
            ) as fetch:
                stats = capture_m1_incremental("R_75", tmp, initial_days=7.0)
            self.assertAlmostEqual(
                fetch.call_args.kwargs["since_epoch"],
                time.time() - 7.0 * 86400.0,
                delta=5.0,
            )
            self.assertEqual(stats.ticks_before, 0)
            self.assertEqual(stats.ticks_after, 12)
            self.assertIsNone(stats.error)

    def test_cap_warning_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=_candles(_M1_BASE_EPOCH, 5),
            ), mock.patch(
                "synthetic_trader.data.m1_capture.MAX_TICKS_PER_CSV",
                10,  # 20 ticks written >= 10 * 0.8
            ):
                stats = capture_m1_incremental("R_75", tmp)
            self.assertIsNone(stats.error)  # warning must not look like failure
            self.assertIn("near tick-store cap", stats.warning)


class CaptureLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_writes_status_and_compounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                return_value=_candles(_M1_BASE_EPOCH, 5),
            ):
                results = await run_m1_capture_loop(
                    ["R_75", "R_100"],
                    tmp,
                    run_once=True,
                    status_path=status_path,
                )

            self.assertEqual(set(results), {"R_75", "R_100"})
            for symbol, stats in results.items():
                self.assertEqual(stats.ticks_after, 20)
                self.assertIsNone(stats.error)

            self.assertTrue(status_path.exists())
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["symbols"]), {"R_75", "R_100"})

    async def test_run_once_records_fetch_error_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            with mock.patch(
                "synthetic_trader.data.m1_capture.fetch_m1_candles",
                side_effect=RuntimeError("MT5 initialize failed: simulated"),
            ):
                results = await run_m1_capture_loop(
                    ["R_75"], tmp, run_once=True, status_path=status_path,
                )
            self.assertIn("R_75", results)
            self.assertIn("MT5 initialize failed", results["R_75"].error)
            # The status file must land in the temp dir — NEVER the repo's
            # real data/m1_capture.json (a previous version of this test
            # omitted status_path and clobbered the production status file
            # with test junk: a temp output dir + a simulated MT5 error).
            self.assertEqual(status_path.parent, Path(tmp))
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertIn("MT5 initialize failed", payload["symbols"]["R_75"]["error"])


if __name__ == "__main__":
    unittest.main()
