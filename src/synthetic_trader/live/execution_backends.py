from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from synthetic_trader.config import LiveMode, Mt5Config, PaperExecutionConfig, Venue
from synthetic_trader.domain import Candle, Direction, OrderIntent, TradeOutcome
from synthetic_trader.execution.mt5 import (
    Mt5CloseRequest,
    Mt5ModifyRequest,
    Mt5OrderRequest,
    Mt5OrderResult,
    Mt5PositionSnapshot,
    Mt5SyncResult,
    close_mt5_position,
    modify_mt5_position,
    place_mt5_order,
    synchronize_mt5_positions,
)
from synthetic_trader.execution.paper import PaperBroker


@dataclass(frozen=True)
class SubmitResult:
    accepted: bool
    position_id: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ShutdownResult:
    outcomes: tuple[TradeOutcome, ...]
    open_positions_before_shutdown: int
    unresolved_positions: int
    finalized: bool


@dataclass(frozen=True)
class TrackedMt5Position:
    ticket: int
    venue_symbol: str
    signal: object
    stake: float
    volume: float


class ExecutionBackend(Protocol):
    def submit(self, intent: OrderIntent) -> SubmitResult: ...

    def on_candle(self, candle: Candle) -> list[TradeOutcome]: ...

    def open_positions_count(self) -> int: ...

    def shutdown(self, candle: Candle | None) -> ShutdownResult: ...


class SimulatedExecutionBackend:
    def __init__(self, *, config: PaperExecutionConfig) -> None:
        self._broker = PaperBroker(config)

    def submit(self, intent: OrderIntent) -> SubmitResult:
        position = self._broker.submit(intent)
        return SubmitResult(
            accepted=True,
            position_id=position.id,
            metadata={"backend": "simulated"},
        )

    def on_candle(self, candle: Candle) -> list[TradeOutcome]:
        return self._broker.on_candle(candle)

    def open_positions_count(self) -> int:
        return len(self._broker.positions)

    def shutdown(self, candle: Candle | None) -> ShutdownResult:
        open_positions_before_shutdown = len(self._broker.positions)
        outcomes = tuple(self._broker.close_all(candle)) if candle is not None else ()
        return ShutdownResult(
            outcomes=outcomes,
            open_positions_before_shutdown=open_positions_before_shutdown,
            unresolved_positions=len(self._broker.positions),
            finalized=True,
        )


class Mt5LiveExecutionBackend:
    def __init__(self, *, mt5_config: Mt5Config, symbol: str, journal, mt5_module) -> None:
        self._mt5_config = mt5_config
        self._symbol = symbol
        self._journal = journal
        self._mt5_module = mt5_module
        self._tracked_positions: dict[int, TrackedMt5Position] = {}
        self._last_sync = Mt5SyncResult(
            ready=True,
            failures=(),
            venue_symbol=mt5_config.resolve_symbol(symbol),
            positions=(),
        )

    def submit(self, intent: OrderIntent) -> SubmitResult:
        venue_symbol = self._mt5_config.resolve_symbol(intent.signal.symbol)
        self._journal.record_event(
            "mt5_live_entry_submitted",
            {
                "symbol": intent.signal.symbol,
                "venue_symbol": venue_symbol,
                "mode": "armed-live",
            },
        )
        result = self._place_order(intent, venue_symbol)
        self._journal.record_event(
            "mt5_live_entry_result",
            {
                "symbol": intent.signal.symbol,
                "venue_symbol": venue_symbol,
                "accepted": result.accepted,
                "order_ticket": result.order_ticket,
                "deal_ticket": result.deal_ticket,
                "retcode": result.retcode,
                "message": result.message,
            },
        )
        self._last_sync = self._sync_positions()
        self._journal.record_event(
            "mt5_live_sync_result",
            {
                "symbol": intent.signal.symbol,
                "venue_symbol": self._last_sync.venue_symbol,
                "positions": len(self._last_sync.positions),
                "failures": list(self._last_sync.failures),
            },
        )
        if result.accepted and not self._last_sync.failures:
            if len(self._last_sync.positions) == 1:
                position = self._last_sync.positions[0]
                self._tracked_positions[position.ticket] = TrackedMt5Position(
                    ticket=position.ticket,
                    venue_symbol=position.venue_symbol,
                    signal=intent.signal,
                    stake=intent.stake,
                    volume=position.volume,
                )
            return SubmitResult(
                accepted=True,
                position_id=str(result.order_ticket),
                metadata={"backend": "mt5"},
            )
        self._journal.record_event(
            "mt5_live_fail_closed",
            {
                "symbol": intent.signal.symbol,
                "reason": "entry_sync_failed",
            },
        )
        return SubmitResult(accepted=False, position_id=None, metadata={"backend": "mt5"})

    def on_candle(self, candle: Candle) -> list[TradeOutcome]:
        outcomes: list[TradeOutcome] = []
        for ticket, tracked in list(self._tracked_positions.items()):
            if tracked.signal.symbol != candle.symbol:
                continue
            outcome = self._maybe_close_tracked_position(tracked, candle)
            if outcome is not None:
                outcomes.append(outcome)
                del self._tracked_positions[ticket]
        return outcomes

    def open_positions_count(self) -> int:
        return len(self._last_sync.positions)

    def shutdown(self, candle: Candle | None) -> ShutdownResult:
        del candle
        sync_result = self._sync_positions()
        self._journal.record_event(
            "mt5_live_shutdown_reconcile",
            {
                "symbol": self._symbol,
                "venue_symbol": sync_result.venue_symbol,
                "positions": len(sync_result.positions),
                "failures": list(sync_result.failures),
            },
        )
        if sync_result.failures or len(sync_result.positions) > 1:
            self._journal.record_event(
                "mt5_live_fail_closed",
                {
                    "symbol": self._symbol,
                    "reason": "ambiguous_shutdown_state",
                },
            )
            return ShutdownResult(
                outcomes=(),
                open_positions_before_shutdown=len(sync_result.positions),
                unresolved_positions=len(sync_result.positions),
                finalized=False,
            )
        if len(sync_result.positions) == 1:
            position = sync_result.positions[0]
            close_result = self._close_position(position)
            self._journal.record_event(
                "mt5_close_result",
                {
                    "symbol": self._symbol,
                    "venue_symbol": position.venue_symbol,
                    "ticket": position.ticket,
                    "accepted": close_result.accepted,
                    "retcode": close_result.retcode,
                    "message": close_result.message,
                },
            )
            return ShutdownResult(
                outcomes=(),
                open_positions_before_shutdown=1,
                unresolved_positions=0 if close_result.accepted else 1,
                finalized=close_result.accepted,
            )
        return ShutdownResult(
            outcomes=(),
            open_positions_before_shutdown=len(sync_result.positions),
            unresolved_positions=len(sync_result.positions),
            finalized=True,
        )

    def _place_order(self, intent: OrderIntent, venue_symbol: str | None) -> Mt5OrderResult:
        return place_mt5_order(
            request=Mt5OrderRequest(
                symbol=intent.signal.symbol,
                venue_symbol=venue_symbol or intent.signal.symbol,
                volume=float(intent.metadata.get("volume", 0.2)),
                order_type="BUY" if intent.signal.direction is Direction.LONG else "SELL",
                stop_loss=intent.signal.stop_loss,
                take_profit=intent.signal.take_profit,
                comment="synthetic-trader-mt5-live",
            ),
            mt5_module=self._mt5_module,
        )

    def _sync_positions(self) -> Mt5SyncResult:
        return synchronize_mt5_positions(
            config=self._mt5_config,
            symbol=self._symbol,
            mt5_module=self._mt5_module,
        )

    def _close_position(self, position: Mt5PositionSnapshot) -> Mt5OrderResult:
        return close_mt5_position(
            request=Mt5CloseRequest(
                symbol=position.symbol,
                venue_symbol=position.venue_symbol,
                ticket=position.ticket,
                volume=position.volume,
                direction=position.direction,
            ),
            mt5_module=self._mt5_module,
        )

    def _modify_position(
        self,
        position: TrackedMt5Position,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Mt5OrderResult:
        return modify_mt5_position(
            request=Mt5ModifyRequest(
                symbol=position.signal.symbol,
                venue_symbol=position.venue_symbol,
                ticket=position.ticket,
                stop_loss=stop_loss,
                take_profit=take_profit,
            ),
            mt5_module=self._mt5_module,
        )

    def modify(
        self,
        position_id: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Mt5OrderResult | None:
        # position_id is the order ticket as a string; _tracked_positions is keyed by int ticket.
        try:
            ticket = int(position_id)
        except (ValueError, TypeError):
            return None
        position = self._tracked_positions.get(ticket)
        if position is None:
            return None
        return self._modify_position(position, stop_loss=stop_loss, take_profit=take_profit)

    def _maybe_close_tracked_position(
        self,
        tracked: TrackedMt5Position,
        candle: Candle,
    ) -> TradeOutcome | None:
        signal = tracked.signal
        expired = candle.open_time + candle.timeframe_sec >= signal.snapshot.epoch + signal.horizon_sec
        if signal.direction is Direction.LONG:
            stop_hit = candle.low <= signal.stop_loss
            target_hit = candle.high >= signal.take_profit
        else:
            stop_hit = candle.high >= signal.stop_loss
            target_hit = candle.low <= signal.take_profit

        exit_price: float | None = None
        if stop_hit and target_hit:
            exit_price = signal.stop_loss
        elif stop_hit:
            exit_price = signal.stop_loss
        elif target_hit:
            exit_price = signal.take_profit
        elif expired:
            exit_price = candle.close

        if exit_price is None:
            return None

        close_result = self._close_position(
            Mt5PositionSnapshot(
                symbol=signal.symbol,
                venue_symbol=tracked.venue_symbol,
                ticket=tracked.ticket,
                direction=signal.direction,
                volume=tracked.volume,
                open_price=signal.entry,
                current_price=exit_price,
                broker_time=candle.open_time + candle.timeframe_sec,
            )
        )
        self._journal.record_event(
            "mt5_close_result",
            {
                "symbol": signal.symbol,
                "venue_symbol": tracked.venue_symbol,
                "ticket": tracked.ticket,
                "accepted": close_result.accepted,
                "retcode": close_result.retcode,
                "message": close_result.message,
            },
        )
        if not close_result.accepted:
            self._journal.record_event(
                "mt5_live_fail_closed",
                {
                    "symbol": signal.symbol,
                    "reason": "mid_session_close_failed",
                },
            )
            return None

        risk_distance = abs(signal.entry - signal.stop_loss)
        if signal.direction is Direction.LONG:
            return_r = (exit_price - signal.entry) / risk_distance
        else:
            return_r = (signal.entry - exit_price) / risk_distance
        pnl = tracked.stake * return_r
        return TradeOutcome(
            position_id=str(tracked.ticket),
            symbol=signal.symbol,
            direction=signal.direction,
            entry=signal.entry,
            exit=exit_price,
            pnl=pnl,
            return_r=return_r,
            opened_at=signal.snapshot.epoch,
            closed_at=candle.open_time + candle.timeframe_sec,
            features=signal.snapshot.features,
            won=pnl > 0,
        )


def build_execution_backend(
    *,
    symbol: str,
    venue: Venue,
    live_mode: LiveMode,
    paper_config: PaperExecutionConfig,
    mt5_config: Mt5Config,
    journal,
) -> ExecutionBackend:
    if venue is Venue.MT5 and live_mode is LiveMode.ARMED_LIVE:
        import MetaTrader5  # type: ignore

        return Mt5LiveExecutionBackend(
            mt5_config=mt5_config,
            symbol=symbol,
            journal=journal,
            mt5_module=MetaTrader5,
        )
    del symbol, venue, live_mode, mt5_config, journal
    return SimulatedExecutionBackend(config=paper_config)
