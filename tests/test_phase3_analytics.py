from __future__ import annotations

import unittest

from synthetic_trader.journal.trade_journal import JournalMetrics, summarize_run_diagnostics


class Phase3AnalyticsTests(unittest.TestCase):
    def test_summarize_run_diagnostics_includes_shutdown_and_rejection_counts(self) -> None:
        diagnostics = summarize_run_diagnostics(
            metrics=JournalMetrics(
                trades=4,
                win_rate=0.5,
                profit_factor=1.2,
                expectancy_r=0.1,
                net_pnl=2.0,
            ),
            signals=10,
            rejected_signals=6,
            shutdown_closed_trades=1,
            session_resets=2,
        )

        self.assertEqual(diagnostics["approval_rate"], 0.4)
        self.assertEqual(diagnostics["shutdown_closed_trades"], 1)
        self.assertEqual(diagnostics["session_resets"], 2)


if __name__ == "__main__":
    unittest.main()
