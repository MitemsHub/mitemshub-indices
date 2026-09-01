#!/usr/bin/env python3
"""QUICK-TP STUDY: does banking small, fast wins beat waiting for one big TP?

Motivation (2026-09-01 request): instead of holding for one large target,
run an ultra-active profile — many trades, each with a small, achievable
target (roughly 1-1.5R), banking wins quickly instead of waiting for a
rare large gain.

Two legs are scored on real recorded data, net of spread:

  1. TICK-FADE (Boom/Crash 1000) on the three recorded tick sessions
     (artifacts/ticks/), reusing the validated EA-order replay from
     cb_exit_grid_search.py. Swept: TP (xATR), MIN_RR gate, hold time,
     trailing mode (full trail vs take-profit-and-done), cooldown.

  2. BAND-FADE (M5, EA-faithful sigma pipeline from
     backtest_real_history.py) on the Boom/Crash 1000 30k-bar caches
     (~104 days). Swept: target (x sigma_h), cooldown, min RR.

All results are in R units (1R = planned SL distance of that config) so
configs with different stop widths stay comparable. A config "wins" when
it raises total R AND trades/day without a worse max drawdown than the
incumbent.

Usage:
    .venv/Scripts/python.exe scripts/cb_quick_tp_study.py
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ART = ROOT / "artifacts"
TICK_DIR = ART / "ticks"

# ---- fixed EA parameters (shared with cb_exit_grid_search.py) ----
TICK_SPIKE_PTS = 3.0
SPIKE_TIMEOUT_S = 900
GAP_S = 300
BAR = 300
SPREAD_PTS = 0.483

# incumbent live geometry: SL 0.3xATR (v26.8) / TP 4.0xATR, R anchor 0.4,
# hold 8 M5 bars, full trailing, min RR 2.0, cooldown 1 bar
INCUMBENT = dict(sl=0.3, tp=4.0, r=0.4, remax_boom=0.60, remax_crash=0.50,
                 hold=2400, min_rr=2.0, cooldown_bars=1, trail=True)

SESSIONS = [
    ("BOOM  08-29", "MITEMSHUB_ticks_Boom_1000_Index_20260829.csv", False, 0.60),
    ("BOOM  08-30", "MITEMSHUB_ticks_Boom_1000_Index_20260830.csv", False, 0.60),
    ("CRASH 08-30", "MITEMSHUB_ticks_Crash_1000_Index_20260830.csv", True, 0.50),
]


def load_ticks(glob: str):
    import csv
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


def scaled_fade_entry(jump: float, fade_r: float) -> float:
    lo = fade_r * math.sqrt(12.0 / max(jump, 1.0))
    return max(0.18, min(0.40, lo))


def simulate_tick_fade(ticks, is_crash: bool, atr: float, *, sl_mult: float,
                       tp_mult: float, fade_r: float, re_max: float,
                       hold_s: float, min_rr: float, trail: bool,
                       cooldown_s: float, spread: float = SPREAD_PTS):
    """EA-order replay with quick-TP knobs.

    Differences from cb_exit_grid_search.simulate:
      * min_rr is a parameter (the deployed gate is 2.0; a quick-TP profile
        must lower it or every small target is rejected before entry).
      * trail=False disables the +1R BE/trail and exits only at TP/SL/time
        — the pure "bank the small target" mode.
      * cooldown_s re-arms a new entry after a close (0 = immediately).
    """
    trades = []
    pos = None
    cur = None
    rearm_at = 0.0
    n = len(ticks)

    def close_pos(ts, price, reason):
        nonlocal pos, rearm_at
        if pos["dir"] > 0:
            r = (price - pos["entry"]) / pos["risk_pts"]
        else:
            r = (pos["entry"] - (price + spread)) / pos["risk_pts"]
        trades.append({"t": pos["t_entry"], "dir": pos["dir"], "r": r,
                       "reason": reason, "hold": ts - pos["t_entry"]})
        rearm_at = ts + cooldown_s
        pos = None

    for i in range(1, n):
        ts, bid, _ = ticks[i]
        if ts - ticks[i - 1][0] > GAP_S:
            if pos is not None:
                close_pos(ticks[i - 1][0], ticks[i - 1][1], "GAP")
            cur = None
            continue

        if pos is not None:
            if trail:
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
            elif pos is None and ts >= rearm_at and \
                    retrace >= scaled_fade_entry(cur["jump"], fade_r):
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
                if rr < min_rr:
                    cur = None
                else:
                    pos = {"dir": 1 if is_crash else -1, "entry": entry_px,
                           "sl": sl, "tp": tp, "risk_pts": sl_d, "t_entry": ts,
                           "peak_gain": 0.0}
                    cur = None

    if pos is not None:
        ts, bid, _ = ticks[-1]
        close_pos(ts, bid, "END")
    return trades


def score(trades, span_s: float) -> dict:
    total = sum(t["r"] for t in trades)
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": len(trades), "r": round(total, 2),
            "per_day": round(len(trades) / max(span_s / 86400.0, 1e-9), 2),
            "wr": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
            "pf": round(gw / gl, 2) if gl > 0 else 99.0,
            "dd": round(dd, 2),
            "avg_hold_s": round(sum(t["hold"] for t in trades) / len(trades)) if trades else 0}


# ---------------- band-fade (EA-faithful M5 pipeline) ----------------
GATE_RATIO, SIGMA_EMA_LEN, STOP_MULT, HOLD_SEC, WARMUP = 1.25, 30, 0.10, 3600, 60


def simulate_band(bars, z_entry: float, tgt_mult: float, cooldown_bars: int,
                  min_rr: float):
    """backtest_real_history.simulate with quick-TP knobs (cooldown, min RR)."""
    n = len(bars)
    closes = [b["close"] for b in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    sigma_ema, trades, reasons = None, [], []
    i, cooldown = WARMUP, 0
    while i < n - 1:
        seg = rets[max(0, i - 19): i]
        if len(seg) >= 15 and i >= WARMUP:
            s_now = statistics_stdev(seg)
            a = 2.0 / (SIGMA_EMA_LEN + 1)
            sigma_ema = s_now if sigma_ema is None else a * s_now + (1 - a) * sigma_ema
            if s_now > GATE_RATIO * sigma_ema and cooldown <= 0:
                sma = sum(closes[i - 19: i + 1]) / 20.0
                if sma > 0 and closes[i] > 0:
                    z = math.log(closes[i] / sma) / s_now
                    d = -1 if z >= z_entry else (1 if z <= -z_entry else 0)
                    if d != 0:
                        hb = max(1, round(HOLD_SEC / ((bars[1]["epoch"] - bars[0]["epoch"]))))
                        sig_h = s_now * math.sqrt(hb)
                        stop_f, tgt_f = STOP_MULT * sig_h, tgt_mult * sig_h
                        if tgt_f / stop_f >= min_rr:
                            entry = closes[i]
                            sl = entry - d * stop_f * entry
                            tp = entry + d * tgt_f * entry
                            out_r, reason = None, "TIME"
                            for j in range(i + 1, min(n, i + 1 + hb + 2)):
                                hit_sl = bars[j]["low"] <= sl if d > 0 else bars[j]["high"] >= sl
                                hit_tp = bars[j]["high"] >= tp if d > 0 else bars[j]["low"] <= tp
                                if hit_sl:
                                    out_r, reason = -1.0, "STOP"
                                    break
                                if hit_tp:
                                    out_r, reason = tgt_f / stop_f, "TARGET"
                                    break
                            if out_r is None:
                                jx = min(n - 1, i + hb)
                                out_r = d * (closes[jx] - entry) / entry / stop_f
                            trades.append(out_r)
                            reasons.append(reason)
                            cooldown = cooldown_bars
                            i += 1
                            continue
        cooldown = max(0, cooldown - 1)
        i += 1
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t > 0]
    gl, gw = sum(-t for t in trades if t < 0), sum(wins)
    dd = peak = cum = 0.0
    for t in trades:
        cum += t
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    days = (bars[-1]["epoch"] - bars[0]["epoch"]) / 86400.0
    rc = {k: reasons.count(k) for k in ("TARGET", "STOP", "TIME")}
    return {"trades": len(trades), "per_day": round(len(trades) / days, 2),
            "wr": round(100 * len(wins) / len(trades), 1),
            "pf": round(gw / gl, 2) if gl > 0 else 99.0,
            "exp_r": round(sum(trades) / len(trades), 3),
            "total_r": round(sum(trades), 2), "max_dd_r": round(dd, 2),
            "exits": rc}


def statistics_stdev(xs):
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def main():
    print("=" * 100)
    print("QUICK-TP STUDY — bank small fast wins vs wait for one big TP")
    print("=" * 100)

    # ---------------- 1. tick-fade sweep ----------------
    sessions = []
    for name, glob, is_crash, re_max in SESSIONS:
        ticks = load_ticks(glob)
        if len(ticks) < 500:
            print(f"[skip] {name}")
            continue
        atr = m5_atr_from_ticks(ticks)
        sessions.append((name, ticks, is_crash, re_max, atr,
                         (ticks[-1][0] - ticks[0][0])))
    print(f"\n--- TICK-FADE: TP sweep (SL=0.3xATR, R=0.4 anchor, trail modes) ---")
    tp_grid = (1.0, 1.2, 1.5, 2.0, 2.5, 3.2, 4.0)
    minrr_grid = (0.8, 1.0, 1.5, 2.0)
    rows = []
    for tp, min_rr, trail in itertools.product(tp_grid, minrr_grid, (True, False)):
        per = {}
        for name, ticks, is_crash, re_max, atr, span in sessions:
            tr = simulate_tick_fade(ticks, is_crash, atr, sl_mult=0.3, tp_mult=tp,
                                    fade_r=0.4, re_max=re_max, hold_s=2400,
                                    min_rr=min_rr, trail=trail, cooldown_s=0)
            per[name] = score(tr, span)
        tot_r = sum(s["r"] for s in per.values())
        tot_n = sum(s["n"] for s in per.values())
        worst = min(s["r"] for s in per.values())
        rows.append((tot_r, tp, min_rr, trail, tot_n, worst, per))
    rows.sort(reverse=True)
    print(f"{'TP':>4} {'minRR':>5} {'trail':>5} | {'totR':>7} {'trades':>6} {'worst':>6} | " +
          " | ".join(f"{n:>13}" for n, *_ in sessions))
    for tot_r, tp, min_rr, trail, tot_n, worst, per in rows:
        cells = " | ".join(f"n={per[n]['n']:>2} {per[n]['r']:>+6.2f}" for n, *_ in sessions)
        print(f"{tp:>4} {min_rr:>5} {str(trail):>5} | {tot_r:>+7.2f} {tot_n:>6} {worst:>+6.2f} | {cells}")

    print(f"\n--- TICK-FADE: cooldown / hold sweep at the best TP family ---")
    best_tp, best_minrr = rows[0][1], rows[0][2]
    for cooldown, hold in itertools.product((0, 30, 120, 300), (600, 1200, 2400)):
        per = {}
        for name, ticks, is_crash, re_max, atr, span in sessions:
            tr = simulate_tick_fade(ticks, is_crash, atr, sl_mult=0.3, tp_mult=best_tp,
                                    fade_r=0.4, re_max=re_max, hold_s=hold,
                                    min_rr=best_minrr, trail=False, cooldown_s=cooldown)
            per[name] = score(tr, span)
        tot_r = sum(s["r"] for s in per.values())
        tot_n = sum(s["n"] for s in per.values())
        worst = min(s["r"] for s in per.values())
        pd = sum(s["per_day"] for s in per.values())
        print(f"  cd={cooldown:>3}s hold={hold:>4}s | totR {tot_r:>+7.2f} trades {tot_n:>3} "
              f"({pd:>5.1f}/d) worst {worst:>+6.2f}")

    # ---------------- 1b. ROBUSTNESS GATE on distinct TP families ----------------
    # Same protocol as cb_exit_grid_search.py:
    #   F1: >= 4 trades total across sessions (sample matters)
    #   F2: no session below -1.5R (no one-session blowup)
    #   F3: ATR x0.8 and x1.2 aggregate >= 0R (vol-estimate error)
    #   F4: spread x1.5 aggregate >= 0R (cost stress)
    # minRR rows are identical in the sweep (the pre-spike TP clamp dominates
    # the RR calc, so the gate never binds) — test each (tp, trail) family at
    # the deployed minRR 2.0 once.
    print("\n--- ROBUSTNESS GATE (F1-F4) on distinct TP geometry families ---")
    print("  F1: >=4 trades | F2: no session < -1.5R | F3: ATR x0.8 & x1.2 >= 0R | F4: spread x1.5 >= 0R")
    families = []
    seen = set()
    for tot_r, tp, min_rr, trail, tot_n, worst, per in rows:
        key = (tp, trail)
        if key not in seen:
            seen.add(key)
            families.append((tp, trail))

    def run_family(tp, trail, atr_mult=1.0, spread=SPREAD_PTS):
        per = {}
        for name, ticks, is_crash, re_max, atr, span in sessions:
            tr = simulate_tick_fade(ticks, is_crash, atr * atr_mult,
                                    sl_mult=0.3, tp_mult=tp, fade_r=0.4,
                                    re_max=re_max, hold_s=2400, min_rr=2.0,
                                    trail=trail, cooldown_s=0, spread=spread)
            per[name] = score(tr, span)
        return per

    print(f"{'TP':>4} {'trail':>5} | {'base':>7} {'ATR0.8':>7} {'ATR1.2':>7} {'SPR1.5':>7} "
          f"{'worst':>6} {'trades':>6} | verdict")
    survivors = []
    for tp, trail in families:
        base = run_family(tp, trail)
        s08 = sum(s["r"] for s in run_family(tp, trail, atr_mult=0.8).values())
        s12 = sum(s["r"] for s in run_family(tp, trail, atr_mult=1.2).values())
        s15 = sum(s["r"] for s in run_family(tp, trail, spread=SPREAD_PTS * 1.5).values())
        tot = sum(s["r"] for s in base.values())
        n = sum(s["n"] for s in base.values())
        worst = min(s["r"] for s in base.values())
        fails = []
        if n < 4:
            fails.append("F1")
        if worst < -1.5:
            fails.append("F2")
        if s08 < 0 or s12 < 0:
            fails.append("F3")
        if s15 < 0:
            fails.append("F4")
        verdict = "PASS" if not fails else "FAIL(" + ",".join(fails) + ")"
        if not fails:
            survivors.append((tot, tp, trail, n))
        print(f"{tp:>4} {str(trail):>5} | {tot:>+7.2f} {s08:>+7.2f} {s12:>+7.2f} {s15:>+7.2f} "
              f"{worst:>+6.2f} {n:>6} | {verdict}")

    survivors.sort(reverse=True)
    if survivors:
        print(f"\nSURVIVORS (ranked by base total R): "
              + ", ".join(f"TP{tp} trail={'ON' if tr else 'OFF'} (+{tot:.2f}R, {n} tr)"
                          for tot, tp, tr, n in survivors))
    else:
        print("\nSURVIVORS: none — no TP geometry passed all four gates")

    # ---------------- 2. band-fade sweep ----------------
    print(f"\n--- BAND-FADE (M5, EA-faithful): target/cooldown sweep, z=2.0 ---")
    sys.path.insert(0, str(ROOT))
    from scripts.mt5_data import _read_cache
    band_rows = []
    for sym in ("Boom 1000 Index", "Crash 1000 Index"):
        arr = _read_cache(sym, "M5")
        bars = [{"epoch": float(r["epoch"]), "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "close": float(r["close"])} for r in arr]
        for tgt, cd in itertools.product((0.2, 0.3, 0.4, 0.6, 0.8), (0, 1, 2)):
            r = simulate_band(bars, 2.0, tgt, cd, min_rr=2.5)
            r.update(symbol=sym, tgt=tgt, cd=cd)
            band_rows.append(r)
    print(f"{'symbol':<18} {'tgt':>4} {'cd':>2} | {'trades':>6} {'/d':>5} {'wr%':>5} "
          f"{'PF':>5} {'expR':>6} {'totR':>7} {'dd':>5} | T/S/Tm")
    for r in sorted(band_rows, key=lambda r: (r["symbol"], r["tgt"], r["cd"])):
        if not r.get("trades"):
            print(f"{r['symbol']:<18} {r['tgt']:>4} {r['cd']:>2} | no trades")
            continue
        ex = r["exits"]
        print(f"{r['symbol']:<18} {r['tgt']:>4} {r['cd']:>2} | {r['trades']:>6} "
              f"{r['per_day']:>5} {r['wr']:>5} {r['pf']:>5} {r['exp_r']:>+6.3f} "
              f"{r['total_r']:>+7.2f} {r['max_dd_r']:>5} | "
              f"{ex['TARGET']}/{ex['STOP']}/{ex['TIME']}")

    out = {"tick_fade": [{"tp": tp, "min_rr": mrr, "trail": tr, "tot_r": tr_,
                          "trades": n, "worst": w,
                          "per_session": {k: v for k, v in per.items()}}
                         for tr_, tp, mrr, tr, n, w, per in rows[:15]],
           "robustness": [{"tp": tp, "trail": trail, "base_r": tot, "trades": n}
                          for tot, tp, trail, n in survivors],
           "band_fade": band_rows}
    (ART / "cb_quick_tp_study.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\n[wrote] artifacts/cb_quick_tp_study.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
