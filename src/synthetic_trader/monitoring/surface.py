from __future__ import annotations

from typing import Any


MT5_EVENT_TYPES = {
    "mt5_runtime_summary",
    "mt5_sync_summary",
    "mt5_reconcile_summary",
    "mt5_close_result",
    "mt5_modify_result",
    "mt5_live_entry_result",
    "mt5_live_shutdown_reconcile",
    "mt5_live_fail_closed",
}


def filter_mt5_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if str(event.get("type")) in MT5_EVENT_TYPES]


def build_mt5_monitor_snapshot(
    *,
    events: list[dict[str, Any]],
    symbol: str | None = None,
) -> dict[str, Any]:
    filtered = filter_mt5_events(events)
    if symbol is not None:
        filtered = [event for event in filtered if event.get("symbol") == symbol]

    snapshot: dict[str, Any] = {
        "symbol": None,
        "venue_symbol": None,
        "runtime_ready": False,
        "runtime_failures": [],
        "positions": 0,
        "sync_failures": [],
        "reconcile_actionable": False,
        "reconcile_target_ticket": None,
        "reconcile_failures": [],
        "last_close_ticket": None,
        "last_close_accepted": False,
        "last_close_retcode": None,
        "last_close_message": "",
        "last_modify_ticket": None,
        "last_modify_accepted": False,
        "last_modify_retcode": None,
        "last_modify_message": "",
        "last_live_entry_accepted": False,
        "last_live_entry_retcode": None,
        "last_live_entry_message": "",
        "last_fail_closed_reason": "",
    }

    for event in filtered:
        event_type = event.get("type")
        if event.get("symbol") is not None:
            snapshot["symbol"] = event.get("symbol")
        if event.get("venue_symbol") is not None:
            snapshot["venue_symbol"] = event.get("venue_symbol")

        if event_type == "mt5_runtime_summary":
            snapshot["runtime_ready"] = bool(event.get("ready", False))
            snapshot["runtime_failures"] = list(event.get("failures", []))
        elif event_type == "mt5_sync_summary":
            snapshot["positions"] = int(event.get("positions", 0))
            snapshot["sync_failures"] = list(event.get("failures", []))
        elif event_type == "mt5_reconcile_summary":
            snapshot["reconcile_actionable"] = bool(event.get("actionable", False))
            snapshot["reconcile_target_ticket"] = event.get("target_ticket")
            snapshot["reconcile_failures"] = list(event.get("failures", []))
        elif event_type == "mt5_close_result":
            snapshot["last_close_ticket"] = event.get("ticket")
            snapshot["last_close_accepted"] = bool(event.get("accepted", False))
            snapshot["last_close_retcode"] = event.get("retcode")
            snapshot["last_close_message"] = str(event.get("message", ""))
        elif event_type == "mt5_modify_result":
            snapshot["last_modify_ticket"] = event.get("ticket")
            snapshot["last_modify_accepted"] = bool(event.get("accepted", False))
            snapshot["last_modify_retcode"] = event.get("retcode")
            snapshot["last_modify_message"] = str(event.get("message", ""))
        elif event_type == "mt5_live_entry_result":
            snapshot["last_live_entry_accepted"] = bool(event.get("accepted", False))
            snapshot["last_live_entry_retcode"] = event.get("retcode")
            snapshot["last_live_entry_message"] = str(event.get("message", ""))
        elif event_type == "mt5_live_fail_closed":
            snapshot["last_fail_closed_reason"] = str(event.get("reason", ""))

    return snapshot


def build_monitor_snapshot(*, live_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": live_summary.get("symbol"),
        "signals": live_summary.get("signals", 0),
        "approved_signals": live_summary.get("approved_signals", 0),
        "rejected_signals": live_summary.get("rejected_signals", 0),
        "session_resets": live_summary.get("session_resets", 0),
        "shutdown_closed_trades": live_summary.get("shutdown_closed_trades", 0),
    }


def build_validation_snapshot(
    *,
    venue: str,
    mode: str,
    live_summary: object,
    latency_summary: dict[str, Any] | None = None,
    armed_confirmation: bool = False,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "venue": venue,
        "mode": mode,
        "armed_confirmation": armed_confirmation,
        "symbol": getattr(live_summary, "symbol"),
        "warmup_ticks": getattr(live_summary, "warmup_ticks"),
        "live_ticks": getattr(live_summary, "live_ticks"),
        "signals": getattr(live_summary, "signals"),
        "approved_signals": getattr(live_summary, "approved_signals"),
        "rejected_signals": getattr(live_summary, "rejected_signals"),
        "closed_trades": getattr(live_summary, "closed_trades"),
        "shutdown_closed_trades": getattr(live_summary, "shutdown_closed_trades"),
        "unresolved_positions": getattr(live_summary, "unresolved_positions"),
        "finalized": getattr(live_summary, "finalized"),
        "final_equity": getattr(live_summary, "final_equity"),
        "model_version": getattr(live_summary, "model_version"),
    }
    if latency_summary is not None:
        snapshot["latency_total_ms"] = latency_summary.get("total_duration_ms")
    return snapshot


def build_rollout_status_snapshot(
    *,
    venue: str,
    symbol: str,
    live_mode: str,
    readiness_ok: bool,
    readiness_failures: tuple[str, ...],
    validation_snapshot: dict[str, Any] | None = None,
    mt5_snapshot: dict[str, Any] | None = None,
    mt5_runtime_ready: bool | None = None,
    mt5_runtime_failures: tuple[str, ...] = (),
    mt5_venue_symbol: str | None = None,
    armed_confirmation: bool = False,
) -> dict[str, Any]:
    validation_snapshot = validation_snapshot or {}
    mt5_snapshot = mt5_snapshot or {}
    return {
        "rollout_stage": (
            "dry-run-preflight" if live_mode == "dry-run-live" else "armed-live-preflight"
        ),
        "venue": venue,
        "symbol": symbol,
        "live_mode": live_mode,
        "armed_confirmation": armed_confirmation,
        "readiness_ok": readiness_ok,
        "readiness_failures": list(readiness_failures),
        "validation_finalized": bool(validation_snapshot.get("finalized", False)),
        "validation_final_equity": validation_snapshot.get("final_equity"),
        "validation_model_version": validation_snapshot.get("model_version"),
        "mt5_runtime_ready": (
            bool(mt5_snapshot.get("runtime_ready", False))
            if mt5_runtime_ready is None
            else mt5_runtime_ready
        ),
        "mt5_runtime_failures": list(mt5_runtime_failures),
        "mt5_venue_symbol": mt5_venue_symbol,
        "mt5_positions": int(mt5_snapshot.get("positions", 0)),
        "mt5_sync_failures": list(mt5_snapshot.get("sync_failures", [])),
    }


def render_rollout_status_text(snapshot: dict[str, Any]) -> str:
    ordered_keys = [
        "rollout_stage",
        "venue",
        "symbol",
        "live_mode",
        "armed_confirmation",
        "readiness_ok",
        "readiness_failures",
        "validation_finalized",
        "validation_final_equity",
        "validation_model_version",
        "mt5_runtime_ready",
        "mt5_runtime_failures",
        "mt5_venue_symbol",
        "mt5_positions",
        "mt5_sync_failures",
    ]
    lines: list[str] = []
    for key in ordered_keys:
        if key not in snapshot:
            continue
        prefix = key if key == "rollout_stage" else f"rollout_{key}"
        lines.append(f"{prefix}={snapshot.get(key)}")
    return "\n".join(lines)


def render_validation_text(snapshot: dict[str, Any]) -> str:
    ordered_keys = [
        "venue",
        "mode",
        "armed_confirmation",
        "symbol",
        "warmup_ticks",
        "live_ticks",
        "signals",
        "approved_signals",
        "rejected_signals",
        "closed_trades",
        "shutdown_closed_trades",
        "unresolved_positions",
        "finalized",
        "final_equity",
        "model_version",
        "latency_total_ms",
    ]
    return "\n".join(
        f"validation_{key}={snapshot.get(key)}"
        for key in ordered_keys
        if key in snapshot
    )


def render_mt5_monitor_text(snapshot: dict[str, Any]) -> str:
    ordered_keys = [
        "symbol",
        "venue_symbol",
        "runtime_ready",
        "runtime_failures",
        "positions",
        "sync_failures",
        "reconcile_actionable",
        "reconcile_target_ticket",
        "reconcile_failures",
        "last_close_ticket",
        "last_close_accepted",
        "last_close_retcode",
        "last_close_message",
        "last_modify_ticket",
        "last_modify_accepted",
        "last_modify_retcode",
        "last_modify_message",
        "last_live_entry_accepted",
        "last_live_entry_retcode",
        "last_live_entry_message",
        "last_fail_closed_reason",
    ]
    return "\n".join(f"mt5_{key}={snapshot.get(key)}" for key in ordered_keys)


def render_monitor_text(snapshot: dict[str, Any]) -> str:
    return "\n".join(f"{key}={value}" for key, value in snapshot.items())
