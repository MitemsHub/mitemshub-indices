"""Diagnose exactly which gate blocks signal generation."""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from synthetic_trader.config import TraderConfig
from synthetic_trader.live.market_snapshot import (
    _load_csv_ticks,
    TRADING_MODE_PRESETS,
    build_mode_config,
)
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.strategy.decision_engine import DecisionEngine
from synthetic_trader.strategy.setup_builder import classify_setup
from synthetic_trader.strategy.confirmation_builder import confirm_setup
from synthetic_trader.strategy.top_down_bias import infer_top_down_bias


def diagnose(symbol: str, trading_mode: str):
    print(f"\n{'='*70}")
    print(f"DIAGNOSIS: {symbol} ({trading_mode})")
    print(f"{'='*70}")

    preset = TRADING_MODE_PRESETS[trading_mode]
    config = build_mode_config(TraderConfig.default(), preset)
    profile = config.symbols[symbol]

    print(f"\n  Config:")
    print(f"    min_history_candles: {profile.min_history_candles}")
    print(f"    min_confidence (risk): {config.risk.min_confidence}")
    print(f"    confidence_relaxation: {profile.confidence_relaxation}")
    print(f"    effective min_confidence: {max(0.0, config.risk.min_confidence - profile.confidence_relaxation):.3f}")
    print(f"    execution_timeframe_sec: {profile.execution_timeframe_sec}")
    print(f"    bias_timeframe_sec: {profile.bias_timeframe_sec}")
    print(f"    setup_timeframe_sec: {profile.setup_timeframe_sec}")
    print(f"    confirmation_timeframe_sec: {profile.confirmation_timeframe_sec}")

    # Load ticks
    ticks = _load_csv_ticks(symbol) or []
    print(f"\n  CSV ticks loaded: {len(ticks)}")
    if not ticks:
        print("  BLOCKED: No CSV data!")
        return
    print(f"  First tick epoch: {ticks[0].epoch}")
    print(f"  Last tick epoch: {ticks[-1].epoch}")
    span_hours = (ticks[-1].epoch - ticks[0].epoch) / 3600
    print(f"  Time span: {span_hours:.1f} hours")

    # Build candles for all role timeframes
    role_timeframes = {
        "bias": profile.bias_timeframe_sec,
        "setup": profile.setup_timeframe_sec,
        "confirmation": profile.confirmation_timeframe_sec,
        "execution": profile.execution_timeframe_sec,
    }
    all_tfs = sorted(set([*role_timeframes.values()]))
    builder = MultiTimeframeCandleBuilder(symbol, all_tfs)
    histories = {tf: [] for tf in all_tfs}

    for tick in ticks:
        closed = builder.update(tick)
        for tf, candle in closed.items():
            histories.setdefault(tf, []).append(candle)
    flushed = builder.flush()
    for tf, candle in flushed.items():
        histories.setdefault(tf, []).append(candle)

    role_candles = {
        role: histories.get(role_timeframe, [])
        for role, role_timeframe in role_timeframes.items()
    }

    print(f"\n  Candle counts per role:")
    for role, tf in role_timeframes.items():
        count = len(role_candles[role])
        status = "OK" if count >= profile.min_history_candles else "BLOCKED"
        print(f"    {role:15s} (tf={tf:5d}s): {count:5d} candles  {status}")

    execution_candles = role_candles["execution"]
    setup_candles = role_candles["setup"]
    confirmation_candles = role_candles["confirmation"]
    bias_candles = role_candles["bias"]

    # Gate 1: min_history_candles
    if len(execution_candles) < profile.min_history_candles:
        print(f"\n  *** BLOCKED at Gate 1: need {profile.min_history_candles} execution candles, have {len(execution_candles)} ***")
        return

    print(f"\n  [OK] Gate 1 passed: {len(execution_candles)} execution candles >= {profile.min_history_candles}")

    # Build features
    if not execution_candles:
        print("  BLOCKED: No execution candles")
        return

    snapshot = build_snapshot(
        symbol=symbol,
        timeframe_sec=profile.execution_timeframe_sec,
        candles=execution_candles,
        higher_timeframe_candles=confirmation_candles,
        extra_timeframes={
            "bias": bias_candles,
            "setup": setup_candles,
            "confirmation": confirmation_candles,
            "execution": execution_candles,
        },
    )
    features = dict(snapshot.features)
    print(f"\n  Features built. Regime: {snapshot.regime.value}")

    engine = DecisionEngine(config)
    model_long_prob = engine.model.predict_proba(features)
    print(f"  Model long probability: {model_long_prob:.4f}")

    calibrated_prob = engine.calibration.calibrate(model_long_prob)
    print(f"  Calibrated probability: {calibrated_prob:.4f}")

    # Score directions
    long_score = engine._score_direction(
        __import__('synthetic_trader.domain', fromlist=['Direction']).Direction.LONG,
        snapshot.regime, features, calibrated_prob,
    )
    short_score = engine._score_direction(
        __import__('synthetic_trader.domain', fromlist=['Direction']).Direction.SHORT,
        snapshot.regime, features, calibrated_prob,
    )
    print(f"  Long score: {long_score:.4f}")
    print(f"  Short score: {short_score:.4f}")

    # Check bias and setup
    bias = infer_top_down_bias(
        symbol=symbol,
        bias_candles=bias_candles,
        setup_candles=setup_candles,
        confirmation_candles=confirmation_candles,
        execution_candles=execution_candles,
    )
    print(f"\n  Bias: direction={bias.direction}, reason={bias.reason[:100]}")
    print(f"    invalidation_price={bias.invalidation_price}")

    setup = classify_setup(bias=bias, setup_candles=setup_candles)
    print(f"  Setup: state={setup.state}, trade_direction={setup.trade_direction}")
    print(f"    reason={setup.reason[:100]}")

    confirmation = confirm_setup(setup=setup, confirmation_candles=confirmation_candles[-30:])
    print(f"  Confirmation: state={confirmation.state}")
    print(f"    reason={confirmation.reason[:100]}")

    # Determine direction and confidence
    from synthetic_trader.domain import Direction
    direction = Direction.LONG if setup.trade_direction == "buy" else Direction.SHORT
    confidence = long_score if direction is Direction.LONG else short_score

    if setup.state != "none" and confirmation.state in {"confirmed", "actionable"}:
        confidence = max(confidence, profile.confirmed_setup_confidence_floor)

    min_confidence = max(0.0, config.risk.min_confidence - profile.confidence_relaxation)

    print(f"\n  Direction: {direction.value}")
    print(f"  Confidence: {confidence:.4f}")
    print(f"  Min confidence: {min_confidence:.4f}")

    # Gate 2: confidence threshold
    if confidence < min_confidence:
        print(f"\n  *** BLOCKED at Gate 2: confidence {confidence:.4f} < min_confidence {min_confidence:.4f} ***")
        return
    print(f"  [OK] Gate 2 passed: confidence {confidence:.4f} >= min_confidence {min_confidence:.4f}")

    # Gate 3: formal setup OR strong confidence
    has_formal_setup = setup.state != "none" and confirmation.state in {"confirmed", "actionable"}
    has_strong_confidence = confidence >= 0.52
    print(f"\n  has_formal_setup: {has_formal_setup} (setup={setup.state}, confirmation={confirmation.state})")
    print(f"  has_strong_confidence: {has_strong_confidence} (confidence={confidence:.4f} >= 0.52)")

    if not has_formal_setup and not has_strong_confidence:
        print(f"\n  *** BLOCKED at Gate 3: neither formal setup nor strong confidence ***")
        return
    print(f"  [OK] Gate 3 passed")
    print(f"\n  *** ALL GATES PASSED -- Signal should be generated! ***")


if __name__ == "__main__":
    for symbol in ["R_100", "R_75"]:
        for mode in ["sniper", "active_trader"]:
            diagnose(symbol, mode)
