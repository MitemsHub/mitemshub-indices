from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import replace
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine, load_ticks_csv
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
from synthetic_trader.data.collector import collect_history
from synthetic_trader.data.tick_store import TickDatasetReport, inspect_ticks
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.live.paper_runner import run_live_paper
from synthetic_trader.monitoring.surface import build_monitor_snapshot, render_monitor_text
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.research.walk_forward import (
    render_walk_forward_report,
    run_walk_forward,
    save_walk_forward_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synth-trader")
    subparsers = parser.add_subparsers(dest="command")

    inspect = subparsers.add_parser("inspect-data", help="inspect tick CSV quality")
    inspect.add_argument("--csv", required=True, help="CSV path with epoch,price columns")
    inspect.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])

    collect = subparsers.add_parser("collect-history", help="download historical Deriv ticks into CSV")
    collect.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    collect.add_argument("--count", type=int, default=5000)
    collect.add_argument("--batch-size", type=int, default=5000)
    collect.add_argument("--output", default="data/ticks.csv")
    collect.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")
    collect.add_argument("--replace", action="store_true", help="replace output instead of appending")

    backtest = subparsers.add_parser("backtest", help="run a candle-based paper backtest from tick CSV")
    backtest.add_argument("--csv", required=True, help="CSV path with epoch,price columns")
    backtest.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    backtest.add_argument("--timeframe", type=int, default=60, help="primary candle timeframe in seconds")
    backtest.add_argument("--higher-timeframe", type=int, default=300, help="higher timeframe in seconds")
    backtest.add_argument("--journal", help="optional JSONL path for signal/outcome journal")
    backtest.add_argument(
        "--model-load",
        "--model-in",
        dest="model_load",
        help="optional trained model JSON to load before the run",
    )
    backtest.add_argument(
        "--model-save",
        "--model-out",
        dest="model_save",
        help="optional path to save the updated model after the run",
    )
    backtest.add_argument("--artifact-output", help="optional path to save the backtest report as JSON")
    backtest.add_argument("--exit-slippage-ticks", type=float, default=0.0)
    backtest.add_argument("--execution-penalty", type=float, default=0.0)

    walk_forward = subparsers.add_parser("walk-forward", help="run chronological train/test validation")
    walk_forward.add_argument("--csv", required=True, help="CSV path with epoch,price columns")
    walk_forward.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    walk_forward.add_argument("--train-ticks", type=int, required=True)
    walk_forward.add_argument("--test-ticks", type=int, required=True)
    walk_forward.add_argument("--step-ticks", type=int)
    walk_forward.add_argument("--timeframe", type=int, default=60)
    walk_forward.add_argument("--higher-timeframe", type=int, default=300)
    walk_forward.add_argument("--model-load", help="optional trained model JSON to load before each fold")
    walk_forward.add_argument("--model-save", help="optional path to save the final trained model after the run")
    walk_forward.add_argument(
        "--artifact-output",
        help="optional path to save the walk-forward report as JSON",
    )

    paper_live = subparsers.add_parser("paper-live", help="run live Deriv data through the paper trader only")
    paper_live.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    paper_live.add_argument("--duration-sec", type=int, default=900)
    paper_live.add_argument("--max-live-ticks", type=int)
    paper_live.add_argument("--warmup-count", type=int, default=5000)
    paper_live.add_argument("--timeframe", type=int, default=60)
    paper_live.add_argument("--higher-timeframe", type=int, default=300)
    paper_live.add_argument("--journal", default="journals/live_paper.jsonl")
    paper_live.add_argument("--ticks-output", help="optional CSV path to store warmup and live ticks")
    paper_live.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")
    paper_live.add_argument("--exit-slippage-ticks", type=float, default=0.0)
    paper_live.add_argument("--execution-penalty", type=float, default=0.0)

    monitor_live = subparsers.add_parser(
        "monitor-live",
        help="render a lightweight paper-live monitor from a summary JSON",
    )
    monitor_live.add_argument("--summary-json", required=True, help="paper-live summary JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "inspect-data":
        ticks = load_ticks_csv(args.csv, default_symbol=args.symbol)
        _print_dataset_report(inspect_ticks(ticks, symbol=args.symbol))
        return 0

    if args.command == "collect-history":
        report = asyncio.run(
            collect_history(
                symbol=args.symbol,
                count=args.count,
                output_path=args.output,
                app_id=args.app_id,
                batch_size=args.batch_size,
                append=not args.replace,
            )
        )
        _print_dataset_report(report)
        print(f"output={Path(args.output)}")
        return 0

    if args.command == "backtest":
        config = _build_runtime_config(args)
        journal = TradeJournal(Path(args.journal)) if args.journal else None
        model = OnlineLogisticModel.load(args.model_load) if args.model_load else None
        ticks = load_ticks_csv(args.csv, default_symbol=args.symbol)
        engine = BacktestEngine(config=config, model=model, journal=journal)
        result = engine.run_ticks(
            ticks,
            symbol=args.symbol,
            timeframe_sec=args.timeframe,
            higher_timeframe_sec=args.higher_timeframe,
            artifact_output_path=args.artifact_output,
        )
        if args.model_save:
            engine.model.save(args.model_save, metadata={"symbol": args.symbol, "command": "backtest"})
        print(f"symbol={args.symbol}")
        print(f"trades={result.metrics.trades}")
        print(f"signals={result.signals}")
        print(f"rejected_signals={result.rejected_signals}")
        print(f"win_rate={result.metrics.win_rate:.2%}")
        print(f"profit_factor={_format_float(result.metrics.profit_factor)}")
        print(f"expectancy_r={result.metrics.expectancy_r:.3f}")
        print(f"net_pnl={result.metrics.net_pnl:.2f}")
        print(f"final_equity={result.final_equity:.2f}")
        print(f"model_version={result.model_version}")
        if args.model_save:
            print(f"model_saved={Path(args.model_save)}")
        return 0

    if args.command == "walk-forward":
        ticks = load_ticks_csv(args.csv, default_symbol=args.symbol)
        report = run_walk_forward(
            ticks=ticks,
            symbol=args.symbol,
            train_ticks=args.train_ticks,
            test_ticks=args.test_ticks,
            step_ticks=args.step_ticks,
            timeframe_sec=args.timeframe,
            higher_timeframe_sec=args.higher_timeframe,
            model=OnlineLogisticModel.load(args.model_load) if args.model_load else None,
            model_output_path=args.model_save,
            model_metadata={"symbol": args.symbol, "command": "walk-forward"} if args.model_save else None,
        )
        if args.artifact_output:
            save_walk_forward_report(report, args.artifact_output)
        print(render_walk_forward_report(report))
        if args.model_save:
            print(f"model_saved={Path(args.model_save)}")
        return 0

    if args.command == "paper-live":
        config = _build_runtime_config(args)
        summary = asyncio.run(
            run_live_paper(
                symbol=args.symbol,
                app_id=args.app_id,
                duration_sec=args.duration_sec,
                max_live_ticks=args.max_live_ticks,
                warmup_count=args.warmup_count,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.higher_timeframe,
                journal_path=args.journal,
                ticks_output_path=args.ticks_output,
                config=config,
            )
        )
        print(f"symbol={summary.symbol}")
        print(f"warmup_ticks={summary.warmup_ticks}")
        print(f"live_ticks={summary.live_ticks}")
        print(f"signals={summary.signals}")
        print(f"approved_signals={summary.approved_signals}")
        print(f"rejected_signals={summary.rejected_signals}")
        print(f"closed_trades={summary.closed_trades}")
        print(f"shutdown_closed_trades={summary.shutdown_closed_trades}")
        print(f"open_positions_before_shutdown={summary.open_positions_before_shutdown}")
        print(f"unresolved_positions={summary.unresolved_positions}")
        print(f"session_resets={summary.session_resets}")
        print(f"finalized={summary.finalized}")
        print(f"final_equity={summary.final_equity:.2f}")
        print(f"model_version={summary.model_version}")
        return 0

    if args.command == "monitor-live":
        summary_payload = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
        snapshot = build_monitor_snapshot(live_summary=summary_payload)
        print(render_monitor_text(snapshot))
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


def _print_dataset_report(report: TickDatasetReport) -> None:
    print(f"ticks={report.ticks}")
    print(f"symbols={','.join(report.symbols)}")
    print(f"duplicates={report.duplicates}")
    print(f"out_of_order={report.out_of_order}")
    print(f"first_epoch={report.first_epoch}")
    print(f"last_epoch={report.last_epoch}")
    print(f"min_price={report.min_price}")
    print(f"max_price={report.max_price}")
    print(f"mean_interval_sec={report.mean_interval_sec:.3f}")
    print(f"max_interval_sec={report.max_interval_sec:.3f}")
    print(f"max_abs_return={report.max_abs_return:.6f}")


def _format_float(value: float) -> str:
    return "inf" if math.isinf(value) else f"{value:.2f}"


def _build_runtime_config(args: argparse.Namespace) -> TraderConfig:
    config = TraderConfig.default()
    return replace(
        config,
        paper=PaperExecutionConfig(
            entry_slippage_ticks=0.0,
            exit_slippage_ticks=getattr(args, "exit_slippage_ticks", 0.0),
            execution_penalty_per_trade=getattr(args, "execution_penalty", 0.0),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
