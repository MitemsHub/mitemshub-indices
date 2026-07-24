from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def build_call_record(alert: dict[str, object]) -> dict[str, object]:
    logged_at = datetime.now(timezone.utc).isoformat()
    return {
        "recorded_at": logged_at,
        "symbol": alert.get("symbol"),
        "generated_at": alert.get("generated_at") or logged_at,
        "call": alert.get("call"),
        "trade_status": alert.get("trade_status"),
        "alert_type": alert.get("alert_type"),
        "guardian_state": alert.get("guardian_state"),
        "guardian_reason": alert.get("guardian_reason"),
        "direction_bias": alert.get("direction_bias"),
        "regime": alert.get("regime"),
        "trigger_type": alert.get("execution_trigger_type", alert.get("alert_type")),
        "confidence": alert.get("confidence"),
        "entry": alert.get("entry"),
        "execution_stop": alert.get("execution_stop"),
        "primary_target": alert.get("primary_target"),
        "thesis_invalidation": alert.get("thesis_invalidation"),
        "hold_horizon_minutes": alert.get("hold_horizon_minutes"),
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
