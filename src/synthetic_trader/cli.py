from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from synthetic_trader.backtest.engine import BacktestEngine, load_ticks_csv
from synthetic_trader.config import LiveMode, Mt5Config, PaperExecutionConfig, TraderConfig, Venue
from synthetic_trader.data.collector import collect_history
from synthetic_trader.data.tick_store import TickDatasetReport, inspect_ticks
from synthetic_trader.data.migrate_csv import migrate_legacy_csv
from synthetic_trader.live.stage3_gate import MIN_STAGE3_SAMPLES
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

    backfill_candles = subparsers.add_parser(
        "backfill-candles",
        help="backfill multi-day history from Deriv 1-minute candles into a tick CSV "
        "(tick-style history cannot page back in time; candle-style can)",
    )
    backfill_candles.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    backfill_candles.add_argument("--days", type=float, default=5.0, help="days of history to backfill")
    backfill_candles.add_argument("--granularity", type=int, default=60, help="candle granularity in seconds (base tick spacing)")
    backfill_candles.add_argument("--batch-size", type=int, default=5000)
    backfill_candles.add_argument("--output", default="data/backfill/ticks.csv")
    backfill_candles.add_argument("--app-id", help="Deriv app id; defaults to 116450 or DERIV_APP_ID")

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

    backtest_vol = subparsers.add_parser(
        "backtest-vol",
        help="run vol-targeting fade backtest (EGARCH forecast + ADWIN drift gate) from tick CSV",
    )
    backtest_vol.add_argument("--csv", required=True, help="CSV path with epoch,price columns")
    backtest_vol.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    backtest_vol.add_argument("--timeframe", type=int, default=60, help="primary candle timeframe in seconds")
    backtest_vol.add_argument(
        "--mode",
        choices=["fade", "momentum"],
        default="fade",
        help="which vol-regime strategy to run as primary: fade (mean-reversion"
        " on extended vol) or momentum (follow the move in a high-vol regime)",
    )
    backtest_vol.add_argument(
        "--compare",
        action="store_true",
        help="also run the other vol-regime strategy AND the sniper strategy on"
        " the same data and print all three (fade vs momentum vs sniper)",
    )
    backtest_vol.add_argument(
        "--artifact-output",
        help="optional path to save the primary (--mode) backtest report as JSON",
    )
    backtest_vol.add_argument("--entry-slippage-ticks", type=float, default=1.0)
    backtest_vol.add_argument("--exit-slippage-ticks", type=float, default=1.0)
    backtest_vol.add_argument("--execution-penalty", type=float, default=0.5)
    backtest_vol.add_argument("--z-entry", type=float, default=1.5, help="price extension threshold in forecast sigmas")
    backtest_vol.add_argument("--vol-extended-ratio", type=float, default=1.5)
    backtest_vol.add_argument(
        "--min-revert-signal",
        type=float,
        default=0.02,
        help="require the EGARCH mean-reversion signal to be at least this"
        " (selects sharp-spike fades; 0 disables). Tuned on the clean 7-day corpus",
    )
    backtest_vol.add_argument("--stop-sigma-mult", type=float, default=2.5)
    backtest_vol.add_argument("--target-sigma-mult", type=float, default=1.5)
    backtest_vol.add_argument("--mom-z-entry", type=float, default=0.8, help="momentum price-extension threshold in forecast sigmas")
    backtest_vol.add_argument("--mom-vol-min-ratio", type=float, default=1.15, help="momentum high-vol regime gate (ratio only): sigma vs its slow baseline")
    backtest_vol.add_argument(
        "--mom-gate",
        choices=["ratio", "absolute", "trend"],
        default="ratio",
        help="momentum high-vol gate: 'ratio' (sigma freshly above its slow EMA),"
        " 'absolute' (sigma above abs_sigma_mult x calibrated long-run vol — stays on"
        " through sustained regimes), or 'trend' (sigma EMA itself still rising)",
    )
    backtest_vol.add_argument(
        "--mom-abs-mult",
        type=float,
        default=2.0,
        help="momentum absolute gate: sigma must exceed this multiple of the"
        " calibrated long-run vol (only used with --mom-gate absolute)",
    )
    backtest_vol.add_argument(
        "--mom-trend-eps",
        type=float,
        default=1e-4,
        help="momentum trend gate: minimum relative rise of the sigma EMA to count"
        " as a building vol regime (only used with --mom-gate trend)",
    )
    backtest_vol.add_argument("--mom-stop-sigma-mult", type=float, default=1.5)
    backtest_vol.add_argument("--mom-target-sigma-mult", type=float, default=3.0)
    backtest_vol.add_argument("--max-hold-bars", type=int, default=30)
    backtest_vol.add_argument(
        "--breakeven-trail-frac",
        type=float,
        default=0.0,
help="breakeven trail for both vol-regime strategies: move the stop to entry "
        "once MFE reaches this fraction of the target distance (0 disables). "
        "Fixes the fade's realized-RR drag (see PHASE5_SUMMARY 31)",
    )
    backtest_vol.add_argument("--distribution", choices=["normal", "studentt"], default="normal")
    backtest_vol.add_argument("--dof", type=float, default=5.0)
    backtest_vol.add_argument(
        "--no-calibration",
        action="store_true",
        help="skip loading calibrated EGARCH parameters from data/garch_calibration",
    )

    backtest_gate = subparsers.add_parser(
        "backtest-gate",
        help="walk-forward backtest of the Stage-3 empirical gate: emit calls from a tick CSV,"
        " score them by trigger type, and show what the gate would suppress vs keep",
    )
    backtest_gate.add_argument("--csv", required=True, help="CSV path with epoch,price columns")
    backtest_gate.add_argument("--symbol", default="R_100", choices=["R_75", "R_100"])
    backtest_gate.add_argument("--timeframe", type=int, default=60, help="primary candle timeframe in seconds")
    backtest_gate.add_argument("--higher-timeframe", type=int, default=300, help="higher timeframe in seconds")
    backtest_gate.add_argument(
        "--min-samples",
        type=int,
        default=None,
        help="minimum scored outcomes before the gate trusts the empirical rate"
        " (default: SYNTH_GATE_MIN_SAMPLES or 10)",
    )
    backtest_gate.add_argument(
        "--hit-rate-floor",
        type=float,
        default=None,
        help="empirical target-hit rate floor for the gate. When omitted the floor is the "
        "per-trigger-type BREAK-EVEN rate (1/(1+avg reward:risk) + margin), so a 3R setup "
        "must clear ~30%% instead of an unreachable flat bar. Pass a number to force one "
        "fixed bar for every trigger (e.g. 0.5 for the legacy behavior)",
    )
    backtest_gate.add_argument(
        "--suppression-mode",
        choices=["suppress", "annotate"],
        default="suppress",
        help="'suppress' holds below-floor call types back; 'annotate' keeps emitting them with the honest rate",
    )
    backtest_gate.add_argument(
        "--proven-only",
        action="store_true",
        help="only evidence_status == 'proven' calls may execute; everything else is forced paper-only",
    )

    sweep_vol = subparsers.add_parser(
        "sweep-vol",
        help="systematic parameter sweep over fade + momentum vol-targeting configs",
    )
    sweep_vol.add_argument("--csv", required=True, help="CSV path with epoch,price columns")
    sweep_vol.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    sweep_vol.add_argument("--timeframe", type=int, default=60, help="primary candle timeframe in seconds")
    sweep_vol.add_argument(
        "--min-trades",
        type=int,
        default=5,
        help="only report configs with at least this many trades",
    )
    sweep_vol.add_argument("--top-n", type=int, default=10, help="how many top configs to print")
    sweep_vol.add_argument(
        "--gates",
        default="ratio,absolute",
        help="comma-separated momentum gates to sweep (ratio, absolute)",
    )
    sweep_vol.add_argument(
        "--strategies",
        default="fade,momentum",
        help="comma-separated strategy families to sweep (fade, momentum); "
        "pass 'momentum' alone for a focused momentum-only re-tune",
    )
    sweep_vol.add_argument(
        "--mom-json",
        help="optional JSON file with focused momentum grid overrides, e.g. "
        "{\"z_entries\":[0.5,1.0,0.25],\"stops\":[1.0,2.0,0.5],"
        "\"targets\":[2.0,5.0,1.0],\"holds\":[10,120,10],"
        "\"ref_periods\":[300,1200,150],\"gate\":{\"abs_sigma_mult\":[1.2,3.0,0.2]}}",
    )
    sweep_vol.add_argument(
        "--artifact-output",
        help="optional path to save the full sweep report as JSON",
    )

    tune_bands = subparsers.add_parser(
        "tune-bands",
        help="band-tuning pass: re-fit p50/p90 range multipliers for R_75 and R_100 "
        "on recent walk-forward coverage and persist them",
    )
    tune_bands.add_argument(
        "--engine-root",
        default=".",
        help="engine root whose data/backfill CSVs and calibration are used (default .)",
    )

    forecast_horizon = subparsers.add_parser(
        "forecast-horizon",
        help="forecast the volatility regime over the next N hours (EGARCH + ADWIN)",
    )
    forecast_horizon.add_argument("--csv", required=True, help="tick CSV path")
    forecast_horizon.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    forecast_horizon.add_argument("--timeframe", type=int, default=300, help="primary candle timeframe in seconds")
    forecast_horizon.add_argument("--horizon-hours", type=float, default=5.0, help="forecast horizon in hours (default 5)")
    forecast_horizon.add_argument(
        "--validate",
        action="store_true",
        help="walk-forward validate range-band coverage over the full tick history",
    )
    forecast_horizon.add_argument(
        "--no-calibration",
        action="store_true",
        help="skip loading calibrated EGARCH parameters from data/garch_calibration",
    )
    forecast_horizon.add_argument(
        "--fit-multipliers",
        action="store_true",
        help="fit empirical range multipliers on a train split, validate coverage "
        "on the holdout, and persist them to data/forecast_multipliers",
    )
    forecast_horizon.add_argument(
        "--apply-multipliers",
        action="store_true",
        help="validate using previously fitted multipliers from data/forecast_multipliers "
        "(requires a prior --fit-multipliers run)",
    )

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
    live_snapshot.add_argument(
        "--proven-only",
        action="store_true",
        help="only evidence_status == 'proven' calls may carry a live order; "
        "everything else is forced paper-only (SYNTH_GATE_PROVEN_ONLY)",
    )

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
        "--calls-journal",
        default="journals/live_calibration_calls.jsonl",
        help="auto-log every emitted call here for the scoring loop (set to empty to disable)",
    )
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
    live_watch.add_argument(
        "--proven-only",
        action="store_true",
        help="only evidence_status == 'proven' calls may carry a live order; "
        "everything else is forced paper-only (SYNTH_GATE_PROVEN_ONLY)",
    )
    live_watch.add_argument(
        "--auto-score",
        type=float,
        nargs="?",
        const=300.0,
        metavar="INTERVAL",
        help="auto-score the calls journal on a timer during the watch and once at exit "
        "(interval seconds; default 300). Keeps the outcomes journal fresh without "
        "a separate score-live-loop process.",
    )
    live_watch.add_argument("--auto-score-status-path", default="data/auto_scorer.json")

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

    score_live_loop = subparsers.add_parser(
        "score-live-loop",
        help="auto-score every live call (target/stop/neither) on a loop",
    )
    score_live_loop.add_argument("--calls-journal", default="journals/live_calibration_calls.jsonl")
    score_live_loop.add_argument("--output", default="journals/live_calibration_outcomes.jsonl")
    score_live_loop.add_argument("--symbol", choices=["R_75", "R_100"])
    score_live_loop.add_argument("--window-minutes", type=int)
    score_live_loop.add_argument("--interval", type=float, default=300.0, help="sweep interval in seconds")
    score_live_loop.add_argument("--status-path", default="data/auto_scorer.json")
    score_live_loop.add_argument("--once", action="store_true", help="single sweep then exit (cron-friendly)")

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

    collect_live = subparsers.add_parser(
        "collect-live-ticks",
        help="run the continuous live tick collection service (Blueberry MT5 terminal)",
    )
    collect_live.add_argument("--symbols", default="R_75,R_100", help="comma-separated symbols (default R_75,R_100)")
    collect_live.add_argument("--venue-symbol", help="MT5 venue symbol override (auto-detected: SYN75/SYN100)")
    collect_live.add_argument("--output-dir", default="data/backfill", help="directory to append tick CSVs into")
    collect_live.add_argument("--duration-sec", type=float, help="stop after this many seconds (default: run until interrupted)")
    collect_live.add_argument("--status-path", default="data/live_tick_collector.json", help="status JSON output path")
    collect_live.add_argument("--poll-interval-sec", type=float, default=0.5)
    collect_live.add_argument("--flush-interval-sec", type=float, default=30.0)
    collect_live.add_argument("--flush-batch-size", type=int, default=500)
    collect_live.add_argument("--stall-warn-sec", type=float, default=120.0)
    collect_live.add_argument("--stall-reconnect-sec", type=float, default=600.0)
    collect_live.add_argument("--rollover-hour-utc", type=int, default=0, help="daily rollover hour (UTC) — stall tolerance window")
    collect_live.add_argument("--rollover-grace-sec", type=float, default=120.0)
    collect_live.add_argument("--mt5-server")
    collect_live.add_argument("--mt5-login", type=int)
    collect_live.add_argument("--mt5-password")
    collect_live.add_argument("--mt5-terminal-path")

    capture_m1 = subparsers.add_parser(
        "capture-m1",
        help="continuously capture M1 rates into the tick corpus (compounds data/backfill over time)",
    )
    capture_m1.add_argument("--symbols", default="R_75,R_100", help="comma-separated symbols (default R_75,R_100)")
    capture_m1.add_argument("--output-dir", default="data/backfill", help="directory holding {symbol}_ticks.csv")
    capture_m1.add_argument("--interval", type=float, default=3600.0, help="seconds between sweeps (default 3600 = hourly)")
    capture_m1.add_argument("--initial-days", type=float, default=7.0, help="days of history seeded on a symbol's first capture")
    capture_m1.add_argument("--overlap-sec", type=float, default=300.0, help="refetch overlap before the newest captured candle")
    capture_m1.add_argument("--once", action="store_true", help="run a single sweep and exit (cron / Task Scheduler friendly)")
    capture_m1.add_argument("--status-path", default="data/m1_capture.json", help="status JSON output path")
    capture_m1.add_argument("--mt5-terminal-path", help="path to terminal64.exe (auto-detected if omitted)")

    tick_coverage = subparsers.add_parser(
        "tick-coverage",
        help="report per-symbol tick coverage and WFO readiness (how much data is enough)",
    )
    tick_coverage.add_argument("--symbols", default="R_75,R_100", help="comma-separated symbols (default R_75,R_100)")
    tick_coverage.add_argument("--engine-root", default=".", help="repo root containing data/ (default: current dir)")
    tick_coverage.add_argument("--timeframes", default="60,300", help="comma-separated candle timeframes for window estimates")
    tick_coverage.add_argument("--horizon-hours", default="4,6", help="comma-separated horizons for window estimates")
    tick_coverage.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    tick_task_health = subparsers.add_parser(
        "tick-task-health",
        help="health check for the daily tick-collector task: warn when the "
        "corpus stopped growing (ticks flat for 48h) or the task went stale "
        "(exit code 0 = healthy, 1 = warnings, for alert gating)",
    )
    tick_task_health.add_argument(
        "--engine-root", default=".",
        help="repo root containing .data/ and data/backfill (default: current dir)",
    )
    tick_task_health.add_argument(
        "--flat-hours", type=float, default=48.0,
        help="warn when a symbol's tick count is flat for this many hours (default 48)",
    )
    tick_task_health.add_argument(
        "--task-stale-hours", type=float, default=26.0,
        help="warn when the last task action is older than this (default 26)",
    )
    tick_task_health.add_argument(
        "--verify-stale-hours", type=float, default=26.0,
        help="warn when the verify snapshot is older than this (default 26)",
    )
    tick_task_health.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )

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

    backfill_mt5 = subparsers.add_parser(
        "backfill-mt5",
        help="backfill multi-day history from the Blueberry MT5 terminal (M1 rates -> tick CSV). "
        "Uses the CORRECT broker symbols (SYN75/SYN100) and price scale, unlike the Deriv API fallback.",
    )
    backfill_mt5.add_argument("--symbol", default="R_75", choices=["R_75", "R_100"])
    backfill_mt5.add_argument("--venue-symbol", help="MT5 venue symbol (auto-detected: SYN75/SYN100)")
    backfill_mt5.add_argument("--days", type=float, default=5.0, help="days of history to backfill")
    backfill_mt5.add_argument("--output", default="data/backfill/ticks.csv")
    backfill_mt5.add_argument("--mt5-terminal-path", help="path to terminal64.exe (auto-detected if omitted)")

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
    # Load .env.local (root + the Next.js app) so direct runs — scheduled
    # tasks, collect-live-ticks, manual CLI — see the same credentials the
    # dashboard's subprocesses see.  Idempotent; exported env always wins.
    try:
        from synthetic_trader.envloader import load_env_files

        load_env_files()
    except Exception:  # pragma: no cover - never block the CLI on env load
        pass

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

    if args.command == "backfill-candles":
        from synthetic_trader.data.collector import collect_candle_history

        report = asyncio.run(
            collect_candle_history(
                symbol=args.symbol,
                days=args.days,
                output_path=args.output,
                app_id=args.app_id,
                granularity=args.granularity,
                batch_size=args.batch_size,
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

    if args.command == "backtest-vol":
        from synthetic_trader.backtest.vol_momentum import (
            VolMomentumConfig,
            run_vol_momentum_backtest,
        )
        from synthetic_trader.backtest.vol_reversion import (
            VolReversionConfig,
            dedupe_ticks,
            run_vol_reversion_backtest,
        )
        from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

        ticks = dedupe_ticks(load_ticks_csv(args.csv, default_symbol=args.symbol))
        paper = PaperExecutionConfig(
            entry_slippage_ticks=args.entry_slippage_ticks,
            exit_slippage_ticks=args.exit_slippage_ticks,
            execution_penalty_per_trade=args.execution_penalty,
        )
        config = replace(TraderConfig.default(), paper=paper)
        fade_config = VolReversionConfig(
            z_entry=args.z_entry,
            vol_extended_ratio=args.vol_extended_ratio,
            min_revert_signal=args.min_revert_signal,
            stop_sigma_mult=args.stop_sigma_mult,
            target_sigma_mult=args.target_sigma_mult,
            max_hold_bars=args.max_hold_bars,
            distribution=args.distribution,
            dof=args.dof,
            breakeven_trail_frac=args.breakeven_trail_frac,
        )
        moment_config = VolMomentumConfig(
            z_entry=args.mom_z_entry,
            vol_min_ratio=args.mom_vol_min_ratio,
            mom_gate=args.mom_gate,
            abs_sigma_mult=args.mom_abs_mult,
            trend_eps=args.mom_trend_eps,
            stop_sigma_mult=args.mom_stop_sigma_mult,
            target_sigma_mult=args.mom_target_sigma_mult,
            max_hold_bars=args.max_hold_bars,
            distribution=args.distribution,
            dof=args.dof,
            breakeven_trail_frac=args.breakeven_trail_frac,
        )
        garch_state = None if args.no_calibration else load_calibrated_garch_state(args.symbol)
        if not args.no_calibration and garch_state is None:
            print(f"calibrated_garch=not_found (using default priors)")

        def _print_result(label: str, result) -> None:
            print(f"strategy={label}")
            print(f"symbol={args.symbol}")
            print(f"timeframe_sec={args.timeframe}")
            print(f"trades={result.metrics.trades}")
            print(f"signals={result.signals}")
            print(f"rejected_signals={result.rejected_signals}")
            print(f"win_rate={result.metrics.win_rate:.2%}")
            print(f"profit_factor={_format_float(result.metrics.profit_factor)}")
            print(f"expectancy_r={result.metrics.expectancy_r:.3f}")
            print(f"net_pnl={result.metrics.net_pnl:.2f}")
            print(f"final_equity={result.final_equity:.2f}")
            print(f"model_version={result.model_version}")
            if garch_state is not None and label != "sniper":
                print(f"calibrated_garch=loaded")

        # Primary: the strategy selected by --mode (artifact goes to it).
        if args.mode == "momentum":
            primary = run_vol_momentum_backtest(
                ticks,
                symbol=args.symbol,
                timeframe_sec=args.timeframe,
                config=config,
                strategy_config=moment_config,
                garch_state=garch_state,
                paper=paper,
                artifact_output_path=args.artifact_output,
            )
            primary_label = "vol-momentum"
        else:
            primary = run_vol_reversion_backtest(
                ticks,
                symbol=args.symbol,
                timeframe_sec=args.timeframe,
                config=config,
                strategy_config=fade_config,
                garch_state=garch_state,
                paper=paper,
                artifact_output_path=args.artifact_output,
            )
            primary_label = "vol-reversion"
        print(f"=== {primary_label} (primary) ===")
        _print_result(primary_label, primary)

        if args.compare:
            # Run the OTHER vol-regime strategy too, then the sniper reference,
            # so the operator can see fade vs momentum vs sniper on the same
            # ticks and decide whether following or fading vol is profitable.
            if args.mode == "momentum":
                other = run_vol_reversion_backtest(
                    ticks,
                    symbol=args.symbol,
                    timeframe_sec=args.timeframe,
                    config=config,
                    strategy_config=fade_config,
                    garch_state=garch_state,
                    paper=paper,
                )
                other_label = "vol-reversion"
            else:
                other = run_vol_momentum_backtest(
                    ticks,
                    symbol=args.symbol,
                    timeframe_sec=args.timeframe,
                    config=config,
                    strategy_config=moment_config,
                    garch_state=garch_state,
                    paper=paper,
                )
                other_label = "vol-momentum"
            print(f"\n=== {other_label} ===")
            _print_result(other_label, other)

            sniper = BacktestEngine(config=config)
            sniper_result = sniper.run_ticks(
                ticks,
                symbol=args.symbol,
                timeframe_sec=args.timeframe,
                higher_timeframe_sec=args.timeframe * 3,
            )
            print(f"\n=== sniper (reference) ===")
            _print_result("sniper", sniper_result)
        return 0

    if args.command == "backtest-gate":
        from synthetic_trader.research.gate_backtest import (
            backtest_gate_from_csv,
            print_gate_backtest_report,
        )

        result = backtest_gate_from_csv(
            csv_path=args.csv,
            symbol=args.symbol,
            timeframe_sec=args.timeframe,
            higher_timeframe_sec=args.higher_timeframe,
            min_samples=args.min_samples if args.min_samples is not None else MIN_STAGE3_SAMPLES,
            # None (the default) means the per-trigger-type break-even floor;
            # an explicit --hit-rate-floor forces the legacy flat bar.
            hit_rate_floor=args.hit_rate_floor,
            suppression_mode=args.suppression_mode,
            proven_only=args.proven_only,
        )
        print_gate_backtest_report(result)
        return 0

    if args.command == "sweep-vol":
        from synthetic_trader.research.vol_param_sweep import (
            print_sweep_report,
            run_sweep_for_csv,
        )

        gates = tuple(g.strip() for g in args.gates.split(",") if g.strip())
        strategies = tuple(
            g.strip() for g in args.strategies.split(",") if g.strip()
        )
        momentum_ranges = None
        if args.mom_json:
            import json as _json

            mom_json_path = Path(args.mom_json)
            if not mom_json_path.exists():
                print(f"error=mom_json_not_found:{mom_json_path}")
                return 1
            raw = _json.loads(mom_json_path.read_text(encoding="utf-8"))
            # CLI uses plain (start, stop, step) triples; map keys to the
            # momentum_grid override names.  Unknown keys are ignored with a
            # warning (a typo like "z_entry" must not silently run defaults).
            momentum_ranges = {}
            grid_keys = ("z_entries", "stops", "targets", "holds", "ref_periods")
            for k, v in raw.items():
                if k == "gate":
                    continue
                if k in grid_keys and isinstance(v, (list, tuple)) and len(v) == 3:
                    momentum_ranges[k] = tuple(v)
                else:
                    print(f"sweep-vol: ignoring unknown mom-json key {k!r} "
                          f"(expected one of {grid_keys} or 'gate')")
            if isinstance(raw.get("gate"), dict):
                for gk, gv in raw["gate"].items():
                    if isinstance(gv, (list, tuple)) and len(gv) == 3:
                        momentum_ranges.setdefault("gate_ranges", {})[gk] = tuple(gv)
                    else:
                        print(f"sweep-vol: ignoring invalid gate override {gk!r}")
            elif "gate" in raw:
                print("sweep-vol: ignoring 'gate' override (expected an object)")
        report = run_sweep_for_csv(
            args.csv,
            symbol=args.symbol,
            timeframe_sec=args.timeframe,
            min_trades=args.min_trades,
            top_n=args.top_n,
            gates=gates,
            strategies=strategies,
            momentum_ranges=momentum_ranges,
            artifact_output_path=args.artifact_output,
        )
        print_sweep_report(report, args.symbol, args.timeframe)
        return 0

    if args.command == "tune-bands":
        from synthetic_trader.scripts.horizon_forecast_stats import tune_all_multipliers

        report = tune_all_multipliers(args.engine_root)
        for symbol, symbol_report in report.items():
            if isinstance(symbol_report, dict) and "error" in symbol_report:
                print(f"symbol={symbol} error={symbol_report['error']}")
                continue
            print(f"== {symbol} ==")
            if not isinstance(symbol_report, dict):
                continue
            for horizon_key, tuned in symbol_report.items():
                if not isinstance(tuned, dict):
                    continue
                p50 = tuned.get("p50_mult")
                p90 = tuned.get("p90_mult")
                print(
                    f"horizon={horizon_key} verdict={tuned.get('verdict')} "
                    f"windows={tuned.get('windows')} "
                    f"coverage_p50={tuned.get('coverage_p50', 0.0):.3f} "
                    f"coverage_p90={tuned.get('coverage_p90', 0.0):.3f} "
                    f"p50_mult={p50 if p50 is None else p50:.3f} "
                    f"p90_mult={p90 if p90 is None else p90:.3f} "
                    f"iters={tuned.get('iterations')} persisted={tuned.get('persisted')}"
                )
        return 0

    if args.command == "forecast-horizon":
        from synthetic_trader.models.garch_calibration import load_calibrated_garch_state
        from synthetic_trader.models.horizon_forecast import (
            HorizonVolForecaster,
            horizon_verdict,
            load_forecast_multipliers,
            save_forecast_multipliers,
            score_horizon_forecast,
        )

        ticks = load_ticks_csv(args.csv, default_symbol=args.symbol)
        garch_state = None if args.no_calibration else load_calibrated_garch_state(args.symbol)
        if garch_state is not None:
            print(f"calibrated_garch=loaded")

        if args.validate or args.fit_multipliers:
            if args.fit_multipliers:
                # Fit multipliers on a train split, score coverage on the
                # holdout (honest out-of-sample calibration), and persist.
                validation = score_horizon_forecast(
                    ticks,
                    symbol=args.symbol,
                    horizon_sec=int(args.horizon_hours * 3600),
                    timeframe_sec=args.timeframe,
                    garch_state=garch_state,
                )
                horizon_key = f"{int(args.horizon_hours)}h"
                path = save_forecast_multipliers(
                    args.symbol,
                    args.timeframe,
                    {
                        horizon_key: {
                            "p50_mult": validation.fitted_p50_mult,
                            "p90_mult": validation.fitted_p90_mult,
                            "windows": validation.windows,
                            "coverage_p50": validation.coverage_p50,
                            "coverage_p90": validation.coverage_p90,
                        }
                    },
                )
                print(f"multipliers_saved={path}")
                print(f"multipliers_p50={validation.fitted_p50_mult:.3f}")
                print(f"multipliers_p90={validation.fitted_p90_mult:.3f}")
            else:
                p50 = p90 = None
                if args.apply_multipliers:
                    mults = load_forecast_multipliers(args.symbol, args.timeframe)
                    entry = (mults or {}).get(f"{int(args.horizon_hours)}h")
                    if entry:
                        p50, p90 = entry.get("p50_mult"), entry.get("p90_mult")
                        print(f"multipliers=loaded p50={p50:.3f} p90={p90:.3f}")
                    else:
                        print(f"multipliers=not_found (run --fit-multipliers first)")
                validation = score_horizon_forecast(
                    ticks,
                    symbol=args.symbol,
                    horizon_sec=int(args.horizon_hours * 3600),
                    timeframe_sec=args.timeframe,
                    garch_state=garch_state,
                    p50_mult=p50,
                    p90_mult=p90,
                )
            print(f"validation=walk_forward_coverage")
            print(f"symbol={validation.symbol}")
            print(f"horizon_sec={validation.horizon_sec}")
            print(f"timeframe_sec={validation.timeframe_sec}")
            print(f"windows={validation.windows}")
            print(f"coverage_p50={validation.coverage_p50:.3f}")
            print(f"coverage_p90={validation.coverage_p90:.3f}")
            print(f"median_realized_ratio={validation.median_realized_ratio:.3f}")
            print(f"mean_realized_ratio={validation.mean_realized_ratio:.3f}")
            print(f"over_forecast_pct={validation.over_forecast_pct:.3f}")
            print(f"drift_events={validation.drift_events}")
            print(f"fitted_p50_mult={validation.fitted_p50_mult:.3f}")
            print(f"fitted_p90_mult={validation.fitted_p90_mult:.3f}")
            verdict = horizon_verdict(validation)
            print(f"verdict={verdict}")
            return 0

        forecaster = HorizonVolForecaster(
            args.symbol,
            timeframe_sec=args.timeframe,
            garch_state=garch_state,
        )
        from synthetic_trader.data.candles import MultiTimeframeCandleBuilder

        builder = MultiTimeframeCandleBuilder(args.symbol, [args.timeframe])
        for tick in sorted(ticks, key=lambda item: item.epoch):
            closed = builder.update(tick)
            for tf, candle in closed.items():
                if tf == args.timeframe:
                    forecaster.on_candle(candle)

        # flush() is destructive — call it exactly once for the final close.
        final_candle = builder.flush().get(args.timeframe)
        forecast = forecaster.forecast(
            int(args.horizon_hours * 3600),
            current_close=final_candle.close if final_candle else None,
        )
        print(f"symbol={forecast.symbol}")
        print(f"horizon_sec={forecast.horizon_sec}")
        print(f"bars={forecast.bars}")
        print(f"current_close={forecast.current_close:.2f}")
        print(f"current_sigma={forecast.current_sigma:.6f}")
        print(f"projected_sigma_avg={forecast.projected_sigma_avg:.6f}")
        print(f"projected_sigma_end={forecast.projected_sigma_end:.6f}")
        print(f"long_run_sigma={forecast.long_run_sigma:.6f}")
        print(f"vol_trend={forecast.vol_trend}")
        print(f"range_p50_price={forecast.range_p50_price:.2f}")
        print(f"range_p90_price={forecast.range_p90_price:.2f}")
        print(f"expected_low_p50={forecast.expected_low_p50:.2f}")
        print(f"expected_high_p50={forecast.expected_high_p50:.2f}")
        print(f"expected_low_p90={forecast.expected_low_p90:.2f}")
        print(f"expected_high_p90={forecast.expected_high_p90:.2f}")
        print(f"regime_stable={forecast.regime_stable}")
        print(f"drift_events={forecast.drift_events}")
        print(f"confidence={forecast.confidence:.2f}")
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
        from synthetic_trader.live.auto_scorer import _resolve_scoring_client_factory

        journal_path = Path(args.calls_journal)
        if not journal_path.exists():
            print(f"error=journal_not_found:{journal_path}")
            return 1
        # Scoring has NO Deriv fallback: resolve the Blueberry MT5 client or
        # fail loudly (the call levels are SYN-scale; Deriv 1HZ is wrong-scale).
        try:
            client_factory = _resolve_scoring_client_factory()
        except Exception as exc:
            print(f"error=scoring_unavailable:{exc}")
            return 1
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
        result = run_score_unresolved_records_from_market(
            calls_path=journal_path,
            outcomes_path=Path(args.output),
            now=now,
            symbol=args.symbol,
            window_minutes=args.window_minutes,
            client_factory=client_factory,
        )
        print(f"calls_journal={journal_path}")
        print(f"output={Path(args.output)}")
        print(f"scored_records={result.scored_records}")
        print(f"failed_records={result.failed_records}")
        print(f"skipped_records={result.skipped_records}")
        return 0

    if args.command == "score-live-loop":
        from synthetic_trader.live.auto_scorer import run_auto_score_loop

        mode = "single sweep" if args.once else f"loop every {args.interval:g}s"
        print(f"score-live-loop: {mode}")
        print(f"calls_journal={args.calls_journal}")
        print(f"output={args.output}")
        stats = asyncio.run(
            run_auto_score_loop(
                calls_path=args.calls_journal,
                outcomes_path=args.output,
                interval_sec=args.interval,
                symbol=args.symbol,
                window_minutes=args.window_minutes,
                status_path=args.status_path,
                run_once=args.once,
            )
        )
        for symbol_stats in stats.values():
            print(
                f"symbol={symbol_stats.symbol} "
                f"scored={symbol_stats.calls_scored} "
                f"failed={symbol_stats.calls_failed} "
                f"skipped={symbol_stats.calls_skipped} "
                f"pending={symbol_stats.calls_pending} "
                f"error={symbol_stats.error}"
            )
            if symbol_stats.warning:
                print(f"warning={symbol_stats.warning}")
        print(f"status_output={Path(args.status_path)}")
        # A scheduled sweep must be able to signal failure: exit non-zero when
        # the sweep recorded an error (MT5/Deriv unreachable, credentials
        # missing) so Task Scheduler / cron sees it instead of a false "ok".
        if args.once and any(s.error is not None for s in stats.values()):
            # Note: print to stdout (not stderr) — ``sys`` is a local name in
            # this module's main() (imported later inside a subcommand handler),
            # so referencing sys.stderr here would raise UnboundLocalError.
            print("error=sweep_failed (see status file for details)")
            return 1
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
                proven_only=args.proven_only,
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
                calls_journal_path=args.calls_journal or None,
                emit_initial=args.emit_initial,
                max_alerts=args.max_alerts,
                max_minutes=args.max_minutes,
                max_reconnects=args.max_reconnects,
                reconnect_backoff_sec=args.reconnect_backoff_sec,
                app_id=args.app_id,
                auto_score_interval_sec=args.auto_score,
                auto_score_status_path=args.auto_score_status_path,
                proven_only=args.proven_only,
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

    if args.command == "collect-live-ticks":
        from synthetic_trader.data.continuous_collector import collect_live_ticks

        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        for key, value in (
            ("SYNTHETIC_MT5_SERVER", args.mt5_server),
            ("SYNTHETIC_MT5_LOGIN", str(args.mt5_login) if args.mt5_login else None),
            ("SYNTHETIC_MT5_PASSWORD", args.mt5_password),
            ("SYNTHETIC_MT5_TERMINAL_PATH", args.mt5_terminal_path),
        ):
            if value:
                os.environ[key] = value

        results = asyncio.run(
            collect_live_ticks(
                symbols,
                output_dir=args.output_dir,
                duration_sec=args.duration_sec,
                status_path=args.status_path,
            )
        )
        for symbol, stats in results.items():
            print(f"=== {symbol} ===")
            print(stats.summary().strip())
        print(f"status_output={Path(args.status_path)}")
        return 0

    if args.command == "capture-m1":
        from synthetic_trader.data.m1_capture import run_m1_capture_loop

        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.mt5_terminal_path:
            os.environ["SYNTHETIC_MT5_TERMINAL_PATH"] = args.mt5_terminal_path

        mode = "single sweep" if args.once else f"loop every {args.interval:g}s"
        print(f"capture-m1: {mode} for {', '.join(symbols)}")
        results = asyncio.run(
            run_m1_capture_loop(
                symbols,
                output_dir=args.output_dir,
                interval_sec=args.interval,
                initial_days=args.initial_days,
                overlap_sec=args.overlap_sec,
                terminal_path=args.mt5_terminal_path,
                status_path=args.status_path,
                run_once=args.once,
            )
        )
        for symbol, stats in results.items():
            print(f"=== {symbol} ===")
            print(stats.summary().strip())
        print(f"status_output={Path(args.status_path)}")
        return 0

    if args.command == "tick-coverage":
        import sys

        # The coverage report uses arrow glyphs (→) that crash cp1252 consoles;
        # same reconfigure fix as run_wfo.py.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        from synthetic_trader.scripts.tick_coverage_stats import (
            build_coverage_report,
            render_coverage_report,
        )

        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        timeframes = [int(x) for x in args.timeframes.split(",") if x.strip()]
        horizons = [float(x) for x in args.horizon_hours.split(",") if x.strip()]
        report = build_coverage_report(
            symbols,
            engine_root=args.engine_root,
            timeframes=timeframes,
            horizon_hours=horizons,
        )
        if args.json:
            print(report.to_json())
        else:
            print(render_coverage_report(report))
        return 0

    if args.command == "tick-task-health":
        import json as _json

        from synthetic_trader.scripts.tick_task_health import (
            check_task_health,
            render_report,
        )

        report = check_task_health(
            args.engine_root,
            flat_hours=args.flat_hours,
            task_stale_hours=args.task_stale_hours,
            verify_stale_hours=args.verify_stale_hours,
        )
        if args.json:
            print(_json.dumps(report.to_dict(), indent=2))
        else:
            print(render_report(report))
        # Exit code is the alert gate: 0 = healthy, 1 = warnings fired.
        return 0 if report.healthy else 1

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

    if args.command == "backfill-mt5":
        from synthetic_trader.calibration.mt5_collector import collect_mt5_candle_history

        print(f"Backfilling {args.symbol} ({args.days:g} days) from Blueberry MT5 terminal...")
        result = collect_mt5_candle_history(
            symbol=args.symbol,
            days=args.days,
            output_path=args.output,
            venue_symbol=args.venue_symbol,
            terminal_path=args.mt5_terminal_path,
        )
        print(result.summary())
        return 0

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
        else:
            # Auto-save to the standard calibration directory so the
            # assembler's _get_garch_forecaster() picks it up on next start.
            from synthetic_trader.models.garch_calibration import save_calibrated_garch_state
            saved_path = save_calibrated_garch_state(result, args.symbol)
            print(f"\nAuto-saved calibrated parameters to {saved_path}")

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
