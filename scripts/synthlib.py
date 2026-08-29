"""Shared helpers for Boom/Crash research scripts.

Extracted from boom1000_60day_analysis.py, crash1000_60day_analysis.py,
boom1000_fade_optimize.py, and boom1000_fade_perfection.py.

All functions operate on plain list-of-dicts bars (epoch/open/high/low/close).
"""
from __future__ import annotations

import statistics
from typing import Any

ATR_PERIOD = 14


# ---------------------------------------------------------------------------
# Time slicing
# ---------------------------------------------------------------------------
def slice_60d(m5, days: int = 60) -> list[dict]:
    """Return the trailing ``days`` worth of bars from an iterable of dicts."""
    if not m5:
        return []
    last_epoch = m5[-1]["epoch"]
    cutoff = last_epoch - days * 86400
    return [b for b in m5 if b["epoch"] >= cutoff]


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------
def detect_spikes(
    bars: list[dict], threshold: float = 2.5
) -> list[dict[str, Any]]:
    """Detect spikes: body >= ``threshold`` × robust rolling body EMA.

    Returns a list of dicts, one per bar:
        {idx, is_spike, body, body_ema, body_ratio}
    """
    bodies = [abs(b["close"] - b["open"]) for b in bars]
    result: list[dict[str, Any]] = []
    body_ema = 0.0
    alpha = 0.05
    for i, body in enumerate(bodies):
        if i < 20:
            body_ema = body if i == 0 else alpha * body + (1 - alpha) * body_ema
        else:
            if body <= body_ema * 2.0:
                body_ema = alpha * body + (1 - alpha) * body_ema
        is_spike = (body_ema > 0 and body >= body_ema * threshold) and i >= 20
        result.append({
            "idx": i,
            "is_spike": is_spike,
            "body": body,
            "body_ema": body_ema,
            "body_ratio": body / body_ema if body_ema > 0 else 0,
        })
    return result


def get_spike_indices(
    bars: list[dict], threshold: float = 2.5
) -> list[int]:
    """Return just the indices of spike bars (convenience wrapper)."""
    return [s["idx"] for s in detect_spikes(bars, threshold) if s["is_spike"]]


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------
def compute_atr(bars: list[dict], period: int = ATR_PERIOD) -> list[float]:
    """Wilder-smoothed ATR (no MT5 indicator dependency).

    Returns a list of length ``len(bars) - 1`` (aligned to bar[1..]).
    """
    trs: list[float] = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return [0.0] * len(trs)
    atr_vals = [0.0] * len(trs)
    atr_vals[period - 1] = statistics.mean(trs[:period])
    for i in range(period, len(trs)):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + trs[i]) / period
    return atr_vals


# ---------------------------------------------------------------------------
# Body EMA (robust, spike-excluding)
# ---------------------------------------------------------------------------
def compute_body_ema(
    bodies: list[float], idx: int, ema_len: int = 50
) -> float:
    """Robust body EMA at bar ``idx``, excluding spikes > 2× current EMA."""
    if idx < 10:
        return statistics.mean(bodies[max(0, idx - 10): idx + 1]) if idx >= 0 else 0.0
    ema = statistics.mean(bodies[max(0, idx - 19): idx + 1])
    alpha = 2.0 / (ema_len + 1)
    for i in range(max(20, idx - 49), idx + 1):
        body = bodies[i]
        if body <= ema * 2.0:
            ema = alpha * body + (1 - alpha) * ema
    return ema


# ---------------------------------------------------------------------------
# Grind detection
# ---------------------------------------------------------------------------
def detect_grinds(bars: list[dict], min_duration: int = 3) -> list[dict]:
    """Detect grind sequences (consecutive same-direction bars).

    Returns a list of dicts:
        {start, end, direction, duration, avg_body}
    """
    n = len(bars)
    grinds: list[dict] = []
    current_dir = 0
    current_len = 0
    current_start = 0
    body_sum = 0.0

    for i in range(n):
        body = bars[i]["close"] - bars[i]["open"]
        bar_dir = 1 if body > 0 else -1

        if bar_dir == current_dir:
            current_len += 1
            body_sum += abs(body)
        else:
            if current_len >= min_duration:
                grinds.append({
                    "start": current_start,
                    "end": i - 1,
                    "direction": current_dir,
                    "duration": current_len,
                    "avg_body": body_sum / current_len,
                })
            current_dir = bar_dir
            current_len = 1
            current_start = i
            body_sum = abs(body)

    if current_len >= min_duration:
        grinds.append({
            "start": current_start,
            "end": n - 1,
            "direction": current_dir,
            "duration": current_len,
            "avg_body": body_sum / current_len,
        })
    return grinds


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------
def trade_stats(trades: list[dict], label: str = "") -> dict:
    """Compute summary stats from a list of trade dicts with an 'r' key.

    Returns a dict with trades, wins, losses, total_r, pf, exp_r, wr, max_dd,
    exits.  Prints a summary line to stdout.
    """
    if not trades:
        print(f"  {label}: no trades")
        return {"trades": 0, "label": label}

    wins = [t for t in trades if t["r"] > 0]
    losses = [t for t in trades if t["r"] < 0]
    total_r = sum(t["r"] for t in trades)
    gw = sum(t["r"] for t in wins)
    gl = sum(-t["r"] for t in losses)
    pf = gw / gl if gl > 0 else 99.0
    exp_r = total_r / len(trades)
    wr = 100 * len(wins) / len(trades)

    # Max drawdown in R
    eq = [0.0]
    for t in trades:
        eq.append(eq[-1] + t["r"])
    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    # Exit reason breakdown
    reasons: dict[str, int] = {}
    for t in trades:
        r = t.get("reason", "UNKNOWN")
        reasons[r] = reasons.get(r, 0) + 1

    # Per-day rate
    if len(trades) >= 2:
        span_days = (trades[-1].get("entry_epoch", 0) - trades[0].get("entry_epoch", 0)) / 86400.0
        per_day = len(trades) / max(span_days, 1.0)
    else:
        per_day = 0.0

    result = {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "total_r": round(total_r, 2),
        "pf": round(pf, 2),
        "exp_r": round(exp_r, 3),
        "wr": round(wr, 1),
        "max_dd": round(max_dd, 2),
        "max_dd_r": round(max_dd, 2),  # alias for callers using old name
        "per_day": round(per_day, 2),
        "exits": dict(reasons),
        "label": label,
    }

    exits_str = " ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
    print(
        f"  {label}: {len(trades)} trades  "
        f"WR {wr:.1f}%  PF {pf:.2f}  ExpR {exp_r:+.3f}  "
        f"MaxDD {max_dd:.1f}R  {exits_str}"
    )
    return result
