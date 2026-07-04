from __future__ import annotations

import unittest

from synthetic_trader.config import PaperExecutionConfig, TraderConfig


class ExecutionRealismConfigTests(unittest.TestCase):
    def test_paper_execution_config_defaults_to_zero_penalties(self) -> None:
        config = PaperExecutionConfig()

        self.assertEqual(config.entry_slippage_ticks, 0.0)
        self.assertEqual(config.exit_slippage_ticks, 0.0)
        self.assertEqual(config.execution_penalty_per_trade, 0.0)

    def test_default_trader_config_exposes_paper_execution_realism_settings(self) -> None:
        config = TraderConfig.default()

        self.assertIsInstance(config.paper, PaperExecutionConfig)
        self.assertEqual(config.paper.entry_slippage_ticks, 0.0)
        self.assertEqual(config.paper.exit_slippage_ticks, 0.0)
        self.assertEqual(config.paper.execution_penalty_per_trade, 0.0)


if __name__ == "__main__":
    unittest.main()
