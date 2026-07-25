# Top-Down Structure Inference Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current short-horizon `1m/5m` close-anchored trade engine with a higher-timeframe-led structure engine for `R_75` and `R_100` that derives bias from `4H`, setup from `1H`, confirmation from `15m`, and execution from `5m`.

**Architecture:** Add a dedicated top-down decision pipeline instead of continuing to overload the current scorer. The new path builds a multi-timeframe market map, infers higher-timeframe bias, qualifies `1H` setups, confirms them on `15m`, and only then builds a `5m` execution plan with structure-led entry, invalidation, and targets. The existing live snapshot and bridge layers keep their current contracts where possible, but the payload content becomes structure-led instead of latest-close-led.

**Tech Stack:** Python 3.13, pytest, existing `synthetic_trader` feature/strategy/live modules, TypeScript Next.js bridge tests with Vitest only where payload/contract behavior changes.

---

## File Map

**Create**
- `src/synthetic_trader/features/multi_timeframe_structure.py` - Shared helpers for extracting structural zones, liquidity shelves, and directional maps across `4H`, `1H`, `15m`, and `5m`.
- `src/synthetic_trader/strategy/top_down_bias.py` - Higher-timeframe bias builder from `4H` and `1H`.
- `src/synthetic_trader/strategy/setup_builder.py` - `1H` setup classification aligned to higher-timeframe bias.
- `src/synthetic_trader/strategy/confirmation_builder.py` - `15m` confirmation rules.
- `tests/test_multi_timeframe_structure.py` - Unit tests for structural zone extraction and liquidity maps.
- `tests/test_top_down_bias.py` - Unit tests for `4H`/`1H` bias inference.
- `tests/test_setup_builder.py` - Unit tests for setup classification.
- `tests/test_confirmation_builder.py` - Unit tests for `15m` confirmation gating.

**Modify**
- `src/synthetic_trader/config.py` - Add explicit multi-timeframe configuration and longer hold-horizon defaults.
- `src/synthetic_trader/features/assembler.py` - Build and return multi-timeframe feature packages instead of only base + one higher timeframe.
- `src/synthetic_trader/strategy/decision_engine.py` - Replace latest-close trade construction with top-down structure plan generation.
- `src/synthetic_trader/live/market_snapshot.py` - Surface new rationale, invalidation, multi-target, and hold-horizon details in live output.
- `src/synthetic_trader/live/signal_guardian.py` - Keep the existing lifecycle, but guard a structure-led plan rather than a tiny local move.
- `tests/test_decision_engine.py` - Replace short-horizon assertions with top-down structure assertions.
- `tests/test_live_market_snapshot.py` - Update runtime snapshot expectations for structure-led plans.
- `external/mitemshub-indices/src/lib/contracts.ts` - Extend live payload contract if new plan fields are added.
- `external/mitemshub-indices/src/lib/engine-bridge.ts` - Normalize new structure-led payload fields if needed.
- `external/mitemshub-indices/tests/contracts.test.ts` - Contract coverage for the richer payload.
- `external/mitemshub-indices/tests/engine-bridge.test.ts` - Ensure new fields survive the bridge.

## Task 1: Add Multi-Timeframe Configuration

**Files:**
- Modify: `src/synthetic_trader/config.py`
- Test: `tests/test_top_down_bias.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.config import TraderConfig


def test_default_symbol_profile_exposes_top_down_timeframes() -> None:
    config = TraderConfig.default()
    r75 = config.symbols["R_75"]

    assert r75.bias_timeframe_sec == 14_400
    assert r75.setup_timeframe_sec == 3_600
    assert r75.confirmation_timeframe_sec == 900
    assert r75.execution_timeframe_sec == 300
    assert r75.monitoring_timeframe_sec == 60
    assert r75.hold_bars_bias >= 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_top_down_bias.py::test_default_symbol_profile_exposes_top_down_timeframes -q`
Expected: FAIL with `AttributeError` for missing timeframe fields on `SymbolProfile`.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class SymbolProfile:
    symbol: str
    display_name: str
    pip_size: float
    default_timeframe_sec: int = 60
    higher_timeframe_sec: int = 300
    stop_atr_multiple: float = 1.25
    take_profit_rr: float = 1.8
    min_history_candles: int = 80
    confidence_relaxation: float = 0.0
    bias_timeframe_sec: int = 14_400
    setup_timeframe_sec: int = 3_600
    confirmation_timeframe_sec: int = 900
    execution_timeframe_sec: int = 300
    monitoring_timeframe_sec: int = 60
    hold_bars_bias: int = 6
    hold_bars_setup: int = 8
```

```python
"R_75": SymbolProfile(
    symbol="R_75",
    display_name="Volatility 75 Index",
    pip_size=0.01,
    stop_atr_multiple=1.35,
    take_profit_rr=1.9,
    confidence_relaxation=0.08,
    bias_timeframe_sec=14_400,
    setup_timeframe_sec=3_600,
    confirmation_timeframe_sec=900,
    execution_timeframe_sec=300,
    monitoring_timeframe_sec=60,
    hold_bars_bias=6,
    hold_bars_setup=10,
),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_top_down_bias.py::test_default_symbol_profile_exposes_top_down_timeframes -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/config.py tests/test_top_down_bias.py
git commit -m "feat: add top-down timeframe config"
```

## Task 2: Add Shared Multi-Timeframe Structure Extraction

**Files:**
- Create: `src/synthetic_trader/features/multi_timeframe_structure.py`
- Test: `tests/test_multi_timeframe_structure.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.features.multi_timeframe_structure import build_structure_map
from tests.test_decision_engine import trending_candles


def test_build_structure_map_extracts_bias_and_invalidation_zones() -> None:
    structure = build_structure_map(
        bias_candles=trending_candles(symbol="R_75", count=120),
        setup_candles=trending_candles(symbol="R_75", count=90),
        confirmation_candles=trending_candles(symbol="R_75", count=60),
        execution_candles=trending_candles(symbol="R_75", count=40),
    )

    assert structure.bias_direction == "bullish"
    assert structure.bias_zone_low is not None
    assert structure.bias_zone_high is not None
    assert structure.invalidation_price is not None
    assert structure.target_one is not None
    assert structure.target_extended is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_multi_timeframe_structure.py::test_build_structure_map_extracts_bias_and_invalidation_zones -q`
Expected: FAIL with `ModuleNotFoundError` for `multi_timeframe_structure`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.features.market_structure import detect_swings


@dataclass(frozen=True)
class StructureMap:
    bias_direction: str
    bias_zone_low: float | None
    bias_zone_high: float | None
    invalidation_price: float | None
    target_one: float | None
    target_extended: float | None


def _latest_swing(candles: list[Candle], kind: str) -> float | None:
    swings = [swing for swing in detect_swings(candles, left=2, right=2) if swing.kind == kind]
    return swings[-1].price if swings else None


def build_structure_map(
    *,
    bias_candles: list[Candle],
    setup_candles: list[Candle],
    confirmation_candles: list[Candle],
    execution_candles: list[Candle],
) -> StructureMap:
    bias_high = _latest_swing(bias_candles, "high")
    bias_low = _latest_swing(bias_candles, "low")
    setup_close = setup_candles[-1].close
    bias_direction = "bullish" if setup_close >= setup_candles[0].close else "bearish"

    if bias_direction == "bullish":
        invalidation = bias_low
        target_one = bias_high
        target_extended = max(candle.high for candle in bias_candles[-20:])
    else:
        invalidation = bias_high
        target_one = bias_low
        target_extended = min(candle.low for candle in bias_candles[-20:])

    return StructureMap(
        bias_direction=bias_direction,
        bias_zone_low=min(candle.low for candle in setup_candles[-10:]),
        bias_zone_high=max(candle.high for candle in setup_candles[-10:]),
        invalidation_price=invalidation,
        target_one=target_one,
        target_extended=target_extended,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_multi_timeframe_structure.py::test_build_structure_map_extracts_bias_and_invalidation_zones -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/features/multi_timeframe_structure.py tests/test_multi_timeframe_structure.py
git commit -m "feat: add shared multi-timeframe structure map"
```

## Task 3: Build Higher-Timeframe Bias Inference

**Files:**
- Create: `src/synthetic_trader/strategy/top_down_bias.py`
- Test: `tests/test_top_down_bias.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.strategy.top_down_bias import infer_top_down_bias
from tests.test_decision_engine import trending_candles


def test_infer_top_down_bias_prefers_higher_timeframe_structure() -> None:
    bias = infer_top_down_bias(
        symbol="R_75",
        bias_candles=trending_candles(symbol="R_75", count=150),
        setup_candles=trending_candles(symbol="R_75", count=100),
    )

    assert bias.direction == "bullish"
    assert "4h" in bias.reason.lower()
    assert bias.invalidation_price is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_top_down_bias.py::test_infer_top_down_bias_prefers_higher_timeframe_structure -q`
Expected: FAIL with `ModuleNotFoundError` for `top_down_bias`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.features.multi_timeframe_structure import build_structure_map


@dataclass(frozen=True)
class TopDownBias:
    direction: str
    reason: str
    invalidation_price: float | None


def infer_top_down_bias(
    *,
    symbol: str,
    bias_candles: list[Candle],
    setup_candles: list[Candle],
) -> TopDownBias:
    structure = build_structure_map(
        bias_candles=bias_candles,
        setup_candles=setup_candles,
        confirmation_candles=setup_candles,
        execution_candles=setup_candles,
    )
    return TopDownBias(
        direction=structure.bias_direction,
        reason=f"4H structure is {structure.bias_direction}",
        invalidation_price=structure.invalidation_price,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_top_down_bias.py::test_infer_top_down_bias_prefers_higher_timeframe_structure -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/top_down_bias.py tests/test_top_down_bias.py src/synthetic_trader/features/multi_timeframe_structure.py
git commit -m "feat: add higher-timeframe bias inference"
```

## Task 4: Build 1H Setup Classification

**Files:**
- Create: `src/synthetic_trader/strategy/setup_builder.py`
- Test: `tests/test_setup_builder.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.strategy.setup_builder import classify_setup
from synthetic_trader.strategy.top_down_bias import TopDownBias
from tests.test_decision_engine import trending_candles


def test_classify_setup_marks_pullback_continuation_when_bias_and_setup_align() -> None:
    setup = classify_setup(
        bias=TopDownBias(direction="bullish", reason="4H structure is bullish", invalidation_price=98.0),
        setup_candles=trending_candles(symbol="R_75", count=100),
    )

    assert setup.state == "continuation"
    assert setup.trade_direction == "buy"
    assert setup.trigger_zone_low is not None
    assert setup.trigger_zone_high is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_setup_builder.py::test_classify_setup_marks_pullback_continuation_when_bias_and_setup_align -q`
Expected: FAIL with `ModuleNotFoundError` for `setup_builder`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.strategy.top_down_bias import TopDownBias


@dataclass(frozen=True)
class SetupDecision:
    state: str
    trade_direction: str
    trigger_zone_low: float | None
    trigger_zone_high: float | None
    reason: str


def classify_setup(*, bias: TopDownBias, setup_candles: list[Candle]) -> SetupDecision:
    recent = setup_candles[-12:]
    return SetupDecision(
        state="continuation" if bias.direction in {"bullish", "bearish"} else "none",
        trade_direction="buy" if bias.direction == "bullish" else "sell",
        trigger_zone_low=min(candle.low for candle in recent),
        trigger_zone_high=max(candle.high for candle in recent),
        reason=f"1H setup aligns with {bias.direction} higher-timeframe bias",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_setup_builder.py::test_classify_setup_marks_pullback_continuation_when_bias_and_setup_align -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/setup_builder.py tests/test_setup_builder.py
git commit -m "feat: add 1h setup classification"
```

## Task 5: Build 15m Confirmation Rules

**Files:**
- Create: `src/synthetic_trader/strategy/confirmation_builder.py`
- Test: `tests/test_confirmation_builder.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.strategy.confirmation_builder import confirm_setup
from synthetic_trader.strategy.setup_builder import SetupDecision
from tests.test_decision_engine import trending_candles


def test_confirm_setup_requires_lower_timeframe_alignment() -> None:
    result = confirm_setup(
        setup=SetupDecision(
            state="continuation",
            trade_direction="buy",
            trigger_zone_low=101.0,
            trigger_zone_high=103.0,
            reason="1H setup aligns with bullish higher-timeframe bias",
        ),
        confirmation_candles=trending_candles(symbol="R_75", count=60),
    )

    assert result.state == "confirmed"
    assert "15m" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_confirmation_builder.py::test_confirm_setup_requires_lower_timeframe_alignment -q`
Expected: FAIL with `ModuleNotFoundError` for `confirmation_builder`.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.strategy.setup_builder import SetupDecision


@dataclass(frozen=True)
class ConfirmationDecision:
    state: str
    reason: str


def confirm_setup(*, setup: SetupDecision, confirmation_candles: list[Candle]) -> ConfirmationDecision:
    confirmed = confirmation_candles[-1].close >= confirmation_candles[-2].close if setup.trade_direction == "buy" else confirmation_candles[-1].close <= confirmation_candles[-2].close
    return ConfirmationDecision(
        state="confirmed" if confirmed else "forming",
        reason=f"15m confirmation {'aligns' if confirmed else 'does not align'} with the setup",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_confirmation_builder.py::test_confirm_setup_requires_lower_timeframe_alignment -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/confirmation_builder.py tests/test_confirmation_builder.py
git commit -m "feat: add 15m confirmation rules"
```

## Task 6: Expand Snapshot Assembly To Multi-Timeframe Inputs

**Files:**
- Modify: `src/synthetic_trader/features/assembler.py`
- Test: `tests/test_multi_timeframe_structure.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.features.assembler import build_snapshot
from tests.test_decision_engine import trending_candles


def test_build_snapshot_includes_multi_timeframe_feature_prefixes() -> None:
    snapshot = build_snapshot(
        symbol="R_75",
        timeframe_sec=300,
        candles=trending_candles(symbol="R_75", count=80),
        higher_timeframe_candles=trending_candles(symbol="R_75", count=60),
        extra_timeframes={
            "bias": trending_candles(symbol="R_75", count=120),
            "setup": trending_candles(symbol="R_75", count=90),
            "confirmation": trending_candles(symbol="R_75", count=70),
        },
    )

    assert "bias_structure_bias" in snapshot.features
    assert "setup_structure_bias" in snapshot.features
    assert "confirmation_structure_bias" in snapshot.features
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_multi_timeframe_structure.py::test_build_snapshot_includes_multi_timeframe_feature_prefixes -q`
Expected: FAIL with `TypeError` because `build_snapshot()` has no `extra_timeframes` parameter.

- [ ] **Step 3: Write minimal implementation**

```python
def build_snapshot(
    symbol: str,
    timeframe_sec: int,
    candles: list[Candle],
    higher_timeframe_candles: list[Candle] | None = None,
    extra_timeframes: dict[str, list[Candle]] | None = None,
) -> FeatureSnapshot:
```

```python
    if extra_timeframes:
        for prefix, timeframe_candles in extra_timeframes.items():
            if not timeframe_candles:
                continue
            tf_regime, tf_features, tf_notes = classify_regime(timeframe_candles)
            tf_structure = market_structure_features(timeframe_candles)
            features.update({f"{prefix}_{key}": value for key, value in tf_features.items()})
            features.update({f"{prefix}_{key}": value for key, value in tf_structure.items()})
            features[f"{prefix}_regime_{tf_regime.value}"] = 1.0
            notes.extend(f"{prefix.upper()} {note}" for note in tf_notes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_multi_timeframe_structure.py::test_build_snapshot_includes_multi_timeframe_feature_prefixes -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/features/assembler.py tests/test_multi_timeframe_structure.py
git commit -m "feat: extend snapshot assembly for top-down timeframes"
```

## Task 7: Replace DecisionEngine With Top-Down Plan Construction

**Files:**
- Modify: `src/synthetic_trader/strategy/decision_engine.py`
- Test: `tests/test_decision_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from synthetic_trader.config import TraderConfig
from synthetic_trader.strategy.decision_engine import DecisionEngine
from tests.test_decision_engine import trending_candles


def test_decision_engine_builds_structure_led_trade_plan() -> None:
    engine = DecisionEngine(TraderConfig.default())
    report = engine.evaluate(
        "R_75",
        candles=trending_candles(symbol="R_75", count=120),
        higher_timeframe_candles=trending_candles(symbol="R_75", count=100),
    )

    assert report.signal is not None
    assert report.signal.entry != report.signal.snapshot.epoch
    assert report.signal.stop_loss < report.signal.entry
    assert report.signal.take_profit > report.signal.entry
    assert any("4H" in item or "1H" in item or "15m" in item for item in report.reasons)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_decision_engine.py::test_decision_engine_builds_structure_led_trade_plan -q`
Expected: FAIL because current rationale and trade construction remain close-anchored.

- [ ] **Step 3: Write minimal implementation**

```python
from synthetic_trader.strategy.confirmation_builder import confirm_setup
from synthetic_trader.strategy.setup_builder import classify_setup
from synthetic_trader.strategy.top_down_bias import infer_top_down_bias
```

```python
        bias = infer_top_down_bias(
            symbol=symbol,
            bias_candles=higher_timeframe_candles or candles,
            setup_candles=candles,
        )
        setup = classify_setup(
            bias=bias,
            setup_candles=candles,
        )
        confirmation = confirm_setup(
            setup=setup,
            confirmation_candles=candles[-30:],
        )
        if confirmation.state != "confirmed":
            return DecisionReport(None, (bias.reason, setup.reason, confirmation.reason))
```

```python
        entry = setup.trigger_zone_high if setup.trade_direction == "buy" else setup.trigger_zone_low
        stop_loss = bias.invalidation_price if bias.invalidation_price is not None else candles[-1].low
        risk_distance = abs(entry - stop_loss)
        take_profit = entry + risk_distance * profile.take_profit_rr if setup.trade_direction == "buy" else entry - risk_distance * profile.take_profit_rr
        rationale = (
            bias.reason,
            setup.reason,
            confirmation.reason,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_decision_engine.py::test_decision_engine_builds_structure_led_trade_plan -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/strategy/decision_engine.py tests/test_decision_engine.py src/synthetic_trader/strategy/top_down_bias.py src/synthetic_trader/strategy/setup_builder.py src/synthetic_trader/strategy/confirmation_builder.py
git commit -m "feat: switch decision engine to top-down structure plans"
```

## Task 8: Expose Structure-Led Live Snapshot Fields

**Files:**
- Modify: `src/synthetic_trader/live/market_snapshot.py`
- Test: `tests/test_live_market_snapshot.py`

- [ ] **Step 1: Write the failing test**

```python
def test_analyze_live_snapshot_returns_structure_led_invalidates_and_targets(self) -> None:
    ticks = [
        Tick(symbol="R_100", epoch=float(index * 60), price=460.0 + index * 0.1)
        for index in range(120)
    ]

    snapshot = analyze_live_snapshot(
        symbol="R_100",
        ticks=ticks,
        timeframe_sec=300,
        higher_timeframe_sec=3600,
        config=TraderConfig.default(),
    )

    self.assertIn("invalidates_if", snapshot)
    self.assertIn("decision_summary", snapshot)
    self.assertIn("target_area", snapshot)
    self.assertIn("guardian_state", snapshot)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_analyze_live_snapshot_returns_structure_led_invalidates_and_targets -q`
Expected: FAIL because the new structure-led reasoning is not yet in the snapshot path.

- [ ] **Step 3: Write minimal implementation**

```python
        snapshot = {
            "call": call,
            "trade_status": "valid" if risk_decision.approved else "not_valid",
            "direction_bias": direction_bias,
            "briefing": "; ".join(report.signal.rationale[:2]),
            "symbol": symbol,
            "regime": report.signal.snapshot.regime.value,
            "confidence": round(report.signal.confidence, 3),
            "decision_summary": "; ".join(report.signal.rationale),
            "invalidates_if": _build_invalidation_text(direction_bias, report.signal.stop_loss),
            **_format_trade_areas(
                report.signal.entry,
                report.signal.stop_loss,
                report.signal.take_profit,
            ),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests::test_analyze_live_snapshot_returns_structure_led_invalidates_and_targets -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/market_snapshot.py tests/test_live_market_snapshot.py
git commit -m "feat: expose structure-led live snapshot reasoning"
```

## Task 9: Update Guardian To Track Structure-Led Plans

**Files:**
- Modify: `src/synthetic_trader/live/signal_guardian.py`
- Test: `tests/test_signal_guardian.py`

- [ ] **Step 1: Write the failing test**

```python
def test_actionable_structure_plan_stays_actionable_until_real_invalidation() -> None:
    snapshot = GuardianSnapshot(
        symbol="R_75",
        direction_bias="buy",
        trade_status="valid",
        entry=100.0,
        stop_loss=98.0,
        take_profit=106.0,
        current_close=100.2,
    )
    context = GuardianContext(
        tick_prices=[100.0, 100.05, 100.1, 100.08, 100.12, 100.2],
        ticks_since_armed=6,
        max_favorable_excursion=0.2,
        max_adverse_excursion=0.02,
    )

    result = evaluate_signal_guardian(snapshot, context, DEFAULT_GUARDIAN_THRESHOLDS)

    assert result.state in {"actionable", "confirmed"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_signal_guardian.py::test_actionable_structure_plan_stays_actionable_until_real_invalidation -q`
Expected: FAIL if the current guard still reacts too tightly to small local drift.

- [ ] **Step 3: Write minimal implementation**

```python
    if adverse_ratio >= thresholds.weakening_excursion_ratio:
        return GuardianEvaluation(
            "failing",
            "The setup is deteriorating and the old plan is no longer fresh.",
        )

    # Structure-led plans should remain actionable while post-entry movement is still orderly.
    if context.ticks_since_armed <= thresholds.min_persistence_ticks + 2 and adverse_ratio < thresholds.rollover_warning_ratio:
        return GuardianEvaluation(
            "actionable",
            "The setup is actionable, but live continuation still needs more persistence.",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_signal_guardian.py::test_actionable_structure_plan_stays_actionable_until_real_invalidation -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/synthetic_trader/live/signal_guardian.py tests/test_signal_guardian.py
git commit -m "feat: align guardian with structure-led plans"
```

## Task 10: Update App Contracts For Richer Trade Plans

**Files:**
- Modify: `external/mitemshub-indices/src/lib/contracts.ts`
- Modify: `external/mitemshub-indices/src/lib/engine-bridge.ts`
- Test: `external/mitemshub-indices/tests/contracts.test.ts`
- Test: `external/mitemshub-indices/tests/engine-bridge.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("accepts structure-led invalidation and decision summary fields", () => {
  const result = freshCallResponseSchema.parse({
    symbol: "R_75",
    call: "buy_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.64,
    regime: "trend_up",
    direction_bias: "buy",
    why: "4H and 1H structure align bullishly",
    wait_for: "wait for a clean bullish continuation close",
    decision_summary: "4H bullish bias; 1H pullback held; 15m confirmed continuation",
    invalidates_if: "price closes back below the defended 1H shelf",
    entry_area: "around 53886.0",
    stop_area: "below 53779.1",
    target_area: "toward 54089.3",
    entry: 53886.0,
    stop_loss: 53779.1,
    take_profit: 54089.3,
    reward_risk: 1.9,
    current_close: 53886.0,
    guardian_state: "actionable",
    guardian_reason: "The setup is actionable, but live continuation still needs more persistence.",
    generated_at: new Date().toISOString(),
    account_mode: "own_account",
    prop_compliance: null,
    prop_adjusted_risk: null,
    prop_block_reason: null,
    prop_remaining_daily_buffer: null,
    prop_remaining_overall_buffer: null,
  });

  expect(result.invalidates_if).toMatch(/1H shelf/i);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run tests/contracts.test.ts tests/engine-bridge.test.ts`
Expected: FAIL if the richer payload is not normalized consistently.

- [ ] **Step 3: Write minimal implementation**

```ts
export const freshCallResponseSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  call: z.enum(["buy_candidate", "sell_candidate", "stand_aside"]),
  alert_type: z.enum(["setup_candidate", "context_update"]),
  trade_status: z.enum(["valid", "not_valid"]),
  confidence: z.number().nullable(),
  regime: z.string().nullable(),
  direction_bias: z.string().nullable(),
  why: z.string(),
  wait_for: z.string(),
  decision_summary: z.string().nullable(),
  invalidates_if: z.string().nullable().optional(),
```

```ts
function mapLiveSnapshot(raw: Record<string, unknown>, symbol: SymbolCode): BaseFreshCall {
  return {
    symbol,
    call,
    alert_type: normalizeText(raw.alert_type) ?? classifyAlertType(call, tradeStatus),
    trade_status: tradeStatus,
    confidence: normalizeNumber(raw.confidence),
    regime: normalizeText(raw.regime),
    direction_bias: normalizeText(raw.direction_bias),
    why,
    wait_for: normalizeText(raw.wait_for),
    decision_summary: normalizeText(raw.decision_summary),
    invalidates_if: normalizeText(raw.invalidates_if),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- --run tests/contracts.test.ts tests/engine-bridge.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add external/mitemshub-indices/src/lib/contracts.ts external/mitemshub-indices/src/lib/engine-bridge.ts external/mitemshub-indices/tests/contracts.test.ts external/mitemshub-indices/tests/engine-bridge.test.ts
git commit -m "feat: preserve structure-led trade payload through app bridge"
```

## Task 11: Full Regression Sweep

**Files:**
- Test: `tests/test_multi_timeframe_structure.py`
- Test: `tests/test_top_down_bias.py`
- Test: `tests/test_setup_builder.py`
- Test: `tests/test_confirmation_builder.py`
- Test: `tests/test_decision_engine.py`
- Test: `tests/test_live_market_snapshot.py`
- Test: `tests/test_signal_guardian.py`
- Test: `external/mitemshub-indices/tests/contracts.test.ts`
- Test: `external/mitemshub-indices/tests/engine-bridge.test.ts`

- [ ] **Step 1: Run focused Python suite**

Run: `python -m pytest tests/test_multi_timeframe_structure.py tests/test_top_down_bias.py tests/test_setup_builder.py tests/test_confirmation_builder.py tests/test_decision_engine.py tests/test_live_market_snapshot.py tests/test_signal_guardian.py -q`
Expected: PASS

- [ ] **Step 2: Run focused app suite**

Run: `powershell -Command "$nodeDir='C:\\Users\\USER\\AppData\\Roaming\\TRAE SOLO\\ModularData\\ai-agent\\vm\\tools\\node'; $env:Path=\"$nodeDir;$env:Path\"; & \"$nodeDir\\npm.cmd\" test -- --run tests/contracts.test.ts tests/engine-bridge.test.ts"`
Expected: PASS

- [ ] **Step 3: Runtime verification**

Run:

```bash
python -m pytest tests/test_live_market_snapshot.py::LiveSnapshotAnalysisTests -q
```

Then restart the app and verify:

```powershell
$body = @{ symbol = 'R_75'; account_mode = 'own_account'; prop_account_state = $null; prop_connection = $null } | ConvertTo-Json -Depth 5
(Invoke-WebRequest -UseBasicParsing -Method Post -Uri http://localhost:3006/api/calls/run -ContentType 'application/json' -Body $body).Content
```

Expected:

```text
trade_status=valid
guardian_state=actionable or confirmed
decision_summary contains higher-timeframe reasoning
invalidates_if is non-empty
entry/stop/target reflect structure, not a tiny latest-close hop
```

- [ ] **Step 4: Commit**

```bash
git add tests external/mitemshub-indices/tests
git commit -m "test: verify top-down structure inference engine"
```

## Spec Coverage Check

- Higher-timeframe-led bias: Tasks 1, 2, 3, 6, 7
- `1H` setup formation: Tasks 4 and 7
- `15m` confirmation: Tasks 5 and 7
- `5m` execution refinement: Tasks 6, 7, and 8
- `1m` guard only: Task 9
- Structure-led entry/stop/target/invalidation: Tasks 2, 7, and 8
- Longer structural hold horizon: Tasks 1 and 7
- Bridge/runtime output: Tasks 8, 10, and 11

