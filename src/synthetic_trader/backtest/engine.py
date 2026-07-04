from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from synthetic_trader.config import TraderConfig
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import Candle, Tick, TradeOutcome
from synthetic_trader.execution.paper import PaperBroker
from synthetic_trader.journal.trade_journal import (
    JournalMetrics,
    TradeJournal,
    metrics_from_outcomes,
    summarize_run_diagnostics,
)
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.reporting.serializers import dump_json_file
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine


@dataclass(frozen=True)
class BacktestResult:
    metrics: JournalMetrics
    final_equity: float
    signals: int
    rejected_signals: int
    diagnostics: dict[str, float | int]
    model_version: str


class BacktestEngine:
    def __init__(
        self,
        config: TraderConfig | None = None,
        model: OnlineLogisticModel | None = None,
        journal: TradeJournal | None = None,
    ) -> None:
        self.config = config or TraderConfig.default()
        self.model = model or OnlineLogisticModel(self.config.model)
        self.journal = journal

    def run_ticks(
        self,
        ticks: list[Tick],
        symbol: str,
        timeframe_sec: int | None = None,
        higher_timeframe_sec: int | None = None,
        learn: bool = True,
        artifact_output_path: str | Path | None = None,
    ) -> BacktestResult:
        if symbol not in self.config.symbols:
            raise ValueError(f"unsupported symbol {symbol!r}")

        base_profile = self.config.symbols[symbol]
        timeframe = timeframe_sec or base_profile.default_timeframe_sec
        higher_timeframe = higher_timeframe_sec or max(base_profile.higher_timeframe_sec, timeframe * 5)
        profile = replace(
            base_profile,
            default_timeframe_sec=timeframe,
            higher_timeframe_sec=higher_timeframe,
        )
        config = replace(self.config, symbols={**self.config.symbols, symbol: profile})

        builders = MultiTimeframeCandleBuilder(symbol, [timeframe, higher_timeframe])
        histories: dict[int, list[Candle]] = {timeframe: [], higher_timeframe: []}
        decision_engine = DecisionEngine(config, self.model)
        risk_engine = RiskEngine(config.risk)
        broker = PaperBroker(config.paper)
        outcomes: list[TradeOutcome] = []
        signals = 0
        rejected = 0

        for tick in sorted(ticks, key=lambda item: item.epoch):
            closed = builders.update(tick)
            for tf, candle in closed.items():
                if tf != timeframe:
                    histories[tf].append(candle)

            primary = closed.get(timeframe)
            if primary is None:
                continue

            for outcome in broker.on_candle(primary):
                outcomes.append(outcome)
                risk_engine.register_outcome(outcome)
                self._record_and_learn(outcome, learn=learn)

            histories[timeframe].append(primary)
            report = decision_engine.evaluate(
                symbol=symbol,
                candles=histories[timeframe],
                higher_timeframe_candles=histories[higher_timeframe],
            )
            if report.signal is None:
                if self.journal is not None:
                    self.journal.record_event(
                        "decision_skip",
                        {
                            "symbol": symbol,
                            "epoch": primary.open_time + primary.timeframe_sec,
                            "reasons": list(report.reasons),
                        },
                    )
                continue

            signals += 1
            risk_decision = risk_engine.evaluate(report.signal)
            if not risk_decision.approved or risk_decision.intent is None:
                rejected += 1
                if self.journal is not None:
                    self.journal.record_rejection(
                        symbol=symbol,
                        epoch=report.signal.snapshot.epoch,
                        reasons=risk_decision.reasons,
                        model_version=report.signal.model_version,
                        confidence=report.signal.confidence,
                    )
                continue

            broker.submit(risk_decision.intent)
            risk_engine.register_open()
            if self.journal is not None:
                self.journal.record_signal(report.signal)

        flushed = builders.flush()
        final_primary = flushed.get(timeframe)
        if final_primary is not None:
            for outcome in broker.on_candle(final_primary):
                outcomes.append(outcome)
                risk_engine.register_outcome(outcome)
                self._record_and_learn(outcome, learn=learn)
            for outcome in broker.close_all(final_primary):
                outcomes.append(outcome)
                risk_engine.register_outcome(outcome)
                self._record_and_learn(outcome, learn=learn)

        metrics = metrics_from_outcomes(outcomes)
        diagnostics = summarize_run_diagnostics(
            metrics=metrics,
            signals=signals,
            rejected_signals=rejected,
            shutdown_closed_trades=0,
            session_resets=0,
        )
        result = BacktestResult(
            metrics=metrics,
            final_equity=risk_engine.state.equity,
            signals=signals,
            rejected_signals=rejected,
            diagnostics=diagnostics,
            model_version=self.model.version,
        )
        if artifact_output_path is not None:
            dump_json_file(
                artifact_output_path,
                {
                    **asdict(result),
                    "paper": asdict(config.paper),
                },
            )
        return result

    def _record_and_learn(self, outcome: TradeOutcome, learn: bool) -> None:
        if self.journal is not None:
            self.journal.record_outcome(outcome)
            if learn:
                self.journal.teach(self.model, outcome)
            return
        if not learn:
            return
        label = 1 if outcome.exit > outcome.entry else 0
        self.model.update(dict(outcome.features), label=label, sample_weight=min(2.0, max(0.25, abs(outcome.return_r))))


def load_ticks_csv(path: str | Path, default_symbol: str) -> list[Tick]:
    ticks: list[Tick] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"epoch", "price"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            ticks.append(
                Tick(
                    symbol=row.get("symbol") or default_symbol,
                    epoch=float(row["epoch"]),
                    price=float(row["price"]),
                )
            )
    return ticks
