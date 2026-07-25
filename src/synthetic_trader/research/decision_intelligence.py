"""Decision intelligence - enhanced explainability and uncertainty quantification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from synthetic_trader.domain import Candle, Direction, Regime, TradeSignal
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.features.market_structure import market_structure_features
from synthetic_trader.features.regimes import classify_regime
from synthetic_trader.models.advanced import ConfidenceScorer, FeatureSelector, ModelCalibrator
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.strategy.decision_engine import DecisionEngine


class EvidenceType(str, Enum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"


@dataclass
class Evidence:
    """A piece of evidence for or against a decision."""
    evidence_id: str
    name: str
    type: EvidenceType
    description: str
    strength: float  # 0-1, how strong this evidence is
    source: str  # model, structure, regime, displacement, etc.
    value: Any  # The actual value (e.g., "bos_up": 1.0)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UncertaintyDecomposition:
    """Breakdown of uncertainty sources."""
    total_uncertainty: float
    aleatoric: float  # Irreducible noise
    epistemic: float  # Model uncertainty
    calibration: float  # Calibration uncertainty
    regime: float  # Regime uncertainty
    structural: float  # Structure uncertainty

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionTrace:
    """Complete trace of a decision for auditability."""
    trace_id: str
    timestamp: str
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    min_confidence: float

    # Evidence
    supporting_evidence: List[Evidence]
    contradicting_evidence: List[Evidence]
    neutral_evidence: List[Evidence]

    # Uncertainty
    uncertainty: UncertaintyDecomposition

    # Model state
    model_version: str
    features_used: List[str]
    feature_values: Dict[str, float]

    # Regime & Structure
    regime: str
    regime_confidence: float
    structure_bias: float
    displacement: float

    # Alternative scenarios
    counterfactuals: List[Dict[str, Any]]  # What would change the decision?

    # Invalidation
    invalidation_criteria: List[str]
    invalidation_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "confidence": self.confidence,
            "min_confidence": self.min_confidence,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "contradicting_evidence": [e.to_dict() for e in self.contradicting_evidence],
            "neutral_evidence": [e.to_dict() for e in self.neutral_evidence],
            "uncertainty": self.uncertainty.to_dict(),
            "model_version": self.model_version,
            "features_used": self.features_used,
            "feature_values": self.feature_values,
            "regime": self.regime,
            "regime_confidence": self.regime_confidence,
            "structure_bias": self.structure_bias,
            "displacement": self.displacement,
            "counterfactuals": self.counterfactuals,
            "invalidation_criteria": self.invalidation_criteria,
            "invalidation_price": self.invalidation_price,
        }


class DecisionIntelligence:
    """
    Enhanced decision engine with full explainability and uncertainty quantification.

    Provides:
    - Evidence decomposition (supporting/contradicting/neutral)
    - Uncertainty quantification (aleatoric/epistemic/calibration/regime/structural)
    - Counterfactual analysis (what would change the decision?)
    - Invalidation criteria (what would prove the thesis wrong)
    - Complete audit trail
    """

    def __init__(
        self,
        decision_engine: DecisionEngine,
        confidence_scorer: ConfidenceScorer,
        feature_selector: FeatureSelector,
        calibrator: ModelCalibrator,
    ) -> None:
        self.decision_engine = decision_engine
        self.confidence_scorer = confidence_scorer
        self.feature_selector = feature_selector
        self.calibrator = calibrator

    def analyze(
        self,
        symbol: str,
        candles: List[Candle],
        higher_timeframe_candles: List[Candle] = None,
        role_candles: Dict[str, List[Candle]] = None,
    ) -> DecisionTrace:
        """
        Perform full decision analysis with explainability.

        Returns a DecisionTrace with complete evidence, uncertainty, and audit trail.
        """
        # Get base decision
        report = self.decision_engine.evaluate(
            symbol=symbol,
            candles=candles,
            higher_timeframe_candles=higher_timeframe_candles,
            role_candles=role_candles,
        )

        # Build feature snapshot
        snapshot = build_snapshot(
            symbol=symbol,
            timeframe_sec=60,
            candles=candles,
            higher_timeframe_candles=higher_timeframe_candles,
        )

        features = dict(snapshot.features)
        regime = snapshot.regime.value
        structure = snapshot.structure

        # Get model prediction
        model = self.decision_engine.model
        raw_prob = model.predict_proba(features)
        calibrated_prob = self.calibrator.calibrate(raw_prob) if self.calibrator._fitted else raw_prob

        # Direction
        direction = Direction.LONG if calibrated_prob > 0.5 else Direction.SHORT
        direction_str = direction.value

        # Evidence collection
        supporting, contradicting, neutral = self._collect_evidence(
            features, calibrated_prob, direction, regime, structure
        )

        # Uncertainty decomposition
        uncertainty = self._decompose_uncertainty(
            features, calibrated_prob, regime, structure
        )

        # Counterfactuals
        counterfactuals = self._generate_counterfactuals(
            features, calibrated_prob, direction, regime, structure
        )

        # Invalidation criteria
        invalidation_criteria, invalidation_price = self._define_invalidation(
            report.signal if report.signal else None,
            regime,
            structure,
        )

        # Build trace
        trace = DecisionTrace(
            trace_id=f"trace_{datetime.utcnow().timestamp()}",
            timestamp=datetime.utcnow().isoformat() + "Z",
            symbol=symbol,
            direction=direction_str,
            entry_price=report.signal.entry if report.signal else 0,
            stop_loss=report.signal.stop_loss if report.signal else 0,
            take_profit=report.signal.take_profit if report.signal else 0,
            confidence=report.signal.confidence if report.signal else 0,
            min_confidence=report.signal.min_confidence if report.signal else 0,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            neutral_evidence=neutral,
            uncertainty=uncertainty,
            model_version=model.version,
            features_used=list(features.keys()),
            feature_values=features,
            regime=regime,
            regime_confidence=self._calculate_regime_confidence(regime, features),
            structure_bias=structure.get("structure_bias", 0),
            displacement=structure.get("displacement_atr", 0),
            counterfactuals=counterfactuals,
            invalidation_criteria=invalidation_criteria,
            invalidation_price=invalidation_price,
        )

        return trace

    def _collect_evidence(
        self,
        features: Dict[str, float],
        prob: float,
        direction: Direction,
        regime: str,
        structure: Dict[str, float],
    ) -> Tuple[List[Evidence], List[Evidence], List[Evidence]]:
        """Collect and categorize evidence."""
        supporting = []
        contradicting = []
        neutral = []
        is_long = direction == Direction.LONG

        def add_evidence(name: str, source: str, value: Any, strength: float,
                        etype: EvidenceType, description: str, context: Dict = None):
            ev = Evidence(
                evidence_id=f"ev_{len(supporting)+len(contradicting)+len(neutral)}",
                name=name,
                type=etype,
                description=description,
                strength=strength,
                source=source,
                value=value,
                context=context or {},
            )
            if etype == EvidenceType.SUPPORTING:
                supporting.append(ev)
            elif etype == EvidenceType.CONTRADICTING:
                contradicting.append(ev)
            else:
                neutral.append(ev)

        # Model probability
        if (is_long and prob > 0.55) or (not is_long and prob < 0.45):
            add_evidence(
                "model_probability", "model", prob, abs(prob - 0.5) * 2,
                EvidenceType.SUPPORTING,
                f"Model predicts {direction.value} with {prob:.1%} probability",
            )
        elif (is_long and prob < 0.45) or (not is_long and prob > 0.55):
            add_evidence(
                "model_probability", "model", prob, abs(prob - 0.5) * 2,
                EvidenceType.CONTRADICTING,
                f"Model predicts opposite direction ({prob:.1%})",
            )
        else:
            add_evidence(
                "model_probability", "model", prob, 0.1,
                EvidenceType.NEUTRAL,
                f"Model is uncertain ({prob:.1%})",
            )

        # Regime alignment
        regime_scores = {
            "trend_up": (1.0, -1.0) if is_long else (-1.0, 1.0),
            "trend_down": (-1.0, 1.0) if is_long else (1.0, -1.0),
            "range": (0.0, 0.0),
            "volatile": (-0.5, -0.5),
            "compression": (-0.3, -0.3),
        }
        align, misalign = regime_scores.get(regime, (0.0, 0.0))
        if align > 0:
            add_evidence(
                "regime_alignment", "regime", regime, align,
                EvidenceType.SUPPORTING,
                f"Regime '{regime}' aligns with {direction.value} direction",
            )
        elif misalign < 0:
            add_evidence(
                "regime_alignment", "regime", regime, abs(misalign),
                EvidenceType.CONTRADICTING,
                f"Regime '{regime}' opposes {direction.value} direction",
            )

        # Structure evidence
        structure_bias = structure.get("structure_bias", 0)
        if (is_long and structure_bias > 0.3) or (not is_long and structure_bias < -0.3):
            add_evidence(
                "structure_bias", "structure", structure_bias, abs(structure_bias),
                EvidenceType.SUPPORTING,
                f"Market structure {'bullish' if structure_bias > 0 else 'bearish'} (bias: {structure_bias:.2f})",
            )
        elif (is_long and structure_bias < -0.3) or (not is_long and structure_bias > 0.3):
            add_evidence(
                "structure_bias", "structure", structure_bias, abs(structure_bias),
                EvidenceType.CONTRADICTING,
                f"Market structure opposes direction (bias: {structure_bias:.2f})",
            )

        # BOS
        for bos_key, direction_match in [("bos_up", True), ("bos_down", False)]:
            if structure.get(bos_key, 0) > 0:
                if (is_long and direction_match) or (not is_long and not direction_match):
                    add_evidence(
                        "break_of_structure", "structure", bos_key, 0.7,
                        EvidenceType.SUPPORTING,
                        f"Break of Structure {'up' if direction_match else 'down'} confirms direction",
                    )
                else:
                    add_evidence(
                        "break_of_structure", "structure", bos_key, 0.7,
                        EvidenceType.CONTRADICTING,
                        f"Break of Structure {'up' if direction_match else 'down'} contradicts direction",
                    )

        # Liquidity sweeps
        for sweep_key, direction_match in [("liquidity_sweep_down", True), ("liquidity_sweep_up", False)]:
            if structure.get(sweep_key, 0) > 0:
                if (is_long and direction_match) or (not is_long and not direction_match):
                    add_evidence(
                        "liquidity_sweep", "structure", sweep_key, 0.6,
                        EvidenceType.SUPPORTING,
                        f"Liquidity sweep {'down' if direction_match else 'up'} reclaimed",
                    )

        # FVG
        for fvg_key, direction_match in [("fvg_bullish_active", True), ("fvg_bearish_active", False)]:
            if structure.get(fvg_key, 0) > 0:
                if (is_long and direction_match) or (not is_long and not direction_match):
                    add_evidence(
                        "fair_value_gap", "structure", fvg_key, 0.5,
                        EvidenceType.SUPPORTING,
                        f"Active {'bullish' if direction_match else 'bearish'} FVG supports direction",
                    )

        # Displacement
        displacement = structure.get("displacement_atr", 0)
        if displacement > 1.0:
            add_evidence(
                "displacement", "structure", displacement, min(displacement / 2, 1.0),
                EvidenceType.SUPPORTING,
                f"Strong displacement ({displacement:.1f} ATR) confirms momentum",
            )

        # Momentum
        slope = features.get("slope_20_atr", 0)
        if (is_long and slope > 0.1) or (not is_long and slope < -0.1):
            add_evidence(
                "momentum", "model", slope, min(abs(slope) * 5, 1.0),
                EvidenceType.SUPPORTING,
                f"Momentum {'positive' if slope > 0 else 'negative'} (slope: {slope:.2f})",
            )

        # Volatility regime
        atr_ratio = features.get("atr_ratio", 1.0)
        if atr_ratio > 1.5:
            add_evidence(
                "volatility", "model", atr_ratio, 0.3,
                EvidenceType.CONTRADICTING,
                f"High volatility (ATR ratio: {atr_ratio:.2f}) increases uncertainty",
            )

        return supporting, contradicting, neutral

    def _decompose_uncertainty(
        self,
        features: Dict[str, float],
        prob: float,
        regime: str,
        structure: Dict[str, float],
    ) -> UncertaintyDecomposition:
        """Decompose uncertainty into sources."""
        # Aleatoric: irreducible market noise (use volatility)
        atr_ratio = features.get("atr_ratio", 1.0)
        atr_z = features.get("atr_z_20", 0)
        aleatoric = min(0.2 + 0.3 * (atr_ratio - 1) + 0.1 * abs(atr_z), 0.8)

        # Epistemic: model uncertainty (distance from decision boundary)
        distance_from_boundary = abs(prob - 0.5)
        epistemic = max(0.1, 0.5 - distance_from_boundary)  # Higher when near 0.5

        # Calibration: calibration quality
        calibration = 0.0
        if self.calibrator._fitted:
            # Use recent ECE as calibration uncertainty
            calibration = 0.02  # Would use actual ECE
        else:
            calibration = 0.1  # Uncalibrated = higher uncertainty

        # Regime: regime uncertainty
        regime_uncertainties = {
            "trend_up": 0.05,
            "trend_down": 0.05,
            "range": 0.15,
            "volatile": 0.25,
            "compression": 0.20,
            "unknown": 0.30,
        }
        regime = regime_uncertainties.get(regime, 0.15)

        # Structural: structure clarity
        structure_bias = abs(structure.get("structure_bias", 0))
        structural = max(0.05, 0.15 - structure_bias * 0.1)

        total = min(aleatoric + epistemic + calibration + regime + structural, 1.0)

        return UncertaintyDecomposition(
            total_uncertainty=total,
            aleatoric=aleatoric,
            epistemic=epistemic,
            calibration=calibration,
            regime=regime,
            structural=structural,
        )

    def _generate_counterfactuals(
        self,
        features: Dict[str, float],
        prob: float,
        direction: Direction,
        regime: str,
        structure: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Generate counterfactual scenarios that would change the decision."""
        counterfactuals = []
        is_long = direction == Direction.LONG

        # What if model probability flipped?
        flip_prob = 1 - prob
        counterfactuals.append({
            "scenario": "model_probability_flipped",
            "description": f"If model predicted {1-prob:.1%} instead of {prob:.1%}",
            "change": {"model_probability": {"from": prob, "to": flip_prob}},
            "new_direction": "short" if is_long else "long",
            "plausibility": "low",
        })

        # What if structure bias flipped?
        structure_bias = structure.get("structure_bias", 0)
        flip_bias = -structure_bias
        counterfactuals.append({
            "scenario": "structure_bias_reversed",
            "description": f"If structure bias was {flip_bias:.2f} instead of {structure_bias:.2f}",
            "change": {"structure_bias": {"from": structure_bias, "to": flip_bias}},
            "new_direction": "short" if is_long else "long",
            "plausibility": "medium",
        })

        # What if regime was different?
        regime_impacts = {"trend_up": 0.8, "trend_down": 0.2, "range": 0.5, "volatile": 0.3}
        for alt_regime, alt_prob in regime_impacts.items():
            if alt_regime != regime:
                counterfactuals.append({
                    "scenario": f"regime_change_to_{alt_regime}",
                    "description": f"If regime changed from {regime} to {alt_regime}",
                    "change": {"regime": {"from": regime, "to": alt_regime}},
                    "estimated_probability": alt_prob,
                    "new_direction": "long" if alt_prob > 0.5 else "short",
                    "plausibility": "medium",
                })

        # What if key feature changed?
        key_features = ["slope_20_atr", "displacement_atr", "atr_ratio", "structure_bias"]
        for feat in key_features:
            if feat in features:
                current = features[feat]
                # Simulate 2 std deviation change
                if feat == "slope_20_atr":
                    new_val = -current if abs(current) > 0.1 else 0.2
                elif feat == "displacement_atr":
                    new_val = max(0.5, current / 2)
                elif feat == "atr_ratio":
                    new_val = 1.0 if current > 1 else 1.5
                elif feat == "structure_bias":
                    new_val = -current
                else:
                    continue

                # Estimate new probability (simplified)
                counterfactuals.append({
                    "scenario": f"feature_change_{feat}",
                    "description": f"If {feat} changed from {current:.2f} to {new_val:.2f}",
                    "change": {feat: {"from": current, "to": new_val}},
                    "estimated_impact": "medium",
                    "plausibility": "high",
                })

        return counterfactuals

    def _define_invalidation(
        self,
        signal: Optional[TradeSignal],
        regime: str,
        structure: Dict[str, float],
    ) -> Tuple[List[str], Optional[float]]:
        """Define what would invalidate the thesis."""
        if not signal:
            return ["No signal generated"], None

        criteria = []
        invalidation_price = None

        # Price-based invalidation
        if signal.direction == Direction.LONG:
            invalidation_price = signal.stop_loss
            criteria.append(f"Price falls below stop loss ({signal.stop_loss:.5f})")
            criteria.append(f"Price closes below thesis invalidation ({signal.thesis_invalidation:.5f})" if signal.thesis_invalidation else "Thesis invalidation level not defined")
        else:
            invalidation_price = signal.stop_loss
            criteria.append(f"Price rises above stop loss ({signal.stop_loss:.5f})")
            criteria.append(f"Price closes above thesis invalidation ({signal.thesis_invalidation:.5f})" if signal.thesis_invalidation else "Thesis invalidation level not defined")

        # Structure-based invalidation
        structure_bias = structure.get("structure_bias", 0)
        if signal.direction == Direction.LONG and structure_bias < -0.5:
            criteria.append("Market structure turns bearish (structure_bias < -0.5)")
        elif signal.direction == Direction.SHORT and structure_bias > 0.5:
            criteria.append("Market structure turns bullish (structure_bias > 0.5)")

        # Regime invalidation
        if signal.direction == Direction.LONG and regime in ("trend_down", "volatile"):
            criteria.append(f"Regime shifts to {regime} (unfavorable for long)")
        elif signal.direction == Direction.SHORT and regime in ("trend_up", "volatile"):
            criteria.append(f"Regime shifts to {regime} (unfavorable for short)")

        # Volatility expansion
        if structure.get("displacement_atr", 0) < 0.3:
            criteria.append("Displacement collapses below 0.3 ATR (loss of momentum)")

        return criteria, invalidation_price

    def _calculate_regime_confidence(self, regime: str, features: Dict[str, float]) -> float:
        """Calculate confidence in regime classification."""
        hurst = features.get("hurst_exponent", 0.5)
        entropy = features.get("entropy", 0.0)
        atr_ratio = features.get("atr_ratio", 1.0)

        # Heuristic confidence based on feature alignment
        if regime in ("trend_up", "trend_down"):
            if hurst > 0.6 and atr_ratio > 1.1:
                return 0.85
            elif hurst > 0.55:
                return 0.70
            return 0.55
        elif regime == "range":
            if entropy > 0.6 and 0.8 < atr_ratio < 1.2:
                return 0.80
            return 0.60
        elif regime == "volatile":
            if atr_ratio > 1.5:
                return 0.85
            return 0.65
        elif regime == "compression":
            if atr_ratio < 0.8 and features.get("range_z_50", 0) < -1:
                return 0.80
            return 0.60
        return 0.50


class DecisionTraceStore:
    """Storage for decision traces."""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._traces: List[DecisionTrace] = []

    def save(self, trace: DecisionTrace) -> Path:
        """Save a decision trace."""
        file = self.storage_path / f"trace_{trace.trace_id}.json"
        file.write_text(json.dumps(trace.to_dict(), indent=2))
        self._traces.append(trace)
        return file

    def load(self, trace_id: str) -> Optional[DecisionTrace]:
        """Load a decision trace."""
        file = self.storage_path / f"trace_{trace_id}.json"
        if file.exists():
            data = json.loads(file.read_text())
            return self._dict_to_trace(data)
        return None

    def load_recent(self, limit: int = 100) -> List[DecisionTrace]:
        """Load most recent traces."""
        files = sorted(self.storage_path.glob("trace_*.json"), reverse=True)
        traces = []
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                traces.append(self._dict_to_trace(data))
            except Exception:
                pass
        return traces

    def _dict_to_trace(self, data: Dict) -> DecisionTrace:
        """Convert dict back to DecisionTrace."""
        # Reconstruct evidence
        def dict_to_evidence(d: Dict) -> Evidence:
            return Evidence(**d)

        def dict_to_uncertainty(d: Dict) -> UncertaintyDecomposition:
            return UncertaintyDecomposition(**d)

        return DecisionTrace(
            trace_id=data["trace_id"],
            timestamp=data["timestamp"],
            symbol=data["symbol"],
            direction=data["direction"],
            entry_price=data["entry_price"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            confidence=data["confidence"],
            min_confidence=data["min_confidence"],
            supporting_evidence=[dict_to_evidence(e) for e in data["supporting_evidence"]],
            contradicting_evidence=[dict_to_evidence(e) for e in data["contradicting_evidence"]],
            neutral_evidence=[dict_to_evidence(e) for e in data["neutral_evidence"]],
            uncertainty=dict_to_uncertainty(data["uncertainty"]),
            model_version=data["model_version"],
            features_used=data["features_used"],
            feature_values=data["feature_values"],
            regime=data["regime"],
            regime_confidence=data["regime_confidence"],
            structure_bias=data["structure_bias"],
            displacement=data["displacement"],
            counterfactuals=data["counterfactuals"],
            invalidation_criteria=data["invalidation_criteria"],
            invalidation_price=data.get("invalidation_price"),
        )

    def export_audit_report(self, output_path: Path, since: str = None) -> Path:
        """Export audit report as markdown."""
        traces = self.load_recent(200)
        if since:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            traces = [t for t in traces if datetime.fromisoformat(t.timestamp.replace("Z", "+00:00")) > since_dt]

        lines = [
            "# Decision Audit Report",
            f"Generated: {datetime.utcnow().isoformat()}",
            f"Total Decisions: {len(traces)}",
            "",
        ]

        for t in traces:
            lines.append(f"## {t.trace_id} - {t.symbol} {t.direction}")
            lines.append(f"**Time:** {t.timestamp}")
            lines.append(f"**Direction:** {t.direction} | **Confidence:** {t.confidence:.1%} (min: {t.min_confidence:.1%})")
            lines.append(f"**Entry:** {t.entry_price:.5f} | **SL:** {t.stop_loss:.5f} | **TP:** {t.take_profit:.5f}")
            lines.append(f"**Regime:** {t.regime} (confidence: {t.regime_confidence:.0%})")
            lines.append(f"**Structure Bias:** {t.structure_bias:.2f} | **Displacement:** {t.displacement:.1f} ATR")
            lines.append(f"**Uncertainty:** {t.uncertainty.total_uncertainty:.1%} (aleatoric: {t.uncertainty.aleatoric:.1%}, epistemic: {t.uncertainty.epistemic:.1%})")
            lines.append("")

            lines.append("### Supporting Evidence")
            for e in t.supporting_evidence:
                lines.append(f"- **{e.name}** ({e.strength:.0%}): {e.description}")
            lines.append("")

            lines.append("### Contradicting Evidence")
            for e in t.contradicting_evidence:
                lines.append(f"- **{e.name}** ({e.strength:.0%}): {e.description}")
            lines.append("")

            lines.append("### Invalidation Criteria")
            for c in t.invalidation_criteria:
                lines.append(f"- {c}")
            lines.append("")

            lines.append("---")
            lines.append("")

        output_path.write_text("\n".join(lines))
        return output_path