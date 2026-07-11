from __future__ import annotations

import unittest

from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)


class SignalGuardianTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = GuardianThresholds(
            max_arming_ticks=12,
            max_confirmation_window_ticks=6,
            weakening_excursion_ratio=0.35,
            max_adverse_excursion_ratio=0.8,
            max_entry_drift_ratio=0.75,
            microstructure_window_ticks=6,
            min_persistence_ticks=4,
            min_impulse_ratio=0.12,
            max_pullback_ratio=0.22,
            rollover_warning_ratio=0.18,
            rollover_invalidation_ratio=0.3,
            adverse_cluster_window_ticks=4,
            max_adverse_cluster_count=2,
        )

    def test_buy_setup_becomes_confirmed_when_zone_holds_and_microstructure_improves(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.7,
        )
        context = GuardianContext(
            tick_prices=[459.4, 459.5, 459.55, 459.62, 459.7, 459.78],
            ticks_since_armed=4,
            max_favorable_excursion=0.18,
            max_adverse_excursion=0.12,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "confirmed")
        self.assertIn("confirmation", result.reason.lower())

    def test_buy_setup_becomes_invalidated_after_large_adverse_excursion(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=458.35,
        )
        context = GuardianContext(
            tick_prices=[459.55, 459.4, 459.1, 458.8, 458.55, 458.35],
            ticks_since_armed=5,
            max_favorable_excursion=0.02,
            max_adverse_excursion=1.25,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "invalidated")
        self.assertIn("invalidat", result.reason.lower())

    def test_buy_setup_becomes_weakening_before_full_invalidation(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.1,
        )
        context = GuardianContext(
            tick_prices=[459.62, 459.58, 459.45, 459.32, 459.2, 459.1],
            ticks_since_armed=5,
            max_favorable_excursion=0.05,
            max_adverse_excursion=0.5,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "weakening")
        self.assertIn("weak", result.reason.lower())

    def test_buy_setup_stays_armed_when_persistence_is_too_weak(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.67,
        )
        context = GuardianContext(
            tick_prices=[459.58, 459.61, 459.59, 459.64, 459.62, 459.67],
            ticks_since_armed=4,
            max_favorable_excursion=0.09,
            max_adverse_excursion=0.05,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "armed")
        self.assertIn("persistence", result.reason.lower())

    def test_buy_setup_stays_armed_when_single_impulse_is_not_supported_by_persistence(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.74,
        )
        context = GuardianContext(
            tick_prices=[459.56, 459.58, 459.57, 459.59, 459.6, 459.74],
            ticks_since_armed=4,
            max_favorable_excursion=0.14,
            max_adverse_excursion=0.04,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "armed")
        self.assertIn("persistence", result.reason.lower())

    def test_buy_setup_stays_armed_when_entry_drift_gets_too_large(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=460.9,
        )
        context = GuardianContext(
            tick_prices=[460.1, 460.2, 460.35, 460.48, 460.72, 460.9],
            ticks_since_armed=5,
            max_favorable_excursion=1.3,
            max_adverse_excursion=0.0,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "armed")
        self.assertIn("drift", result.reason.lower())

    def test_buy_setup_weakens_when_pullback_depth_breaks_rollover_warning(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.44,
        )
        context = GuardianContext(
            tick_prices=[459.92, 459.86, 459.75, 459.62, 459.53, 459.44],
            ticks_since_armed=5,
            max_favorable_excursion=0.32,
            max_adverse_excursion=0.16,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "weakening")
        self.assertIn("reversal", result.reason.lower())

    def test_confirmed_buy_setup_becomes_invalidated_when_reversal_clusters_break_reclaimed_territory(
        self,
    ) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.5,
        )
        context = GuardianContext(
            tick_prices=[459.82, 459.7, 459.76, 459.6, 459.66, 459.5],
            ticks_since_armed=5,
            max_favorable_excursion=0.24,
            max_adverse_excursion=0.1,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "invalidated")
        self.assertIn("invalidated", result.reason.lower())

    def test_confirmed_buy_setup_downgrades_when_follow_through_rolls_over(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.52,
        )
        context = GuardianContext(
            tick_prices=[459.8, 459.76, 459.7, 459.64, 459.58, 459.52],
            ticks_since_armed=5,
            max_favorable_excursion=0.24,
            max_adverse_excursion=0.2,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "weakening")
        self.assertIn("weak", result.reason.lower())

    def test_armed_setup_goes_stale_when_confirmation_window_expires(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.62,
        )
        context = GuardianContext(
            tick_prices=[459.55, 459.58, 459.61, 459.6, 459.59, 459.6],
            ticks_since_armed=14,
            max_favorable_excursion=0.04,
            max_adverse_excursion=0.09,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "invalidated")
        self.assertIn("stale", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
