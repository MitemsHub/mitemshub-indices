from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine, load_ticks_csv
from synthetic_trader.config import LiveMode, Mt5Config, PaperExecutionConfig, TraderConfig, Venue
from synthetic_trader.data.collector import collect_history
from synthetic_trader.data.tick_store import TickDatasetReport, inspect_ticks
from synthetic_trader.data.migrate_csv import migrate_legacy_csv
from synthetic_trader.execution.mt5 import (
    Mt5OrderRequest,
    evaluate_mt5_runtime,
    mt5_dependency_available,
    reconcile_mt5_positions,
    synchronize_mt5_positions,
)
from synthetic_trader.journal.trade_journal import TradeJournal
from synthetic_trader.live.calibration_logger import append_call_record, build_call_record
from synthetic_trader.live.calibration_scorer import run_score_unresolved_records_from_market
from synthetic_trader.live.market_snapshot import (
    build_live_watch_review_snapshot,
    render_live_snapshot_text,
    render_live_watch_alert_text,
    render_live_watch_review_text,
    run_live_snapshot,
    run_live_watch,
)
from synthetic_trader.live.paper_runner import run_live_paper
from synthetic_trader.live.supervised_live import (
    build_live_readiness_report,
    execute_supervised_mt5_close,
    execute_supervised_mt5_modify,
    execute_supervised_mt5_order,
    run_supervised_live_session,
)
from synthetic_trader.monitoring.surface import (
    build_monitor_snapshot,
    build_mt5_monitor_snapshot,
    build_rollout_status_snapshot,
    build_validation_snapshot,
    render_monitor_text,
    render_mt5_monitor_text,
    render_rollout_status_text,
    render_validation_text,
)
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.reporting.serializers import dump_json_file
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

    prepare_live_model = subparsers.add_parser(
        "prepare-live-model",
        help="collect history and build a seeded model artifact for live dry-run",
    )
    prepare_live_model.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    prepare_live_model.add_argument("--count", type=int, default=5000)
    prepare_live_model.add_argument("--batch-size", type=int, default=5000)
    prepare_live_model.add_argument("--output", help="optional CSV output path for collected ticks")
    prepare_live_model.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")
    prepare_live_model.add_argument("--replace", action="store_true", help="replace output instead of appending")
    prepare_live_model.add_argument("--timeframe", type=int, default=60, help="primary candle timeframe in seconds")
    prepare_live_model.add_argument(
        "--higher-timeframe",
        type=int,
        default=300,
        help="higher timeframe in seconds",
    )
    prepare_live_model.add_argument("--model-load", help="optional trained model JSON to load before the run")
    prepare_live_model.add_argument("--model-save", help="optional path to save the seeded model artifact")
    prepare_live_model.add_argument("--artifact-output", help="optional path to save the backtest report as JSON")
    prepare_live_model.add_argument("--exit-slippage-ticks", type=float, default=0.0)
    prepare_live_model.add_argument("--execution-penalty", type=float, default=0.0)

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

    paper_live = subparsers.add_parser("paper-live", help="run live venue data through the paper trader only")
    paper_live.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    paper_live.add_argument("--venue", default=Venue.DERIV.value, choices=[venue.value for venue in Venue])
    paper_live.add_argument("--duration-sec", type=int, default=900)
    paper_live.add_argument("--max-live-ticks", type=int)
    paper_live.add_argument("--warmup-count", type=int, default=5000)
    paper_live.add_argument("--timeframe", type=int, default=60)
    paper_live.add_argument("--higher-timeframe", type=int, default=300)
    paper_live.add_argument("--model-load", help="optional trained model JSON to load before the run")
    paper_live.add_argument("--journal", default="journals/live_paper.jsonl")
    paper_live.add_argument("--ticks-output", help="optional CSV path to store warmup and live ticks")
    paper_live.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")
    paper_live.add_argument("--api-token", help="override Deriv API token for supervised live")
    paper_live.add_argument(
        "--live-mode",
        default=LiveMode.PAPER.value,
        choices=[mode.value for mode in LiveMode],
        help="execution mode for supervised live gating",
    )
    paper_live.add_argument(
        "--armed-live",
        action="store_true",
        help="explicit operator confirmation required for armed-live mode",
    )
    paper_live.add_argument("--mt5-server")
    paper_live.add_argument("--mt5-login")
    paper_live.add_argument("--mt5-password")
    paper_live.add_argument("--mt5-terminal-path")
    paper_live.add_argument("--mt5-symbol", help="venue symbol alias for the selected project symbol")
    paper_live.add_argument("--exit-slippage-ticks", type=float, default=0.0)
    paper_live.add_argument("--execution-penalty", type=float, default=0.0)
    paper_live.add_argument(
        "--latency-profile",
        action="store_true",
        help="print shared live-path latency summary",
    )

    live_snapshot = subparsers.add_parser(
        "live-snapshot",
        help="render a read-only live market snapshot for a symbol",
    )
    live_snapshot.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    live_snapshot.add_argument("--warmup-count", type=int, default=5000)
    live_snapshot.add_argument("--timeframe", type=int, default=60)
    live_snapshot.add_argument("--higher-timeframe", type=int, default=300)
    live_snapshot.add_argument("--max-live-ticks", type=int, default=90)
    live_snapshot.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")

    live_watch = subparsers.add_parser(
        "live-watch",
        help="monitor a symbol and emit read-only operator calls on meaningful change",
    )
    live_watch.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    live_watch.add_argument("--warmup-count", type=int, default=5000)
    live_watch.add_argument("--timeframe", type=int, default=60)
    live_watch.add_argument("--higher-timeframe", type=int, default=300)
    live_watch.add_argument("--journal", default="journals/live_watch_alerts.jsonl")
    live_watch.add_argument(
        "--emit-initial",
        action="store_true",
        help="emit the current baseline market state immediately before waiting for change",
    )
    live_watch.add_argument("--max-alerts", type=int)
    live_watch.add_argument("--max-minutes", type=int)
    live_watch.add_argument("--max-reconnects", type=int, default=5)
    live_watch.add_argument("--reconnect-backoff-sec", type=int, default=1)
    live_watch.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")

    live_watch_review = subparsers.add_parser(
        "live-watch-review",
        help="review live-watch calls, suppression, and transport health from the journal",
    )
    live_watch_review.add_argument("--journal", default="journals/live_watch_alerts.jsonl")
    live_watch_review.add_argument("--symbol", choices=["R_75", "R_100"])
    live_watch_review.add_argument("--limit", type=int, default=5)
    live_watch_review.add_argument("--call", dest="call_filter")
    live_watch_review.add_argument("--valid-only", action="store_true")

    log_live_call = subparsers.add_parser(
        "log-live-call",
        help="append one live calibration call record",
    )
    log_live_call.add_argument("--symbol", required=True, choices=["R_75", "R_100"])
    log_live_call.add_argument("--payload-json", required=True)
    log_live_call.add_argument("--output", default="journals/live_calibration_calls.jsonl")

    score_live_calibration = subparsers.add_parser(
        "score-live-calibration",
        help="inspect live calibration calls pending scoring",
    )
    score_live_calibration.add_argument("--calls-journal", default="journals/live_calibration_calls.jsonl")
    score_live_calibration.add_argument("--output", default="journals/live_calibration_outcomes.jsonl")
    score_live_calibration.add_argument("--symbol", choices=["R_75", "R_100"])
    score_live_calibration.add_argument("--window-minutes", type=int)
    score_live_calibration.add_argument("--now", help="optional ISO timestamp for deterministic scoring")

    mt5_live_order = subparsers.add_parser(
        "mt5-live-order",
        help="run terminal-backed supervised MT5 order placement",
    )
    mt5_live_order.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_live_order.add_argument(
        "--live-mode",
        default=LiveMode.DRY_RUN_LIVE.value,
        choices=[mode.value for mode in LiveMode],
        help="execution mode for supervised MT5 order placement",
    )
    mt5_live_order.add_argument(
        "--armed-live",
        action="store_true",
        help="explicit operator confirmation required for armed-live mode",
    )
    mt5_live_order.add_argument("--mt5-server", required=True)
    mt5_live_order.add_argument("--mt5-login", required=True)
    mt5_live_order.add_argument("--mt5-password", required=True)
    mt5_live_order.add_argument("--mt5-terminal-path")
    mt5_live_order.add_argument("--mt5-symbol", required=True)
    mt5_live_order.add_argument("--volume", type=float, required=True)
    mt5_live_order.add_argument("--journal", help="optional MT5 analytics journal path")

    mt5_sync = subparsers.add_parser(
        "mt5-sync",
        help="synchronize MT5 lifecycle state",
    )
    mt5_sync.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_sync.add_argument("--mt5-server", required=True)
    mt5_sync.add_argument("--mt5-login", required=True)
    mt5_sync.add_argument("--mt5-password", required=True)
    mt5_sync.add_argument("--mt5-terminal-path")
    mt5_sync.add_argument("--mt5-symbol", required=True)
    mt5_sync.add_argument("--journal", help="optional MT5 analytics journal path")

    mt5_reconcile = subparsers.add_parser(
        "mt5-reconcile",
        help="reconcile MT5 lifecycle state",
    )
    mt5_reconcile.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_reconcile.add_argument("--ticket", type=int)
    mt5_reconcile.add_argument("--mt5-server", required=True)
    mt5_reconcile.add_argument("--mt5-login", required=True)
    mt5_reconcile.add_argument("--mt5-password", required=True)
    mt5_reconcile.add_argument("--mt5-terminal-path")
    mt5_reconcile.add_argument("--mt5-symbol", required=True)
    mt5_reconcile.add_argument("--journal", help="optional MT5 analytics journal path")

    mt5_close = subparsers.add_parser(
        "mt5-close",
        help="run supervised MT5 close handling",
    )
    mt5_close.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_close.add_argument(
        "--live-mode",
        default=LiveMode.DRY_RUN_LIVE.value,
        choices=[mode.value for mode in LiveMode],
        help="execution mode for supervised MT5 close handling",
    )
    mt5_close.add_argument(
        "--armed-live",
        action="store_true",
        help="explicit operator confirmation required for armed-live mode",
    )
    mt5_close.add_argument("--ticket", type=int)
    mt5_close.add_argument("--mt5-server", required=True)
    mt5_close.add_argument("--mt5-login", required=True)
    mt5_close.add_argument("--mt5-password", required=True)
    mt5_close.add_argument("--mt5-terminal-path")
    mt5_close.add_argument("--mt5-symbol", required=True)
    mt5_close.add_argument("--journal", help="optional MT5 analytics journal path")

    mt5_modify = subparsers.add_parser(
        "mt5-modify",
        help="run supervised MT5 modify handling",
    )
    mt5_modify.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_modify.add_argument("--ticket", type=int)
    mt5_modify.add_argument(
        "--live-mode",
        default=LiveMode.DRY_RUN_LIVE.value,
        choices=[mode.value for mode in LiveMode],
        help="execution mode for supervised MT5 modify handling",
    )
    mt5_modify.add_argument(
        "--armed-live",
        action="store_true",
        help="explicit operator confirmation required for armed-live mode",
    )
    mt5_modify.add_argument("--stop-loss", type=float)
    mt5_modify.add_argument("--take-profit", type=float)
    mt5_modify.add_argument("--mt5-server", required=True)
    mt5_modify.add_argument("--mt5-login", required=True)
    mt5_modify.add_argument("--mt5-password", required=True)
    mt5_modify.add_argument("--mt5-terminal-path")
    mt5_modify.add_argument("--mt5-symbol", required=True)
    mt5_modify.add_argument("--journal", help="optional MT5 analytics journal path")

    monitor_live = subparsers.add_parser(
        "monitor-live",
        help="render a lightweight paper-live monitor from a summary JSON",
    )
    monitor_live.add_argument("--summary-json", required=True, help="paper-live summary JSON path")

    mt5_monitor = subparsers.add_parser(
        "mt5-monitor",
        help="render a read-only MT5 monitor from journal analytics",
    )
    mt5_monitor.add_argument("--journal", required=True, help="MT5 analytics journal JSONL path")
    mt5_monitor.add_argument("--symbol", help="optional MT5 symbol filter")

    mt5_rollout_check = subparsers.add_parser(
        "mt5-rollout-check",
        help="render a read-only MT5 rollout preflight summary",
    )
    mt5_rollout_check.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    mt5_rollout_check.add_argument(
        "--live-mode",
        default=LiveMode.DRY_RUN_LIVE.value,
        choices=[LiveMode.DRY_RUN_LIVE.value, LiveMode.ARMED_LIVE.value],
    )
    mt5_rollout_check.add_argument("--mt5-server", required=True)
    mt5_rollout_check.add_argument("--mt5-login", required=True)
    mt5_rollout_check.add_argument("--mt5-password", required=True)
    mt5_rollout_check.add_argument("--mt5-terminal-path")
    mt5_rollout_check.add_argument("--mt5-symbol", required=True)
    mt5_rollout_check.add_argument("--validation-json", help="optional validation artifact JSON path")
    mt5_rollout_check.add_argument("--journal", help="optional MT5 analytics journal JSONL path")
    mt5_rollout_check.add_argument("--artifact-output", help="optional rollout snapshot JSON output path")

    validate_system = subparsers.add_parser(
        "validate-system",
        help="run final validation and benchmarking summary",
    )
    validate_system.add_argument("--symbol", required=True, help="symbol to validate")
    validate_system.add_argument("--artifact-output", help="optional validation JSON output path")

    backtest_synth = subparsers.add_parser(
        "backtest-synth",
        help="run strategy against synthetic data to detect curve-fitting",
    )
    backtest_synth.add_argument(
        "--symbol", default="SYN100",
        help="symbol: Deriv (R_75, R_100, V75, V100) or Blueberry (SYN50/75/100, SURGE50/75/100, DROP50/75/100, LEAP50/75/100)",
    )
    backtest_synth.add_argument("--episodes", type=int, default=20, help="number of independent synthetic datasets")
    backtest_synth.add_argument("--ticks", type=int, default=5000, help="ticks per episode")
    backtest_synth.add_argument("--seed", type=int, default=42, help="base seed for reproducibility")
    backtest_synth.add_argument("--no-learn", action="store_true", help="disable online learning during backtest")
    backtest_synth.add_argument(
        "--prop-firm",
        choices=["blueberry_2step", "blueberry_synthetic", "none"],
        default="none",
        help="enforce prop firm rules during backtest (default: none)",
    )
    backtest_synth.add_argument("--artifact-output", help="optional path to save the report as JSON")

    collect_ticks = subparsers.add_parser(
        "collect-ticks",
        help="collect real tick data from MT5 for EGARCH calibration",
    )
    collect_ticks.add_argument("--symbol", required=True, help="symbol (e.g., SYN100, R_100)")
    collect_ticks.add_argument("--venue-symbol", help="MT5 venue symbol (auto-detected if omitted)")
    collect_ticks.add_argument("--duration", type=int, default=300, help="collection duration in seconds")
    collect_ticks.add_argument("--max-ticks", type=int, default=10000, help="maximum ticks to collect")
    collect_ticks.add_argument("--output", default="data/calibration_ticks.csv", help="CSV output path")
    collect_ticks.add_argument("--mt5-server")
    collect_ticks.add_argument("--mt5-login", type=int)
    collect_ticks.add_argument("--mt5-password")
    collect_ticks.add_argument("--mt5-terminal-path")

    calibrate_egarch = subparsers.add_parser(
        "calibrate-egarch",
        help="fit EGARCH(1,1) parameters to collected tick data",
    )
    calibrate_egarch.add_argument("--csv", required=True, help="tick CSV path")
    calibrate_egarch.add_argument("--symbol", required=True, help="symbol name")
    calibrate_egarch.add_argument("--output", help="optional JSON output path for fitted parameters")
    calibrate_egarch.add_argument("--apply", action="store_true", help="apply fitted params to synthetic generator config")

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

    if args.command == "prepare-live-model":
        output_path = Path(args.output) if args.output else Path(f"data/{args.symbol.lower()}_ticks.csv")
        model_path = (
            Path(args.model_save)
            if args.model_save
            else Path(f"artifacts/{args.symbol.lower()}_live_seed_model.json")
        )
        report = asyncio.run(
            collect_history(
                symbol=args.symbol,
                count=args.count,
                output_path=str(output_path),
                app_id=args.app_id,
                batch_size=args.batch_size,
                append=not args.replace,
            )
        )
        _print_dataset_report(report)
        print(f"output={output_path}")

        config = _build_runtime_config(args)
        model = OnlineLogisticModel.load(args.model_load) if args.model_load else None
        ticks = load_ticks_csv(output_path, default_symbol=args.symbol)
        engine = BacktestEngine(config=config, model=model)
        result = engine.run_ticks(
            ticks,
            symbol=args.symbol,
            timeframe_sec=args.timeframe,
            higher_timeframe_sec=args.higher_timeframe,
            artifact_output_path=args.artifact_output,
        )
        engine.model.save(model_path, metadata={"symbol": args.symbol, "command": "prepare-live-model"})
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
        print(f"model_saved={model_path}")
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
        venue = Venue(args.venue)
        mode = LiveMode(args.live_mode)
        mt5_config = _build_mt5_config(args)
        runtime_status = None
        if venue is Venue.MT5 and mode is LiveMode.ARMED_LIVE:
            runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
        readiness = build_live_readiness_report(
            venue=venue,
            mode=mode,
            symbol=args.symbol,
            app_id=args.app_id,
            token=args.api_token,
            armed=args.armed_live,
            supported_symbols=set(TraderConfig.default().symbols),
            mt5_config=mt5_config,
            mt5_dependency_ready=mt5_dependency_available() if venue is Venue.MT5 else False,
            mt5_runtime_status=runtime_status,
        )
        print(f"live_mode={mode.value}")
        print(f"readiness_ok={readiness.ready}")
        if readiness.failures:
            print(f"readiness_failures={','.join(readiness.failures)}")
        if mode is not LiveMode.PAPER and not readiness.ready:
            return 1

        config = _build_runtime_config(args)
        run_kwargs = dict(
            symbol=args.symbol,
            app_id=args.app_id,
            token=args.api_token,
            duration_sec=args.duration_sec,
            max_live_ticks=args.max_live_ticks,
            warmup_count=args.warmup_count,
            timeframe_sec=args.timeframe,
            higher_timeframe_sec=args.higher_timeframe,
            journal_path=args.journal,
            ticks_output_path=args.ticks_output,
            config=config,
            venue=venue,
            live_mode=mode,
            model=OnlineLogisticModel.load(args.model_load) if args.model_load else None,
        )
        latency_profile = None
        if mode is LiveMode.PAPER:
            summary = asyncio.run(run_live_paper(**run_kwargs))
        elif args.latency_profile:
            summary, latency_profile = asyncio.run(
                run_supervised_live_session(
                    venue=venue,
                    mode=mode,
                    readiness_ok=readiness.ready,
                    dry_run_runner=lambda: run_live_paper(**run_kwargs),
                    armed_runner=lambda: run_live_paper(**run_kwargs),
                    capture_latency=True,
                )
            )
        else:
            summary = asyncio.run(
                run_supervised_live_session(
                    venue=venue,
                    mode=mode,
                    readiness_ok=readiness.ready,
                    dry_run_runner=lambda: run_live_paper(**run_kwargs),
                    armed_runner=lambda: run_live_paper(**run_kwargs),
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
        if latency_profile is not None:
            print(_render_latency_profile(latency_profile))
        return 0

    if args.command == "mt5-live-order":
        journal = _build_mt5_journal(args)
        mode = LiveMode(args.live_mode)
        mt5_config = _build_mt5_config(args)
        runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
        journal.record_mt5_runtime_summary(
            symbol=args.symbol,
            venue_symbol=runtime_status.venue_symbol,
            ready=runtime_status.ready,
            failures=runtime_status.failures,
        )
        readiness = build_live_readiness_report(
            venue=Venue.MT5,
            mode=mode,
            symbol=args.symbol,
            app_id=None,
            token=None,
            armed=args.armed_live,
            supported_symbols=set(TraderConfig.default().symbols),
            mt5_config=mt5_config,
            mt5_dependency_ready=mt5_dependency_available(),
            mt5_runtime_status=runtime_status,
        )
        _print_mt5_summary(
            "mt5-live-order",
            readiness_ok=readiness.ready,
            venue_symbol=runtime_status.venue_symbol,
            failures=",".join(readiness.failures),
        )
        print(f"live_mode={mode.value}")
        print(f"readiness_ok={readiness.ready}")
        if readiness.failures:
            print(f"readiness_failures={','.join(readiness.failures)}")
        if not readiness.ready:
            return 1

        mt5_module = _load_mt5_module() if mode is LiveMode.ARMED_LIVE else None
        result = execute_supervised_mt5_order(
            mode=mode,
            readiness_ok=readiness.ready,
            request=Mt5OrderRequest(
                symbol=args.symbol,
                venue_symbol=runtime_status.venue_symbol or args.mt5_symbol,
                volume=args.volume,
                order_type="BUY",
                comment="synthetic-trader-mt5",
            ),
            mt5_module=mt5_module,
        )
        if isinstance(result, str):
            print(f"order_result={result}")
            return 0
        print(f"order_accepted={result.accepted}")
        print(f"order_ticket={result.order_ticket}")
        print(f"deal_ticket={result.deal_ticket}")
        print(f"retcode={result.retcode}")
        print(f"message={result.message}")
        return 0

    if args.command == "mt5-sync":
        journal = _build_mt5_journal(args)
        mt5_config = _build_mt5_config(args)
        sync_result = synchronize_mt5_positions(
            config=mt5_config,
            symbol=args.symbol,
            mt5_module=_load_mt5_module(),
        )
        journal.record_mt5_sync_summary(
            symbol=args.symbol,
            venue_symbol=sync_result.venue_symbol,
            positions=len(sync_result.positions),
            failures=sync_result.failures,
        )
        _print_mt5_summary(
            "mt5-sync",
            positions=len(sync_result.positions),
            failures=",".join(sync_result.failures),
        )
        print(f"positions={len(sync_result.positions)}")
        if sync_result.failures:
            print(f"sync_failures={','.join(sync_result.failures)}")
            return 1
        return 0

    if args.command == "mt5-reconcile":
        journal = _build_mt5_journal(args)
        mt5_config = _build_mt5_config(args)
        reconcile_result = reconcile_mt5_positions(
            config=mt5_config,
            symbol=args.symbol,
            ticket=args.ticket,
            mt5_module=_load_mt5_module(),
        )
        journal.record_mt5_reconcile_summary(
            symbol=args.symbol,
            target_ticket=reconcile_result.target_ticket,
            actionable=reconcile_result.actionable,
            failures=reconcile_result.failures,
        )
        _print_mt5_summary(
            "mt5-reconcile",
            actionable=reconcile_result.actionable,
            target_ticket=reconcile_result.target_ticket,
            failures=",".join(reconcile_result.failures),
        )
        print(f"actionable={reconcile_result.actionable}")
        print(f"target_ticket={reconcile_result.target_ticket}")
        if reconcile_result.failures:
            print(f"reconcile_failures={','.join(reconcile_result.failures)}")
            return 1
        return 0

    if args.command == "mt5-close":
        journal = _build_mt5_journal(args)
        mode = LiveMode(args.live_mode)
        mt5_config = _build_mt5_config(args)
        runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
        journal.record_mt5_runtime_summary(
            symbol=args.symbol,
            venue_symbol=runtime_status.venue_symbol,
            ready=runtime_status.ready,
            failures=runtime_status.failures,
        )
        readiness = build_live_readiness_report(
            venue=Venue.MT5,
            mode=mode,
            symbol=args.symbol,
            app_id=None,
            token=None,
            armed=args.armed_live,
            supported_symbols=set(TraderConfig.default().symbols),
            mt5_config=mt5_config,
            mt5_dependency_ready=mt5_dependency_available(),
            mt5_runtime_status=runtime_status,
        )
        _print_mt5_summary(
            "mt5-close",
            readiness_ok=readiness.ready,
            venue_symbol=runtime_status.venue_symbol,
            failures=",".join(readiness.failures),
        )
        print(f"live_mode={mode.value}")
        print(f"readiness_ok={readiness.ready}")
        if readiness.failures:
            print(f"readiness_failures={','.join(readiness.failures)}")
        if not readiness.ready:
            return 1

        mt5_module = _load_mt5_module()
        sync_result = synchronize_mt5_positions(
            config=mt5_config,
            symbol=args.symbol,
            mt5_module=mt5_module,
        )
        journal.record_mt5_sync_summary(
            symbol=args.symbol,
            venue_symbol=sync_result.venue_symbol,
            positions=len(sync_result.positions),
            failures=sync_result.failures,
        )
        _print_mt5_summary(
            "mt5-close",
            positions=len(sync_result.positions),
            sync_failures=",".join(sync_result.failures),
        )
        print(f"positions={len(sync_result.positions)}")
        if sync_result.failures:
            print(f"sync_failures={','.join(sync_result.failures)}")
            return 1

        result = execute_supervised_mt5_close(
            mode=mode,
            readiness_ok=readiness.ready,
            sync_result=sync_result,
            ticket=args.ticket,
            mt5_module=mt5_module,
        )
        if isinstance(result, str):
            print(f"close_result={result}")
            return 0
        close_ticket = args.ticket if args.ticket is not None else sync_result.positions[0].ticket
        journal.record_mt5_close_result(
            symbol=args.symbol,
            venue_symbol=result.venue_symbol,
            ticket=close_ticket,
            accepted=result.accepted,
            retcode=result.retcode,
            message=result.message,
        )
        _print_mt5_summary(
            "mt5-close",
            close_accepted=result.accepted,
            order_ticket=result.order_ticket,
            deal_ticket=result.deal_ticket,
            retcode=result.retcode,
        )
        print(f"close_accepted={result.accepted}")
        print(f"order_ticket={result.order_ticket}")
        print(f"deal_ticket={result.deal_ticket}")
        print(f"retcode={result.retcode}")
        print(f"message={result.message}")
        return 0

    if args.command == "mt5-modify":
        journal = _build_mt5_journal(args)
        mode = LiveMode(args.live_mode)
        mt5_config = _build_mt5_config(args)
        runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
        journal.record_mt5_runtime_summary(
            symbol=args.symbol,
            venue_symbol=runtime_status.venue_symbol,
            ready=runtime_status.ready,
            failures=runtime_status.failures,
        )
        readiness = build_live_readiness_report(
            venue=Venue.MT5,
            mode=mode,
            symbol=args.symbol,
            app_id=None,
            token=None,
            armed=args.armed_live,
            supported_symbols=set(TraderConfig.default().symbols),
            mt5_config=mt5_config,
            mt5_dependency_ready=mt5_dependency_available(),
            mt5_runtime_status=runtime_status,
        )
        _print_mt5_summary(
            "mt5-modify",
            readiness_ok=readiness.ready,
            venue_symbol=runtime_status.venue_symbol,
            failures=",".join(readiness.failures),
        )
        print(f"live_mode={mode.value}")
        print(f"readiness_ok={readiness.ready}")
        if readiness.failures:
            print(f"readiness_failures={','.join(readiness.failures)}")
        if not readiness.ready:
            return 1

        mt5_module = _load_mt5_module()
        reconcile_result = reconcile_mt5_positions(
            config=mt5_config,
            symbol=args.symbol,
            ticket=args.ticket,
            mt5_module=mt5_module,
        )
        journal.record_mt5_reconcile_summary(
            symbol=args.symbol,
            target_ticket=reconcile_result.target_ticket,
            actionable=reconcile_result.actionable,
            failures=reconcile_result.failures,
        )
        _print_mt5_summary(
            "mt5-modify",
            actionable=reconcile_result.actionable,
            target_ticket=reconcile_result.target_ticket,
            reconcile_failures=",".join(reconcile_result.failures),
        )
        print(f"actionable={reconcile_result.actionable}")
        print(f"target_ticket={reconcile_result.target_ticket}")
        if reconcile_result.failures:
            print(f"reconcile_failures={','.join(reconcile_result.failures)}")
            return 1

        result = execute_supervised_mt5_modify(
            mode=mode,
            readiness_ok=readiness.ready,
            reconcile_result=reconcile_result,
            stop_loss=args.stop_loss,
            take_profit=args.take_profit,
            mt5_module=mt5_module,
        )
        if isinstance(result, str):
            print(f"modify_result={result}")
            return 0
        modify_ticket = reconcile_result.target_ticket if reconcile_result.target_ticket is not None else 0
        journal.record_mt5_modify_result(
            symbol=args.symbol,
            venue_symbol=result.venue_symbol,
            ticket=modify_ticket,
            accepted=result.accepted,
            retcode=result.retcode,
            message=result.message,
        )
        _print_mt5_summary(
            "mt5-modify",
            modify_accepted=result.accepted,
            order_ticket=result.order_ticket,
            deal_ticket=result.deal_ticket,
            retcode=result.retcode,
        )
        print(f"modify_accepted={result.accepted}")
        print(f"order_ticket={result.order_ticket}")
        print(f"deal_ticket={result.deal_ticket}")
        print(f"retcode={result.retcode}")
        print(f"message={result.message}")
        return 0

    if args.command == "monitor-live":
        summary_payload = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
        snapshot = build_monitor_snapshot(live_summary=summary_payload)
        print(render_monitor_text(snapshot))
        return 0

    if args.command == "log-live-call":
        payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            print("error=invalid_payload:expected_json_object")
            return 1
        payload.setdefault("symbol", args.symbol)
        record = build_call_record(payload)
        append_call_record(Path(args.output), record)
        print(f"symbol={record.get('symbol')}")
        print(f"output={Path(args.output)}")
        return 0

    if args.command == "score-live-calibration":
        journal_path = Path(args.calls_journal)
        if not journal_path.exists():
            print(f"error=journal_not_found:{journal_path}")
            return 1
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
        result = run_score_unresolved_records_from_market(
            calls_path=journal_path,
            outcomes_path=Path(args.output),
            now=now,
            symbol=args.symbol,
            window_minutes=args.window_minutes,
        )
        print(f"calls_journal={journal_path}")
        print(f"output={Path(args.output)}")
        print(f"scored_records={result.scored_records}")
        print(f"failed_records={result.failed_records}")
        print(f"skipped_records={result.skipped_records}")
        return 0

    if args.command == "live-snapshot":
        snapshot = asyncio.run(
            run_live_snapshot(
                symbol=args.symbol,
                warmup_count=args.warmup_count,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.higher_timeframe,
                max_live_ticks=args.max_live_ticks,
                app_id=args.app_id,
            )
        )
        print(render_live_snapshot_text(snapshot))
        return 0

    if args.command == "live-watch":
        alerts = asyncio.run(
            run_live_watch(
                symbol=args.symbol,
                warmup_count=args.warmup_count,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.higher_timeframe,
                journal_path=args.journal,
                emit_initial=args.emit_initial,
                max_alerts=args.max_alerts,
                max_minutes=args.max_minutes,
                max_reconnects=args.max_reconnects,
                reconnect_backoff_sec=args.reconnect_backoff_sec,
                app_id=args.app_id,
            )
        )
        for alert in alerts:
            print(render_live_watch_alert_text(alert))
        return 0

    if args.command == "live-watch-review":
        journal_path = Path(args.journal)
        if not journal_path.exists():
            print(f"error=journal_not_found:{journal_path}")
            return 1
        try:
            snapshot = build_live_watch_review_snapshot(
                journal_path=journal_path,
                symbol=args.symbol,
                limit=args.limit,
                call_filter=args.call_filter,
                valid_only=args.valid_only,
            )
        except ValueError as exc:
            print(f"error=invalid_journal:{exc}")
            return 1
        print(render_live_watch_review_text(snapshot))
        return 0

    if args.command == "mt5-monitor":
        journal_path = Path(args.journal)
        if not journal_path.exists():
            print(f"error=journal_not_found:{journal_path}")
            return 1

        events = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        snapshot = build_mt5_monitor_snapshot(
            events=events,
            symbol=getattr(args, "symbol", None),
        )
        print(render_mt5_monitor_text(snapshot))
        return 0

    if args.command == "mt5-rollout-check":
        mode = LiveMode(args.live_mode)
        mt5_config = _build_mt5_config(args)
        runtime_status = evaluate_mt5_runtime(config=mt5_config, symbol=args.symbol)
        readiness = build_live_readiness_report(
            venue=Venue.MT5,
            mode=mode,
            symbol=args.symbol,
            app_id=None,
            token=None,
            armed=False,
            supported_symbols=set(TraderConfig.default().symbols),
            mt5_config=mt5_config,
            mt5_dependency_ready=mt5_dependency_available(),
            mt5_runtime_status=runtime_status,
        )

        validation_snapshot = None
        if args.validation_json:
            validation_snapshot = json.loads(Path(args.validation_json).read_text(encoding="utf-8"))

        mt5_snapshot = None
        if args.journal:
            journal_path = Path(args.journal)
            events = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            mt5_snapshot = build_mt5_monitor_snapshot(events=events, symbol=args.symbol)

        snapshot = build_rollout_status_snapshot(
            venue=Venue.MT5.value,
            symbol=args.symbol,
            live_mode=mode.value,
            readiness_ok=readiness.ready,
            readiness_failures=readiness.failures,
            validation_snapshot=validation_snapshot,
            mt5_snapshot=mt5_snapshot,
            mt5_runtime_ready=runtime_status.ready,
            mt5_runtime_failures=runtime_status.failures,
            mt5_venue_symbol=runtime_status.venue_symbol,
        )
        print(render_rollout_status_text(snapshot))
        if args.artifact_output:
            dump_json_file(args.artifact_output, snapshot)
        return 0

    if args.command == "validate-system":
        summary = asyncio.run(
            run_live_paper(
                symbol=args.symbol,
                duration_sec=0,
                max_live_ticks=0,
            )
        )
        snapshot = build_validation_snapshot(
            venue=Venue.DERIV.value,
            mode=LiveMode.PAPER.value,
            live_summary=summary,
        )
        print(render_validation_text(snapshot))
        if args.artifact_output:
            dump_json_file(args.artifact_output, snapshot)
        return 0

    if args.command == "backtest-synth":
        from synthetic_trader.backtest.synthetic_runner import SyntheticBacktestRunner
        from synthetic_trader.backtest.synthetic_generator import (
            SyntheticIndexConfig,
            BLUEBERRY_INDICES,
        )
        from synthetic_trader.backtest.synthetic_validation import validate_synthetic_data

        # Auto-detect broker from symbol
        symbol_upper = args.symbol.upper()
        if symbol_upper in BLUEBERRY_INDICES:
            gen_config = SyntheticIndexConfig.from_blueberry(symbol_upper)
            broker_label = "Blueberry Markets"
        elif symbol_upper.startswith("R_") or symbol_upper.startswith("V"):
            gen_config = SyntheticIndexConfig.from_deriv(symbol_upper)
            broker_label = "Deriv"
        else:
            gen_config = SyntheticIndexConfig(symbol=symbol_upper)
            broker_label = "Deriv (default)"

        print(f"symbol={args.symbol}")
        print(f"broker={broker_label}")
        print(f"episodes={args.episodes}")
        print(f"ticks_per_episode={args.ticks}")
        print(f"seed={args.seed}")
        print()

        # Quick validation of synthetic data quality
        print("Validating synthetic data quality...")
        from synthetic_trader.backtest.synthetic_generator import SyntheticPriceGenerator
        gen = SyntheticPriceGenerator(config=gen_config, seed=args.seed)
        sample_ticks = gen.generate_ticks(min(1000, args.ticks))
        validation = validate_synthetic_data(sample_ticks)
        print(f"data_validation={validation.summary}")
        for t in validation.tests:
            status = "PASS" if t.passed else "FAIL"
            print(f"  {status} {t.name}: {t.description}")
        print()

        # Resolve prop firm profile
        prop_firm = None
        if args.prop_firm != "none":
            from synthetic_trader.backtest.prop_firm import get_prop_firm_profile
            prop_firm = get_prop_firm_profile(args.prop_firm)
            if prop_firm:
                print(f"prop_firm={prop_firm.name}")
                print(f"  max_daily_loss={prop_firm.max_daily_loss_pct:.0%}")
                print(f"  max_drawdown={prop_firm.max_overall_drawdown_pct:.0%}")
                print(f"  risk_per_trade={prop_firm.risk_per_trade_pct:.1%}")
                print(f"  leverage=1:{prop_firm.leverage}")
                print()

        # Run the synthetic backtest
        print("Running synthetic backtest...")
        runner = SyntheticBacktestRunner(
            n_episodes=args.episodes,
            ticks_per_episode=args.ticks,
            base_seed=args.seed,
            learn=not args.no_learn,
            config_override=gen_config,
            prop_firm=prop_firm,
        )
        report = runner.run(args.symbol)
        print(runner.render_report(report))

        if args.artifact_output:
            dump_json_file(args.artifact_output, report.to_dict())
            print(f"\nartifact_output={Path(args.artifact_output)}")
        return 0

    if args.command == "collect-ticks":
        from synthetic_trader.calibration.mt5_collector import (
            collect_ticks_from_mt5,
            get_venue_symbol,
        )

        venue_sym = args.venue_symbol or get_venue_symbol(args.symbol)
        print(f"Collecting ticks for {args.symbol} ({venue_sym})...")
        print(f"Duration: {args.duration}s, Max ticks: {args.max_ticks}")
        print(f"Output: {args.output}")
        print()

        try:
            result = collect_ticks_from_mt5(
                symbol=args.symbol,
                venue_symbol=venue_sym,
                duration_sec=args.duration,
                max_ticks=args.max_ticks,
                output_path=args.output,
                server=args.mt5_server,
                login=args.mt5_login,
                password=args.mt5_password,
                terminal_path=args.mt5_terminal_path,
            )
            print(result.summary())
            return 0
        except RuntimeError as exc:
            print(f"Error: {exc}")
            print("Make sure MT5 terminal is running and the symbol is available.")
            return 1

    if args.command == "calibrate-egarch":
        from synthetic_trader.models.garch_calibration import (
            calibrate_from_ticks_csv,
            save_calibration_result,
        )

        print(f"Calibrating EGARCH(1,1) for {args.symbol}...")
        print(f"Input: {args.csv}")
        print()

        result = calibrate_from_ticks_csv(
            csv_path=args.csv,
            symbol=args.symbol,
        )

        print(f"symbol={result.symbol}")
        print(f"observations={result.n_observations}")
        print(f"convergence={result.convergence}")
        print(f"message={result.message}")
        print()
        print("Fitted Parameters:")
        print(f"  omega  = {result.omega:.6f}")
        print(f"  alpha  = {result.alpha:.6f}")
        print(f"  beta   = {result.beta:.6f}")
        print(f"  gamma  = {result.gamma:.6f}")
        print()
        print("Diagnostics:")
        print(f"  persistence    = {result.persistence:.4f}")
        print(f"  half_life      = {result.half_life:.1f} obs")
        print(f"  long_run_vol   = {result.long_run_vol:.6f}")
        print(f"  realized_vol   = {result.realized_vol:.6f}")
        print(f"  vol_ratio      = {result.vol_ratio:.4f}")
        print(f"  neg_log_lik    = {result.negative_log_likelihood:.2f}")
        print(f"  ljung_box_p    = {result.ljung_box_p_value:.4f}")
        print(f"  arch_test_p    = {result.arch_test_p_value:.4f}")

        if args.output:
            save_calibration_result(result, args.output)
            print(f"\nSaved to {args.output}")

        if args.apply:
            print("\nApplying to synthetic generator config...")
            print(f"  New GARCH params for {args.symbol}:")
            print(f"    omega={result.omega:.6e}")
            print(f"    alpha={result.alpha:.4f}")
            print(f"    beta={result.beta:.4f}")
            print(f"    gamma={result.gamma:.4f}")

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


def _build_mt5_journal(args: argparse.Namespace) -> TradeJournal:
    journal_path = getattr(args, "journal", None) or "journals/mt5_analytics.jsonl"
    return TradeJournal(Path(journal_path))


def _print_mt5_summary(command: str, **fields: object) -> None:
    print(f"mt5_command={command}")
    for key, value in fields.items():
        print(f"mt5_{key}={value}")


def _render_latency_profile(profile) -> str:
    lines = [f"latency_total_ms={profile.total_duration_ms}"]
    for stage in profile.stages:
        lines.append(f"latency_stage={stage.name},{stage.category},{stage.duration_ms}")
    return "\n".join(lines)


def _build_mt5_config(args: argparse.Namespace) -> Mt5Config:
    symbol_map = {args.symbol: args.mt5_symbol} if getattr(args, "mt5_symbol", None) else {}
    return Mt5Config(
        server=getattr(args, "mt5_server", None),
        login=getattr(args, "mt5_login", None),
        password=getattr(args, "mt5_password", None),
        terminal_path=getattr(args, "mt5_terminal_path", None),
        symbol_map=symbol_map,
    )


def _load_mt5_module():
    import MetaTrader5  # type: ignore

    return MetaTrader5


def _build_runtime_config(args: argparse.Namespace) -> TraderConfig:
    config = TraderConfig.default()
    return replace(
        config,
        paper=PaperExecutionConfig(
            entry_slippage_ticks=0.0,
            exit_slippage_ticks=getattr(args, "exit_slippage_ticks", 0.0),
            execution_penalty_per_trade=getattr(args, "execution_penalty", 0.0),
        ),
        mt5=_build_mt5_config(args),
    )


if __name__ == "__main__":
    raise SystemExit(main())
