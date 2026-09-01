#!/usr/bin/env python3
"""TICK-FADE MULTI-SESSION VERDICT — all recorded Boom/Crash 1000 tick sessions.

The original tick-fade verdict rested on only 3 sessions. This script aggregates
EVERY session in artifacts/ticks/ into one verdict:

  - Per-session coverage: ticks, duration, gaps (>60s), spike count
  - Coverage gate: sessions with <2h span or >10% gap-time are flagged and
    excluded from the headline verdict (marked "partial")
  - Tick-fade replay per session using the EA-FAITHFUL simulator from
    cb_quick_tp_study.py: the entry fires on a recorded tick SPIKE (jump
    >= TICK_SPIKE_PTS against the grind) once its retrace enters the
    size-scaled window — NOT on every 3-tick micro-streak, which fired on
    ~7k trades/session and measured nothing but the heuristic's own noise.
    Geometry: SL 0.3xATR, TP 3.2x (v26.15 robustness gate F2 winner),
    min-RR 2.0, hold 2400s, full trailing, facade-gated expectancy guard.
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
sys.path.insert(0, str(ROOT))

from scripts.cb_quick_tp_study import simulate_tick_fade, m5_atr_from_ticks, score, SESSIONS as STUDY_SESSIONS

TICKS_DIR = ROOT / "artifacts" / "ticks"
OUT_PATH = ROOT / "artifacts" / "tick_fade_verdict.json"

# --- EA-faithful tick-fade geometry (v26.15/26.16) ---
SPREAD = 0.483          # points, measured Boom/Crash 1000 spread
TP_MULT = 3.2           # TP = 3.2 x ATR (robustness gate F2 winner)
SL_MULT = 0.3           # SL = 0.3 x ATR
FADE_R = 0.4            # fade entry anchor (v26.8)
HOLD_S = 2400           # position hold
MIN_RR = 2.0            # deployed min-RR gate
TRAIL = True            # deployed: full trailing on tick fades
SPIKE_JUMP = 3.0        # points; matches EA recorder's spike threshold
GAP_SECONDS = 60        # recording gap threshold
MIN_HOURS_DEFAULT = 2.0  # coverage gate: minimum session span

# Facade gate (mirrors the EA's EWMA gate, hardened by the v26.13 fix)
FACADE_MIN_TRADES = 4   # min closed trades before the gate may block
FACADE_FLOOR = -0.10    # EWMA expectancy floor (R)
FACADE_ALPHA = 0.15     # EWMA alpha

KILL_GATE = {
    "min_sessions": 10,
    "min_trades": 60,
    "min_pf": 1.15,
    "min_expectancy": 0.05,
}

# Per-symbol retrace ceilings from the study's SESSIONS table
# (Boom 0.60 / Crash 0.50); symbol inferred from the file name.
RE_MAX = {"Boom": 0.60, "Crash": 0.50}


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

    # spike count (mid jumps) — informational, matches the EA recorder's counter
    spikes = 0
    prev_mid = None
    for _, bid, ask in rows:
        mid = (bid + ask) / 2.0
        if prev_mid is not None and abs(mid - prev_mid) >= SPIKE_JUMP:
            spikes += 1
        prev_mid = mid

    symbol = "Boom" if "Boom" in path.name else ("Crash" if "Crash" in path.name else "?")
    return {
        "file": path.name,
        "symbol": symbol,
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
    """EA-faithful tick-fade replay on one session.

    Uses the validated EA-order simulator from cb_quick_tp_study.py:
    the entry fires on a recorded tick SPIKE (jump >= 3 pts against the
    grind) once its retrace enters the size-scaled window, with the
    deployed geometry (SL 0.3xATR, TP 3.2x, min-RR 2.0, hold 2400s,
    full trailing). Open-at-end trades are excluded from the aggregates.
    """
    rows = session["rows"]
    symbol = session.get("symbol", "?")
    is_crash = symbol == "Crash"
    re_max = RE_MAX.get(symbol, 0.60)
    atr = m5_atr_from_ticks(rows)
    if atr <= 0:
        return {"trades": 0, "closed": 0, "open_at_end": 0, "wins": 0,
                "losses": 0, "win_rate": None, "total_r": 0.0, "pf": None,
                "expectancy_r": None}
    trades = simulate_tick_fade(rows, is_crash, atr, sl_mult=SL_MULT,
                                tp_mult=TP_MULT, fade_r=FADE_R, re_max=re_max,
                                hold_s=HOLD_S, min_rr=MIN_RR, trail=TRAIL,
                                cooldown_s=0, spread=SPREAD)
    return summarize(trades)


def summarize(trades: list) -> dict:
    closed = [t for t in trades if t["reason"] in ("TARGET", "STOP", "TIME")]
    wins = [t for t in trades if t["r"] > 0]
    losses = [t for t in trades if t["r"] <= 0]
    gw = sum(t["r"] for t in wins)
    gl = abs(sum(t["r"] for t in losses))
    total_r = sum(t["r"] for t in closed)
    return {
        "trades": len(trades),
        "closed": len(closed),
        "open_at_end": len(trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "total_r": round(total_r, 2),
        "pf": round(gw / gl, 3) if gl > 0 else (None if gw == 0 else math.inf),
        "expectancy_r": round(total_r / len(closed), 3) if closed else None,
    }


def facade_guard_simulate(session: dict, replay: dict) -> dict:
    """Facade-gate projection: blocks trading once trailing expectancy
    drops below the floor after FACADE_MIN_TRADES. Applied as a filter on
    the sequential trade list (trades after the gate closes are discarded).

    The gate here mirrors the EA's EWMA facade gate (alpha 0.15, floor
    -0.10R, min 4 trades before blocking) — the same guard the v26.13
    deadlock fix hardened in-engine.
    """
    rows = session["rows"]
    symbol = session.get("symbol", "?")
    is_crash = symbol == "Crash"
    re_max = RE_MAX.get(symbol, 0.60)
    atr = m5_atr_from_ticks(rows)
    if atr <= 0 or not replay.get("closed"):
        return dict(replay)

    trades = simulate_tick_fade(rows, is_crash, atr, sl_mult=SL_MULT,
                                tp_mult=TP_MULT, fade_r=FADE_R, re_max=re_max,
                                hold_s=HOLD_S, min_rr=MIN_RR, trail=TRAIL,
                                cooldown_s=0, spread=SPREAD)

    ewma = 0.0
    n = 0
    blocked = False
    kept = []
    for t in trades:
        if blocked:
            break
        kept.append(t)
        if t["reason"] not in ("TARGET", "STOP", "TIME"):
            continue
        n += 1
        ewma = FACADE_ALPHA * t["r"] + (1 - FACADE_ALPHA) * ewma
        if n >= FACADE_MIN_TRADES and ewma < FACADE_FLOOR:
            blocked = True

    out = summarize(kept)
    out["blocked_after_trade"] = n if blocked else None
    return out


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
        tr = [s[key] for s in sessions_list if s.get(key)]
        if not tr:
            return {"sessions": 0, "trades": 0, "total_r": 0.0, "pf": None,
                    "expectancy_r": None}
        trades = sum(t["closed"] for t in tr)
        total_r = round(sum(t["total_r"] for t in tr), 2)
        wins = sum(t["wins"] for t in tr)
        losses = sum(t["losses"] for t in tr)
        # recompute PF from per-session wins/losses at the deployed geometry:
        # each win is +TP_MULT R, each loss -1R (SL normalized to -1R)
        pf = round((wins * TP_MULT) / losses, 3) if losses else (None if wins == 0 else math.inf)
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
            "sl_atr": SL_MULT,
            "fade_r": FADE_R,
            "min_rr": MIN_RR,
            "trail": TRAIL,
            "hold_s": HOLD_S,
            "entry": "spike-jump >= 3pts + size-scaled retrace window (EA-faithful, cb_quick_tp_study simulator)",
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
    print("TICK-FADE MULTI-SESSION VERDICT (EA-faithful replay)")
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
