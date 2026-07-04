from __future__ import annotations

import unittest

from synthetic_trader.config import LiveMode


class Phase4ExecutionModeTests(unittest.TestCase):
    def test_live_mode_exposes_paper_dry_run_and_armed_values(self) -> None:
        self.assertEqual(LiveMode.PAPER.value, "paper")
        self.assertEqual(LiveMode.DRY_RUN_LIVE.value, "dry-run-live")
        self.assertEqual(LiveMode.ARMED_LIVE.value, "armed-live")


class Phase4ReadinessTests(unittest.TestCase):
    def test_readiness_fails_when_armed_live_has_no_token(self) -> None:
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            mode=LiveMode.ARMED_LIVE,
            symbol="R_75",
            app_id="12345",
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertFalse(report.ready)
        self.assertIn("missing_api_token", report.failures)
        self.assertIn("missing_armed_confirmation", report.failures)

    def test_readiness_passes_for_dry_run_live_with_supported_symbol_and_app_id(self) -> None:
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_75",
            app_id="12345",
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertTrue(report.ready)
        self.assertEqual(report.failures, ())

    def test_readiness_collects_missing_app_id_and_unsupported_symbol_failures(self) -> None:
        from synthetic_trader.live.supervised_live import build_live_readiness_report

        report = build_live_readiness_report(
            mode=LiveMode.DRY_RUN_LIVE,
            symbol="R_50",
            app_id=None,
            token=None,
            armed=False,
            supported_symbols={"R_75", "R_100"},
        )

        self.assertFalse(report.ready)
        self.assertEqual(
            report.failures,
            ("unsupported_symbol", "missing_app_id"),
        )


if __name__ == "__main__":
    unittest.main()
