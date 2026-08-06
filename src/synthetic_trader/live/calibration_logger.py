from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def build_call_record(alert: dict[str, object]) -> dict[str, object]:
    logged_at = datetime.now(timezone.utc).isoformat()
    # A suppressed call is downgraded to stand_aside for the operator, but the
    # journal must keep the ORIGINAL intent so outcome scoring measures what
    # the engine actually wanted to trade.
    stage3 = alert.get("stage3")
    suppressed_call = stage3.get("suppressed_call") if isinstance(stage3, dict) else None
    call = suppressed_call or alert.get("call")
    # Level aliases: the main ``build_watch_alert`` path sets
    # ``execution_stop``/``primary_target`` (plus ``stop_loss``/``take_profit``
    # mirrors), while the prepared-state path only sets ``stop_loss``/
    # ``take_profit``.  Resolving both key names here guarantees the calls
    # journal always persists scorable levels no matter which builder emitted
    # the alert -- otherwise every scored outcome would be target=stop=0%.
    execution_stop = alert.get("execution_stop")
    if execution_stop is None:
        execution_stop = alert.get("stop_loss")
    primary_target = alert.get("primary_target")
    if primary_target is None:
        primary_target = alert.get("take_profit")
    hold_horizon_minutes = alert.get("hold_horizon_minutes")
    if hold_horizon_minutes is None:
        hold_horizon_minutes = alert.get("hold_horizon") or 60
    return {
        "recorded_at": logged_at,
        "symbol": alert.get("symbol"),
        "generated_at": alert.get("generated_at") or logged_at,
        "call": call,
        "trade_status": alert.get("trade_status"),
        "alert_type": alert.get("alert_type"),
        "guardian_state": alert.get("guardian_state"),
        "guardian_reason": alert.get("guardian_reason"),
        "direction_bias": alert.get("direction_bias"),
        "regime": alert.get("regime"),
        "trigger_type": alert.get("execution_trigger_type", alert.get("alert_type")),
        "confidence": alert.get("confidence"),
        "entry": alert.get("entry"),
        "execution_stop": execution_stop,
        "primary_target": primary_target,
        "thesis_invalidation": alert.get("thesis_invalidation"),
        "hold_horizon_minutes": hold_horizon_minutes,
        "why": alert.get("why"),
        "wait_for": alert.get("wait_for"),
        "decision_summary": alert.get("decision_summary"),
        "invalidates_if": alert.get("invalidates_if"),
        "current_close": alert.get("current_close"),
        "model_version": alert.get("model_version"),
    }


def append_call_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
