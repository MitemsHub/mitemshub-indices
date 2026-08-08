"""Regression tests for the MT5 IPC-timeout hardening in Mt5TickClient.

The recurring failure: mt5.initialize() can return (-10005, 'IPC timeout')
when the terminal is busy or a previous subprocess left a half-open IPC
channel.  The old code did one portable(False→True) pass with no retry and
no shutdown between attempts, so a single timeout surfaced as "Bridge
Offline" — and the zombie initialize thread kept the channel wedged for the
next subprocess.

The hardening: retry the whole pass up to _INIT_FULL_RETRY_COUNT times,
calling mt5.shutdown() (best-effort) between passes so the half-open state
is cleared.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from synthetic_trader.execution.mt5_data import Mt5TickClient


def _fake_mt5(init_results: list, *, terminal_info=None):
    """Fake MetaTrader5 module whose initialize() returns the given results
    in order (last value repeats)."""
    fake = types.ModuleType("MetaTrader5")
    fake.initialize = MagicMock(side_effect=list(init_results))
    fake.shutdown = MagicMock(return_value=True)
    fake.login = MagicMock(return_value=True)
    fake.last_error = MagicMock(return_value=(-10005, "IPC timeout"))
    fake.terminal_info = MagicMock(return_value=terminal_info)
    return fake


class Mt5ClientHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="mt5-harden-")
        self._env = patch.dict(
            os.environ,
            {
                "SYNTHETIC_MT5_SERVER": "BlueberryMarketsSVG-Live",
                "SYNTHETIC_MT5_LOGIN": "12345",
                "SYNTHETIC_MT5_PASSWORD": "secret",
                "SYNTHETIC_MT5_TERMINAL_PATH": str(Path(self._tmp) / "terminal64.exe"),
            },
            clear=False,
        )
        self._env.start()
        self._modules = patch.dict(sys.modules, {})
        self._modules.start()

    def tearDown(self) -> None:
        self._modules.stop()
        self._env.stop()

    def test_single_ipc_timeout_recovers_on_retry(self) -> None:
        """An IPC timeout on the whole first pass (portable=False AND
        portable=True both fail) must not fail the connect — the retry pass
        re-initializes successfully, with a shutdown between passes."""
        # Pass 0: portable=False fails, portable=True fails.  Pass 1:
        # portable=False succeeds (the terminal recovered).
        fake = _fake_mt5([False, False, True])
        with patch.dict(sys.modules, {"MetaTrader5": fake}):
            client = Mt5TickClient()

            async def _connect():
                await client.__aenter__()
                return client

            connected = asyncio.run(_connect())

        self.assertIsNotNone(connected)
        # Two full passes attempted (2 + 1 initialize calls).
        self.assertGreaterEqual(fake.initialize.call_count, 3)
        # shutdown must have been called between passes (clears the
        # half-open IPC channel left by the timed-out pass 0).
        self.assertGreaterEqual(fake.shutdown.call_count, 1)

    def test_all_timeouts_raise_with_retries_attempted(self) -> None:
        """If every initialize attempt times out, connect must raise — but
        only after exhausting the retry budget, and shutdown is called each
        pass to release the channel."""
        fake = _fake_mt5([False, False, False, False, False, False])
        with patch.dict(sys.modules, {"MetaTrader5": fake}):
            client = Mt5TickClient()

            async def _connect():
                await client.__aenter__()

            with self.assertRaises(RuntimeError):
                asyncio.run(_connect())

        # portable(False→True) × _INIT_FULL_RETRY_COUNT passes.
        self.assertEqual(fake.initialize.call_count, 6)
        # shutdown called before each retry pass (passes 2 and 3) — and
        # best-effort, so at least once.
        self.assertGreaterEqual(fake.shutdown.call_count, 1)

    def test_success_path_calls_shutdown_zero_or_more_but_connects(self) -> None:
        """A clean first-attempt connect still works (shutdown not required)."""
        fake = _fake_mt5([True])
        with patch.dict(sys.modules, {"MetaTrader5": fake}):
            client = Mt5TickClient()

            async def _connect():
                await client.__aenter__()
                return client

            connected = asyncio.run(_connect())

        self.assertIsNotNone(connected)
        self.assertEqual(fake.initialize.call_count, 1)


if __name__ == "__main__":
    unittest.main()
