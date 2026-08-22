"""Live EA Monitoring Dashboard

Polls the MQL5 EA state files and pending call files to render a real-time
terminal dashboard showing position status, P&L, risk halt status, and
pending signals for both R_75 and R_100.

Usage:
    python -m synthetic_trader.live.dashboard
    python -m synthetic_trader.live.dashboard --interval 5
    python -m synthetic_trader.live.dashboard --once
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from synthetic_trader.execution.ea_emitter import (
    call_file_path,
    mt5_common_files_dir,
    read_ea_state,
    state_file_path,
)


SYMBOLS = ("R_75", "R_100")
DEFAULT_POLL_INTERVAL = 3  # seconds


@dataclass
class SymbolStatus:
    """Parsed status for one symbol's EA."""
    symbol: str
    # State file fields
    call_id: str = ""
    status: str = "no_file"
    updated_at_epoch: float = 0
    open_ticket: int = 0
    open_price: float = 0.0
    open_sl: float = 0.0
    mfe: float = 0.0
    consecutive_losses: int = 0
    peak_equity: float = 0.0
    halted_daily: bool = False
    halted_consecutive: bool = False
    halted_equity_dd: bool = False
    # Call file (pending order)
    pending_call: dict[str, Any] | None = None
    # Derived
    file_age_sec: float = 0
    is_stale: bool = False
    has_position: bool = False
    open_pnl_r: float = 0.0


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def read_call_file(symbol: str, files_dir: Path | None = None) -> dict[str, Any] | None:
    """Read the pending call file for a symbol (Python -> EA)."""
    path = call_file_path(symbol, files_dir)
    return _read_json(path)


def parse_symbol_status(symbol: str, files_dir: Path | None = None) -> SymbolStatus:
    """Read and parse all state for one symbol."""
    now = time.time()
    ss = SymbolStatus(symbol=symbol)

    # EA state file
    state = read_ea_state(symbol, files_dir=files_dir)
    if state is not None:
        ss.call_id = state.get("call_id", "")
        ss.status = state.get("status", "unknown")
        ss.updated_at_epoch = state.get("updated_at_epoch", 0)
        ss.open_ticket = state.get("open_ticket", 0)
        ss.open_price = state.get("open_price", 0.0)
        ss.open_sl = state.get("open_sl", 0.0)
        ss.mfe = state.get("mfe", 0.0)
        ss.consecutive_losses = state.get("consecutive_losses", 0)
        ss.peak_equity = state.get("peak_equity", 0.0)
        halted = state.get("halted", {})
        if isinstance(halted, dict):
            ss.halted_daily = halted.get("daily", False)
            ss.halted_consecutive = halted.get("consecutive", False)
            ss.halted_equity_dd = halted.get("equity_dd", False)
        ss.file_age_sec = now - ss.updated_at_epoch if ss.updated_at_epoch > 0 else 9999
        ss.is_stale = ss.file_age_sec > 300  # stale after 5 minutes
        ss.has_position = ss.open_ticket > 0
        # Compute open P&L in R units (from MFE which tracks max excursion)
        # We approximate from the state — actual P&L needs current price
    else:
        ss.status = "no_file"
        ss.file_age_sec = 9999
        ss.is_stale = True

    # Pending call file
    ss.pending_call = read_call_file(symbol, files_dir)
    if ss.pending_call is not None:
        # Check expiry
        expiry = ss.pending_call.get("expiry_epoch", 0)
        if expiry > 0 and now > expiry:
            ss.pending_call = None  # expired

    return ss


def render_dashboard(
    statuses: list[SymbolStatus],
    cycle: int = 0,
    files_dir: Path | None = None,
) -> str:
    """Render the full dashboard as a string."""
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    lines: list[str] = []

    # Header
    lines.append("")
    lines.append("=" * 90)
    lines.append(f"  SYNTHETIC INDICES LIVE DASHBOARD       {now}       Cycle #{cycle}")
    lines.append("=" * 90)

    # Connection info
    resolved_dir = files_dir or mt5_common_files_dir()
    lines.append(f"  EA Files Dir: {resolved_dir}")
    lines.append("")

    for ss in statuses:
        lines.append(f"  +{'-' * 86}+")
        lines.append(f"  | {ss.symbol:^84} |")
        lines.append(f"  +{'-' * 86}+")

        # Connection status
        if ss.status == "no_file":
            conn = "NO STATE FILE"
            conn_color = "RED"
        elif ss.is_stale:
            age_m = ss.file_age_sec / 60
            conn = f"STALE ({age_m:.0f}m ago)"
            conn_color = "YELLOW"
        else:
            age_s = ss.file_age_sec
            conn = f"LIVE ({age_s:.0f}s ago)"
            conn_color = "GREEN"

        lines.append(f"  |  Connection:  {conn:<30} Status: {ss.status:<20} |")

        # Position status
        if ss.has_position:
            pos_str = f"TICKET #{ss.open_ticket}"
            pos_detail = f"Entry: {ss.open_price:.5f}  SL: {ss.open_sl:.5f}  MFE: {ss.mfe:+.2f}R"
        else:
            pos_str = "FLAT (no open position)"
            pos_detail = ""

        lines.append(f"  |  Position:    {pos_str:<30} {pos_detail:<30} |")

        # Call ID
        if ss.call_id:
            lines.append(f"  |  Last Call:   {ss.call_id:<56} |")

        # Pending call
        if ss.pending_call is not None:
            pc = ss.pending_call
            direction = pc.get("direction", "?").upper()
            entry = pc.get("entry", 0)
            sl = pc.get("stop_loss", 0)
            tp = pc.get("take_profit", 0)
            vol = pc.get("volume", 0)
            evidence = pc.get("evidence_status", "?")
            rr = pc.get("reward_risk", 0)
            expiry = pc.get("expiry_epoch", 0)
            ttl = max(0, expiry - time.time()) if expiry > 0 else 0

            lines.append(f"  |  PENDING ORDER:                                                         |")
            lines.append(f"  |    {direction}  Entry: {entry:.5f}  SL: {sl:.5f}  TP: {tp:.5f}  Vol: {vol}  |")
            lines.append(f"  |    R:R: {rr:.2f}  Evidence: {evidence}  TTL: {ttl:.0f}s                          |")
        else:
            lines.append(f"  |  Pending:     (none)                                                     |")

        # Risk halt status
        halts = []
        if ss.halted_daily:
            halts.append("DAILY LOSS")
        if ss.halted_consecutive:
            halts.append("CONSECUTIVE LOSS")
        if ss.halted_equity_dd:
            halts.append("EQUITY DD")

        if halts:
            halt_str = " | ".join(halts)
            lines.append(f"  |  HALTED:      *** {halt_str:<65} |")
        else:
            lines.append(f"  |  Risk Halt:   OK (no halts active)                                        |")

        # Stats
        lines.append(f"  |  Consec Loss: {ss.consecutive_losses:<10} Peak Equity: ${ss.peak_equity:<15.2f} |")

        lines.append(f"  |{' ' * 86}|")

    # Footer
    lines.append(f"  +{'-' * 86}+")
    lines.append("")
    lines.append("  Legend: LIVE=state file current | STALE=no update >5min | FLAT=no open position")
    lines.append("  HALT types: DAILY LOSS=daily loss limit | CONSECUTIVE=loss streak | EQUITY DD=drawdown limit")
    lines.append("")

    return "\n".join(lines)


def run_dashboard(
    interval: float = DEFAULT_POLL_INTERVAL,
    once: bool = False,
    files_dir: Path | None = None,
) -> None:
    """Run the live dashboard loop."""
    cycle = 0

    try:
        while True:
            cycle += 1
            statuses = [parse_symbol_status(s, files_dir) for s in SYMBOLS]
            output = render_dashboard(statuses, cycle, files_dir)

            # Clear screen and render
            os.system("cls" if os.name == "nt" else "clear")
            print(output)

            if once:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n  Dashboard stopped.")
        sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live EA monitoring dashboard")
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Print one snapshot and exit (no loop)",
    )
    parser.add_argument(
        "--files-dir", type=str, default=None,
        help="Override MT5 Common Files directory",
    )
    args = parser.parse_args(argv)

    files_dir = Path(args.files_dir) if args.files_dir else None
    run_dashboard(interval=args.interval, once=args.once, files_dir=files_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
