from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import re
from dataclasses import dataclass
from pathlib import Path

from synthetic_trader.config import TraderConfig
from synthetic_trader.data.collector import deriv_credentials_from_env
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder
from synthetic_trader.domain import Tick
from synthetic_trader.execution.deriv_ws import DerivWebSocketClient
from synthetic_trader.execution.venues import MarketDataClient
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.live.signal_guardian import (
    GuardianContext,
    GuardianSnapshot,
    GuardianThresholds,
    evaluate_signal_guardian,
)
from synthetic_trader.risk.engine import RiskEngine
from synthetic_trader.strategy.decision_engine import DecisionEngine


@dataclass(frozen=True)
class WatchState:
    call: str
    alert_type: str
    trade_status: str
    direction_bias: str
    regime: str
    confidence_bucket: str
    wait_for: str


DEFAULT_CONTEXT_ALERT_COOLDOWN = 2
DEFAULT_GUARDIAN_THRESHOLDS = GuardianThresholds(
    max_arming_ticks=12,
    max_confirmation_window_ticks=6,
    weakening_excursion_ratio=0.35,
    max_adverse_excursion_ratio=0.8,
    max_entry_drift_ratio=0.75,
    microstructure_window_ticks=6,
    min_persistence_ticks=4,
    min_impulse_ratio=0.12,
    max_pullback_ratio=0.22,
    rollover_warning_ratio=0.18,
    rollover_invalidation_ratio=0.3,
    adverse_cluster_window_ticks=4,
    max_adverse_cluster_count=2,
)


async def collect_live_snapshot_ticks(
    *,
    symbol: str,
    warmup_count: int,
    max_live_ticks: int,
    app_id: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> list[Tick]:
    credentials = deriv_credentials_from_env(app_id=app_id)
    factory = client_factory or (lambda: DerivWebSocketClient(credentials))
    collected: list[Tick] = []

    async with factory() as client:
        if warmup_count > 0:
            collected.extend(await client.ticks_history(symbol=symbol, count=warmup_count))
        if max_live_ticks > 0:
            seen_live_ticks = 0
            async for tick in client.subscribe_ticks(symbol):
                collected.append(tick)
                seen_live_ticks += 1
                if seen_live_ticks >= max_live_ticks:
                    break

    return sorted(collected, key=lambda item: item.epoch)


def _extract_reason_value(reasons: list[str], pattern: str) -> float | None:
    matcher = re.compile(pattern)
    for reason in reasons:
        match = matcher.search(reason)
        if match:
            return float(match.group(1))
    return None


def _direction_bias_from_probability(model_long_probability: float | None) -> str:
    if model_long_probability is None:
        return "none"
    if model_long_probability >= 0.55:
        return "buy"
    if model_long_probability <= 0.45:
        return "sell"
    return "none"


def _summarize_structure(structure: dict[str, float] | object) -> str:
    if not isinstance(structure, dict):
        return "structure still forming"
    if structure.get("bos_up", 0.0):
        return "break of structure up"
    if structure.get("bos_down", 0.0):
        return "break of structure down"
    if structure.get("liquidity_sweep_down", 0.0):
        return "downside sweep reclaimed"
    if structure.get("liquidity_sweep_up", 0.0):
        return "upside sweep rejected"
    bias = structure.get("structure_bias", 0.0)
    if bias > 0:
        return "bullish structure bias"
    if bias < 0:
        return "bearish structure bias"
    return "structure is mixed"


def _wait_for_next(trade_status: str, direction_bias: str, reasons: list[str]) -> str:
    if trade_status == "valid":
        if direction_bias == "buy":
            return "wait for a clean bullish continuation close"
        if direction_bias == "sell":
            return "wait for a clean bearish continuation close"
        return "wait for the next aligned candle close"

    for reason in reasons:
        if "need " in reason and "candles" in reason:
            return "wait for more candle history before trusting the setup"
        if "confidence" in reason:
            return "wait for confidence above threshold and cleaner directional agreement"
        if "reward/risk" in reason:
            return "wait for a cleaner entry so reward outweighs the risk"
        if "volatility" in reason:
            return "wait for volatility to normalize before considering a trade"
    return "wait for clearer structure and stronger confirmation"


def _format_trade_areas(entry: float, stop_loss: float, take_profit: float) -> dict[str, str]:
    return {
        "entry_area": f"around {entry}",
        "stop_area": f"below {stop_loss}" if stop_loss < entry else f"above {stop_loss}",
        "target_area": f"toward {take_profit}",
    }


def _excursion_window(
    *,
    direction_bias: str,
    entry: float | None,
    prices: list[float],
) -> tuple[float, float]:
    if entry is None or not prices:
        return 0.0, 0.0

    if direction_bias == "buy":
        favorable = max(0.0, max(price - entry for price in prices))
        adverse = max(0.0, max(entry - price for price in prices))
        return favorable, adverse

    if direction_bias == "sell":
        favorable = max(0.0, max(entry - price for price in prices))
        adverse = max(0.0, max(price - entry for price in prices))
        return favorable, adverse

    return 0.0, 0.0


def build_guardian_snapshot(snapshot: dict[str, object], ticks: list[Tick]) -> dict[str, object]:
    current_close = ticks[-1].price if ticks else snapshot.get("current_close")
    enriched = dict(snapshot)
    enriched["current_close"] = current_close

    signal_snapshot = GuardianSnapshot(
        symbol=str(snapshot.get("symbol", "")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        entry=float(snapshot["entry"]) if snapshot.get("entry") is not None else None,
        stop_loss=float(snapshot["stop_loss"]) if snapshot.get("stop_loss") is not None else None,
        take_profit=float(snapshot["take_profit"]) if snapshot.get("take_profit") is not None else None,
        current_close=float(current_close) if current_close is not None else None,
    )
    prices = [tick.price for tick in ticks[-DEFAULT_GUARDIAN_THRESHOLDS.max_arming_ticks :]]
    max_favorable_excursion, max_adverse_excursion = _excursion_window(
        direction_bias=signal_snapshot.direction_bias,
        entry=signal_snapshot.entry,
        prices=prices,
    )
    guardian = evaluate_signal_guardian(
        signal_snapshot,
        GuardianContext(
            tick_prices=prices,
            ticks_since_armed=len(prices),
            max_favorable_excursion=max_favorable_excursion,
            max_adverse_excursion=max_adverse_excursion,
        ),
        DEFAULT_GUARDIAN_THRESHOLDS,
    )
    enriched["guardian_state"] = guardian.state
    enriched["guardian_reason"] = guardian.reason
    return enriched


def build_decision_summary(alert: dict[str, object]) -> str | None:
    call = str(alert.get("call", ""))
    trade_status = str(alert.get("trade_status", ""))
    why = str(alert.get("why", "")).strip()
    wait_for = str(alert.get("wait_for", "")).strip()

    if trade_status != "valid" or call not in {"buy_candidate", "sell_candidate"}:
        return None

    direction = "buy" if call == "buy_candidate" else "sell"
    return f"{direction} setup valid; {why}; {wait_for}"


def classify_alert_type(alert: dict[str, object]) -> str:
    call = str(alert.get("call", ""))
    trade_status = str(alert.get("trade_status", ""))
    if trade_status == "valid" and call in {"buy_candidate", "sell_candidate"}:
        return "setup_candidate"
    return "context_update"


def build_watch_state(snapshot: dict[str, object]) -> WatchState:
    confidence = float(snapshot.get("confidence", 0.0) or 0.0)
    if confidence >= 0.58:
        bucket = "above_threshold"
    elif confidence >= 0.50:
        bucket = "near_threshold"
    else:
        bucket = "low_confidence"
    alert_type = str(snapshot.get("alert_type", "") or "")
    if not alert_type:
        alert_type = classify_alert_type(snapshot)
    return WatchState(
        call=str(snapshot.get("call", "stand_aside")),
        alert_type=alert_type,
        trade_status=str(snapshot.get("trade_status", "not_valid")),
        direction_bias=str(snapshot.get("direction_bias", "none")),
        regime=str(snapshot.get("regime", "unknown")),
        confidence_bucket=bucket,
        wait_for=str(snapshot.get("wait_for", "")),
    )


def has_material_context_change(previous: WatchState, current: WatchState) -> bool:
    return (
        previous.regime != current.regime
        or previous.direction_bias != current.direction_bias
        or previous.trade_status != current.trade_status
        or previous.wait_for != current.wait_for
    )


def should_emit_watch_alert(
    previous: WatchState | None,
    current: WatchState,
    *,
    context_cooldown_remaining: int = 0,
) -> bool:
    if previous is None:
        return False
    if previous == current:
        return False
    if current.alert_type == "setup_candidate":
        return True
    if not has_material_context_change(previous, current):
        return False
    return context_cooldown_remaining <= 0


async def watch_live_ticks(
    *,
    symbol: str,
    app_id: str | None = None,
    max_live_ticks: int | None = None,
    max_minutes: int | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> list[Tick]:
    credentials = deriv_credentials_from_env(app_id=app_id)
    factory = client_factory or (lambda: DerivWebSocketClient(credentials))
    async with factory() as client:
        collected: list[Tick] = []
        deadline = None
        if max_minutes is not None:
            deadline = asyncio.get_running_loop().time() + max(0, max_minutes) * 60

        tick_iterator = client.subscribe_ticks(symbol).__aiter__()
        while True:
            try:
                if deadline is None:
                    tick = await tick_iterator.__anext__()
                else:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    tick = await asyncio.wait_for(tick_iterator.__anext__(), timeout=remaining)
            except (StopAsyncIteration, TimeoutError):
                break

            collected.append(tick)
            if max_live_ticks is not None and len(collected) >= max_live_ticks:
                break
    return collected


def analyze_live_snapshot(
    *,
    symbol: str,
    ticks: list[Tick],
    timeframe_sec: int,
    higher_timeframe_sec: int,
    config: TraderConfig,
) -> dict[str, object]:
    builder = MultiTimeframeCandleBuilder(symbol, [timeframe_sec, higher_timeframe_sec])
    histories: dict[int, list[object]] = {timeframe_sec: [], higher_timeframe_sec: []}

    for tick in ticks:
        closed = builder.update(tick)
        for timeframe, candle in closed.items():
            histories.setdefault(timeframe, []).append(candle)

    flushed = builder.flush()
    for timeframe, candle in flushed.items():
        histories.setdefault(timeframe, []).append(candle)

    primary_candles = histories.get(timeframe_sec, [])
    higher_timeframe_candles = histories.get(higher_timeframe_sec, [])
    current_close = primary_candles[-1].close if primary_candles else (ticks[-1].price if ticks else None)

    regime = "unknown"
    regime_explanation = "need more candle history to classify the market"
    structure_summary = "structure still forming"
    model_long_probability = None

    if primary_candles:
        feature_snapshot = build_snapshot(
            symbol=symbol,
            timeframe_sec=timeframe_sec,
            candles=primary_candles,
            higher_timeframe_candles=higher_timeframe_candles,
        )
        regime = feature_snapshot.regime.value
        regime_explanation = "; ".join(feature_snapshot.notes) or "regime is still neutral"
        structure_summary = _summarize_structure(dict(feature_snapshot.structure))
        model_long_probability = round(
            DecisionEngine(config).model.predict_proba(dict(feature_snapshot.features)),
            3,
        )

    decision_engine = DecisionEngine(config)
    report = decision_engine.evaluate(
        symbol=symbol,
        candles=primary_candles,
        higher_timeframe_candles=higher_timeframe_candles,
    )
    if report.signal is None:
        reasons = list(report.reasons)
        confidence = _extract_reason_value(reasons, r"confidence ([0-9.]+)") or 0.0
        inferred_model_probability = _extract_reason_value(reasons, r"model long probability ([0-9.]+)")
        if inferred_model_probability is not None:
            model_long_probability = round(inferred_model_probability, 3)
        direction_bias = _direction_bias_from_probability(model_long_probability)
        snapshot = {
            "call": "stand_aside",
            "trade_status": "not_valid",
            "direction_bias": direction_bias,
            "briefing": "current movement is active but not a clean setup yet",
            "symbol": symbol,
            "regime": regime,
            "regime_explanation": regime_explanation,
            "structure_summary": structure_summary,
            "confidence": confidence,
            "model_long_probability": model_long_probability,
            "current_close": current_close,
            "wait_for": _wait_for_next("not_valid", direction_bias, reasons),
            "reasons": reasons,
        }
        return build_guardian_snapshot(snapshot, ticks)

    risk_engine = RiskEngine(config.risk)
    risk_decision = risk_engine.evaluate(report.signal)
    reasons = list(risk_decision.reasons or report.signal.rationale)
    direction_bias = "buy" if report.signal.direction.value == "long" else "sell"
    call = (
        "buy_candidate"
        if risk_decision.approved and direction_bias == "buy"
        else "sell_candidate"
        if risk_decision.approved and direction_bias == "sell"
        else "stand_aside"
    )
    snapshot = {
        "call": call,
        "trade_status": "valid" if risk_decision.approved else "not_valid",
        "direction_bias": direction_bias,
        "briefing": "; ".join(report.signal.rationale[:2]),
        "symbol": symbol,
        "regime": report.signal.snapshot.regime.value,
        "regime_explanation": "; ".join(report.signal.snapshot.notes) or "regime is still neutral",
        "structure_summary": _summarize_structure(dict(report.signal.snapshot.structure)),
        "confidence": round(report.signal.confidence, 3),
        "model_long_probability": round(
            DecisionEngine(config).model.predict_proba(dict(report.signal.snapshot.features)),
            3,
        ),
        "model_version": report.signal.model_version,
        "current_close": current_close,
        "entry": report.signal.entry,
        "stop_loss": report.signal.stop_loss,
        "take_profit": report.signal.take_profit,
        "reward_risk": round(report.signal.reward_risk, 3),
        "wait_for": _wait_for_next("valid" if risk_decision.approved else "not_valid", direction_bias, reasons),
        "reasons": reasons,
        **_format_trade_areas(
            report.signal.entry,
            report.signal.stop_loss,
            report.signal.take_profit,
        ),
    }
    return build_guardian_snapshot(snapshot, ticks)


async def run_live_snapshot(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    max_live_ticks: int,
    app_id: str | None = None,
) -> dict[str, object]:
    ticks = await collect_live_snapshot_ticks(
        symbol=symbol,
        warmup_count=warmup_count,
        max_live_ticks=max_live_ticks,
        app_id=app_id,
    )
    return analyze_live_snapshot(
        symbol=symbol,
        ticks=ticks,
        timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe_sec,
        config=TraderConfig.default(),
    )


def build_watch_alert(snapshot: dict[str, object]) -> dict[str, object]:
    alert = {
        "call": snapshot.get("call", "stand_aside"),
        "symbol": snapshot.get("symbol"),
        "why": snapshot.get("why", snapshot.get("briefing")),
        "wait_for": snapshot.get("wait_for"),
        "trade_status": snapshot.get("trade_status"),
        "direction_bias": snapshot.get("direction_bias"),
        "regime": snapshot.get("regime"),
        "confidence": snapshot.get("confidence"),
        "current_close": snapshot.get("current_close"),
        "guardian_state": snapshot.get("guardian_state"),
        "guardian_reason": snapshot.get("guardian_reason"),
        "reasons": snapshot.get("reasons"),
        "entry_area": snapshot.get("entry_area"),
        "stop_area": snapshot.get("stop_area"),
        "target_area": snapshot.get("target_area"),
        "entry": snapshot.get("entry"),
        "stop_loss": snapshot.get("stop_loss"),
        "take_profit": snapshot.get("take_profit"),
        "reward_risk": snapshot.get("reward_risk"),
    }
    alert["alert_type"] = classify_alert_type(alert)
    decision_summary = build_decision_summary(alert)
    if decision_summary is not None:
        alert["decision_summary"] = decision_summary
    return {key: value for key, value in alert.items() if value is not None}


def append_watch_alert(path: Path, alert: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(alert) + "\n")


def build_suppressed_context_record(
    snapshot: dict[str, object],
    *,
    suppressed_after_context_cooldown: int,
) -> dict[str, object]:
    record = {
        "record_type": "suppressed_context",
        "symbol": snapshot.get("symbol"),
        "call": snapshot.get("call", "stand_aside"),
        "alert_type": "context_update",
        "trade_status": snapshot.get("trade_status"),
        "direction_bias": snapshot.get("direction_bias"),
        "regime": snapshot.get("regime"),
        "confidence": snapshot.get("confidence"),
        "why": snapshot.get("why", snapshot.get("briefing")),
        "wait_for": snapshot.get("wait_for"),
        "suppression_reason": "context_cooldown_active",
        "suppressed_after_context_cooldown": suppressed_after_context_cooldown,
    }
    return {key: value for key, value in record.items() if value is not None}


def build_watch_transport_record(
    *,
    symbol: str,
    event: str,
    reason: str,
    attempt: int | None = None,
    attempts: int | None = None,
    baseline_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    record = {
        "record_type": "watch_transport",
        "symbol": symbol,
        "event": event,
        "reason": reason,
        "attempt": attempt,
        "attempts": attempts,
    }
    if baseline_snapshot is not None:
        record.update(
            {
                "regime": baseline_snapshot.get("regime"),
                "direction_bias": baseline_snapshot.get("direction_bias"),
                "trade_status": baseline_snapshot.get("trade_status"),
                "confidence": baseline_snapshot.get("confidence"),
            }
        )
    return {key: value for key, value in record.items() if value is not None}


def is_watch_transport_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "client is not connected" in message
        or "keepalive" in message
        or "ping timeout" in message
        or "connection closed" in message
        or "socket" in message
    )


async def run_live_watch(
    *,
    symbol: str,
    warmup_count: int,
    timeframe_sec: int,
    higher_timeframe_sec: int,
    journal_path: str,
    emit_initial: bool = False,
    max_alerts: int | None = None,
    max_minutes: int | None = None,
    max_reconnects: int = 5,
    reconnect_backoff_sec: int = 1,
    app_id: str | None = None,
) -> list[dict[str, object]]:
    async def load_baseline_state() -> tuple[list[Tick], dict[str, object], WatchState]:
        history = await collect_live_snapshot_ticks(
            symbol=symbol,
            warmup_count=warmup_count,
            max_live_ticks=0,
            app_id=app_id,
        )
        baseline_snapshot = analyze_live_snapshot(
            symbol=symbol,
            ticks=history,
            timeframe_sec=timeframe_sec,
            higher_timeframe_sec=higher_timeframe_sec,
            config=TraderConfig.default(),
        )
        return history, baseline_snapshot, build_watch_state(baseline_snapshot)

    history, baseline_snapshot, previous_state = await load_baseline_state()
    alerts: list[dict[str, object]] = []
    buffer = list(history)
    journal = Path(journal_path)
    context_cooldown_remaining = 0
    reconnect_attempts = 0

    if emit_initial:
        initial_alert = build_watch_alert(baseline_snapshot)
        append_watch_alert(journal, initial_alert)
        alerts.append(initial_alert)
        if initial_alert.get("alert_type") == "context_update":
            context_cooldown_remaining = DEFAULT_CONTEXT_ALERT_COOLDOWN
        if max_alerts is not None and len(alerts) >= max_alerts:
            return alerts

    while True:
        try:
            ticks = await watch_live_ticks(symbol=symbol, app_id=app_id, max_minutes=max_minutes)
        except Exception as exc:
            if not is_watch_transport_error(exc):
                raise
            reconnect_attempts += 1
            append_watch_alert(
                journal,
                build_watch_transport_record(
                    symbol=symbol,
                    event="reconnect_attempt",
                    reason=str(exc),
                    attempt=reconnect_attempts,
                ),
            )
            if reconnect_attempts > max_reconnects:
                append_watch_alert(
                    journal,
                    build_watch_transport_record(
                        symbol=symbol,
                        event="reconnect_failed",
                        reason=str(exc),
                        attempts=reconnect_attempts,
                    ),
                )
                break
            await asyncio.sleep(min(max(reconnect_backoff_sec, 1) * reconnect_attempts, 10))
            history, baseline_snapshot, previous_state = await load_baseline_state()
            buffer = list(history)
            context_cooldown_remaining = 0
            append_watch_alert(
                journal,
                build_watch_transport_record(
                    symbol=symbol,
                    event="reconnect_rebaseline_ok",
                    reason="baseline rebuilt after reconnect",
                    attempt=reconnect_attempts,
                    baseline_snapshot=baseline_snapshot,
                ),
            )
            continue

        for tick in ticks:
            buffer.append(tick)
            bucket = int(tick.epoch // timeframe_sec) * timeframe_sec
            previous_bucket = int(buffer[-2].epoch // timeframe_sec) * timeframe_sec if len(buffer) > 1 else bucket
            if bucket == previous_bucket:
                continue
            if context_cooldown_remaining > 0:
                context_cooldown_remaining -= 1

            snapshot = analyze_live_snapshot(
                symbol=symbol,
                ticks=buffer,
                timeframe_sec=timeframe_sec,
                higher_timeframe_sec=higher_timeframe_sec,
                config=TraderConfig.default(),
            )
            current_state = build_watch_state(snapshot)
            should_emit = should_emit_watch_alert(
                previous_state,
                current_state,
                context_cooldown_remaining=context_cooldown_remaining,
            )
            if should_emit:
                alert = build_watch_alert(snapshot)
                append_watch_alert(journal, alert)
                alerts.append(alert)
                if current_state.alert_type == "context_update":
                    context_cooldown_remaining = DEFAULT_CONTEXT_ALERT_COOLDOWN
                previous_state = current_state
                if max_alerts is not None and len(alerts) >= max_alerts:
                    return alerts
            else:
                if (
                    previous_state is not None
                    and current_state.alert_type == "context_update"
                    and has_material_context_change(previous_state, current_state)
                    and context_cooldown_remaining > 0
                ):
                    suppressed_record = build_suppressed_context_record(
                        snapshot,
                        suppressed_after_context_cooldown=context_cooldown_remaining,
                    )
                    append_watch_alert(journal, suppressed_record)
                previous_state = current_state
        break

    return alerts


def render_live_snapshot_text(snapshot: dict[str, object]) -> str:
    briefing_keys = [
        "trade_status",
        "direction_bias",
        "briefing",
    ]
    structured_keys = [
        "symbol",
        "regime",
        "regime_explanation",
        "structure_summary",
        "confidence",
        "model_long_probability",
        "model_version",
        "current_close",
        "guardian_state",
        "guardian_reason",
        "wait_for",
        "reasons",
    ]
    lines: list[str] = []
    for key in briefing_keys + structured_keys:
        if key in snapshot:
            lines.append(f"{key}={snapshot.get(key)}")
    return "\n".join(lines)


def render_live_watch_alert_text(alert: dict[str, object]) -> str:
    ordered = [
        "decision_summary",
        "alert_type",
        "call",
        "symbol",
        "why",
        "wait_for",
        "entry_area",
        "stop_area",
        "target_area",
        "entry",
        "stop_loss",
        "take_profit",
        "reward_risk",
        "trade_status",
        "direction_bias",
        "regime",
        "confidence",
        "current_close",
        "guardian_state",
        "guardian_reason",
        "reasons",
    ]
    return "\n".join(f"{key}={alert.get(key)}" for key in ordered if key in alert)


def build_live_watch_review_snapshot(
    *,
    journal_path: Path,
    symbol: str | None = None,
    limit: int = 5,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> dict[str, object]:
    alerts, suppressed, transport = load_live_watch_journal_records(journal_path)
    filtered = filter_live_watch_alerts(
        alerts,
        symbol=symbol,
        call_filter=call_filter,
        valid_only=valid_only,
    )
    filtered_suppressed = filter_suppressed_context_records(
        suppressed,
        symbol=symbol,
        call_filter=call_filter,
        valid_only=valid_only,
    )
    filtered_transport = filter_watch_transport_records(transport, symbol=symbol)
    recent = list(reversed(filtered[-max(limit, 0) :]))
    latest = filtered[-1] if filtered else {}
    latest_suppressed = filtered_suppressed[-1] if filtered_suppressed else {}
    latest_transport = filtered_transport[-1] if filtered_transport else {}
    return {
        "latest_call": latest.get("call"),
        "latest_symbol": latest.get("symbol"),
        "latest_trade_status": latest.get("trade_status"),
        "latest_direction_bias": latest.get("direction_bias"),
        "latest_regime": latest.get("regime"),
        "latest_confidence": latest.get("confidence"),
        "latest_current_close": latest.get("current_close"),
        "latest_wait_for": latest.get("wait_for"),
        "alert_count": len(filtered),
        "suppressed_context_count": len(filtered_suppressed),
        "latest_suppressed_symbol": latest_suppressed.get("symbol"),
        "latest_suppressed_call": latest_suppressed.get("call"),
        "latest_suppressed_direction_bias": latest_suppressed.get("direction_bias"),
        "latest_suppressed_regime": latest_suppressed.get("regime"),
        "latest_suppressed_why": latest_suppressed.get("why"),
        "latest_suppressed_wait_for": latest_suppressed.get("wait_for"),
        "latest_suppressed_confidence": latest_suppressed.get("confidence"),
        "transport_event_count": len(filtered_transport),
        "latest_transport_event": latest_transport.get("event"),
        "latest_transport_reason": latest_transport.get("reason"),
        "latest_transport_attempt": latest_transport.get("attempt"),
        "latest_transport_attempts": latest_transport.get("attempts"),
        "latest_transport_regime": latest_transport.get("regime"),
        "latest_transport_direction_bias": latest_transport.get("direction_bias"),
        "latest_transport_trade_status": latest_transport.get("trade_status"),
        "latest_transport_confidence": latest_transport.get("confidence"),
        "alerts": recent,
    }


def render_live_watch_review_text(snapshot: dict[str, object]) -> str:
    ordered = [
        "latest_call",
        "latest_symbol",
        "latest_trade_status",
        "latest_direction_bias",
        "latest_regime",
        "latest_confidence",
        "latest_current_close",
        "latest_wait_for",
        "alert_count",
        "suppressed_context_count",
        "latest_suppressed_direction_bias",
        "latest_suppressed_regime",
        "latest_suppressed_why",
        "latest_suppressed_wait_for",
        "transport_event_count",
        "latest_transport_event",
        "latest_transport_reason",
        "latest_transport_attempt",
        "latest_transport_attempts",
        "latest_transport_regime",
        "latest_transport_direction_bias",
        "latest_transport_trade_status",
        "latest_transport_confidence",
    ]
    lines = [
        f"review_{key}={snapshot.get(key)}"
        for key in ordered
    ]
    alerts = snapshot.get("alerts", [])
    if isinstance(alerts, list) and alerts:
        lines.append("review_recent_alerts=")
        for alert in alerts:
            lines.append(render_live_watch_alert_text(alert))
    return "\n".join(lines)


def load_live_watch_journal_records(
    journal_path: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    alerts: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []
    transport: list[dict[str, object]] = []
    for index, line in enumerate(journal_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid journal JSON at line {index}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            continue
        record_type = payload.get("record_type")
        if record_type == "suppressed_context" and payload.get("symbol") is not None:
            suppressed.append(payload)
        elif record_type == "watch_transport" and payload.get("symbol") is not None:
            transport.append(payload)
        elif payload.get("call") is not None and payload.get("symbol") is not None:
            alerts.append(payload)
    return alerts, suppressed, transport


def load_live_watch_alerts(journal_path: Path) -> list[dict[str, object]]:
    alerts, _suppressed, _transport = load_live_watch_journal_records(journal_path)
    return alerts


def filter_watch_transport_records(
    records: list[dict[str, object]],
    *,
    symbol: str | None = None,
) -> list[dict[str, object]]:
    filtered = list(records)
    if symbol is not None:
        filtered = [record for record in filtered if record.get("symbol") == symbol]
    return filtered


def filter_suppressed_context_records(
    records: list[dict[str, object]],
    *,
    symbol: str | None = None,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> list[dict[str, object]]:
    filtered = list(records)
    if symbol is not None:
        filtered = [record for record in filtered if record.get("symbol") == symbol]
    if call_filter is not None:
        filtered = [record for record in filtered if record.get("call") == call_filter]
    if valid_only:
        return []
    return filtered


def filter_live_watch_alerts(
    alerts: list[dict[str, object]],
    *,
    symbol: str | None = None,
    call_filter: str | None = None,
    valid_only: bool = False,
) -> list[dict[str, object]]:
    filtered = list(alerts)
    if symbol is not None:
        filtered = [alert for alert in filtered if alert.get("symbol") == symbol]
    if call_filter is not None:
        filtered = [alert for alert in filtered if alert.get("call") == call_filter]
    if valid_only:
        filtered = [alert for alert in filtered if alert.get("trade_status") == "valid"]
    return filtered
