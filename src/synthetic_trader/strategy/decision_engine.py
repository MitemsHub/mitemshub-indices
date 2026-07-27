from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import mean

from synthetic_trader.config import SymbolProfile, TraderConfig
from synthetic_trader.domain import Candle, Direction, Regime, TradeSignal
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.features.indicators import clamp, safe_div
from synthetic_trader.features.market_structure import structural_direction
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.strategy.confirmation_builder import confirm_setup
from synthetic_trader.strategy.intraday_execution_builder import build_intraday_execution
from synthetic_trader.strategy.swing_execution_builder import build_swing_execution
from synthetic_trader.strategy.setup_builder import classify_setup
from synthetic_trader.strategy.top_down_bias import infer_top_down_bias
from synthetic_trader.strategy.regime_models import regime_model


@dataclass(frozen=True)
class DecisionReport:
    signal: TradeSignal | None
    reasons: tuple[str, ...]


@dataclass
class CalibrationState:
    predictions: list[float] = field(default_factory=list)
    outcomes: list[int] = field(default_factory=list)
    _fitted_ir: object | None = field(default=None, repr=False)
    _fitted_platt: object | None = field(default=None, repr=False)
    _fitted_ir_version: int = field(default=0, repr=False)
    _fitted_platt_version: int = field(default=0, repr=False)

    def add(self, prediction: float, outcome: int) -> None:
        self.predictions.append(prediction)
        self.outcomes.append(outcome)
        # Invalidate cached models when new training data arrives.
        self._fitted_ir = None
        self._fitted_platt = None

    def _ensure_ir(self) -> object | None:
        """Fit and cache the IsotonicRegression model if needed."""
        if self._fitted_ir_version == len(self.predictions):
            return self._fitted_ir  # cached (model or cached failure)
        try:
            import numpy as np
            from sklearn.isotonic import IsotonicRegression
            ir = IsotonicRegression(out_of_bounds="clip")
            ir.fit(np.array(self.predictions), np.array(self.outcomes))
            self._fitted_ir = ir
            self._fitted_ir_version = len(self.predictions)
            return ir
        except Exception:
            # Cache the failure so we don't retry on every call.
            self._fitted_ir = None
            self._fitted_ir_version = len(self.predictions)
            return None

    def _ensure_platt(self) -> object | None:
        """Fit and cache the Platt-scaling LogisticRegression model if needed."""
        if self._fitted_platt_version == len(self.predictions):
            return self._fitted_platt  # cached (model or cached failure)
        try:
            import numpy as np
            from sklearn.linear_model import LogisticRegression
            X = np.array(self.predictions).reshape(-1, 1)
            y = np.array(self.outcomes)
            lr = LogisticRegression(solver="lbfgs")
            lr.fit(X, y)
            self._fitted_platt = lr
            self._fitted_platt_version = len(self.predictions)
            return lr
        except Exception:
            # Cache the failure so we don't retry on every call.
            self._fitted_platt = None
            self._fitted_platt_version = len(self.predictions)
            return None

    def calibrate(self, prediction: float) -> float:
        if len(self.predictions) < 30:
            return prediction
        ir = self._ensure_ir()
        if ir is None:
            return prediction
        try:
            return float(ir.predict([prediction])[0])
        except Exception:
            return prediction

    def platt_calibrate(self, prediction: float) -> float:
        if len(self.predictions) < 30:
            return prediction
        lr = self._ensure_platt()
        if lr is None:
            return prediction
        try:
            return float(lr.predict_proba([[prediction]])[0, 1])
        except Exception:
            return prediction


class DecisionEngine:
    def __init__(
        self,
        config: TraderConfig,
        model: OnlineLogisticModel | None = None,
    ) -> None:
        self.config = config
        self.model = model or OnlineLogisticModel(config.model)
        self.calibration = CalibrationState()
        self._call_lifecycle: dict[str, str] = {}

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        higher_timeframe_candles: list[Candle] | None = None,
        role_candles: dict[str, list[Candle]] | None = None,
        trading_mode: str = "intraday",
    ) -> DecisionReport:
        profile = self._profile(symbol)
        execution_candles = role_candles.get("execution", candles) if role_candles else candles
        setup_candles = role_candles.get("setup", candles) if role_candles else candles
        confirmation_candles = (
            role_candles.get("confirmation", setup_candles)
            if role_candles
            else candles
        )
        bias_candles = (
            role_candles.get("bias", higher_timeframe_candles or setup_candles)
            if role_candles
            else (higher_timeframe_candles or candles)
        )

        if len(execution_candles) < profile.min_history_candles:
            return DecisionReport(
                None,
                (f"need {profile.min_history_candles} candles, have {len(execution_candles)}",),
            )

        snapshot = build_snapshot(
            symbol=symbol,
            timeframe_sec=profile.execution_timeframe_sec if role_candles else profile.default_timeframe_sec,
            candles=execution_candles,
            higher_timeframe_candles=confirmation_candles if role_candles else higher_timeframe_candles,
            extra_timeframes={
                "bias": bias_candles,
                "setup": setup_candles,
                "confirmation": confirmation_candles,
            } if role_candles else None,
        )
        features = dict(snapshot.features)
        model_long_probability = self.model.predict_proba(features)
        calibrated_prob = self.calibration.calibrate(model_long_probability)

        # ── Regime-specific probabilistic model (direction-agnostic) ──
        regime_out = regime_model(features, snapshot.regime, Direction.FLAT)
        features.update(regime_out.to_features())

        long_score = self._score_direction(Direction.LONG, snapshot.regime, features, calibrated_prob)
        short_score = self._score_direction(Direction.SHORT, snapshot.regime, features, calibrated_prob)
        bias = infer_top_down_bias(
            symbol=symbol,
            bias_candles=bias_candles,
            setup_candles=setup_candles,
            confirmation_candles=confirmation_candles,
            execution_candles=execution_candles,
        )
        setup = classify_setup(
            bias=bias,
            setup_candles=setup_candles,
        )
        confirmation = confirm_setup(
            setup=setup,
            confirmation_candles=confirmation_candles[-30:],
        )
        direction = Direction.LONG if setup.trade_direction == "buy" else Direction.SHORT
        confidence = long_score if direction is Direction.LONG else short_score
        if setup.state != "none" and confirmation.state in {"confirmed", "actionable"}:
            confidence = max(confidence, profile.confirmed_setup_confidence_floor)
        min_confidence = max(
            0.0,
            self.config.risk.min_confidence - profile.confidence_relaxation,
        )

        if confidence < min_confidence:
            return DecisionReport(
                None,
                (
                    f"confidence {confidence:.3f} below threshold {min_confidence:.3f}",
                    f"model long probability {model_long_probability:.3f}",
                    f"calibrated probability {calibrated_prob:.3f}",
                ),
            )

        rationale = (
            bias.reason,
            setup.reason,
            confirmation.reason,
        )

        # ── Mean-reversion scalp path for range regimes ──────────────
        # When the market is range-bound (Hurst < 0.4) and the regime model
        # produces a directional probability above threshold, generate a
        # scalp trade with tighter stops/targets instead of refusing.
        hurst = features.get("hurst_exponent", 0.5)
        current_regime = snapshot.regime
        is_range_scalp = (
            current_regime in (Regime.RANGE, Regime.COMPRESSION)
            and hurst < 0.4
            and features.get("regime_confidence", 0.0) > 0.15
        )
        if is_range_scalp and confidence >= min_confidence:
            regime_bull = features.get("regime_bull_prob", 0.5)
            regime_bear = features.get("regime_bear_prob", 0.5)
            scalp_direction_prob = max(regime_bull, regime_bear)
            scalp_direction = Direction.LONG if regime_bull > regime_bear else Direction.SHORT
            # Require at least 60% directional probability for scalp
            if scalp_direction_prob >= 0.60:
                atr_14 = features.get("atr_14", 1.0)
                entry = features.get("close", execution_candles[-1].close)
                # Tight scalp: stop = 1x ATR, target = 1.5x ATR (1.5R)
                scalp_stop_distance = min(atr_14, entry * profile.max_stop_distance_pct)
                if scalp_direction is Direction.LONG:
                    scalp_stop = entry - scalp_stop_distance
                    scalp_target = entry + scalp_stop_distance * 1.5
                else:
                    scalp_stop = entry + scalp_stop_distance
                    scalp_target = entry - scalp_stop_distance * 1.5
                scalp_rationale = (
                    f"range scalp: Hurst={hurst:.2f} regime_bull={regime_bull:.2f} regime_bear={regime_bear:.2f}",
                    f"mean-reversion scalp in {current_regime.value} regime",
                ) + tuple(regime_out.reasoning[:3])
                signal = TradeSignal(
                    symbol=symbol,
                    direction=scalp_direction,
                    confidence=confidence,
                    min_confidence=min_confidence,
                    entry=entry,
                    stop_loss=scalp_stop,
                    take_profit=scalp_target,
                    horizon_sec=profile.execution_timeframe_sec * 2,
                    snapshot=snapshot,
                    rationale=scalp_rationale,
                    model_version=self.model.version,
                    execution_stop=scalp_stop,
                    thesis_invalidation=None,
                    primary_target=scalp_target,
                    extended_target=scalp_target,
                    hold_horizon_minutes=30,
                    execution_trigger_type="mean_reversion_scalp",
                )
                return DecisionReport(signal, scalp_rationale)

        # Allow signals when confidence is sufficiently high even if the formal
        # setup/confirmation gates are not fully met.  The confidence score
        # already incorporates model probability, structure, regime, momentum,
        # and confluence — it is a better综合 (holistic) measure than the
        # binary setup/confirmation states alone.
        #
        # Gate: require BOTH setup state AND confirmation to be valid,
        # OR confidence above an elevated threshold (0.62) which means
        # at least 5 of the 8 scoring components agree on direction.
        has_formal_setup = (
            setup.state != "none"
            and confirmation.state in {"confirmed", "actionable"}
        )
        # Lowered from 0.62 to 0.52 — with a fresh untrained model the
        # confidence typically scores 0.48-0.55, which is enough when
        # combined with structure/regime/momentum signals.  0.52 matches
        # the confirmed_setup_confidence_floor for R_100.
        has_strong_confidence = confidence >= 0.52
        if not has_formal_setup and not has_strong_confidence:
            return DecisionReport(None, rationale)

        execution_plan = None
        if role_candles and trading_mode == "sniper":
            swing_signal = build_swing_execution(
                symbol=symbol,
                direction=setup.trade_direction,
                setup_candles=setup_candles,
                confirmation_candles=confirmation_candles,
                bias_candles=bias_candles,
                max_stop_distance_pct=profile.max_stop_distance_pct,
            )
            if swing_signal is not None:
                signal = TradeSignal(
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    min_confidence=min_confidence,
                    entry=swing_signal.entry,
                    stop_loss=swing_signal.stop_loss,
                    take_profit=swing_signal.take_profit,
                    horizon_sec=swing_signal.hold_hours * 3600,
                    snapshot=snapshot,
                    rationale=rationale,
                    model_version=self.model.version,
                    execution_stop=swing_signal.stop_loss,
                    thesis_invalidation=swing_signal.invalidation,
                    primary_target=swing_signal.take_profit,
                    extended_target=swing_signal.take_profit,
                    hold_horizon_minutes=swing_signal.hold_hours * 60,
                    execution_trigger_type="liquidity_sweep_reversal" if swing_signal.setup_type == "liquidity_sweep_reversal" else "structure_continuation",
                )
                return DecisionReport(signal, rationale)
        elif role_candles:
            default_thesis_invalidation = (
                execution_candles[-1].low if direction is Direction.LONG else execution_candles[-1].high
            )
            execution_plan = build_intraday_execution(
                symbol=symbol,
                direction=setup.trade_direction,
                execution_candles=execution_candles,
                thesis_invalidation=(
                    bias.invalidation_price
                    if bias.invalidation_price is not None
                    else default_thesis_invalidation
                ),
                config=self.config,
            )
        if execution_plan is None:
            snapshot_features = dict(snapshot.features) if snapshot else {}
            atr_14 = snapshot_features.get("atr_14", 0.0)
            entry = snapshot_features.get("close", execution_candles[-1].close) if snapshot_features else execution_candles[-1].close

            # Sanity cap: stop distance can never exceed 5% of entry price.
            # This prevents insane ATR values (e.g. 360 on a 258-priced instrument)
            # from producing impossible TP levels like 1,336.
            max_stop = entry * profile.max_stop_distance_pct

            if direction is Direction.LONG:
                stop_distance = max(atr_14 * 1.5, entry * 0.002) if atr_14 > 0 else max(entry - execution_candles[-1].low, profile.pip_size * 2)
                raw_stop_distance = stop_distance
                stop_distance = min(stop_distance, max_stop)
                stop_loss = entry - stop_distance
                take_profit = entry + stop_distance * profile.take_profit_rr
            else:
                stop_distance = max(atr_14 * 1.5, entry * 0.002) if atr_14 > 0 else max(execution_candles[-1].high - entry, profile.pip_size * 2)
                raw_stop_distance = stop_distance
                stop_distance = min(stop_distance, max_stop)
                stop_loss = entry + stop_distance
                take_profit = entry - stop_distance * profile.take_profit_rr

            # Diagnostic: log stop distance cap status for live tuning.
            cap_triggered = raw_stop_distance > max_stop
            stop_pct = (abs(entry - stop_loss) / entry * 100) if entry else 0
            logging.info(
                "[%s] fallback stop_cap=%s raw=%.4f capped=%.4f stop_pct=%.2f%% max_pct=%.2f%% entry=%.4f",
                symbol, "TRIGGERED" if cap_triggered else "ok",
                raw_stop_distance, stop_distance, stop_pct,
                profile.max_stop_distance_pct * 100, entry,
            )

            signal = TradeSignal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                min_confidence=min_confidence,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                horizon_sec=profile.execution_timeframe_sec * profile.hold_bars_setup,
                snapshot=snapshot,
                rationale=rationale,
                model_version=self.model.version,
                execution_stop=stop_loss,
                thesis_invalidation=bias.invalidation_price,
                primary_target=take_profit,
                extended_target=take_profit,
                hold_horizon_minutes=profile.intraday_hold_horizon_minutes,
            )
            return DecisionReport(signal, rationale)

        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            min_confidence=min_confidence,
            entry=execution_plan.entry,
            stop_loss=execution_plan.execution_stop,
            take_profit=execution_plan.primary_target,
            horizon_sec=execution_plan.hold_horizon_minutes * 60,
            snapshot=snapshot,
            rationale=rationale,
            model_version=self.model.version,
            execution_stop=execution_plan.execution_stop,
            thesis_invalidation=execution_plan.thesis_invalidation,
            primary_target=execution_plan.primary_target,
            extended_target=execution_plan.extended_target,
            hold_horizon_minutes=execution_plan.hold_horizon_minutes,
            execution_trigger_type=execution_plan.trigger_type,
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
        momentum_component = self._momentum_component(direction, features)
        volatility_component = self._volatility_component(direction, features)
        confluence_component = self._confluence_component(direction, features)
        tick_flow_component = self._tick_flow_component(direction, features)

        weights = {
            "model": 0.25,
            "structure": 0.20,
            "regime": 0.15,
            "mean_reversion": 0.08,
            "displacement": 0.06,
            "momentum": 0.06,
            "volatility": 0.05,
            "confluence": 0.07,
            "tick_flow": 0.08,
        }

        confidence = (
            weights["model"] * model_component
            + weights["structure"] * structure_component
            + weights["regime"] * regime_component
            + weights["mean_reversion"] * mean_reversion_component
            + weights["displacement"] * displacement_component
            + weights["momentum"] * momentum_component
            + weights["volatility"] * volatility_component
            + weights["confluence"] * confluence_component
            + weights["tick_flow"] * tick_flow_component
        )
        return clamp(confidence, 0.0, 1.0)

    def _structure_component(self, direction: Direction, features: dict[str, float]) -> float:
        structural = structural_direction(features)
        if structural is direction:
            base = 0.85
        elif structural is Direction.FLAT:
            bias = features.get("structure_bias", 0.0)
            if direction is Direction.LONG:
                base = 0.50 + clamp(bias, -1.0, 1.0) * 0.25
            else:
                base = 0.50 - clamp(bias, -1.0, 1.0) * 0.25
        else:
            base = 0.20

        internal_bos = features.get("internal_bos_up", 0.0) if direction is Direction.LONG else features.get("internal_bos_down", 0.0)
        fvg_active = features.get("fvg_bullish_active", 0.0) if direction is Direction.LONG else features.get("fvg_bearish_active", 0.0)
        sweep = features.get("liquidity_sweep_down", 0.0) if direction is Direction.LONG else features.get("liquidity_sweep_up", 0.0)

        boost = internal_bos * 0.15 + fvg_active * 0.10 + sweep * 0.15
        return clamp(base + boost, 0.0, 1.0)

    def _regime_component(self, direction: Direction, regime: Regime, features: dict[str, float]) -> float:
        """Regime component using probabilistic regime model output.

        When regime_bull_prob/regime_bear_prob are available from the
        regime-specific models, use them directly.  Otherwise fall back
        to the legacy heuristic scoring.
        """
        hurst = features.get("hurst_exponent", 0.5)
        entropy = features.get("entropy", 0.5)
        vol_cluster = features.get("volatility_clustering", 1.0)

        # Use probabilistic regime model output when available.
        regime_bull = features.get("regime_bull_prob")
        regime_bear = features.get("regime_bear_prob")
        if regime_bull is not None and regime_bear is not None:
            if direction is Direction.LONG:
                base = regime_bull
            else:
                base = regime_bear
            # Boost with Hurst persistence when available
            if hurst > 0.6:
                base = clamp(base + (hurst - 0.5) * 0.1, 0.0, 1.0)
            elif hurst < 0.3:
                base = clamp(base - (0.5 - hurst) * 0.1, 0.0, 1.0)
            return clamp(base, 0.0, 1.0)

        # Legacy heuristic fallback
        if regime is Regime.TREND_UP:
            base = 0.85 if direction is Direction.LONG else 0.20
            if hurst > 0.6:
                base += 0.05 if direction is Direction.LONG else -0.05
        elif regime is Regime.TREND_DOWN:
            base = 0.85 if direction is Direction.SHORT else 0.20
            if hurst > 0.6:
                base += 0.05 if direction is Direction.SHORT else -0.05
        elif regime is Regime.VOLATILE:
            displacement = features.get("displacement_atr", 0.0)
            aligned = (
                (direction is Direction.LONG and features.get("body", 0.0) > 0)
                or (direction is Direction.SHORT and features.get("body", 0.0) < 0)
            )
            base = 0.65 if aligned and displacement > 1.0 else 0.35
            if vol_cluster > 2.0:
                base -= 0.10
        elif regime is Regime.COMPRESSION:
            base = 0.45
        elif regime is Regime.RANGE:
            base = 0.55
            if entropy > 0.7:
                base -= 0.05
        else:
            base = 0.50
        return clamp(base, 0.0, 1.0)

    def _mean_reversion_component(self, direction: Direction, regime: Regime, features: dict[str, float]) -> float:
        position = features.get("position_in_20_range", 0.5)
        rsi_value = features.get("rsi_14", 50.0)
        dc_pos = features.get("dc_position", 0.5)
        kc_pos = features.get("kc_position", 0.5)

        if regime not in (Regime.RANGE, Regime.COMPRESSION):
            return 0.50

        if direction is Direction.LONG:
            range_score = (1.0 - position) * 0.5
            rsi_score = safe_div(55.0 - rsi_value, 55.0) * 0.3
            dc_score = (1.0 - dc_pos) * 0.1
            kc_score = (1.0 - kc_pos) * 0.1
        else:
            range_score = position * 0.5
            rsi_score = safe_div(rsi_value - 45.0, 55.0) * 0.3
            dc_score = dc_pos * 0.1
            kc_score = kc_pos * 0.1

        return clamp(range_score + rsi_score + dc_score + kc_score, 0.0, 1.0)

    def _displacement_component(self, direction: Direction, features: dict[str, float]) -> float:
        displacement = clamp(features.get("displacement_atr", 0.0) / 2.5, 0.0, 1.0)
        body = features.get("body", 0.0)
        if direction is Direction.LONG and body > 0:
            return displacement
        if direction is Direction.SHORT and body < 0:
            return displacement
        return 0.30

    def _momentum_component(self, direction: Direction, features: dict[str, float]) -> float:
        slope = features.get("slope_20_atr", 0.0)
        ema_spread = features.get("ema_9_21_spread_atr", 0.0)
        last_return = features.get("last_return", 0.0)

        if direction is Direction.LONG:
            score = clamp(slope * 0.5 + ema_spread * 0.3 + max(last_return, 0.0) * 10.0, 0.0, 1.0)
        else:
            score = clamp(-slope * 0.5 - ema_spread * 0.3 + min(last_return, 0.0) * -10.0, 0.0, 1.0)
        return score

    def _volatility_component(self, direction: Direction, features: dict[str, float]) -> float:
        atr_ratio = features.get("atr_ratio", 1.0)
        atr_z = features.get("atr_z_20", 0.0)
        realized_vol = features.get("realized_vol_20", 0.0)

        if atr_z > 2.0:
            return 0.30
        if atr_ratio > 1.5:
            return 0.40
        if atr_ratio < 0.7:
            return 0.60
        return 0.55

    def _confluence_component(self, direction: Direction, features: dict[str, float]) -> float:
        htf_bias_up = features.get("bias_structure_bias", 0.0)
        htf_bias_down = -features.get("bias_structure_bias", 0.0)
        setup_bias = features.get("setup_structure_bias", 0.0)
        conf_bias = features.get("confirmation_structure_bias", 0.0)

        if direction is Direction.LONG:
            alignment = sum(1 for v in [htf_bias_up, setup_bias, conf_bias] if v > 0)
        else:
            alignment = sum(1 for v in [htf_bias_down, -setup_bias, -conf_bias] if v > 0)

        return alignment / 3.0

    def _tick_flow_component(self, direction: Direction, features: dict[str, float]) -> float:
        """Score based on tick-level micro-structure features.

        Uses velocity, acceleration, exhaustion, impulse/retrace ratio,
        and streak bias to estimate short-term directional pressure.
        """
        velocity = features.get("tick_velocity", 0.0)
        acceleration = features.get("tick_acceleration", 0.0)
        exhaustion = features.get("tick_exhaustion", 0.0)
        impulse_ratio = features.get("tick_impulse_retrace_ratio", 1.0)
        streak_bias = features.get("tick_streak_bias", 0.0)
        up_ratio = features.get("tick_up_ratio", 0.5)
        total_ticks = features.get("tick_total", 0.0)

        # Need at least 10 ticks for meaningful flow analysis
        if total_ticks < 10:
            return 0.50

        # Velocity contribution (signed, normalized by ATR)
        atr = features.get("atr_14", 1.0)
        velocity_score = clamp(velocity / max(atr, 1e-10) * 2.0, -0.25, 0.25)

        # Acceleration = velocity change direction
        accel_score = clamp(acceleration / max(atr, 1e-10) * 3.0, -0.15, 0.15)

        # Impulse/retrace ratio: >1 = trending, <1 = ranging
        impulse_score = clamp((impulse_ratio - 1.0) * 0.15, -0.15, 0.15)

        # Streak bias: positive = up streak, negative = down streak
        streak_score = clamp(streak_bias * 0.15, -0.15, 0.15)

        # Up/down ratio deviation from 0.5
        ratio_score = clamp((up_ratio - 0.5) * 0.2, -0.10, 0.10)

        # Exhaustion penalty: high exhaustion = reduce conviction
        exhaustion_penalty = exhaustion * 0.10

        raw = 0.50 + velocity_score + accel_score + impulse_score + streak_score + ratio_score - exhaustion_penalty

        return clamp(raw, 0.0, 1.0)

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
            f"hurst={features.get('hurst_exponent', 0.5):.2f}",
            f"entropy={features.get('entropy', 0.0):.2f}",
        ]
        if features.get("liquidity_sweep_down", 0.0):
            notes.append("downside sweep reclaimed")
        if features.get("liquidity_sweep_up", 0.0):
            notes.append("upside sweep rejected")
        if features.get("bos_up", 0.0):
            notes.append("break of structure up")
        if features.get("bos_down", 0.0):
            notes.append("break of structure down")
        if features.get("internal_bos_up", 0.0):
            notes.append("internal BOS up")
        if features.get("internal_bos_down", 0.0):
            notes.append("internal BOS down")
        if features.get("fvg_bullish_active", 0.0):
            notes.append("bullish FVG active")
        if features.get("fvg_bearish_active", 0.0):
            notes.append("bearish FVG active")
        if features.get("equal_highs", 0.0):
            notes.append("equal highs detected")
        if features.get("equal_lows", 0.0):
            notes.append("equal lows detected")
        if features.get("structure_bias", 0.0) > 0.5:
            notes.append("bullish market structure")
        elif features.get("structure_bias", 0.0) < -0.5:
            notes.append("bearish market structure")
        return tuple(notes)

    def update_calibration(self, prediction: float, outcome: int) -> None:
        self.calibration.add(prediction, outcome)

    def explain_signal(self, signal: TradeSignal) -> dict[str, object]:
        features = dict(signal.snapshot.features)
        return {
            "direction": signal.direction.value,
            "confidence": signal.confidence,
            "model_probability": signal.snapshot.features.get("model_long_probability", 0.5),
            "regime": signal.snapshot.regime.value,
            "structure_bias": features.get("structure_bias", 0.0),
            "key_factors": {
                "model_component": features.get("model_long_probability", 0.5),
                "structure_component": features.get("bos_up", 0.0) if signal.direction == Direction.LONG else features.get("bos_down", 0.0),
                "regime_component": 1.0 if (signal.direction == Direction.LONG and signal.snapshot.regime == Regime.TREND_UP) or (signal.direction == Direction.SHORT and signal.snapshot.regime == Regime.TREND_DOWN) else 0.5,
                "displacement": features.get("displacement_atr", 0.0),
                "momentum": features.get("slope_20_atr", 0.0),
            },
            "rationale": list(signal.rationale),
            "entry_reason": f"Entry at {signal.entry:.5f} based on {signal.execution_trigger_type or 'pattern'} trigger",
            "invalidation": f"Thesis invalidated at {signal.thesis_invalidation:.5f}" if signal.thesis_invalidation else "No thesis invalidation level",
            "targets": {
                "primary": signal.primary_target,
                "extended": signal.extended_target,
            },
        }
