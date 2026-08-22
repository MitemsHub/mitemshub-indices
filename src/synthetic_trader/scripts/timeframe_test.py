"""Multi-Timeframe Strategy Comparison

Tests the optimized band strategy (z_entry=2.0, stop=0.10, target=0.80/1.20)
on M5 (300s), M15 (900s), and H1 (3600s) timeframes to find the best
execution timeframe for each symbol.

Usage:
    python -m synthetic_trader.scripts.timeframe_test --symbol R_75
    python -m synthetic_trader.scripts.timeframe_test --symbol R_100
    python -m synthetic_trader.scripts.timeframe_test --symbol R_75 --symbol R_100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_band import VolBandConfig, run_vol_band_backtest
from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.config import PaperExecutionConfig
from synthetic_trader.models.garch_calibration import load_calibrated_garch_state


# ── Timeframes to test ──────────────────────────────────────────────────
TIMEFRAMES = {
    "M5":  300,    # 5-minute candles
    "M15": 900,    # 15-minute candles
    "H1":  3600,   # 1-hour candles
}

# ── Optimized band parameters (from backtest sweep) ──────────────────────
OPTIMIZED_PARAMS = {
    "R_75": {
        "z_entry": 2.0,
        "stop_sigma_mult": 0.10,
        "target_sigma_mult": 1.20,
        "max_hold_sec": 3600,
        "min_rr": 2.0,
        "max_stop_pct": 0.015,
        "warmup_candles": 60,
    },
    "R_100": {
        "z_entry": 2.0,
        "stop_sigma_mult": 0.10,
        "target_sigma_mult": 0.80,
        "max_hold_sec": 3600,
        "min_rr": 2.0,
        "max_stop_pct": 0.015,
        "warmup_candles": 60,
    },
}


@dataclass
class TimeframeResult:
    """Results for a single timeframe test."""
    symbol: str
    timeframe_name: str
    timeframe_sec: int
    n_ticks: int
    n_candles: int
    n_trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    net_pnl: float
    max_drawdown: float
    sharpe_ratio: float
    avg_rr_ratio: float
    avg_holding_sec: float
    trades_per_day: float


def run_single_timeframe(
    symbol: str,
    timeframe_name: str,
    timeframe_sec: int,
    ticks: list,
    params: dict,
) -> TimeframeResult:
    """Run the band strategy on a single timeframe and return metrics."""
    # Adjust warmup_candles proportionally for larger timeframes
    # More candles needed on longer timeframes for sufficient warmup data
    base_warmup = params["warmup_candles"]
    if timeframe_sec >= 3600:
        warmup = max(base_warmup, 30)  # H1 needs fewer candles but more data
    elif timeframe_sec >= 900:
        warmup = max(base_warmup, 40)  # M15
    else:
        warmup = base_warmup  # M5 uses default

    # Scale max_hold_sec to be compatible with the timeframe
    # A trade should hold at least 1 candle and not exceed the timeframe
    max_hold = params["max_hold_sec"]

    band_config = VolBandConfig(
        z_entry=params["z_entry"],
        stop_sigma_mult=params["stop_sigma_mult"],
        target_sigma_mult=params["target_sigma_mult"],
        max_hold_sec=max_hold,
        min_target_rr=params["min_rr"],
        max_stop_pct=params["max_stop_pct"],
        warmup_candles=warmup,
    )
    paper = PaperExecutionConfig(
        entry_slippage_ticks=0.05,
        exit_slippage_ticks=0.05,
    )
    garch_state = load_calibrated_garch_state(symbol)

    print(f"  Running {timeframe_name} ({timeframe_sec}s) backtest...")
    start = time.time()

    report = run_vol_band_backtest(
        ticks=ticks,
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        strategy_config=band_config,
        paper=paper,
        garch_state=garch_state,
    )

    elapsed = time.time() - start
    print(f"    Completed in {elapsed:.1f}s")

    metrics = report.metrics
    n_trades = metrics.trades

    if n_trades == 0:
        return TimeframeResult(
            symbol=symbol,
            timeframe_name=timeframe_name,
            timeframe_sec=timeframe_sec,
            n_ticks=len(ticks),
            n_candles=0,
            n_trades=0,
            win_rate=0, profit_factor=0, expectancy_r=0,
            net_pnl=0, max_drawdown=0, sharpe_ratio=0,
            avg_rr_ratio=0, avg_holding_sec=0, trades_per_day=0,
        )

    # Estimate candle count
    total_span = ticks[-1].epoch - ticks[0].epoch if len(ticks) > 1 else 0
    n_candles = max(1, int(total_span / timeframe_sec))

    # Calculate additional metrics from diagnostics
    max_dd = report.diagnostics.get("max_drawdown_r", 0)
    if isinstance(max_dd, (int, float)) and max_dd < 0:
        max_dd = abs(max_dd)

    # Sharpe from expectancy and net_pnl
    sharpe = 0
    if n_trades > 1:
        mean_ret = metrics.expectancy_r
        # Approximate from profit factor
        if metrics.profit_factor > 0:
            # Use simple approximation: sharpe ~ expectancy * sqrt(trades)
            sharpe = metrics.expectancy_r * (n_trades ** 0.5)

    # Average RR ratio
    avg_rr = 0
    if hasattr(metrics, 'profit_factor') and metrics.profit_factor > 0:
        # From profit factor and win rate
        avg_rr = metrics.profit_factor * metrics.win_rate / (1 - metrics.win_rate) if metrics.win_rate < 1 else 0

    # Trades per day
    trades_per_day = n_trades / (total_span / 86400) if total_span > 0 else 0

    return TimeframeResult(
        symbol=symbol,
        timeframe_name=timeframe_name,
        timeframe_sec=timeframe_sec,
        n_ticks=len(ticks),
        n_candles=n_candles,
        n_trades=n_trades,
        win_rate=metrics.win_rate * 100,  # Convert to percentage
        profit_factor=metrics.profit_factor,
        expectancy_r=metrics.expectancy_r,
        net_pnl=metrics.net_pnl,
        max_drawdown=float(max_dd),
        sharpe_ratio=sharpe,
        avg_rr_ratio=avg_rr,
        avg_holding_sec=max_hold,
        trades_per_day=trades_per_day,
    )


def print_results_table(results: list[TimeframeResult]) -> None:
    """Print a formatted comparison table."""
    print(f"\n{'='*100}")
    print(f"  TIMEFRAME COMPARISON: {results[0].symbol}")
    print(f"{'='*100}")
    print(f"  {'Metric':<22} {'M5 (5m)':>14} {'M15 (15m)':>14} {'H1 (1h)':>14}")
    print(f"  {'-'*64}")

    # Collect values for each timeframe
    m5 = next((r for r in results if r.timeframe_name == "M5"), None)
    m15 = next((r for r in results if r.timeframe_name == "M15"), None)
    h1 = next((r for r in results if r.timeframe_name == "H1"), None)

    def fmt(r, attr, fmt_str="{:>14.2f}"):
        val = getattr(r, attr) if r else 0
        return fmt_str.format(val)

    print(f"  {'Trades':<22} {fmt(m5, 'n_trades', '{:>14d}')} {fmt(m15, 'n_trades', '{:>14d}')} {fmt(h1, 'n_trades', '{:>14d}')}")
    print(f"  {'Win Rate %':<22} {fmt(m5, 'win_rate')} {fmt(m15, 'win_rate')} {fmt(h1, 'win_rate')}")
    print(f"  {'Profit Factor':<22} {fmt(m5, 'profit_factor')} {fmt(m15, 'profit_factor')} {fmt(h1, 'profit_factor')}")
    print(f"  {'Expectancy (R)':<22} {fmt(m5, 'expectancy_r', '{:>+14.4f}')} {fmt(m15, 'expectancy_r', '{:>+14.4f}')} {fmt(h1, 'expectancy_r', '{:>+14.4f}')}")
    print(f"  {'Net PnL (R)':<22} {fmt(m5, 'net_pnl', '{:>+14.4f}')} {fmt(m15, 'net_pnl', '{:>+14.4f}')} {fmt(h1, 'net_pnl', '{:>+14.4f}')}")
    print(f"  {'Max Drawdown (R)':<22} {fmt(m5, 'max_drawdown', '{:>14.4f}')} {fmt(m15, 'max_drawdown', '{:>14.4f}')} {fmt(h1, 'max_drawdown', '{:>14.4f}')}")
    print(f"  {'Sharpe Ratio':<22} {fmt(m5, 'sharpe_ratio')} {fmt(m15, 'sharpe_ratio')} {fmt(h1, 'sharpe_ratio')}")
    print(f"  {'Avg R:R':<22} {fmt(m5, 'avg_rr_ratio')} {fmt(m15, 'avg_rr_ratio')} {fmt(h1, 'avg_rr_ratio')}")
    print(f"  {'Trades/Day':<22} {fmt(m5, 'trades_per_day')} {fmt(m15, 'trades_per_day')} {fmt(h1, 'trades_per_day')}")

    # Find best timeframe
    valid = [r for r in results if r.n_trades >= 5]
    if valid:
        # Score: expectancy * profit_factor * min(trades_per_day, 10)
        # Penalize too few or too many trades
        def score(r):
            trade_score = min(r.n_trades / 10, 1.0)  # Reward at least 10 trades
            freq_score = min(r.trades_per_day, 10) / 10  # Sweet spot: ~5-10/day
            return r.expectancy_r * r.profit_factor * trade_score * (0.5 + 0.5 * freq_score)

        best = max(valid, key=score)
        print(f"\n  >>> RECOMMENDED: {best.timeframe_name} ({best.timeframe_sec}s)")
        print(f"      Reason: Best balance of expectancy ({best.expectancy_r:+.4f}R), "
              f"profit factor ({best.profit_factor:.2f}), and trade frequency ({best.trades_per_day:.1f}/day)")
    else:
        print(f"\n  >>> INSUFFICIENT DATA: Need at least 5 trades per timeframe")

    print(f"{'='*100}")


def run_timeframe_comparison(
    symbol: str,
    csv_path: str | Path,
) -> list[TimeframeResult]:
    """Run the band strategy across all timeframes and compare."""
    params = OPTIMIZED_PARAMS[symbol]

    print(f"\n{'#'*100}")
    print(f"  MULTI-TIMEFRAME TEST: {symbol}")
    print(f"  Optimized params: z={params['z_entry']}, stop={params['stop_sigma_mult']}, "
          f"target={params['target_sigma_mult']}")
    print(f"  Testing timeframes: M5 (300s), M15 (900s), H1 (3600s)")
    print(f"{'#'*100}")

    # Load tick data
    print(f"\n[1/4] Loading tick data from {csv_path}...")
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    total_ticks = len(ticks)
    print(f"       {total_ticks:,} ticks loaded")

    if total_ticks < 1000:
        print(f"       WARNING: Very few ticks ({total_ticks}). Results may be unreliable.")
        print(f"       Need at least ~10,000 ticks for meaningful timeframe comparison.")

    # Run each timeframe
    print(f"\n[2/4] Running backtests across timeframes...")
    results = []
    for tf_name, tf_sec in TIMEFRAMES.items():
        result = run_single_timeframe(symbol, tf_name, tf_sec, ticks, params)
        results.append(result)

    # Print comparison table
    print(f"\n[3/4] Comparison results:")
    print_results_table(results)

    # Print individual timeframe details
    print(f"\n[4/4] Detailed timeframe analysis:")
    for result in results:
        print(f"\n  --- {result.timeframe_name} ({result.timeframe_sec}s) ---")
        if result.n_trades == 0:
            print(f"  No trades generated")
            continue
        print(f"  Candles analyzed: {result.n_candles:,}")
        print(f"  Trades: {result.n_trades}")
        print(f"  Win Rate: {result.win_rate:.1f}%")
        print(f"  Profit Factor: {result.profit_factor:.2f}")
        print(f"  Expectancy: {result.expectancy_r:+.4f}R per trade")
        print(f"  Net PnL: {result.net_pnl:+.4f}R")
        print(f"  Max Drawdown: {result.max_drawdown:.4f}R")
        print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"  Avg R:R: {result.avg_rr_ratio:.2f}")
        print(f"  Trade Frequency: {result.trades_per_day:.2f} trades/day")

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Multi-timeframe strategy comparison")
    parser.add_argument(
        "--symbol", action="append", choices=["R_75", "R_100"],
        help="Symbol(s) to test (repeat for multiple)",
    )
    args = parser.parse_args(argv)

    symbols = args.symbol or ["R_75", "R_100"]
    all_results = []

    for symbol in symbols:
        csv_path = Path("data/backfill") / f"{symbol}_ticks.csv"
        if not csv_path.exists():
            print(f"ERROR: {csv_path} not found", file=sys.stderr)
            return 1
        results = run_timeframe_comparison(symbol, csv_path)
        all_results.extend(results)

    # Final recommendation
    print(f"\n{'#'*100}")
    print(f"  FINAL RECOMMENDATION")
    print(f"{'#'*100}")

    for symbol in symbols:
        symbol_results = [r for r in all_results if r.symbol == symbol and r.n_trades >= 5]
        if symbol_results:
            # Score each timeframe
            def score(r):
                trade_score = min(r.n_trades / 10, 1.0)
                freq_score = min(r.trades_per_day, 10) / 10
                return r.expectancy_r * r.profit_factor * trade_score * (0.5 + 0.5 * freq_score)

            best = max(symbol_results, key=score)
            print(f"\n  {symbol}:")
            print(f"    Best timeframe: {best.timeframe_name} ({best.timeframe_sec}s)")
            print(f"    Expectancy: {best.expectancy_r:+.4f}R per trade")
            print(f"    Profit Factor: {best.profit_factor:.2f}")
            print(f"    Win Rate: {best.win_rate:.1f}%")
            print(f"    Trade Frequency: {best.trades_per_day:.1f} trades/day")
            print(f"    Net PnL: {best.net_pnl:+.4f}R")
        else:
            print(f"\n  {symbol}: Insufficient data for recommendation")

    # Save results
    output_path = Path("data") / "timeframe_comparison.json"
    output_data = []
    for r in all_results:
        output_data.append({
            "symbol": r.symbol,
            "timeframe": r.timeframe_name,
            "timeframe_sec": r.timeframe_sec,
            "n_ticks": r.n_ticks,
            "n_candles": r.n_candles,
            "n_trades": r.n_trades,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "expectancy_r": r.expectancy_r,
            "net_pnl": r.net_pnl,
            "max_drawdown": r.max_drawdown,
            "sharpe_ratio": r.sharpe_ratio,
            "avg_rr_ratio": r.avg_rr_ratio,
            "trades_per_day": r.trades_per_day,
        })

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"\n  Results saved to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
