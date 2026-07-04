from __future__ import annotations

import unittest

from synthetic_trader.config import LiveMode


class Phase4ExecutionModeTests(unittest.TestCase):
    def test_live_mode_exposes_paper_dry_run_and_armed_values(self) -> None:
        self.assertEqual(LiveMode.PAPER.value, "paper")
        self.assertEqual(LiveMode.DRY_RUN_LIVE.value, "dry-run-live")
        self.assertEqual(LiveMode.ARMED_LIVE.value, "armed-live")


if __name__ == "__main__":
    unittest.main()
