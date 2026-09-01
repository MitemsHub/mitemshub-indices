#!/usr/bin/env python3
"""Offline EXIT-GEOMETRY GRID SEARCH (TP / SL / retrace-entry / hold) for the
Crash/Boom tick fast-fade, run over ALL recorded tick sessions, net of spread.

Reuses the validated tick-fade replay from cb_burst_guard_backtest.py (the
simulator that reproduced the 2026-08-30 live Crash entries to the second and
4/7 live Boom entries): tick spike state machine with extension merging,
ScaledFadeEntry, retrace-quality ceiling, pending timeout, pre-spike TP clamp,
min-R:R gate, tick-by-tick exits (BE at +1R, trail 1R->0.7R, gap-through SL
fills), one position at a time, spread paid on every round trip.

What is swept here (the exit/entry geometry, not the guard):
  SL_MULT   x ATR   (InpCBFadeSL)         0.3 0.4 0.5 0.6 0.8 1.0
  TP_MULT   x ATR   (InpCBFadeTP)         1.5 2.0 2.5 3.2 4.0 5.0
  FADE_R            (InpCBFadeR base)     0.2 0.3 0.4   (ScaledFadeEntry anchor)
  RETRACE_MAX       (entry ceiling)       0.4 0.5 0.6
  TIME_EXIT_S       (hold)                1200 1800 2400 3600 s

Everything is scored NET OF SPREAD (0.483 pts measured from recorded ticks,
paid on every round trip) and in R units where 1R = the planned SL distance
of that config, so configs are comparable across SL sizes.

Robustness protocol (anti-curve-fit):
  1. every config is scored on ALL THREE sessions (Boom 08-29, Boom 08-30,
     Crash 08-30) — a config must not be a one-day wonder;
  2. the finalists are re-run under ATR x0.8 / x1.2 (volatility-estimate
     error) and spread x1.5 (cost stress) and must keep non-negative
     aggregate R;
  3. the incumbent live geometry (SL 0.4 / TP 3.2 / R 0.30 / max 0.50-0.60 /
     hold 2400s) is the benchmark — a challenger must beat it, not the void.

Usage:
    python scripts/cb_exit_grid_search.py
"""
from __future__ import annotations

import itertools
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TICK_DIR = ROOT / "artifacts" / "ticks"

# ---- fixed EA parameters (not swept) ----
TICK_SPIKE_PTS = 3.0
MIN_RR = 2.0
SPIKE_TIMEOUT_S = 900
GAP_S = 300
BAR = 300
SPREAD_PTS = 0.483

# ---- sweep grid ----
SL_GRID = (0.3, 0.4, 0.5, 0.6, 0.8, 1.0)
TP_GRID = (1.5, 2.0, 2.5, 3.2, 4.0, 5.0)
R_GRID = (0.2, 0.3, 0.4)
REMAX_GRID = (0.40, 0.50, 0.60)
HOLD_GRID = (1200, 1800, 2400, 3600)

# ---- sessions ----
SESSIONS = [
    ("BOOM  08-29", "MITEMSHUB_ticks_Boom_1000_Index_20260829.csv", False, 0.60),
    ("BOOM  08-30", "MITEMSHUB_ticks_Boom_1000_Index_20260830.csv", False, 0.60),
    ("CRASH 08-30", "MITEMSHUB_ticks_Crash_1000_Index_20260830.csv", True, 0.50),
]

# incumbent live geometry (Boom/Crash .set): SL 0.4xATR, TP 3.2xATR,
# FADE_R 0.3, hold 8 bars = 2400s, retrace ceiling 0.50 Boom / 0.50 Crash
INCUMBENT = dict(sl=0.4, tp=3.2, r=0.30, remax=0.50, hold=2400)


def load_ticks(glob: str):
    rows = []
    for f in sorted(TICK_DIR.glob(glob)):
        import csv
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


def scaled_fade_entry(jump: float, fade_r: float) -> float:
    """CrashBoomStrategy.ScaledFadeEntry with parametrized anchor."""
    lo = fade_r * math.sqrt(12.0 / max(jump, 1.0))
    return max(0.18, min(0.40, lo))


def simulate(ticks, is_crash: bool, atr: float, *,
             sl_mult: float, tp_mult: float, fade_r: float,
             re_max: float, hold_s: float, spread: float = SPREAD_PTS):
    """EA-order replay with parametrized geometry. Returns trade list."""
    trades = []
    pos = None
    cur = None
    n = len(ticks)

    def close_pos(ts, price, reason):
        nonlocal pos
        if pos["dir"] > 0:
            r = (price - pos["entry"]) / pos["risk_pts"]
        else:
            r = (pos["entry"] - (price + spread)) / pos["risk_pts"]
        trades.append({"t": pos["t_entry"], "dir": pos["dir"], "r": r,
                       "reason": reason, "jump": pos["jump"], "hold": ts - pos["t_entry"]})
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
            if pos is not None and ts - pos["t_entry"] >= hold_s:
                close_pos(ts, bid, "TIME")

        jump_tick = bid - ticks[i - 1][1]
        hit = (jump_tick <= -TICK_SPIKE_PTS) if is_crash else (jump_tick >= TICK_SPIKE_PTS)
        if hit:
            if cur is None:
                cur = {"pre": ticks[i - 1][1], "peak": bid, "jump": abs(jump_tick), "t0": ts}
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
            elif pos is None and retrace >= scaled_fade_entry(cur["jump"], fade_r):
                entry_px = bid + (spread if is_crash else 0.0)
                sl_d = sl_mult * atr
                tp_d = tp_mult * atr
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
                else:
                    pos = {"dir": 1 if is_crash else -1, "entry": entry_px,
                           "sl": sl, "tp": tp, "risk_pts": sl_d, "t_entry": ts,
                           "jump": cur["jump"], "peak_gain": 0.0}
                    cur = None

    if pos is not None:
        ts, bid, _ = ticks[-1]
        close_pos(ts, bid, "END")
    return trades


def score(trades) -> dict:
    total = sum(t["r"] for t in trades)
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": len(trades), "r": total,
            "pf": (gw / gl) if gl > 0 else 99.0, "dd": dd,
            "wr": len(wins) / len(trades) if trades else 0.0}


def fmt_t(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def main():
    data = {}
    for name, glob, is_crash, re_max_live in SESSIONS:
        ticks = load_ticks(glob)
        if len(ticks) < 500:
            print(f"[{name}] not enough ticks — skipped")
            continue
        atr = m5_atr_from_ticks(ticks)
        data[name] = {"ticks": ticks, "crash": is_crash, "atr": atr}
        span = (ticks[-1][0] - ticks[0][0]) / 3600
        print(f"[{name}] ticks={len(ticks)} span={span:.1f}h ATR={atr:.2f}")

    if len(data) < len(SESSIONS):
        print("WARNING: some sessions missing — results are weaker than intended")

    names = list(data.keys())
    print(f"\nSweep: SL{SL_GRID} x TP{TP_GRID} x R{R_GRID} x REMAX{REMAX_GRID} x HOLD{HOLD_GRID}")
    print(f"= {len(SL_GRID)*len(TP_GRID)*len(R_GRID)*len(REMAX_GRID)*len(HOLD_GRID)} configs "
          f"x {len(names)} sessions, net of {SPREAD_PTS} pts spread each round trip\n")

    # ---------------- FULL GRID ----------------
    results = []   # (cfg, {session: score})
    for sl, tp, fr, rm, hold in itertools.product(SL_GRID, TP_GRID, R_GRID, REMAX_GRID, HOLD_GRID):
        per = {}
        for name in names:
            d = data[name]
            tr = simulate(d["ticks"], d["crash"], d["atr"],
                          sl_mult=sl, tp_mult=tp, fade_r=fr, re_max=rm, hold_s=hold)
            per[name] = score(tr)
        results.append((dict(sl=sl, tp=tp, r=fr, remax=rm, hold=hold), per))

    # incumbent benchmark (per-session ceiling matches live .set: Boom 0.60)
    inc_per = {}
    for name in names:
        d = data[name]
        rm_live = 0.60 if name.startswith("BOOM") else 0.50
        tr = simulate(d["ticks"], d["crash"], d["atr"],
                      sl_mult=INCUMBENT["sl"], tp_mult=INCUMBENT["tp"],
                      fade_r=INCUMBENT["r"], re_max=rm_live, hold_s=INCUMBENT["hold"])
        inc_per[name] = score(tr)
    inc_total = sum(s["r"] for s in inc_per.values())
    print("INCUMBENT (SL0.4 TP3.2 R0.30 hold2400s):")
    for name in names:
        s = inc_per[name]
        print(f"   {name}: n={s['n']} R={s['r']:+.2f} PF={s['pf']:.2f} DD={s['dd']:.2f}")
    print(f"   TOTAL R={inc_total:+.2f}\n")

    # ---------------- RANKING ----------------
    ranked = sorted(results, key=lambda kv: sum(s["r"] for s in kv[1].values()), reverse=True)
    print("TOP 20 configs by aggregate net R (all sessions):")
    print(f"{'rank':>4} {'SL':>4} {'TP':>4} {'R':>4} {'REmax':>5} {'hold':>5} | "
          f"{'TOT R':>7} | " + " | ".join(f"{n:>13}" for n in names) +
          " | worst-day R")
    for i, (cfg, per) in enumerate(ranked[:20]):
        tot = sum(s["r"] for s in per.values())
        worst = min(s["r"] for s in per.values())
        cells = " | ".join(f"n={per[n]['n']:>2} {per[n]['r']:>+6.2f}" for n in names)
        print(f"{i:>4} {cfg['sl']:>4} {cfg['tp']:>4} {cfg['r']:>4} {cfg['remax']:>5} {cfg['hold']:>5} | "
              f"{tot:>+7.2f} | {cells} | {worst:>+6.2f}")

    # ---------------- ROBUSTNESS GATE ----------------
    print("\nROBUSTNESS GATE — filters every candidate must pass:")
    print("  F1: >= 4 trades total across sessions (sample matters)")
    print("  F2: no session below -1.5R (no one-session blowup)")
    print("  F3: ATR x0.8 and x1.2 aggregate >= 0R (vol-estimate error)")
    print("  F4: spread x1.5 aggregate >= 0R (cost stress)")

    def run_all(cfg, atr_mult=1.0, spread=SPREAD_PTS):
        tot = {}
        for name in names:
            d = data[name]
            rm_live = 0.60 if name.startswith("BOOM") else 0.50
            tr = simulate(d["ticks"], d["crash"], d["atr"] * atr_mult,
                          sl_mult=cfg["sl"], tp_mult=cfg["tp"], fade_r=cfg["r"],
                          re_max=cfg["remax"], hold_s=cfg["hold"], spread=spread)
            tot[name] = score(tr)
        return tot

    finalists = []
    for cfg, per in ranked[:150]:                      # shortlist for speed
        n_tot = sum(s["n"] for s in per.values())
        worst = min(s["r"] for s in per.values())
        if n_tot < 4 or worst < -1.5:
            continue
        s08 = sum(s["r"] for s in run_all(cfg, atr_mult=0.8).values())
        s12 = sum(s["r"] for s in run_all(cfg, atr_mult=1.2).values())
        s15 = sum(s["r"] for s in run_all(cfg, spread=SPREAD_PTS * 1.5).values())
        if s08 >= 0 and s12 >= 0 and s15 >= 0:
            finalists.append((cfg, per, s08, s12, s15))

    print(f"\nFINALISTS: {len(finalists)} of {len(ranked)} configs passed")
    print(f"{'SL':>4} {'TP':>4} {'R':>4} {'REmax':>5} {'hold':>5} | {'TOT':>6} | "
          f"{'ATR0.8':>7} {'ATR1.2':>7} {'SPR1.5':>7} | worst-day")
    for cfg, per, s08, s12, s15 in finalists[:25]:
        tot = sum(s["r"] for s in per.values())
        worst = min(s["r"] for s in per.values())
        print(f"{cfg['sl']:>4} {cfg['tp']:>4} {cfg['r']:>4} {cfg['remax']:>5} {cfg['hold']:>5} | "
              f"{tot:>+6.2f} | {s08:>+7.2f} {s12:>+7.2f} {s15:>+7.2f} | {worst:>+6.2f}")

    # ---------------- TRADE-LEVEL DIAGNOSIS of top finalist vs incumbent ----
    if finalists:
        cfg = finalists[0][0]
        print(f"\nTOP FINALIST detail: SL={cfg['sl']} TP={cfg['tp']} R={cfg['r']} "
              f"REmax={cfg['remax']} hold={cfg['hold']}s")
        for name in names:
            d = data[name]
            tr = simulate(d["ticks"], d["crash"], d["atr"], sl_mult=cfg["sl"],
                          tp_mult=cfg["tp"], fade_r=cfg["r"], re_max=cfg["remax"],
                          hold_s=cfg["hold"])
            print(f"  {name}:")
            for t in tr:
                d2 = "BUY " if t["dir"] > 0 else "SELL"
                print(f"    {fmt_t(t['t'])}  {d2} jump={t['jump']:>5.1f} "
                      f"R={t['r']:+6.2f} hold={t['hold']/60:4.0f}m  {t['reason']}")

    # stability note: where does the incumbent rank?
    inc_rank = next((i for i, (cfg, _) in enumerate(ranked)
                     if cfg == {k: INCUMBENT[k] for k in ('sl', 'tp', 'r', 'remax', 'hold')}), None)
    print(f"\nIncumbent rank in full grid: {inc_rank if inc_rank is not None else '>150 (or per-session ceiling differs)'}")


if __name__ == "__main__":
    main()
