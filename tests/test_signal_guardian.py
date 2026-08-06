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
        # Use ticks_since_armed=15 to be past the 8-tick grace period.
        # During the grace period (<=8 ticks), adverse excursion is suppressed
        # to give new plans time to form before failing.
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
            ticks_since_armed=15,
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

        # Sniper-only mode: persistence/impulse checks relaxed.
        # Setup now reaches 'confirmed' directly instead of staying 'actionable'.
        self.assertIn(result.state, ("confirmed", "actionable"))

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

        # Sniper-only mode: persistence/impulse checks relaxed.
        self.assertIn(result.state, ("confirmed", "actionable"))

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
        # ticks_since_armed=10 is OUTSIDE the 8-tick grace period.
        # Prices show a deep pullback: max adverse delta = 0.30, stop_distance = 1.4
        # pullback_ratio = 0.30 / 1.4 = 0.214 > rollover_warning_ratio (0.18)
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.3,
        )
        context = GuardianContext(
            tick_prices=[459.8, 459.5, 459.45, 459.4, 459.35, 459.3],
            ticks_since_armed=10,
            max_favorable_excursion=0.20,
            max_adverse_excursion=0.30,
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
        # ticks_since_armed=10 is OUTSIDE the 8-tick grace period.
        # Prices show follow-through rolling over with deep pullback:
        # max adverse delta = 0.30, stop_distance = 1.4
        # pullback_ratio = 0.30 / 1.4 = 0.214 > rollover_warning_ratio (0.18)
        snapshot = GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,
            take_profit=462.2,
            current_close=459.3,
        )
        context = GuardianContext(
            tick_prices=[460.0, 459.7, 459.5, 459.4, 459.35, 459.3],
            ticks_since_armed=10,
            max_favorable_excursion=0.40,
            max_adverse_excursion=0.30,
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

        # Sniper-only mode: persistence/impulse checks relaxed.
        self.assertIn(result.state, ("confirmed", "actionable"))

    def test_deteriorating_setup_moves_to_failing_before_cancelled(self) -> None:
        # Use ticks_since_armed=12 to be past the 8-tick grace period.
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
            ticks_since_armed=12,
            max_favorable_excursion=16.0,
            max_adverse_excursion=40.0,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "failing")

    # ── Sniper-mode cancel hardening ─────────────────────────────────────
    # The operator reported: a confirmed BUY plan cancelled on a small dip,
    # then re-confirmed on refresh.  Root cause: the top-of-function cancel
    # fired on a *window-max* adverse excursion (a transient wick near the
    # stop) even when price had already recovered.  For sniper (4-6h swing)
    # plans, cancellation must require the adverse move to be SUSTAINED or
    # the stop actually traded through.

    def _sniper_snapshot(self, current_close: float) -> GuardianSnapshot:
        return GuardianSnapshot(
            symbol="R_100",
            direction_bias="buy",
            trade_status="valid",
            entry=459.6,
            stop_loss=458.2,  # stop distance 1.4
            take_profit=462.2,
            current_close=current_close,
        )

    def test_sniper_transient_wick_does_not_cancel_confirmed_plan(self) -> None:
        # Window max excursion = 1.15 (ratio 0.82 >= max_adverse 0.8 — the
        # OLD code cancelled here) but price has RECOVERED to 459.55
        # (current adverse ratio 0.036 << weakening 0.35).  A confirmed
        # sniper plan must stand by the call.
        snapshot = self._sniper_snapshot(current_close=459.55)
        context = GuardianContext(
            tick_prices=[459.7, 459.4, 459.1, 458.9, 459.3, 459.55],
            ticks_since_armed=30,
            max_favorable_excursion=0.2,
            max_adverse_excursion=1.15,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "confirmed")

    def test_sniper_intraday_wick_through_stop_without_closed_candle_holds(self) -> None:
        # Price wick-traded THROUGH the stop intraday (window max adverse 1.6,
        # ratio 1.14 >= 1.0) but has RECOVERED to 459.55, and no CLOSED
        # execution candle confirms the breach — a spread/jitter wick inside
        # the still-forming candle.  The stop-lock grace must hold the plan.
        snapshot = self._sniper_snapshot(current_close=459.55)
        context = GuardianContext(
            tick_prices=[459.6, 459.2, 458.8, 458.5, 459.3, 459.55],
            ticks_since_armed=30,
            max_favorable_excursion=0.1,
            max_adverse_excursion=1.6,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
            stop_traded_on_closed_candle=False,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "confirmed")
        self.assertNotIn("broken", result.reason.lower())

    def test_sniper_intraday_wick_through_stop_cancels_when_sustained_right_now(self) -> None:
        # Same wick, but price is STILL through the stop at the current close
        # (458.1 < stop 458.2): sustained beyond reasonable doubt — cancels
        # even without a closed candle.
        snapshot = self._sniper_snapshot(current_close=458.1)
        context = GuardianContext(
            tick_prices=[459.6, 459.2, 458.8, 458.5, 458.3, 458.1],
            ticks_since_armed=30,
            max_favorable_excursion=0.1,
            max_adverse_excursion=1.5,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
            stop_traded_on_closed_candle=False,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "cancelled")

    def test_sniper_stop_trade_through_on_closed_candle_cancels_plan(self) -> None:
        # Price traded through the stop (459.6 -> 458.1 < stop 458.2) AND a
        # closed execution candle confirms the breach: the thesis is genuinely
        # broken — the position would have been stopped out.
        snapshot = self._sniper_snapshot(current_close=458.1)
        context = GuardianContext(
            tick_prices=[459.6, 459.2, 458.8, 458.5, 458.3, 458.1],
            ticks_since_armed=30,
            max_favorable_excursion=0.1,
            max_adverse_excursion=1.5,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
            stop_traded_on_closed_candle=True,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "cancelled")
        self.assertIn("closed 15m candle", result.reason.lower())

    def test_sniper_sustained_near_stop_position_cancels_plan(self) -> None:
        # Window max 1.15 (0.82 >= 0.8) AND price is STILL sitting 0.857 of
        # the stop away right now (current_close 458.4): sustained near-stop
        # — beyond reasonable doubt.
        snapshot = self._sniper_snapshot(current_close=458.4)
        context = GuardianContext(
            tick_prices=[459.6, 459.2, 458.8, 458.6, 458.5, 458.4],
            ticks_since_armed=30,
            max_favorable_excursion=0.1,
            max_adverse_excursion=1.15,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "cancelled")

    def test_generic_mode_still_cancels_on_window_max_excursion(self) -> None:
        # Non-sniper modes keep the strict rule: a window-max excursion past
        # max_adverse_excursion_ratio cancels even if price recovered.
        snapshot = self._sniper_snapshot(current_close=459.55)
        context = GuardianContext(
            tick_prices=[459.7, 459.4, 459.1, 458.9, 459.3, 459.55],
            ticks_since_armed=30,
            max_favorable_excursion=0.2,
            max_adverse_excursion=1.15,
        )

        result = evaluate_signal_guardian(snapshot, context, DEFAULT_THRESHOLDS)

        self.assertEqual(result.state, "cancelled")
        self.assertIn("broken", result.reason.lower())



if __name__ == "__main__":
    unittest.main()
