from __future__ import annotations

import unittest
from unittest.mock import Mock, ANY

from synthetic_trader.config import Mt5Config
from synthetic_trader.domain import Candle, Direction, FeatureSnapshot, OrderIntent, Regime, TradeSignal
from synthetic_trader.execution.mt5 import Mt5OrderResult, Mt5PositionSnapshot, Mt5SyncResult
from synthetic_trader.live.execution_backends import Mt5LiveExecutionBackend


class Mt5LiveBackendTests(unittest.TestCase):
    def test_submit_places_mt5_order_and_returns_accepted_result(self) -> None:
        journal = Mock()
        backend = Mt5LiveExecutionBackend(
            mt5_config=Mt5Config(symbol_map={"R_100": "Volatility 100 Index"}),
            symbol="R_100",
            journal=journal,
            mt5_module=Mock(),
        )
        backend._place_order = Mock(
            return_value=Mt5OrderResult(
                accepted=True,
                order_ticket=11,
                deal_ticket=22,
                retcode=10009,
                message="done",
                venue_symbol="Volatility 100 Index",
            )
        )
        backend._sync_positions = Mock(
            return_value=Mt5SyncResult(
                ready=True,
                failures=(),
                venue_symbol="Volatility 100 Index",
                positions=(),
            )
        )

        signal = TradeSignal(
            symbol="R_100",
            direction=Direction.LONG,
            confidence=0.7,
            entry=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            horizon_sec=600,
            snapshot=FeatureSnapshot(
                symbol="R_100",
                epoch=60,
                timeframe_sec=60,
                features={"atr_14": 1.0},
                regime=Regime.RANGE,
                structure={"bias": 0.0},
            ),
            rationale=("test",),
            model_version="unit-test",
        )

        result = backend.submit(OrderIntent(signal=signal, stake=10.0, max_loss=10.0))

        self.assertTrue(result.accepted)
        journal.record_event.assert_any_call("mt5_live_entry_result", ANY)

    def test_shutdown_records_fail_closed_when_multiple_positions_exist(self) -> None:
        journal = Mock()
        backend = Mt5LiveExecutionBackend(
            mt5_config=Mt5Config(symbol_map={"R_100": "Volatility 100 Index"}),
            symbol="R_100",
            journal=journal,
            mt5_module=Mock(),
        )
        backend._sync_positions = Mock(
            return_value=Mt5SyncResult(
                ready=True,
                failures=(),
                venue_symbol="Volatility 100 Index",
                positions=(Mock(ticket=1), Mock(ticket=2)),
            )
        )

        result = backend.shutdown(None)

        self.assertFalse(result.finalized)
        journal.record_event.assert_any_call(
            "mt5_live_fail_closed",
            {"symbol": "R_100", "reason": "ambiguous_shutdown_state"},
        )

    def test_shutdown_closes_single_position_when_state_is_unambiguous(self) -> None:
        journal = Mock()
        backend = Mt5LiveExecutionBackend(
            mt5_config=Mt5Config(symbol_map={"R_100": "Volatility 100 Index"}),
            symbol="R_100",
            journal=journal,
            mt5_module=Mock(),
        )
        backend._sync_positions = Mock(
            return_value=Mt5SyncResult(
                ready=True,
                failures=(),
                venue_symbol="Volatility 100 Index",
                positions=(
                    Mt5PositionSnapshot(
                        symbol="R_100",
                        venue_symbol="Volatility 100 Index",
                        ticket=7,
                        direction=Direction.LONG,
                        volume=0.2,
                        open_price=100.0,
                        current_price=101.0,
                        broker_time=123,
                    ),
                ),
            )
        )
        backend._close_position = Mock(
            return_value=Mt5OrderResult(
                accepted=True,
                order_ticket=70,
                deal_ticket=71,
                retcode=10009,
                message="closed",
                venue_symbol="Volatility 100 Index",
            )
        )

        result = backend.shutdown(None)

        self.assertTrue(result.finalized)
        self.assertEqual(result.unresolved_positions, 0)
        journal.record_event.assert_any_call(
            "mt5_close_result",
            {
                "symbol": "R_100",
                "venue_symbol": "Volatility 100 Index",
                "ticket": 7,
                "accepted": True,
                "retcode": 10009,
                "message": "closed",
            },
        )

    def test_on_candle_closes_tracked_position_when_take_profit_is_hit(self) -> None:
        journal = Mock()
        backend = Mt5LiveExecutionBackend(
            mt5_config=Mt5Config(symbol_map={"R_100": "Volatility 100 Index"}),
            symbol="R_100",
            journal=journal,
            mt5_module=Mock(),
        )
        backend._place_order = Mock(
            return_value=Mt5OrderResult(
                accepted=True,
                order_ticket=11,
                deal_ticket=22,
                retcode=10009,
                message="done",
                venue_symbol="Volatility 100 Index",
            )
        )
        backend._sync_positions = Mock(
            return_value=Mt5SyncResult(
                ready=True,
                failures=(),
                venue_symbol="Volatility 100 Index",
                positions=(
                    Mt5PositionSnapshot(
                        symbol="R_100",
                        venue_symbol="Volatility 100 Index",
                        ticket=7,
                        direction=Direction.LONG,
                        volume=0.2,
                        open_price=100.0,
                        current_price=100.0,
                        broker_time=123,
                    ),
                ),
            )
        )
        backend._close_position = Mock(
            return_value=Mt5OrderResult(
                accepted=True,
                order_ticket=70,
                deal_ticket=71,
                retcode=10009,
                message="closed",
                venue_symbol="Volatility 100 Index",
            )
        )

        signal = TradeSignal(
            symbol="R_100",
            direction=Direction.LONG,
            confidence=0.7,
            entry=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            horizon_sec=600,
            snapshot=FeatureSnapshot(
                symbol="R_100",
                epoch=60,
                timeframe_sec=60,
                features={"atr_14": 1.0},
                regime=Regime.RANGE,
                structure={"bias": 0.0},
            ),
            rationale=("test",),
            model_version="unit-test",
        )
        backend.submit(OrderIntent(signal=signal, stake=10.0, max_loss=10.0))

        outcomes = backend.on_candle(
            Candle(
                symbol="R_100",
                timeframe_sec=60,
                open_time=60,
                open=100.0,
                high=102.5,
                low=99.8,
                close=101.8,
            )
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].symbol, "R_100")
        self.assertGreater(outcomes[0].pnl, 0.0)
        journal.record_event.assert_any_call(
            "mt5_close_result",
            {
                "symbol": "R_100",
                "venue_symbol": "Volatility 100 Index",
                "ticket": 7,
                "accepted": True,
                "retcode": 10009,
                "message": "closed",
            },
        )


if __name__ == "__main__":
    unittest.main()
