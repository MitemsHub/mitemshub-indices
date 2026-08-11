"""Collector health report: does the MT5 single-flight guard stop IPC timeouts?

The guard (§44) serializes ``mt5.initialize()`` across the collector, the
dashboard warmup, and CLI runs.  To measure whether IPC timeouts still
recur, the collector appends every reconnect/init-failure/feed-loss event to
``.data/mt5_events.jsonl`` (see :mod:`synthetic_trader.data.continuous_collector`).
This module turns that history into a windowed verdict:

- ``needs_re_tune`` — ≥ :data:`IPC_RE_TUNE_THRESHOLD` IPC-timeout init
  failures in the window: the guard didn't eliminate the race, so the
  reconnect backoff needs re-tuning.
- ``attention`` — 1–2 IPC timeouts, or repeated feed-loss/read-error events
  (terminal-side), or a stale corpus (no fresh ticks for 12h+).
- ``ok`` — no IPC timeouts in the window.

Run it manually after the 48h window, and the daily collector task logs a
one-line summary each morning (non-fatal).

CLI: ``python -m synthetic_trader.cli collector-health-report --hours 48``
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from synthetic_trader.backtest.engine import load_ticks_csv
from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.data.tick_store import SCALE_GUARD_MAX_RATIO

# ── Verdict thresholds (48h window) ────────────────────────────────────
# ≥ this many IPC-timeout init failures in the window -> re-tune backoff.
IPC_RE_TUNE_THRESHOLD = 3
# 1..(threshold-1) IPC timeouts -> attention (single incidents may be the
# terminal's own, not the guard's).
IPC_ATTENTION_THRESHOLD = 1
# Feed-loss / read-error counts that also flag attention (terminal-side).
EVENT_ATTENTION_THRESHOLD = 3
# No fresh tick for this long (outside rollover) -> corpus is stale.
STALE_TICK_AGE_SEC = 12 * 3600.0
# ANY tick in the MT5 corpus whose price deviates more than the append-time
# scale guard from the corpus median is a venue leak: Deriv 1HZ-scale
# prices (~3.7-4.0x Blueberry SYN scale) got appended despite the guard.
# This is the loudest verdict — polluted data corrupts every downstream
# verdict, so it outranks IPC/reconnect concerns.

DEFAULT_EVENTS_PATH = Path(".data") / "mt5_events.jsonl"


def _load_events(engine_root: str | Path) -> list[dict[str, Any]]:
    path = Path(engine_root) / DEFAULT_EVENTS_PATH
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return events


def _scan_corpus(
    engine_root: str | Path, symbol: str
) -> dict[str, Any]:
    """Load a symbol's corpus once; report freshness AND venue-scale leaks.

    Returns ``{"last_tick_epoch", "out_of_scale_ticks", "out_of_scale_samples"}``.
    A tick is flagged as out-of-scale when its price deviates from the corpus
    median by more than ``SCALE_GUARD_MAX_RATIO`` (the same rule the append
    guard uses) — Deriv 1HZ prices are ~3.7-4.0x the Blueberry SYN scale, so
    any leak lands far outside the band while genuine intraday range never
    does.
    """
    root = Path(engine_root)
    for candidate in (
        root / "data" / "backfill" / f"{symbol}_ticks.csv",
        root / "data" / f"{symbol.lower()}_ticks.csv",
        root / "data" / f"{symbol}_ticks.csv",
    ):
        if not (candidate.exists() and candidate.stat().st_size > 0):
            continue
        try:
            ticks = load_ticks_csv(candidate, default_symbol=symbol)
        except Exception:
            return {"last_tick_epoch": None, "out_of_scale_ticks": 0, "out_of_scale_samples": []}
        if not ticks:
            return {"last_tick_epoch": None, "out_of_scale_ticks": 0, "out_of_scale_samples": []}
        # Scan the RAW rows — not ``dedupe_ticks`` output.  Dedupe drops
        # exact-duplicate epochs, and a leaked Deriv tick could (in theory)
        # share an epoch with a real row and be silently masked; the scale
        # check must see every row in the file.
        prices = sorted(t.price for t in ticks if t.price and t.price > 0)
        median = prices[len(prices) // 2] if prices else 0.0
        out_of_scale: list[dict[str, Any]] = []
        if median > 0:
            for t in ticks:
                if t.price <= 0:
                    continue
                ratio = t.price / median
                if ratio > SCALE_GUARD_MAX_RATIO or ratio < 1.0 / SCALE_GUARD_MAX_RATIO:
                    out_of_scale.append({"epoch": t.epoch, "price": t.price})
                    if len(out_of_scale) >= 5:
                        break
        # Freshness uses the sorted-deduped tail (max epoch across all rows).
        last_epoch = max(float(t.epoch) for t in ticks)
        return {
            "last_tick_epoch": last_epoch,
            "out_of_scale_ticks": len(out_of_scale),
            "out_of_scale_samples": out_of_scale,
        }
    return {"last_tick_epoch": None, "out_of_scale_ticks": 0, "out_of_scale_samples": []}


def _corpus_last_tick(engine_root: str | Path, symbol: str) -> float | None:
    return _scan_corpus(engine_root, symbol)["last_tick_epoch"]


def run_collector_health(
    engine_root: str | Path = ".",
    hours: float = 48.0,
    now: float | None = None,
) -> dict[str, Any]:
    """Summarize MT5 events over the window and return the verdict."""
    now_ts = now if now is not None else time.time()
    window_start = now_ts - hours * 3600.0
    events = [e for e in _load_events(engine_root) if e.get("ts", 0) >= window_start]

    by_kind: dict[str, int] = {}
    ipc_timeouts = 0
    last_ts = 0.0
    samples: list[dict[str, Any]] = []
    for e in events:
        kind = e.get("kind", "reconnect")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        msg = str(e.get("message", ""))
        if "ipc timeout" in msg.lower():
            ipc_timeouts += 1
        if e.get("ts", 0) > last_ts:
            last_ts = float(e["ts"])
        if len(samples) < 8:
            samples.append({"ts": e.get("ts"), "kind": kind, "message": msg[:140]})

    # Corpus freshness + venue-scale leaks per symbol (one load each).
    corpus: dict[str, Any] = {}
    for symbol in ("R_75", "R_100"):
        scan = _scan_corpus(engine_root, symbol)
        last = scan["last_tick_epoch"]
        corpus[symbol] = {
            "last_tick_epoch": last,
            "last_tick_age_sec": round(max(0.0, now_ts - last), 1) if last else None,
            "out_of_scale_ticks": scan["out_of_scale_ticks"],
            "out_of_scale_samples": scan["out_of_scale_samples"],
        }

    stale = any(
        c.get("last_tick_age_sec") is not None
        and c["last_tick_age_sec"] > STALE_TICK_AGE_SEC
        for c in corpus.values()
    )
    leaked = [(sym, c) for sym, c in corpus.items() if c.get("out_of_scale_ticks", 0) > 0]

    # ── Verdict ────────────────────────────────────────────────────────
    # A venue leak outranks everything: wrong-scale prices in the corpus
    # poison every backtest and live verdict until cleaned, so it must be
    # the loudest morning signal.
    reason: str
    if leaked:
        verdict = "venue_leak"
        bits = []
        for sym, c in leaked:
            s = c["out_of_scale_samples"][0]
            bits.append(
                f"{sym}: {c['out_of_scale_ticks']}+ tick(s) outside {1 / SCALE_GUARD_MAX_RATIO:.1f}x-"
                f"{SCALE_GUARD_MAX_RATIO:.1f}x the corpus median "
                f"(e.g. price {s['price']:.2f} vs median scale) — Deriv 1HZ data leaked "
                "into the MT5 corpus; quarantine the rows (see tick_store venue guard)"
            )
        reason = "VENUE LEAK — " + "; ".join(bits)
    elif ipc_timeouts >= IPC_RE_TUNE_THRESHOLD:
        verdict = "needs_re_tune"
        reason = (
            f"{ipc_timeouts} IPC-timeout init failures in {hours:.0f}h — "
            "the single-flight guard did not eliminate the race; re-tune the "
            "reconnect backoff (RECONNECT_BACKOFF_SEC / MAX_RECONNECTS / "
            "STALL_RECONNECT_SEC in continuous_collector.py)"
        )
    elif ipc_timeouts >= IPC_ATTENTION_THRESHOLD:
        verdict = "attention"
        reason = f"{ipc_timeouts} IPC-timeout init failure(s) in {hours:.0f}h — monitor; single incidents may be terminal-side"
    elif stale:
        verdict = "attention"
        reason = "no fresh ticks for 12h+ — collector may be down (not an IPC-timeout issue)"
    elif any(
        by_kind.get(k, 0) >= EVENT_ATTENTION_THRESHOLD
        for k in ("feed_lost", "read_errors", "reconnect")
    ):
        verdict = "attention"
        reason = "repeated feed-loss/read-error reconnects — terminal-side stalls, no IPC timeouts"
    else:
        verdict = "ok"
        reason = f"no IPC timeouts in {hours:.0f}h — the single-flight guard is holding"

    return {
        "window_hours": hours,
        "generated_at": now_ts,
        "verdict": verdict,
        "verdict_reason": reason,
        "events": {"by_kind": by_kind, "total": len(events), "ipc_timeouts": ipc_timeouts},
        "first_event_ts": events[0]["ts"] if events else None,
        "last_event_ts": last_ts if events else None,
        "samples": samples,
        "corpus": corpus,
    }


def print_collector_health(report: dict[str, Any]) -> None:
    w = report["window_hours"]
    print(f"== collector health (last {w:.0f}h) ==")
    print(f"events: total={report['events']['total']} "
          f"ipc_timeouts={report['events']['ipc_timeouts']} "
          f"by_kind={report['events']['by_kind']}")
    for symbol, c in report["corpus"].items():
        age = c["last_tick_age_sec"]
        age_s = f"{age / 3600:.1f}h" if age is not None else "n/a"
        oos = c.get("out_of_scale_ticks", 0)
        oos_s = f" — VENUE LEAK: {oos}+ out-of-scale tick(s)" if oos else ""
        print(f"  {symbol}: last tick {age_s} ago{oos_s}")
    if report["samples"]:
        print("  recent events:")
        for s in report["samples"][-4:]:
            print(f"    [{s.get('kind')}] {s.get('message', '')[:120]}")
    print(f"verdict: {report['verdict']}")
    print(f"reason: {report['verdict_reason']}")
