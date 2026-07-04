from __future__ import annotations


def build_monitor_snapshot(*, live_summary: dict[str, object]) -> dict[str, object]:
    return {
        "symbol": live_summary.get("symbol"),
        "signals": live_summary.get("signals", 0),
        "approved_signals": live_summary.get("approved_signals", 0),
        "rejected_signals": live_summary.get("rejected_signals", 0),
        "session_resets": live_summary.get("session_resets", 0),
        "shutdown_closed_trades": live_summary.get("shutdown_closed_trades", 0),
    }


def render_monitor_text(snapshot: dict[str, object]) -> str:
    return "\n".join(f"{key}={value}" for key, value in snapshot.items())
