"""Stage-3 empirical gate for live calls.

The decision engine's ``confidence`` is a *model* number — how well the
feature pipeline agrees with the learned model.  Stage 3 is the honest
overlay: before a call is shown to the operator, look up how that exact
``(symbol, trigger_type)`` has actually performed in the scored-outcomes
journal (``score-live-calibration`` → ``live_calibration_outcomes.jsonl``)
and the persisted horizon verdict (``data/forecast_verdicts.json``), then
replace the operator-facing confidence with the **market-verified target-hit
rate** instead of the raw model confidence.

Gate states:

- ``gated`` — enough scored samples (``MIN_STAGE3_SAMPLES``), the empirical
  target-hit rate clears ``GATE_HIT_RATE_FLOOR``, and the horizon verdict is
  ``calibrated``.  The call is displayed with the empirical rate.
- ``annotated`` — evidence is *positive* (rate clears the floor) but the
  horizon verdict is not yet calibrated.  The call is still emitted, but the
  operator sees the honest empirical rate and a note explaining what is
  missing.
- ``suppressed`` — enough scored samples and the empirical target-hit rate is
  BELOW ``GATE_HIT_RATE_FLOOR``.  This call type has been market-tested and
  failed the floor, so the call is downgraded to ``stand_aside`` instead of
  being surfaced as a candidate.  The original call intent is preserved in
  ``suppressed_call`` so the journal still records what the engine wanted.
- ``insufficient_data`` — fewer than ``MIN_STAGE3_SAMPLES`` scored outcomes
  for this (symbol, trigger_type).  The raw model confidence is kept
  (nothing better exists) and the annotation says so plainly.

Suppression mode (``SYNTH_GATE_SUPPRESSION_MODE``, default ``suppress``):

- ``suppress`` (default) — a below-floor call type is held back entirely: the
  call is downgraded to ``stand_aside`` and never surfaced as a candidate.
- ``annotate`` — the same below-floor evidence is *annotated* instead of
  acted on: the call still emits (with the honest, low empirical rate and a
  note saying it is below the floor), so the operator can watch the failing
  call type without the system silently holding it back.  ``evidence_status``
  is ``suppressed`` in both modes — the mode only changes what is done with
  the call, never what the data says.

Proven-only execution mode (``SYNTH_GATE_PROVEN_ONLY``, default off):

When on, **only** call candidates whose ``evidence_status`` is ``proven``
(above the floor AND enough scored samples) may trigger orders.  Anything
still learning, without data, or below the floor is forced to paper-only
sizing (multiplier 0.0) and stamped ``execution_allowed: false`` — the
call may still be *shown* (so the operator can watch what the engine wants
and paper-trade it to build outcomes) but it can never place a live order,
regardless of suppression mode.  ``annotate`` mode shows more, it does not
unlock execution: in proven-only mode the annotate escape hatch is closed.
This is the strictest belt: the operator is saying "prove it in the market
before I risk real money on it".

Every block carries an ``evidence_status`` so the dashboard can distinguish
"proven" (enough samples, clears the floor), "still_learning" (samples
accumulating), "suppressed" (below the floor), and "no_data" (nothing yet)
without re-deriving the rules.

Everything is best-effort: any failure (missing journal, corrupt JSONL,
unreadable cache) degrades to ``insufficient_data`` rather than crashing the
snapshot.  The gate never fabricates evidence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from synthetic_trader.live.calibration_scorer import (
    load_jsonl_records,
    summarize_outcomes,
)

# ── Gate thresholds (env-configurable) ──────────────────────────────
# Minimum number of scored outcomes before the empirical rate is trusted.
# Override with SYNTH_GATE_MIN_SAMPLES.
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


MIN_STAGE3_SAMPLES = _env_int("SYNTH_GATE_MIN_SAMPLES", 10)
# Empirical target-hit rate that must clear for the gate to pass.  This is the
# FALLBACK floor used when no setup geometry is known (see break_even_floor):
# the default gate floor is the per-trigger-type BREAK-EVEN rate, not a flat
# number.  Override with SYNTH_GATE_HIT_RATE_FLOOR to force a flat bar.
GATE_HIT_RATE_FLOOR = _env_float("SYNTH_GATE_HIT_RATE_FLOOR", 0.5)

# ── Break-even floor ────────────────────────────────────────────────
# The default gate floor is the per-trigger-type BREAK-EVEN target-hit rate:
# floor = 1/(1 + avg reward:risk) + margin.  A 3R setup breaks even at 25%,
# so the old flat 50% was mathematically unreachable for it and turned the
# gate into an all-or-nothing switch (the R_75 backtest verdict).  The floor
# is now reachable by construction: any trigger that beats its own break-even
# by the margin clears the gate.  Override the margin with
# SYNTH_GATE_BREAK_EVEN_MARGIN; clamp bounds with SYNTH_GATE_FLOOR_MIN/MAX.
BREAK_EVEN_MARGIN = _env_float("SYNTH_GATE_BREAK_EVEN_MARGIN", 0.05)
BREAK_EVEN_FLOOR_MIN = _env_float("SYNTH_GATE_FLOOR_MIN", 0.10)
BREAK_EVEN_FLOOR_MAX = _env_float("SYNTH_GATE_FLOOR_MAX", 0.60)

# Empirical-confidence position sizing.  The gate turns its evidence into a
# position-size multiplier (risk scales with empirical confidence):
#   gated (calibrated horizon + above-floor rate)  -> full  (1.0)
#   annotated (above-floor rate, horizon pending)  -> half  (0.5, configurable)
#   everything else (no verdict yet, or below floor) -> paper-only (0.0)
# The half fraction is env-configurable (SYNTH_GATE_SIZE_HALF); full and
# paper-only are fixed at 1.0 / 0.0 by definition.
STAGE3_SIZE_HALF = _env_float("SYNTH_GATE_SIZE_HALF", 0.5)

SIZING_LEVELS = ("full", "half", "paper_only", "stand_aside")

# Suppression behaviour: "suppress" downgrades a below-floor call type to
# stand_aside (never surfaced as a candidate); "annotate" keeps emitting it
# with the honest below-floor rate and a note.  Override with
# SYNTH_GATE_SUPPRESSION_MODE.
def _env_mode() -> str:
    mode = os.environ.get("SYNTH_GATE_SUPPRESSION_MODE", "suppress").strip().lower()
    return mode if mode in ("suppress", "annotate") else "suppress"


SUPPRESSION_MODE = _env_mode()

# Proven-only execution: when on, only evidence_status == "proven" calls may
# trigger orders; everything else is forced paper-only (0.0) regardless of
# suppression mode.  Override with SYNTH_GATE_PROVEN_ONLY (1/true/yes/on).
PROVEN_ONLY_MODE = _env_bool("SYNTH_GATE_PROVEN_ONLY", False)

# Default journal paths (cwd-relative — matches the CLI defaults, and the
# Python snapshot subprocess runs with cwd = engine root).
DEFAULT_OUTCOMES_PATH = Path("journals/live_calibration_outcomes.jsonl")
DEFAULT_VERDICT_CACHE_PATH = Path("data/forecast_verdicts.json")

# Horizon labels surfaced in the verdict cache (must match
# horizon_forecast_stats.HORIZON_HOURS formatting).
HORIZON_LABELS = ("4h", "6h")

# Forecast-detail keys the gate surfaces on a call (mirrors
# horizon_forecast_stats._FORECAST_CACHE_KEYS — kept here so the reader
# whitelists even if a future writer adds extra keys).
FORECAST_DETAIL_KEYS = (
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


def break_even_floor(reward_risk: float | None, margin: float | None = None) -> float:
    """Empirical floor for a setup geometry: break-even target-hit rate + margin.

    Break-even hit rate for a reward:risk of ``rr`` is ``1/(1+rr)`` — the
    rate at which wins and losses cancel.  A 3R setup breaks even at 25%, so
    a flat 50% floor is unreachable for it and turns the gate into an
    all-or-nothing switch.  This floor is reachable by construction.

    Falls back to ``GATE_HIT_RATE_FLOOR`` (the conservative flat default)
    when the reward:risk is unknown, and clamps to ``[BREAK_EVEN_FLOOR_MIN,
    BREAK_EVEN_FLOOR_MAX]`` so degenerate geometry can never produce a
    meaningless floor.
    """
    if reward_risk is None or reward_risk <= 0.0:
        return GATE_HIT_RATE_FLOOR
    margin = BREAK_EVEN_MARGIN if margin is None else margin
    raw = 1.0 / (1.0 + reward_risk) + margin
    return max(BREAK_EVEN_FLOOR_MIN, min(raw, BREAK_EVEN_FLOOR_MAX))


def average_reward_risk(
    *,
    symbol: str,
    trigger_type: str,
    outcomes_path: str | Path | None = None,
) -> float | None:
    """Mean reward:risk of scored outcomes for ``(symbol, trigger_type)``.

    Uses the same level filter as ``summarize_outcomes`` (level-less and
    Deriv-fallback rows are not evidence) and the same RR math as
    ``reward_risk_from_record`` in the gate backtest, so the live gate and the
    backtest can never disagree about what a trigger's geometry is worth.
    Returns ``None`` when there is no level-bearing evidence for this trigger.
    """
    path = Path(outcomes_path) if outcomes_path else DEFAULT_OUTCOMES_PATH
    try:
        records = load_jsonl_records(path)
    except (OSError, ValueError):
        return None
    rrs: list[float] = []
    for rec in records:
        if str(rec.get("symbol")) != symbol:
            continue
        if str(rec.get("trigger_type")) != trigger_type:
            continue
        if rec.get("scoring_source") == "deriv_fallback":
            continue
        entry = rec.get("entry")
        stop = rec.get("execution_stop")
        target = rec.get("primary_target")
        if entry is None or stop is None or target is None:
            continue
        try:
            e, s, t = float(entry), float(stop), float(target)
        except (TypeError, ValueError):
            continue
        risk = abs(e - s)
        if risk <= 0.0:
            continue
        rrs.append(abs(t - e) / risk)
    if not rrs:
        return None
    return sum(rrs) / len(rrs)


def load_empirical_summary(
    *,
    symbol: str,
    trigger_type: str,
    outcomes_path: str | Path | None = None,
) -> dict[str, Any]:
    """Roll up scored outcomes for (symbol, trigger_type) across trade statuses.

    Uses the same ``summarize_outcomes`` grouping as the CLI so the gate can
    never disagree with ``synth-trader score-live-calibration`` output.
    Returns ``{count, target_hit_rate, stop_hit_rate, neither_rate}`` — all
    zero/None when there is no evidence for this trigger type.
    """
    path = Path(outcomes_path) if outcomes_path else DEFAULT_OUTCOMES_PATH
    try:
        outcomes = load_jsonl_records(path)
    except (OSError, ValueError):
        outcomes = []
    summary = summarize_outcomes(outcomes)

    total_count = 0
    target_hits = 0
    stop_hits = 0
    neither = 0
    # Aggregate across every trade_status for this (symbol, trigger_type):
    # scored outcomes are recorded per status, and the operator-facing rate is
    # "of all calls the engine emitted for this trigger, how often the target
    # was reached".  Aggregating all statuses is deliberate — filtering to
    # only the "valid" bucket would silently drop the calls that were scored
    # but never became actionable, flattering the empirical rate.
    for (sym, trig, _status), stats in summary.items():
        if sym != symbol or trig != trigger_type:
            continue
        count = int(stats.get("count") or 0)
        total_count += count
        target_hits += round(float(stats.get("target_hit_rate") or 0.0) * count)
        stop_hits += round(float(stats.get("stop_hit_rate") or 0.0) * count)
        neither += round(float(stats.get("neither_rate") or 0.0) * count)

    if total_count == 0:
        return {
            "count": 0,
            "target_hit_rate": None,
            "stop_hit_rate": None,
            "neither_rate": None,
        }
    return {
        "count": total_count,
        "target_hit_rate": target_hits / total_count,
        "stop_hit_rate": stop_hits / total_count,
        "neither_rate": neither / total_count,
    }


def _unwrap_verdict(entry: Any) -> str | None:
    """Accept either the old flat string cache entry or the richer dict form."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        verdict = entry.get("verdict")
        return verdict if isinstance(verdict, str) else None
    return None


def _horizon_forecast_block(entry: Any) -> dict[str, Any]:
    """Compact forecast block for one horizon from the verdict cache.

    Carries the horizon verdict, whether the multipliers were tuned
    (``multipliers_applied``), the tuned 60s p50/p90 range multipliers, and
    the live band numbers so a call can be annotated with the actual
    calibrated forecast (not just the verdict label).  Empty dict when the
    cache has no forecast detail for this horizon.
    """
    if not isinstance(entry, dict):
        return {}
    block: dict[str, Any] = {}
    verdict = _unwrap_verdict(entry)
    if verdict is not None:
        block["verdict"] = verdict
    if isinstance(entry.get("multipliers_applied"), bool):
        block["multipliers_applied"] = entry["multipliers_applied"]
    for key in ("p50_mult", "p90_mult"):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            block[key] = float(value)
    forecast = entry.get("forecast")
    if isinstance(forecast, dict):
        # Whitelist the exact keys the stats writer persists, so a cache that
        # grows extra keys can never leak them onto the call payload.  Reads
        # each value fresh from ``forecast`` — never reuse an outer loop
        # variable (a shadowed ``value`` here would smear one scalar across
        # every band field).
        block["forecast"] = {
            key: forecast[key]
            for key in FORECAST_DETAIL_KEYS
            if key in forecast and isinstance(forecast[key], (int, float, str))
        }
    return block


def load_horizon_verdict(
    *,
    symbol: str,
    verdict_cache_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read the persisted horizon verdict cache for a symbol.

    The cache is written by ``horizon_forecast_stats.get_horizon_forecast_stats``
    (the same computation behind the /api/system/forecast-horizon route) so
    this lookup is a cheap file read, never a full walk-forward replay.
    Returns ``{verdict, verdict_4h, verdict_6h, windows, coverage_p50,
    coverage_p90, horizons, p50_mult, p90_mult}`` with ``None`` values when the
    cache is absent or the symbol is missing.  ``horizons`` carries the
    per-horizon forecast blocks (verdict + tuned multipliers + live bands)
    and ``p50_mult``/``p90_mult`` are the overall tuned multipliers (4h
    preferred, 6h fallback) — the direct answer to "which calibrated 60s
    range multipliers are in force right now".
    """
    _no_data = {
        "verdict": None,
        "verdict_4h": None,
        "verdict_6h": None,
        "windows": None,
        "coverage_p50": None,
        "coverage_p90": None,
        "horizons": {"4h": {}, "6h": {}},
        "p50_mult": None,
        "p90_mult": None,
    }
    path = Path(verdict_cache_path) if verdict_cache_path else DEFAULT_VERDICT_CACHE_PATH
    try:
        data = load_jsonl_records(path)
        cache = data[-1] if data else {}
        symbol_entry = cache.get(symbol) if isinstance(cache, dict) else None
    except (OSError, ValueError, IndexError):
        return _no_data

    if not isinstance(symbol_entry, dict):
        return _no_data

    verdict_4h = _unwrap_verdict(symbol_entry.get("4h"))
    verdict_6h = _unwrap_verdict(symbol_entry.get("6h"))
    verdicts = [v for v in (verdict_4h, verdict_6h) if v is not None]
    # A symbol is "calibrated" only if BOTH horizons are (the honest bar).
    overall = (
        "calibrated"
        if len(verdicts) == len(HORIZON_LABELS) and all(v == "calibrated" for v in verdicts)
        else (verdicts[0] if verdicts else None)
    )

    # Windows/coverage come from the richer dict entry (fall back to None).
    def _num(entry: Any, key: str) -> float | int | None:
        if isinstance(entry, dict):
            value = entry.get(key)
            if isinstance(value, (int, float)):
                return value
        return None

    horizons = {
        "4h": _horizon_forecast_block(symbol_entry.get("4h")),
        "6h": _horizon_forecast_block(symbol_entry.get("6h")),
    }
    # Overall tuned multipliers (4h preferred, 6h fallback).
    p50_mult = horizons["4h"].get("p50_mult")
    if p50_mult is None:
        p50_mult = horizons["6h"].get("p50_mult")
    p90_mult = horizons["4h"].get("p90_mult")
    if p90_mult is None:
        p90_mult = horizons["6h"].get("p90_mult")

    return {
        "verdict": overall,
        "verdict_4h": verdict_4h,
        "verdict_6h": verdict_6h,
        "windows": _num(symbol_entry.get("4h"), "windows"),
        "coverage_p50": _num(symbol_entry.get("4h"), "coverage_p50"),
        "coverage_p90": _num(symbol_entry.get("4h"), "coverage_p90"),
        "horizons": horizons,
        "p50_mult": p50_mult,
        "p90_mult": p90_mult,
    }


def sizing_ladder(
    *,
    state: str,
    evidence_status: str,
    hit_rate: float | None,
    hit_rate_floor: float,
    half_multiplier: float | None = None,
    proven_only: bool = False,
) -> dict[str, Any]:
    """Turn the gate decision into an empirical position-size recommendation.

    Risk scales with empirical confidence:

    - ``gated`` — calibrated horizon AND above-floor market-verified hit rate
      -> **full** size (multiplier 1.0).  This is the only call type with
      both bars met, so it is the only one that gets full risk budget.
    - ``annotated`` with positive evidence (rate clears the floor but the
      horizon verdict is not calibrated yet) -> **half** size (multiplier
      ``half_multiplier`` or ``STAGE3_SIZE_HALF``).  The setup is proven in
      the market but the vol bands are not yet verified — a fraction, not
      full.
    - ``annotated`` below the floor (annotate suppression mode) ->
      **paper_only** (0.0).  Never size real money on evidence below the
      floor, even in annotate mode.
    - ``insufficient_data`` (still_learning / no_data) -> **paper_only**
      (0.0).  No empirical verdict yet — the call emits so the operator can
      watch it, but no live position.
    - ``suppressed`` -> **stand_aside** (0.0).  Held back entirely.

    ``proven_only`` (SYNTH_GATE_PROVEN_ONLY) is the strictest belt: when on,
    ANY evidence_status other than ``proven`` is forced to **paper_only**
    (0.0) before the ladder runs, so still_learning / no_data / suppressed
    calls can never size a live position — even in annotate mode.  The call
    stays visible (the operator can watch it and paper-trade it to build
    outcomes) but the execution path is closed.

    Returns ``{level, multiplier, basis, reason}``.
    """
    half = (
        float(half_multiplier)
        if half_multiplier is not None and float(half_multiplier) > 0.0
        else STAGE3_SIZE_HALF
    )
    rate_display = f"{hit_rate:.0%}" if hit_rate is not None else "n/a"

    if proven_only and evidence_status != "proven":
        return {
            "level": "paper_only",
            "multiplier": 0.0,
            "basis": "proven_only",
            "reason": (
                f"proven-only mode: evidence is '{evidence_status}' "
                f"({rate_display} hit rate) — not market-proven, paper only "
                "until the scored outcomes clear the floor"
            ),
        }
    if state == "suppressed":
        return {
            "level": "stand_aside",
            "multiplier": 0.0,
            "basis": "suppressed",
            "reason": f"below the {hit_rate_floor:.0%} verified floor ({rate_display}) — held back",
        }
    if state == "gated":
        return {
            "level": "full",
            "multiplier": 1.0,
            "basis": "gated",
            "reason": f"calibrated horizon + {rate_display} hit rate clears the floor",
        }
    if state == "annotated":
        if evidence_status == "suppressed":
            return {
                "level": "paper_only",
                "multiplier": 0.0,
                "basis": "below_floor",
                "reason": f"below the {hit_rate_floor:.0%} verified floor ({rate_display}) — paper only even in annotate mode",
            }
        return {
            "level": "half",
            "multiplier": half,
            "basis": "annotated",
            "reason": f"{rate_display} hit rate clears the floor but the horizon verdict is not calibrated — half size",
        }
    # insufficient_data
    if evidence_status == "no_data":
        return {
            "level": "paper_only",
            "multiplier": 0.0,
            "basis": "no_data",
            "reason": "no scored outcomes yet — paper only until an empirical verdict exists",
        }
    return {
        "level": "paper_only",
        "multiplier": 0.0,
        "basis": "still_learning",
        "reason": f"{rate_display} hit rate on fewer than the minimum samples — paper only until verified",
    }


def resolve_trigger_type(snapshot: dict[str, Any]) -> str:
    """Mirror ``build_call_record``: trigger type = execution trigger or alert type."""
    return str(
        snapshot.get("execution_trigger_type")
        or snapshot.get("alert_type")
        or snapshot.get("trigger_type")
        or "unknown"
    )


def gate_decision(
    *,
    count: int,
    hit_rate: float | None,
    verdict_label: str | None,
    min_samples: int,
    hit_rate_floor: float,
    suppression_mode: str,
) -> tuple[str, str]:
    """Pure gate state machine shared by the live gate and the gate backtest.

    Returns ``(state, evidence_status)`` using the exact same rules
    ``build_stage3_block`` applies:

    - ``evidence_status`` is how far verification has gotten: ``no_data``,
      ``still_learning``, ``suppressed`` (enough samples AND below floor),
      or ``proven``.
    - ``state`` is the operator-facing decision: ``suppressed`` (below floor,
      suppress mode), ``annotated`` (below floor in annotate mode, or above
      floor with uncalibrated horizon), ``gated`` (above floor + calibrated
      horizon), or ``insufficient_data`` (fewer than ``min_samples``).

    Keeping this pure lets the backtest replay the corpus through the exact
    production rules instead of a copy that can drift.
    """
    if count == 0:
        evidence_status = "no_data"
    elif count < min_samples:
        evidence_status = "still_learning"
    elif hit_rate is not None and hit_rate < hit_rate_floor:
        evidence_status = "suppressed"
    else:
        evidence_status = "proven"

    if count >= min_samples:
        if hit_rate is not None and hit_rate < hit_rate_floor:
            # Market-tested and BELOW the floor.  evidence_status stays
            # "suppressed" in both modes — the mode only decides the action.
            state = "annotated" if suppression_mode == "annotate" else "suppressed"
        elif hit_rate is not None and hit_rate >= hit_rate_floor and verdict_label == "calibrated":
            state = "gated"
        else:
            state = "annotated"
    else:
        state = "insufficient_data"
    return state, evidence_status


def build_stage3_block(
    snapshot: dict[str, Any],
    *,
    outcomes_path: str | Path | None = None,
    verdict_cache_path: str | Path | None = None,
    min_samples: int | None = None,
    hit_rate_floor: float | None = None,
    suppression_mode: str | None = None,
    proven_only: bool | None = None,
) -> dict[str, Any]:
    """Compute the Stage-3 annotation block for a call snapshot.

    ``min_samples`` / ``hit_rate_floor`` / ``suppression_mode`` / ``proven_only``
    override the (env-configurable) module thresholds for this call; when
    omitted the module defaults apply.
    """
    symbol = str(snapshot.get("symbol") or "")
    trigger_type = resolve_trigger_type(snapshot)
    model_confidence = snapshot.get("confidence")
    min_samples = min_samples if min_samples is not None else MIN_STAGE3_SAMPLES
    # The caller's explicit floor (if any) always wins; when omitted the floor
    # is the per-trigger-type BREAK-EVEN rate computed below.
    explicit_floor = hit_rate_floor
    mode = (
        suppression_mode
        if suppression_mode in ("suppress", "annotate")
        else SUPPRESSION_MODE
    )
    proven = proven_only if proven_only is not None else PROVEN_ONLY_MODE

    if not symbol:
        # No geometry can be known without a symbol — fall back to the explicit
        # override or the conservative flat floor.  The basis is labelled
        # honestly: without a symbol there is no geometry to derive a
        # break-even from, so "break_even" would be a lie.
        resolved_floor = explicit_floor if explicit_floor is not None else GATE_HIT_RATE_FLOOR
        return {
            "state": "insufficient_data",
            "evidence_status": "no_data",
            "trigger_type": trigger_type,
            "empirical_target_hit_rate": None,
            "empirical_sample_count": 0,
            "empirical_stop_hit_rate": None,
            "horizon_verdict": None,
            "horizon_verdict_4h": None,
            "horizon_verdict_6h": None,
            "p50_mult": None,
            "p90_mult": None,
            "horizon_forecast": {"4h": {}, "6h": {}},
            "model_confidence": model_confidence,
            "display_confidence": model_confidence,
            "min_samples": min_samples,
            "hit_rate_floor": resolved_floor,
            "floor_basis": "configured" if explicit_floor is not None else "fallback",
            "break_even_rr": None,
            "suppression_mode": mode,
            "proven_only": proven,
            "execution_allowed": False,
            "below_floor": False,
            "sizing": sizing_ladder(
                state="insufficient_data",
                evidence_status="no_data",
                hit_rate=None,
                hit_rate_floor=resolved_floor,
                proven_only=proven,
            ),
            "suppressed_call": None,
            "note": "no symbol — cannot look up empirical evidence",
        }

    empirical = load_empirical_summary(
        symbol=symbol,
        trigger_type=trigger_type,
        outcomes_path=outcomes_path,
    )
    verdict = load_horizon_verdict(
        symbol=symbol,
        verdict_cache_path=verdict_cache_path,
    )

    # ── Floor resolution: per-trigger-type break-even by default ──
    # The floor is 1/(1+avg reward:risk) + margin, computed from the scored
    # outcomes' real geometry for this (symbol, trigger_type).  When no
    # outcomes exist yet, fall back to the CURRENT call's own reward:risk
    # (its levels are known even before it is scored); when that is unknown
    # too, fall back to the conservative flat GATE_HIT_RATE_FLOOR.
    if explicit_floor is not None:
        hit_rate_floor = explicit_floor
        floor_basis = "configured"
        break_even_rr = None
    else:
        avg_rr = average_reward_risk(
            symbol=symbol,
            trigger_type=trigger_type,
            outcomes_path=outcomes_path,
        )
        if avg_rr is None:
            rr = snapshot.get("reward_risk")
            if isinstance(rr, (int, float)) and rr > 0:
                avg_rr = float(rr)
        if avg_rr is not None:
            hit_rate_floor = break_even_floor(avg_rr)
            floor_basis = "break_even"
        else:
            # No geometry known at all (no scored outcomes with levels AND no
            # reward:risk on the call) -> conservative flat fallback, labelled
            # honestly so the dashboard never claims it is break-even-derived.
            hit_rate_floor = GATE_HIT_RATE_FLOOR
            floor_basis = "fallback"
        break_even_rr = avg_rr

    count = empirical["count"]
    hit_rate = empirical["target_hit_rate"]
    verdict_label = verdict["verdict"]

    # ── Gate decision ─────────────────────────────────────────────
    # Pure shared decision (also used by the gate backtest so the replay
    # measures the exact production rules).
    state, evidence_status = gate_decision(
        count=count,
        hit_rate=hit_rate,
        verdict_label=verdict_label,
        min_samples=min_samples,
        hit_rate_floor=hit_rate_floor,
        suppression_mode=mode,
    )

    rate_display = f"{hit_rate:.0%}" if hit_rate is not None else "n/a"
    if state == "suppressed":
        note = (
            f"{count} scored outcomes; target-hit rate {rate_display} is BELOW "
            f"the {hit_rate_floor:.0%} floor — {trigger_type} calls are "
            "suppressed until the market-verified rate improves."
        )
    elif state == "annotated" and evidence_status == "suppressed":
        # Annotate-only mode: the failing call type is still shown with its
        # honest rate so the operator can watch it, but the note says plainly
        # that it is below the floor.
        note = (
            f"{count} scored outcomes; target-hit rate {rate_display} is BELOW "
            f"the {hit_rate_floor:.0%} floor — suppression mode is 'annotate', "
            f"so {trigger_type} calls are still shown with this honest rate. "
            "Set SYNTH_GATE_SUPPRESSION_MODE=suppress to hold them back."
        )
    elif state == "gated":
        note = (
            f"{count} scored outcomes; target-hit rate {rate_display} clears "
            f"{hit_rate_floor:.0%} and the horizon verdict is calibrated."
        )
    elif state == "annotated":
        # count >= min_samples and the rate clears the floor; only the
        # horizon verdict is missing (or the rate is None, which can't
        # happen with count >= min_samples — defensive).
        missing = []
        if verdict_label != "calibrated":
            missing.append("horizon verdict not calibrated")
        note = (
            f"{count} scored outcomes; target-hit rate "
            f"{rate_display} clears the floor ({', '.join(missing)})."
        )
    else:
        remaining = max(0, min_samples - count)
        note = (
            f"only {count}/{min_samples} scored outcome(s) for "
            f"{symbol}/{trigger_type} — the raw model confidence is shown; "
            f"{remaining} more outcome(s) needed for an empirical verdict."
        )

    # ── Display confidence: market-verified rate over model confidence ──
    # Only trust the empirical rate once enough samples exist; below that the
    # honest display is the raw model confidence (nothing better is known).
    # A suppressed call keeps its (low) empirical rate — that IS the reason
    # it is suppressed, so the operator sees exactly why.
    display_confidence = (
        hit_rate
        if (count >= min_samples and hit_rate is not None)
        else model_confidence
    )

    # Preserve the pre-suppression call intent so the calls journal still
    # records what the engine wanted even when the operator is told to stand
    # aside (see apply_stage3_gate).
    suppressed_call = (
        str(snapshot.get("call")) if state == "suppressed" else None
    )

    # Machine-readable execution gate: proven-only mode closes live execution
    # for anything that isn't market-proven yet (still_learning / no_data /
    # suppressed), even in annotate mode.  The sizing ladder above already
    # forces paper_only for those; this flag is the explicit contract for
    # downstream consumers (dashboard submit path, CLI renderers).
    execution_allowed = not proven or evidence_status == "proven"

    return {
        "state": state,
        "evidence_status": evidence_status,
        "trigger_type": trigger_type,
        "empirical_target_hit_rate": hit_rate,
        "empirical_sample_count": count,
        "empirical_stop_hit_rate": empirical["stop_hit_rate"],
        "horizon_verdict": verdict_label,
        "horizon_verdict_4h": verdict["verdict_4h"],
        "horizon_verdict_6h": verdict["verdict_6h"],
        # The tuned 60s p50/p90 range multipliers and the live forecast bands
        # (from tune-bands → verdict cache) so the operator-facing call shows
        # the actual calibrated bands, not just the verdict label.
        "p50_mult": verdict["p50_mult"],
        "p90_mult": verdict["p90_mult"],
        "horizon_forecast": verdict["horizons"],
        "model_confidence": model_confidence,
        "display_confidence": display_confidence,
        "min_samples": min_samples,
        "hit_rate_floor": hit_rate_floor,
        # Floor transparency: how the floor was derived and (for break-even
        # floors) the reward:risk it came from, so the dashboard can show
        # "floor 30% (break-even @ 3R)" instead of an opaque number.
        "floor_basis": floor_basis,
        "break_even_rr": break_even_rr,
        "suppression_mode": mode,
        # Proven-only execution mode + the resulting go/no-go for live orders.
        "proven_only": proven,
        "execution_allowed": execution_allowed,
        # Machine-readable marker: True whenever the empirical evidence is below
        # the floor (both modes), so downstream execution consumers can tell a
        # below-floor call from a genuine one without parsing the note.
        "below_floor": evidence_status == "suppressed",
        # Empirical position sizing — risk scales with empirical confidence.
        "sizing": sizing_ladder(
            state=state,
            evidence_status=evidence_status,
            hit_rate=hit_rate,
            hit_rate_floor=hit_rate_floor,
            proven_only=proven,
        ),
        "suppressed_call": suppressed_call,
        "note": note,
    }


def apply_stage3_gate(
    snapshot: dict[str, Any],
    *,
    outcomes_path: str | Path | None = None,
    verdict_cache_path: str | Path | None = None,
    min_samples: int | None = None,
    hit_rate_floor: float | None = None,
    suppression_mode: str | None = None,
    proven_only: bool | None = None,
) -> dict[str, Any]:
    """Annotate (and optionally suppress) a call snapshot with the Stage-3 gate.

    Replaces ``snapshot["confidence"]`` with the market-verified target-hit
    rate when evidence exists, and attaches the full ``stage3`` block so the
    bridge can surface it in the operator payload.  When the call type is
    ``suppressed`` (enough samples, rate below the floor, and suppression
    mode is ``suppress``) the call is downgraded to ``stand_aside`` so a
    failing call type is never surfaced as a candidate — the original intent
    stays in ``stage3.suppressed_call``.  In ``annotate`` mode the same
    evidence is shown honestly without holding the call back.

    ``proven_only`` (SYNTH_GATE_PROVEN_ONLY) closes live execution for any
    call whose evidence isn't ``proven``: the sizing is forced to paper_only
    (multiplier 0.0) and ``stage3.execution_allowed`` is False, so no
    downstream consumer can place a live order — even in annotate mode.  The
    call is still surfaced (watch it, paper-trade it) but never risked.
    Best-effort: never raises.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    original_call = snapshot.get("call")
    try:
        block = build_stage3_block(
            snapshot,
            outcomes_path=outcomes_path,
            verdict_cache_path=verdict_cache_path,
            min_samples=min_samples,
            hit_rate_floor=hit_rate_floor,
            suppression_mode=suppression_mode,
            proven_only=proven_only,
        )
    except Exception:
        proven = proven_only if proven_only is not None else PROVEN_ONLY_MODE
        block = {
            "state": "insufficient_data",
            "evidence_status": "no_data",
            "trigger_type": resolve_trigger_type(snapshot),
            "empirical_target_hit_rate": None,
            "empirical_sample_count": 0,
            "empirical_stop_hit_rate": None,
            "horizon_verdict": None,
            "horizon_verdict_4h": None,
            "horizon_verdict_6h": None,
            "p50_mult": None,
            "p90_mult": None,
            "horizon_forecast": {"4h": {}, "6h": {}},
            "model_confidence": snapshot.get("confidence"),
            "display_confidence": snapshot.get("confidence"),
            "min_samples": min_samples if min_samples is not None else MIN_STAGE3_SAMPLES,
            "hit_rate_floor": hit_rate_floor if hit_rate_floor is not None else GATE_HIT_RATE_FLOOR,
            "suppression_mode": (
                suppression_mode
                if suppression_mode in ("suppress", "annotate")
                else SUPPRESSION_MODE
            ),
            "proven_only": proven,
            "execution_allowed": False,
            "below_floor": False,
            "sizing": sizing_ladder(
                state="insufficient_data",
                evidence_status="no_data",
                hit_rate=None,
                hit_rate_floor=(
                    hit_rate_floor if hit_rate_floor is not None else GATE_HIT_RATE_FLOOR
                ),
                proven_only=proven,
            ),
            "suppressed_call": None,
            "note": "stage-3 lookup failed; raw model confidence shown",
        }
    snapshot["stage3"] = block
    if block["display_confidence"] is not None:
        snapshot["confidence"] = block["display_confidence"]
    # Also stamp the trigger type for the calls journal (mirrors
    # build_call_record, but guarantees the scored record keys match).
    if block["trigger_type"] != "unknown":
        snapshot.setdefault("execution_trigger_type", block["trigger_type"])
    # ── Suppression: a market-failing call type is not surfaced as a call ──
    if block["state"] == "suppressed" and original_call in ("buy_candidate", "sell_candidate"):
        snapshot["call"] = "stand_aside"
        snapshot.setdefault("suppressed_reason", block["note"])
    else:
        # If a snapshot is reused (e.g. re-gated after the journal improves),
        # never leave a stale suppression reason behind on a live call.
        snapshot.pop("suppressed_reason", None)

    # ── Empirical position sizing: risk scales with empirical confidence ──
    # The sizing multiplier rides on the alert so any downstream consumer
    # (RiskEngine stake scaling, MT5 volume, dashboard badge) can apply it
    # without re-deriving the evidence.  position_sizing (the guardian/regime
    # label) is left untouched — the empirical size is a separate axis.
    sizing = block.get("sizing") or {}
    snapshot["size_multiplier"] = float(sizing.get("multiplier", 1.0))
    snapshot["position_sizing_empirical"] = sizing.get("level", "full")
    # Proven-only execution contract: explicit go/no-go for live orders.
    snapshot["execution_allowed"] = bool(block.get("execution_allowed", True))
    return snapshot
