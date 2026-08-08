"""Tests for the zero-drawdown band geometry and its guardian trail."""

from __future__ import annotations

import unittest

from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)
from synthetic_trader.strategy.band_geometry import (
    BandGeometryConfig,
    band_levels,
    horizon_sigma,
)


class BandLevelsTests(unittest.TestCase):
    def test_buy_levels_are_reachable_and_zd(self) -> None:
        # R_75 ~1770 with a 0.17% per-5m sigma over a 2h hold.
        levels = band_levels(
            entry=1770.0,
            direction="buy",
            sigma_per_bar=0.0017,
            bar_sec=300,
            hold_horizon_sec=7200,
        )
        self.assertIsNotNone(levels)
        assert levels is not None
        # Tight invalidation: stop is a fraction of a percent, NOT the old
        # sniper's 6% stop.
        self.assertLess((1770.0 - levels.stop_loss) / 1770.0, 0.01)
        # Target inside the calibrated band (2h p75 range ~1.9%) — reachable.
        self.assertLess((levels.take_profit - 1770.0) / 1770.0, 0.02)
        # Zero-drawdown reward:risk.
        self.assertGreaterEqual(levels.reward_risk, 2.0)
        self.assertEqual(levels.hold_horizon_sec, 7200)

    def test_sell_mirrors_buy(self) -> None:
        buy = band_levels(entry=100.0, direction="buy", sigma_per_bar=0.002, bar_sec=300)
        sell = band_levels(entry=100.0, direction="sell", sigma_per_bar=0.002, bar_sec=300)
        assert buy is not None and sell is not None
        self.assertAlmostEqual(100.0 - buy.stop_loss, sell.stop_loss - 100.0)
        self.assertAlmostEqual(sell.take_profit - 100.0, 100.0 - buy.take_profit)

    def test_rejects_degenerate_inputs(self) -> None:
        self.assertIsNone(band_levels(entry=0.0, direction="buy", sigma_per_bar=0.002, bar_sec=300))
        self.assertIsNone(band_levels(entry=100.0, direction="buy", sigma_per_bar=0.0, bar_sec=300))
        self.assertIsNone(band_levels(entry=100.0, direction="sideways", sigma_per_bar=0.002, bar_sec=300))
        self.assertIsNone(
            band_levels(
                entry=100.0,
                direction="buy",
                sigma_per_bar=0.002,
                bar_sec=300,
                config=BandGeometryConfig(stop_sigma_mult=0.8, target_sigma_mult=0.9),  # RR < 2
            )
        )

    def test_stop_cap_rejects_absurd_sigma(self) -> None:
        self.assertIsNone(
            band_levels(
                entry=100.0,
                direction="buy",
                sigma_per_bar=0.20,  # 20% per bar → stop would blow the 1.5% cap
                bar_sec=300,
                hold_horizon_sec=3600,
            )
        )

    def test_horizon_sigma_scales_with_sqrt_bars(self) -> None:
        self.assertAlmostEqual(horizon_sigma(0.01, 300, 1200), 0.02, places=6)  # 4 bars → 2x


class GuardianBreakevenTrailTests(unittest.TestCase):
    THRESHOLDS = GuardianThresholds(
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
        breakeven_trail_frac=0.3,
    )

    def _snapshot(self, *, entry=100.0, stop=99.7, target=101.5, current_close=100.3):
        # RR ~ (1.5 / 0.3) = 5; trail arms at 0.3 * 1.5 = 0.45 of favorable move.
        return GuardianSnapshot(
            symbol="R_75",
            direction_bias="buy",
            trade_status="valid",
            entry=entry,
            stop_loss=stop,
            take_profit=target,
            current_close=current_close,
        )

    def test_trail_armed_plan_cancels_when_entry_traded_through_on_closed_candle(self) -> None:
        # MFE 0.6 >= 0.3 * (101.5-100) → trail armed; price back at entry,
        # confirmed by a closed execution candle → cancel at breakeven.
        snapshot = self._snapshot(current_close=100.0)
        context = GuardianContext(
            tick_prices=[100.0, 100.4, 100.6, 100.3, 100.1, 100.0],
            ticks_since_armed=30,
            max_favorable_excursion=0.6,
            max_adverse_excursion=0.1,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
            stop_traded_on_closed_candle=False,
            entry_traded_on_closed_candle=True,
        )
        result = evaluate_signal_guardian(snapshot, context, self.THRESHOLDS)
        self.assertEqual(result.state, "cancelled")
        self.assertIn("breakeven", result.reason.lower())

    def test_trail_not_armed_keeps_original_stop_semantics(self) -> None:
        # MFE 0.2 < 0.45 → trail NOT armed; small adverse move is noise → confirmed.
        snapshot = self._snapshot(current_close=100.15)
        context = GuardianContext(
            tick_prices=[100.0, 100.1, 100.15],
            ticks_since_armed=5,
            max_favorable_excursion=0.2,
            max_adverse_excursion=0.1,
            trading_mode="sniper",
            stop_traded_on_closed_candle=False,
        )
        result = evaluate_signal_guardian(snapshot, context, self.THRESHOLDS)
        self.assertNotEqual(result.state, "cancelled")

    def test_trail_armed_but_price_above_entry_holds(self) -> None:
        # Trail armed, but price still above entry → plan holds.
        snapshot = self._snapshot(current_close=100.5)
        context = GuardianContext(
            tick_prices=[100.0, 100.4, 100.6, 100.5],
            ticks_since_armed=30,
            max_favorable_excursion=0.6,
            max_adverse_excursion=0.05,
            previous_guardian_state="confirmed",
            first_confirmed_at_tick=1,
            trading_mode="sniper",
            stop_traded_on_closed_candle=False,
            entry_traded_on_closed_candle=False,
        )
        result = evaluate_signal_guardian(snapshot, context, self.THRESHOLDS)
        self.assertNotEqual(result.state, "cancelled")


if __name__ == "__main__":
    unittest.main()
