"""Volatility harvesting strategy for synthetic indices.

On synthetic indices, the generator's GARCH-like variance scheduling
produces a reliable mean-reversion pattern: after extreme moves (z-score > 2.5),
volatility contracts and price tends to retrace toward the mean.

This module implements a dedicated trade mode that:
1. Monitors GARCH z-scores for extreme conditions
2. Generates mean-reversion entries when conditions are met
3. Uses tighter stops/targets appropriate for reversion trades
4. Integrates with the existing decision engine architecture

Key insight: While individual price ticks are random, the VARIANCE is
predictable. When the generator produces an extreme move, its variance
scheduling algorithm will pull volatility back — and price follows.

Entry conditions:
- garch_z_score > 2.5 (extreme move in one direction)
- garch_mean_revert_signal > 0.6 (high probability of reversion)
- garch_vol_regime == 2.0 (currently in high-vol regime)
- ATR z-score > 1.5 (confirms elevated volatility)

Exit conditions:
- Take profit at 1.5x the entry distance from current price
- Stop loss at 2.5x the entry distance (wider stop for reversion)
- Time-based exit after 4 bars (1 hour on 15M timeframe)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from synthetic_trader.domain import Direction, TradeSignal


@dataclass(frozen=True)
class VolatilityHarvestSignal:
    """A volatility harvesting trade signal."""
    
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    z_score: float
    mean_revert_signal: float
    hold_minutes: int
    rationale: tuple[str, ...]


class VolatilityHarvester:
    """Detects and generates volatility harvesting trade signals.
    
    This strategy exploits the ONE genuinely exploitable property of
    synthetic indices: after extreme moves, the generator's variance
    scheduling algorithm pulls volatility back, and price tends to retrace.
    
    Parameters
    ----------
    z_threshold : float
        Minimum |z-score| to trigger entry (default 2.5).
    mr_signal_threshold : float
        Minimum mean-revert signal probability (default 0.6).
    min_atr_z : float
        Minimum ATR z-score to confirm elevated volatility (default 1.5).
    take_profit_multiple : float
        Take profit as multiple of entry distance (default 1.5).
    stop_loss_multiple : float
        Stop loss as multiple of entry distance (default 2.5).
    hold_bars : int
        Maximum hold time in bars (default 4).
    cooldown_bars : int
        Minimum bars between signals (default 10).
    """
    
    def __init__(
        self,
        z_threshold: float = 2.5,
        mr_signal_threshold: float = 0.6,
        min_atr_z: float = 1.0,
        take_profit_multiple: float = 1.5,
        stop_loss_multiple: float = 2.5,
        hold_bars: int = 4,
        cooldown_bars: int = 10,
    ) -> None:
        self.z_threshold = z_threshold
        self.mr_signal_threshold = mr_signal_threshold
        self.min_atr_z = min_atr_z
        self.take_profit_multiple = take_profit_multiple
        self.stop_loss_multiple = stop_loss_multiple
        self.hold_bars = hold_bars
        self.cooldown_bars = cooldown_bars
        
        self._last_signal_bar: int = 0
        self._bar_count: int = 0
    
    def set_harvest_mode(self) -> None:
        """Switch to dedicated volatility harvesting mode with relaxed thresholds.
        
        In harvest mode, the z-score threshold drops from 2.5 to 1.8,
        the mean-revert signal threshold stays at 0.6, the ATR z
        threshold drops from 1.0 to 0.8, and hold_bars drops from
        4 to 3 for faster exits on mean-reversion trades.
        """
        self.z_threshold = 1.8
        self.mr_signal_threshold = 0.6
        self.min_atr_z = 0.8
        self.cooldown_bars = 6  # shorter cooldown in dedicated mode
        self.stop_loss_multiple = 2.0  # slightly tighter stops
        self.hold_bars = 3  # faster exits for mean-reversion
    
    def set_default_mode(self) -> None:
        """Restore default thresholds for sniper/active_trader modes."""
        self.z_threshold = 2.5
        self.mr_signal_threshold = 0.6
        self.min_atr_z = 1.0
        self.cooldown_bars = 10
        self.stop_loss_multiple = 2.5
        self.hold_bars = 4
    
    def evaluate(
        self,
        features: dict[str, float],
        current_price: float,
        atr_14: float,
    ) -> Optional[VolatilityHarvestSignal]:
        """Evaluate whether to generate a volatility harvesting signal.
        
        Parameters
        ----------
        features : dict[str, float]
            Feature dictionary containing GARCH outputs and other indicators.
        current_price : float
            Current price level.
        atr_14 : float
            14-period ATR for stop/target calculation.
            
        Returns
        -------
        VolatilityHarvestSignal or None
            A signal if conditions are met, None otherwise.
        """
        self._bar_count += 1
        
        # Check cooldown — only enforce after a signal has been emitted
        if self._last_signal_bar > 0 and (self._bar_count - self._last_signal_bar) < self.cooldown_bars:
            return None
        
        # Extract GARCH features
        garch_z = features.get("garch_z_score", 0.0)
        garch_mr_signal = features.get("garch_mean_revert_signal", 0.0)
        garch_vol_regime = features.get("garch_vol_regime", 1.0)
        garch_sigma = features.get("garch_sigma", 0.0)
        atr_z = features.get("atr_z_20", 0.0)
        hurst = features.get("hurst_exponent", 0.5)
        
        # Validate inputs
        if garch_sigma <= 0 or atr_14 <= 0 or current_price <= 0:
            return None
        
        # ── Entry conditions ──────────────────────────────────────
        # 1. Extreme z-score: price has moved far relative to forecast vol
        abs_z = abs(garch_z)
        if abs_z < self.z_threshold:
            return None
        
        # 2. High mean-revert signal probability
        if garch_mr_signal < self.mr_signal_threshold:
            return None
        
        # 3. Elevated volatility regime (regime >= 1.0 = at least normal)
        if garch_vol_regime < 1.0:  # skip only during very low vol
            return None
        
        # 4. Confirmed by ATR z-score
        if atr_z < self.min_atr_z:
            return None
        
        # 5. Low Hurst (mean-reverting tendency) — bonus, not required
        is_mean_reverting = hurst < 0.45
        
        # ── Determine direction ───────────────────────────────────
        # Mean-reversion: bet AGAINST the extreme move
        if garch_z > 0:
            # Big up move → expect reversion DOWN → SHORT
            direction = Direction.SHORT
        else:
            # Big down move → expect reversion UP → LONG
            direction = Direction.LONG
        
        # ── Calculate entry/stop/target ───────────────────────────
        # Entry: current price (market order for reversion)
        entry = current_price
        
        # Distance from entry: use ATR * z-score magnitude
        distance = atr_14 * min(abs_z, 5.0) * 0.5  # conservative scaling
        
        if direction is Direction.LONG:
            stop_loss = entry - distance * self.stop_loss_multiple
            take_profit = entry + distance * self.take_profit_multiple
        else:
            stop_loss = entry + distance * self.stop_loss_multiple
            take_profit = entry - distance * self.take_profit_multiple
        
        # ── Confidence calculation ────────────────────────────────
        # Base confidence from z-score extremity
        base_confidence = min(0.5 + (abs_z - self.z_threshold) * 0.1, 0.8)
        
        # Boost for mean-reverting Hurst
        if is_mean_reverting:
            base_confidence = min(base_confidence + 0.05, 0.85)
        
        # Boost for very high mean-revert signal
        if garch_mr_signal > 0.8:
            base_confidence = min(base_confidence + 0.05, 0.85)
        
        # ── Build rationale ───────────────────────────────────────
        rationale: tuple[str, ...] = (
            f"volatility harvesting: z={garch_z:.2f} mr_signal={garch_mr_signal:.2f}",
            f"extreme move detected — betting on mean reversion",
            f"high vol regime (garch_vol_regime={garch_vol_regime:.1f})",
            f"atr_z={atr_z:.2f} hurst={hurst:.2f}",
        )
        if is_mean_reverting:
            rationale += ("low Hurst confirms mean-reverting tendency",)
        
        self._last_signal_bar = self._bar_count
        
        return VolatilityHarvestSignal(
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=base_confidence,
            z_score=garch_z,
            mean_revert_signal=garch_mr_signal,
            hold_minutes=self.hold_bars * 15,  # assuming 15M bars
            rationale=rationale,
        )
    
    def to_trade_signal(
        self,
        signal: VolatilityHarvestSignal,
        symbol: str,
        min_confidence: float,
        position_scale: float,
        snapshot: Any,
        model_version: str,
    ) -> TradeSignal:
        """Convert a VolatilityHarvestSignal to a TradeSignal."""
        return TradeSignal(
            symbol=symbol,
            direction=signal.direction,
            confidence=signal.confidence,
            min_confidence=min_confidence,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            horizon_sec=signal.hold_minutes * 60,
            snapshot=snapshot,
            rationale=signal.rationale,
            model_version=model_version,
            execution_stop=signal.stop_loss,
            thesis_invalidation=None,
            primary_target=signal.take_profit,
            extended_target=signal.take_profit,
            hold_horizon_minutes=signal.hold_minutes,
            execution_trigger_type="volatility_harvest",
            signal_strength="strong_buy" if signal.direction is Direction.LONG else "strong_sell",
            position_scale=position_scale,
        )
