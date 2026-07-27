"""Regime-specific strategy models.

Instead of a single trade/no-trade decision, the engine routes to
regime-specific models that each produce probability distributions:

- **TREND model**: Momentum-following, uses EMA slopes, ADX-like strength
- **RANGE model**: Mean-reversion, uses Bollinger bands, RSI extremes, distance from equilibrium
- **BREAKOUT model**: Volatility expansion, uses ATR surge, BB width, volume proxies
- **VOLATILE model**: Momentum exhaustion, uses Hurst, entropy, tick flow exhaustion

Each model outputs:
- bull_probability: float (0-1)
- bear_probability: float (0-1)
- expected_move: float (points, signed)
- expected_adverse_excursion: float (points)
- confidence: float (0-1)
- reasoning: list[str]

The decision engine combines these with the existing component scoring
to produce a richer probabilistic output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from synthetic_trader.domain import Direction, Regime
from synthetic_trader.features.indicators import clamp, safe_div


@dataclass
class RegimeModelOutput:
    """Output from a regime-specific strategy model."""

    bull_probability: float = 0.5
    bear_probability: float = 0.5
    expected_move: float = 0.0
    expected_adverse_excursion: float = 0.0
    confidence: float = 0.0
    reasoning: List[str] = field(default_factory=list)

    def to_features(self) -> dict[str, float]:
        """Convert to a flat feature dict for downstream consumption."""
        return {
            "regime_bull_prob": self.bull_probability,
            "regime_bear_prob": self.bear_probability,
            "regime_expected_move": self.expected_move,
            "regime_adverse_excursion": self.expected_adverse_excursion,
            "regime_confidence": self.confidence,
        }


def trend_model(features: dict[str, float], direction: Direction) -> RegimeModelOutput:
    """Momentum-following model for TREND_UP / TREND_DOWN regimes.

    Uses EMA slopes, Hurst persistence, and structure bias to estimate
    continuation probability.
    """
    reasoning: list[str] = []
    bull = 0.5
    bear = 0.5

    # EMA slope alignment
    slope = features.get("slope_20_atr", 0.0)
    ema_spread = features.get("ema_21_50_spread_atr", 0.0)
    hurst = features.get("hurst_exponent", 0.5)

    # Slope contribution (max +/- 0.25)
    slopeContrib = clamp(slope * 2.0, -0.25, 0.25)
    if slopeContrib > 0:
        bull += slopeContrib
        reasoning.append(f"EMA slope bullish (+{slopeContrib:.2f})")
    else:
        bear += abs(slopeContrib)
        reasoning.append(f"EMA slope bearish ({slopeContrib:.2f})")

    # EMA spread contribution
    spreadContrib = clamp(ema_spread * 1.5, -0.20, 0.20)
    if spreadContrib > 0:
        bull += spreadContrib
        reasoning.append(f"EMA spread bullish (+{spreadContrib:.2f})")
    else:
        bear += abs(spreadContrib)
        reasoning.append(f"EMA spread bearish ({spreadContrib:.2f})")

    # Hurst persistence bonus
    if hurst > 0.6:
        persistence_bonus = (hurst - 0.5) * 0.3
        if slope > 0:
            bull += persistence_bonus
            reasoning.append(f"Hurst persistence favors trend ({hurst:.2f})")
        else:
            bear += persistence_bonus
            reasoning.append(f"Hurst persistence favors trend ({hurst:.2f})")

    # Structure bias
    structure_bias = features.get("structure_bias", 0.0)
    structContrib = clamp(structure_bias * 0.3, -0.15, 0.15)
    if structContrib > 0:
        bull += structContrib
    else:
        bear += abs(structContrib)

    # Normalize
    total = bull + bear
    bull /= total
    bear /= total

    # Expected move: ATR-based
    atr = features.get("atr_14", 1.0)
    expected_move = atr * 1.5 * (1 if bull > bear else -1)
    adverse = atr * 0.5

    confidence = abs(bull - bear)

    return RegimeModelOutput(
        bull_probability=clamp(bull, 0.01, 0.99),
        bear_probability=clamp(bear, 0.01, 0.99),
        expected_move=expected_move,
        expected_adverse_excursion=adverse,
        confidence=confidence,
        reasoning=reasoning,
    )


def range_model(features: dict[str, float], direction: Direction) -> RegimeModelOutput:
    """Mean-reversion model for RANGE regimes.

    Uses Bollinger position, RSI extremes, distance from equilibrium,
    and entropy to estimate reversal probability.
    """
    reasoning: list[str] = []
    bull = 0.5
    bear = 0.5

    # Bollinger position (0 = at lower band, 1 = at upper band)
    bb_pos = features.get("bb_position", 0.5)
    rsi = features.get("rsi_14", 50.0)
    entropy = features.get("entropy", 0.5)
    kc_pos = features.get("kc_position", 0.5)

    # Bollinger reversion signal
    if bb_pos < 0.2:
        bull += 0.20
        reasoning.append(f"Price near lower Bollinger band ({bb_pos:.2f}) — reversion up")
    elif bb_pos > 0.8:
        bear += 0.20
        reasoning.append(f"Price near upper Bollinger band ({bb_pos:.2f}) — reversion down")

    # RSI extremes
    if rsi < 30:
        bull += 0.15
        reasoning.append(f"RSI oversold ({rsi:.0f}) — mean reversion up")
    elif rsi > 70:
        bear += 0.15
        reasoning.append(f"RSI overbought ({rsi:.0f}) — mean reversion down")

    # Keltner position (equilibrium proxy)
    kcContrib = clamp((0.5 - kc_pos) * 0.3, -0.15, 0.15)
    if kcContrib > 0:
        bull += kcContrib
        reasoning.append(f"Below Keltner equilibrium (+{kcContrib:.2f})")
    else:
        bear += abs(kcContrib)
        reasoning.append(f"Above Keltner equilibrium ({kcContrib:.2f})")

    # High entropy = stronger mean-reversion signal
    if entropy > 0.7:
        entropy_bonus = (entropy - 0.5) * 0.15
        if bb_pos < 0.5:
            bull += entropy_bonus
        else:
            bear += entropy_bonus
        reasoning.append(f"High entropy supports reversion ({entropy:.2f})")

    # Normalize
    total = bull + bear
    bull /= total
    bear /= total

    atr = features.get("atr_14", 1.0)
    expected_move = atr * 0.8 * (1 if bull > bear else -1)
    adverse = atr * 0.4

    confidence = abs(bull - bear)

    return RegimeModelOutput(
        bull_probability=clamp(bull, 0.01, 0.99),
        bear_probability=clamp(bear, 0.01, 0.99),
        expected_move=expected_move,
        expected_adverse_excursion=adverse,
        confidence=confidence,
        reasoning=reasoning,
    )


def breakout_model(features: dict[str, float], direction: Direction) -> RegimeModelOutput:
    """Volatility expansion model for volatile/compression breakout regimes.

    Uses ATR surge, Bollinger width, Hurst, and displacement to estimate
    breakout direction probability.
    """
    reasoning: list[str] = []
    bull = 0.5
    bear = 0.5

    atr_ratio = features.get("atr_ratio", 1.0)
    bb_width = features.get("bb_width", 0.0)
    displacement = features.get("displacement", 0.0)
    hurst = features.get("hurst_exponent", 0.5)
    slope = features.get("slope_20_atr", 0.0)

    # ATR surge suggests breakout in trend direction
    if atr_ratio > 1.3:
        surge_bonus = clamp((atr_ratio - 1.0) * 0.15, 0.0, 0.15)
        if slope > 0:
            bull += surge_bonus
            reasoning.append(f"ATR surge in uptrend ({atr_ratio:.2f}x)")
        else:
            bear += surge_bonus
            reasoning.append(f"ATR surge in downtrend ({atr_ratio:.2f}x)")

    # Displacement = strong directional move
    if abs(displacement) > 0.5:
        dispContrib = clamp(displacement * 0.15, -0.15, 0.15)
        if dispContrib > 0:
            bull += dispContrib
        else:
            bear += abs(dispContrib)
        reasoning.append(f"Displacement {'bullish' if displacement > 0 else 'bearish'} ({displacement:.2f})")

    # Wide Bollinger = expansion
    if bb_width > 0.04:
        reasoning.append(f"Bollinger expansion ({bb_width:.3f})")
        # Direction from slope
        if slope > 0.1:
            bull += 0.10
        elif slope < -0.1:
            bear += 0.10

    # Low Hurst in volatile regime = chaotic, reduce confidence
    if hurst < 0.4:
        reasoning.append(f"Low Hurst ({hurst:.2f}) — chaotic breakout, reduced confidence")

    total = bull + bear
    bull /= total
    bear /= total

    atr = features.get("atr_14", 1.0)
    expected_move = atr * 2.5 * (1 if bull > bear else -1)
    adverse = atr * 1.0

    confidence = abs(bull - bear) * 0.8  # reduce confidence for volatile regimes

    return RegimeModelOutput(
        bull_probability=clamp(bull, 0.01, 0.99),
        bear_probability=clamp(bear, 0.01, 0.99),
        expected_move=expected_move,
        expected_adverse_excursion=adverse,
        confidence=confidence,
        reasoning=reasoning,
    )


def regime_model(features: dict[str, float], regime: Regime, direction: Direction) -> RegimeModelOutput:
    """Route to the appropriate regime-specific model and return its output.

    This is the main entry point called by the decision engine.
    """
    if regime in (Regime.TREND_UP, Regime.TREND_DOWN):
        return trend_model(features, direction)
    elif regime == Regime.RANGE:
        return range_model(features, direction)
    elif regime in (Regime.VOLATILE, Regime.COMPRESSION):
        return breakout_model(features, direction)
    else:
        # UNKNOWN or transitional — use a blended model
        trend_out = trend_model(features, direction)
        range_out = range_model(features, direction)
        # 50/50 blend
        return RegimeModelOutput(
            bull_probability=(trend_out.bull_probability + range_out.bull_probability) / 2,
            bear_probability=(trend_out.bear_probability + range_out.bear_probability) / 2,
            expected_move=(trend_out.expected_move + range_out.expected_move) / 2,
            expected_adverse_excursion=(trend_out.expected_adverse_excursion + range_out.expected_adverse_excursion) / 2,
            confidence=(trend_out.confidence + range_out.confidence) / 2,
            reasoning=[f"[blended] {r}" for r in trend_out.reasoning[:1] + range_out.reasoning[:1]],
        )
