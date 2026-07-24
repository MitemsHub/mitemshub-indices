from __future__ import annotations

import unittest

from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)

DEFAULT_THRESHOLDS = GuardianThresholds(
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


class SignalGuardianTests(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = DEFAULT_THRESHOLDS

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

    def test_buy_setup_becomes_cancelled_after_large_adverse_excursion(self) -> None:
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

        self.assertEqual(result.state, "cancelled")
        self.assertIn("broken", result.reason.lower())

    def test_buy_setup_becomes_failing_before_full_cancellation(self) -> None:
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

        self.assertEqual(result.state, "failing")
        self.assertIn("deterior", result.reason.lower())

    def test_buy_setup_becomes_actionable_when_persistence_is_too_weak(self) -> None:
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

        self.assertEqual(result.state, "actionable")
        self.assertIn("persistence", result.reason.lower())

    def test_buy_setup_becomes_actionable_when_single_impulse_lacks_persistence(self) -> None:
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

        self.assertEqual(result.state, "actionable")
        self.assertIn("persistence", result.reason.lower())

    def test_buy_setup_becomes_actionable_when_entry_drift_gets_too_large(self) -> None:
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

        self.assertEqual(result.state, "actionable")
        self.assertIn("drift", result.reason.lower())

    def test_buy_setup_fails_when_pullback_depth_breaks_rollover_warning(self) -> None:
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

        self.assertEqual(result.state, "failing")
        self.assertIn("deterior", result.reason.lower())

    def test_confirmed_buy_setup_becomes_cancelled_when_reversal_clusters_break_reclaimed_territory(
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

        self.assertEqual(result.state, "cancelled")
        self.assertIn("broken", result.reason.lower())

    def test_confirmed_buy_setup_downgrades_to_failing_when_follow_through_rolls_over(self) -> None:
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

        self.assertEqual(result.state, "failing")
        self.assertIn("deterior", result.reason.lower())

    def test_armed_setup_becomes_actionable_when_confirmation_window_expires(self) -> None:
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
            tick_prices=[459.4, 459.46, 459.52, 459.58, 459.64, 459.7],
            ticks_since_armed=14,
            max_favorable_excursion=0.14,
            max_adverse_excursion=0.09,
        )

        result = evaluate_signal_guardian(snapshot, context, self.thresholds)

        self.assertEqual(result.state, "actionable")
        self.assertIn("stale", result.reason.lower())

    def test_usable_setup_becomes_actionable_before_full_confirmation(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_75",
            direction_bias="sell",
            trade_status="valid",
            entry=53074.2,
            stop_loss=53173.2,
            take_profit=52886.2,
            current_close=53070.0,
        )
        context = GuardianContext(
            tick_prices=[53090.0, 53084.0, 53080.0, 53076.0, 53072.0, 53070.0],
            ticks_since_armed=2,
            max_favorable_excursion=24.0,
            max_adverse_excursion=8.0,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "actionable")
        self.assertTrue(
            "usable" in result.reason.lower() or "actionable" in result.reason.lower()
        )

    def test_structure_led_buy_plan_stays_actionable_during_orderly_early_post_entry_move(
        self,
    ) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_75",
            direction_bias="buy",
            trade_status="valid",
            entry=100.0,
            stop_loss=98.0,
            take_profit=106.0,
            current_close=100.26,
        )
        context = GuardianContext(
            tick_prices=[100.0, 100.12, 100.22, 100.19, 100.23, 100.26],
            ticks_since_armed=6,
            max_favorable_excursion=0.31,
            max_adverse_excursion=0.03,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "actionable")
        self.assertIn("actionable", result.reason.lower())

    def test_deteriorating_setup_moves_to_failing_before_cancelled(self) -> None:
        snapshot = GuardianSnapshot(
            symbol="R_75",
            direction_bias="sell",
            trade_status="valid",
            entry=53074.2,
            stop_loss=53173.2,
            take_profit=52886.2,
            current_close=53110.0,
        )
        context = GuardianContext(
            tick_prices=[53072.0, 53076.0, 53085.0, 53094.0, 53103.0, 53110.0],
            ticks_since_armed=4,
            max_favorable_excursion=16.0,
            max_adverse_excursion=40.0,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "failing")


if __name__ == "__main__":
    unittest.main()
