"""Milestone-gated full head-to-head verification (band vs fade vs momentum vs sniper).

The §40 head-to-head found the band geometry winning at ``+0.994R`` (23
trades on a 9.7-day corpus) — but a 23-trade cell is not a statistical
verdict.  This module re-runs the FULL four-strategy head-to-head (identical
configs and costs to ``backtest-vol --compare``) automatically once the
corpus crosses a milestone, so the +0.994R claim is re-tested on 40+ trades
without a manual step.

Design (mirrors :mod:`synthetic_trader.research.band_revalidate`):

1. **Span + growth gate** — skip fast unless the corpus span is ≥
   :data:`MIN_SPAN_DAYS` (14d) AND grew by ≥ :data:`MIN_GROWTH_DAYS` (4d)
   since the last verified span.  The growth re-run means the verify fires
   again at ~18d, when the ~2.4 entries/day band cadence reaches 40+ trades.
2. **Identical legs to the CLI** — the same ``VolBandConfig`` /
   ``VolReversionConfig`` / ``VolMomentumConfig`` defaults, calibrated EGARCH
   state, realistic costs (0.05 slip / 0.10 fee), and the sniper reference
   via ``BacktestEngine.run_ticks``.
3. **Honest verdict** — ``holds`` only when the band has ≥
   :data:`MILESTONE_TRADES` trades and expectancy ≥ :data:`HOLD_THRESHOLD_R`;
   ``insufficient_n`` when below the trade floor; ``edge_lost`` when the
   trades are there but the expectancy collapsed.
4. **Versioned artifact** — timestamped JSON + ``latest_{symbol}.json`` so
   the milestone history is preserved and the dashboard can surface it.

CLI: ``python -m synthetic_trader.cli verify-headtohead --symbol R_75``
(``--force`` bypasses the gates for a manual re-run; ``--min-span-days``
overrides the milestone).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from synthetic_trader.backtest.engine import BacktestEngine, load_ticks_csv
from synthetic_trader.backtest.vol_band import VolBandConfig, run_vol_band_backtest
from synthetic_trader.backtest.vol_momentum import (
    VolMomentumConfig,
    run_vol_momentum_backtest,
)
from synthetic_trader.backtest.vol_reversion import (
    VolReversionConfig,
    dedupe_ticks,
    run_vol_reversion_backtest,
)
from synthetic_trader.config import PaperExecutionConfig, TraderConfig

# ── Milestone thresholds ───────────────────────────────────────────────
MIN_SPAN_DAYS = 14.0  # first meaningful re-verify (was 9.7d at §40)
MIN_GROWTH_DAYS = 4.0  # re-run when the span grows this much past the last
# verified span — so it fires again at ~18d, when 40+ band trades are likely.
MILESTONE_TRADES = 40  # the statistical sample-size goal for the verdict
HOLD_THRESHOLD_R = 0.5  # expectancy must be >= this to call the cell "holds"
DEFAULT_ARTIFACT_SUBDIR = ".data/headtohead_verify"


def load_latest_verify(symbol: str, engine_root: str | Path = ".") -> dict[str, Any] | None:
    """Read the latest head-to-head verify artifact; None when absent."""
    d = Path(engine_root) / DEFAULT_ARTIFACT_SUBDIR
    path = d / f"latest_{symbol}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _span_days(ticks: list) -> float:
    if len(ticks) < 2:
        return 0.0
    return max(0.0, (ticks[-1].epoch - ticks[0].epoch) / 86400.0)


def _resolve_corpus(engine_root: str | Path, symbol: str) -> tuple[Path, list]:
    root = Path(engine_root)
    candidates = [
        root / "data" / "backfill" / f"{symbol}_ticks.csv",
        root / "data" / f"{symbol.lower()}_ticks.csv",
        root / "data" / f"{symbol}_ticks.csv",
    ]
    csv_path = next(
        (c for c in candidates if c.exists() and c.stat().st_size > 0), None
    )
    if csv_path is None:
        raise FileNotFoundError(f"no tick csv for {symbol} under {root}")
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    return csv_path, ticks


def _leg_result(label: str, result) -> dict[str, Any]:
    mt = result.metrics
    return {
        "strategy": label,
        "trades": mt.trades,
        "signals": result.signals,
        "rejected": result.rejected_signals,
        "win_rate": round(mt.win_rate, 4),
        "profit_factor": round(mt.profit_factor, 4),
        "expectancy_r": round(mt.expectancy_r, 4),
        "net_pnl": round(mt.net_pnl, 2),
        "final_equity": round(result.final_equity, 2),
        "model_version": result.model_version,
    }


def band_verdict(band: dict[str, Any]) -> dict[str, str]:
    """Honest verdict on the +0.994R cell at the milestone."""
    trades = band["trades"]
    exp = band["expectancy_r"]
    if trades < MILESTONE_TRADES:
        return {
            "status": "insufficient_n",
            "label": f"only {trades} trades (< {MILESTONE_TRADES}) — not a statistical verdict yet",
        }
    if exp >= HOLD_THRESHOLD_R:
        return {
            "status": "holds",
            "label": f"+{exp:.3f}R at {trades} trades — the §40 cell holds at sample size",
        }
    if exp > 0.0:
        return {
            "status": "positive_but_diluted",
            "label": f"+{exp:.3f}R at {trades} trades — still positive but below the {HOLD_THRESHOLD_R:.1f}R bar",
        }
    return {
        "status": "edge_lost",
        "label": f"{exp:.3f}R at {trades} trades — the edge is gone; re-tune the geometry",
    }


def run_headtohead_verify(
    *,
    symbol: str,
    engine_root: str | Path = ".",
    timeframe_sec: int = 300,
    min_span_days: float = MIN_SPAN_DAYS,
    min_growth_days: float = MIN_GROWTH_DAYS,
    force: bool = False,
    artifact_dir: str | Path | None = None,
    now: float | None = None,
    paper: PaperExecutionConfig | None = None,
) -> dict[str, Any]:
    """Run the full head-to-head when the milestone gates pass.

    Returns a JSON-serializable report with ``verdict == "skipped"`` +
    ``skip_reason`` when the span/growth gates fire.
    """
    root = Path(engine_root)
    artifact_dir = Path(artifact_dir) if artifact_dir else root / DEFAULT_ARTIFACT_SUBDIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    now_ts = now if now is not None else time.time()

    try:
        csv_path, ticks = _resolve_corpus(root, symbol)
    except FileNotFoundError as exc:
        return {"version": 1, "symbol": symbol, "generated_at": now_ts,
                "verdict": "skipped", "skip_reason": f"no_tick_csv: {exc}"}
    span_days = _span_days(ticks)

    # ── Gates ──────────────────────────────────────────────────────────
    if not force:
        if span_days < min_span_days:
            return {
                "version": 1, "symbol": symbol, "generated_at": now_ts,
                "verdict": "skipped",
                "skip_reason": f"span_too_short:{span_days:.2f}d<{min_span_days:.0f}d",
                "corpus": {"csv": str(csv_path), "ticks": len(ticks), "span_days": round(span_days, 3)},
            }
        previous = load_latest_verify(symbol, root)
        if previous is not None:
            prev_span = (previous.get("corpus") or {}).get("span_days", 0.0) or 0.0
            growth = span_days - prev_span
            if growth < min_growth_days:
                return {
                    "version": 1, "symbol": symbol, "generated_at": now_ts,
                    "verdict": "skipped",
                    "skip_reason": f"insufficient_growth:{growth:.2f}d<{min_growth_days:.0f}d",
                    "corpus": {"csv": str(csv_path), "ticks": len(ticks), "span_days": round(span_days, 3)},
                    "previous_span_days": round(prev_span, 3),
                }

    # ── Run the four legs (identical to backtest-vol --compare) ────────
    cost_paper = paper or PaperExecutionConfig(
        entry_slippage_ticks=0.05,
        exit_slippage_ticks=0.05,
        execution_penalty_per_trade=0.10,
    )
    trader = TraderConfig.default()
    from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

    garch_state = load_calibrated_garch_state(symbol)

    legs: dict[str, dict[str, Any]] = {}

    band_res = run_vol_band_backtest(
        ticks, symbol=symbol, timeframe_sec=timeframe_sec, config=trader,
        strategy_config=VolBandConfig(), garch_state=garch_state, paper=cost_paper,
    )
    legs["band"] = _leg_result("vol-band", band_res)

    fade_res = run_vol_reversion_backtest(
        ticks, symbol=symbol, timeframe_sec=timeframe_sec, config=trader,
        strategy_config=VolReversionConfig(), garch_state=garch_state, paper=cost_paper,
    )
    legs["fade"] = _leg_result("vol-reversion", fade_res)

    mom_res = run_vol_momentum_backtest(
        ticks, symbol=symbol, timeframe_sec=timeframe_sec, config=trader,
        strategy_config=VolMomentumConfig(), garch_state=garch_state, paper=cost_paper,
    )
    legs["momentum"] = _leg_result("vol-momentum", mom_res)

    sniper_engine = BacktestEngine(config=trader)
    sniper_res = sniper_engine.run_ticks(
        ticks, symbol=symbol, timeframe_sec=timeframe_sec,
    )
    legs["sniper"] = _leg_result("sniper", sniper_res)

    verdict = band_verdict(legs["band"])

    report: dict[str, Any] = {
        "version": 1,
        "symbol": symbol,
        "generated_at": now_ts,
        "timeframe_sec": timeframe_sec,
        "verdict": verdict["status"],
        "verdict_label": verdict["label"],
        "corpus": {
            "csv": str(csv_path),
            "ticks": len(ticks),
            "span_days": round(span_days, 3),
        },
        "legs": legs,
        "milestone": {
            "min_span_days": min_span_days,
            "milestone_trades": MILESTONE_TRADES,
            "hold_threshold_r": HOLD_THRESHOLD_R,
        },
    }

    versioned = artifact_dir / (
        f"{symbol}_headtohead_{time.strftime('%Y%m%d_%H%M%S', time.gmtime(now_ts))}.json"
    )
    versioned.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest = artifact_dir / f"latest_{symbol}.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact"] = str(latest)
    report["versioned_artifact"] = str(versioned)
    return report


def print_verify_report(report: dict[str, Any]) -> None:
    if report["verdict"] == "skipped":
        print(f"verify-headtohead {report['symbol']}: SKIPPED ({report['skip_reason']})")
        return
    c = report["corpus"]
    print(f"== head-to-head {report['symbol']} @ {report['timeframe_sec']}s "
          f"({c['ticks']:,} ticks, {c['span_days']:.2f}d) ==")
    print(f"{'strategy':<12} {'trades':>5} {'WR':>6} {'PF':>6} {'ExpR':>7} {'net':>9}")
    for label, leg in report["legs"].items():
        print(
            f"{label:<12} {leg['trades']:>5} {leg['win_rate']:>5.0%} "
            f"{leg['profit_factor']:>6.2f} {leg['expectancy_r']:>+7.3f} {leg['net_pnl']:>+9.2f}"
        )
    print(f"verdict: {report['verdict_label']}")
    print(f"artifact: {report.get('artifact')}")
