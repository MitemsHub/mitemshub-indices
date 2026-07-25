from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Tick
from synthetic_trader.journal.trade_journal import JournalMetrics, summarize_run_diagnostics
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.reporting.serializers import dump_json_file


@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train_start_epoch: float
    train_end_epoch: float
    test_start_epoch: float
    test_end_epoch: float
    train_ticks: int
    test_ticks: int
    train_trades: int
    test_trades: int
    test_win_rate: float
    test_profit_factor: float
    test_expectancy_r: float
    test_net_pnl: float
    model_version: str


@dataclass(frozen=True)
class WalkForwardReport:
    symbol: str
    folds: tuple[WalkForwardFold, ...]
    aggregate: JournalMetrics
    mean_profit_factor: float
    worst_expectancy_r: float
    total_signals: int
    total_rejected_signals: int
    diagnostics: dict[str, float | int]


def run_walk_forward(
    ticks: list[Tick],
    symbol: str,
    train_ticks: int,
    test_ticks: int,
    step_ticks: int | None = None,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
    config: TraderConfig | None = None,
    model: OnlineLogisticModel | None = None,
    model_output_path: str | Path | None = None,
    model_metadata: dict[str, str] | None = None,
) -> WalkForwardReport:
    if train_ticks <= 0 or test_ticks <= 0:
        raise ValueError("train_ticks and test_ticks must be positive")

    ordered = sorted([tick for tick in ticks if tick.symbol == symbol], key=lambda item: item.epoch)
    step = step_ticks or test_ticks
    if len(ordered) < train_ticks + test_ticks:
        raise ValueError("not enough ticks for a single walk-forward fold")

    cfg = config or TraderConfig.default()
    folds: list[WalkForwardFold] = []
    total_signals = 0
    total_rejected = 0
    start = 0
    index = 1
    final_model: OnlineLogisticModel | None = None
    while start + train_ticks + test_ticks <= len(ordered):
        train_stop = start + train_ticks
        # Keep identical timestamps in the same fold partition so train/test windows
        # remain strictly chronological at the split boundary.
        while train_stop < len(ordered) and ordered[train_stop - 1].epoch == ordered[train_stop].epoch:
            train_stop += 1
        test_stop = train_stop + test_ticks
        if test_stop > len(ordered):
            break

        train_slice = ordered[start:train_stop]
        test_slice = ordered[train_stop:test_stop]
        fold_model = model.clone() if model is not None else OnlineLogisticModel(cfg.model)

        train_result = BacktestEngine(config=cfg, model=fold_model).run_ticks(
            train_slice,
            symbol=symbol,
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            learn=True,
        )
        test_result = BacktestEngine(config=cfg, model=fold_model).run_ticks(
            test_slice,
            symbol=symbol,
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            learn=False,
        )

        total_signals += test_result.signals
        total_rejected += test_result.rejected_signals
        folds.append(
            WalkForwardFold(
                index=index,
                train_start_epoch=train_slice[0].epoch,
                train_end_epoch=train_slice[-1].epoch,
                test_start_epoch=test_slice[0].epoch,
                test_end_epoch=test_slice[-1].epoch,
                train_ticks=len(train_slice),
                test_ticks=len(test_slice),
                train_trades=train_result.metrics.trades,
                test_trades=test_result.metrics.trades,
                test_win_rate=test_result.metrics.win_rate,
                test_profit_factor=test_result.metrics.profit_factor,
                test_expectancy_r=test_result.metrics.expectancy_r,
                test_net_pnl=test_result.metrics.net_pnl,
                model_version=fold_model.version,
            )
        )
        final_model = fold_model
        start += step
        index += 1

    aggregate = _aggregate_folds(folds)
    diagnostics = summarize_run_diagnostics(
        metrics=aggregate,
        signals=total_signals,
        rejected_signals=total_rejected,
        shutdown_closed_trades=0,
        session_resets=0,
    )
    finite_pfs = [fold.test_profit_factor for fold in folds if not math.isinf(fold.test_profit_factor)]
    mean_pf = sum(finite_pfs) / len(finite_pfs) if finite_pfs else float("inf")
    worst_expectancy = min((fold.test_expectancy_r for fold in folds), default=0.0)
    if model_output_path is not None and final_model is not None:
        final_model.save(model_output_path, metadata=model_metadata)
    return WalkForwardReport(
        symbol=symbol,
        folds=tuple(folds),
        aggregate=aggregate,
        mean_profit_factor=mean_pf,
        worst_expectancy_r=worst_expectancy,
        total_signals=total_signals,
        total_rejected_signals=total_rejected,
        diagnostics=diagnostics,
    )


def render_walk_forward_report(report: WalkForwardReport) -> str:
    lines = [
        f"symbol={report.symbol}",
        f"folds={len(report.folds)}",
        f"test_trades={report.aggregate.trades}",
        f"test_win_rate={report.aggregate.win_rate:.2%}",
        f"mean_profit_factor={_format_float(report.mean_profit_factor)}",
        f"test_expectancy_r={report.aggregate.expectancy_r:.3f}",
        f"worst_fold_expectancy_r={report.worst_expectancy_r:.3f}",
        f"test_net_pnl={report.aggregate.net_pnl:.2f}",
        f"test_signals={report.total_signals}",
        f"test_rejected_signals={report.total_rejected_signals}",
    ]
    for fold in report.folds:
        lines.append(
            "fold={index} train_trades={train_trades} test_trades={test_trades} "
            "win_rate={win_rate:.2%} pf={pf} expectancy_r={expectancy:.3f} net_pnl={net_pnl:.2f}".format(
                index=fold.index,
                train_trades=fold.train_trades,
                test_trades=fold.test_trades,
                win_rate=fold.test_win_rate,
                pf=_format_float(fold.test_profit_factor),
                expectancy=fold.test_expectancy_r,
                net_pnl=fold.test_net_pnl,
            )
        )
    return "\n".join(lines)


def save_walk_forward_report(report: WalkForwardReport, output_path: str | Path) -> None:
    dump_json_file(output_path, report)


def _aggregate_folds(folds: list[WalkForwardFold]) -> JournalMetrics:
    total_trades = sum(fold.test_trades for fold in folds)
    total_net = sum(fold.test_net_pnl for fold in folds)
    if total_trades == 0:
        return JournalMetrics(trades=0, win_rate=0.0, profit_factor=0.0, expectancy_r=0.0, net_pnl=0.0)

    weighted_win_rate = sum(fold.test_win_rate * fold.test_trades for fold in folds) / total_trades
    weighted_expectancy = sum(fold.test_expectancy_r * fold.test_trades for fold in folds) / total_trades
    finite_pfs = [fold.test_profit_factor for fold in folds if fold.test_trades and not math.isinf(fold.test_profit_factor)]
    mean_pf = sum(finite_pfs) / len(finite_pfs) if finite_pfs else float("inf")
    return JournalMetrics(
        trades=total_trades,
        win_rate=weighted_win_rate,
        profit_factor=mean_pf,
        expectancy_r=weighted_expectancy,
        net_pnl=total_net,
    )


def _format_float(value: float) -> str:
    return "inf" if math.isinf(value) else f"{value:.2f}"
