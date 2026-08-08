"""Zero-drawdown-style band geometry for live calls and backtests.

The sniper/SMC swing builder sets targets from *structure* (external
liquidity, order blocks) — on a CSPRNG-generated price those levels are
noise, and the 3–3.5R targets they produce (9–18% moves) are far beyond the
calibrated 6h volatility band (~3–5%), so the calls can never resolve.

This module derives stop/target from the **calibrated EGARCH volatility
band** instead, with a zero-drawdown risk geometry:

- stop  = entry ∓ ``stop_sigma_mult × σ_h``   (tight invalidation — being
  wrong is cheap; the trade is dead the moment price leaves the band)
- target = entry ± ``target_sigma_mult × σ_h`` (reachable — inside the band
  the calibrated forecast says price ranges this far)

where ``σ_h = σ_per_bar × sqrt(bars)`` is the horizon log-return volatility.
With the §38 sweep-winner ratios (0.20σ_h / 0.80σ_h) the reward:risk is 4.0
and the target is inside the calibrated band, so the *geometry itself* is
honest: the level the call asks for is one the market actually reaches.

Used by BOTH the live path (``decision_engine`` sniper branch) and the
``vol-band`` backtest strategy so live geometry and measured geometry can
never diverge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BandGeometryConfig:
    """Level placement for the band-derived (zero-drawdown) geometry.

    Levels are placed in units of the horizon volatility ``σ_h`` (per-bar
    forecast sigma scaled by ``sqrt(bars)`` over the hold).  The defaults
    are the §38 sweep winner (stop 0.20σ_h / target 0.80σ_h / 1h hold →
    RR 4.0), which beat the original 0.35σ_h / 1.0σ_h / 2h defaults
    (+0.994R vs +0.654R at similar trade counts on the 9.5-day R_75
    corpus).  A wrong call costs ~0.20σ_h instead of the 6% stops the SMC
    sniper used.
    """

    hold_horizon_sec: int = 3600  # 1h default (§38 sweep winner); 1h–3h supported
    stop_sigma_mult: float = 0.20  # ZD invalidation: 0.20 × σ_h
    target_sigma_mult: float = 0.80  # reachable target: 0.80 × σ_h
    # Reject levels whose reward:risk is below this (protects against a
    # degenerate σ_h that would make the geometry a coin-flip lottery).
    min_target_rr: float = 2.0
    # Safety cap: the stop may never sit more than this fraction of price
    # away (1.5% = 0.015; mirrors the sniper's max_stop_distance_pct guard).
    max_stop_pct: float = 0.015


@dataclass(frozen=True)
class BandLevels:
    stop_loss: float
    take_profit: float
    hold_horizon_sec: int
    reward_risk: float
    horizon_sigma: float  # log-return σ over the hold horizon


def horizon_sigma(
    sigma_per_bar: float,
    bar_sec: int,
    hold_horizon_sec: int,
) -> float:
    """Scale the per-bar log-return sigma to the hold horizon (sqrt-of-bars)."""
    bars = max(1, round(hold_horizon_sec / max(1, bar_sec)))
    return sigma_per_bar * math.sqrt(bars)


def band_levels(
    entry: float,
    direction: str,
    sigma_per_bar: float,
    bar_sec: int,
    hold_horizon_sec: int | None = None,
    config: BandGeometryConfig | None = None,
) -> BandLevels | None:
    """Compute zero-drawdown stop/target from the forecast band.

    ``direction`` is ``"buy"`` or ``"sell"``.  Returns ``None`` when the
    geometry is not tradeable (missing/stale sigma, reward:risk too low, or
    the stop would breach the safety cap) — callers must stand aside rather
    than fall back to unreachable SMC levels.
    """
    cfg = config or BandGeometryConfig()
    if entry is None or entry <= 0.0 or sigma_per_bar is None or sigma_per_bar <= 0.0:
        return None
    if not math.isfinite(entry) or not math.isfinite(sigma_per_bar):
        return None
    if not isinstance(direction, str) or direction not in ("buy", "sell"):
        return None

    hold = hold_horizon_sec if hold_horizon_sec is not None else cfg.hold_horizon_sec
    if hold <= 0:
        return None
    sigma_h = horizon_sigma(sigma_per_bar, bar_sec, hold)
    if not math.isfinite(sigma_h) or sigma_h <= 0.0:
        return None

    stop_dist = cfg.stop_sigma_mult * sigma_h
    target_dist = cfg.target_sigma_mult * sigma_h
    if stop_dist <= 0.0 or target_dist <= 0.0:
        return None

    if direction == "buy":
        stop_loss = entry * (1.0 - stop_dist)
        take_profit = entry * (1.0 + target_dist)
    else:
        stop_loss = entry * (1.0 + stop_dist)
        take_profit = entry * (1.0 - target_dist)

    rr = target_dist / stop_dist
    if rr < cfg.min_target_rr:
        return None
    if abs(entry - stop_loss) / entry > cfg.max_stop_pct:
        return None
    if direction == "buy":
        if not (0.0 < stop_loss < take_profit):
            return None
    elif not (take_profit < stop_loss):
        return None

    return BandLevels(
        stop_loss=stop_loss,
        take_profit=take_profit,
        hold_horizon_sec=hold,
        reward_risk=rr,
        horizon_sigma=sigma_h,
    )
