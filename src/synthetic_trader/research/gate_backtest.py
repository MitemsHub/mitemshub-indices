"""Walk-forward backtest of the Stage-3 empirical gate.

The gate replaces raw model confidence with the market-verified target-hit
rate of the call's ``(symbol, trigger_type)``, and (in ``suppress`` mode)
holds back call types whose verified rate is below the floor.  This module
answers the honest question: **does that empirical filter actually improve
call quality?**

Method (no lookahead):

1. **Emit** - walk the tick corpus forward building candles incrementally
   (O(n), same as ``BacktestEngine``) but with the sniper role timeframes,
   and run ``DecisionEngine.evaluate`` exactly like the live snapshot path.
   Every emitted candidate is converted into a production call record via
   ``build_call_record`` (same journal format the auto-scorer scores).

2. **Score** - each call is scored against the corpus ticks in its hold
   window using ``score_call_outcome`` (the same target/stop/neither rules
   the live scorer applies to real market data).

3. **Gate, walk-forward** - a call's outcome only becomes *visible* once its
   hold window has elapsed (``generated_at + hold``), mirroring the live
   auto-scorer which skips calls whose horizon hasn't ended.  At each
   emission the gate decides using only outcomes resolved *before* it, via
   the shared ``stage3_gate.gate_decision`` - the exact production rules.

4. **Verdict** - compares the target-hit rate (and expectancy) of calls the
   gate would have kept vs suppressed vs the full corpus, per trigger type
   and overall.  If suppression works, kept calls must outperform suppressed
   ones; if the gate merely suppresses everything (or keeps everything), the
   verdict says so plainly.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.config import MAX_FEATURE_HISTORY, TraderConfig
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import Candle, Tick
from synthetic_trader.live.calibration_logger import build_call_record
from synthetic_trader.live.calibration_scorer import score_call_outcome
from synthetic_trader.live.market_snapshot import build_mode_config, classify_alert_type
from synthetic_trader.live.stage3_gate import (
    GATE_HIT_RATE_FLOOR,
    MIN_STAGE3_SAMPLES,
    break_even_floor,
    gate_decision,
    resolve_trigger_type,
)
from synthetic_trader.models.online import OnlineLogisticModel
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine

# Fallback hold horizon (minutes) when a signal carries none - matches the
# live scorer's default of 60 minutes.
DEFAULT_HOLD_MINUTES = 60


@dataclass(frozen=True)
class GateBacktestConfig:
    symbol: str = "R_100"
    timeframe_sec: int = 60
    higher_timeframe_sec: int = 300
    min_samples: int = MIN_STAGE3_SAMPLES
    # ``None`` (the default) means the per-trigger-type BREAK-EVEN floor:
    # each trigger's floor is 1/(1+its running avg reward:risk) + margin,
    # computed walk-forward from the calls emitted so far (no lookahead — the
    # reward:risk is known at emission, the outcome is not).  A flat number
    # forces the legacy fixed bar for every trigger.
    hit_rate_floor: float | None = None


@dataclass
class CallRecord:
    """One emitted call plus its eventual outcome and gate decision."""

    generated_at_epoch: float
    record: dict[str, object]
    trigger_type: str
    level_key: tuple[object, ...] = ()
    outcome_label: str | None = None
    gate_state: str | None = None
    evidence_status: str | None = None
    hit_rate_at_emission: float | None = None
    samples_at_emission: int = 0
    # Break-even floor bookkeeping (only set when the auto floor is used):
    # the floor that was actually applied to this call and the running avg
    # reward:risk it was derived from.
    floor_at_emission: float | None = None
    avg_rr_at_emission: float | None = None


@dataclass
class TriggerStats:
    trigger_type: str
    emitted: int = 0
    scored: int = 0
    suppressed: int = 0
    kept: int = 0
    target_hits_kept: int = 0
    target_hits_suppressed: int = 0
    stopped_kept: int = 0
    stopped_suppressed: int = 0
    kept_hit_rate: float | None = None
    suppressed_hit_rate: float | None = None
    kept_expectancy_r: float | None = None
    suppressed_expectancy_r: float | None = None
    # Mean break-even floor applied to this trigger's calls (only meaningful
    # when the auto floor is used; the floor a 3R trigger must clear is ~30%,
    # a 2R trigger ~38%).
    avg_floor_at_emission: float | None = None


@dataclass
class GateBacktestResult:
    symbol: str
    timeframe_sec: int
    calls: list[CallRecord] = field(default_factory=list)
    per_trigger: dict[str, TriggerStats] = field(default_factory=dict)
    config: GateBacktestConfig | None = None

    @property
    def scored_calls(self) -> list[CallRecord]:
        return [c for c in self.calls if c.outcome_label is not None]

    @property
    def kept_calls(self) -> list[CallRecord]:
        # "Kept" = everything the gate did NOT hold back (gated, annotated, or
        # insufficient_data — the paper-only learning calls).  These are the
        # calls the operator actually sees and paper-trades.
        return [c for c in self.scored_calls if c.gate_state != "suppressed"]

    @property
    def suppressed_calls(self) -> list[CallRecord]:
        # Held back entirely: below-floor call types (collapsed gate).
        return [c for c in self.scored_calls if c.gate_state == "suppressed"]

    def _hit_rate(self, calls: list[CallRecord]) -> float | None:
        if not calls:
            return None
        hits = sum(1 for c in calls if c.outcome_label == "target_hit")
        return hits / len(calls)

    def _expectancy_r(self, calls: list[CallRecord]) -> float | None:
        """Mean per-trade R-multiple: hit*RR - (1-hit), using each call's RR."""
        values = []
        for c in calls:
            rr = reward_risk_from_record(c.record)
            if c.outcome_label == "target_hit":
                values.append(rr)
            elif c.outcome_label == "stop_hit":
                values.append(-1.0)
            elif c.outcome_label == "neither_reached":
                # Half-way: no target and no stop in window - price ran nowhere.
                values.append(0.0)
        if not values:
            return None
        return sum(values) / len(values)

    # ── Verdict helpers ──────────────────────────────────────────
    def kept_vs_all_lift(self) -> float | None:
        all_rate = self._hit_rate(self.scored_calls)
        kept_rate = self._hit_rate(self.kept_calls)
        if all_rate is None or kept_rate is None:
            return None
        return kept_rate - all_rate

    def kept_vs_suppressed_lift(self) -> float | None:
        kept_rate = self._hit_rate(self.kept_calls)
        suppressed_rate = self._hit_rate(self.suppressed_calls)
        if kept_rate is None or suppressed_rate is None:
            return None
        return kept_rate - suppressed_rate


def _epoch_to_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _fmt_rate(rate: float | None) -> str:
    return f"{rate:.0%}" if rate is not None else "-"


def _fmt_r(value: float | None) -> str:
    return f"{value:+.3f}" if value is not None else "-"


def reward_risk_from_record(record: dict[str, object]) -> float:
    """Derive reward:risk from entry/stop/target levels.

    ``build_call_record`` does not persist ``reward_risk`` (it is a computed
    property on the signal), so the backtest recomputes it from the levels
    the journal does store - identical math to the live signal's property.
    """
    entry = record.get("entry")
    stop = record.get("execution_stop")
    target = record.get("primary_target")
    if entry is None or stop is None or target is None:
        return 1.0
    try:
        entry_f, stop_f, target_f = float(entry), float(stop), float(target)
    except (TypeError, ValueError):
        return 1.0
    risk = abs(entry_f - stop_f)
    if risk <= 0.0:
        return 1.0
    return abs(target_f - entry_f) / risk


def _prices_in_window(
    ticks: list[Tick], start_epoch: float, end_epoch: float
) -> list[tuple[float, float]]:
    """Extract (price, epoch) pairs within [start_epoch, end_epoch) from a sorted tick list.

    Epochs are included so ``score_call_outcome`` can apply the same
    stop-lock grace as the live auto-scorer (stop only confirmed by a CLOSED
    execution-timeframe candle) — the backtest verdict must score with the
    exact production rules.
    """
    epochs = [t.epoch for t in ticks]
    left = bisect.bisect_left(epochs, start_epoch)
    right = bisect.bisect_left(epochs, end_epoch)
    return [(ticks[i].price, ticks[i].epoch) for i in range(left, right)]


def emit_calls_from_ticks(
    *,
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    model: OnlineLogisticModel | None = None,
) -> list[CallRecord]:
    """Walk the corpus emitting call records exactly like the live path.

    Builds candles incrementally (O(n) total) for the sniper role timeframes,
    mirrors the live signal→snapshot mapping in ``analyze_live_snapshot``
    (entry/stop/target/trigger/hold horizon), and converts each emitted
    candidate to a production call record via ``build_call_record``.
    """
    config = build_mode_config(TraderConfig.default(), _sniper_preset())
    profile = config.symbols[symbol]
    role_timeframes = {
        "bias": profile.bias_timeframe_sec,
        "setup": profile.setup_timeframe_sec,
        "confirmation": profile.confirmation_timeframe_sec,
        "execution": profile.execution_timeframe_sec,
    }
    requested_timeframes = sorted(
        set([timeframe_sec, higher_timeframe_sec, *role_timeframes.values()])
    )
    builder = MultiTimeframeCandleBuilder(symbol, requested_timeframes)
    histories: dict[int, list[Candle]] = {tf: [] for tf in requested_timeframes}
    decision_engine = DecisionEngine(config, model=model)
    risk_engine = RiskEngine(config.risk)
    emitted: list[CallRecord] = []

    sorted_ticks = sorted(ticks, key=lambda item: item.epoch)
    for tick in sorted_ticks:
        closed = builder.update(tick)
        for tf, candle in closed.items():
            if tf != timeframe_sec:
                histories[tf].append(candle)

        primary = closed.get(timeframe_sec)
        if primary is None:
            continue
        histories[timeframe_sec].append(primary)

        role_candles = {
            role: histories.get(role_timeframe, [])[-MAX_FEATURE_HISTORY:]
            for role, role_timeframe in role_timeframes.items()
        }
        execution_candles = role_candles["execution"]
        confirmation_candles = role_candles["confirmation"]
        if len(execution_candles) < profile.min_history_candles:
            continue

        report = decision_engine.evaluate(
            symbol=symbol,
            candles=execution_candles,
            higher_timeframe_candles=confirmation_candles,
            role_candles=role_candles,
            trading_mode="sniper",
        )
        if report.signal is None:
            continue
        risk_decision = risk_engine.evaluate(report.signal)
        if not risk_decision.approved:
            continue

        signal = report.signal
        direction_bias = "buy" if signal.direction.value == "long" else "sell"
        call = "buy_candidate" if direction_bias == "buy" else "sell_candidate"
        current_close = primary.close
        snapshot: dict[str, object] = {
            "call": call,
            "trade_status": "valid",
            "direction_bias": direction_bias,
            "symbol": symbol,
            "regime": signal.snapshot.regime.value,
            "confidence": round(signal.confidence, 3),
            "model_version": signal.model_version,
            "current_close": current_close,
            "entry": signal.entry,
            "execution_stop": signal.execution_stop,
            "thesis_invalidation": signal.thesis_invalidation,
            "primary_target": signal.primary_target,
            "extended_target": signal.extended_target,
            "hold_horizon_minutes": signal.hold_horizon_minutes,
            "stop_loss": (
                signal.execution_stop
                if signal.execution_stop is not None
                else signal.stop_loss
            ),
            "take_profit": (
                signal.primary_target
                if signal.primary_target is not None
                else signal.take_profit
            ),
            "reward_risk": round(signal.reward_risk, 3),
            "execution_trigger_type": signal.execution_trigger_type,
            "generated_at": _epoch_to_iso(float(primary.open_time) + primary.timeframe_sec),
        }
        # alert_type is what the live builder stamps (and what the trigger
        # falls back to when no execution trigger exists) - mirror it so the
        # trigger bucket matches the production journal exactly.
        snapshot["alert_type"] = classify_alert_type(snapshot)
        # Trigger type resolution mirrors the live journal/gate.
        trigger_type = resolve_trigger_type(snapshot)

        # The live watch only LOGS a call when the setup state changes - a
        # signal that persists across candles is the same trade idea, not a
        # new call.  Dedupe to first appearance per distinct levels so the
        # backtest counts independent entries, exactly like the journal.
        level_key = (
            call,
            round(float(signal.entry), 4) if signal.entry is not None else None,
            round(float(signal.execution_stop), 4) if signal.execution_stop is not None else None,
            round(float(signal.primary_target), 4) if signal.primary_target is not None else None,
        )
        if emitted and emitted[-1].level_key == level_key:
            continue
        record = build_call_record(snapshot)
        emitted.append(
            CallRecord(
                generated_at_epoch=float(primary.open_time) + primary.timeframe_sec,
                record=record,
                trigger_type=trigger_type,
                level_key=level_key,
            )
        )

    return emitted


def _sniper_preset():
    from synthetic_trader.live.market_snapshot import TRADING_MODE_PRESETS

    return TRADING_MODE_PRESETS["sniper"]


def score_emitted_calls(
    *,
    calls: list[CallRecord],
    ticks: list[Tick],
) -> None:
    """Score each emitted call against the corpus's post-call ticks.

    The window is ``[generated_at, generated_at + hold)`` using the same
    default hold as the live scorer when the signal carries none.  Calls
    whose window falls past the end of the corpus stay unscored (the live
    auto-scorer would score them later).
    """
    sorted_ticks = sorted(ticks, key=lambda item: item.epoch)
    max_epoch = sorted_ticks[-1].epoch if sorted_ticks else 0.0
    for call in calls:
        hold_minutes = int(call.record.get("hold_horizon_minutes") or DEFAULT_HOLD_MINUTES)
        window_end = call.generated_at_epoch + hold_minutes * 60
        if window_end > max_epoch:
            continue  # not enough future data - would be scored later live
        prices = _prices_in_window(sorted_ticks, call.generated_at_epoch, window_end)
        if not prices:
            continue
        outcome = score_call_outcome(record=call.record, prices=prices)
        call.outcome_label = outcome["outcome_label"]


def simulate_gate_walk_forward(
    *,
    calls: list[CallRecord],
    min_samples: int,
    hit_rate_floor: float | None = None,
    horizon_verdict: str | None = "calibrated",
) -> None:
    """Walk emissions forward applying the gate with no lookahead.

    A call's outcome becomes visible at ``generated_at + hold``.  At each
    emission the gate rolls up only outcomes resolved strictly before it and
    decides via the shared ``gate_decision`` - the exact production rules.

    ``hit_rate_floor``: when ``None`` the floor is the per-trigger-type
    BREAK-EVEN rate - 1/(1+running avg reward:risk) + margin, where the
    running average is over calls of that trigger emitted so far.  The
    reward:risk is a property of the call's levels, which exist at emission
    (no outcome lookahead).  A flat number forces the legacy fixed bar.

    ``horizon_verdict`` defaults to ``calibrated`` so the backtest isolates
    the *empirical-hit-rate* axis of the gate (the suppression decision does
    not depend on the horizon verdict; that is a separate calibration check).
    """
    outcomes_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
    # Running reward:risk per (symbol, trigger) for break-even floors.  RR is
    # known at emission (it is derived from the call's own levels), so
    # accumulating it as we walk is NOT outcome lookahead.
    rr_by_key: dict[tuple[str, str], list[float]] = {}
    resolved: list[tuple[float, CallRecord]] = []

    for call in calls:
        hold_minutes = int(call.record.get("hold_horizon_minutes") or DEFAULT_HOLD_MINUTES)
        resolved.append((call.generated_at_epoch + hold_minutes * 60, call))

    pending = sorted(calls, key=lambda c: c.generated_at_epoch)
    resolved.sort(key=lambda item: item[0])

    resolved_index = 0
    for call in pending:
        # Make visible every outcome whose hold window ended before this
        # emission (strictly before - no lookahead, no same-instant peeking).
        while resolved_index < len(resolved) and resolved[resolved_index][0] < call.generated_at_epoch:
            earlier = resolved[resolved_index][1]
            if earlier.outcome_label is not None:
                key = (call.record.get("symbol"), earlier.trigger_type)
                outcomes_by_key.setdefault(key, []).append(
                    {
                        "symbol": call.record.get("symbol"),
                        "trigger_type": earlier.trigger_type,
                        "outcome_label": earlier.outcome_label,
                        "trade_status": earlier.record.get("trade_status"),
                    }
                )
            resolved_index += 1

        key = (call.record.get("symbol"), call.trigger_type)
        bucket = outcomes_by_key.get(key, [])
        count = len(bucket)
        if count:
            hit_rate = sum(1 for o in bucket if o["outcome_label"] == "target_hit") / count
        else:
            hit_rate = None

        # ── Per-trigger-type break-even floor (default) ─────────────
        # Floor = 1/(1+running avg RR of this trigger's calls so far) +
        # margin.  The running average only ever includes calls emitted
        # strictly BEFORE this one (same strictness as the outcomes), so a
        # trigger's own geometry is never used to judge itself.
        if hit_rate_floor is None:
            prior_rrs = rr_by_key.get(key, [])
            if prior_rrs:
                avg_rr = sum(prior_rrs) / len(prior_rrs)
            else:
                avg_rr = None
            floor = break_even_floor(avg_rr)
            call.floor_at_emission = floor
            call.avg_rr_at_emission = avg_rr
        else:
            floor = hit_rate_floor
            call.floor_at_emission = floor
            call.avg_rr_at_emission = None
        rr_by_key.setdefault(key, []).append(reward_risk_from_record(call.record))

        state, evidence_status = gate_decision(
            count=count,
            hit_rate=hit_rate,
            verdict_label=horizon_verdict,
            min_samples=min_samples,
            hit_rate_floor=floor,
        )
        call.gate_state = state
        call.evidence_status = evidence_status
        call.hit_rate_at_emission = hit_rate
        call.samples_at_emission = count


def _aggregate(result: GateBacktestResult) -> None:
    by_trigger: dict[str, TriggerStats] = {}
    for call in result.calls:
        stats = by_trigger.setdefault(call.trigger_type, TriggerStats(trigger_type=call.trigger_type))
        stats.emitted += 1
        if call.outcome_label is None:
            continue
        stats.scored += 1
        if call.gate_state == "suppressed":
            stats.suppressed += 1
            if call.outcome_label == "target_hit":
                stats.target_hits_suppressed += 1
            if call.outcome_label == "stop_hit":
                stats.stopped_suppressed += 1
        else:
            stats.kept += 1
            if call.outcome_label == "target_hit":
                stats.target_hits_kept += 1
            if call.outcome_label == "stop_hit":
                stats.stopped_kept += 1

    for stats in by_trigger.values():
        if stats.kept:
            stats.kept_hit_rate = stats.target_hits_kept / stats.kept
        if stats.suppressed:
            stats.suppressed_hit_rate = stats.target_hits_suppressed / stats.suppressed
        # Mean break-even floor actually applied across this trigger's calls.
        floors = [
            c.floor_at_emission
            for c in result.calls
            if c.trigger_type == stats.trigger_type and c.floor_at_emission is not None
        ]
        if floors:
            stats.avg_floor_at_emission = sum(floors) / len(floors)
        # Expectancy uses the same outcome weighting as the overall report
        # (target=+RR, stop=-1, neither=0) so the table never contradicts the
        # verdict numbers.
        kept_calls = [
            c for c in result.calls
            if c.trigger_type == stats.trigger_type
            and c.gate_state != "suppressed"
            and c.outcome_label is not None
        ]
        if kept_calls:
            kept_values = [
                reward_risk_from_record(c.record) if c.outcome_label == "target_hit"
                else -1.0 if c.outcome_label == "stop_hit"
                else 0.0
                for c in kept_calls
            ]
            stats.kept_expectancy_r = sum(kept_values) / len(kept_values)
        suppressed_calls = [
            c for c in result.calls
            if c.trigger_type == stats.trigger_type
            and c.gate_state == "suppressed"
            and c.outcome_label is not None
        ]
        if suppressed_calls:
            suppressed_values = [
                reward_risk_from_record(c.record) if c.outcome_label == "target_hit"
                else -1.0 if c.outcome_label == "stop_hit"
                else 0.0
                for c in suppressed_calls
            ]
            stats.suppressed_expectancy_r = sum(suppressed_values) / len(suppressed_values)

    result.per_trigger = by_trigger


def run_gate_backtest(
    *,
    ticks: list[Tick],
    symbol: str,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
    min_samples: int = MIN_STAGE3_SAMPLES,
    hit_rate_floor: float | None = None,
    model: OnlineLogisticModel | None = None,
) -> GateBacktestResult:
    """Full pipeline: emit → score → walk-forward gate → aggregate.

    ``hit_rate_floor`` ``None`` (default) uses the per-trigger-type
    BREAK-EVEN floor; a flat number forces the legacy fixed bar.
    """
    config = GateBacktestConfig(
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        min_samples=min_samples,
        hit_rate_floor=hit_rate_floor,
    )
    calls = emit_calls_from_ticks(
        ticks=ticks,
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        model=model,
    )
    score_emitted_calls(calls=calls, ticks=ticks)
    simulate_gate_walk_forward(
        calls=calls,
        min_samples=min_samples,
        hit_rate_floor=hit_rate_floor,
    )
    result = GateBacktestResult(
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        calls=calls,
        config=config,
    )
    _aggregate(result)
    return result


def print_gate_backtest_report(result: GateBacktestResult) -> None:
    """Human-readable suppressed-vs-kept verdict."""
    scored = result.scored_calls
    kept = result.kept_calls
    suppressed = result.suppressed_calls
    all_rate = result._hit_rate(scored)
    kept_rate = result._hit_rate(kept)
    suppressed_rate = result._hit_rate(suppressed)
    kept_exp = result._expectancy_r(kept)
    all_exp = result._expectancy_r(scored)
    suppressed_exp = result._expectancy_r(suppressed)
    config_floor = result.config.hit_rate_floor if result.config else None
    min_samples = result.config.min_samples if result.config else MIN_STAGE3_SAMPLES

    print(f"=== Stage-3 Gate Backtest: {result.symbol} @ {result.timeframe_sec}s ===")
    print(f"emitted calls: {len(result.calls)}  scored: {len(scored)}  "
          f"unscored (no future data): {sum(1 for c in result.calls if c.outcome_label is None)}")
    if config_floor is None:
        floor_desc = "auto (per-trigger break-even: 1/(1+RR) + margin)"
    else:
        floor_desc = f"{config_floor:.0%} (fixed)"
    print(f"gate: min_samples={min_samples} floor={floor_desc} (collapsed: full/half/paper)")
    print()

    header = (f"{'trigger':<28} {'emit':>4} {'score':>5} {'kept':>4} {'suppr':>5} "
              f"{'floor':>5} {'kept_hit':>8} {'suppr_hit':>9} {'kept_R':>7} {'suppr_R':>8}")
    print(header)
    print("-" * len(header))
    for stats in sorted(result.per_trigger.values(), key=lambda s: -s.emitted):
        kept_hit = f"{stats.kept_hit_rate:.0%}" if stats.kept_hit_rate is not None else "-"
        suppr_hit = f"{stats.suppressed_hit_rate:.0%}" if stats.suppressed_hit_rate is not None else "-"
        kept_r = f"{stats.kept_expectancy_r:+.2f}" if stats.kept_expectancy_r is not None else "-"
        suppr_r = f"{stats.suppressed_expectancy_r:+.2f}" if stats.suppressed_expectancy_r is not None else "-"
        floor = stats.avg_floor_at_emission
        floor_txt = f"{floor:.0%}" if floor is not None else "-"
        print(f"{stats.trigger_type:<28} {stats.emitted:>4} {stats.scored:>5} "
              f"{stats.kept:>4} {stats.suppressed:>5} "
              f"{floor_txt:>5} {kept_hit:>8} {suppr_hit:>9} {kept_r:>7} {suppr_r:>8}")

    def _fmt(rate: float | None) -> str:
        return f"{rate:.0%}" if rate is not None else "n/a"

    print()
    print("-- Verdict ----------------------------------------------------------")
    print(f"all calls:        hit {_fmt(all_rate):>5}  expectancy {_fmt_r(all_exp)} R  (n={len(scored)})")
    print(f"gate KEPT:        hit {_fmt(kept_rate):>5}  expectancy {_fmt_r(kept_exp)} R  (n={len(kept)})")
    print(f"gate SUPPRESSED:  hit {_fmt(suppressed_rate):>5}  expectancy {_fmt_r(suppressed_exp)} R  (n={len(suppressed)})")
    lift_kept_all = result.kept_vs_all_lift()
    lift_kept_suppr = result.kept_vs_suppressed_lift()
    print(f"lift kept vs all:        {_fmt(lift_kept_all)}")
    print(f"lift kept vs suppressed: {_fmt(lift_kept_suppr)}")

    # Interpretation
    print()
    # Why were calls kept?  The gate keeps a call when it has no verdict yet
    # (insufficient_data) OR when the trigger type cleared the floor.  Only
    # the latter is "kept because proven" - the former is just "no data yet",
    # which is not evidence the filter worked.  Split them so the verdict is
    # never read as the gate endorsing the kept calls.
    kept_insufficient = [
        c for c in kept if c.evidence_status in ("no_data", "still_learning")
    ]
    kept_proven = [c for c in kept if c.evidence_status not in ("no_data", "still_learning")]
    print(f"kept breakdown: {len(kept_insufficient)} no-verdict-yet (insufficient_data), "
          f"{len(kept_proven)} cleared the floor")

    if len(scored) == 0:
        print("VERDICT: no call had a resolvable outcome on this corpus - ",
              "the gate cannot be measured yet (needs more data or a longer hold window).")
        return
    if len(suppressed) == 0 and not kept_proven:
        print("VERDICT: the gate suppressed NOTHING and no trigger type cleared the floor. "
              "Either every trigger type failed the floor once samples accumulated (all kept "
              "calls were no-verdict-yet), or no trigger type reached the minimum sample count. "
              "Suppression never engaged, so the filter had no measurable effect on call quality.")
        return
    if len(suppressed) == 0:
        # Suppressed nothing because EVERYTHING cleared the floor.
        print(f"VERDICT: the gate suppressed NOTHING because every trigger type cleared its "
              "floor (break-even + margin, or the fixed floor if configured) once "
              f"{min_samples} samples accumulated. Nothing was held "
              "back, so the empirical filter changed nothing: call quality is what it is.")
        return
    if kept_rate is None or suppressed_rate is None:
        print("VERDICT: insufficient scored calls on one side of the gate to compare.")
        return
    if len(suppressed) > 0 and not kept_proven:
        # The gate suppressed everything once samples accumulated, and NOTHING
        # was ever kept because it cleared the floor.  The kept set is purely
        # early no-verdict-yet calls, so kept-vs-suppressed hit rates are a
        # time-ordering artifact, not evidence of filtering.
        if config_floor is None:
            floor_why = (
                "the BREAK-EVEN floor (1/(1+avg reward:risk) + margin) is reachable by "
                "construction, so zero clears mean these setups are not even beating their "
                "own geometry's break-even + margin. The gate is a risk-control switch, "
                "correctly refusing to endorse a call type that loses money."
            )
        else:
            floor_why = (
                f"a FIXED floor of {config_floor:.0%} is the unreachable-floor trap for "
                "2R+ setups: the break-even rate for 3R geometry is ~25%, so a fixed bar "
                "above ~30% turns the gate into an all-or-nothing switch regardless of "
                "call quality. Re-run without --hit-rate-floor to use the per-trigger "
                "break-even floor and measure the real call quality."
            )
        print("VERDICT: ALL-OR-NOTHING SWITCH. Every kept call was kept only because no verdict "
              "existed yet (insufficient_data) - zero calls cleared the floor, yet "
              f"{len(suppressed)} were suppressed. {floor_why}")
        return
    if lift_kept_suppr is not None and lift_kept_suppr > 0.02:
        # Honest framing: "improves" is a RELATIVE claim (kept beats
        # suppressed).  If kept expectancy is still negative, say so explicitly
        # so the operator never misreads it as profitability.
        exp_note = (
            f" Note: kept expectancy is still {_fmt_r(kept_exp)} R — the filter "
            "removes the worst call types, but the survivors are not yet "
            "profitable."
            if kept_exp is not None and kept_exp < 0
            else ""
        )
        print(f"VERDICT: the empirical filter IMPROVES call quality - kept calls hit the target "
              f"{_fmt(kept_rate)} vs {_fmt(suppressed_rate)} for suppressed ({lift_kept_suppr:+.0%} lift). "
              f"Suppression is removing genuinely worse call types.{exp_note}")
    elif lift_kept_suppr is not None and lift_kept_suppr < -0.02:
        print(f"VERDICT: the empirical filter HURTS call quality - suppressed calls actually hit "
              f"{_fmt(suppressed_rate)} vs {_fmt(kept_rate)} for kept ({lift_kept_suppr:+.0%}). "
              "The gate is holding back better call types; the floor/sample thresholds need review.")
    else:
        print(f"VERDICT: no material difference - kept {_fmt(kept_rate)} vs suppressed "
              f"{_fmt(suppressed_rate)}. On this corpus the empirical filter neither helps nor "
              "hurts call quality (as expected when price direction is unpredictable); "
              "suppression is a risk-control switch, not an edge.")
    print()
    print("context: a trigger's break-even target-hit rate is 1/(1+avg reward:risk). "
          "The default floor is break-even + margin per trigger type, so any call type "
          "that beats its own geometry's break-even clears the gate - the floor is "
          "reachable by construction. A fixed floor (SYNTH_GATE_HIT_RATE_FLOOR or "
          "--hit-rate-floor) still forces one bar for every trigger.")


def backtest_gate_from_csv(
    *,
    csv_path: str | Path,
    symbol: str,
    timeframe_sec: int = 60,
    higher_timeframe_sec: int = 300,
    min_samples: int = MIN_STAGE3_SAMPLES,
    hit_rate_floor: float | None = None,
) -> GateBacktestResult:
    ticks = load_ticks_csv(csv_path, default_symbol=symbol)
    return run_gate_backtest(
        ticks=ticks,
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        min_samples=min_samples,
        hit_rate_floor=hit_rate_floor,
    )
