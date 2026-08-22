"""Calibration health stats for the operator dashboard.

Surfaces, per symbol:

- the persisted horizon validation (windows, coverage_p50/p90, verdict per
  4h/6h horizon) read from ``data/forecast_verdicts.json`` — the same cache
  the Stage-3 gate and the /api/system/forecast-horizon computation write,
  so the panel never replays the tick corpus itself; and
- per-trigger-type target-hit rates from the scored outcomes journal
  (``journals/live_calibration_outcomes.jsonl``, written by
  ``synth-trader score-live-calibration``).

This is the honest "how calibrated are the calls I am being shown" view: the
horizon verdicts say whether the volatility bands generalize, and the
per-trigger rates say whether the specific setups the engine emits actually
reach their targets in the market.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from synthetic_trader.live.calibration_scorer import (
    load_jsonl_records,
    summarize_outcomes,
)
from synthetic_trader.live.stage3_gate import (
    DEFAULT_OUTCOMES_PATH,
    GATE_HIT_RATE_FLOOR,
    MIN_STAGE3_SAMPLES,
)

VERDICT_CACHE_REL = "data/forecast_verdicts.json"
HORIZON_LABELS = ("4h", "6h")
MIN_SAMPLES = MIN_STAGE3_SAMPLES  # matches stage3_gate.MIN_STAGE3_SAMPLES


def _read_last_cache_record(path: Path) -> dict[str, Any]:
    """Read the most recent JSONL record from the verdict cache."""
    if not path.exists():
        return {}
    try:
        records = load_jsonl_records(path)
    except (OSError, ValueError):
        return {}
    last = records[-1] if records else {}
    return last if isinstance(last, dict) else {}


def _horizon_detail(entry: Any) -> dict[str, Any]:
    """Normalize a per-horizon cache entry (dict or legacy string)."""
    if isinstance(entry, dict):
        return {
            "verdict": entry.get("verdict") if isinstance(entry.get("verdict"), str) else None,
            "windows": entry.get("windows") if isinstance(entry.get("windows"), (int, float)) else None,
            "coverage_p50": entry.get("coverage_p50") if isinstance(entry.get("coverage_p50"), (int, float)) else None,
            "coverage_p90": entry.get("coverage_p90") if isinstance(entry.get("coverage_p90"), (int, float)) else None,
        }
    if isinstance(entry, str):
        return {"verdict": entry, "windows": None, "coverage_p50": None, "coverage_p90": None}
    return {"verdict": None, "windows": None, "coverage_p50": None, "coverage_p90": None}


def summarize_trigger_rates(
    *,
    outcomes_path: str | Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Roll up scored outcomes per (symbol, trigger_type) across trade statuses.

    Mirrors ``stage3_gate.load_empirical_summary`` but for every trigger type,
    so the panel can show the full per-trigger table without re-implementing
    the grouping.  Returns ``{symbol: [ {trigger_type, count, target_hit_rate,
    stop_hit_rate, neither_rate}, ... ]}``.
    """
    path = Path(outcomes_path) if outcomes_path else DEFAULT_OUTCOMES_PATH
    try:
        outcomes = load_jsonl_records(path)
    except (OSError, ValueError):
        outcomes = []
    summary = summarize_outcomes(outcomes)

    per_symbol: dict[str, dict[str, dict[str, float | int]]] = {}
    for (symbol, trigger_type, _status), stats in summary.items():
        if symbol is None or trigger_type is None:
            continue
        count = int(stats.get("count") or 0)
        bucket = per_symbol.setdefault(symbol, {}).setdefault(trigger_type, {"count": 0})
        bucket["count"] = int(bucket["count"]) + count
        bucket["target_hits"] = float(bucket.get("target_hits") or 0.0) + round(
            float(stats.get("target_hit_rate") or 0.0) * count
        )
        bucket["stop_hits"] = float(bucket.get("stop_hits") or 0.0) + round(
            float(stats.get("stop_hit_rate") or 0.0) * count
        )
        bucket["neither"] = float(bucket.get("neither") or 0.0) + round(
            float(stats.get("neither_rate") or 0.0) * count
        )

    result: dict[str, list[dict[str, Any]]] = {}
    for symbol, triggers in per_symbol.items():
        rows: list[dict[str, Any]] = []
        for trigger_type, bucket in sorted(triggers.items()):
            count = int(bucket["count"])
            target = round(float(bucket["target_hits"]) / count, 4)
            stop = round(float(bucket["stop_hits"]) / count, 4)
            neither = round(float(bucket["neither"]) / count, 4)
            rows.append(
                {
                    "trigger_type": trigger_type,
                    "count": count,
                    "target_hit_rate": target,
                    "stop_hit_rate": stop,
                    "neither_rate": neither,
                    "enough_samples": count >= MIN_SAMPLES,
                    # Mirrors stage3_gate: enough samples AND below the floor
                    # means this call type is (or would be) suppressed.  Uses
                    # the same rounded value the row displays so the flag and
                    # the shown rate can never disagree at the boundary.
                    "suppressed": count >= MIN_SAMPLES and target < GATE_HIT_RATE_FLOOR,
                }
            )
        result[symbol] = rows
    return result


def get_calibration_health(engine_root: str) -> dict[str, Any]:
    """Return calibration health for R_75 and R_100.

    Structure::

        {
          "R_75": {
            "horizons": {"4h": {verdict, windows, coverage_p50, coverage_p90}, ...},
            "triggers": [{trigger_type, count, target_hit_rate, stop_hit_rate, ...}],
            "cache_fresh": bool,
          },
          ...
        }
    """
    root = Path(engine_root)
    cache = _read_last_cache_record(root / VERDICT_CACHE_REL)
    # Resolve the outcomes journal relative to the engine root so the panel
    # sees the same journal the CLI's score-live-calibration writes.
    outcomes_path = root / DEFAULT_OUTCOMES_PATH
    trigger_rates = summarize_trigger_rates(outcomes_path=outcomes_path)

    result: dict[str, Any] = {}
    for symbol in ("R_75", "R_100"):
        symbol_entry = cache.get(symbol) if isinstance(cache, dict) else None
        symbol_cache = symbol_entry if isinstance(symbol_entry, dict) else {}
        horizons = {
            label: _horizon_detail(symbol_cache.get(label))
            for label in HORIZON_LABELS
        }
        # Fresh only when both horizons carry a verdict AND validation data.
        cache_fresh = all(
            h["verdict"] is not None and h["windows"] is not None
            for h in horizons.values()
        )
        result[symbol] = {
            "horizons": horizons,
            "triggers": trigger_rates.get(symbol, []),
            "cache_fresh": cache_fresh,
        }
    return result


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(get_calibration_health(root)))
