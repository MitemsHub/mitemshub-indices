from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from synthetic_trader.config import PaperExecutionConfig
from synthetic_trader.domain import Candle, Direction, OrderIntent, Position, TradeOutcome


@dataclass
class PaperBroker:
    config: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)
    positions: dict[str, Position] = field(default_factory=dict)

    def submit(self, intent: OrderIntent) -> Position:
        position = Position(
            id=str(uuid4()),
            signal=intent.signal,
            stake=intent.stake,
            opened_at=intent.signal.snapshot.epoch,
            open_price=intent.signal.entry,
        )
        self.positions[position.id] = position
        return position

    def on_candle(self, candle: Candle) -> list[TradeOutcome]:
        outcomes: list[TradeOutcome] = []
        for position in list(self.positions.values()):
            if not position.is_open or position.signal.symbol != candle.symbol:
                continue

            outcome = self._maybe_close(position, candle)
            if outcome is not None:
                outcomes.append(outcome)
                del self.positions[position.id]
        return outcomes

    def close_all(self, candle: Candle) -> list[TradeOutcome]:
        outcomes: list[TradeOutcome] = []
        for position in list(self.positions.values()):
            if position.signal.symbol != candle.symbol:
                continue
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(position.signal, candle.close),
                candle.open_time + candle.timeframe_sec,
            )
            outcomes.append(outcome)
            del self.positions[position.id]
        return outcomes

    def _maybe_close(self, position: Position, candle: Candle) -> TradeOutcome | None:
        signal = position.signal
        expired = candle.open_time + candle.timeframe_sec >= signal.snapshot.epoch + signal.horizon_sec
        if signal.direction is Direction.LONG:
            stop_hit = candle.low <= signal.stop_loss
            target_hit = candle.high >= signal.take_profit
        else:
            stop_hit = candle.high >= signal.stop_loss
            target_hit = candle.low <= signal.take_profit

        if stop_hit and target_hit:
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.stop_loss),
                candle.open_time + candle.timeframe_sec,
            )
        if stop_hit:
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.stop_loss),
                candle.open_time + candle.timeframe_sec,
            )
        if target_hit:
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.take_profit),
                candle.open_time + candle.timeframe_sec,
            )
        if expired:
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, candle.close),
                candle.open_time + candle.timeframe_sec,
            )
        return None

    def _apply_exit_slippage(self, signal, price: float) -> float:
        ticks = self.config.exit_slippage_ticks
        if signal.direction is Direction.LONG:
            return price - ticks
        return price + ticks

    def _close_at_price(self, position: Position, price: float, closed_at: float) -> TradeOutcome:
        signal = position.signal
        risk_distance = abs(signal.entry - signal.stop_loss)
        if risk_distance <= 0.0:
            risk_distance = signal.entry * 0.001
        if signal.direction is Direction.LONG:
            return_r = (price - signal.entry) / risk_distance
        else:
            return_r = (signal.entry - price) / risk_distance
        pnl = position.stake * return_r - self.config.execution_penalty_per_trade
        position.is_open = False
        position.closed_at = closed_at
        position.close_price = price
        position.pnl = pnl
        return TradeOutcome(
            position_id=position.id,
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            exit=price,
            pnl=pnl,
            return_r=return_r,
            opened_at=position.opened_at,
            closed_at=closed_at,
            features=signal.snapshot.features,
            won=pnl > 0,
        )
