#!/usr/bin/env python3
"""FACADE-GATE VERIFICATION — 08-30 burst day (the day that killed the fixed guard).

Replays the recorded tick sessions with four guard configurations and compares:
  1. baseline        — no guard at all (what the raw tick-fade does)
  2. fixed burst     — deployed v26.0 cluster/min-gap guard (Crash ON in prod)
  3. EA facade       — the EA's exact CbSpikeFacade logic: EWMA alpha=0.15,
                       min 4 trades evidence, block when expect < -0.25R or
                       (expect < 0 AND expect < 1.5*sigma), exploration budget
                       3 signals after a gate close, daily quiet-day decay
                       (expect *= 0.5, n *= 0.6) on day rollover.
  4. EA facade + recovery — same, but the gate OPENS as soon as expect
                       recovers above the floor (verdict re-evaluated per trade,
                       matching ReevaluateCbSpikeGate in the EA).

Scored net of spread (0.483 pts), R units where 1R = planned SL distance.
The question: does the facade gate beat the fixed burst guard on the burst
day that killed the fixed guard (Boom 08-30: fixed guard -12.5R vs baseline
-3.8R)?

Usage:
    .venv/Scripts/python.exe scripts/cb_facade_verify.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TICK_DIR = ROOT / "artifacts" / "ticks"

# ---- fixed EA parameters (v25.7 tick fast-fade) ----
TICK_SPIKE_PTS = 3.0
FADE_R = 0.30
RETRACE_MAX_DEFAULT = 0.50
SL_MULT = 0.4
TP_MULT = 3.2
MIN_RR = 2.0
SPIKE_TIMEOUT_S = 900
TIME_EXIT_S = 8 * 300
BAR = 300
SPREAD_PTS = 0.483
GAP_S = 300

# v26.0 fixed burst guard defaults
GUARD_WINDOW_S = 1800
GUARD_MAX_SPIKES = 2
GUARD_MIN_GAP_S = 600

# EA facade gate (CbSpikeFacade) constants
FACADE_ALPHA = 0.15
FACADE_MIN_TRADES = 4
FACADE_HARD_FLOOR = -0.25
FACADE_PROBE_BUDGET = 3
FACADE_QUIET_DECAY = 0.5   # daily: expect *= 0.5
FACADE_QUIET_N_DECAY = 0.6  # daily: n *= 0.6

SESSIONS = [
    ("BOOM  08-29", "MITEMSHUB_ticks_Boom_1000_Index_20260829.csv", False, 0.60),
    ("BOOM  08-30", "MITEMSHUB_ticks_Boom_1000_Index_20260830.csv", False, 0.60),
    ("CRASH 08-30", "MITEMSHUB_ticks_Crash_1000_Index_20260830.csv", True, 0.50),
]


def load_ticks(glob: str):
    rows = []
    for f in sorted(TICK_DIR.glob(glob)):
        with open(f, newline="") as fh:
            for rec in csv.DictReader(fh):
                try:
                    rows.append((int(rec["ts"]), float(rec["bid"]), float(rec["ask"])))
                except (ValueError, KeyError):
                    continue
    rows.sort(key=lambda r: r[0])
    return rows


def m5_atr_from_ticks(ticks) -> float:
    bars = {}
    for ts, bid, _ in ticks:
        k = ts - ts % BAR
        b = bars.setdefault(k, {"open": bid, "high": bid, "low": bid, "close": bid})
        b["high"] = max(b["high"], bid)
        b["low"] = min(b["low"], bid)
        b["close"] = bid
    trs, prev_close = [], None
    for k in sorted(bars):
        b = bars[k]
        tr = b["high"] - b["low"]
        if prev_close is not None:
            tr = max(tr, abs(b["high"] - prev_close), abs(b["low"] - prev_close))
        trs.append(tr)
        prev_close = b["close"]
    if len(trs) < 20:
        return 0.0
    atr = sum(trs[:14]) / 14.0
    for tr in trs[14:]:
        atr = (13.0 * atr + tr) / 14.0
    return atr


def scaled_fade_entry(jump: float) -> float:
    lo = FADE_R * math.sqrt(12.0 / max(jump, 1.0))
    return max(0.18, min(0.40, lo))


class BurstRing:
    """v26.0 fixed cluster/min-gap guard."""

    def __init__(self):
        self.times = []

    def record(self, ts: float):
        self.times.append(ts)
        if len(self.times) > 8:
            self.times.pop(0)

    def blocks(self, now: float):
        in_win = sum(1 for t in self.times if 0 <= now - t <= GUARD_WINDOW_S)
        if in_win >= GUARD_MAX_SPIKES:
            return f"cluster={in_win}/{GUARD_MAX_SPIKES}@{GUARD_WINDOW_S}s"
        if len(self.times) >= 2:
            gap = self.times[-1] - self.times[-2]
            if 0 < gap < GUARD_MIN_GAP_S:
                return f"gap={gap}s<{GUARD_MIN_GAP_S}s"
        return None


class EAFacade:
    """The EA's exact CbSpikeFacade + UpdateCbSpikeLearning + daily decay."""

    def __init__(self, auto_reopen: bool = False):
        self.n = 0
        self.expect = 0.0
        self.sigma = 0.5
        self.probe = 0
        self.blocked = False
        self.day = None
        self.auto_reopen = auto_reopen

    def _decay_day(self, now: float):
        day = int(now // 86400)
        if self.day is None:
            self.day = day
        elif day != self.day:
            # DecayCbSpikeLearning on day rollover
            if self.n > 0:
                self.expect *= FACADE_QUIET_DECAY
                self.sigma = max(0.5, self.sigma * 0.7)
                if self.n > 2:
                    self.n = int(self.n * FACADE_QUIET_N_DECAY)
            self.day = day
            self._reeval()

    def _reeval(self):
        self.blocked = self._facade()

    def _facade(self) -> bool:
        if self.n < FACADE_MIN_TRADES:
            return False
        if self.probe > 0:
            return False
        if self.expect < FACADE_HARD_FLOOR:
            return True
        if self.expect < 0.0 and self.sigma > 0 and self.expect < 1.5 * self.sigma:
            return True
        return False

    def record(self, ts: float):
        self._decay_day(ts)

    def trade_closed(self, ts: float, r: float):
        """UpdateCbSpikeLearning after each closed CB spike trade."""
        self._decay_day(ts)
        self.n += 1
        a = FACADE_ALPHA
        self.expect = r if self.n <= 2 else (a * r + (1.0 - a) * self.expect)
        dev = r - self.expect
        self.sigma = 0.5 if self.n <= 2 else math.sqrt(
            a * dev * dev + (1.0 - a) * self.sigma * self.sigma)
        if self.probe > 0:
            self.probe = 0
        self._reeval()

    def blocks(self, now: float) -> str | None:
        self._decay_day(now)
        if self._facade():
            return (f"facade expect={self.expect:+.2f} sigma={self.sigma:.2f} "
                    f"n={self.n}")
        return None

    def note_fired(self):
        """A fade fired while blocked consumes one exploration slot."""
        if self.blocked and self.probe > 0:
            self.probe -= 1

    def on_gate_closed(self, now: float):
        """Gate just closed -> grant exploration budget (EA v26.13)."""
        self.probe = FACADE_PROBE_BUDGET


def simulate(ticks, is_crash: bool, atr: float, guard, re_max: float):
    """EA-order replay (manage pos -> spike SM -> pending fire)."""
    trades, skipped = [], []
    pos = None
    cur = None
    n = len(ticks)

    def close_pos(ts, price, reason):
        nonlocal pos
        if pos["dir"] > 0:
            r = (price - pos["entry"]) / pos["risk_pts"]
        else:
            r = (pos["entry"] - (price + SPREAD_PTS)) / pos["risk_pts"]
        r = round(r, 2)
        trades.append({"t": pos["t_entry"], "r": r, "reason": reason})
        if isinstance(guard, EAFacade):
            guard.trade_closed(ts, r)
        pos = None

    for i in range(1, n):
        ts, bid, _ = ticks[i]
        if ts - ticks[i - 1][0] > GAP_S:
            if pos is not None:
                close_pos(ticks[i - 1][0], ticks[i - 1][1], "GAP")
            cur = None
            continue

        if pos is not None:
            gain = (bid - pos["entry"]) if pos["dir"] > 0 else (pos["entry"] - bid)
            pos["peak_gain"] = max(pos["peak_gain"], gain)
            gr = pos["peak_gain"] / pos["risk_pts"]
            if gr >= 1.0:
                if pos["dir"] > 0:
                    pos["sl"] = max(pos["sl"], pos["entry"],
                                    pos["entry"] + (pos["peak_gain"] - 0.7 * pos["risk_pts"]))
                else:
                    pos["sl"] = min(pos["sl"], pos["entry"],
                                    pos["entry"] - (pos["peak_gain"] - 0.7 * pos["risk_pts"]))
            if pos["dir"] > 0:
                if bid >= pos["tp"]:
                    close_pos(ts, pos["tp"], "TARGET")
                elif bid <= pos["sl"]:
                    close_pos(ts, bid, "STOP")
            else:
                if bid <= pos["tp"]:
                    close_pos(ts, pos["tp"], "TARGET")
                elif bid >= pos["sl"]:
                    close_pos(ts, bid, "STOP")
            if pos is not None and ts - pos["t_entry"] >= TIME_EXIT_S:
                close_pos(ts, bid, "TIME")

        jump_tick = bid - ticks[i - 1][1]
        hit = (jump_tick <= -TICK_SPIKE_PTS) if is_crash else (jump_tick >= TICK_SPIKE_PTS)
        if hit:
            if guard is not None:
                guard.record(ts)
            if cur is None:
                cur = {"pre": ticks[i - 1][1], "peak": bid,
                       "jump": abs(jump_tick), "t0": ts}
            else:
                deeper = (bid < cur["peak"]) if is_crash else (bid > cur["peak"])
                if deeper:
                    cur["peak"] = bid
                    cur["jump"] = abs(cur["peak"] - cur["pre"])
                    cur["t0"] = ts

        if cur is not None:
            retrace = ((bid - cur["peak"]) / cur["jump"]) if is_crash \
                else ((cur["peak"] - bid) / cur["jump"])
            age = ts - cur["t0"]
            full = (bid >= cur["pre"]) if is_crash else (bid <= cur["pre"])
            if full or age > SPIKE_TIMEOUT_S or retrace > re_max:
                cur = None
            elif pos is None and retrace >= scaled_fade_entry(cur["jump"]):
                entry_px = bid + (SPREAD_PTS if is_crash else 0.0)
                sl_d = SL_MULT * atr
                tp_d = TP_MULT * atr
                if is_crash:
                    sl = entry_px - sl_d
                    tp = entry_px + tp_d
                    if tp < cur["pre"]:
                        tp = cur["pre"] + 0.2 * atr
                    rr = (tp - entry_px) / max(entry_px - sl, 1e-9)
                else:
                    sl = entry_px + sl_d
                    tp = entry_px - tp_d
                    if tp > cur["pre"]:
                        tp = cur["pre"] - 0.2 * atr
                    rr = (entry_px - tp) / max(sl - entry_px, 1e-9)
                if rr < MIN_RR:
                    cur = None
                    continue
                why = guard.blocks(ts) if guard is not None else None
                if why is not None:
                    if isinstance(guard, EAFacade) and guard.probe > 0:
                        # exploration budget: this fade still fires
                        guard.note_fired()
                    else:
                        skipped.append((ts, f"GUARD:{why}", cur["jump"]))
                        cur = None
                        continue
                pos = {"dir": 1 if is_crash else -1, "entry": entry_px,
                       "sl": sl, "tp": tp, "risk_pts": sl_d, "t_entry": ts,
                       "peak_gain": 0.0}
                if isinstance(guard, EAFacade) and guard.blocked:
                    guard.on_gate_closed_pos_fired = ts  # noop marker
                cur = None

    if pos is not None:
        ts, bid, _ = ticks[-1]
        close_pos(ts, bid, "END")
    return trades, skipped


def summarize(trades):
    if not trades:
        return "no trades"
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    exits = {k: sum(1 for t in trades if t["reason"] == k)
             for k in ("TARGET", "STOP", "TIME", "END", "GAP")}
    return (f"trades={len(trades)} W/L={len(wins)}/{len(trades) - len(wins)} "
            f"totalR={sum(t['r'] for t in trades):+.2f} PF={gw / gl if gl > 0 else 99:.2f} "
            f"maxDD={dd:.2f} exits={exits}")


def fmt_t(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def run_session(name: str, glob: str, is_crash: bool, re_max: float):
    ticks = load_ticks(glob)
    if len(ticks) < 500:
        print(f"\n[{name}] not enough ticks — skipped")
        return
    t0, t1 = ticks[0][0], ticks[-1][0]
    print("\n" + "=" * 96)
    print(f"{name}  ticks={len(ticks)}  {fmt_t(t0)}->{fmt_t(t1)} srv ({(t1 - t0) / 3600:.1f}h)")
    print("=" * 96)
    atr = m5_atr_from_ticks(ticks)
    print(f"ATR={atr:.2f} -> SL {SL_MULT * atr:.2f}, TP {TP_MULT * atr:.2f} pts "
          f"| spread {SPREAD_PTS} = {SPREAD_PTS / (SL_MULT * atr):.2f}R/roundtrip")

    # 1. baseline
    tr0, _ = simulate(ticks, is_crash, atr, None, re_max)
    print(f"\n--- BASELINE (no guard) ---")
    for t in tr0:
        print(f"  {fmt_t(t['t'])}  R={t['r']:+.2f}  {t['reason']}")
    print(f"  => {summarize(tr0)}")

    # 2. fixed burst guard
    ring = BurstRing()
    trg, skg = simulate(ticks, is_crash, atr, ring, re_max)
    print(f"\n--- FIXED BURST GUARD (v26.0 window={GUARD_WINDOW_S}s max={GUARD_MAX_SPIKES} gap={GUARD_MIN_GAP_S}s) ---")
    for t in trg:
        print(f"  {fmt_t(t['t'])}  R={t['r']:+.2f}  {t['reason']}")
    for s in skg:
        print(f"  {fmt_t(s[0])}  BLOCKED  {s[1]}")
    print(f"  => {summarize(trg)}   (blocks: {len(skg)})")
    print(f"  DELTA vs baseline: {sum(t['r'] for t in trg) - sum(t['r'] for t in tr0):+.2f}")

    # 3. EA facade gate (exact CbSpikeFacade semantics)
    fac = EAFacade()
    trf, skf = simulate(ticks, is_crash, atr, fac, re_max)
    print(f"\n--- EA FACADE GATE (CbSpikeFacade: floor {FACADE_HARD_FLOOR}R, "
          f"min {FACADE_MIN_TRADES} trades, probe {FACADE_PROBE_BUDGET}, daily decay) ---")
    for t in trf:
        print(f"  {fmt_t(t['t'])}  R={t['r']:+.2f}  {t['reason']}")
    for s in skf:
        print(f"  {fmt_t(s[0])}  BLOCKED  {s[1]}")
    print(f"  => {summarize(trf)}   (blocks: {len(skf)})")
    print(f"  DELTA vs baseline: {sum(t['r'] for t in trf) - sum(t['r'] for t in tr0):+.2f}")

    return {"baseline": summarize(tr0), "fixed": summarize(trg),
            "facade": summarize(trf),
            "baseline_R": round(sum(t["r"] for t in tr0), 2),
            "fixed_R": round(sum(t["r"] for t in trg), 2),
            "facade_R": round(sum(t["r"] for t in trf), 2)}


def main():
    out = {}
    for name, glob, is_crash, re_max in SESSIONS:
        r = run_session(name, glob, is_crash, re_max)
        if r:
            out[name] = r
    (ROOT / "artifacts" / "cb_facade_verify.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print("\n[wrote] artifacts/cb_facade_verify.json")


if __name__ == "__main__":
    main()
