"""Walk-forward optimization with PBO on the collected tick data.

Runs the ``WalkForwardOptimizer`` (rolling IS/OOS windows + PBO via
CSCV-style comparison) over the real tick CSVs with realistic slippage,
and calibrates the EGARCH variance model from the same data so the live
forecaster starts with market-fitted parameters.

Usage::

    python -m synthetic_trader.research.run_wfo [--symbols R_75,R_100] [--quick]

The WFO is sized from the actual span of each CSV (the collected data is
~24h of ticks), so hour-scale windows are used instead of the day-scale
defaults.  Results are saved to ``data/research/wfo_{symbol}.json`` and
EGARCH fits to ``data/garch_calibration/{symbol}.json``.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
from synthetic_trader.research.wfo import (
    HyperparameterGrid,
    WalkForwardOptimizer,
    render_wfo_report,
)

DATA_DIR = Path("data")
RESEARCH_DIR = Path("data/research")
DEFAULT_SYMBOLS = ["R_75", "R_100"]


def dedupe_ticks(ticks: list) -> list:
    """Sort by epoch and drop exact-duplicate epochs (keep first).

    The WFO validator requires strict chronological order — the collected
    CSVs occasionally contain ticks sharing the same epoch.
    """
    seen: set = set()
    result = []
    for tick in sorted(ticks, key=lambda t: t.epoch):
        if tick.epoch in seen:
            continue
        seen.add(tick.epoch)
        result.append(tick)
    return result


def build_slippage_config() -> TraderConfig:
    """TraderConfig with realistic execution costs for the backtest.

    One tick of entry/exit slippage plus a small per-trade penalty is a
    conservative stand-in for real fills on a 4-6 hour swing trade.
    """
    base = TraderConfig.default()
    return replace(
        base,
        paper=PaperExecutionConfig(
            entry_slippage_ticks=1.0,
            exit_slippage_ticks=1.0,
            execution_penalty_per_trade=0.5,
        ),
    )


def build_param_grid(quick: bool) -> HyperparameterGrid:
    """Hyperparameter grid for in-sample optimization."""
    if quick:
        return HyperparameterGrid(
            learning_rates=[0.005, 0.02],
            l2_reg=[0.0, 0.01],
            feature_clip=[10.0],
        )
    return HyperparameterGrid()


def size_windows(span_seconds: float) -> tuple[float, float, float]:
    """Pick (is_days, oos_days, step_days) from the available data span."""
    span_hours = span_seconds / 3600.0
    if span_hours >= 30.0:
        return 0.5, 0.1667, 0.1667  # 12h IS / 4h OOS / 4h step
    if span_hours >= 16.0:
        return 0.3333, 0.0833, 0.0833  # 8h IS / 2h OOS / 2h step
    if span_hours >= 8.0:
        return 0.1667, 0.0417, 0.0417  # 4h IS / 1h OOS / 1h step
    return max(0.02, span_hours / 24.0 * 0.5), 0.02, 0.02


def resolve_wfo_csv(symbol: str) -> Path | None:
    """Pick the best tick CSV for WFO: the clean backfill corpus first.

    The continuous collector appends to ``data/backfill/{symbol}_ticks.csv``
    (correct Blueberry scale).  Fall back to the legacy ``data/`` files only
    when no backfill exists — those may contain the old Deriv-scale rows.
    """
    backfill = DATA_DIR / "backfill" / f"{symbol}_ticks.csv"
    if backfill.exists() and backfill.stat().st_size > 0:
        return backfill
    legacy = DATA_DIR / f"{symbol}_ticks.csv"
    if legacy.exists() and legacy.stat().st_size > 0:
        return legacy
    return None


def run_wfo_for_symbol(symbol: str, quick: bool, timeframe_sec: int = 300) -> None:
    """Run WFO + EGARCH calibration for one symbol."""
    csv_path = resolve_wfo_csv(symbol)
    if csv_path is None:
        print(f"[wfo] missing tick CSV for {symbol} — skipping (run collect-live-ticks first)")
        return

    started = time.time()
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    if len(ticks) < 200:
        print(f"[wfo] {symbol}: only {len(ticks)} ticks — skipping")
        return
    span_seconds = ticks[-1].epoch - ticks[0].epoch
    print(
        f"[wfo] {symbol}: {len(ticks)} ticks over {span_seconds / 3600.0:.1f}h"
    )

    is_days, oos_days, step_days = size_windows(span_seconds)
    config = build_slippage_config()
    optimizer = WalkForwardOptimizer(
        is_days=is_days,
        oos_days=oos_days,
        step_days=step_days,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=timeframe_sec * 3,
        param_grid=build_param_grid(quick),
        min_oos_trades=1,
    )

    result = None
    try:
        result = optimizer.optimize(
            ticks,
            symbol=symbol,
            config=config,
            progress_callback=lambda done, total: print(
                f"    fold {done}/{total}", flush=True
            ),
        )
    except ValueError as exc:
        print(f"[wfo] {symbol}: no viable folds — {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[wfo] {symbol}: optimization failed — {exc!r}")

    if result is None:
        print(f"[wfo] {symbol}: no walk-forward result (strategy produced no"
              " tradable setups in the OOS windows)")
    else:
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RESEARCH_DIR / f"wfo_{symbol.lower()}.json"
        optimizer.save(result, out_path)
        print(render_wfo_report(result))
        print(f"[wfo] {symbol}: saved to {out_path}")

    print(f"[wfo] {symbol}: elapsed {time.time() - started:.0f}s")

    calibrate_egarch_from_csv(symbol, csv_path)


def calibrate_egarch_from_csv(symbol: str, csv_path: Path) -> None:
    """Fit EGARCH(1,1) parameters from the tick CSV and persist them.

    Tries progressively finer bar scales (volatility clustering may live
    at sub-minute scale for these indices) and rejects degenerate fits
    whose parameters sit pinned at the optimizer bounds.
    """
    from synthetic_trader.models.garch_calibration import (
        _params_at_bounds,
        calibrate_from_ticks_csv,
        save_calibrated_garch_state,
    )

    for bar_seconds in (10, 30, 60):
        try:
            result = calibrate_from_ticks_csv(
                csv_path, symbol=symbol, bar_seconds=bar_seconds
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[wfo] {symbol}: EGARCH calibration failed at {bar_seconds}s bars — {exc!r}")
            continue
        if not result.convergence:
            continue
        if _params_at_bounds(result):
            print(
                f"[wfo] {symbol}: {bar_seconds}s-bar EGARCH fit degenerate "
                f"(alpha={result.alpha:.4f}, beta={result.beta:.4f}, "
                f"gamma={result.gamma:.4f}) — skipping"
            )
            continue
        saved = save_calibrated_garch_state(result, symbol)
        print(
            f"[wfo] {symbol}: EGARCH calibrated at {bar_seconds}s bars "
            f"(alpha={result.alpha:.4f}, beta={result.beta:.4f}, "
            f"gamma={result.gamma:.4f}, persistence={result.persistence:.4f}) -> {saved}"
        )
        return
    print(f"[wfo] {symbol}: no non-degenerate EGARCH fit at 10/30/60s bars — "
          "keeping default GARCH priors")


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252 and choke on the ✓/⚠ glyphs in
    # the rendered WFO report — force UTF-8 (best-effort).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        prog="run-wfo",
        description="Walk-forward optimization + PBO + EGARCH calibration on tick CSVs",
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="comma-separated symbols (default: R_75,R_100)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="use a smaller hyperparameter grid for faster runs",
    )
    parser.add_argument(
        "--timeframe",
        type=int,
        default=300,
        help="primary candle timeframe in seconds (default 300)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    for symbol in symbols:
        run_wfo_for_symbol(symbol, quick=args.quick, timeframe_sec=args.timeframe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
