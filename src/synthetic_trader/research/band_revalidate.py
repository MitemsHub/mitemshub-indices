"""Weekly band-geometry re-validation harness.

The §38 sweep found the winning vol-band geometry cell on a 9.5-day corpus
(``z 1.0 / vol 1.3 / stop 0.20σ / target 0.80σ / 1h hold`` → +0.994R at 23
trades on R_75 @300s).  But a corpus is a moving target: as the collector
compounds data, the market's volatility regime can drift and the once-best
cell can stop being best.  This module keeps the **live geometry tracking
the freshest data** by re-validating around the current defaults on a
weekly cadence:

1. **Growth gate** — skip fast unless ≥ :data:`MIN_ELAPSED_DAYS` elapsed
   since the last run AND the corpus span grew by ≥
   :data:`MIN_GROWTH_DAYS` since the last run's recorded span.  A dead or
   stalled collector must not trigger useless (and expensive) re-sweeps.
2. **Focused local sweep** — a small grid *around the current defaults*
   (not the full §38 grid) over the band geometry knobs, run on the
   **train split** (older 80% of the corpus by time).
3. **Honest holdout** — the top candidates AND the current default are
   re-run on the **holdout split** (newest 20%).  A candidate is promoted
   only if it beats the current default on the holdout by ≥
   :data:`PROMOTE_MARGIN_R` with ≥ :data:`MIN_HOLDOUT_TRADES` trades —
   otherwise the verdict is ``keep``.
4. **Versioned artifact** — every run writes a timestamped artifact plus a
   ``latest.json`` the live path reads.  ``_live_band_signal`` overlays the
   promoted knobs on ``VolBandConfig`` only while the artifact is fresh
   (≤ :data:`MAX_ARTIFACT_AGE_DAYS`); stale artifacts fall back to the
   compiled defaults.

The harness is deliberately cheap when nothing changed: the growth gate is
a JSON read + a span computation, so piggybacking it on the daily collector
task costs seconds on the 6 of 7 days it skips.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_band import VolBandConfig, run_vol_band_backtest
from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.config import PaperExecutionConfig, TraderConfig

# ── Cadence / freshness ────────────────────────────────────────────────
# Minimum wall-clock time between re-validation runs (weekly cadence).
MIN_ELAPSED_DAYS = 7.0
# Minimum corpus span growth (in days) since the last run before a re-sweep
# is worth it.  ~6 days of new data ≈ one full week of the collector.
MIN_GROWTH_DAYS = 6.0
# A promoted artifact older than this is treated as stale by the live path
# (falls back to compiled defaults) — the collector may have died and the
# "promoted" geometry is no longer validated by fresh data.
MAX_ARTIFACT_AGE_DAYS = 21.0

# ── Train / holdout split ──────────────────────────────────────────────
TRAIN_FRAC = 0.8  # older 80% trains the re-sweep when the corpus is large
# The holdout is the newest ``hold_min_days`` of wall-clock (at minimum the
# newest ``1 - TRAIN_FRAC`` of the span).  A fixed minimum matters because
# the band gate is selective (~2 entries/day): a pure 20% slice of a young
# corpus can contain ZERO entries, making the verdict vacuous.  3 days ≈
# 4-6 entries at the observed cadence — enough to mean something.
HOLD_MIN_DAYS = 3.0
# The train split always keeps at least this fraction of ticks, so a tiny
# corpus can't hand everything to the holdout.
MIN_TRAIN_FRAC = 0.4

# ── Promotion rules ────────────────────────────────────────────────────
# Minimum trades on the HOLDOUT for a candidate to be promotable (a config
# with 2 holdout trades can't support a promotion claim).
MIN_HOLDOUT_TRADES = 6
# Minimum trades on the TRAIN for a candidate to enter the candidate set.
MIN_TRAIN_TRADES = 10
# A candidate must beat the current default's holdout expectancy by at
# least this many R/trade to be promoted (guards against noise-promotion).
PROMOTE_MARGIN_R = 0.05
# Absolute floor on holdout expectancy for promotion (never promote a
# config that is itself unprofitable on fresh data).
PROMOTE_MIN_EXPECTANCY_R = 0.10
# How many top train candidates get a holdout re-run.
TOP_N_CANDIDATES = 5

# ── Focused grid around the current defaults (overridable) ─────────────
# Small deltas around the §38 winner so re-validation is local, not an
# exhaustive re-discovery.  3×3×3×3×2 = 162 configs per symbol.
DEFAULT_GRID = {
    # z_entry: 0.75, 1.0, 1.25
    "z_entries": (0.75, 1.25, 0.25),
    # vol_extended_ratio: 1.15, 1.3, 1.45
    "vol_ratios": (1.15, 1.45, 0.15),
    # stop_sigma_mult: 0.15, 0.20, 0.25, 0.30
    "stops": (0.15, 0.30, 0.05),
    # target_sigma_mult: 0.60, 0.80, 1.00
    "targets": (0.60, 1.00, 0.20),
    # max_hold_sec: 1h, 2h
    "holds": (3600, 7200, 3600),
}

# Default artifact location, relative to the engine root.
DEFAULT_ARTIFACT_SUBDIR = ".data/band_revalidate"


# ── Artifact I/O ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class SplitStats:
    ticks: int
    span_days: float
    first_epoch: float
    last_epoch: float

    def to_dict(self) -> dict:
        return {
            "ticks": self.ticks,
            "span_days": round(self.span_days, 3),
            "first_epoch": self.first_epoch,
            "last_epoch": self.last_epoch,
        }


def _span_days(ticks: list) -> float:
    if len(ticks) < 2:
        return 0.0
    return max(0.0, (ticks[-1].epoch - ticks[0].epoch) / 86400.0)


def split_ticks(
    ticks: list,
    train_frac: float = TRAIN_FRAC,
    hold_min_days: float = HOLD_MIN_DAYS,
) -> tuple[list, list]:
    """Split by time into ``(train, holdout)``.

    Holdout = the newest ``hold_min_days`` of wall-clock data, or the
    newest ``(1 - train_frac)`` of the span when the corpus is large enough
    for that to exceed ``hold_min_days`` — whichever is longer, capped so
    the train split keeps at least :data:`MIN_TRAIN_FRAC` of the ticks.
    Ticks must be sorted ascending by epoch.
    """
    if not ticks:
        return [], []
    span = ticks[-1].epoch - ticks[0].epoch
    hold_span = max(span * (1.0 - train_frac), hold_min_days * 86400.0)
    hold_span = min(hold_span, span * (1.0 - MIN_TRAIN_FRAC))
    import bisect

    epochs = [t.epoch for t in ticks]
    cut = bisect.bisect_left(epochs, ticks[-1].epoch - hold_span)
    cut = max(1, min(cut, len(ticks) - 1))
    return ticks[:cut], ticks[cut:]


def split_stats(ticks: list) -> SplitStats:
    if not ticks:
        return SplitStats(0, 0.0, 0.0, 0.0)
    return SplitStats(
        ticks=len(ticks),
        span_days=_span_days(ticks),
        first_epoch=float(ticks[0].epoch),
        last_epoch=float(ticks[-1].epoch),
    )


def artifact_paths(artifact_dir: str | Path) -> tuple[Path, Path]:
    """(latest.json, timestamped artifact dir) inside artifact_dir."""
    d = Path(artifact_dir)
    return d / "latest.json", d


def load_latest_artifact(
    symbol: str, artifact_dir: str | Path
) -> dict[str, Any] | None:
    """Read the latest artifact for a symbol; None when absent/unreadable."""
    latest, _ = artifact_paths(artifact_dir)
    path = latest.with_name(f"latest_{symbol}.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_live_band_overrides(
    symbol: str,
    engine_root: str | Path = ".",
    *,
    now: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fresh promoted knobs for the live path, or ``({}, None)``.

    Returns ``(overrides, artifact)`` where ``overrides`` maps
    ``VolBandConfig`` field names to promoted values.  Empty dict when there
    is no artifact, the artifact is stale (> MAX_ARTIFACT_AGE_DAYS), or its
    verdict is not ``promote`` — the caller falls back to compiled defaults.
    """
    artifact = load_latest_artifact(symbol, Path(engine_root) / DEFAULT_ARTIFACT_SUBDIR)
    if artifact is None:
        return {}, None
    generated_at = artifact.get("generated_at", 0.0)
    age_days = ((now if now is not None else time.time()) - generated_at) / 86400.0
    if age_days > MAX_ARTIFACT_AGE_DAYS:
        return {}, artifact
    promoted = artifact.get("promoted")
    if artifact.get("verdict") != "promote" or not isinstance(promoted, dict):
        return {}, artifact
    knobs = (
        "z_entry",
        "vol_extended_ratio",
        "stop_sigma_mult",
        "target_sigma_mult",
        "max_hold_sec",
    )
    return {k: promoted["config"][k] for k in knobs if k in promoted.get("config", {})}, artifact


# ── The re-validation run ──────────────────────────────────────────────
def focused_band_grid(
    overrides: dict[str, Any] | None = None,
) -> list[VolBandConfig]:
    """Cartesian grid around the current defaults (all ranges overridable)."""
    from synthetic_trader.research.vol_param_sweep import _arange, band_grid

    grid = dict(DEFAULT_GRID)
    if overrides:
        grid.update({k: tuple(v) for k, v in overrides.items() if v is not None})
    return band_grid(**grid)


def _run_band_on(
    ticks: list,
    symbol: str,
    timeframe_sec: int,
    config: VolBandConfig,
    *,
    paper: PaperExecutionConfig,
    trader: TraderConfig,
    garch_state,
    count_from_epoch: float | None = None,
    count_until_epoch: float | None = None,
) -> tuple[int, float, float]:
    """Run the band backtest with a walk-forward count window.

    The whole ``ticks`` stream is always fed to the strategy/broker/risk
    pipeline (state carries full history, exactly like a live process); the
    window only decides which signals/trades are COUNTED.  Returns
    ``(trades, expectancy_r, net_pnl)``.
    """
    res = run_vol_band_backtest(
        ticks,
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        config=trader,
        strategy_config=config,
        garch_state=garch_state,
        paper=paper,
        count_from_epoch=count_from_epoch,
        count_until_epoch=count_until_epoch,
    )
    return res.metrics.trades, res.metrics.expectancy_r, res.metrics.net_pnl


def revalidate_band_geometry(
    *,
    symbol: str,
    engine_root: str | Path = ".",
    timeframe_sec: int = 300,
    grid_overrides: dict[str, Any] | None = None,
    min_train_trades: int = MIN_TRAIN_TRADES,
    min_holdout_trades: int = MIN_HOLDOUT_TRADES,
    promote_margin_r: float = PROMOTE_MARGIN_R,
    promote_min_expectancy_r: float = PROMOTE_MIN_EXPECTANCY_R,
    top_n: int = TOP_N_CANDIDATES,
    force: bool = False,
    artifact_dir: str | Path | None = None,
    now: float | None = None,
    paper: PaperExecutionConfig | None = None,
    garch_state=None,
) -> dict[str, Any]:
    """Run the weekly re-validation for one symbol.

    Returns a JSON-serializable report.  When the growth or elapsed gate
    fires, the report has ``verdict == "skipped"`` with a ``skip_reason``.
    """
    from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

    root = Path(engine_root)
    artifact_dir = Path(artifact_dir) if artifact_dir else root / DEFAULT_ARTIFACT_SUBDIR
    latest_path, versioned_dir = artifact_paths(artifact_dir)
    latest_path = latest_path.with_name(f"latest_{symbol}.json")
    versioned_dir.mkdir(parents=True, exist_ok=True)

    now_ts = now if now is not None else time.time()

    # Resolve the corpus (continuous-collection file first, like
    # tick-coverage does).
    csv_candidates = [
        root / "data" / "backfill" / f"{symbol}_ticks.csv",
        root / "data" / f"{symbol.lower()}_ticks.csv",
        root / "data" / f"{symbol}_ticks.csv",
    ]
    csv_path = next((c for c in csv_candidates if c.exists() and c.stat().st_size > 0), None)
    if csv_path is None:
        return {
            "version": 1,
            "symbol": symbol,
            "generated_at": now_ts,
            "verdict": "skipped",
            "skip_reason": f"no_tick_csv_for_{symbol}",
            "corpus": None,
        }
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    if len(ticks) < 400:
        return {
            "version": 1,
            "symbol": symbol,
            "generated_at": now_ts,
            "verdict": "skipped",
            "skip_reason": f"corpus_too_small:{len(ticks)}",
            "corpus": {"csv": str(csv_path), "ticks": len(ticks), "span_days": round(_span_days(ticks), 3)},
        }
    corpus_span_days = _span_days(ticks)

    # ── Gates ──────────────────────────────────────────────────────────
    previous = load_latest_artifact(symbol, artifact_dir)
    if previous is not None and not force:
        elapsed_days = (now_ts - previous.get("generated_at", 0.0)) / 86400.0
        if elapsed_days < MIN_ELAPSED_DAYS:
            return {
                "version": 1,
                "symbol": symbol,
                "generated_at": now_ts,
                "verdict": "skipped",
                "skip_reason": f"too_soon:{elapsed_days:.1f}d<{MIN_ELAPSED_DAYS:.0f}d",
                "corpus": {"csv": str(csv_path), "ticks": len(ticks), "span_days": round(corpus_span_days, 3)},
            }
        prev_corpus = previous.get("corpus") or {}
        prev_span = prev_corpus.get("span_days", 0.0) or 0.0
        growth = corpus_span_days - prev_span
        if growth < MIN_GROWTH_DAYS:
            return {
                "version": 1,
                "symbol": symbol,
                "generated_at": now_ts,
                "verdict": "skipped",
                "skip_reason": f"insufficient_growth:{growth:.2f}d<{MIN_GROWTH_DAYS:.0f}d",
                "corpus": {"csv": str(csv_path), "ticks": len(ticks), "span_days": round(corpus_span_days, 3)},
                "previous_span_days": round(prev_span, 3),
            }

    # ── Splits ─────────────────────────────────────────────────────────
    train, holdout = split_ticks(ticks)
    train_stats = split_stats(train)
    holdout_stats = split_stats(holdout)

    trader = TraderConfig.default()
    cost_paper = paper or PaperExecutionConfig(
        entry_slippage_ticks=0.05,
        exit_slippage_ticks=0.05,
        execution_penalty_per_trade=0.10,
    )
    if garch_state is None:
        garch_state = load_calibrated_garch_state(symbol)

    # Walk-forward window: every config runs ONCE over the full corpus with
    # the strategy/broker/risk state carrying the entire history (exactly
    # like a live process).  The train window counts trades opened before
    # the holdout boundary; the holdout window counts trades opened from it.
    boundary_epoch = float(holdout[0].epoch)

    default_config = VolBandConfig()
    default_hold = _run_band_on(
        ticks, symbol, timeframe_sec, default_config,
        paper=cost_paper, trader=trader, garch_state=garch_state,
        count_from_epoch=boundary_epoch,
    )

    # ── Train sweep (focused grid, count window = pre-holdout) ─────────
    grid = focused_band_grid(grid_overrides)
    train_rows: list[tuple[VolBandConfig, tuple[int, float, float]]] = []
    for cfg in grid:
        metrics = _run_band_on(
            ticks, symbol, timeframe_sec, cfg,
            paper=cost_paper, trader=trader, garch_state=garch_state,
            count_until_epoch=boundary_epoch,
        )
        train_rows.append((cfg, metrics))
    eligible = [(c, m) for c, m in train_rows if m[0] >= min_train_trades]
    eligible.sort(key=lambda cm: cm[1][1], reverse=True)

    # ── Holdout validation of top candidates ───────────────────────────
    candidates: list[dict[str, Any]] = []
    for cfg, train_metrics in eligible[:top_n]:
        hold_metrics = _run_band_on(
            ticks, symbol, timeframe_sec, cfg,
            paper=cost_paper, trader=trader, garch_state=garch_state,
            count_from_epoch=boundary_epoch,
        )
        candidates.append(
            {
                "config": asdict(cfg),
                "train": {
                    "trades": train_metrics[0],
                    "expectancy_r": round(train_metrics[1], 4),
                    "net_pnl": round(train_metrics[2], 2),
                },
                "holdout": {
                    "trades": hold_metrics[0],
                    "expectancy_r": round(hold_metrics[1], 4),
                    "net_pnl": round(hold_metrics[2], 2),
                },
            }
        )

    default_hold_trades, default_hold_exp, default_hold_net = default_hold
    promoted = decide_promotion(
        candidates,
        default_hold_exp,
        min_holdout_trades=min_holdout_trades,
        promote_margin_r=promote_margin_r,
        promote_min_expectancy_r=promote_min_expectancy_r,
    )
    verdict = "promote" if promoted is not None else "keep"

    report: dict[str, Any] = {
        "version": 1,
        "symbol": symbol,
        "generated_at": now_ts,
        "verdict": verdict,
        "corpus": {
            "csv": str(csv_path),
            "ticks": len(ticks),
            "span_days": round(corpus_span_days, 3),
        },
        "train": train_stats.to_dict(),
        "holdout": holdout_stats.to_dict(),
        "timeframe_sec": timeframe_sec,
        "boundary_epoch": boundary_epoch,
        "grid": {
            "configs_tested": len(grid),
            "train_eligible": len(eligible),
            "ranges": {
                k: list(v)
                for k, v in {**DEFAULT_GRID, **(grid_overrides or {})}.items()
            },
        },
        "default": {
            "config": asdict(default_config),
            "holdout": {
                "trades": default_hold_trades,
                "expectancy_r": round(default_hold_exp, 4),
                "net_pnl": round(default_hold_net, 2),
            },
        },
        "promoted": promoted,
        "top_candidates": candidates,
    }

    # ── Persist versioned + latest ─────────────────────────────────────
    versioned = versioned_dir / (
        f"{symbol}_revalidate_{time.strftime('%Y%m%d_%H%M%S', time.gmtime(now_ts))}.json"
    )
    versioned.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact"] = str(latest_path)
    report["versioned_artifact"] = str(versioned)
    return report


def print_revalidate_report(report: dict[str, Any]) -> None:
    symbol = report["symbol"]
    if report["verdict"] == "skipped":
        print(f"band-revalidate {symbol}: SKIPPED ({report['skip_reason']})")
        return
    corpus = report["corpus"]
    print(f"== band-revalidate {symbol} @ {report['timeframe_sec']}s ==")
    print(
        f"corpus: {corpus['ticks']:,} ticks, {corpus['span_days']:.2f}d "
        f"(train {report['train']['span_days']:.2f}d / holdout {report['holdout']['span_days']:.2f}d)"
    )
    print(f"grid: {report['grid']['configs_tested']} configs, "
          f"{report['grid']['train_eligible']} eligible on train")
    d = report["default"]["holdout"]
    print(
        f"default holdout: trades={d['trades']} expR={d['expectancy_r']:+.3f} "
        f"net={d['net_pnl']:+.2f}"
    )
    if report["promoted"] is not None:
        p = report["promoted"]
        cfg = {k: p["config"][k] for k in (
            "z_entry", "vol_extended_ratio", "stop_sigma_mult",
            "target_sigma_mult", "max_hold_sec")}
        print(f"PROMOTED: {json.dumps(cfg)}")
        print(
            f"  train: trades={p['train']['trades']} expR={p['train']['expectancy_r']:+.3f} | "
            f"holdout: trades={p['holdout']['trades']} expR={p['holdout']['expectancy_r']:+.3f}"
        )
    else:
        print("verdict: keep (default geometry stays)")
    print(f"artifact: {report.get('artifact')}")


def decide_promotion(
    candidates: list[dict[str, Any]],
    default_hold_exp: float,
    *,
    min_holdout_trades: int = MIN_HOLDOUT_TRADES,
    promote_margin_r: float = PROMOTE_MARGIN_R,
    promote_min_expectancy_r: float = PROMOTE_MIN_EXPECTANCY_R,
) -> dict[str, Any] | None:
    """Pick the first candidate that beats the default on the holdout.

    A candidate is promotable only when it (a) has enough holdout trades to
    mean something, (b) is itself profitable on fresh data, and (c) beats
    the current default's holdout expectancy by the margin — otherwise the
    verdict stays ``keep`` and the compiled defaults remain live.
    """
    for cand in candidates:
        h = cand["holdout"]
        if h["trades"] < min_holdout_trades:
            continue
        if h["expectancy_r"] < promote_min_expectancy_r:
            continue
        if h["expectancy_r"] < default_hold_exp + promote_margin_r:
            continue
        return cand
    return None


def revalidate_for_symbols(
    symbols: list[str],
    engine_root: str | Path = ".",
    **kwargs: Any,
) -> dict[str, Any]:
    """Run re-validation for several symbols; returns {symbol: report}."""
    return {
        symbol: revalidate_band_geometry(symbol=symbol, engine_root=engine_root, **kwargs)
        for symbol in symbols
    }
