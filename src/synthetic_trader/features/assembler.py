from __future__ import annotations

from synthetic_trader.domain import Candle, Regime, Tick, FeatureSnapshot
from synthetic_trader.features.market_structure import market_structure_features
from synthetic_trader.features.smc_enhanced import smc_features
from synthetic_trader.features.regimes import classify_regime
from synthetic_trader.features.tick_integration import compute_tick_flow_features
from synthetic_trader.features.arch_garch import ArchGarchForecaster
from synthetic_trader.models.garch_calibration import load_calibrated_garch_state
from synthetic_trader.features.session_filter import SessionVolatilityFilter
from synthetic_trader.features.generator_fingerprint import GeneratorFingerprintDetector
import time as _time


# Module-level GARCH forecasters — one per symbol to maintain state across snapshots.
_garch_forecasters: dict[str, ArchGarchForecaster] = {}
# Tracks whether each symbol's forecaster was initialized from a
# market-calibrated calibration file (True) or from defaults (False).
_garch_calibrated: dict[str, bool] = {}
_session_filters: dict[str, SessionVolatilityFilter] = {}
_fingerprint_detectors: dict[str, GeneratorFingerprintDetector] = {}


def clear_assembler_caches() -> None:
    """Clear all module-level caches (GARCH, session filter, fingerprint).

    Call this in test fixtures or when starting a fresh analysis session to
    prevent stale state from previous runs leaking into new results.
    """
    _garch_forecasters.clear()
    _garch_calibrated.clear()
    _session_filters.clear()
    _fingerprint_detectors.clear()


def _get_garch_forecaster(symbol: str) -> ArchGarchForecaster:
    """Get or create the GARCH forecaster for a symbol.

    On first access, checks for a calibrated calibration file at
    ``data/garch_calibration/{symbol}.json``.  If one exists and
    converged during MLE fitting, the forecaster is initialized with
    those market-calibrated parameters instead of the generic defaults.
    This means the online forecaster starts with priors that reflect
    actual Deriv synthetic index behavior.

    The arch library's ArchGarchForecaster provides:
    - EWMA online volatility (fast, no dependencies)
    - Periodic arch model fitting every 100 observations (MLE validation)
    - Proper persistence and long-run variance estimation
    - Z-score and mean reversion signal computation
    """
    if symbol not in _garch_forecasters:
        calibrated_state = load_calibrated_garch_state(symbol)
        if calibrated_state is not None:
            # Initialize forecaster with calibrated parameters.
            # Convert GARCHState to ArchGarchForecaster parameters.
            forecaster = ArchGarchForecaster(
                long_run_var_prior=calibrated_state.long_run_variance,
                min_observations=10,  # Start fitting sooner with calibrated priors
            )
            # Initialize the online state with calibrated persistence
            forecaster.state.persistence = calibrated_state.persistence
            forecaster.state.long_run_variance = calibrated_state.long_run_variance
            _garch_forecasters[symbol] = forecaster
            _garch_calibrated[symbol] = True
        else:
            _garch_forecasters[symbol] = ArchGarchForecaster()
            _garch_calibrated[symbol] = False
    return _garch_forecasters[symbol]


def build_snapshot(
    symbol: str,
    timeframe_sec: int,
    candles: list[Candle],
    higher_timeframe_candles: list[Candle] | None = None,
    extra_timeframes: dict[str, list[Candle]] | None = None,
    ticks: list[Tick] | None = None,
) -> FeatureSnapshot:
    regime, base_features, regime_notes = classify_regime(candles)
    structure = market_structure_features(candles)
    features = dict(base_features)
    features.update(structure)

    # ── SMC institutional features ──────────────────────────────
    # Bring smart-money-concepts intelligence into the feature vector.
    # These complement the basic structure features with institutional-
    # grade FVG, BOS/CHoCH, Order Blocks, and Liquidity analysis.
    try:
        smc_feats = smc_features(candles)
        features.update(smc_feats)
    except Exception:
        pass  # SMC features are supplementary — never crash the pipeline

    # ── EGARCH variance forecast ──────────────────────────────────
    # Feed the latest log-return into the EGARCH forecaster to get
    # a one-step-ahead variance prediction.  This is the ONE genuinely
    # exploitable property of synthetic indices — their volatility
    # clusters due to the generator's variance scheduling.
    garch = _get_garch_forecaster(symbol)
    # Flag whether the forecaster was initialized from a market-calibrated
    # calibration file (True) or from generic defaults (False).
    features["garch_calibrated"] = 1.0 if _garch_calibrated.get(symbol, False) else 0.0
    log_return = features.get("log_return", 0.0)
    if log_return != 0.0:
        # NOTE: no `observations > 0` guard here — that guard froze the
        # forecaster at observation 0 (the FIRST update was never allowed,
        # so observations never grew and garch_z_score stayed 0.0 forever
        # in every process, since caches are cleared per run).  update()
        # handles warm-up internally (return buffer + min_observations for
        # the arch fit), so feeding from observation 1 is safe and makes
        # garch_z_score / garch_vol_ratio real features again.
        garch_features = garch.update(log_return)
    else:
        garch_features = garch.get_forecast()
    features.update(garch_features)

    notes = list(regime_notes)
    if higher_timeframe_candles:
        higher_regime, higher_features, higher_notes = classify_regime(higher_timeframe_candles)
        higher_structure = market_structure_features(higher_timeframe_candles)
        features.update({f"htf_{key}": value for key, value in higher_features.items()})
        features.update({f"htf_{key}": value for key, value in higher_structure.items()})
        # When higher TF regime is UNKNOWN (insufficient candles), inherit
        # from primary — or fall back to RANGE if primary is also UNKNOWN.
        effective_htf_regime = higher_regime if higher_regime != Regime.UNKNOWN else regime
        if effective_htf_regime == Regime.UNKNOWN:
            effective_htf_regime = Regime.RANGE
        features[f"htf_regime_{effective_htf_regime.value}"] = 1.0
        features[f"htf_regime_unknown"] = 0.0
        # Regime confidence: 1.0 = own candles, 0.5 = inherited from parent, 0.25 = RANGE fallback
        if higher_regime != Regime.UNKNOWN and len(higher_timeframe_candles) >= 5:
            features["htf_regime_confidence"] = 1.0
        elif higher_regime != Regime.UNKNOWN:
            features["htf_regime_confidence"] = 0.75  # own candles but < 5
        elif regime != Regime.UNKNOWN:
            features["htf_regime_confidence"] = 0.5   # inherited from primary
        else:
            features["htf_regime_confidence"] = 0.25  # RANGE fallback
        notes.extend(f"HTF {note}" for note in higher_notes)

    if extra_timeframes:
        for prefix, timeframe_candles in extra_timeframes.items():
            # Determine effective regime for this extra timeframe.
            # When the higher TF has no candles or insufficient candles,
            # inherit the parent timeframe's regime.  If the parent is also
            # UNKNOWN (primary has < 5 candles), fall back to RANGE — the
            # safest actionable assumption.  This prevents the frontend
            # from ever showing "unknown" in the 4H/1H/15M panels.
            if not timeframe_candles:
                effective_regime = regime if regime != Regime.UNKNOWN else Regime.RANGE
                features[f"{prefix}_regime_{effective_regime.value}"] = 1.0
                features[f"{prefix}_regime_unknown"] = 0.0
                notes.append(f"{prefix.upper()} regime set to {effective_regime.value} (no candles yet)")
                continue
            extra_regime, extra_features, extra_notes = classify_regime(timeframe_candles)
            extra_structure = market_structure_features(timeframe_candles)
            features.update({f"{prefix}_{key}": value for key, value in extra_features.items()})
            features.update({f"{prefix}_{key}": value for key, value in extra_structure.items()})
            # When the regime classifier returns UNKNOWN (too few candles),
            # inherit the parent timeframe's regime.  If parent is also UNKNOWN,
            # fall back to RANGE as the safest actionable default.
            effective_regime = extra_regime if extra_regime != Regime.UNKNOWN else regime  # type: ignore[assignment]
            if effective_regime == Regime.UNKNOWN:
                effective_regime = Regime.RANGE
            features[f"{prefix}_regime_{effective_regime.value}"] = 1.0
            features[f"{prefix}_regime_unknown"] = 0.0
            # Regime confidence: 1.0 = own candles, 0.5 = inherited from parent, 0.25 = RANGE fallback
            if extra_regime != Regime.UNKNOWN and len(timeframe_candles) >= 5:
                features[f"{prefix}regime_confidence"] = 1.0
            elif extra_regime != Regime.UNKNOWN:
                features[f"{prefix}regime_confidence"] = 0.75  # own candles but < 5
            elif regime != Regime.UNKNOWN:
                features[f"{prefix}regime_confidence"] = 0.5   # inherited from primary
            else:
                features[f"{prefix}regime_confidence"] = 0.25  # RANGE fallback
            if extra_regime == Regime.UNKNOWN:
                notes.append(f"{prefix.upper()} regime set to {effective_regime.value} (inherited — {len(timeframe_candles)} candles insufficient)")
            else:
                notes.extend(f"{prefix.upper()} {note}" for note in extra_notes)

    # ── Session volatility filter ────────────────────────────────
    # Track which hours produce the most volatile moves on each index.
    # The generator's server load balancing creates time-dependent behavior.
    if symbol not in _session_filters:
        _session_filters[symbol] = SessionVolatilityFilter()
    sf = _session_filters[symbol]
    # Extract UTC hour — gmtime().tm_hour gives 0-23, not epoch % 24
    current_hour = _time.gmtime().tm_hour  # 0-23 UTC
    if log_return != 0.0:
        session_features = sf.update(current_hour, log_return)
        features.update(session_features)

    # ── Generator fingerprint detection ──────────────────────────
    # Detect which index is being traded by analyzing return statistics.
    if symbol not in _fingerprint_detectors:
        _fingerprint_detectors[symbol] = GeneratorFingerprintDetector()
    fp = _fingerprint_detectors[symbol]
    if log_return != 0.0:
        fingerprint_features = fp.update(log_return)
        features.update(fingerprint_features)

    # ── Tick-level features ───────────────────────────────────────
    # Feed raw ticks into TickFlowEngine to capture micro-structure
    # dynamics (velocity, acceleration, impulse/retrace, exhaustion)
    # that candle-derived features miss.
    if ticks:
        tick_features = compute_tick_flow_features(ticks)
        features.update(tick_features)
        if any(v != 0.0 for k, v in tick_features.items() if k != "tick_total"):
            notes.append(f"tick_flow: vel={tick_features.get('tick_velocity', 0):.4f} accel={tick_features.get('tick_acceleration', 0):.4f}")

    # Primary timeframe regime confidence: 1.0 if >=5 candles, 0.75 if <5
    features["regime_confidence"] = 1.0 if len(candles) >= 5 else 0.75

    # Primary timeframe regime confidence: 1.0 if >=5 candles, 0.75 if <5
    features["regime_confidence"] = 1.0 if len(candles) >= 5 else 0.75

    epoch = candles[-1].open_time + timeframe_sec if candles else 0.0
    return FeatureSnapshot(
        symbol=symbol,
        epoch=epoch,
        timeframe_sec=timeframe_sec,
        features=features,
        regime=regime,
        structure=structure,
        notes=tuple(notes),
    )
