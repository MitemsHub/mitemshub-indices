"""Per-symbol tick coverage report: how much data exists, is it enough to re-run WFO.

The operator's blocker is data: one day of ticks gives only ~255 usable
walk-forward windows, and the WFO / horizon validation needs hundreds more
before the verdict is statistically meaningful.  This module answers three
questions per symbol:

1. **What do we have?**  ticks, span (hours), quality (duplicates,
   out-of-order), price range, per-day tick density.
2. **How much is enough?**  using the same window math as
   :func:`synthetic_trader.models.horizon_forecast.score_horizon_forecast`
   (candles − warmup − horizon bars), it reports usable walk-forward
   windows at each timeframe/horizon, and WFO readiness via the same
   sizing rules as :func:`synthetic_trader.research.run_wfo.size_windows`
   (≥30h span → day-scale WFO; ≥16h → 8h/2h; ≥8h → 4h/1h).
3. **When will we get there?**  at the observed tick density, how many
   more days until the span crosses each WFO threshold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.data.tick_store import inspect_ticks

# ── Thresholds shared with the research pipeline ────────────────────────
# Minimum windows for a meaningful walk-forward coverage verdict
# (mirrors score_horizon_forecast: verdict needs windows >= 30).
MIN_VALIDATION_WINDOWS = 30
# Warmup candles before the horizon forecaster is trusted.
WARMUP_BARS = 60
# Minimum ticks for the WFO to attempt an optimization at all.
MIN_WFO_TICKS = 200
# Span thresholds for WFO window sizing (see run_wfo.size_windows).
WFO_DAY_SCALE_SPAN_HOURS = 30.0
WFO_HOUR_SCALE_SPAN_HOURS = 16.0
WFO_COARSE_SCALE_SPAN_HOURS = 8.0


@dataclass(frozen=True)
class HorizonWindowEstimate:
    """Estimated usable walk-forward windows at one timeframe × horizon."""

    timeframe_sec: int
    horizon_hours: float
    n_candles: int
    usable_windows: int
    verdict_ready: bool  # usable_windows >= MIN_VALIDATION_WINDOWS

    def to_dict(self) -> dict:
        return {
            "timeframe_sec": self.timeframe_sec,
            "horizon_hours": self.horizon_hours,
            "n_candles": self.n_candles,
            "usable_windows": self.usable_windows,
            "verdict_ready": self.verdict_ready,
        }


@dataclass(frozen=True)
class WfoReadiness:
    """Whether the corpus is big enough for a meaningful WFO run."""

    ready: bool
    scale: str  # "day" | "hour" | "coarse" | "insufficient"
    is_days: float
    oos_days: float
    step_days: float
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "scale": self.scale,
            "is_days": self.is_days,
            "oos_days": self.oos_days,
            "step_days": self.step_days,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SymbolCoverage:
    symbol: str
    tick_csv: str | None
    ticks: int
    span_hours: float
    span_days: float
    duplicates: int
    out_of_order: int
    min_price: float | None
    max_price: float | None
    ticks_per_day: float
    max_gap_sec: float
    mean_interval_sec: float
    wfo: WfoReadiness
    horizons: tuple[HorizonWindowEstimate, ...]
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "tick_csv": self.tick_csv,
            "error": self.error,
            "ticks": self.ticks,
            "span_hours": round(self.span_hours, 2),
            "span_days": round(self.span_days, 2),
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "ticks_per_day": round(self.ticks_per_day, 1),
            "max_gap_sec": round(self.max_gap_sec, 1),
            "mean_interval_sec": round(self.mean_interval_sec, 3),
            "wfo": self.wfo.to_dict(),
            "horizons": [h.to_dict() for h in self.horizons],
        }


@dataclass(frozen=True)
class CoverageReport:
    symbols: tuple[SymbolCoverage, ...]
    generated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "symbols": [s.to_dict() for s in self.symbols],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _resolve_ticks(engine_root: str, symbol: str) -> tuple[list, str | None, str | None]:
    """Load + dedupe the best tick CSV for a symbol inside the engine root.

    Prefers the continuous-collection file (``data/backfill/{symbol}_ticks.csv``),
    then the legacy ``data/{symbol.lower()}_ticks.csv`` / ``{symbol}_ticks.csv``.
    Returns ``(ticks, csv_path, error)``.
    """
    root = Path(engine_root)
    candidates = [
        root / "data" / "backfill" / f"{symbol}_ticks.csv",
        root / "data" / f"{symbol.lower()}_ticks.csv",
        root / "data" / f"{symbol}_ticks.csv",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            try:
                ticks = dedupe_ticks(load_ticks_csv(candidate, default_symbol=symbol))
                return ticks, str(candidate), None
            except Exception as exc:  # pragma: no cover - defensive
                return [], str(candidate), f"load_failed: {exc}"
    return [], None, "no_tick_csv"


def _wfo_readiness(span_hours: float, ticks: int) -> WfoReadiness:
    """Mirror run_wfo.size_windows to say whether a WFO is meaningful now."""
    if ticks < MIN_WFO_TICKS:
        return WfoReadiness(
            ready=False,
            scale="insufficient",
            is_days=0.0,
            oos_days=0.0,
            step_days=0.0,
            reason=f"only {ticks} ticks (need >= {MIN_WFO_TICKS})",
        )
    if span_hours >= WFO_DAY_SCALE_SPAN_HOURS:
        return WfoReadiness(
            ready=True, scale="day", is_days=0.5, oos_days=0.1667, step_days=0.1667,
            reason="12h IS / 4h OOS / 4h step",
        )
    if span_hours >= WFO_HOUR_SCALE_SPAN_HOURS:
        return WfoReadiness(
            ready=True, scale="hour", is_days=0.3333, oos_days=0.0833, step_days=0.0833,
            reason="8h IS / 2h OOS / 2h step",
        )
    if span_hours >= WFO_COARSE_SCALE_SPAN_HOURS:
        return WfoReadiness(
            ready=True, scale="coarse", is_days=0.1667, oos_days=0.0417, step_days=0.0417,
            reason="4h IS / 1h OOS / 1h step",
        )
    return WfoReadiness(
        ready=False,
        scale="insufficient",
        is_days=0.02,
        oos_days=0.02,
        step_days=0.02,
        reason=f"{span_hours:.1f}h span (need >= {WFO_COARSE_SCALE_SPAN_HOURS:.0f}h)",
    )


def _horizon_estimates(
    ticks: list,
    span_hours: float,
    timeframes: tuple[int, ...],
    horizon_hours: tuple[float, ...],
) -> tuple[HorizonWindowEstimate, ...]:
    """Estimate usable walk-forward windows per timeframe × horizon.

    Window math mirrors ``score_horizon_forecast``: candles built from the
    tick span, each window covers ``horizon_bars`` candles, and the first
    ``WARMUP_BARS`` are consumed before windows count.  Usable windows ≈
    ``n_candles - horizon_bars - WARMUP_BARS`` (bounded at zero).
    """
    estimates: list[HorizonWindowEstimate] = []
    for timeframe_sec in timeframes:
        n_candles = max(0, int(span_hours * 3600 / timeframe_sec))
        for horizon in horizon_hours:
            horizon_bars = max(1, round(horizon * 3600 / timeframe_sec))
            usable = max(0, n_candles - horizon_bars - WARMUP_BARS)
            estimates.append(
                HorizonWindowEstimate(
                    timeframe_sec=timeframe_sec,
                    horizon_hours=horizon,
                    n_candles=n_candles,
                    usable_windows=usable,
                    verdict_ready=usable >= MIN_VALIDATION_WINDOWS,
                )
            )
    return tuple(estimates)


def compute_symbol_coverage(
    symbol: str,
    engine_root: str = ".",
    timeframes: tuple[int, ...] = (60, 300),
    horizon_hours: tuple[float, ...] = (4.0, 6.0),
) -> SymbolCoverage:
    """Compute the coverage report for one symbol."""
    ticks, csv_path, error = _resolve_ticks(engine_root, symbol)
    if error is not None or not ticks:
        return SymbolCoverage(
            symbol=symbol,
            tick_csv=csv_path,
            ticks=0,
            span_hours=0.0,
            span_days=0.0,
            duplicates=0,
            out_of_order=0,
            min_price=None,
            max_price=None,
            ticks_per_day=0.0,
            max_gap_sec=0.0,
            mean_interval_sec=0.0,
            wfo=_wfo_readiness(0.0, 0),
            horizons=(),
            error=error,
        )

    report = inspect_ticks(ticks, symbol=symbol)
    span_sec = max(0.0, (report.last_epoch or 0.0) - (report.first_epoch or 0.0))
    span_hours = span_sec / 3600.0
    span_days = span_hours / 24.0
    ticks_per_day = len(ticks) / span_days if span_days > 0 else 0.0

    intervals = [
        ticks[i + 1].epoch - ticks[i].epoch for i in range(len(ticks) - 1)
        if ticks[i + 1].epoch > ticks[i].epoch
    ]
    max_gap_sec = max(intervals) if intervals else 0.0
    mean_interval_sec = mean(intervals) if intervals else 0.0

    wfo = _wfo_readiness(span_hours, len(ticks))
    horizons = _horizon_estimates(ticks, span_hours, timeframes, horizon_hours)

    return SymbolCoverage(
        symbol=symbol,
        tick_csv=csv_path,
        ticks=len(ticks),
        span_hours=span_hours,
        span_days=span_days,
        duplicates=report.duplicates,
        out_of_order=report.out_of_order,
        min_price=report.min_price,
        max_price=report.max_price,
        ticks_per_day=ticks_per_day,
        max_gap_sec=max_gap_sec,
        mean_interval_sec=mean_interval_sec,
        wfo=wfo,
        horizons=horizons,
    )


def build_coverage_report(
    symbols: list[str],
    engine_root: str = ".",
    timeframes: tuple[int, ...] = (60, 300),
    horizon_hours: tuple[float, ...] = (4.0, 6.0),
) -> CoverageReport:
    """Build the per-symbol coverage report."""
    import time as _time

    return CoverageReport(
        symbols=tuple(
            compute_symbol_coverage(symbol, engine_root, timeframes, horizon_hours)
            for symbol in symbols
        ),
        generated_at=_time.time(),
    )


def render_coverage_report(report: CoverageReport) -> str:
    """Human-readable report for the operator."""
    lines = ["=== tick coverage ==="]
    for sym in report.symbols:
        lines.append(f"--- {sym.symbol} ---")
        if sym.error is not None:
            lines.append(f"  ERROR: {sym.error} ({sym.tick_csv or 'no csv'})")
            continue
        lines.append(f"  csv: {sym.tick_csv}")
        lines.append(
            f"  ticks: {sym.ticks:,}  span: {sym.span_hours:.1f}h ({sym.span_days:.1f}d)  "
            f"~{sym.ticks_per_day:,.0f} ticks/day"
        )
        lines.append(
            f"  quality: {sym.duplicates} dupes, {sym.out_of_order} out-of-order  "
            f"max gap {sym.max_gap_sec:.0f}s"
        )
        if sym.min_price is not None and sym.max_price is not None:
            lines.append(f"  price: {sym.min_price:.2f} → {sym.max_price:.2f}")
        wfo = sym.wfo
        if wfo.ready:
            lines.append(
                f"  WFO: READY ({wfo.scale}-scale, {wfo.reason})"
            )
        else:
            lines.append(f"  WFO: not yet ({wfo.reason})")
        for h in sym.horizons:
            status = "OK" if h.verdict_ready else "short"
            lines.append(
                f"  {h.timeframe_sec}s x {h.horizon_hours:g}h: {h.usable_windows} windows "
                f"(need {MIN_VALIDATION_WINDOWS}) [{status}]"
            )
    return "\n".join(lines)
