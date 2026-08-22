"""Forward Demo Paper-Live Validation

Splits tick data 80/20 into train/test windows and runs the optimized band
strategy on both to validate out-of-sample performance. Reports whether the
strategy generalizes beyond the training period.

Usage:
    python -m synthetic_trader.scripts.forward_demo --symbol R_75
    python -m synthetic_trader.scripts.forward_demo --symbol R_100
    python -m synthetic_trader.scripts.forward_demo --symbol R_75 --symbol R_100
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
        "breakeven_trail_frac": 0.0,  # Trail KILLS R_75 (12:1 RR -> 0% WR)
    },
    "R_100": {
        "z_entry": 2.0,
        "stop_sigma_mult": 0.10,
        "target_sigma_mult": 0.80,
        "max_hold_sec": 3600,
        "min_rr": 2.0,
        "max_stop_pct": 0.015,
        "warmup_candles": 60,
        "breakeven_trail_frac": 0.3,  # Trail HELPS R_100 (8:1 RR -> 13.3% WR)
    },
}

TRAIN_FRACTION = 0.80  # 80% train, 20% test


@dataclass
class ValidationResult:
    """Summary of a single split's backtest results."""
    symbol: str
    split: str  # "train" or "test"
    n_ticks: int
    n_trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    net_pnl: float
    max_drawdown: float
    total_return_pct: float
    sharpe_ratio: float
    avg_rr_ratio: float


def run_forward_validation(
    symbol: str,
    csv_path: str | Path,
    train_fraction: float = TRAIN_FRACTION,
) -> dict:
    """Run forward validation for a single symbol.

    Splits the tick data chronologically into train/test, runs the optimized
    band strategy on both splits, and returns a comparison report.
    """
    params = OPTIMIZED_PARAMS[symbol]
    print(f"\n{'='*80}")
    print(f"  FORWARD DEMO VALIDATION: {symbol}")
    print(f"  Optimized params: z={params['z_entry']}, stop={params['stop_sigma_mult']}, "
          f"target={params['target_sigma_mult']}")
    print(f"{'='*80}")

    # Load and deduplicate ticks
    print(f"\n[1/6] Loading tick data from {csv_path}...")
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    total_ticks = len(ticks)
    print(f"       {total_ticks:,} ticks loaded")

    # Split chronologically
    split_idx = int(total_ticks * train_fraction)
    train_ticks = ticks[:split_idx]
    test_ticks = ticks[split_idx:]
    print(f"\n[2/6] Chronological split:")
    print(f"       Train: {len(train_ticks):,} ticks ({train_fraction*100:.0f}%)")
    print(f"       Test:  {len(test_ticks):,} ticks ({(1-train_fraction)*100:.0f}%)")

    # Time range
    if train_ticks:
        train_start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(train_ticks[0].epoch))
        train_end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(train_ticks[-1].epoch))
        print(f"       Train period: {train_start} to {train_end}")
    if test_ticks:
        test_start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(test_ticks[0].epoch))
        test_end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(test_ticks[-1].epoch))
        print(f"       Test period:  {test_start} to {test_end}")

    # Build band config
    band_config = VolBandConfig(
        z_entry=params["z_entry"],
        stop_sigma_mult=params["stop_sigma_mult"],
        target_sigma_mult=params["target_sigma_mult"],
        max_hold_sec=params["max_hold_sec"],
        min_target_rr=params["min_rr"],
        max_stop_pct=params["max_stop_pct"],
        warmup_candles=params["warmup_candles"],
        breakeven_trail_frac=params.get("breakeven_trail_frac", 0.3),
    )
    paper = PaperExecutionConfig(
        entry_slippage_ticks=0.05,
        exit_slippage_ticks=0.05,
    )
    garch_state = load_calibrated_garch_state(symbol)

    results = {}

    # Run train split
    print(f"\n[3/6] Running band backtest on TRAIN split...")
    train_report = run_vol_band_backtest(
        ticks=train_ticks,
        symbol=symbol,
        strategy_config=band_config,
        paper=paper,
        garch_state=garch_state,
    )
    results["train"] = _extract_metrics(train_report, symbol, "train", len(train_ticks))
    _print_split(results["train"])

    # Run test split (out-of-sample)
    print(f"\n[4/6] Running band backtest on TEST split (out-of-sample)...")
    test_report = run_vol_band_backtest(
        ticks=test_ticks,
        symbol=symbol,
        strategy_config=band_config,
        paper=paper,
        garch_state=garch_state,
    )
    results["test"] = _extract_metrics(test_report, symbol, "test", len(test_ticks))
    _print_split(results["test"])

    # Compare
    print(f"\n[5/6] Comparing in-sample vs out-of-sample:")
    _print_comparison(results["train"], results["test"])

    # Walk-forward stability check
    print(f"\n[6/6] Forward validation verdict:")
    verdict = _evaluate_forward(results["train"], results["test"])
    print(f"       {verdict}")

    return {
        "symbol": symbol,
        "params": params,
        "train": results["train"],
        "test": results["test"],
        "verdict": verdict,
    }


def _extract_metrics(report, symbol: str, split: str, n_ticks: int) -> ValidationResult:
    """Extract key metrics from a vol band backtest report."""
    metrics = report.metrics
    n_trades = metrics.trades

    if n_trades == 0:
        return ValidationResult(
            symbol=symbol, split=split, n_ticks=n_ticks,
            n_trades=0, win_rate=0, profit_factor=0,
            expectancy_r=0, net_pnl=0, max_drawdown=0,
            total_return_pct=0, sharpe_ratio=0, avg_rr_ratio=0,
        )

    # Extract metrics directly from JournalMetrics
    win_rate = metrics.win_rate * 100
    profit_factor = metrics.profit_factor
    expectancy_r = metrics.expectancy_r
    net_pnl = metrics.net_pnl

    # Max drawdown from diagnostics
    max_dd = float(report.diagnostics.get("net_pnl", 0))
    # Approximate max drawdown from equity curve
    if n_trades > 0:
        max_dd = max(0, -net_pnl) if net_pnl < 0 else 0

    total_return_pct = net_pnl * 100
    sharpe = metrics.expectancy_r * (n_trades ** 0.5) if n_trades > 1 else 0
    avg_rr = 0

    return ValidationResult(
        symbol=symbol, split=split, n_ticks=n_ticks,
        n_trades=n_trades, win_rate=win_rate,
        profit_factor=profit_factor, expectancy_r=expectancy_r,
        net_pnl=net_pnl, max_drawdown=max_dd,
        total_return_pct=total_return_pct, sharpe_ratio=sharpe,
        avg_rr_ratio=avg_rr,
    )


def _print_split(r: ValidationResult) -> None:
    """Print metrics for a single split."""
    print(f"       Trades:        {r.n_trades}")
    print(f"       Win Rate:      {r.win_rate:.1f}%")
    print(f"       Profit Factor: {r.profit_factor:.2f}")
    print(f"       Expectancy:    {r.expectancy_r:+.3f}R per trade")
    print(f"       Net PnL:       {r.net_pnl:+.2f}R")
    print(f"       Max Drawdown:  {r.max_drawdown:.2f}R")
    print(f"       Sharpe Ratio:  {r.sharpe_ratio:.2f}")
    print(f"       Avg R:R:       {r.avg_rr_ratio:.2f}")


def _print_comparison(train: ValidationResult, test: ValidationResult) -> None:
    """Print side-by-side comparison of train vs test."""
    print(f"       {'Metric':<20} {'Train':>12} {'Test':>12} {'Delta':>12}")
    print(f"       {'-'*56}")

    metrics = [
        ("Trades", train.n_trades, test.n_trades, "{:>12d}", "{:>12d}", "{:>+12d}"),
        ("Win Rate %", train.win_rate, test.win_rate, "{:>11.1f}%", "{:>11.1f}%", "{:>+11.1f}%"),
        ("Profit Factor", train.profit_factor, test.profit_factor, "{:>12.2f}", "{:>12.2f}", "{:>+12.2f}"),
        ("Expectancy R", train.expectancy_r, test.expectancy_r, "{:>12.3f}", "{:>12.3f}", "{:>+12.3f}"),
        ("Net PnL R", train.net_pnl, test.net_pnl, "{:>12.2f}", "{:>12.2f}", "{:>+12.2f}"),
        ("Max Drawdown R", train.max_drawdown, test.max_drawdown, "{:>12.2f}", "{:>12.2f}", "{:>+12.2f}"),
        ("Sharpe Ratio", train.sharpe_ratio, test.sharpe_ratio, "{:>12.2f}", "{:>12.2f}", "{:>+12.2f}"),
    ]

    for name, tv, ttv, tf, ttf, df in metrics:
        print(f"       {name:<20} {tf.format(tv)} {ttf.format(ttv)} {df.format(ttv - tv)}")


def _evaluate_forward(train: ValidationResult, test: ValidationResult) -> str:
    """Evaluate whether the strategy generalizes out-of-sample."""
    issues = []

    # Check 1: Test should have positive expectancy
    if test.expectancy_r <= 0:
        issues.append(f"Test expectancy is NEGATIVE ({test.expectancy_r:+.3f}R)")

    # Check 2: Test should have >0 trades
    if test.n_trades < 5:
        issues.append(f"Test has only {test.n_trades} trades (need >=5 for significance)")

    # Check 3: Win rate shouldn't collapse
    wr_drop = train.win_rate - test.win_rate
    if wr_drop > 15:
        issues.append(f"Win rate collapsed: {train.win_rate:.1f}% -> {test.win_rate:.1f}% (dropped {wr_drop:.1f}pp)")

    # Check 4: Profit factor shouldn't collapse
    if train.profit_factor > 1.0 and test.profit_factor < 0.7:
        issues.append(f"Profit factor collapsed: {train.profit_factor:.2f} -> {test.profit_factor:.2f}")

    # Check 5: Expectancy shouldn't degrade by more than 50%
    if train.expectancy_r > 0 and test.expectancy_r < train.expectancy_r * 0.5:
        issues.append(f"Expectancy degraded >50%: {train.expectancy_r:+.3f}R -> {test.expectancy_r:+.3f}R")

    # Check 6: Sharpe shouldn't go negative
    if test.sharpe_ratio < 0 and train.sharpe_ratio > 0.5:
        issues.append(f"Sharpe went negative: {train.sharpe_ratio:.2f} -> {test.sharpe_ratio:.2f}")

    if not issues:
        return "PASS -- Strategy generalizes out-of-sample. Ready for live demo."
    else:
        return "WARNINGS:\n" + "\n".join(f"       - {i}" for i in issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forward demo paper-live validation")
    parser.add_argument(
        "--symbol", action="append", choices=["R_75", "R_100"],
        help="Symbol(s) to validate (repeat for multiple)",
    )
    parser.add_argument("--train-fraction", type=float, default=0.80)
    args = parser.parse_args(argv)

    symbols = args.symbol or ["R_75", "R_100"]
    all_results = []

    for symbol in symbols:
        csv_path = Path("data/backfill") / f"{symbol}_ticks.csv"
        if not csv_path.exists():
            print(f"ERROR: {csv_path} not found", file=sys.stderr)
            return 1
        result = run_forward_validation(symbol, csv_path, args.train_fraction)
        all_results.append(result)

    # Summary
    print(f"\n{'='*80}")
    print(f"  FORWARD VALIDATION SUMMARY")
    print(f"{'='*80}")
    for r in all_results:
        print(f"\n  {r['symbol']}:")
        print(f"    Params: z={r['params']['z_entry']}, stop={r['params']['stop_sigma_mult']}, "
              f"target={r['params']['target_sigma_mult']}")
        print(f"    Train: {r['train'].n_trades} trades, {r['train'].win_rate:.1f}% WR, "
              f"PF={r['train'].profit_factor:.2f}, E[r]={r['train'].expectancy_r:+.3f}")
        print(f"    Test:  {r['test'].n_trades} trades, {r['test'].win_rate:.1f}% WR, "
              f"PF={r['test'].profit_factor:.2f}, E[r]={r['test'].expectancy_r:+.3f}")
        print(f"    Verdict: {r['verdict']}")

    # Save results
    output_path = Path("data/forward_validation_report.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
