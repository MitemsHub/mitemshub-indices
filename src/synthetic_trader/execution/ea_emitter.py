"""Emit approved calls to the MQL5 ``SynthCallExecutor`` EA.

Architecture (Python = quant research lab, MQL5 = production executor):

- Python computes the call (EGARCH band geometry, Stage-3 gate) and writes a
  tiny JSON call file into the MT5 **Common Files** folder
  (``%APPDATA%\\MetaQuotes\\Terminal\\Common\\Files``), which every terminal
  instance on the machine can read via the ``FILE_COMMON`` flag.
- The EA attached to the SYN75/SYN100 chart polls that file on a 1-second
  ``OnTimer``, and — when the call is ``proven`` and the levels are sane —
  places a market order with broker SL/TP at native tick speed.
- The EA writes ``synth_ea_state_<symbol>.json`` back so the dashboard and
  the outcomes journal can see exactly what executed (ticket, fill price,
  status) — closing the loop without any Python->MT5 IPC in the hot path.

Only ``evidence_status == "proven"`` calls are ever emitted (unless
``require_proven=False`` for a paper/harness run).  Writes are atomic
(tmp + ``os.replace``) so the EA never reads a half-written file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Default EA magic (mirrors SynthCallExecutor.mq5 input InpMagic).
EA_DEFAULT_MAGIC = 7788123

# File names, per symbol, inside the MT5 Common Files folder.
CALL_FILE_TMPL = "synth_calls_{symbol}.json"
STATE_FILE_TMPL = "synth_ea_state_{symbol}.json"

_CALL_VERSION = 1


def mt5_common_files_dir() -> Path:
    """Resolve the MT5 Common Files folder (env override wins)."""
    override = os.environ.get("SYNTH_EA_FILES_DIR")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    # Fallback for non-Windows / test environments: keep it repo-local.
    return Path("data") / "ea_files"


def call_file_path(symbol: str, files_dir: Path | None = None) -> Path:
    return (files_dir or mt5_common_files_dir()) / CALL_FILE_TMPL.format(symbol=symbol)


def state_file_path(symbol: str, files_dir: Path | None = None) -> Path:
    return (files_dir or mt5_common_files_dir()) / STATE_FILE_TMPL.format(symbol=symbol)


def build_call_record(
    alert: dict[str, Any],
    *,
    symbol: str,
    venue_symbol: str,
    volume: float,
    magic: int = EA_DEFAULT_MAGIC,
    expiry_epoch: float | None = None,
    call_id: str | None = None,
) -> dict[str, Any]:
    """Build the EA call record from a Stage-3-gated watch alert.

    Reads the same level aliases the calls journal uses (``execution_stop`` /
    ``primary_target`` with ``stop_loss`` / ``take_profit`` fallbacks) so the
    record always carries scorable levels.
    """
    direction = alert.get("direction_bias")
    if direction not in ("buy", "sell"):
        call = alert.get("call")
        if call == "buy_candidate":
            direction = "buy"
        elif call == "sell_candidate":
            direction = "sell"
    if direction not in ("buy", "sell"):
        raise ValueError(f"alert has no tradable direction: {direction!r}")

    stop = alert.get("execution_stop")
    if stop is None:
        stop = alert.get("stop_loss")
    target = alert.get("primary_target")
    if target is None:
        target = alert.get("take_profit")
    entry = alert.get("entry")

    hold_min = alert.get("hold_horizon_minutes")
    if hold_min is None:
        hold_min = alert.get("hold_horizon") or 60
    horizon_sec = int(hold_min) * 60

    if call_id is None:
        call_id = make_ea_call_id(symbol, alert.get("generated_at"), direction)

    issued_at = time.time()
    if expiry_epoch is None:
        expiry_epoch = issued_at + horizon_sec

    return {
        "version": _CALL_VERSION,
        "call_id": call_id,
        "symbol": symbol,
        "venue_symbol": venue_symbol,
        "direction": direction,
        "entry": float(entry) if entry is not None else None,
        "stop_loss": float(stop) if stop is not None else None,
        "take_profit": float(target) if target is not None else None,
        "volume": float(volume),
        "magic": int(magic),
        "issued_at_epoch": round(issued_at, 3),
        "expiry_epoch": round(float(expiry_epoch), 3),
        "horizon_sec": int(horizon_sec),
        "evidence_status": _evidence_status(alert),
        "reward_risk": alert.get("reward_risk"),
    }


def _evidence_status(alert: dict[str, Any]) -> str:
    stage3 = alert.get("stage3")
    if isinstance(stage3, dict) and stage3.get("evidence_status"):
        return str(stage3["evidence_status"])
    return str(alert.get("evidence_status") or "no_data")


def make_ea_call_id(symbol: str, generated_at: object, direction: str) -> str:
    """Deterministic EA call id: ``SYMBOL_<iso>_<dir>`` (mirrors make_signal_id).

    ``generated_at`` is the call's birth time; when absent (raw snapshots do
    not always carry it) fall back to the current wall clock so two calls for
    the same symbol+direction never collide — a constant id would let the EA's
    ``g_lastCallId`` dedupe suppress every later call of that type.
    """
    iso = str(generated_at or "").strip()
    if not iso:
        # Sub-second granularity so two different calls emitted within the
        # same second (e.g. two polls in quick succession) never collide — a
        # second-granular fallback would give them the same id and the EA's
        # dedupe would suppress the second trade.
        iso = time.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int((time.time() % 1) * 1000):03d}"
    for ch in (":", ".", " ", "T"):
        iso = iso.replace(ch, "-")
    return f"{symbol}_{iso}_{direction}"


def _record_is_tradeable(record: dict[str, Any]) -> tuple[bool, str]:
    """Validate levels are present, ordered, and sane for execution."""
    entry, stop, target = record["entry"], record["stop_loss"], record["take_profit"]
    if None in (entry, stop, target):
        return False, "missing levels"
    if entry <= 0 or stop <= 0 or target <= 0:
        return False, "non-positive levels"
    direction = record["direction"]
    if direction == "buy" and not (stop < entry < target):
        return False, "buy levels unordered (need stop < entry < target)"
    if direction == "sell" and not (target < entry < stop):
        return False, "sell levels unordered (need target < entry < stop)"
    if record["volume"] <= 0:
        return False, "non-positive volume"
    return True, "ok"


def _same_trade(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when two records describe the same trade (direction + levels)."""
    for key in ("direction", "entry", "stop_loss", "take_profit"):
        if a.get(key) != b.get(key):
            return False
    return True


def write_call_file(record: dict[str, Any], *, files_dir: Path | None = None) -> Path:
    """Atomically write the call record (tmp + os.replace).

    Idempotent per trade: when the file already holds the same direction +
    levels, the write is skipped (the existing record is returned) so a
    still-alive plan is not re-emitted on every poll — the EA would otherwise
    re-open the same trade after a position closes.  A genuinely new trade
    (different levels) always replaces the file.
    """
    path = call_file_path(str(record["symbol"]), files_dir)
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if _same_trade(existing, record):
            return path
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def emit_call_from_alert(
    alert: dict[str, Any],
    *,
    symbol: str,
    venue_symbol: str,
    volume: float,
    files_dir: Path | None = None,
    magic: int = EA_DEFAULT_MAGIC,
    require_proven: bool = True,
    expiry_epoch: float | None = None,
    call_id: str | None = None,
) -> dict[str, Any] | None:
    """Emit a call to the EA folder when the Stage-3 gate allows it.

    Returns the emitted record, or ``None`` (with a log line) when the call
    is held back — either by the proven-only gate or by invalid levels.
    Never raises on validation failures (best-effort, like the gate).
    """
    import logging

    if require_proven and _evidence_status(alert) != "proven":
        logging.info(
            "[ea_emitter] %s held back: evidence_status=%s (require_proven=True)",
            symbol,
            _evidence_status(alert),
        )
        return None
    # Respect the gate's own go/no-go when present.
    execution_allowed = alert.get("execution_allowed")
    if execution_allowed is not None and not execution_allowed:
        logging.info("[ea_emitter] %s held back: stage-3 execution_allowed=False", symbol)
        return None
    call = alert.get("call")
    if call not in ("buy_candidate", "sell_candidate"):
        logging.info("[ea_emitter] %s held back: alert_type=%s", symbol, call)
        return None

    record = build_call_record(
        alert,
        symbol=symbol,
        venue_symbol=venue_symbol,
        volume=volume,
        magic=magic,
        expiry_epoch=expiry_epoch,
        call_id=call_id,
    )
    ok, reason = _record_is_tradeable(record)
    if not ok:
        logging.info("[ea_emitter] %s held back: %s", symbol, reason)
        return None
    write_call_file(record, files_dir=files_dir)
    logging.info(
        "[ea_emitter] %s emitted call_id=%s %s entry=%s sl=%s tp=%s vol=%s",
        symbol,
        record["call_id"],
        record["direction"],
        record["entry"],
        record["stop_loss"],
        record["take_profit"],
        record["volume"],
    )
    return record


def read_ea_state(symbol: str, *, files_dir: Path | None = None) -> dict[str, Any] | None:
    """Read the EA's execution-state file back (None when absent/unparseable)."""
    path = state_file_path(symbol, files_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_call_file(symbol: str, *, files_dir: Path | None = None) -> bool:
    """Remove the call file (used after the EA has executed / call expired)."""
    path = call_file_path(symbol, files_dir)
    try:
        path.unlink()
        return True
    except OSError:
        return False
