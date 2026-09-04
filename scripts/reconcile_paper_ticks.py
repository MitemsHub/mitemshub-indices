"""Reconcile live paper fills against the tick-study baseline (pre-registered).

PURPOSE. The v26.28+ paper engine makes virtual fills and runs the exit
ladder live. The fast-fail tick study (study_fastfail_ticks.py) validated
that same ladder offline against 1.5M real broker ticks. This tool checks,
once >= --min-days of paper ledger exists, that the LIVE paper engine still
matches the tick-replay reality — i.e. that no drift has crept into fills,
ladder management, or bookkeeping — and quantifies the paper engine's
built-in conservatism (InpPaperSpreadMult entry shift) separately.

WHAT IT MEASURES (per closed ledger trade, simulated tick-by-tick through
the SAME ladder constants as the study):
  F1. ladder delta  = ledger R − tick-ladder R run FROM the ledger's own
      fill (entry/sl/tp as written). Should be ~0: same geometry, same
      ladder; differences = management/bookkeeping drift.
  F2. fill shift    = ledger entry − tick-derived fair fill at the same
      millisecond (ask+extra for BUY, bid−extra for SELL). Should be
      ≈ +spread_mult−1 × spread for BUY, −... for SELL (conservative),
      i.e. the paper engine trades a slightly WORSE fill on purpose.
  F3. exit reason agreement (STOP→SL, TARGET→TP, others identity) ≥ 75%.
  F4. exit price sanity: |ledger exit − tick price at close| ≤ 3×median
      spread (catches clock/price drift between virtual and broker feed).

VERDICT (fixed 2026-09-04, before data exists):
  KEEP COLLECTING          — coverage < --min-days (default 7).
  MATCHED                  — |mean F1| ≤ 0.10R with bootstrap CI covering 0,
                             F3 and F4 pass. Fill shift F2 reported (may be
                             legitimately conservative).
  OPTIMISTIC-DRIFT         — ledger systematically BETTER than tick replay
                             (mean F1 > +0.10R, CI excludes 0). Dangerous:
                             the virtual engine is kinder than reality.
  CONSERVATIVE-DRIFT       — ledger systematically worse (mean F1 < −0.10R):
                             spread mult or slippage model too harsh; cert
                             numbers UNDERSTATE live performance.
  REASON/PRICE-DRIFT       — F3/F4 fail (mechanics diverged even if R agrees).

Usage:
  python scripts/reconcile_paper_ticks.py --a-dir "<terminal>/MQL5/Files" \
      [--b-dir "<terminalB>/MQL5/Files"] [--min-days 7] [--ticks FILE]
Writes: artifacts/v75_replay/paper_tick_reconciliation.json

NOTE: epochs in the ledger are SECONDS (TimeCurrent), ms only inside the
tick file. Ladder constants are imported from study_fastfail_ticks so the
baseline cannot silently diverge from the study.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import statistics as st
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from study_fastfail_ticks import (  # noqa: E402  (single source of ladder truth)
    BAR, MAX_BARS, PLOCK_HW, PLOCK_Z, BE_TRIG, TRAIL_START, TRAIL_DIST,
    ECUT_BARS, ECUT_R, ECUT_HW, TIME_BARS, TIME_EXT_BARS, boot_ci,
)

DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
OUT = os.path.join(DATA, "paper_tick_reconciliation.json")
LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
PULL = os.path.join(HERE, "pull_v75_ticks.py")
MIN_DAYS_DEFAULT = 7.0
BIAS_R = 0.10             # systematic ladder-delta threshold
REASON_AGREE_MIN = 0.75
EXIT_TOL_SPREADS = 3.0
REASON_MAP = {"STOP": "SL", "TARGET": "TP", "BE": "BE"}


# ---------------------------------------------------------------- ledger ---
def load_ledger(path):
    """EA wire format (seconds!): OPEN,epoch,ticket,dir,entry,sl,tp,vol,eff_risk,
    orig_risk,max_hold,tag / CLOSE,epoch,ticket,reason,exit,r,pnl,veq / EQ,veq."""
    trades, curve, problems, opens = [], [], [], {}
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if not p:
                continue
            if p[0] == "OPEN":
                opens[p[2]] = dict(epoch=int(p[1]), dir=int(p[3]), entry=float(p[4]),
                                   sl=float(p[5]), tp=float(p[6]), vol=float(p[7]),
                                   eff_risk=float(p[8]))
            elif p[0] == "CLOSE":
                o = opens.pop(p[2], None)
                trades.append(dict(epoch=int(p[1]), ticket=p[2], reason=p[3],
                                   exit=float(p[4]), r=float(p[5]), pnl=float(p[6]),
                                   veq=float(p[7]),
                                   open_epoch=o["epoch"] if o else None,
                                   odir=o["dir"] if o else None,
                                   oentry=o["entry"] if o else None,
                                   osl=o["sl"] if o else None,
                                   otp=o["tp"] if o else None))
            elif p[0] == "EQ":
                curve.append(float(p[1]))
    if len(opens) > 1:
        problems.append(f"{len(opens)} OPEN rows without CLOSE")
    for a, b in zip(curve, curve[1:]):
        if abs(b - a) > 1e9:
            problems.append("veq discontinuity")
            break
    return trades, curve, problems


# ------------------------------------------------------------- tick sim ---
def sim_ladder(t, ts, bid, ask):
    """Ladder from the LEDGER's own fill; same constants as the tick study.
    Returns (r, reason) or (None, why-skipped)."""
    d = t["odir"]
    if d is None:
        return None, "no-open-row"
    entry, sd = t["oentry"], abs(t["oentry"] - t["osl"])
    if sd <= 0:
        return None, "zero-risk"
    tp_r = abs(t["otp"] - t["oentry"]) / sd
    sl, tp = t["osl"], t["otp"]
    t0 = t["open_epoch"] * 1000
    i0 = _bisect(ts, t0)
    if i0 >= len(ts):
        return None, "before-tick-coverage"
    hw = 0.0
    t_end = t0 + MAX_BARS * BAR
    i = i0
    while i < len(ts) and ts[i] <= t_end:
        rc = ((bid[i] - entry) if d > 0 else (entry - ask[i])) / sd
        fav = rc                                   # favorable excursion source
        hw = max(hw, fav)
        hit_sl = (bid[i] <= sl) if d > 0 else (ask[i] >= sl)
        hit_tp = (bid[i] >= tp) if d > 0 else (ask[i] <= tp)
        if hit_sl and not hit_tp:
            return rc, ("BE" if abs((sl - entry) / sd) < 1e-9 and abs(rc) < 0.05 else "SL")
        if hit_tp and not hit_sl:
            return tp_r, "TP"
        if hit_sl and hit_tp:
            return rc, "SL(ambig)"
        bars = (ts[i] - t0) // BAR
        if hw >= PLOCK_HW and 0 < rc <= PLOCK_Z:
            return rc, "PLOCK"
        if hw >= BE_TRIG:
            ns = entry
            if (d > 0 and ns > sl) or (d < 0 and ns < sl):
                sl = ns
        if hw >= TRAIL_START:
            ns = (bid[i] if d > 0 else ask[i]) - d * TRAIL_DIST * sd
            if (d > 0 and ns > sl) or (d < 0 and ns < sl):
                sl = ns
        if bars >= ECUT_BARS and rc <= ECUT_R and hw < ECUT_HW:
            return rc, "ECUT"
        if bars >= TIME_BARS and rc <= 0.2:
            return rc, "TIME" if bars < TIME_EXT_BARS else "TIME_EXT"
        i += 1
    last = len(ts) - 1
    return ((bid[last] - entry) if d > 0 else (entry - ask[last])) / sd, "EOD"


def _bisect(ts, x):
    lo, hi = 0, len(ts)
    while lo < hi:
        mid = (lo + hi) // 2
        if ts[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


# --------------------------------------------------------------- ticks ----
def load_ticks(path):
    ts, bid, ask = [], [], []
    with open(path) as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            ts.append(int(row[0])); bid.append(float(row[1])); ask.append(float(row[2]))
    return ts, bid, ask


def ensure_tick_coverage(ts, bid, ask, need_lo_ms, need_hi_ms, ticks_path):
    """If the ledger window isn't covered, pull the missing span from the broker."""
    if not ts or need_lo_ms < ts[0] or need_hi_ms > ts[-1]:
        d1 = datetime.fromtimestamp(need_lo_ms / 1000, tz=timezone.utc).date()
        d2 = datetime.fromtimestamp(need_hi_ms / 1000, tz=timezone.utc).date() \
            + __import__("datetime").timedelta(days=1)
        out = ticks_path.replace(".csv", f"_{d1}_{d2}.csv")
        print(f"tick coverage insufficient — pulling {d1} .. {d2} from broker ...")
        r = subprocess.run([sys.executable, PULL, "--from", str(d1), "--to", str(d2),
                            "--out", out], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("broker pull failed — run scripts/pull_v75_ticks.py manually for "
                  "the window above, then re-run with --ticks")
            sys.exit(2)
        return load_ticks(out), out
    return (ts, bid, ask), ticks_path


# ---------------------------------------------------------------- main ----
def reconcile(ledger_path, ts, bid, ask, spread_med):
    trades, curve, problems = load_ledger(ledger_path)
    closed = [t for t in trades if t["open_epoch"] is not None]
    deltas, reasons_ok, exit_bad, fill_shifts = [], 0, 0, []
    sim_rows = []
    for t in closed:
        r_tick, why = sim_ladder(t, ts, bid, ask)
        if r_tick is None:
            sim_rows.append({"ticket": t["ticket"], "skip": why})
            continue
        deltas.append(t["r"] - r_tick)
        lr = REASON_MAP.get(t["reason"], t["reason"])
        reasons_ok += (lr == why)
        # exit price sanity at ledger close second
        j = _bisect(ts, t["epoch"] * 1000)
        if j < len(ts):
            px = bid[j] if t["odir"] > 0 else ask[j]
            if abs(px - t["exit"]) > EXIT_TOL_SPREADS * spread_med:
                exit_bad += 1
        # fill shift vs fair tick fill at open
        i0 = _bisect(ts, t["open_epoch"] * 1000)
        if i0 < len(ts):
            fair = ask[i0] if t["odir"] > 0 else bid[i0]
            fill_shifts.append((t["oentry"] - fair) * t["odir"])
    n = len(deltas)
    res = {"ledger_trades": len(trades), "simmed": n, "skipped": len(sim_rows),
           "integrity": problems or "ok"}
    if n == 0:
        return res, None
    mean_d = st.mean(deltas)
    lo, hi = boot_ci(deltas)
    res.update({
        "mean_ladder_delta_r": round(mean_d, 4),
        "ci95": [round(lo, 3), round(hi, 3)],
        "mean_abs_delta_r": round(st.mean(map(abs, deltas)), 4),
        "reason_agreement": round(reasons_ok / n, 3),
        "exit_price_violations": exit_bad,
        "fill_shift_median": round(st.median(fill_shifts), 2) if fill_shifts else None,
    })
    ci0 = lo <= 0 <= hi
    if res["reason_agreement"] < REASON_AGREE_MIN:
        verdict = "REASON-DRIFT"
    elif exit_bad > max(1, int(0.05 * n)):
        verdict = "PRICE-DRIFT"
    elif mean_d > BIAS_R and not ci0:
        verdict = "OPTIMISTIC-DRIFT"
    elif mean_d < -BIAS_R and not ci0:
        verdict = "CONSERVATIVE-DRIFT"
    else:
        verdict = "MATCHED"
    return res, verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir", required=True)
    ap.add_argument("--b-dir", default="")
    ap.add_argument("--min-days", type=float, default=MIN_DAYS_DEFAULT)
    ap.add_argument("--ticks", default=os.path.join(HERE, "..", "data", "v75_ticks_cert_window.csv"))
    args = ap.parse_args()

    ticks_path = os.path.abspath(args.ticks)
    ts, bid, ask = load_ticks(ticks_path) if os.path.exists(ticks_path) else ([], [], [])
    spread_med = st.median([a - b for a, b in zip(ask[:20000], bid[:20000])]) if ts else 18.5

    out = {"rule": "pre-registered 2026-09-04, see module docstring", "arms": {}}
    overall = "KEEP COLLECTING"
    for name, d in [("A", args.a_dir)] + ([("B", args.b_dir)] if args.b_dir else []):
        path = os.path.join(d, LEDGER)
        if not os.path.exists(path):
            print(f"arm {name}: NO LEDGER at {path}")
            out["arms"][name] = {"missing": path}
            continue
        trades, curve, _ = load_ledger(path)
        if not trades:
            print(f"arm {name}: ledger exists but has no closed trades yet")
            out["arms"][name] = {"closed": 0}
            continue
        days = (trades[-1]["epoch"] - trades[0]["epoch"]) / 86400
        if days < args.min_days:
            print(f"arm {name}: {days:.1f}/{args.min_days:.0f} days of data — KEEP COLLECTING "
                  f"(~{max(0, math.ceil(args.min_days - days))}d to go)")
            out["arms"][name] = {"days": round(days, 2), "closed": len(trades)}
            continue
        lo_ms, hi_ms = trades[0]["epoch"] * 1000 - 3_600_000, trades[-1]["epoch"] * 1000 + 60_000
        (ts, bid, ask), ticks_path = ensure_tick_coverage(ts, bid, ask, lo_ms, hi_ms, ticks_path)
        spread_med = st.median([a - b for a, b in zip(ask[:20000], bid[:20000])])
        res, verdict = reconcile(path, ts, bid, ask, spread_med)
        res["days"] = round(days, 2)
        out["arms"][name] = res
        if name == "A":
            overall = verdict or "KEEP COLLECTING"
        print(f"arm {name}: {res['simmed']} trades over {days:.1f}d | "
              f"ladder delta {res.get('mean_ladder_delta_r')}R CI{res.get('ci95')} | "
              f"reason-agree {res.get('reason_agreement')} | exit-viol {res.get('exit_price_violations')} | "
              f"fill-shift {res.get('fill_shift_median')} -> {verdict}")

    out["verdict"] = overall
    print(f"\nVERDICT: {overall}")
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"artifact: {OUT}")


if __name__ == "__main__":
    main()
