"""Combined sub-account backtest with overlap attribution and an A/B verdict.

The probe (``_probe_combined.py``) showed that stacking a second strategy
next to the band fade is usually **arithmetic, not synergy**: the ratio-gate
momentum fires on the SAME candles in the OPPOSITE direction (a hedge), and
the disjoint absolute-gate leg was unprofitable at realistic costs.  This
module productionizes that measurement so any future strategy pair can be
A/B tested against the same baseline automatically.

Design:

- **One shared candle stream, two independent sub-accounts** — each leg gets
  its own broker (breakeven-trail for band/fade, plain paper for momentum
  unless configured) and its own RiskEngine, exactly like
  :func:`synthetic_trader.backtest.vol_reversion.run_vol_regime_backtest`
  would give it alone.  The strategy, broker, and risk state carry full
  history; optional ``count_from_epoch`` / ``count_until_epoch`` windows
  restrict which signals/trades are counted (walk-forward, §42).
- **Overlap attribution** — per-candle signal overlap (both fire? same or
  opposite direction?), and per-account PnL split into overlap-candle trades
  vs standalone trades, so a hedge structure is visible in the numbers, not
  just the entry list.
- **A/B verdict** — combined net vs the best single leg, combined trade
  count vs the best single leg, combined expectancy vs the best single leg,
  daily-PnL correlation, and a composite label
  (``adds_trades_and_net`` / ``adds_trades_net_neutral`` / ``dilutes_net`` /
  ``no_change``).

CLI::

    python -m synthetic_trader.cli combine-regime --csv data/backfill/R_75_ticks.csv \\
        --symbol R_75 --timeframe 300 --leg-a band --leg-b momentum
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_band import VolBandConfig, VolBandStrategy
from synthetic_trader.backtest.vol_momentum import (
    VolMomentumConfig,
    VolMomentumStrategy,
)
from synthetic_trader.backtest.vol_reversion import (
    BreakevenTrailBroker,
    VolReversionConfig,
    VolReversionStrategy,
    dedupe_ticks,
)
from synthetic_trader.config import PaperExecutionConfig, TraderConfig
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.execution.paper import PaperBroker
from synthetic_trader.journal.trade_journal import metrics_from_outcomes
from synthetic_trader.risk.engine import RiskEngine

# Realistic execution costs, matching backtest-vol §36.
DEFAULT_PAPER = PaperExecutionConfig(
    entry_slippage_ticks=0.05,
    exit_slippage_ticks=0.05,
    execution_penalty_per_trade=0.10,
)
# Combined net must beat the best single leg by this fraction to count as
# an improvement (noise guard on tiny PnL magnitudes).
NET_MARGIN_FRAC = 0.01
# |daily PnL correlation| above this = strongly correlated / hedging.
CORR_STRONG = 0.5

SUPPORTED_STRATEGIES = ("band", "fade", "momentum")


@dataclass(frozen=True)
class LegSpec:
    """One sub-account leg: a strategy name + config overrides."""

    strategy: str
    config: dict[str, Any] = field(default_factory=dict)
    label: str | None = None  # default = strategy name

    def __post_init__(self) -> None:
        if self.strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(
                f"leg strategy must be one of {SUPPORTED_STRATEGIES}; got {self.strategy!r}"
            )

    @property
    def effective_label(self) -> str:
        return self.label or self.strategy


def _build_strategy(spec: LegSpec, symbol: str, timeframe_sec: int, garch_state):
    """Construct the strategy instance for a leg spec."""
    if spec.strategy == "band":
        cfg = VolBandConfig(**(spec.config or {}))
        return VolBandStrategy(symbol, timeframe_sec, config=cfg, garch_state=garch_state), cfg
    if spec.strategy == "fade":
        cfg = VolReversionConfig(**(spec.config or {}))
        return VolReversionStrategy(symbol, timeframe_sec, config=cfg, garch_state=garch_state), cfg
    # momentum
    cfg = VolMomentumConfig(**(spec.config or {}))
    return VolMomentumStrategy(symbol, timeframe_sec, config=cfg, garch_state=garch_state), cfg


def _make_broker(paper: PaperExecutionConfig, cfg) -> PaperBroker:
    trail_frac = getattr(cfg, "breakeven_trail_frac", 0.0) or 0.0
    return (
        BreakevenTrailBroker(paper, breakeven_trail_frac=trail_frac)
        if trail_frac > 0.0
        else PaperBroker(paper)
    )


@dataclass
class LegResult:
    label: str
    metrics: Any
    signals: int = 0
    rejected: int = 0
    equity: float = 0.0
    outcomes: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        mt = self.metrics
        return {
            "label": self.label,
            "trades": mt.trades,
            "signals": self.signals,
            "rejected": self.rejected,
            "win_rate": round(mt.win_rate, 4),
            "profit_factor": round(mt.profit_factor, 4),
            "expectancy_r": round(mt.expectancy_r, 4),
            "net_pnl": round(mt.net_pnl, 2),
            "final_equity": round(self.equity, 2),
        }


@dataclass
class CombinedRun:
    legs: dict[str, LegResult]
    combined_metrics: Any
    combined_equity: float
    sig_log: list[tuple[float, str, str, float]]
    overlap_stats: dict[str, int]
    attribution: dict[str, float]          # label -> overlap/standalone net
    attribution_n: dict[str, int]
    daily_corr: float
    daily_days: int
    lift_days: int
    lift_total_days: int


def run_combined_legs(
    ticks: list,
    symbol: str,
    timeframe_sec: int,
    leg_a: LegSpec,
    leg_b: LegSpec,
    *,
    paper: PaperExecutionConfig | None = None,
    config: TraderConfig | None = None,
    garch_state=None,
    count_from_epoch: float | None = None,
    count_until_epoch: float | None = None,
) -> CombinedRun:
    """Run two strategies on one candle stream with separate sub-accounts.

    ``ticks`` must be sorted ascending by epoch (dedupe via
    :func:`dedupe_ticks`/``load_ticks_csv``).  Returns the full run with
    overlap attribution already computed.
    """
    trader = config or TraderConfig.default()
    paper = paper or DEFAULT_PAPER
    risk_config = __import__("dataclasses").replace(
        trader.risk, min_confidence=0.0, min_reward_risk=0.0
    )

    specs = {"a": leg_a, "b": leg_b}
    strategies: dict[str, Any] = {}
    brokers: dict[str, PaperBroker] = {}
    risks: dict[str, RiskEngine] = {}
    for key, spec in specs.items():
        strat, cfg = _build_strategy(spec, symbol, timeframe_sec, garch_state)
        strategies[key] = strat
        brokers[key] = _make_broker(paper, cfg)
        risks[key] = RiskEngine(risk_config)

    label_of = {"a": leg_a.effective_label, "b": leg_b.effective_label}
    outcomes: dict[str, list] = {"a": [], "b": []}
    counts: dict[str, dict[str, int]] = {"a": {"signals": 0, "rejected": 0}, "b": {"signals": 0, "rejected": 0}}
    sig_log: list[tuple[float, str, str, float]] = []

    builders = MultiTimeframeCandleBuilder(symbol, [timeframe_sec])

    def _in_window(epoch: float) -> bool:
        if count_from_epoch is not None and epoch < count_from_epoch:
            return False
        if count_until_epoch is not None and epoch >= count_until_epoch:
            return False
        return True

    def _process(key: str, candle) -> None:
        sig = strategies[key].on_candle(candle)
        if sig is None:
            return
        label = label_of[key]
        if _in_window(candle.open_time):
            counts[key]["signals"] += 1
        sig_log.append((candle.open_time, label, sig.direction.name, sig.entry))
        decision = risks[key].evaluate(sig)
        if not decision.approved or decision.intent is None:
            counts[key]["rejected"] += 1
            return
        brokers[key].submit(decision.intent)
        risks[key].register_open()

    def _settle(key: str, closed_candle) -> None:
        for outcome in brokers[key].on_candle(closed_candle):
            outcomes[key].append(outcome)
            risks[key].register_outcome(outcome)

    for tick in sorted(ticks, key=lambda t: t.epoch):
        closed = builders.update(tick)
        for tf, candle in closed.items():
            if tf != timeframe_sec:
                continue
            _settle("a", candle)
            _settle("b", candle)
            _process("a", candle)
            _process("b", candle)

    flushed = builders.flush()
    final = flushed.get(timeframe_sec)
    if final is not None:
        for key in ("a", "b"):
            for outcome in brokers[key].on_candle(final) + brokers[key].close_all(final):
                outcomes[key].append(outcome)
                risks[key].register_outcome(outcome)

    legs = {
        label_of[key]: LegResult(
            label=label_of[key],
            metrics=metrics_from_outcomes(outcomes[key]),
            signals=counts[key]["signals"],
            rejected=counts[key]["rejected"],
            equity=risks[key].state.equity,
            outcomes=list(outcomes[key]),
        )
        for key in ("a", "b")
    }
    all_outcomes = outcomes["a"] + outcomes["b"]
    combined_metrics = metrics_from_outcomes(all_outcomes)
    combined_equity = sum(risks[k].state.equity for k in ("a", "b")) - 1000.0

    overlap_stats = _overlap_stats(sig_log, set(legs))
    attribution, attribution_n = _attribution(sig_log, label_of, outcomes, timeframe_sec)
    db, dm = _daily_series(outcomes["a"]), _daily_series(outcomes["b"])
    corr = _pearson(
        {k: v["pnl"] for k, v in db.items()},
        {k: v["pnl"] for k, v in dm.items()},
    )
    all_days = sorted(set(db) | set(dm))
    lift_days = sum(
        1
        for d in all_days
        if db[d]["trades"] + dm[d]["trades"] > max(db[d]["trades"], dm[d]["trades"])
    )

    return CombinedRun(
        legs=legs,
        combined_metrics=combined_metrics,
        combined_equity=combined_equity,
        sig_log=sig_log,
        overlap_stats=overlap_stats,
        attribution=attribution,
        attribution_n=attribution_n,
        daily_corr=corr,
        daily_days=len(all_days),
        lift_days=lift_days,
        lift_total_days=len(all_days),
    )


# ── Overlap attribution ────────────────────────────────────────────────
def _overlap_stats(sig_log: list, labels: set[str]) -> dict[str, int]:
    """Per-candle overlap: candles where both legs fired + direction agree."""
    by_candle: dict[int, dict[str, tuple[str, float]]] = {}
    for epoch, label, direction, entry in sig_log:
        by_candle.setdefault(int(epoch), {})[label] = (direction, entry)
    both = [v for v in by_candle.values() if len(v) == 2]
    labels_list = sorted(labels)
    opposite = sum(
        1 for v in both if v[labels_list[0]][0] != v[labels_list[1]][0]
    )
    same = len(both) - opposite
    return {
        "candles_total": len(by_candle),
        "both": len(both),
        "opposite_dir": opposite,
        "same_dir": same,
        "leg_a_only": sum(1 for v in by_candle.values() if labels_list[0] in v and labels_list[1] not in v),
        "leg_b_only": sum(1 for v in by_candle.values() if labels_list[1] in v and labels_list[0] not in v),
    }


def _attribution(
    sig_log: list,
    label_of: dict[str, str],
    outcomes: dict[str, list],
    timeframe_sec: int,
) -> tuple[dict[str, float], dict[str, int]]:
    """Split each leg's PnL into overlap-candle vs standalone trades.

    ``opened_at`` = candle open_time + timeframe (signal snapshot epoch), so
    overlap is keyed by the candle's CLOSE time.
    """
    by_candle: dict[float, set[str]] = defaultdict(set)
    for epoch, label, _d, _e in sig_log:
        by_candle[epoch + timeframe_sec].add(label)
    overlap_epochs = {e for e, s in by_candle.items() if len(s) == 2}

    def _net(outs) -> float:
        return metrics_from_outcomes(outs).net_pnl if outs else 0.0

    net_by_label: dict[str, float] = {}
    n_by_label: dict[str, int] = {}
    for key, label in label_of.items():
        ov = [o for o in outcomes[key] if o.opened_at in overlap_epochs]
        so = [o for o in outcomes[key] if o.opened_at not in overlap_epochs]
        net_by_label[f"{label}.overlap"] = _net(ov)
        net_by_label[f"{label}.standalone"] = _net(so)
        n_by_label[f"{label}.overlap"] = len(ov)
        n_by_label[f"{label}.standalone"] = len(so)
    return net_by_label, n_by_label


# ── Daily series helpers ───────────────────────────────────────────────
def _daily_series(outcomes: list) -> dict[str, dict[str, float]]:
    days: dict[str, dict[str, float]] = defaultdict(lambda: {"trades": 0.0, "pnl": 0.0})
    for o in outcomes:
        day = datetime.fromtimestamp(o.closed_at, tz=timezone.utc).strftime("%Y-%m-%d")
        days[day]["trades"] += 1
        days[day]["pnl"] += o.pnl
    return days


def _pearson(a: dict, b: dict) -> float:
    keys = sorted(set(a) & set(b))
    if len(keys) < 2:
        return float("nan")
    ma = sum(a[k] for k in keys) / len(keys)
    mb = sum(b[k] for k in keys) / len(keys)
    cov = sum((a[k] - ma) * (b[k] - mb) for k in keys)
    va = sum((a[k] - ma) ** 2 for k in keys)
    vb = sum((b[k] - mb) ** 2 for k in keys)
    if va == 0 or vb == 0:
        return float("nan")
    return cov / math.sqrt(va * vb)


# ── A/B verdict ────────────────────────────────────────────────────────
def ab_verdict(run: CombinedRun) -> dict[str, Any]:
    """Judge the pair against the best single leg."""
    labels = list(run.legs.keys())
    a, b = labels[0], labels[1]
    la, lb = run.legs[a], run.legs[b]
    best_net = max(la.metrics.net_pnl, lb.metrics.net_pnl)
    best_trades = max(la.metrics.trades, lb.metrics.trades)
    best_exp = max(la.metrics.expectancy_r, lb.metrics.expectancy_r)
    c = run.combined_metrics

    net_status = (
        "improved"
        if c.net_pnl > best_net * (1.0 + NET_MARGIN_FRAC)
        else "reduced"
        if c.net_pnl < best_net * (1.0 - NET_MARGIN_FRAC)
        else "neutral"
    )
    trades_status = "adds_trades" if c.trades > best_trades else "no_change"
    exp_status = "dilutes" if c.expectancy_r < best_exp - 1e-9 else "preserves"

    ov = run.overlap_stats
    if ov["both"] == 0:
        overlap_nature = "disjoint"
    elif ov["opposite_dir"] > 0 and ov["same_dir"] == 0:
        overlap_nature = "opposite_overlap"
    elif ov["same_dir"] > 0:
        overlap_nature = "same_direction_overlap"
    else:
        overlap_nature = "mixed_overlap"

    corr = run.daily_corr
    corr_nature = (
        "diversifying"
        if not math.isnan(corr) and corr <= -CORR_STRONG
        else "correlated"
        if not math.isnan(corr) and corr >= CORR_STRONG
        else "neutral"
    )

    if net_status == "improved" and trades_status == "adds_trades":
        composite = "adds_trades_and_net"
    elif net_status == "reduced":
        composite = "dilutes_net"
    elif trades_status == "adds_trades":
        composite = "adds_trades_net_neutral"
    else:
        composite = "no_change"

    reason = (
        f"{a} {la.metrics.trades} trades {la.metrics.expectancy_r:+.3f}R "
        f"{la.metrics.net_pnl:+.2f} + {b} {lb.metrics.trades} trades "
        f"{lb.metrics.expectancy_r:+.3f}R {lb.metrics.net_pnl:+.2f} -> combined "
        f"{c.trades} trades {c.expectancy_r:+.3f}R {c.net_pnl:+.2f}. "
        f"overlap={ov['both']} candles ({ov['opposite_dir']} opposite-dir), "
        f"daily-corr={corr:+.2f}."
    )
    return {
        "composite": composite,
        "net_status": net_status,
        "trades_status": trades_status,
        "exp_status": exp_status,
        "overlap_nature": overlap_nature,
        "correlation_nature": corr_nature,
        "reason": reason,
    }


def run_combined_pair(
    *,
    csv_path: str | Path,
    symbol: str,
    timeframe_sec: int = 300,
    leg_a: LegSpec,
    leg_b: LegSpec,
    paper: PaperExecutionConfig | None = None,
    garch_state=None,
    artifact_output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the corpus, run the pair, serialize the full A/B report.

    Mirrors ``headtohead_verify``: when no calibrated EGARCH state is given,
    it is loaded from ``data/garch_calibration/{symbol}.json`` so the legs
    run with the same dynamics as every other backtest mode (§35+).
    """
    if garch_state is None:
        try:
            from synthetic_trader.models.garch_calibration import (
                load_calibrated_garch_state,
            )

            garch_state = load_calibrated_garch_state(symbol)
        except Exception:
            garch_state = None
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    run = run_combined_legs(
        ticks,
        symbol,
        timeframe_sec,
        leg_a,
        leg_b,
        paper=paper,
        garch_state=garch_state,
    )
    verdict = ab_verdict(run)
    span_days = (ticks[-1].epoch - ticks[0].epoch) / 86400.0 if len(ticks) > 1 else 0.0

    report: dict[str, Any] = {
        "symbol": symbol,
        "timeframe_sec": timeframe_sec,
        "corpus": {"csv": str(csv_path), "ticks": len(ticks), "span_days": round(span_days, 3)},
        "generated_at": time.time(),
        "legs": {label: leg.to_dict() for label, leg in run.legs.items()},
        "combined": {
            "trades": run.combined_metrics.trades,
            "win_rate": round(run.combined_metrics.win_rate, 4),
            "expectancy_r": round(run.combined_metrics.expectancy_r, 4),
            "net_pnl": round(run.combined_metrics.net_pnl, 2),
            "equity": round(run.combined_equity, 2),
        },
        "overlap": run.overlap_stats,
        "attribution": run.attribution,
        "attribution_n": run.attribution_n,
        "daily_corr": round(run.daily_corr, 4) if not math.isnan(run.daily_corr) else None,
        "daily_days": run.daily_days,
        "lift_days": run.lift_days,
        "lift_total_days": run.lift_total_days,
        "verdict": verdict,
    }
    if artifact_output_path is not None:
        out = Path(artifact_output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["artifact"] = str(out)
    return report


def print_combined_report(report: dict[str, Any]) -> None:
    c = report["corpus"]
    print(f"== combined-regime {report['symbol']} @ {report['timeframe_sec']}s "
          f"({c['ticks']:,} ticks, {c['span_days']:.2f}d) ==")
    print(f"{'leg':<10} {'trades':>5} {'WR':>6} {'ExpR':>7} {'net':>9}")
    for label, leg in report["legs"].items():
        print(
            f"{label:<10} {leg['trades']:>5} {leg['win_rate']:>5.0%} "
            f"{leg['expectancy_r']:>+7.3f} {leg['net_pnl']:>+9.2f}"
        )
    cmb = report["combined"]
    print(
        f"{'combined':<10} {cmb['trades']:>5} {cmb['win_rate']:>5.0%} "
        f"{cmb['expectancy_r']:>+7.3f} {cmb['net_pnl']:>+9.2f}"
    )
    ov = report["overlap"]
    print(
        f"overlap: both={ov['both']} opposite_dir={ov['opposite_dir']} "
        f"same_dir={ov['same_dir']} leg_a_only={ov['leg_a_only']} leg_b_only={ov['leg_b_only']}"
    )
    att = report["attribution"]
    for label, leg in report["legs"].items():
        print(
            f"  {label}: overlap-candle net={att[f'{label}.overlap']:+.2f} "
            f"(n={report['attribution_n'][f'{label}.overlap']}) "
            f"standalone net={att[f'{label}.standalone']:+.2f} "
            f"(n={report['attribution_n'][f'{label}.standalone']})"
        )
    corr = report["daily_corr"]
    corr_str = f"{corr:+.2f}" if corr is not None else "n/a"
    print(
        f"daily PnL correlation: {corr_str} over {report['daily_days']} days; "
        f"combined > best single on {report['lift_days']}/{report['lift_total_days']} days"
    )
    v = report["verdict"]
    print(f"verdict: {v['composite']} ({v['reason']})")
    if report.get("artifact"):
        print(f"artifact: {report['artifact']}")
