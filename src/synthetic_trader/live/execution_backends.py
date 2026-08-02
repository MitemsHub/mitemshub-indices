from __future__ import annotations

import logging
import time as _time
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
from synthetic_trader.journal.signal_feedback import SignalFeedbackTracker, make_signal_id


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


@dataclass
class TrailingStopState:
    """Tracks trailing stop state for an open MT5 position.

    The guardian evaluator computes a recommended_stop level on each
    evaluation cycle.  This state tracks the last stop that was
    actually sent to MT5 to avoid redundant modify calls, and records
    the modification history for diagnostics.
    """
    current_stop: float = 0.0
    last_modified_stop: float = 0.0
    modification_count: int = 0
    last_modified_at: float = 0.0  # epoch seconds


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
        self._trailing_stops: dict[int, TrailingStopState] = {}
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
                # Initialize trailing stop state from the signal's stop loss
                # so the first apply_trailing_stop call doesn't trigger a
                # modify from 0.0 (which would always be far away).
                self._trailing_stops[position.ticket] = TrailingStopState(
                    current_stop=intent.signal.stop_loss,
                    last_modified_stop=intent.signal.stop_loss,
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

    # ── Trailing stop auto-modify ──────────────────────────────────
    # When the guardian evaluator computes a recommended_stop level,
    # this method automatically modifies the MT5 order if the new stop
    # is meaningfully different from the current stop.  This prevents
    # winning trades from turning into losers — the #1 cause of
    # premature trade closures on volatile synthetic indices.
    #
    # Called from the snapshot pipeline after guardian evaluation.
    # The recommended_stop comes from GuardianEvaluation.recommended_stop
    # which is already computed in signal_guardian.py._compute_trailing_stop.
    #
    # Threshold: only modify if the new stop is >= 0.5 pips away from the
    # current stop to avoid noise-driven micro-modifications.
    MIN_STOP_MODIFY_DISTANCE_PIPS = 0.5

    def apply_trailing_stop(
        self,
        position_id: str,
        recommended_stop: float,
    ) -> Mt5OrderResult | None:
        """Auto-modify the stop loss when the guardian recommends a new level.

        Only modifies when the new stop is meaningfully different from
        the current stop (>= 0.5 pips).  Records the modification in
        the journal for diagnostics.
        """
        try:
            ticket = int(position_id)
        except (ValueError, TypeError):
            return None

        position = self._tracked_positions.get(ticket)
        if position is None:
            return None

        # Get or create trailing stop state
        ts = self._trailing_stops.get(ticket)
        if ts is None:
            signal_stop = getattr(position.signal, 'stop_loss', 0.0)
            ts = TrailingStopState(current_stop=signal_stop, last_modified_stop=signal_stop)
            self._trailing_stops[ticket] = ts

        # Check if the new stop is meaningfully different
        stop_distance = abs(recommended_stop - ts.current_stop)
        signal = position.signal
        entry = getattr(signal, 'entry', 0.0)
        # Use the signal's pip_size if available, otherwise derive from entry.
        # Synthetic indices like V75 (entry ~1700) use pip_size=0.01, while
        # V100 (entry ~350) also uses 0.01.  The old fallback of 0.0001 was
        # wrong for these instruments.  Derive from entry with a reasonable
        # default: 0.01 for indices above 100, 0.0001 for forex-like prices.
        pip_size = 0.01 if entry > 100 else 0.0001
        pip_value = pip_size

        if stop_distance < self.MIN_STOP_MODIFY_DISTANCE_PIPS * pip_value:
            return None  # too small a change — skip to avoid noise

        # Ensure recommended stop never moves against the trade
        direction = getattr(signal, 'direction', Direction.LONG)
        if direction is Direction.LONG and recommended_stop < ts.current_stop:
            return None  # don't move stop backward for longs
        if direction is Direction.SHORT and recommended_stop > ts.current_stop:
            return None  # don't move stop backward for shorts

        # Execute the modify
        result = self._modify_position(position, stop_loss=recommended_stop)

        if result.accepted:
            old_stop = ts.current_stop
            ts.current_stop = recommended_stop
            ts.last_modified_stop = old_stop
            ts.modification_count += 1
            ts.last_modified_at = _time.time()

            self._journal.record_event(
                "mt5_trailing_stop_modified",
                {
                    "symbol": signal.symbol,
                    "venue_symbol": position.venue_symbol,
                    "ticket": ticket,
                    "old_stop": old_stop,
                    "new_stop": recommended_stop,
                    "stop_distance": stop_distance,
                    "modification_count": ts.modification_count,
                },
            )
            logging.info(
                "[Mt5Backend] trailing stop modified: ticket=%d old=%.5f new=%.5f dist=%.5f count=%d",
                ticket, ts.last_modified_stop, recommended_stop,
                stop_distance, ts.modification_count,
            )
        else:
            self._journal.record_event(
                "mt5_trailing_stop_modify_failed",
                {
                    "symbol": signal.symbol,
                    "ticket": ticket,
                    "recommended_stop": recommended_stop,
                    "retcode": result.retcode,
                    "message": result.message,
                },
            )
            logging.warning(
                "[Mt5Backend] trailing stop modify FAILED: ticket=%d recommended=%.5f retcode=%d msg=%s",
                ticket, recommended_stop, result.retcode, result.message,
            )

        return result

    def get_trailing_stop_state(self, position_id: str) -> TrailingStopState | None:
        """Return the trailing stop state for a position, or None if not tracked."""
        try:
            ticket = int(position_id)
        except (ValueError, TypeError):
            return None
        return self._trailing_stops.get(ticket)

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

        # Clean up trailing stop state when position is closed
        self._trailing_stops.pop(tracked.ticket, None)

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

        # ── Record close outcome in feedback tracker ──────────────
        # When MT5 auto-closes a position (TP/SL hit or expiry),
        # immediately record the outcome so it feeds into calibration
        # without waiting for the 6-hour bulk_resolve timer.
        self._record_feedback_outcome(
            symbol=signal.symbol,
            generated_at=signal.snapshot.epoch,
            outcome="tp_hit" if target_hit else ("sl_hit" if stop_hit else "expired"),
            exit_price=exit_price,
            pnl_pips=exit_price - signal.entry if signal.direction is Direction.LONG else signal.entry - exit_price,
            r_multiple=return_r,
        )

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

    def _record_feedback_outcome(
        self,
        *,
        symbol: str,
        generated_at: float,
        outcome: str,
        exit_price: float,
        pnl_pips: float,
        r_multiple: float,
    ) -> None:
        """Record a trade close outcome in the signal feedback tracker.

        Writes to data/calibration_outcomes.jsonl which the Python snapshot
        pipeline reads on the next refresh to feed into the calibration buffer.
        This closes the MT5 close → learning loop instantly.
        """
        try:
            from pathlib import Path
            import json as _json

            # Build the signal ID matching the frontend's format
            import datetime as _dt
            gen_dt = _dt.datetime.fromtimestamp(generated_at, tz=_dt.timezone.utc)
            gen_iso = gen_dt.strftime("%Y-%m-%dT%H:%M:%S")
            signal_id = make_signal_id(symbol, gen_iso)

            # Determine label: 1 = win, 0 = loss
            label = 1 if outcome in ("tp_hit",) else 0

            # Write to calibration_outcomes.jsonl for the Python backend to pick up
            outcomes_path = Path("data/calibration_outcomes.jsonl")
            outcomes_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "signal_id": signal_id,
                "prediction": 0.5,  # neutral prediction — actual outcome is what matters
                "label": label,
                "outcome": outcome,
                "exit_price": exit_price,
                "pnl_pips": pnl_pips,
                "r_multiple": r_multiple,
                "source": "mt5_close",
                "fed_at": _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with outcomes_path.open("a", encoding="utf-8") as f:
                f.write(_json.dumps(record) + "\n")

            logging.info(
                "[Mt5Backend] feedback outcome recorded: signal=%s outcome=%s r=%.2f",
                signal_id, outcome, r_multiple,
            )
        except Exception as exc:
            logging.debug("[Mt5Backend] failed to record feedback outcome: %s", exc)


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
