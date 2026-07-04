from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path

from synthetic_trader.config import TraderConfig
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.data.collector import deriv_credentials_from_env
from synthetic_trader.data.tick_store import append_ticks_csv
from synthetic_trader.domain import Candle
from synthetic_trader.execution.deriv_ws import DerivWebSocketClient
from synthetic_trader.execution.paper import PaperBroker
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine


@dataclass(frozen=True)
class LivePaperSummary:
    symbol: str
    live_ticks: int
    warmup_ticks: int
    signals: int
    approved_signals: int
    rejected_signals: int
    closed_trades: int
    shutdown_closed_trades: int
    open_positions_before_shutdown: int
    unresolved_positions: int
    finalized: bool
    session_resets: int
    final_equity: float
    model_version: str


async def run_live_paper(
    symbol: str,
    app_id: str | None = None,
    token: str | None = None,
    duration_sec: int = 900,
    max_live_ticks: int | None = None,
    warmup_count: int = 5000,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
    journal_path: str | Path = "journals/live_paper.jsonl",
    ticks_output_path: str | Path | None = None,
    config: TraderConfig | None = None,
) -> LivePaperSummary:
    cfg = config or TraderConfig.default()
    if symbol not in cfg.symbols:
        raise ValueError(f"unsupported symbol {symbol!r}")
    profile = replace(
        cfg.symbols[symbol],
        default_timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
    )
    cfg = replace(cfg, symbols={**cfg.symbols, symbol: profile})

    credentials = deriv_credentials_from_env(app_id=app_id, token=token)
    model = OnlineLogisticModel(cfg.model)
    decision_engine = DecisionEngine(cfg, model)
    risk_engine = RiskEngine(cfg.risk)
    broker = PaperBroker()
    journal = TradeJournal(journal_path)
    builders = MultiTimeframeCandleBuilder(symbol, [timeframe_sec, higher_timeframe_sec])
    histories: dict[int, list[Candle]] = {timeframe_sec: [], higher_timeframe_sec: []}

    live_ticks = 0
    warmup_ticks = 0
    signals = 0
    approved = 0
    rejected = 0
    closed_trades = 0
    session_resets = 0

    async with DerivWebSocketClient(credentials) as client:
        if warmup_count > 0:
            warmup = await client.ticks_history(symbol=symbol, count=warmup_count)
            warmup_ticks = len(warmup)
            if ticks_output_path is not None:
                append_ticks_csv(ticks_output_path, warmup)
            for tick in warmup:
                risk_engine.sync_session_day(_day_bucket(tick.epoch))
                closed = builders.update(tick)
                _store_closed_candles(closed, histories)

        started = time.monotonic()
        async for tick in client.subscribe_ticks(symbol):
            if duration_sec > 0 and time.monotonic() - started >= duration_sec:
                break
            live_ticks += 1
            if risk_engine.sync_session_day(_day_bucket(tick.epoch)):
                session_resets += 1
                journal.record_event(
                    "session_reset",
                    {
                        "symbol": symbol,
                        "epoch": tick.epoch,
                        "session_day": _day_bucket(tick.epoch),
                    },
                )
            if ticks_output_path is not None:
                append_ticks_csv(ticks_output_path, [tick])

            closed = builders.update(tick)
            primary = closed.get(timeframe_sec)
            _store_closed_candles(closed, histories)
            if primary is not None:
                for outcome in broker.on_candle(primary):
                    closed_trades += 1
                    risk_engine.register_outcome(outcome)
                    journal.record_outcome(outcome)
                    journal.teach(model, outcome)

                report = decision_engine.evaluate(
                    symbol=symbol,
                    candles=histories[timeframe_sec],
                    higher_timeframe_candles=histories[higher_timeframe_sec],
                )
                if report.signal is None:
                    journal.record_event(
                        "decision_skip",
                        {
                            "symbol": symbol,
                            "epoch": primary.open_time + primary.timeframe_sec,
                            "reasons": list(report.reasons),
                        },
                    )
                else:
                    signals += 1
                    risk_decision = risk_engine.evaluate(report.signal)
                    if risk_decision.approved and risk_decision.intent is not None:
                        broker.submit(risk_decision.intent)
                        risk_engine.register_open()
                        journal.record_signal(report.signal)
                        approved += 1
                    else:
                        rejected += 1
                        journal.record_rejection(
                            symbol=symbol,
                            epoch=report.signal.snapshot.epoch,
                            reasons=risk_decision.reasons,
                            model_version=report.signal.model_version,
                            confidence=report.signal.confidence,
                        )

            if max_live_ticks is not None and live_ticks >= max_live_ticks:
                break

    shutdown_closed_trades = 0
    open_positions_before_shutdown = len(broker.positions)
    unresolved_positions = open_positions_before_shutdown
    finalized = False

    # Finalize any in-progress candle state so the end-of-run accounting is explicit.
    flushed = builders.flush()
    final_primary = flushed.get(timeframe_sec)
    _store_closed_candles(flushed, histories)
    if final_primary is not None:
        for outcome in broker.on_candle(final_primary):
            closed_trades += 1
            shutdown_closed_trades += 1
            risk_engine.register_outcome(outcome)
            journal.record_outcome(outcome)
            journal.record_event(
                "shutdown_flush_close",
                {
                    "symbol": outcome.symbol,
                    "position_id": outcome.position_id,
                    "epoch": final_primary.open_time + final_primary.timeframe_sec,
                },
            )
            journal.teach(model, outcome)

        for outcome in broker.close_all(final_primary):
            closed_trades += 1
            shutdown_closed_trades += 1
            risk_engine.register_outcome(outcome)
            journal.record_outcome(outcome)
            journal.record_event(
                "shutdown_forced_close",
                {
                    "symbol": outcome.symbol,
                    "position_id": outcome.position_id,
                    "epoch": final_primary.open_time + final_primary.timeframe_sec,
                },
            )
            journal.teach(model, outcome)

    unresolved_positions = len(broker.positions)
    finalized = True
    journal.record_event(
        "shutdown_summary",
        {
            "symbol": symbol,
            "live_ticks": live_ticks,
            "shutdown_closed_trades": shutdown_closed_trades,
            "open_positions_before_shutdown": open_positions_before_shutdown,
            "unresolved_positions": unresolved_positions,
            "session_resets": session_resets,
            "finalized": finalized,
            "final_equity": risk_engine.state.equity,
        },
    )

    return LivePaperSummary(
        symbol=symbol,
        live_ticks=live_ticks,
        warmup_ticks=warmup_ticks,
        signals=signals,
        approved_signals=approved,
        rejected_signals=rejected,
        closed_trades=closed_trades,
        shutdown_closed_trades=shutdown_closed_trades,
        open_positions_before_shutdown=open_positions_before_shutdown,
        unresolved_positions=unresolved_positions,
        finalized=finalized,
        session_resets=session_resets,
        final_equity=risk_engine.state.equity,
        model_version=model.version,
    )


def _store_closed_candles(closed: dict[int, Candle], histories: dict[int, list[Candle]]) -> None:
    for timeframe, candle in closed.items():
        histories.setdefault(timeframe, []).append(candle)


def _day_bucket(epoch: float) -> int:
    return int(epoch // 86400)
