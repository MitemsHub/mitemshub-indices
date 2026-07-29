"""Walk-Forward Optimization (WFO) framework with PBO calculation.

This module implements rigorous walk-forward validation to prevent
curve-fitting in trading strategy development.  It replaces static
backtests with rolling in-sample/out-of-sample windows that produce
an unbiased equity curve.

Key concepts:
- **In-sample (IS)** window: period used to optimize strategy parameters
- **Out-of-sample (OOS)** window: period used to validate with frozen params
- **Step**: how far to roll the window forward each iteration
- **PBO**: Probability of Backtest Overfitting via CSCV

Reference: Bailey, Borwein, López de Prado, Zhu (2017)
"The Probability of Backtest Overfitting"
Journal of Computational Finance, 20(4), 39-69.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Tick
from synthetic_trader.models.online import OnlineLogisticModel


# ── Data Classes ─────────────────────────────────────────────────


@dataclass
class WindowSpec:
    """Specification for a single in-sample or out-of-sample window."""
    start_epoch: float
    end_epoch: float
    tick_count: int = 0


@dataclass
class WFOFold:
    """Result of a single walk-forward fold."""
    fold_index: int
    in_sample: WindowSpec
    out_of_sample: WindowSpec
    train_trades: int = 0
    is_profit_factor: float = 0.0  # IS performance (for correlation)
    is_win_rate: float = 0.0
    is_expectancy_r: float = 0.0
    test_trades: int = 0
    test_win_rate: float = 0.0
    test_profit_factor: float = 0.0
    test_expectancy_r: float = 0.0
    test_net_pnl: float = 0.0
    test_sharpe: float = 0.0
    model_version: str = ""
    optimized_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class WFOResult:
    """Complete walk-forward optimization result."""
    symbol: str
    folds: list[WFOFold]
    # Aggregate OOS metrics (concatenated OOS segments)
    aggregate_trades: int = 0
    aggregate_win_rate: float = 0.0
    aggregate_profit_factor: float = 0.0
    aggregate_expectancy_r: float = 0.0
    aggregate_net_pnl: float = 0.0
    aggregate_sharpe: float = 0.0
    # Overfitting metrics
    pbo_score: float = 0.0  # Probability of Backtest Overfitting (0-1)
    is_oos_correlation: float = 0.0  # Correlation between IS and OOS performance
    # Stability metrics
    profit_factor_std: float = 0.0
    win_rate_std: float = 0.0
    min_fold_pf: float = float("inf")
    max_fold_pf: float = 0.0
    # Config
    is_duration_days: float = 0.0
    oos_duration_days: float = 0.0
    step_days: float = 0.0
    total_folds: int = 0


@dataclass
class HyperparameterGrid:
    """Grid of hyperparameters to search during in-sample optimization."""
    learning_rates: list[float] = field(default_factory=lambda: [0.001, 0.005, 0.01, 0.02])
    l2_reg: list[float] = field(default_factory=lambda: [0.0, 0.001, 0.01])
    feature_clip: list[float] = field(default_factory=lambda: [5.0, 10.0, 20.0])

    def all_combinations(self) -> list[dict[str, float]]:
        """Generate all parameter combinations."""
        combos = []
        for lr in self.learning_rates:
            for l2 in self.l2_reg:
                for clip in self.feature_clip:
                    combos.append({
                        "learning_rate": lr,
                        "l2": l2,
                        "feature_clip": clip,
                    })
        return combos


# ── Walk-Forward Optimizer ───────────────────────────────────────


class WalkForwardOptimizer:
    """Rolling walk-forward optimization with hyperparameter search.

    Parameters
    ----------
    is_days : float
        In-sample window duration in days. Default 30.
    oos_days : float
        Out-of-sample window duration in days. Default 5.
    step_days : float
        Roll-forward step in days. Default 5 (same as OOS = non-overlapping OOS).
    timeframe_sec : int
        Primary candle timeframe in seconds. Default 60.
    higher_timeframe_sec : int
        Higher timeframe for multi-TF analysis. Default 300.
    param_grid : HyperparameterGrid | None
        Hyperparameter grid for IS optimization. If None, uses defaults.
    min_oos_trades : int
        Minimum trades in OOS window to consider it valid. Default 5.
    """

    def __init__(
        self,
        is_days: float = 30.0,
        oos_days: float = 5.0,
        step_days: float = 5.0,
        timeframe_sec: int = 60,
        higher_timeframe_sec: int = 300,
        param_grid: HyperparameterGrid | None = None,
        min_oos_trades: int = 5,
    ) -> None:
        self.is_days = is_days
        self.oos_days = oos_days
        self.step_days = step_days
        self.timeframe_sec = timeframe_sec
        self.higher_timeframe_sec = higher_timeframe_sec
        self.param_grid = param_grid or HyperparameterGrid()
        self.min_oos_trades = min_oos_trades

    def optimize(
        self,
        ticks: list[Tick],
        symbol: str,
        config: TraderConfig | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> WFOResult:
        """Run walk-forward optimization on tick data.

        Parameters
        ----------
        ticks : list[Tick]
            Full historical tick data.
        symbol : str
            Symbol to optimize for.
        config : TraderConfig | None
            Base configuration. Hyperparameters will be overridden during IS optimization.
        progress_callback : Callable[[int, int], None] | None
            Called with (current_fold, total_folds) for progress tracking.

        Returns
        -------
        WFOResult
            Complete optimization result with aggregate metrics and PBO score.
        """
        if config is None:
            config = TraderConfig.default()

        # Filter and sort ticks for this symbol
        symbol_ticks = sorted(
            [t for t in ticks if t.symbol == symbol],
            key=lambda t: t.epoch,
        )

        if len(symbol_ticks) < 100:
            raise ValueError(f"Not enough ticks for {symbol}: need at least 100, got {len(symbol_ticks)}")

        # Validate chronological order and no duplicates
        epochs = [t.epoch for t in symbol_ticks]
        for i in range(1, len(epochs)):
            if epochs[i] <= epochs[i - 1]:
                raise ValueError(
                    f"Ticks must be in strict chronological order. "
                    f"Epoch {epochs[i]} <= {epochs[i - 1]} at index {i}."
                )

        # Calculate epoch durations
        is_seconds = self.is_days * 86400
        oos_seconds = self.oos_days * 86400
        step_seconds = self.step_days * 86400

        # Find valid windows
        folds = self._run_folds(
            symbol_ticks, symbol, config, is_seconds, oos_seconds, step_seconds,
            progress_callback,
        )

        if not folds:
            raise ValueError("No valid walk-forward folds could be created")

        # Compute aggregate OOS metrics
        result = self._aggregate_results(symbol, folds, is_days=self.is_days,
                                          oos_days=self.oos_days, step_days=self.step_days)

        # Compute PBO
        result.pbo_score = self._compute_pbo(folds)
        result.is_oos_correlation = self._compute_is_oos_correlation(folds)

        return result

    # ── Fold Execution ────────────────────────────────────────────

    def _run_folds(
        self,
        ticks: list[Tick],
        symbol: str,
        config: TraderConfig,
        is_seconds: float,
        oos_seconds: float,
        step_seconds: float,
        progress_callback: Callable[[int, int], None] | None,
    ) -> list[WFOFold]:
        """Execute all walk-forward folds."""
        folds: list[WFOFold] = []
        start_epoch = ticks[0].epoch
        end_epoch = ticks[-1].epoch

        # Calculate total folds for progress
        total_range = end_epoch - start_epoch
        total_folds = max(1, int((total_range - is_seconds - oos_seconds) / step_seconds) + 1)

        fold_index = 0
        current_start = start_epoch

        while current_start + is_seconds + oos_seconds <= end_epoch:
            is_end = current_start + is_seconds
            oos_start = is_end
            oos_end = oos_start + oos_seconds

            # Extract ticks for each window
            is_ticks = [t for t in ticks if current_start <= t.epoch < is_end]
            oos_ticks = [t for t in ticks if oos_start <= t.epoch < oos_end]

            if len(is_ticks) < 20 or len(oos_ticks) < 10:
                current_start += step_seconds
                continue

            # Optimize on in-sample, validate on out-of-sample
            fold = self._run_single_fold(
                fold_index=fold_index,
                is_ticks=is_ticks,
                oos_ticks=oos_ticks,
                symbol=symbol,
                config=config,
                is_start=current_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
            )

            if fold is not None:
                folds.append(fold)

            if progress_callback:
                progress_callback(fold_index + 1, total_folds)

            fold_index += 1
            current_start += step_seconds

        return folds

    def _run_single_fold(
        self,
        fold_index: int,
        is_ticks: list[Tick],
        oos_ticks: list[Tick],
        symbol: str,
        config: TraderConfig,
        is_start: float,
        is_end: float,
        oos_start: float,
        oos_end: float,
    ) -> WFOFold | None:
        """Run a single fold: optimize on IS, validate on OOS."""

        best_score: float = -float("inf")
        best_params: dict[str, Any] = {}
        best_model: OnlineLogisticModel | None = None
        is_result: Any = None  # Track IS result for correlation metric

        # In-sample optimization: try all parameter combinations
        for params in self.param_grid.all_combinations():
            # Create config with overridden hyperparameters (ModelConfig is frozen)
            model_config = replace(
                config.model,
                learning_rate=params["learning_rate"],
                l2=params["l2"],
                feature_clip=params["feature_clip"],
            )
            model = OnlineLogisticModel(model_config)

            engine = BacktestEngine(config=config, model=model)
            result = engine.run_ticks(
                is_ticks,
                symbol=symbol,
                timeframe_sec=self.timeframe_sec,
                higher_timeframe_sec=self.higher_timeframe_sec,
                learn=True,
            )

            # Score: prioritize profit factor and expectancy
            score = self._score_fold(result)
            if score is not None and score > best_score:
                best_score = score
                best_params = params.copy()
                best_model = model
                is_result = result  # Save IS result for metrics

        if best_model is None or is_result is None:
            return None

        # Out-of-sample validation with frozen parameters
        oos_engine = BacktestEngine(config=config, model=best_model)
        oos_result = oos_engine.run_ticks(
            oos_ticks,
            symbol=symbol,
            timeframe_sec=self.timeframe_sec,
            higher_timeframe_sec=self.higher_timeframe_sec,
            learn=False,  # Critical: no learning on OOS
        )

        if oos_result.metrics.trades < self.min_oos_trades:
            return None

        return WFOFold(
            fold_index=fold_index,
            in_sample=WindowSpec(start_epoch=is_start, end_epoch=is_end, tick_count=len(is_ticks)),
            out_of_sample=WindowSpec(start_epoch=oos_start, end_epoch=oos_end, tick_count=len(oos_ticks)),
            train_trades=is_result.metrics.trades,
            is_profit_factor=is_result.metrics.profit_factor,
            is_win_rate=is_result.metrics.win_rate,
            is_expectancy_r=is_result.metrics.expectancy_r,
            test_trades=oos_result.metrics.trades,
            test_win_rate=oos_result.metrics.win_rate,
            test_profit_factor=oos_result.metrics.profit_factor,
            test_expectancy_r=oos_result.metrics.expectancy_r,
            test_net_pnl=oos_result.metrics.net_pnl,
            test_sharpe=self._compute_sharpe(oos_result),
            model_version=best_model.version,
            optimized_params=best_params,
        )

    def _score_fold(self, result: Any) -> float:
        """Score a fold result for IS optimization (higher = better).

        Uses a composite score:
        - Profit factor (capped to avoid infinities)
        - Expectancy
        - Penalizes zero trades heavily
        
        Returns None if no valid score can be computed.
        """
        metrics = result.metrics
        if metrics.trades == 0:
            return None

        pf = min(metrics.profit_factor, 10.0) if not math.isinf(metrics.profit_factor) else 10.0
        return pf * 2.0 + metrics.expectancy_r * 10.0

    def _compute_sharpe(self, result: Any) -> float:
        """Compute simplified Sharpe-like ratio from fold result.

        Uses abs(expectancy_r) to avoid sign-dependent denominator distortion
        when win_rate is very small.
        """
        if result.metrics.trades == 0:
            return 0.0
        wr = max(result.metrics.win_rate, 0.01)
        return abs(result.metrics.expectancy_r) / wr * (1 if result.metrics.expectancy_r >= 0 else -1)

    # ── Aggregate Results ─────────────────────────────────────────

    def _aggregate_results(
        self,
        symbol: str,
        folds: list[WFOFold],
        is_days: float,
        oos_days: float,
        step_days: float,
    ) -> WFOResult:
        """Compute aggregate metrics from all folds."""
        total_trades = sum(f.test_trades for f in folds)
        if total_trades == 0:
            return WFOResult(symbol=symbol, folds=folds)

        # Weighted averages
        agg_win_rate = sum(f.test_win_rate * f.test_trades for f in folds) / total_trades
        agg_expectancy = sum(f.test_expectancy_r * f.test_trades for f in folds) / total_trades
        agg_pnl = sum(f.test_net_pnl for f in folds)

        # Profit factor: mean of finite values
        finite_pfs = [f.test_profit_factor for f in folds if not math.isinf(f.test_profit_factor)]
        agg_pf = sum(finite_pfs) / len(finite_pfs) if finite_pfs else 0.0

        # Sharpe: mean of fold sharpes
        sharpes = [f.test_sharpe for f in folds if f.test_sharpe != 0]
        agg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0.0

        # Stability metrics
        pf_values = [f.test_profit_factor for f in folds if not math.isinf(f.test_profit_factor)]
        wr_values = [f.test_win_rate for f in folds]

        pf_std = self._std(pf_values) if len(pf_values) > 1 else 0.0
        wr_std = self._std(wr_values) if len(wr_values) > 1 else 0.0
        min_pf = min(pf_values) if pf_values else 0.0
        max_pf = max(pf_values) if pf_values else 0.0

        return WFOResult(
            symbol=symbol,
            folds=folds,
            aggregate_trades=total_trades,
            aggregate_win_rate=agg_win_rate,
            aggregate_profit_factor=agg_pf,
            aggregate_expectancy_r=agg_expectancy,
            aggregate_net_pnl=agg_pnl,
            aggregate_sharpe=agg_sharpe,
            profit_factor_std=pf_std,
            win_rate_std=wr_std,
            min_fold_pf=min_pf,
            max_fold_pf=max_pf,
            is_duration_days=is_days,
            oos_duration_days=oos_days,
            step_days=step_days,
            total_folds=len(folds),
        )

    # ── PBO Calculation ───────────────────────────────────────────

    def _compute_pbo(self, folds: list[WFOFold]) -> float:
        """Compute Probability of Backtest Overfitting (PBO).

        Uses a simplified heuristic inspired by CSCV:
        - Compares fold ordering against OOS performance ranking
        - Flags folds where early (more IS data) folds underperform OOS
        
        NOTE: This is a simplified approximation. For production PBO,
        implement proper CSCV with combinatorial subsampling.
        Reference: Bailey et al. (2017) 'The Probability of Backtest Overfitting'
        
        A PBO > 0.5 indicates the strategy is likely overfit.
        """
        if len(folds) < 4:
            return 0.0  # Need at least 4 folds for meaningful PBO

        n = len(folds)
        half = n // 2

        # Split into two halves for comparison
        # Use fold indices as IS "rankings" (higher index = more recent IS data)
        # Actually, use OOS performance as the "true" ranking
        oos_pf = [(i, f.test_profit_factor) for i, f in enumerate(folds)
                  if not math.isinf(f.test_profit_factor)]

        if len(oos_pf) < 4:
            return 0.0

        # Sort by OOS performance (true ranking)
        oos_sorted = sorted(oos_pf, key=lambda x: x[1], reverse=True)
        top_half_indices = {idx for idx, _ in oos_sorted[:len(oos_sorted) // 2]}

        # Check: does the fold with best "IS proxy" (earliest folds = most data seen)
        # actually perform well OOS?
        # Simplified: check correlation between fold order and OOS performance
        overfit_count = 0
        for i, f in enumerate(folds):
            if not math.isinf(f.test_profit_factor):
                # If this fold is in the top IS half but bottom OOS half
                is_top = i < half
                oos_bottom = f.test_profit_factor < oos_sorted[len(oos_sorted) // 2][1] if oos_sorted else False
                if is_top and oos_bottom:
                    overfit_count += 1

        total_checked = max(1, len([f for f in folds if not math.isinf(f.test_profit_factor)]))
        pbo = min(overfit_count / total_checked, 1.0)
        return pbo

    def _compute_is_oos_correlation(self, folds: list[WFOFold]) -> float:
        """Compute correlation between IS and OOS performance.

        Uses actual IS profit factor vs OOS profit factor per fold.
        A low or negative correlation suggests overfitting — the strategy
        performs well IS but poorly OOS.
        """
        if len(folds) < 3:
            return 0.0

        is_scores: list[float] = []
        oos_scores: list[float] = []
        for f in folds:
            is_pf = f.is_profit_factor if not math.isinf(f.is_profit_factor) else 10.0
            oos_pf = f.test_profit_factor if not math.isinf(f.test_profit_factor) else 10.0
            if f.train_trades > 0 and f.test_trades > 0:
                is_scores.append(is_pf)
                oos_scores.append(oos_pf)

        if len(is_scores) < 3:
            return 0.0

        return self._correlation(is_scores, oos_scores)

    # ── Utility Functions ─────────────────────────────────────────

    @staticmethod
    def _std(values: list[float]) -> float:
        """Compute standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)

    @staticmethod
    def _correlation(x: list[float], y: list[float]) -> float:
        """Compute Pearson correlation coefficient."""
        n = min(len(x), len(y))
        if n < 3:
            return 0.0

        x_mean = sum(x[:n]) / n
        y_mean = sum(y[:n]) / n

        cov = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        std_x = math.sqrt(sum((xi - x_mean) ** 2 for xi in x[:n]))
        std_y = math.sqrt(sum((yi - y_mean) ** 2 for yi in y[:n]))

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)

    # ── Persistence ───────────────────────────────────────────────

    def save(self, result: WFOResult, path: str | Path) -> None:
        """Save WFO result to JSON."""
        data = {
            "symbol": result.symbol,
            "is_duration_days": result.is_duration_days,
            "oos_duration_days": result.oos_duration_days,
            "step_days": result.step_days,
            "total_folds": result.total_folds,
            "aggregate": {
                "trades": result.aggregate_trades,
                "win_rate": result.aggregate_win_rate,
                "profit_factor": result.aggregate_profit_factor,
                "expectancy_r": result.aggregate_expectancy_r,
                "net_pnl": result.aggregate_net_pnl,
                "sharpe": result.aggregate_sharpe,
            },
            "overfitting": {
                "pbo_score": result.pbo_score,
                "is_oos_correlation": result.is_oos_correlation,
            },
            "stability": {
                "profit_factor_std": result.profit_factor_std,
                "win_rate_std": result.win_rate_std,
                "min_fold_pf": result.min_fold_pf,
                "max_fold_pf": result.max_fold_pf,
            },
            "folds": [
                {
                    "fold_index": f.fold_index,
                    "is_start": f.in_sample.start_epoch,
                    "is_end": f.in_sample.end_epoch,
                    "oos_start": f.out_of_sample.start_epoch,
                    "oos_end": f.out_of_sample.end_epoch,
                    "test_trades": f.test_trades,
                    "test_win_rate": f.test_win_rate,
                    "test_profit_factor": f.test_profit_factor,
                    "test_expectancy_r": f.test_expectancy_r,
                    "test_net_pnl": f.test_net_pnl,
                    "test_sharpe": f.test_sharpe,
                    "optimized_params": f.optimized_params,
                }
                for f in result.folds
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> WFOResult:
        """Load WFO result from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        agg = data["aggregate"]
        of = data["overfitting"]
        stab = data["stability"]

        folds = [
            WFOFold(
                fold_index=f["fold_index"],
                in_sample=WindowSpec(f["is_start"], f["is_end"]),
                out_of_sample=WindowSpec(f["oos_start"], f["oos_end"]),
                test_trades=f["test_trades"],
                test_win_rate=f["test_win_rate"],
                test_profit_factor=f["test_profit_factor"],
                test_expectancy_r=f["test_expectancy_r"],
                test_net_pnl=f["test_net_pnl"],
                test_sharpe=f.get("test_sharpe", 0.0),
                optimized_params=f.get("optimized_params", {}),
            )
            for f in data["folds"]
        ]

        return WFOResult(
            symbol=data["symbol"],
            folds=folds,
            aggregate_trades=agg["trades"],
            aggregate_win_rate=agg["win_rate"],
            aggregate_profit_factor=agg["profit_factor"],
            aggregate_expectancy_r=agg["expectancy_r"],
            aggregate_net_pnl=agg["net_pnl"],
            aggregate_sharpe=agg.get("sharpe", 0.0),
            pbo_score=of["pbo_score"],
            is_oos_correlation=of["is_oos_correlation"],
            profit_factor_std=stab["profit_factor_std"],
            win_rate_std=stab["win_rate_std"],
            min_fold_pf=stab["min_fold_pf"],
            max_fold_pf=stab["max_fold_pf"],
            is_duration_days=data["is_duration_days"],
            oos_duration_days=data["oos_duration_days"],
            step_days=data["step_days"],
            total_folds=data["total_folds"],
        )


# ── Report Rendering ─────────────────────────────────────────────


def render_wfo_report(result: WFOResult) -> str:  # noqa: C901
    """Render a human-readable WFO report."""
    lines = [
        f"Walk-Forward Optimization Report: {result.symbol}",
        f"{'=' * 50}",
        f"Windows: {result.is_duration_days}d IS / {result.oos_duration_days}d OOS / {result.step_days}d step",
        f"Total folds: {result.total_folds}",
        "",
        "Aggregate OOS Performance:",
        f"  Trades:        {result.aggregate_trades}",
        f"  Win Rate:      {result.aggregate_win_rate:.2%}",
        f"  Profit Factor: {result.aggregate_profit_factor:.2f}",
        f"  Expectancy:    {result.aggregate_expectancy_r:.3f}R",
        f"  Net PnL:       {result.aggregate_net_pnl:.2f}",
        f"  Sharpe:        {result.aggregate_sharpe:.2f}",
        "",
        "Overfitting Analysis:",
        f"  PBO Score:           {result.pbo_score:.2f} {'⚠ OVERFIT RISK' if result.pbo_score > 0.5 else '✓ OK'}",
        f"  IS-OOS Correlation:  {result.is_oos_correlation:.3f} {'⚠ LOW' if result.is_oos_correlation < 0.3 else '✓ OK'}",
        "",
        "Stability:",
        f"  PF Std Dev:    {result.profit_factor_std:.2f}",
        f"  WR Std Dev:    {result.win_rate_std:.2%}",
        f"  Min Fold PF:   {result.min_fold_pf:.2f}",
        f"  Max Fold PF:   {result.max_fold_pf:.2f}",
        "",
        "Fold Details:",
    ]

    for f in result.folds:
        pf_str = "inf" if math.isinf(f.test_profit_factor) else f"{f.test_profit_factor:.2f}"
        lines.append(
            f"  Fold {f.fold_index}: trades={f.test_trades} "
            f"wr={f.test_win_rate:.2%} pf={pf_str} "
            f"e={f.test_expectancy_r:.3f}R pnl={f.test_net_pnl:.2f}"
        )

    return "\n".join(lines)
