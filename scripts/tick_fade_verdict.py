#!/usr/bin/env python3
"""TICK-FADE MULTI-SESSION VERDICT — all recorded Boom/Crash 1000 tick sessions.

The original tick-fade verdict rested on only 3 sessions. This script aggregates
EVERY session in artifacts/ticks/ into one verdict:

  - Per-session coverage: ticks, duration, gaps (>60s), spike count
  - Coverage gate: sessions with <2h span or >10% gap-time are flagged and
    excluded from the headline verdict (marked "partial")
  - Tick-fade replay per session using the EA-faithful geometry
    (SL 0.3xATR-approx, TP 3.2x target, facade-gated expectancy guard)
  - Aggregate verdict: keep/kill decision with a pre-registered kill gate

Usage:
  python scripts/tick_fade_verdict.py            # verdict across all sessions
  python scripts/tick_fade_verdict.py --min-hours 2

Output: artifacts/tick_fade_verdict.json + console report.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKS_DIR = ROOT / "artifacts" / "ticks"
OUT_PATH = ROOT / "artifacts" / "tick_fade_verdict.json"

# --- EA-faithful tick-fade geometry (v26.15/26.16) ---
SPREAD = 0.483          # points, measured Boom/Crash 1000 spread
SL_RISK = 1.0           # R normalized: every stop = -1R
TP_MULT = 3.2           # TP = 3.2 x ATR (robustness gate F2 winner)
ATR_PROXY_WINDOW = 50   # rolling window of tick mid changes for "ATR" proxy
SPIKE_JUMP = 3.0        # points; matches EA recorder's spike threshold
GAP_SECONDS = 60        # recording gap threshold
FACADE_MIN_TRADES = 4   # facade gate: min trades before blocking
FACADE_FLOOR = -0.10    # facade gate: expectancy floor (R)
FACADE_ALPHA = 0.15     # facade gate: EWMA alpha
MIN_HOURS_DEFAULT = 2.0  # coverage gate: minimum session span

KILL_GATE = {
    "min_sessions": 10,
    "min_trades": 60,
    "min_pf": 1.15,
    "min_expectancy": 0.05,
}


def load_session(path: Path) -> dict:
    rows = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rows.append((int(r["ts"]), float(r["bid"]), float(r["ask"])))
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: x[0])
    if not rows:
        return {"file": path.name, "ticks": 0, "usable": False}

    # coverage stats
    gaps = []
    prev = None
    for ts, _, _ in rows:
        if prev is not None and ts - prev > GAP_SECONDS:
            gaps.append(ts - prev)
        prev = ts
    first_ts, last_ts = rows[0][0], rows[-1][0]
    span_s = last_ts - first_ts
    gap_total = sum(gaps)
    gap_frac = gap_total / span_s if span_s > 0 else 1.0

    # spike count (mid jumps)
    spikes = 0
    prev_mid = None
    for _, bid, ask in rows:
        mid = (bid + ask) / 2.0
        if prev_mid is not None and abs(mid - prev_mid) >= SPIKE_JUMP:
            spikes += 1
        prev_mid = mid

    return {
        "file": path.name,
        "symbol": ("Boom" if "Boom" in path.name else "Crash" if "Crash" in path.name else "?"),
        "day": path.stem.split("_")[-1],
        "ticks": len(rows),
        "span_seconds": span_s,
        "span_hours": round(span_s / 3600, 2),
        "gaps_over_60s": len(gaps),
        "gap_time_seconds": gap_total,
        "gap_fraction": round(gap_frac, 3),
        "spikes": spikes,
        "rows": rows,
        "usable": True,
    }


def replay_tick_fade(session: dict) -> dict:
    """EA-faithful simplified tick-fade replay on one session.

    Signals: fade 2+ consecutive same-direction spike bursts (the tick-fade
    entry heuristic used in cb_burst_guard_backtest.py). Exits: SL (-1R),
    TP (+TP_MULT x SL distance / SL distance = +3.2R approx normalized),
    or session end (marked open -> excluded).
    """
    rows = session["rows"]
    mids = [(ts, (b + a) / 2.0) for ts, b, a in rows]
    trades = []

    # rolling "ATR" proxy: mean abs mid change over window
    diffs = []
    i = 1
    state = "flat"          # flat | armed_up | armed_down
    streak_dir = 0
    streak_count = 0
    pos = None              # open trade dict

    for j in range(1, len(mids)):
        ts, mid = mids[j]
        prev_ts, prev_mid = mids[j - 1]
        d = mid - prev_mid
        diffs.append(abs(d))
        atr = sum(diffs[-ATR_PROXY_WINDOW:]) / len(diffs[-ATR_PROXY_WINDOW:]) if diffs else 0.5
        if atr <= 0:
            atr = 0.5

        # manage open position
        if pos is not None:
            move = (mid - pos["entry"]) * (1 if pos["dir"] > 0 else -1)
            if move <= -atr * 0.3:          # SL at 0.3xATR against us
                pos["result"] = -1.0
                pos["exit"] = "SL"
                trades.append(pos)
                pos = None
            elif move >= atr * 0.3 * TP_MULT:  # TP at 3.2x
                pos["result"] = TP_MULT
                pos["exit"] = "TP"
                trades.append(pos)
                pos = None
            continue

        # streak detection (spike-burst heuristic)
        cur_dir = 1 if d > 0 else (-1 if d < 0 else 0)
        if cur_dir != 0 and cur_dir == streak_dir:
            streak_count += 1
        else:
            streak_dir = cur_dir
            streak_count = 1 if cur_dir != 0 else 0

        # entry: fade a 3-tick same-direction burst (contrarian)
        if streak_count >= 3 and streak_dir != 0:
            pos = {
                "entry_ts": ts,
                "entry": mid,
                "dir": -streak_dir,   # fade the burst
                "exit": None,
                "result": None,
            }
            streak_count = 0

    if pos is not None:
        pos["exit"] = "OPEN"
        trades.append(pos)

    closed = [t for t in trades if t["exit"] in ("SL", "TP")]
    wins = [t for t in closed if t["result"] > 0]
    losses = [t for t in closed if t["result"] <= 0]
    gross_win = sum(t["result"] for t in wins)
    gross_loss = abs(sum(t["result"] for t in losses))
    total_r = sum(t["result"] for t in closed)

    return {
        "trades": len(trades),
        "closed": len(closed),
        "open_at_end": len(trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "total_r": round(total_r, 2),
        "pf": round(gross_win / gross_loss, 3) if gross_loss > 0 else (None if gross_win == 0 else math.inf),
        "expectancy_r": round(total_r / len(closed), 3) if closed else None,
    }


def facade_guard_simulate(session: dict, replay: dict) -> dict:
    """Rough facade-gate projection: blocks trading once trailing expectancy
    drops below the floor after FACADE_MIN_TRADES. Applied as a filter on the
    sequential trade list (trades after the gate closes are discarded)."""
    rows = session["rows"]
    if not rows:
        return replay
    # Rebuild sequential trade results with timestamps
    trades = []
    # rerun replay but keep sequence with timestamps
    mids = [(ts, (b + a) / 2.0) for ts, b, a in rows]
    diffs = []
    streak_dir = 0
    streak_count = 0
    pos = None
    for j in range(1, len(mids)):
        ts, mid = mids[j]
        _, prev_mid = mids[j - 1]
        d = mid - prev_mid
        diffs.append(abs(d))
        atr = sum(diffs[-ATR_PROXY_WINDOW:]) / len(diffs[-ATR_PROXY_WINDOW:]) if diffs else 0.5
        if atr <= 0:
            atr = 0.5
        if pos is not None:
            move = (mid - pos["entry"]) * (1 if pos["dir"] > 0 else -1)
            if move <= -atr * 0.3:
                pos["result"] = -1.0
                pos["exit_ts"] = ts
                trades.append(pos)
                pos = None
            elif move >= atr * 0.3 * TP_MULT:
                pos["result"] = TP_MULT
                pos["exit_ts"] = ts
                trades.append(pos)
                pos = None
            continue
        cur_dir = 1 if d > 0 else (-1 if d < 0 else 0)
        if cur_dir != 0 and cur_dir == streak_dir:
            streak_count += 1
        else:
            streak_dir = cur_dir
            streak_count = 1 if cur_dir != 0 else 0
        if streak_count >= 3 and streak_dir != 0:
            pos = {"entry_ts": ts, "entry": mid, "dir": -streak_dir, "result": None, "exit_ts": None}
            streak_count = 0
    if pos is not None:
        pos["exit"] = "OPEN"
        trades.append(pos)

    # facade gate over closed trades
    ewma = 0.0
    n = 0
    blocked = False
    kept = []
    for t in trades:
        if t.get("exit") == "OPEN" or t.get("exit_ts") is None:
            if not blocked:
                kept.append(t)
            continue
        if blocked:
            continue
        kept.append(t)
        n += 1
        ewma = FACADE_ALPHA * t["result"] + (1 - FACADE_ALPHA) * ewma
        if n >= FACADE_MIN_TRADES and ewma < FACADE_FLOOR:
            blocked = True

    closed = [t for t in kept if t.get("exit_ts") is not None]
    wins = [t for t in closed if t["result"] > 0]
    losses = [t for t in closed if t["result"] <= 0]
    total_r = sum(t["result"] for t in closed)
    gross_win = sum(t["result"] for t in wins)
    gross_loss = abs(sum(t["result"] for t in losses))
    return {
        "trades": len(kept),
        "closed": len(closed),
        "blocked_after_trade": n if blocked else None,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "total_r": round(total_r, 2),
        "pf": round(gross_win / gross_loss, 3) if gross_loss > 0 else (None if gross_win == 0 else math.inf),
        "expectancy_r": round(total_r / len(closed), 3) if closed else None,
    }


def main() -> int:
    min_hours = MIN_HOURS_DEFAULT
    if "--min-hours" in sys.argv:
        idx = sys.argv.index("--min-hours")
        min_hours = float(sys.argv[idx + 1])

    if not TICKS_DIR.exists():
        print(f"No ticks dir at {TICKS_DIR}")
        return 1

    files = sorted(TICKS_DIR.glob("*.csv"))
    if not files:
        print(f"No session CSVs in {TICKS_DIR}")
        return 1

    sessions = []
    for f in files:
        s = load_session(f)
        if not s.get("usable"):
            sessions.append(s)
            continue
        s["coverage_ok"] = s["span_hours"] >= min_hours and s["gap_fraction"] < 0.10
        s["replay"] = replay_tick_fade(s)
        s["facade"] = facade_guard_simulate(s, s["replay"])
        # drop heavy rows before serialization
        s.pop("rows", None)
        sessions.append(s)

    usable = [s for s in sessions if s.get("usable")]
    qualifying = [s for s in usable if s["coverage_ok"]]

    def agg(sessions_list, key):
        tr = [t for s in sessions_list for t in ([s[key]] if s.get(key) else [])]
        if not tr:
            return {"sessions": 0, "trades": 0, "total_r": 0.0, "pf": None, "expectancy_r": None}
        trades = sum(t["closed"] for t in tr)
        total_r = round(sum(t["total_r"] for t in tr), 2)
        gw = sum((t["pf"] or 0) * 0 for t in tr)  # pf recomputed below
        wins = sum(t["wins"] for t in tr)
        losses = sum(t["losses"] for t in tr)
        pf = round(wins * TP_MULT / losses, 3) if losses else None
        return {
            "sessions": len(tr),
            "trades": trades,
            "total_r": total_r,
            "pf": pf,
            "expectancy_r": round(total_r / trades, 3) if trades else None,
            "wins": wins,
            "losses": losses,
        }

    verdict = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "params": {
            "spread_points": SPREAD,
            "tp_mult_atr": TP_MULT,
            "sl_atr": 0.3,
            "facade": {"alpha": FACADE_ALPHA, "min_trades": FACADE_MIN_TRADES, "floor_r": FACADE_FLOOR},
            "coverage_gate": {"min_hours": min_hours, "max_gap_fraction": 0.10},
        },
        "kill_gate": KILL_GATE,
        "sessions": [
            {k: v for k, v in s.items() if k != "rows"} for s in sessions
        ],
        "aggregate_all": agg(usable, "replay"),
        "aggregate_qualifying": agg(qualifying, "replay"),
        "aggregate_facade_qualifying": agg(qualifying, "facade"),
    }

    # Kill-gate evaluation on qualifying sessions (facade-gated)
    a = verdict["aggregate_facade_qualifying"]
    checks = {
        "min_sessions": a["sessions"] >= KILL_GATE["min_sessions"],
        "min_trades": a["trades"] >= KILL_GATE["min_trades"],
        "min_pf": (a["pf"] is not None) and a["pf"] >= KILL_GATE["min_pf"],
        "min_expectancy": (a["expectancy_r"] is not None) and a["expectancy_r"] >= KILL_GATE["min_expectancy"],
    }
    verdict["kill_gate_checks"] = checks
    verdict["verdict"] = (
        "KEEP — gate passed" if all(checks.values())
        else "INSUFFICIENT DATA — keep recording" if a["sessions"] < KILL_GATE["min_sessions"]
        else "FAIL — tick-fade does not clear the kill gate"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(verdict, indent=2, default=str))

    # console report
    print("=" * 64)
    print("TICK-FADE MULTI-SESSION VERDICT")
    print("=" * 64)
    for s in sessions:
        if not s.get("usable"):
            print(f"  {s['file']}: EMPTY/unreadable")
            continue
        flag = "OK " if s["coverage_ok"] else "PARTIAL"
        print(f"  [{flag}] {s['file']}: {s['ticks']} ticks, {s['span_hours']}h, "
              f"gaps {s['gaps_over_60s']} ({int(s['gap_fraction']*100)}%), spikes {s['spikes']} | "
              f"trades {s['replay']['closed']} R {s['replay']['total_r']} | "
              f"facade R {s['facade']['total_r']}")
    print("-" * 64)
    for label, key in [("ALL sessions", "aggregate_all"),
                       ("QUALIFYING sessions", "aggregate_qualifying"),
                       ("FACADE-GATED qualifying", "aggregate_facade_qualifying")]:
        a = verdict[key]
        print(f"  {label}: sessions {a['sessions']} | trades {a['trades']} | "
              f"R {a['total_r']} | PF {a['pf']} | expR {a['expectancy_r']}")
    print("-" * 64)
    print("Kill gate:", checks)
    print("VERDICT:", verdict["verdict"])
    print(f"Saved: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
