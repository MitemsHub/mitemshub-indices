from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
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
import time as _time

from synthetic_trader.strategy.volatility_harvesting import VolatilityHarvester
from synthetic_trader.models.regime_detector import RegimeShiftDetector, MarketState


@dataclass(frozen=True)
class DecisionReport:
    signal: TradeSignal | None
    reasons: tuple[str, ...]


MAX_CALIBRATION_SAMPLES = 500


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
        self._prune()
        # Invalidate cached models when new training data arrives.
        self._fitted_ir = None
        self._fitted_platt = None

    def _prune(self) -> None:
        """Trim oldest entries to keep buffer within MAX_CALIBRATION_SAMPLES."""
        if len(self.predictions) > MAX_CALIBRATION_SAMPLES:
            excess = len(self.predictions) - MAX_CALIBRATION_SAMPLES
            self.predictions = self.predictions[excess:]
        # Always re-sync outcomes to match predictions length (defensive invariant).
        self.outcomes = self.outcomes[-len(self.predictions):] if self.predictions else []

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

    def brier_score(self) -> float | None:
        """Compute Brier score on the calibration buffer.

        Brier score measures the accuracy of probabilistic predictions:
          Brier = (1/N) * sum((predicted - actual)^2)

        Lower is better: 0.0 = perfect, 0.25 = coin-flip, 1.0 = worst.

        Returns None if fewer than 10 samples (too few for meaningful score).
        """
        n = len(self.predictions)
        if n < 10:
            return None
        return sum(
            (p - o) ** 2 for p, o in zip(self.predictions, self.outcomes)
        ) / n

    def directional_accuracy(self) -> float | None:
        """Compute directional accuracy (hit rate) on the calibration buffer.

        Measures how often the model's directional prediction matches the
        actual outcome: prediction >= 0.5 when outcome=1, or < 0.5 when
        outcome=0.

        Returns accuracy as a float 0.0–1.0, or None if < 10 samples.
        """
        n = len(self.predictions)
        if n < 10:
            return None
        correct = sum(
            1
            for p, o in zip(self.predictions, self.outcomes)
            if (p >= 0.5 and o == 1) or (p < 0.5 and o == 0)
        )
        return correct / n


class DecisionEngine:
    def __init__(
        self,
        config: TraderConfig,
        model: OnlineLogisticModel | None = None,
    ) -> None:
        self.config = config
        self.model = model or OnlineLogisticModel(config.model)
        self.calibration = CalibrationState()
        self.regime_detector = RegimeShiftDetector()
        self.volatility_harvester = VolatilityHarvester()
        self._trading_mode = "intraday"
        self._call_lifecycle: dict[str, str] = {}
        self._save_count: int = 0

    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        higher_timeframe_candles: list[Candle] | None = None,
        role_candles: dict[str, list[Candle]] | None = None,
        trading_mode: str = "intraday",
    ) -> DecisionReport:
        # Store trading mode for vol_harvest path activation
        self._trading_mode = trading_mode
        # Activate harvest mode thresholds when in volatility_harvest mode;
        # restore defaults otherwise so thresholds don't persist across switches.
        if trading_mode == "volatility_harvest":
            self.volatility_harvester.set_harvest_mode()
        else:
            self.volatility_harvester.set_default_mode()

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

        # ── Regime shift detection (HMM + CUSUM) ──────────────────────
        # Feed the latest log-return into the regime detector.  If it
        # detects an anomaly (CUSUM shift, HMM regime change, or variance
        # spike) the position_scale will be reduced to protect capital.
        log_return = features.get("log_return", 0.0)
        hmm_state, position_scale, regime_alerts = self.regime_detector.update(log_return)
        if position_scale < 1.0:
            logging.info(
                "[%s] regime shift detected: state=%s position_scale=%.2f alerts=%d",
                symbol, hmm_state.name, position_scale, len(regime_alerts),
            )
        features["regime_position_scale"] = position_scale
        features["regime_hmm_state"] = float(hmm_state.value)
        for alert in regime_alerts:
            features[f"regime_alert_{alert.alert_type}"] = 1.0

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

        # --- NEVER return None when data exists. ---
        # The engine should always produce a signal with its actual confidence.
        # Four signal states: strong_buy, weak_buy, wait, strong_sell, weak_sell
        signal_strength = self._classify_signal_strength(
            confidence=confidence,
            min_confidence=min_confidence,
            has_formal_setup=(
                setup.state != "none"
                and confirmation.state in {"confirmed", "actionable"}
            ),
            direction=direction,
        )
        is_weak = signal_strength in ("weak_buy", "weak_sell", "wait")
        if is_weak and signal_strength != "wait":
            rationale_weak = (
                f"weak signal ({signal_strength}) — confidence {confidence:.3f}",
                f"model long probability {model_long_probability:.3f}",
                f"calibrated probability {calibrated_prob:.3f}",
            )
        elif signal_strength == "wait":
            rationale_weak = (
                f"wait — confidence {confidence:.3f} below minimum {min_confidence:.3f}",
                f"model long probability {model_long_probability:.3f}",
                f"calibrated probability {calibrated_prob:.3f}",
            )

        rationale = (
            bias.reason,
            setup.reason,
            confirmation.reason,
        )

        # ── Volatility harvesting path ─────────────────────────────
        # When GARCH detects an extreme z-score with high mean-revert
        # probability, generate a mean-reversion trade exploiting the
        # generator's variance scheduling (the ONE exploitable property).
        # NOTE: Volatility harvesting BYPASSES the session filter — it
        # explicitly exploits extreme moves that happen regardless of hour.
        atr_14 = features.get("atr_14", 0.0)
        vol_harvest_signal = self.volatility_harvester.evaluate(
            features=features,
            current_price=features.get("close", 0.0),
            atr_14=atr_14,
        )
        if vol_harvest_signal is not None:
            vol_signal = self.volatility_harvester.to_trade_signal(
                signal=vol_harvest_signal,
                symbol=symbol,
                min_confidence=min_confidence,
                position_scale=position_scale,
                snapshot=snapshot,
                model_version=self.model.version,
            )
            return DecisionReport(vol_signal, vol_signal.rationale)

        # ── Formal setup check (used by session filter override) ──────
        has_formal_setup = (
            setup.state != "none"
            and confirmation.state in {"confirmed", "actionable"}
        )

        # ── Session filter gate ────────────────────────────────────
        # Block signal generation during low-volatility hours.
        # The generator's server load balancing creates exploitable
        # time-of-day effects — certain hours consistently produce
        # more volatile moves with better risk/reward.
        #
        # STRONG SIGNAL OVERRIDE: When confidence >= 0.75 AND a formal
        # setup is confirmed, bypass the session filter.  High-confidence
        # setups with confirmed structure are rare and shouldn't be
        # filtered out by low-volatility windows — the signal quality
        # already accounts for regime, structure, and momentum.
        #
        # NOTE: The assembler already computes session_quality and
        # session_vol_rank in the feature snapshot.  We use those
        # features directly instead of maintaining a separate filter
        # instance, avoiding state duplication and inconsistency.
        session_quality = features.get("session_quality", 0.5)
        session_vol_rank = features.get("session_vol_rank", 0.5)
        session_is_peak = features.get("session_is_peak", 0.0) == 1.0
        session_observations = features.get("session_total_observations", 0.0)
        min_quality = self.config.risk.min_session_quality
        warmup = self.config.risk.session_filter_warmup

        STRONG_SIGNAL_CONFIDENCE_THRESHOLD = 0.75
        session_blocked = (
            session_observations >= warmup
            and session_quality < min_quality
        )
        strong_signal_override = (
            session_blocked
            and confidence >= STRONG_SIGNAL_CONFIDENCE_THRESHOLD
            and has_formal_setup
        )
        if strong_signal_override:
            logging.info(
                "[%s] session filter bypassed — strong signal override: "
                "confidence=%.3f >= %.3f, formal setup confirmed, "
                "session quality %.2f < %.2f",
                symbol, confidence, STRONG_SIGNAL_CONFIDENCE_THRESHOLD,
                session_quality, min_quality,
            )
            rationale += (
                f"⚠ strong signal override: confidence {confidence:.3f} >= 0.75, "
                f"formal setup confirmed — session filter bypassed "
                f"(quality {session_quality:.2f} < {min_quality:.2f})",
            )

        # During warmup, don't block — we need data to learn.
        # When blocked (and not overridden), return a WAIT signal (not None)
        # so the frontend shows the actual reason instead of a generic
        # "Setup still forming".
        if session_blocked and not strong_signal_override:
            wait_signal = TradeSignal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                min_confidence=min_confidence,
                entry=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                horizon_sec=0,
                snapshot=snapshot,
                rationale=(f"session filter: quality {session_quality:.2f} < {min_quality:.2f} — low-volatility hour (rank={session_vol_rank:.2f}, peak={session_is_peak})",),
                model_version=self.model.version,
                execution_stop=0.0,
                thesis_invalidation=None,
                primary_target=0.0,
                extended_target=0.0,
                hold_horizon_minutes=0,
                execution_trigger_type="session_filter_block",
                signal_strength="wait",
                position_scale=position_scale,
            )
            return DecisionReport(wait_signal, wait_signal.rationale)

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
                    signal_strength=signal_strength,
                    position_scale=position_scale,
                )
                return DecisionReport(signal, scalp_rationale)

        # Allow signals when confidence is sufficiently high even if the formal
        # setup/confirmation gates are not fully met.  The confidence score
        # already incorporates model probability, structure, regime, momentum,
        # and confluence — it is a better综合 (holistic) measure than the
        # binary setup/confirmation states alone.
        #
        # Gate: require BOTH setup state AND confirmation to be valid,
        # OR confidence above an elevated threshold (0.52) which means
        # at least 5 of the 8 scoring components agree on direction.
        # NOTE: has_formal_setup was already computed above for session filter override.
        has_strong_confidence = confidence >= 0.52
        if not has_formal_setup and not has_strong_confidence and not is_weak:
            # Mark as weak instead of blocking — always produce a signal.
            # Recompute signal_strength with has_formal_setup=False so it matches.
            is_weak = True
            signal_strength = self._classify_signal_strength(
                confidence=confidence,
                min_confidence=min_confidence,
                has_formal_setup=False,
                direction=direction,
            )
            rationale_weak = (
                f"no formal setup and confidence {confidence:.3f} below 0.52",
            )

        # Merge weak rationale into the main rationale so the user sees why it's weak.
        if is_weak and rationale_weak:
            rationale = rationale_weak + rationale

        # Append session quality to rationale so user sees why we traded this hour.
        # Placed AFTER all early-exit paths (vol harvest, session block, scalp)
        # so it's never lost for any signal type.
        if session_observations >= warmup:
            rationale += (f"session quality {session_quality:.2f} (rank={session_vol_rank:.2f}, peak={session_is_peak})",)
        else:
            rationale += (f"session quality {session_quality:.2f} (warming up — {int(session_observations)}/{warmup} observations)",)

        # ── Regime shift warning ──────────────────────────────────
        if position_scale < 1.0:
            regime_state = MarketState(int(features.get("regime_hmm_state", 1)))
            rationale = (
                f"⚠ regime shift detected — position_scale={position_scale:.0%} (HMM: {regime_state.name})",
            ) + rationale

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
                    signal_strength=signal_strength,
                    position_scale=position_scale,
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
                signal_strength=signal_strength,
                position_scale=position_scale,
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
            signal_strength=signal_strength,
            position_scale=position_scale,
        )
        return DecisionReport(signal, rationale)

    def _classify_signal_strength(
        self,
        *,
        confidence: float,
        min_confidence: float,
        has_formal_setup: bool,
        direction: Direction,
    ) -> str:
        """Classify the signal into one of four states based on confidence.

        Thresholds:
        - STRONG: confidence >= 0.65 AND formal setup confirmed
        - WEAK: confidence >= min_confidence (but below strong)
        - WAIT: confidence < min_confidence

        Returns one of: "strong_buy", "weak_buy", "wait", "weak_sell", "strong_sell"
        """
        STRONG_THRESHOLD = 0.65
        dir_suffix = "buy" if direction is Direction.LONG else "sell"

        if confidence >= STRONG_THRESHOLD and has_formal_setup:
            return f"strong_{dir_suffix}"
        elif confidence >= min_confidence:
            return f"weak_{dir_suffix}"
        else:
            return "wait"

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
        """Score direction using 10 components with rebalanced weights.

        Weight rebalancing rationale (from comprehensive review):
        - Synthetic indices have a CSPRNG with GARCH-like variance scheduling
        - Pattern features (structure, displacement, momentum, confluence) are
          noise on random data → reduced weight
        - Statistical features (regime, volatility, GARCH, tick_flow) exploit
          the generator's real properties → increased weight
        """
        model_component = model_long_probability if direction is Direction.LONG else 1.0 - model_long_probability
        structure_component = self._structure_component(direction, features)
        regime_component = self._regime_component(direction, regime, features)
        mean_reversion_component = self._mean_reversion_component(direction, regime, features)
        displacement_component = self._displacement_component(direction, features)
        momentum_component = self._momentum_component(direction, features)
        volatility_component = self._volatility_component(direction, features)
        confluence_component = self._confluence_component(direction, features)
        tick_flow_component = self._tick_flow_component(direction, features)
        garch_component = self._garch_component(direction, features)
        garch_mr_component = self._garch_mr_component(direction, features)

        # ── Rebalanced weights ──────────────────────────────────────
        # Pattern-based components reduced (noise on random data):
        #   structure 0.20→0.10, displacement 0.06→0.03,
        #   momentum 0.06→0.03, confluence 0.07→0.04
        # Statistical components increased (exploitable on synthetic indices):
        #   regime 0.15→0.25, volatility 0.05→0.10, tick_flow 0.08→0.12,
        #   garch NEW 0.10, garch_mr NEW 0.03
        weights = {
            "model": 0.15,          # reduced — learns from noise, not signal
            "structure": 0.10,      # halved — patterns are noise on synthetic indices
            "regime": 0.25,         # largest weight — regime clustering IS real
            "mean_reversion": 0.05, # reduced — less reliable without GARCH context
            "displacement": 0.03,   # halved — random on synthetic indices
            "momentum": 0.03,       # halved — random on synthetic indices
            "volatility": 0.10,     # doubled — volatility clustering is exploitable
            "confluence": 0.04,     # halved — multi-TF structure is noise
            "tick_flow": 0.12,      # increased — microstructure is real
            "garch": 0.10,          # NEW — variance forecast from EGARCH(1,1)
            "garch_mr": 0.03,       # NEW — mean-reversion signal from GARCH
        }
        # Total = 1.00 — statistical features now dominate (0.60 vs 0.20 for patterns)

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
            + weights["garch"] * garch_component
            + weights["garch_mr"] * garch_mr_component
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
            # Missed-trade learning boost: when the engine frequently misses
            # opportunities in range markets, increase the base score so it
            # becomes more willing to take range trades.
            range_miss_boost = features.get("range_miss_boost", 0.0)
            if range_miss_boost > 0:
                base = clamp(base + range_miss_boost, 0.0, 1.0)
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
        """Volatility component — enhanced with GARCH forecast context.

        On synthetic indices, volatility clustering is the ONE exploitable
        property.  When the GARCH model forecasts high upcoming volatility,
        we should be cautious about direction (vol expansion = uncertainty).
        When it forecasts low vol (compression), a breakout is imminent.
        """
        atr_ratio = features.get("atr_ratio", 1.0)
        atr_z = features.get("atr_z_20", 0.0)
        garch_vol_ratio = features.get("garch_vol_ratio", 1.0)
        garch_z = features.get("garch_z_score", 0.0)

        # Base ATR-based score
        if atr_z > 2.0:
            base = 0.30  # extreme vol = uncertain
        elif atr_ratio > 1.5:
            base = 0.40
        elif atr_ratio < 0.7:
            base = 0.60  # compression = opportunity
        else:
            base = 0.55

        # GARCH adjustment: when forecast vol is high relative to long-run,
        # reduce conviction (vol expansion = unpredictable)
        if garch_vol_ratio > 1.5:
            base = clamp(base - 0.10, 0.20, 0.80)
        elif garch_vol_ratio < 0.7:
            base = clamp(base + 0.05, 0.20, 0.80)  # compression = good

        # Extreme z-score: generator will mean-revert volatility
        if abs(garch_z) > 2.5:
            base = clamp(base + 0.05, 0.20, 0.80)  # extreme = reversion coming

        return base

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
        streak bias, spread analysis, direction streaks, and volume surge
        detection to estimate short-term directional pressure.

        The spread, direction, and volume features were added to capture
        microstructure dynamics that price-only analysis misses.
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

        # ── Spread features: wide spread = uncertainty = reduce conviction ──
        spread_z = features.get("tick_spread_z_score", 0.0)
        spread_penalty = clamp(spread_z * 0.05, -0.05, 0.05) if spread_z > 1.5 else 0.0

        # ── Direction streak: strong directional streaks amplify conviction ──
        dir_streak_bias = features.get("tick_dir_streak_bias", 0.0)
        dir_switch_rate = features.get("tick_dir_switch_rate", 0.0)
        dir_streak_score = clamp(dir_streak_bias * 0.12, -0.12, 0.12)
        # High switch rate = choppy market = reduce conviction
        chop_penalty = clamp((dir_switch_rate - 0.5) * 0.08, 0.0, 0.08)

        # ── Volume surge: high volume confirms directional move ──
        vol_surge = features.get("tick_vol_surge_ratio", 0.0)
        vol_boost = 0.0
        if vol_surge > 0.1 and velocity != 0:
            # Volume surge + directional velocity = strong confirmation
            aligned = (velocity > 0) == (direction is Direction.LONG)
            vol_boost = clamp(vol_surge * 0.08 * (1.0 if aligned else -1.0), -0.08, 0.08)

        # ── Tick frequency: high activity often precedes volatility ──
        activity_regime = features.get("tick_activity_regime", 0.5)
        freq_z = features.get("tick_freq_z_score", 0.0)
        # Unusually high frequency + directional velocity = strong signal
        freq_boost = 0.0
        if abs(freq_z) > 1.5 and velocity != 0:
            freq_direction = 1.0 if (velocity > 0) == (direction is Direction.LONG) else -1.0
            freq_boost = clamp(freq_z * 0.04 * freq_direction, -0.06, 0.06)
        # Very low frequency = quiet market, reduce conviction slightly
        quiet_penalty = 0.0
        if activity_regime < 0.2:
            quiet_penalty = (0.2 - activity_regime) * 0.08

        raw = (
            0.50
            + velocity_score
            + accel_score
            + impulse_score
            + streak_score
            + ratio_score
            - exhaustion_penalty
            - spread_penalty
            + dir_streak_score
            - chop_penalty
            + vol_boost
            + freq_boost
            - quiet_penalty
        )

        return clamp(raw, 0.0, 1.0)

    def _garch_mr_component(self, direction: Direction, features: dict[str, float]) -> float:
        """GARCH mean-reversion component.

        When the EGARCH model detects an extreme z-score (large price move
        relative to forecast vol), it signals that the generator's variance
        scheduling will pull vol back.  This component scores the direction
        that aligns with this mean-reversion expectation.

        On synthetic indices, extreme moves ARE followed by reversion because
        the generator's GARCH-like variance scheduling is the one exploitable
        property.
        """
        garch_z = features.get("garch_z_score", 0.0)
        garch_mr_signal = features.get("garch_mean_revert_signal", 0.0)
        garch_sigma = features.get("garch_sigma", 0.0)

        if garch_sigma <= 0 or garch_mr_signal <= 0:
            return 0.50  # neutral — no mean-reversion signal

        abs_z = abs(garch_z)

        if abs_z < 1.5:
            return 0.50  # not extreme enough for reversion

        # Score based on whether direction aligns with mean-reversion
        # Mean-reversion says: after a big UP move (z>0), expect DOWN
        #                     after a big DOWN move (z<0), expect UP
        if direction is Direction.LONG and garch_z < -1.5:
            # Aligned: big down move + long = reversion play
            base = 0.50 + garch_mr_signal * 0.30  # up to 0.80
            # Extra boost for very extreme z-scores
            if abs_z > 3.0:
                base = clamp(base + 0.05, 0.50, 0.85)
            return base
        elif direction is Direction.SHORT and garch_z > 1.5:
            # Aligned: big up move + short = reversion play
            base = 0.50 + garch_mr_signal * 0.30
            if abs_z > 3.0:
                base = clamp(base + 0.05, 0.50, 0.85)
            return base
        else:
            # Opposed: direction doesn't align with reversion
            # Penalize slightly — this is a trend-continuation bet during extreme vol
            return clamp(0.50 - garch_mr_signal * 0.10, 0.35, 0.50)

    def _garch_component(self, direction: Direction, features: dict[str, float]) -> float:
        """GARCH variance forecast component — the NEW statistical component.

        This component uses the EGARCH(1,1) one-step-ahead variance forecast
        to score directional confidence.  On synthetic indices, the generator's
        variance scheduling IS predictable — high vol clusters, low vol clusters.

        The component scores:
        1. Vol regime alignment (high vol = trade with caution, low vol = prepare)
        2. Mean-reversion signal (when GARCH detects extreme vol, bet on reversion)
        3. Persistence (high persistence = regime will last, low = rapid change)
        """
        garch_sigma = features.get("garch_sigma", 0.0)
        garch_persistence = features.get("garch_persistence", 0.9)
        garch_vol_regime = features.get("garch_vol_regime", 1.0)
        garch_z = features.get("garch_z_score", 0.0)
        atr_14 = features.get("atr_14", 1.0)

        if garch_sigma <= 0 or atr_14 <= 0:
            return 0.50  # neutral during warmup

        # Base score: volatility regime
        if garch_vol_regime == 0.0:  # low vol
            base = 0.55  # slightly bullish — compression often precedes expansion
        elif garch_vol_regime == 2.0:  # high vol
            base = 0.35  # cautious — extreme vol = unpredictable direction
        else:  # normal
            base = 0.50

        # Persistence adjustment: high persistence = current vol regime will last
        if garch_persistence > 0.95:
            if garch_vol_regime == 0.0:
                base = clamp(base + 0.03, 0.30, 0.80)  # low vol persists = calm trading
            elif garch_vol_regime == 2.0:
                base = clamp(base - 0.03, 0.30, 0.80)  # high vol persists = stay cautious

        # Z-score extremity: very large |z| means the generator's variance
        # scheduling will pull vol back — slight boost for any direction
        # (the actual directional mean-reversion is in _garch_mr_component)
        abs_z = abs(garch_z)
        if abs_z > 3.0:
            base = clamp(base + 0.03, 0.30, 0.80)

        return base

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

    # ── Disk persistence ──────────────────────────────────────────
    # Saves model weights + calibration buffer to JSON so learning
    # survives Python process restarts.  RegimeShiftDetector and
    # VolatilityHarvester are intentionally NOT persisted — they are
    # transient state that rebuilds naturally from live data.

    def save_state(self, path: str | Path) -> None:
        """Persist model weights and calibration buffer to disk."""
        # Compute quality metrics for versioning
        brier = self.calibration.brier_score()
        accuracy = self.calibration.directional_accuracy()
        state = {
            "model": {
                "config": asdict(self.model.config),
                "weights": self.model.weights,
                "bias": self.model.bias,
                "updates": self.model.updates,
                "metadata": self.model.metadata,
            },
            "calibration": {
                "predictions": self.calibration.predictions,
                "outcomes": self.calibration.outcomes,
            },
            "trading_mode": self._trading_mode,
            "versioning": {
                "save_count": getattr(self, "_save_count", 0) + 1,
                "calibration_samples": len(self.calibration.predictions),
                "brier_score": brier,
                "directional_accuracy": accuracy,
            },
        }
        self._save_count = getattr(self, "_save_count", 0) + 1
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp then rename to prevent corruption
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(target)

    def load_state(self, path: str | Path) -> bool:
        """Load model weights and calibration buffer from disk.

        After loading, validates the model quality by computing Brier score.
        If the loaded model performs worse than a fresh baseline model
        (Brier > 0.25 on its own calibration buffer), automatically
        resets to default weights and clears calibration to prevent
        a degraded model from being used.

        Returns True if state was loaded and validated successfully,
        False if the file doesn't exist, is corrupt, or was rolled back.
        """
        target = Path(path)
        if not target.exists():
            return False
        try:
            state = json.loads(target.read_text(encoding="utf-8"))
            # Restore model
            m = state["model"]
            saved_weights = {str(k): float(v) for k, v in m["weights"].items()}
            saved_bias = float(m["bias"])
            saved_updates = int(m["updates"])
            saved_metadata = {str(k): str(v) for k, v in m.get("metadata", {}).items()}
            self.model.weights = saved_weights
            self.model.bias = saved_bias
            self.model.updates = saved_updates
            self.model.metadata = saved_metadata
            # Restore calibration
            cal = state.get("calibration", {})
            saved_predictions = [float(p) for p in cal.get("predictions", [])]
            saved_outcomes = [int(o) for o in cal.get("outcomes", [])]
            self.calibration.predictions = saved_predictions
            self.calibration.outcomes = saved_outcomes
            # Prune oversized buffers loaded from disk (pre-v5 state files)
            self.calibration._prune()
            # Invalidate cached calibration models so they re-fit
            self.calibration._fitted_ir = None
            self.calibration._fitted_platt = None
            self.calibration._fitted_ir_version = 0
            self.calibration._fitted_platt_version = 0
            self._trading_mode = state.get("trading_mode", "intraday")

            # ── Quality validation ──────────────────────────────────
            # Compute Brier score on the loaded calibration buffer.
            # If it exceeds the maximum acceptable threshold (0.25 = coin-flip),
            # the model has degenerated and should be rolled back to fresh weights.
            MAX_ACCEPTABLE_BRIER = 0.25
            loaded_versioning = state.get("versioning", {})
            brier = self.calibration.brier_score()
            accuracy = self.calibration.directional_accuracy()
            save_count = loaded_versioning.get("save_count", 0)

            if brier is not None and brier > MAX_ACCEPTABLE_BRIER:
                # Model has degenerated — reset to fresh weights
                fresh_model = OnlineLogisticModel(self.config.model)
                self.model.weights = fresh_model.weights
                self.model.bias = fresh_model.bias
                self.model.updates = 0
                self.model.metadata = {}
                self.calibration.predictions = []
                self.calibration.outcomes = []
                self.calibration._fitted_ir = None
                self.calibration._fitted_platt = None
                self.calibration._fitted_ir_version = 0
                self.calibration._fitted_platt_version = 0
                self._save_count = 0
                logging.warning(
                    "[DecisionEngine] ROLLED BACK model for %s: "
                    "Brier score %.4f > %.4f threshold (was %d samples, "
                    "accuracy=%.3f, save #%d)",
                    path, brier, MAX_ACCEPTABLE_BRIER,
                    len(saved_predictions), accuracy or 0.0, save_count,
                )
                return False

            self._save_count = save_count
            logging.info(
                "[DecisionEngine] loaded state: model_updates=%d, "
                "calibration_samples=%d, brier=%.4f, accuracy=%s, save #%d",
                saved_updates, len(saved_predictions),
                brier if brier is not None else -1.0,
                f"{accuracy:.3f}" if accuracy is not None else "N/A",
                save_count,
            )
            return True
        except Exception as e:
            logging.warning("[DecisionEngine] failed to load state from %s: %s", path, e)
            return False

    def explain_signal(self, signal: TradeSignal) -> dict[str, object]:
        features = dict(signal.snapshot.features)
        return {
            "direction": signal.direction.value,
            "confidence": signal.confidence,
            "position_scale": signal.position_scale,
            "position_sizing": signal.position_sizing,
            "model_probability": signal.snapshot.features.get("model_long_probability", 0.5),
            "regime": signal.snapshot.regime.value,
            "regime_shift": {
                "hmm_state": MarketState(int(features.get("regime_hmm_state", 1))).name,
                "position_scale": features.get("regime_position_scale", 1.0),
                "alerts": [k for k in features if k.startswith("regime_alert_")],
            },
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
