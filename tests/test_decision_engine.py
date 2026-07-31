from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle, Direction, FeatureSnapshot, Regime
from synthetic_trader.strategy.confirmation_builder import confirm_setup
from synthetic_trader.strategy.decision_engine import DecisionEngine, CalibrationState, MAX_CALIBRATION_SAMPLES
from synthetic_trader.strategy.intraday_execution_builder import IntradayExecutionPlan
from synthetic_trader.strategy.setup_builder import classify_setup
from synthetic_trader.strategy.top_down_bias import infer_top_down_bias


def trending_candles(symbol: str = "R_75", count: int = 100) -> list[Candle]:
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = open_price + 0.35
        candles.append(
            Candle(
                symbol=symbol,
                timeframe_sec=60,
                open_time=index * 60,
                open=open_price,
                high=close + 0.12,
                low=open_price - 0.08,
                close=close,
                tick_count=5,
            )
        )
        price = close
    return candles


def borderline_trending_candles(symbol: str = "R_75", count: int = 100) -> list[Candle]:
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = open_price + 0.05
        candles.append(
            Candle(
                symbol=symbol,
                timeframe_sec=60,
                open_time=index * 60,
                open=open_price,
                high=close + 0.05,
                low=open_price - 0.05,
                close=close,
                tick_count=5,
            )
        )
        price = close
    return candles


def intraday_execution_plan(
    *,
    entry: float = 103.4,
    execution_stop: float = 102.6,
    thesis_invalidation: float = 101.0,
    primary_target: float = 104.8,
    extended_target: float | None = None,
    hold_horizon_minutes: int = 60,
    trigger_type: str | None = None,
) -> IntradayExecutionPlan:
    return IntradayExecutionPlan(
        entry=entry,
        execution_stop=execution_stop,
        thesis_invalidation=thesis_invalidation,
        primary_target=primary_target,
        extended_target=extended_target,
        hold_horizon_minutes=hold_horizon_minutes,
        trigger_type=trigger_type,
    )


class CalibrationStatePruningTests(unittest.TestCase):
    """Tests for calibration buffer pruning (max 500 samples)."""

    def test_add_keeps_buffer_within_limit(self) -> None:
        cal = CalibrationState()
        for i in range(600):
            cal.add(0.5 + (i % 10) * 0.01, i % 2)
        self.assertLessEqual(len(cal.predictions), MAX_CALIBRATION_SAMPLES)
        self.assertLessEqual(len(cal.outcomes), MAX_CALIBRATION_SAMPLES)
        self.assertEqual(len(cal.predictions), len(cal.outcomes))

    def test_pruning_keeps_most_recent_entries(self) -> None:
        cal = CalibrationState()
        for i in range(600):
            cal.add(float(i), i % 2)
        # After 600 adds with limit 500, oldest 100 should be dropped
        self.assertEqual(len(cal.predictions), 500)
        # The first remaining prediction should be index 100
        self.assertEqual(cal.predictions[0], 100.0)
        self.assertEqual(cal.predictions[-1], 599.0)
        self.assertEqual(cal.outcomes[0], 100 % 2)

    def test_pruning_preserves_calibration_integrity(self) -> None:
        cal = CalibrationState()
        for i in range(550):
            cal.add(0.7 if i % 2 == 0 else 0.3, i % 2)
        self.assertEqual(len(cal.predictions), MAX_CALIBRATION_SAMPLES)
        self.assertEqual(len(cal.outcomes), MAX_CALIBRATION_SAMPLES)
        # Brier score should still be computable
        brier = cal.brier_score()
        self.assertIsNotNone(brier)
        self.assertGreaterEqual(brier, 0.0)

    def test_no_pruning_when_under_limit(self) -> None:
        cal = CalibrationState()
        for i in range(100):
            cal.add(float(i), i % 2)
        self.assertEqual(len(cal.predictions), 100)
        self.assertEqual(len(cal.outcomes), 100)

    def test_exactly_at_limit_no_pruning(self) -> None:
        cal = CalibrationState()
        for i in range(MAX_CALIBRATION_SAMPLES):
            cal.add(float(i), i % 2)
        self.assertEqual(len(cal.predictions), MAX_CALIBRATION_SAMPLES)
        self.assertEqual(cal.predictions[0], 0.0)

    def test_one_over_limit_triggers_pruning(self) -> None:
        cal = CalibrationState()
        for i in range(MAX_CALIBRATION_SAMPLES + 1):
            cal.add(float(i), i % 2)
        self.assertEqual(len(cal.predictions), MAX_CALIBRATION_SAMPLES)
        self.assertEqual(cal.predictions[0], 1.0)  # 0 was dropped

    def test_large_buffer_prunes_correctly(self) -> None:
        cal = CalibrationState()
        for i in range(2000):
            cal.add(float(i), i % 2)
        self.assertEqual(len(cal.predictions), MAX_CALIBRATION_SAMPLES)
        self.assertEqual(len(cal.outcomes), MAX_CALIBRATION_SAMPLES)
        # Should contain the last 500 entries
        self.assertEqual(cal.predictions[0], 1500.0)
        self.assertEqual(cal.predictions[-1], 1999.0)


class DecisionEngineTests(unittest.TestCase):
    def test_waits_for_enough_history(self) -> None:
        engine = DecisionEngine(TraderConfig.default())
        report = engine.evaluate("R_75", trending_candles(count=10))
        self.assertIsNone(report.signal)

    def test_creates_directional_signal(self) -> None:
        engine = DecisionEngine(TraderConfig.default())
        with patch(
            "synthetic_trader.strategy.decision_engine.build_intraday_execution",
            return_value=intraday_execution_plan(
                entry=134.0,
                execution_stop=133.0,
                thesis_invalidation=130.5,
                primary_target=135.5,
            ),
        ):
            report = engine.evaluate("R_75", trending_candles())

        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertEqual(report.signal.direction, Direction.LONG)
        self.assertGreaterEqual(report.signal.reward_risk, 1.35)

    def test_uses_symbol_specific_confidence_floor_for_borderline_synthetic_trend(self) -> None:
        engine = DecisionEngine(TraderConfig.default())

        for symbol in ("R_75", "R_100"):
            with self.subTest(symbol=symbol):
                with patch(
                    "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                    return_value=intraday_execution_plan(),
                ):
                    report = engine.evaluate(symbol, borderline_trending_candles(symbol=symbol))

                self.assertIsNotNone(report.signal)
                assert report.signal is not None
                self.assertGreaterEqual(report.signal.confidence, 0.5)
                self.assertEqual(report.signal.direction, Direction.LONG)

    def test_builds_structure_led_trade_plan_from_top_down_components(self) -> None:
        config = TraderConfig.default()
        engine = DecisionEngine(config)
        candles = trending_candles(symbol="R_75", count=120)
        higher_timeframe_candles = trending_candles(symbol="R_75", count=100)

        bias = infer_top_down_bias(
            symbol="R_75",
            bias_candles=higher_timeframe_candles,
            setup_candles=candles,
        )
        setup = classify_setup(
            bias=bias,
            setup_candles=candles,
        )
        confirmation = confirm_setup(
            setup=setup,
            confirmation_candles=candles[-30:],
        )
        execution_plan = intraday_execution_plan(
            entry=setup.trigger_zone_high if setup.trigger_zone_high is not None else candles[-1].close,
            execution_stop=102.0,
            thesis_invalidation=bias.invalidation_price if bias.invalidation_price is not None else 101.0,
            primary_target=105.0,
        )

        with patch(
            "synthetic_trader.strategy.decision_engine.build_intraday_execution",
            return_value=execution_plan,
        ):
            report = engine.evaluate(
                "R_75",
                candles=candles,
                higher_timeframe_candles=higher_timeframe_candles,
                role_candles={
                    "bias": higher_timeframe_candles,
                    "setup": candles,
                    "confirmation": candles,
                    "execution": candles,
                },
            )

        self.assertEqual(confirmation.state, "confirmed")
        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertEqual(report.signal.direction, Direction.LONG)
        self.assertEqual(report.signal.entry, execution_plan.entry)
        self.assertEqual(report.signal.stop_loss, execution_plan.execution_stop)
        self.assertEqual(report.signal.take_profit, execution_plan.primary_target)
        self.assertEqual(report.signal.thesis_invalidation, execution_plan.thesis_invalidation)
        # Rationale may include weak-signal explanation prepended before the
        # bias/setup/confirmation reasons when confidence is below the strong threshold.
        self.assertIn(bias.reason, report.reasons)
        self.assertIn(setup.reason, report.reasons)
        self.assertIn(confirmation.reason, report.reasons)

    def test_evaluate_prefers_named_role_candle_inputs_over_legacy_reuse(self) -> None:
        config = TraderConfig.default()
        engine = DecisionEngine(config)
        profile = config.symbols["R_75"]
        bias_candles = trending_candles(symbol="R_75", count=150)
        setup_candles = trending_candles(symbol="R_75", count=100)
        confirmation_candles = trending_candles(symbol="R_75", count=60)
        execution_candles = trending_candles(symbol="R_75", count=120)
        feature_snapshot = FeatureSnapshot(
            symbol="R_75",
            epoch=execution_candles[-1].open_time,
            timeframe_sec=profile.execution_timeframe_sec,
            features={"atr_14": 1.0, "structure_bias": 1.0, "body": 1.0},
            regime=Regime.TREND_UP,
            structure={"bos_up": 1.0},
            notes=("execution snapshot",),
        )
        bias = SimpleNamespace(
            direction="bullish",
            reason="4H structure is bullish",
            invalidation_price=101.0,
        )
        setup = SimpleNamespace(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=102.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        )
        confirmation = SimpleNamespace(
            state="confirmed",
            reason="15m confirmation aligns with the setup",
        )
        execution_plan = intraday_execution_plan(
            entry=103.4,
            execution_stop=102.6,
            thesis_invalidation=101.0,
            primary_target=104.8,
        )

        with patch(
            "synthetic_trader.strategy.decision_engine.build_snapshot",
            return_value=feature_snapshot,
        ) as build_snapshot_mock:
            with patch.object(engine, "_score_direction", side_effect=[0.9, 0.1]):
                with patch(
                    "synthetic_trader.strategy.decision_engine.infer_top_down_bias",
                    return_value=bias,
                ) as bias_mock:
                    with patch(
                        "synthetic_trader.strategy.decision_engine.classify_setup",
                        return_value=setup,
                    ):
                        with patch(
                            "synthetic_trader.strategy.decision_engine.confirm_setup",
                            return_value=confirmation,
                        ) as confirm_mock:
                            with patch(
                                "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                                return_value=execution_plan,
                            ):
                                report = engine.evaluate(
                                    "R_75",
                                    candles=execution_candles,
                                    higher_timeframe_candles=bias_candles,
                                    role_candles={
                                        "bias": bias_candles,
                                        "setup": setup_candles,
                                        "confirmation": confirmation_candles,
                                        "execution": execution_candles,
                                    },
                                )

        self.assertIsNotNone(report.signal)
        build_snapshot_mock.assert_called_once_with(
            symbol="R_75",
            timeframe_sec=profile.execution_timeframe_sec,
            candles=execution_candles,
            higher_timeframe_candles=confirmation_candles,
            extra_timeframes={
                "bias": bias_candles,
                "setup": setup_candles,
                "confirmation": confirmation_candles,
            },
        )
        bias_mock.assert_called_once_with(
            symbol="R_75",
            bias_candles=bias_candles,
            setup_candles=setup_candles,
            confirmation_candles=confirmation_candles,
            execution_candles=execution_candles,
        )
        confirm_mock.assert_called_once_with(
            setup=setup,
            confirmation_candles=confirmation_candles[-30:],
        )

    def test_r100_keeps_confirmed_top_down_setup_when_micro_model_is_neutral(self) -> None:
        config = TraderConfig.default()
        engine = DecisionEngine(config)
        profile = config.symbols["R_100"]
        bias_candles = trending_candles(symbol="R_100", count=150)
        setup_candles = trending_candles(symbol="R_100", count=100)
        confirmation_candles = trending_candles(symbol="R_100", count=60)
        execution_candles = trending_candles(symbol="R_100", count=120)
        feature_snapshot = FeatureSnapshot(
            symbol="R_100",
            epoch=execution_candles[-1].open_time,
            timeframe_sec=profile.execution_timeframe_sec,
            features={"atr_14": 1.0, "structure_bias": 0.0, "body": 0.0},
            regime=Regime.RANGE,
            structure={"liquidity_sweep_down": 1.0},
            notes=("execution snapshot",),
        )
        bias = SimpleNamespace(
            direction="bullish",
            reason="4H structure is bullish",
            invalidation_price=101.0,
        )
        setup = SimpleNamespace(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=102.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        )
        confirmation = SimpleNamespace(
            state="confirmed",
            reason="15m confirmation aligns with the setup",
        )
        execution_plan = intraday_execution_plan(
            entry=103.4,
            execution_stop=102.6,
            thesis_invalidation=101.0,
            primary_target=104.8,
        )

        with patch(
            "synthetic_trader.strategy.decision_engine.build_snapshot",
            return_value=feature_snapshot,
        ):
            with patch.object(engine.model, "predict_proba", return_value=0.5):
                with patch.object(engine, "_score_direction", side_effect=[0.426, 0.31]):
                    with patch(
                        "synthetic_trader.strategy.decision_engine.infer_top_down_bias",
                        return_value=bias,
                    ):
                        with patch(
                            "synthetic_trader.strategy.decision_engine.classify_setup",
                            return_value=setup,
                        ):
                            with patch(
                                "synthetic_trader.strategy.decision_engine.confirm_setup",
                                return_value=confirmation,
                            ):
                                with patch(
                                    "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                                    return_value=execution_plan,
                                ):
                                    report = engine.evaluate(
                                        "R_100",
                                        candles=execution_candles,
                                        higher_timeframe_candles=bias_candles,
                                        role_candles={
                                            "bias": bias_candles,
                                            "setup": setup_candles,
                                            "confirmation": confirmation_candles,
                                            "execution": execution_candles,
                                        },
                                    )

        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertGreaterEqual(report.signal.confidence, 0.52)
        self.assertEqual(report.signal.direction, Direction.LONG)

    def test_trade_signal_exposes_distinct_execution_and_thesis_levels(self) -> None:
        engine = DecisionEngine(TraderConfig.default())
        with patch(
            "synthetic_trader.strategy.decision_engine.build_intraday_execution",
            return_value=intraday_execution_plan(),
        ):
            report = engine.evaluate("R_100", candles=trending_candles(symbol="R_100"))

        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertIsNotNone(report.signal.execution_stop)
        self.assertIsNotNone(report.signal.thesis_invalidation)
        self.assertIsNotNone(report.signal.primary_target)
        self.assertEqual(report.signal.hold_horizon_minutes, 60)

    def test_decision_engine_accepts_clean_r100_reclaim_pattern_with_balanced_target(self) -> None:
        config = TraderConfig.default()
        engine = DecisionEngine(config)
        profile = config.symbols["R_100"]
        bias_candles = trending_candles(symbol="R_100", count=150)
        setup_candles = trending_candles(symbol="R_100", count=100)
        confirmation_candles = trending_candles(symbol="R_100", count=60)
        execution_candles = trending_candles(symbol="R_100", count=120)
        feature_snapshot = FeatureSnapshot(
            symbol="R_100",
            epoch=execution_candles[-1].open_time,
            timeframe_sec=profile.execution_timeframe_sec,
            features={"atr_14": 1.0, "structure_bias": 1.0, "body": 1.0},
            regime=Regime.TREND_UP,
            structure={"bos_up": 1.0},
            notes=("execution snapshot",),
        )
        bias = SimpleNamespace(
            direction="bullish",
            reason="4H structure is bullish",
            invalidation_price=101.0,
        )
        setup = SimpleNamespace(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=102.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        )
        confirmation = SimpleNamespace(
            state="confirmed",
            reason="15m confirmation aligns with the setup",
        )
        execution_plan = intraday_execution_plan(
            entry=476.2,
            execution_stop=474.9,
            thesis_invalidation=440.67,
            primary_target=488.4,
            hold_horizon_minutes=60,
        )

        with patch(
            "synthetic_trader.strategy.decision_engine.build_snapshot",
            return_value=feature_snapshot,
        ):
            with patch.object(engine, "_score_direction", side_effect=[0.9, 0.1]):
                with patch(
                    "synthetic_trader.strategy.decision_engine.infer_top_down_bias",
                    return_value=bias,
                ):
                    with patch(
                        "synthetic_trader.strategy.decision_engine.classify_setup",
                        return_value=setup,
                    ):
                        with patch(
                            "synthetic_trader.strategy.decision_engine.confirm_setup",
                            return_value=confirmation,
                        ):
                            with patch(
                                "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                                create=True,
                                return_value=execution_plan,
                            ):
                                report = engine.evaluate(
                                    "R_100",
                                    candles=execution_candles,
                                    higher_timeframe_candles=bias_candles,
                                    role_candles={
                                        "bias": bias_candles,
                                        "setup": setup_candles,
                                        "confirmation": confirmation_candles,
                                        "execution": execution_candles,
                                    },
                                )

        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertEqual(report.signal.stop_loss, report.signal.execution_stop)
        self.assertNotEqual(report.signal.stop_loss, report.signal.thesis_invalidation)
        self.assertEqual(report.signal.take_profit, report.signal.primary_target)
        self.assertAlmostEqual(report.signal.primary_target, 488.4)
        self.assertLess(abs(report.signal.primary_target - report.signal.entry), 20.0)

    def test_decision_engine_accepts_clean_r75_pattern_with_symbol_aware_target(self) -> None:
        config = TraderConfig.default()
        engine = DecisionEngine(config)
        profile = config.symbols["R_75"]
        bias_candles = trending_candles(symbol="R_75", count=150)
        setup_candles = trending_candles(symbol="R_75", count=100)
        confirmation_candles = trending_candles(symbol="R_75", count=60)
        execution_candles = trending_candles(symbol="R_75", count=120)
        feature_snapshot = FeatureSnapshot(
            symbol="R_75",
            epoch=execution_candles[-1].open_time,
            timeframe_sec=profile.execution_timeframe_sec,
            features={"atr_14": 1.0, "structure_bias": 1.0, "body": 1.0},
            regime=Regime.TREND_UP,
            structure={"bos_up": 1.0},
            notes=("execution snapshot",),
        )
        bias = SimpleNamespace(
            direction="bullish",
            reason="4H structure is bullish",
            invalidation_price=52541.0,
        )
        setup = SimpleNamespace(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=55340.0,
            trigger_zone_high=55620.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        )
        confirmation = SimpleNamespace(
            state="confirmed",
            reason="15m confirmation aligns with the setup",
        )
        execution_plan = intraday_execution_plan(
            entry=55620.0,
            execution_stop=55280.0,
            thesis_invalidation=52541.0,
            primary_target=56180.0,
            hold_horizon_minutes=60,
            trigger_type="continuation_close",
        )

        with patch(
            "synthetic_trader.strategy.decision_engine.build_snapshot",
            return_value=feature_snapshot,
        ):
            with patch.object(engine, "_score_direction", side_effect=[0.9, 0.1]):
                with patch(
                    "synthetic_trader.strategy.decision_engine.infer_top_down_bias",
                    return_value=bias,
                ):
                    with patch(
                        "synthetic_trader.strategy.decision_engine.classify_setup",
                        return_value=setup,
                    ):
                        with patch(
                            "synthetic_trader.strategy.decision_engine.confirm_setup",
                            return_value=confirmation,
                        ):
                            with patch(
                                "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                                create=True,
                                return_value=execution_plan,
                            ):
                                report = engine.evaluate(
                                    "R_75",
                                    candles=execution_candles,
                                    higher_timeframe_candles=bias_candles,
                                    role_candles={
                                        "bias": bias_candles,
                                        "setup": setup_candles,
                                        "confirmation": confirmation_candles,
                                        "execution": execution_candles,
                                    },
                                )

        self.assertIsNotNone(report.signal)
        assert report.signal is not None
        self.assertEqual(report.signal.stop_loss, report.signal.execution_stop)
        self.assertNotEqual(report.signal.stop_loss, report.signal.thesis_invalidation)
        self.assertEqual(report.signal.take_profit, report.signal.primary_target)
        self.assertAlmostEqual(report.signal.primary_target, 56180.0)
        self.assertEqual(report.signal.execution_trigger_type, "continuation_close")
        self.assertLess(abs(report.signal.primary_target - report.signal.entry), 800.0)

    def test_decision_engine_preserves_shared_contract_while_symbols_differ(self) -> None:
        config = TraderConfig.default()
        cases = {
            "R_75": {
                "entry": 55620.0,
                "execution_stop": 55280.0,
                "thesis_invalidation": 52541.0,
                "primary_target": 56180.0,
                "trigger_type": "continuation_close",
            },
            "R_100": {
                "entry": 476.2,
                "execution_stop": 474.9,
                "thesis_invalidation": 440.67,
                "primary_target": 488.4,
                "trigger_type": "reclaim_pullback",
            },
        }
        signals = {}

        for symbol, levels in cases.items():
            with self.subTest(symbol=symbol):
                engine = DecisionEngine(config)
                profile = config.symbols[symbol]
                bias_candles = trending_candles(symbol=symbol, count=150)
                setup_candles = trending_candles(symbol=symbol, count=100)
                confirmation_candles = trending_candles(symbol=symbol, count=60)
                execution_candles = trending_candles(symbol=symbol, count=120)
                feature_snapshot = FeatureSnapshot(
                    symbol=symbol,
                    epoch=execution_candles[-1].open_time,
                    timeframe_sec=profile.execution_timeframe_sec,
                    features={"atr_14": 1.0, "structure_bias": 1.0, "body": 1.0},
                    regime=Regime.TREND_UP,
                    structure={"bos_up": 1.0},
                    notes=("execution snapshot",),
                )
                bias = SimpleNamespace(
                    direction="bullish",
                    reason="4H structure is bullish",
                    invalidation_price=levels["thesis_invalidation"],
                )
                setup = SimpleNamespace(
                    state="continuation",
                    trade_direction="buy",
                    trigger_zone_low=levels["execution_stop"],
                    trigger_zone_high=levels["entry"],
                    reason="1H setup aligns with bullish higher-timeframe bias",
                )
                confirmation = SimpleNamespace(
                    state="confirmed",
                    reason="15m confirmation aligns with the setup",
                )
                execution_plan = intraday_execution_plan(
                    entry=levels["entry"],
                    execution_stop=levels["execution_stop"],
                    thesis_invalidation=levels["thesis_invalidation"],
                    primary_target=levels["primary_target"],
                    hold_horizon_minutes=60,
                    trigger_type=levels["trigger_type"],
                )

                with patch(
                    "synthetic_trader.strategy.decision_engine.build_snapshot",
                    return_value=feature_snapshot,
                ):
                    with patch.object(engine, "_score_direction", side_effect=[0.9, 0.1]):
                        with patch(
                            "synthetic_trader.strategy.decision_engine.infer_top_down_bias",
                            return_value=bias,
                        ):
                            with patch(
                                "synthetic_trader.strategy.decision_engine.classify_setup",
                                return_value=setup,
                            ):
                                with patch(
                                    "synthetic_trader.strategy.decision_engine.confirm_setup",
                                    return_value=confirmation,
                                ):
                                    with patch(
                                        "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                                        create=True,
                                        return_value=execution_plan,
                                    ):
                                        report = engine.evaluate(
                                            symbol,
                                            candles=execution_candles,
                                            higher_timeframe_candles=bias_candles,
                                            role_candles={
                                                "bias": bias_candles,
                                                "setup": setup_candles,
                                                "confirmation": confirmation_candles,
                                                "execution": execution_candles,
                                            },
                                        )

                self.assertIsNotNone(report.signal)
                assert report.signal is not None
                self.assertEqual(report.signal.symbol, symbol)
                self.assertEqual(report.signal.stop_loss, report.signal.execution_stop)
                self.assertEqual(report.signal.take_profit, report.signal.primary_target)
                self.assertEqual(report.signal.execution_trigger_type, levels["trigger_type"])
                signals[symbol] = report.signal

        self.assertNotEqual(signals["R_75"].primary_target, signals["R_100"].primary_target)
        self.assertNotEqual(signals["R_75"].entry, signals["R_100"].entry)

    def test_decision_engine_rejects_weak_r100_pattern_even_when_top_down_thesis_is_confirmed(self) -> None:
        config = TraderConfig.default()
        engine = DecisionEngine(config)
        profile = config.symbols["R_100"]
        bias_candles = trending_candles(symbol="R_100", count=150)
        setup_candles = trending_candles(symbol="R_100", count=100)
        confirmation_candles = trending_candles(symbol="R_100", count=60)
        execution_candles = trending_candles(symbol="R_100", count=120)
        feature_snapshot = FeatureSnapshot(
            symbol="R_100",
            epoch=execution_candles[-1].open_time,
            timeframe_sec=profile.execution_timeframe_sec,
            features={"atr_14": 1.0, "structure_bias": 1.0, "body": 1.0},
            regime=Regime.TREND_UP,
            structure={"bos_up": 1.0},
            notes=("execution snapshot",),
        )
        bias = SimpleNamespace(
            direction="bullish",
            reason="4H structure is bullish",
            invalidation_price=101.0,
        )
        setup = SimpleNamespace(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=102.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        )
        confirmation = SimpleNamespace(
            state="confirmed",
            reason="15m confirmation aligns with the setup",
        )

        with patch(
            "synthetic_trader.strategy.decision_engine.build_snapshot",
            return_value=feature_snapshot,
        ):
            with patch.object(engine, "_score_direction", side_effect=[0.9, 0.1]):
                with patch(
                    "synthetic_trader.strategy.decision_engine.infer_top_down_bias",
                    return_value=bias,
                ):
                    with patch(
                        "synthetic_trader.strategy.decision_engine.classify_setup",
                        return_value=setup,
                    ):
                        with patch(
                            "synthetic_trader.strategy.decision_engine.confirm_setup",
                            return_value=confirmation,
                        ):
                            with patch(
                                "synthetic_trader.strategy.decision_engine.build_intraday_execution",
                                create=True,
                                return_value=None,
                            ):
                                report = engine.evaluate(
                                    "R_100",
                                    candles=execution_candles,
                                    higher_timeframe_candles=bias_candles,
                                    role_candles={
                                        "bias": bias_candles,
                                        "setup": setup_candles,
                                        "confirmation": confirmation_candles,
                                        "execution": execution_candles,
                                    },
                                )

        self.assertIsNotNone(report.signal)
        self.assertEqual(report.signal.symbol, "R_100")


if __name__ == "__main__":
    unittest.main()
