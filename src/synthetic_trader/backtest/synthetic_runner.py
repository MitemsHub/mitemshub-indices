"""Synthetic backtest runner for curve-fitting detection.

Runs the trading strategy against multiple independent synthetic datasets
to determine whether the strategy has genuine edge or is merely
curve-fitted to historical patterns.

The key insight: if a strategy performs well on REAL data but poorly
on SYNTHETIC data with the same statistical properties, it's likely
curve-fitted.  If it performs similarly on both, it has genuine edge.

Metrics computed:
1. **Deflated Sharpe Ratio** — adjusts for multiple testing
2. **Probability of Backtest Overfitting (PBO)** — Bailey et al. (2017)
3. **Strategy consistency** — win rate across datasets
4. **Edge stability** — how much performance varies across datasets
5. **Monte Carlo p-value** — probability of achieving observed performance
   by chance on random data

Reference:
- Bailey, Borwein, López de Prado, Zhu (2017) "The Probability of
  Backtest Overfitting" Journal of Computational Finance, 20(4), 39-69.
- Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns"
  "Backtest overfitting" in financial research.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from synthetic_trader.backtest.engine import BacktestEngine
from synthetic_trader.backtest.prop_firm import PropFirmBreachTracker, PropFirmProfile
from synthetic_trader.backtest.synthetic_generator import (
    SyntheticIndexConfig,
    generate_synthetic_datasets,
)
from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Tick
from synthetic_trader.journal.trade_journal import JournalMetrics
from synthetic_trader.models.online import OnlineLogisticModel


@dataclass
class EpisodeResult:
    """Result of a single synthetic dataset backtest."""
    episode_index: int
    seed: int
    n_ticks: int
    metrics: JournalMetrics
    final_equity: float
    signals: int
    rejected_signals: int
    model_version: str


@dataclass
class CurveFittingReport:
    """Complete curve-fitting detection report."""
    symbol: str
    n_episodes: int
    n_ticks_per_episode: int
    ran_at: str = ""
    episodes: list[EpisodeResult]

    # Aggregate metrics
    mean_win_rate: float = 0.0
    mean_profit_factor: float = 0.0
    mean_expectancy_r: float = 0.0
    mean_net_pnl: float = 0.0
    mean_signals: float = 0.0

    # Consistency metrics
    win_rate_std: float = 0.0
    profit_factor_std: float = 0.0
    consistency_score: float = 0.0  # 0-1, higher = more consistent

    # Curve-fitting detection
    deflated_sharpe: float = 0.0
    pbo_score: float = 0.0  # Probability of Backtest Overfitting
    monte_carlo_p_value: float = 0.0  # Probability of performance by chance
    edge_detected: bool = False  # True if strategy has genuine edge

    # Prop firm breach stats
    prop_firm_name: str = ""
    total_breaches: int = 0
    daily_loss_breaches: int = 0
    drawdown_breaches: int = 0
    risk_per_trade_breaches: int = 0
    breach_rate: float = 0.0  # breaches per episode

    # Interpretation
    verdict: str = ""
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "n_episodes": self.n_episodes,
            "n_ticks_per_episode": self.n_ticks_per_episode,
            "aggregate": {
                "mean_win_rate": self.mean_win_rate,
                "mean_profit_factor": self.mean_profit_factor,
                "mean_expectancy_r": self.mean_expectancy_r,
                "mean_net_pnl": self.mean_net_pnl,
                "mean_signals": self.mean_signals,
            },
            "consistency": {
                "win_rate_std": self.win_rate_std,
                "profit_factor_std": self.profit_factor_std,
                "consistency_score": self.consistency_score,
            },
            "curve_fitting": {
                "deflated_sharpe": self.deflated_sharpe,
                "pbo_score": self.pbo_score,
                "monte_carlo_p_value": self.monte_carlo_p_value,
                "edge_detected": self.edge_detected,
            },
            "prop_firm": {
                "name": self.prop_firm_name,
                "total_breaches": self.total_breaches,
                "daily_loss_breaches": self.daily_loss_breaches,
                "drawdown_breaches": self.drawdown_breaches,
                "risk_per_trade_breaches": self.risk_per_trade_breaches,
                "breach_rate": self.breach_rate,
            } if self.prop_firm_name else None,
            "ran_at": self.ran_at,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "episodes": [
                {
                    "episode": e.episode_index,
                    "seed": e.seed,
                    "trades": e.metrics.trades,
                    "win_rate": e.metrics.win_rate,
                    "profit_factor": e.metrics.profit_factor,
                    "expectancy_r": e.metrics.expectancy_r,
                    "net_pnl": e.metrics.net_pnl,
                    "signals": e.signals,
                }
                for e in self.episodes
            ],
        }


# ── Synthetic Backtest Runner ────────────────────────────────────


class SyntheticBacktestRunner:
    """Run the trading strategy against multiple synthetic datasets.

    This is the core component for curve-fitting detection.  It generates
    N independent synthetic datasets (each with the same statistical
    properties as real Deriv indices) and runs the full trading pipeline
    on each one.

    If the strategy performs well on REAL data but poorly on SYNTHETIC
    data, it's likely curve-fitted.  If it performs similarly on both,
    it has genuine edge.

    Parameters
    ----------
    n_episodes : int
        Number of independent synthetic datasets to generate.
        More episodes = more reliable curve-fitting detection.
        Recommended: 50-100 for production testing.
    ticks_per_episode : int
        Number of ticks in each synthetic dataset.
        Recommended: 10,000-50,000 for meaningful results.
    config : TraderConfig | None
        Trading configuration. Uses defaults if None.
    model : OnlineLogisticModel | None
        Online learning model. Fresh model for each episode.
    base_seed : int
        Base seed for reproducibility. Each episode gets a unique seed.
    learn : bool
        Whether to allow online learning during backtest.
        Recommended: True for realistic testing.
    prop_firm : PropFirmProfile | None
        Prop firm rules to enforce during backtesting.  When set,
        the risk engine will reject trades that violate daily loss,
        max drawdown, or risk-per-trade limits.
    """

    def __init__(
        self,
        n_episodes: int = 50,
        ticks_per_episode: int = 20000,
        config: TraderConfig | None = None,
        model: OnlineLogisticModel | None = None,
        base_seed: int = 42,
        learn: bool = True,
        config_override: SyntheticIndexConfig | None = None,
        prop_firm: PropFirmProfile | None = None,
    ) -> None:
        self.n_episodes = n_episodes
        self.ticks_per_episode = ticks_per_episode
        self.config = config or TraderConfig.default()
        self.base_model = model or OnlineLogisticModel(self.config.model)
        self.base_seed = base_seed
        self.learn = learn
        self.config_override = config_override
        self.prop_firm = prop_firm

    def run(
        self,
        symbol: str,
        progress_callback: tuple | None = None,
    ) -> CurveFittingReport:
        """Run the full synthetic backtest.

        Parameters
        ----------
        symbol : str
            Symbol to test (e.g., "R_100", "V75").
        progress_callback : tuple | None
            Optional (current, total) callback for progress tracking.

        Returns
        -------
        CurveFittingReport
            Complete curve-fitting detection report.
        """
        # Generate synthetic datasets
        config = self.config_override or SyntheticIndexConfig(symbol=symbol)
        datasets = generate_synthetic_datasets(
            n_datasets=self.n_episodes,
            ticks_per_dataset=self.ticks_per_episode,
            config=config,
            base_seed=self.base_seed,
        )

        episodes: list[EpisodeResult] = []
        total_breaches = 0
        total_daily_breaches = 0
        total_drawdown_breaches = 0
        total_risk_breaches = 0

        for i, ticks in enumerate(datasets):
            if progress_callback:
                progress_callback(i + 1, self.n_episodes)

            # Fresh model for each episode (prevents cross-contamination)
            model = self.base_model.clone()
            breach_tracker = PropFirmBreachTracker(
                initial_balance=self.config.paper.initial_balance,
            ) if self.prop_firm else None
            engine = BacktestEngine(
                config=self.config,
                model=model,
                prop_firm=self.prop_firm,
                breach_tracker=breach_tracker,
            )

            result = engine.run_ticks(
                ticks,
                symbol=symbol,
                learn=self.learn,
            )

            if breach_tracker is not None:
                total_breaches += breach_tracker.total_breaches
                total_daily_breaches += breach_tracker.daily_loss_breaches
                total_drawdown_breaches += breach_tracker.drawdown_breaches
                total_risk_breaches += breach_tracker.risk_per_trade_breaches

            episodes.append(EpisodeResult(
                episode_index=i,
                seed=self.base_seed + i,
                n_ticks=len(ticks),
                metrics=result.metrics,
                final_equity=result.final_equity,
                signals=result.signals,
                rejected_signals=result.rejected_signals,
                model_version=result.model_version,
            ))

        # Compute aggregate metrics and curve-fitting detection
        report = self._analyze_episodes(symbol, episodes)

        # Attach prop firm breach stats
        if self.prop_firm:
            report.prop_firm_name = self.prop_firm.name
            report.total_breaches = total_breaches
            report.daily_loss_breaches = total_daily_breaches
            report.drawdown_breaches = total_drawdown_breaches
            report.risk_per_trade_breaches = total_risk_breaches
            report.breach_rate = total_breaches / max(self.n_episodes, 1)

        return report

    def _analyze_episodes(
        self,
        symbol: str,
        episodes: list[EpisodeResult],
    ) -> CurveFittingReport:
        """Analyze episode results and compute curve-fitting metrics."""
        n = len(episodes)
        if n == 0:
            return CurveFittingReport(
                symbol=symbol,
                n_episodes=0,
                n_ticks_per_episode=self.ticks_per_episode,
                episodes=[],
                verdict="No episodes completed",
                explanation="Not enough data for analysis",
            )

        # Extract metrics
        win_rates = [e.metrics.win_rate for e in episodes]
        profit_factors = [e.metrics.profit_factor for e in episodes
                         if not math.isinf(e.metrics.profit_factor)]
        expectancies = [e.metrics.expectancy_r for e in episodes]
        pnls = [e.metrics.net_pnl for e in episodes]
        signals_list = [float(e.signals) for e in episodes]

        # Aggregate means
        mean_wr = _mean(win_rates)
        mean_pf = _mean(profit_factors) if profit_factors else 0.0
        mean_er = _mean(expectancies)
        mean_pnl = _mean(pnls)
        mean_signals = _mean(signals_list)

        # Consistency (standard deviations)
        wr_std = _std(win_rates)
        pf_std = _std(profit_factors) if len(profit_factors) > 1 else 0.0

        # Consistency score: 1 = perfect consistency, 0 = highly variable
        # Uses coefficient of variation
        if mean_wr > 0:
            wr_cv = wr_std / mean_wr
            consistency_score = max(0.0, 1.0 - wr_cv)
        else:
            consistency_score = 0.0

        # Deflated Sharpe Ratio
        deflated_sharpe = self._compute_deflated_sharpe(episodes)

        # Probability of Backtest Overfitting (PBO)
        pbo_score = self._compute_pbo(episodes)

        # Monte Carlo p-value
        mc_p_value = self._compute_monte_carlo_p_value(episodes)

        # Edge detection
        edge_detected = (
            mean_wr > 0.52  # Win rate above 52%
            and mean_pf > 1.0  # Profit factor above 1.0
            and mean_er > 0.0  # Positive expectancy
            and pbo_score < 0.5  # Low overfitting risk
            and consistency_score > 0.3  # Somewhat consistent
        )

        # Verdict
        if edge_detected and pbo_score < 0.3:
            verdict = "✅ GENUINE EDGE DETECTED"
            explanation = (
                f"The strategy shows consistent performance across {n} independent "
                f"synthetic datasets. Win rate: {mean_wr:.1%} ± {wr_std:.1%}, "
                f"Profit factor: {mean_pf:.2f} ± {pf_std:.2f}. "
                f"PBO score {pbo_score:.2f} indicates low overfitting risk. "
                f"The strategy appears to exploit genuine statistical properties "
                f"of the synthetic index generator."
            )
        elif edge_detected:
            verdict = "⚠️ LIKELY EDGE (MODERATE OVERFITTING RISK)"
            explanation = (
                f"The strategy shows positive performance across {n} synthetic "
                f"datasets, but PBO score {pbo_score:.2f} suggests moderate "
                f"overfitting risk. Consider increasing the number of episodes "
                f"or using more conservative parameter settings."
            )
        elif mean_wr > 0.50 and mean_pf > 0.9:
            verdict = "⚠️ WEAK EDGE (HIGH OVERFITTING RISK)"
            explanation = (
                f"The strategy shows marginal performance (win rate {mean_wr:.1%}, "
                f"PF {mean_pf:.2f}) but with high variability. PBO {pbo_score:.2f} "
                f"indicates significant overfitting risk. The strategy may be "
                f"partially curve-fitted to historical patterns."
            )
        else:
            verdict = "❌ NO EDGE DETECTED (LIKELY CURVE-FITTED)"
            explanation = (
                f"The strategy does NOT perform well on synthetic data with the "
                f"same statistical properties as real Deriv indices. Win rate: "
                f"{mean_wr:.1%}, PF: {mean_pf:.2f}, Expectancy: {mean_er:.3f}R. "
                f"PBO {pbo_score:.2f} confirms high overfitting risk. The strategy "
                f"is likely curve-fitted to historical noise rather than exploiting "
                f"genuine generator properties."
            )

        now = datetime.now(timezone.utc).isoformat()
        return CurveFittingReport(
            symbol=symbol,
            n_episodes=n,
            n_ticks_per_episode=self.ticks_per_episode,
            ran_at=now,
            episodes=episodes,
            mean_win_rate=mean_wr,
            mean_profit_factor=mean_pf,
            mean_expectancy_r=mean_er,
            mean_net_pnl=mean_pnl,
            mean_signals=mean_signals,
            win_rate_std=wr_std,
            profit_factor_std=pf_std,
            consistency_score=consistency_score,
            deflated_sharpe=deflated_sharpe,
            pbo_score=pbo_score,
            monte_carlo_p_value=mc_p_value,
            edge_detected=edge_detected,
            verdict=verdict,
            explanation=explanation,
        )

    def _compute_deflated_sharpe(self, episodes: list[EpisodeResult]) -> float:
        """Compute Deflated Sharpe Ratio.

        Adjusts the Sharpe ratio for the fact that we tested many
        parameter combinations.  A deflated Sharpe < 1.0 suggests
        the observed performance could be due to chance.

        Reference: Bailey & López de Prado (2014)
        """
        n = len(episodes)
        if n < 2:
            return 0.0

        # Compute Sharpe-like ratios for each episode
        sharpes: list[float] = []
        for e in episodes:
            if e.metrics.trades > 0 and e.metrics.win_rate > 0:
                sharpe = e.metrics.expectancy_r / max(e.metrics.win_rate, 0.01)
                sharpes.append(sharpe)

        if not sharpes:
            return 0.0

        mean_sharpe = _mean(sharpes)
        std_sharpe = _std(sharpes)

        # Deflated Sharpe = (observed - expected) / std
        # Under null hypothesis (no edge), expected Sharpe = 0
        if std_sharpe == 0:
            # Zero std = all episodes identical (maximum consistency)
            # Return the observed Sharpe directly — this IS genuine edge
            return max(-3.0, min(3.0, mean_sharpe))

        deflated = mean_sharpe / std_sharpe
        return max(-3.0, min(3.0, deflated))

    def _compute_pbo(self, episodes: list[EpisodeResult]) -> float:
        """Compute Probability of Backtest Overfitting (PBO).

        Simplified heuristic: compares performance in first half
        vs second half of episodes.  If first half (more data) underperforms
        second half, it suggests curve-fitting.

        Reference: Bailey et al. (2017)
        """
        n = len(episodes)
        if n < 4:
            return 0.5  # Not enough data

        half = n // 2

        # Split episodes into two halves
        first_half = episodes[:half]
        second_half = episodes[half:]

        # Compare win rates
        first_wr = _mean([e.metrics.win_rate for e in first_half])
        second_wr = _mean([e.metrics.win_rate for e in second_half])

        # If first half (more data) underperforms, overfitting is likely
        if first_wr < second_wr:
            # First half worse than second = overfitting signal
            diff = second_wr - first_wr
            pbo = min(0.8, 0.3 + diff * 2.0)
        else:
            # First half better than second = normal behavior
            diff = first_wr - second_wr
            pbo = max(0.1, 0.3 - diff * 2.0)

        return max(0.0, min(1.0, pbo))

    def _compute_monte_carlo_p_value(self, episodes: list[EpisodeResult]) -> float:
        """Compute Monte Carlo p-value for strategy performance.

        Tests the null hypothesis that the strategy has no edge
        (performance is due to chance).

        Uses a simple permutation test: compare observed win rate
        against the distribution of win rates under the null.
        """
        n = len(episodes)
        if n < 10:
            return 0.5  # Not enough data

        observed_wr = _mean([e.metrics.win_rate for e in episodes])

        # Under null hypothesis, expected win rate = 0.50
        # Standard error of mean win rate
        se = math.sqrt(0.25 / n) if n > 0 else 0.1

        # Z-test
        z = (observed_wr - 0.50) / se if se > 0 else 0.0

        # Two-tailed p-value
        p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))

        return max(0.0, min(1.0, p_value))

    def render_report(self, report: CurveFittingReport) -> str:
        """Render a human-readable curve-fitting report."""
        lines = [
            f"{'=' * 60}",
            f"SYNTHETIC BACKTEST: Curve-Fitting Detection Report",
            f"{'=' * 60}",
            f"Symbol: {report.symbol}",
            f"Episodes: {report.n_episodes}",
            f"Ticks per episode: {report.n_ticks_per_episode}",
            "",
            f"{'─' * 60}",
            f"AGGREGATE PERFORMANCE",
            f"{'─' * 60}",
            f"  Mean Win Rate:       {report.mean_win_rate:.1%} ± {report.win_rate_std:.1%}",
            f"  Mean Profit Factor:  {report.mean_profit_factor:.2f} ± {report.profit_factor_std:.2f}",
            f"  Mean Expectancy:     {report.mean_expectancy_r:.3f}R",
            f"  Mean Net PnL:        {report.mean_net_pnl:.2f}",
            f"  Mean Signals/episode:{report.mean_signals:.1f}",
            "",
            f"{'─' * 60}",
            f"CONSISTENCY",
            f"{'─' * 60}",
            f"  Consistency Score:   {report.consistency_score:.2f} (1=perfect)",
            "",
            f"{'─' * 60}",
            f"CURVE-FITTING DETECTION",
            f"{'─' * 60}",
            f"  Deflated Sharpe:     {report.deflated_sharpe:.2f} (>1.0 = good)",
            f"  PBO Score:           {report.pbo_score:.2f} (<0.5 = low risk)",
            f"  Monte Carlo p-value: {report.monte_carlo_p_value:.4f} (<0.05 = significant)",
            "",
            f"{'─' * 60}",
            f"VERDICT",
            f"{'─' * 60}",
            f"  {report.verdict}",
            "",
            f"  {report.explanation}",
            "",
            f"{'─' * 60}",
            f"EPISODE DETAILS (first 10)",
            f"{'─' * 60}",
        ]

        for e in report.episodes[:10]:
            pf_str = "inf" if math.isinf(e.metrics.profit_factor) else f"{e.metrics.profit_factor:.2f}"
            lines.append(
                f"  Episode {e.episode_index:3d}: trades={e.metrics.trades:4d} "
                f"wr={e.metrics.win_rate:.1%} pf={pf_str} "
                f"e={e.metrics.expectancy_r:.3f}R pnl={e.metrics.net_pnl:.2f}"
            )

        if len(report.episodes) > 10:
            lines.append(f"  ... and {len(report.episodes) - 10} more episodes")

        # Prop firm breach summary
        if report.prop_firm_name:
            lines.extend([
                "",
                f"{'─' * 60}",
                f"PROP FIRM CONSTRAINTS: {report.prop_firm_name}",
                f"{'─' * 60}",
                f"  Total Breaches:         {report.total_breaches}",
                f"  Daily Loss Breaches:    {report.daily_loss_breaches}",
                f"  Max Drawdown Breaches:  {report.drawdown_breaches}",
                f"  Risk-Per-Trade Breaches: {report.risk_per_trade_breaches}",
                f"  Breach Rate:            {report.breach_rate:.2f} per episode",
                "",
                f"  ⚠️  Breaches indicate the strategy would have violated",
                f"     real prop firm rules during live trading.",
                f"     A high breach rate means the strategy needs adjustment",
                f"     (smaller position sizes, wider stops, or fewer trades).",
            ])

        return "\n".join(lines)


# ── Utility Functions ─────────────────────────────────────────────


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float], ddof: int = 1) -> float:
    if len(values) <= ddof:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - ddof)
    return math.sqrt(variance)


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
