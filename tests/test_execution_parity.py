"""Tests for the MT5 execution simulator and paper->live execution parity.

The execution layer must behave as ONE layer whether it fills via the
simulated backend (forward-demo paper), the MT5 python-API backend (the
Python CTrade-equivalent), or the MQL5 SynthCallExecutor EA (which polls the
call file ea_emitter writes).  These tests cover the CTrade-equivalent
simulator's fill/close/modify/reject semantics and the parity engine that
proves the simulated and live backends make identical decisions.
"""

from __future__ import annotations

import unittest

from synthetic_trader.config import Mt5Config, PaperExecutionConfig
from synthetic_trader.domain import (
    Candle,
    Direction,
    FeatureSnapshot,
    OrderIntent,
    Regime,
    TradeSignal,
)
from synthetic_trader.execution.ea_emitter import build_call_record
from synthetic_trader.execution.mt5_simulator import FakeMetaTrader5
from synthetic_trader.execution.parity import (
    check_ea_contract,
    run_parity_replay,
    run_rejection_probe,
)

MT5_CONFIG = Mt5Config(symbol_map={"R_75": "SYN75"})
PAPER_CONFIG = PaperExecutionConfig()  # zero slippage/penalty -> exact parity


def _signal(
    direction: Direction,
    entry: float,
    sl: float,
    tp: float,
    horizon_sec: int = 86400,
    epoch: float = 1_700_000_000.0,
) -> TradeSignal:
    return TradeSignal(
        symbol="R_75",
        direction=direction,
        confidence=0.7,
        min_confidence=0.5,
        entry=entry,
        stop_loss=sl,
        take_profit=tp,
        horizon_sec=horizon_sec,
        snapshot=FeatureSnapshot(
            symbol="R_75",
            epoch=epoch,
            timeframe_sec=300,
            features={"rz": 0.8, "z": 1.2},
            regime=Regime.TREND_UP,
            structure={},
        ),
        rationale=("parity-test",),
        model_version="parity",
    )


def _intent(signal: TradeSignal, volume: float = 0.1) -> OrderIntent:
    return OrderIntent(
        signal=signal,
        stake=50.0,
        max_loss=50.0,
        metadata={"volume": volume},
    )


def _candle(open_time: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        symbol="R_75", timeframe_sec=300, open_time=open_time,
        open=o, high=h, low=l, close=c,
    )


class FakeMetaTrader5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.sim = FakeMetaTrader5(bid=1700.0, ask=1700.4)

    def test_open_buy_fills_at_ask_and_buy_at_bid(self) -> None:
        buy = self.sim.order_send(
            {"action": self.sim.TRADE_ACTION_DEAL, "symbol": "SYN75", "volume": 0.1,
             "type": self.sim.ORDER_TYPE_BUY, "sl": 1690.0, "tp": 1712.0,
             "type_time": 0, "type_filling": 0}
        )
        self.assertEqual(buy.retcode, 10009)
        self.assertEqual(self.sim.position_by_ticket(buy.order)["price_open"], 1700.4)
        sell = self.sim.order_send(
            {"action": self.sim.TRADE_ACTION_DEAL, "symbol": "SYN75", "volume": 0.1,
             "type": self.sim.ORDER_TYPE_SELL, "sl": 1710.0, "tp": 1688.0,
             "type_time": 0, "type_filling": 0}
        )
        self.assertEqual(self.sim.position_by_ticket(sell.order)["price_open"], 1700.0)

    def test_close_by_ticket_and_modify_sltp(self) -> None:
        buy = self.sim.order_send(
            {"action": self.sim.TRADE_ACTION_DEAL, "symbol": "SYN75", "volume": 0.1,
             "type": self.sim.ORDER_TYPE_BUY, "sl": 1690.0, "tp": 1712.0,
             "type_time": 0, "type_filling": 0}
        )
        ticket = buy.order
        mod = self.sim.order_send(
            {"action": self.sim.TRADE_ACTION_SLTP, "symbol": "SYN75",
             "position": ticket, "sl": 1700.0, "tp": 1712.0}
        )
        self.assertEqual(mod.retcode, 10009)
        self.assertEqual(self.sim.position_by_ticket(ticket)["sl"], 1700.0)
        close = self.sim.order_send(
            {"action": self.sim.TRADE_ACTION_DEAL, "symbol": "SYN75",
             "position": ticket, "volume": 0.1, "type": self.sim.ORDER_TYPE_SELL,
             "type_time": 0, "type_filling": 0}
        )
        self.assertEqual(close.retcode, 10009)
        self.assertIsNone(self.sim.position_by_ticket(ticket))
        self.assertEqual(self.sim.open_position_count, 0)

    def test_positions_get_filters_by_symbol(self) -> None:
        self.sim.order_send(
            {"action": self.sim.TRADE_ACTION_DEAL, "symbol": "SYN75", "volume": 0.1,
             "type": self.sim.ORDER_TYPE_BUY, "type_time": 0, "type_filling": 0}
        )
        self.assertEqual(len(self.sim.positions_get(symbol="SYN75")), 1)
        self.assertEqual(len(self.sim.positions_get(symbol="SYN100")), 0)

    def test_reject_retcode_places_nothing(self) -> None:
        sim = FakeMetaTrader5(bid=1700.0, ask=1700.0, reject_retcode=10014)
        result = sim.order_send(
            {"action": sim.TRADE_ACTION_DEAL, "symbol": "SYN75", "volume": 0.1,
             "type": sim.ORDER_TYPE_BUY, "type_time": 0, "type_filling": 0}
        )
        self.assertEqual(result.retcode, 10014)
        self.assertEqual(sim.open_position_count, 0)


class ParityReplayTests(unittest.TestCase):
    def _run(self, signal: TradeSignal, candles: list[Candle]) -> object:
        sim = FakeMetaTrader5(bid=signal.entry, ask=signal.entry)
        return run_parity_replay(
            symbol="R_75",
            intents=[_intent(signal)],
            candles=candles,
            mt5_simulator=sim,
            mt5_config=MT5_CONFIG,
            paper_config=PAPER_CONFIG,
        )

    def test_target_exit_parity(self) -> None:
        report = self._run(
            _signal(Direction.LONG, 1700.0, 1690.0, 1712.0),
            [
                _candle(1_700_000_000, 1701, 1703, 1700, 1702),
                _candle(1_700_000_300, 1708, 1713, 1705, 1712),
            ],
        )
        self.assertTrue(report.ok, msg=report.summary())

    def test_stop_exit_parity(self) -> None:
        report = self._run(
            _signal(Direction.SHORT, 1700.0, 1710.0, 1695.0),
            [
                _candle(1_700_000_000, 1701, 1703, 1700, 1702),
                _candle(1_700_000_300, 1708, 1711, 1702, 1710),
            ],
        )
        self.assertTrue(report.ok, msg=report.summary())

    def test_expiry_exit_parity(self) -> None:
        report = self._run(
            _signal(Direction.LONG, 1700.0, 1690.0, 1712.0, horizon_sec=300, epoch=1_700_000_000.0),
            [_candle(1_700_000_000, 1701, 1702, 1699, 1701)],
        )
        self.assertTrue(report.ok, msg=report.summary())

    def test_slippage_breaks_parity(self) -> None:
        """Exit slippage on the paper side must be caught as a mismatch —
        the harness runs with zero slippage so this proves the check has
        teeth, not just happy-path agreement."""
        signal = _signal(Direction.LONG, 1700.0, 1690.0, 1712.0)
        sim = FakeMetaTrader5(bid=signal.entry, ask=signal.entry)
        report = run_parity_replay(
            symbol="R_75",
            intents=[_intent(signal)],
            candles=[_candle(1_700_000_300, 1708, 1713, 1705, 1712)],
            mt5_simulator=sim,
            mt5_config=MT5_CONFIG,
            paper_config=PaperExecutionConfig(exit_slippage_ticks=2.0),
        )
        self.assertFalse(report.ok)
        self.assertTrue(
            any(item.aspect == "outcome:0:exit" for item in report.mismatches)
        )

    def test_rejection_probe(self) -> None:
        signal = _signal(Direction.LONG, 1700.0, 1690.0, 1712.0)
        self.assertTrue(
            run_rejection_probe(symbol="R_75", intent=_intent(signal), mt5_config=MT5_CONFIG)
        )


class EaContractTests(unittest.TestCase):
    def test_ea_contract_matches_executed_levels(self) -> None:
        signal = _signal(Direction.LONG, 1700.0, 1690.0, 1712.0)
        ok, detail = check_ea_contract(
            intent=_intent(signal),
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.1,
            magic=7788123,
        )
        self.assertTrue(ok, msg=detail)
        self.assertIn("buy entry=1700.0", detail)

    def test_ea_contract_detects_level_drift(self) -> None:
        signal = _signal(Direction.SHORT, 1700.0, 1710.0, 1695.0)
        intent = _intent(signal)
        ok, detail = check_ea_contract(
            intent=intent,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.1,
            magic=7788123,
        )
        self.assertTrue(ok, msg=detail)
        # A RECORD that drifted from the executed levels (e.g. an alert whose
        # primary_target diverged from the signal the backend executed) must
        # be caught — this is the EA-vs-Python contract guard.
        drifted = build_call_record(
            {
                "direction_bias": "sell",
                "entry": 1700.0,
                "execution_stop": 1710.0,
                "primary_target": 1690.0,  # drifted from 1695.0
                "hold_horizon_minutes": 1440,
                "generated_at": signal.snapshot.epoch,
                "evidence_status": "proven",
            },
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.1,
            magic=7788123,
        )
        ok, detail = check_ea_contract(
            intent=intent,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.1,
            magic=7788123,
            record=drifted,
        )
        self.assertFalse(ok)
        self.assertIn("take_profit mismatch", detail)


if __name__ == "__main__":
    unittest.main()
