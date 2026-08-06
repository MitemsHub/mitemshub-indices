"""Live horizon volatility forecast stats for the operator dashboard.

Called by the Next.js API route /api/system/forecast-horizon to surface the
current 4h/6h p50/p90 volatility bands, the ADWIN drift state, and the
walk-forward calibration (coverage, fitted range multipliers, verdict) for
both symbols.

This is the live engine output of :mod:`synthetic_trader.models.horizon_forecast`:
the honest, calibrated answer to "what does the next 4-6 hours of volatility
look like" — not a directional prediction (which is impossible on CSPRNG price).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.models.garch_calibration import load_calibrated_garch_state
from synthetic_trader.models.horizon_forecast import (
    HorizonVolForecaster,
    horizon_verdict,
    load_forecast_multipliers,
    score_horizon_forecast,
)

HORIZON_HOURS = (4, 6)
TIMEFRAME_SEC = 60  # the timeframe that calibrated walk-forward validation

# Stage-3 gate reads this cache (see synthetic_trader.live.stage3_gate) so a
# call can be annotated with the current horizon verdict without re-running
# the expensive walk-forward replay on every snapshot.
VERDICT_CACHE_REL = "data/forecast_verdicts.json"


def _resolve_tick_csv(engine_root: str, symbol: str) -> Path | None:
    """Find the best tick CSV for a symbol inside the engine root.

    Prefers the multi-day backfill file (correct Blueberry scale), then the
    live capture file (``data/{symbol_lower}_ticks.csv`` or ``{symbol}``).
    """
    root = Path(engine_root)
    candidates = [
        root / "data" / "backfill" / f"{symbol}_ticks.csv",
        root / "data" / f"{symbol.lower()}_ticks.csv",
        root / "data" / f"{symbol}_ticks.csv",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def _feed_forecaster(
    ticks: list,
    symbol: str,
    garch_state,
) -> tuple[HorizonVolForecaster, float | None]:
    """Replay ticks ONCE into a fresh forecaster; return it plus the last close.

    The forecaster state is independent of the horizon (``forecast()`` only
    projects from it), so one replay serves both 4h and 6h — no per-horizon
    duplicate replays of the full tick history.
    """
    forecaster = HorizonVolForecaster(
        symbol,
        timeframe_sec=TIMEFRAME_SEC,
        garch_state=garch_state,
    )
    builder = MultiTimeframeCandleBuilder(symbol, [TIMEFRAME_SEC])
    for tick in sorted(ticks, key=lambda item: item.epoch):
        closed = builder.update(tick)
        for tf, candle in closed.items():
            if tf == TIMEFRAME_SEC:
                forecaster.on_candle(candle)
    final_candle = builder.flush().get(TIMEFRAME_SEC)
    current_close = final_candle.close if final_candle else None
    return forecaster, current_close


def tune_all_multipliers(engine_root: str) -> dict[str, object]:
    """Band-tuning pass: re-fit p50/p90 range multipliers for R_75/R_100.

    For each symbol the tick corpus is resolved exactly as the dashboard does,
    then ``tune_forecast_multipliers`` re-fits the 4h and 6h multipliers on
    the RECENT walk-forward holdout and persists the tuned values to
    ``data/forecast_multipliers``.  Only symbols/horizons that reach
    "calibrated" on the holdout are persisted — anything still short of data
    is reported but left untouched (the dashboard keeps showing the honest
    ``needs_more_data_or_tuning`` verdict for it).
    """
    from synthetic_trader.models.horizon_forecast import tune_forecast_multipliers

    report: dict[str, object] = {}
    for symbol in ("R_75", "R_100"):
        csv_path = _resolve_tick_csv(engine_root, symbol)
        if csv_path is None:
            report[symbol] = {"error": "no_tick_csv"}
            continue
        ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
        if len(ticks) < 200:
            report[symbol] = {"error": "insufficient_ticks", "ticks": len(ticks)}
            continue
        garch_state = load_calibrated_garch_state(symbol)
        multiplier_dir = Path(engine_root) / "data" / "forecast_multipliers"
        symbol_report: dict[str, object] = {}
        for hours in HORIZON_HOURS:
            horizon_sec = hours * 3600
            tuned = tune_forecast_multipliers(
                symbol,
                ticks,
                horizon_sec=horizon_sec,
                timeframe_sec=TIMEFRAME_SEC,
                garch_state=garch_state,
                multiplier_dir=multiplier_dir,
            )
            symbol_report[f"{hours}h"] = tuned
        report[symbol] = symbol_report
    return report


def get_horizon_forecast_stats(engine_root: str) -> dict[str, object]:
    """Return live horizon forecast + calibration stats for R_75 and R_100."""
    result: dict[str, object] = {}
    for symbol in ("R_75", "R_100"):
        csv_path = _resolve_tick_csv(engine_root, symbol)
        if csv_path is None:
            result[symbol] = {"error": "no_tick_csv"}
            continue

        ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
        if len(ticks) < 200:
            result[symbol] = {"error": "insufficient_ticks", "ticks": len(ticks)}
            continue

        garch_state = load_calibrated_garch_state(symbol)
        # One tick replay per symbol; both horizons project from this state.
        forecaster, current_close = _feed_forecaster(ticks, symbol, garch_state)

        # Empirically calibrated range multipliers (from forecast-horizon
        # --fit-multipliers).  When present, the live bands AND the reported
        # coverage use them instead of the Gaussian priors — the honest
        # calibration the walk-forward fitting is designed to provide.
        multipliers = load_forecast_multipliers(
            symbol,
            TIMEFRAME_SEC,
            Path(engine_root) / "data" / "forecast_multipliers",
        )
        entry: dict[str, object] = {
            "symbol": symbol,
            "timeframe_sec": TIMEFRAME_SEC,
            "tick_csv": str(csv_path),
            "ticks": len(ticks),
            "garch_calibrated": garch_state is not None,
            "error": None,
            "horizons": {},
        }
        for hours in HORIZON_HOURS:
            horizon_sec = hours * 3600
            horizon_key = f"{hours}h"
            mult = (multipliers or {}).get(horizon_key)
            p50 = mult.get("p50_mult") if mult else None
            p90 = mult.get("p90_mult") if mult else None
            validation = score_horizon_forecast(
                ticks,
                symbol=symbol,
                horizon_sec=horizon_sec,
                timeframe_sec=TIMEFRAME_SEC,
                garch_state=garch_state,
                p50_mult=p50,
                p90_mult=p90,
            )
            live = forecaster.forecast(
                horizon_sec,
                current_close=current_close,
                p50_mult=p50,
                p90_mult=p90,
            )
            entry["horizons"][horizon_key] = {
                "horizon_sec": horizon_sec,
                "verdict": horizon_verdict(validation),
                "multipliers_applied": mult is not None,
                "p50_mult": p50,
                "p90_mult": p90,
                "validation": validation.to_dict(),
                "forecast": live.to_dict(),
            }
        result[symbol] = entry

    _persist_verdict_cache(Path(engine_root), result)
    return result


# Forecast-detail keys that ride on the verdict cache so the Stage-3 gate can
# annotate a call with the ACTUAL calibrated 60s p50/p90 multipliers and the
# live band numbers (not just the verdict label) without re-running the
# expensive walk-forward replay on every snapshot.
_FORECAST_CACHE_KEYS = (
    "current_close",
    "range_p50_price",
    "range_p90_price",
    "expected_low_p50",
    "expected_high_p50",
    "expected_low_p90",
    "expected_high_p90",
    "projected_sigma_avg",
    "confidence",
    "vol_trend",
)


def _persist_verdict_cache(engine_root: Path, stats: dict[str, object]) -> None:
    """Write a compact per-symbol horizon verdict cache for the Stage-3 gate
    and the calibration health panel.

    One JSONL record keyed by symbol → {4h: {verdict, windows, coverage_p50,
    coverage_p90, p50_mult, p90_mult, forecast: {...}}, 6h: {...}}; readers
    fetch it with a cheap file read instead of replaying the tick corpus.  The
    tuned multipliers + live band numbers are the payload the call path needs
    so ``tune-bands`` output reaches the operator-facing call.
    """
    cache: dict[str, object] = {}
    for symbol, entry in stats.items():
        if not isinstance(entry, dict) or entry.get("error"):
            continue
        horizons = entry.get("horizons")
        if not isinstance(horizons, dict):
            continue
        per_symbol: dict[str, dict[str, object]] = {}
        for label, horizon in horizons.items():
            if not isinstance(horizon, dict):
                continue
            verdict = horizon.get("verdict")
            validation = horizon.get("validation")
            if not isinstance(verdict, str):
                continue
            detail: dict[str, object] = {"verdict": verdict}
            if isinstance(validation, dict):
                for key in ("windows", "coverage_p50", "coverage_p90"):
                    value = validation.get(key)
                    if isinstance(value, (int, float)):
                        detail[key] = value
            # The tuned range multipliers that produced the live bands — the
            # direct answer to "which 60s p50/p90 multipliers are in force".
            for key in ("p50_mult", "p90_mult"):
                value = horizon.get(key)
                if isinstance(value, (int, float)):
                    detail[key] = value
            # Whether those multipliers were TUNED (walk-forward fitted) or the
            # forecast fell back to Gaussian priors — lets the UI distinguish
            # "calibrated" bands from prior-based bands without guessing.
            if isinstance(horizon.get("multipliers_applied"), bool):
                detail["multipliers_applied"] = horizon["multipliers_applied"]
            # The live forecast band numbers (computed with those multipliers)
            # so the call payload can show the calibrated p50/p90 range.
            forecast = horizon.get("forecast")
            if isinstance(forecast, dict):
                compact: dict[str, object] = {}
                for key in _FORECAST_CACHE_KEYS:
                    value = forecast.get(key)
                    if isinstance(value, (int, float, str)):
                        compact[key] = value
                if compact:
                    detail["forecast"] = compact
            per_symbol[label] = detail
        if per_symbol:
            cache[symbol] = per_symbol
    if not cache:
        return
    try:
        path = engine_root / VERDICT_CACHE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cache) + "\n")
    except OSError:
        # Best-effort — the gate degrades to insufficient_data without it.
        pass


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(get_horizon_forecast_stats(root)))
