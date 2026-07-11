from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.config import SymbolProfile, TraderConfig
from synthetic_trader.domain import Candle, Direction, Regime, TradeSignal
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.features.indicators import clamp, safe_div
from synthetic_trader.features.market_structure import structural_direction
from synthetic_trader.models.online import OnlineLogisticModel


@dataclass(frozen=True)
class DecisionReport:
    signal: TradeSignal | None
    reasons: tuple[str, ...]


class DecisionEngine:
    def __init__(
        self,
        config: TraderConfig,
        model: OnlineLogisticModel | None = None,
    ) -> None:
        self.config = config
        self.model = model or OnlineLogisticModel(config.model)

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        higher_timeframe_candles: list[Candle] | None = None,
    ) -> DecisionReport:
        profile = self._profile(symbol)
        if len(candles) < profile.min_history_candles:
            return DecisionReport(None, (f"need {profile.min_history_candles} candles, have {len(candles)}",))

        snapshot = build_snapshot(
            symbol=symbol,
            timeframe_sec=profile.default_timeframe_sec,
            candles=candles,
            higher_timeframe_candles=higher_timeframe_candles,
        )
        features = dict(snapshot.features)
        model_long_probability = self.model.predict_proba(features)
        long_score = self._score_direction(Direction.LONG, snapshot.regime, features, model_long_probability)
        short_score = self._score_direction(Direction.SHORT, snapshot.regime, features, model_long_probability)
        direction = Direction.LONG if long_score > short_score else Direction.SHORT
        confidence = max(long_score, short_score)

        if confidence < self.config.risk.min_confidence:
            return DecisionReport(
                None,
                (
                    f"confidence {confidence:.3f} below threshold {self.config.risk.min_confidence:.3f}",
                    f"model long probability {model_long_probability:.3f}",
                ),
            )

        entry = candles[-1].close
        atr_value = max(features.get("atr_14", 0.0), features.get("range", 0.0), profile.pip_size)
        risk_distance = max(atr_value * profile.stop_atr_multiple, profile.pip_size)
        if direction is Direction.LONG:
            stop_loss = entry - risk_distance
            take_profit = entry + risk_distance * profile.take_profit_rr
        else:
            stop_loss = entry + risk_distance
            take_profit = entry - risk_distance * profile.take_profit_rr

        rationale = self._rationale(direction, snapshot.regime, features, model_long_probability, confidence)
        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            horizon_sec=profile.default_timeframe_sec * 8,
            snapshot=snapshot,
            rationale=rationale,
            model_version=self.model.version,
        )
        return DecisionReport(signal, rationale)

    def _profile(self, symbol: str) -> SymbolProfile:
        try:
            return self.config.symbols[symbol]
        except KeyError as exc:
            raise ValueError(f"unsupported symbol {symbol!r}") from exc

    def _score_direction(
        self,
        direction: Direction,
        regime: Regime,
        features: dict[str, float],
        model_long_probability: float,
    ) -> float:
        model_component = model_long_probability if direction is Direction.LONG else 1.0 - model_long_probability
        structure_component = self._structure_component(direction, features)
        regime_component = self._regime_component(direction, regime, features)
        mean_reversion_component = self._mean_reversion_component(direction, regime, features)
        displacement_component = self._displacement_component(direction, features)

        confidence = (
            0.36 * model_component
            + 0.26 * structure_component
            + 0.20 * regime_component
            + 0.10 * mean_reversion_component
            + 0.08 * displacement_component
        )
        return clamp(confidence, 0.0, 1.0)

    def _structure_component(self, direction: Direction, features: dict[str, float]) -> float:
        structural = structural_direction(features)
        if structural is direction:
            return 0.82
        if structural is Direction.FLAT:
            bias = features.get("structure_bias", 0.0)
            if direction is Direction.LONG:
                return 0.50 + clamp(bias, -1.0, 1.0) * 0.22
            return 0.50 - clamp(bias, -1.0, 1.0) * 0.22
        return 0.22

    def _regime_component(self, direction: Direction, regime: Regime, features: dict[str, float]) -> float:
        if regime is Regime.TREND_UP:
            return 0.82 if direction is Direction.LONG else 0.24
        if regime is Regime.TREND_DOWN:
            return 0.82 if direction is Direction.SHORT else 0.24
        if regime is Regime.VOLATILE:
            displacement = features.get("displacement_atr", 0.0)
            aligned = (
                (direction is Direction.LONG and features.get("body", 0.0) > 0)
                or (direction is Direction.SHORT and features.get("body", 0.0) < 0)
            )
            return 0.68 if aligned and displacement > 1.0 else 0.38
        if regime is Regime.COMPRESSION:
            return 0.46
        return 0.54

    def _mean_reversion_component(self, direction: Direction, regime: Regime, features: dict[str, float]) -> float:
        position = features.get("position_in_20_range", 0.5)
        rsi_value = features.get("rsi_14", 50.0)
        if regime not in (Regime.RANGE, Regime.COMPRESSION):
            return 0.50
        if direction is Direction.LONG:
            return clamp((1.0 - position) * 0.65 + safe_div(55.0 - rsi_value, 55.0) * 0.35, 0.0, 1.0)
        return clamp(position * 0.65 + safe_div(rsi_value - 45.0, 55.0) * 0.35, 0.0, 1.0)

    def _displacement_component(self, direction: Direction, features: dict[str, float]) -> float:
        displacement = clamp(features.get("displacement_atr", 0.0) / 2.5, 0.0, 1.0)
        body = features.get("body", 0.0)
        if direction is Direction.LONG and body > 0:
            return displacement
        if direction is Direction.SHORT and body < 0:
            return displacement
        return 0.35

    def _rationale(
        self,
        direction: Direction,
        regime: Regime,
        features: dict[str, float],
        model_long_probability: float,
        confidence: float,
    ) -> tuple[str, ...]:
        notes = [
            f"{direction.value} setup in {regime.value} regime",
            f"confidence={confidence:.3f}",
            f"model_long_probability={model_long_probability:.3f}",
            f"structure_bias={features.get('structure_bias', 0.0):.2f}",
            f"displacement_atr={features.get('displacement_atr', 0.0):.2f}",
            f"atr_ratio={features.get('atr_ratio', 1.0):.2f}",
        ]
        if features.get("liquidity_sweep_down", 0.0):
            notes.append("downside sweep reclaimed")
        if features.get("liquidity_sweep_up", 0.0):
            notes.append("upside sweep rejected")
        if features.get("bos_up", 0.0):
            notes.append("break of structure up")
        if features.get("bos_down", 0.0):
            notes.append("break of structure down")
        return tuple(notes)
