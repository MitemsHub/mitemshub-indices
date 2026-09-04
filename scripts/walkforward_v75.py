"""Walk-forward validation harness for VOL75 config rounds (pre-registered).

Round 1 (artifact walkforward_v2629.json): static v26.29 stack vs legacy +
  ablations/neighbors on the 40-day dataset, 4 folds. Verdict NOT VALIDATED
  (consistency criteria failed; EMA-side veto shows no OOS separation).

Round 2 (artifact walkforward_v2631_gate.json): adaptive family-throttle vs
  static configs, same 4 folds. Verdict NOT VALIDATED (tp18-only was the only
  fold-consistent config; throttle helps the full-period metric only).

Round 3 (artifact walkforward_210d.json): the dataset is extended
  to 210 days of broker M15 bars (2026-02-06 .. 2026-09-04, 20,160 bars).
  After the 480-bar burn-in, 26 non-overlapping 8-day folds cover
  2026-02-12 .. 2026-09-04 (the last fold absorbs the 4-day remainder).
  ~10x the scored folds of rounds 1-2, ~500 trades per config.

Round 4 — THIS RUN (artifact walkforward_210d_r4_gate.json): the adaptive-
  gate follow-up. regime_gate_study_v2.py (pre-registered, calibration
  F01-F16 / validation F17-F26) found the static z_abs gate NOT VALIDATED
  (directionally right OOS but deletes 56% of trades for +0.3R) and the
  family-throttle's causal basis real but weak (hot-window +0.013R vs cold
  +0.099R on 283 calibration PB trades). The one combination never tested:
  throttle ON TOP of tp18 (rounds 2 tested throttle on legacy only).

  Configs (fixed a priori, equity $200, honest stop-level booking):
    legacy      tp 2.4, no veto, pb-min 0.30   (v26.27 behaviour)
    v2629       tp 1.8, veto,    pb-min 0.60   (deployed stack)
    tp18        tp 1.8 only                   (round-3 best)
    throttle    legacy + family throttle (10-trade / -3R / probe-5)
    gate+stack  v2629 + family throttle
    tp18+thr    tp 1.8 + family throttle      (NEW in round 4)

  PASS criteria per candidate — ALL must hold, else NOT VALIDATED:
    V1. total R across all 26 folds > 0.
    V2. positive in >= 60% of folds.
    V3. worst fold R > -3.0.
    V4. beats tp18 total R (round-3 reference winner).
    V5. median fold R > 0.
    V6. fold-mean t-stat >= 1.5.

  Caveat: still one instrument, one broker, one 7-month regime stretch; the
  paper run remains the final gate. But with ~25 folds this is real
  statistical power, not the 4-fold screen of rounds 1-2.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from certify_v75 import certify, load  # noqa: E402

DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
EQ = 200.0
FOLD_DAYS = int(os.environ.get("WF_FOLD_DAYS", "8"))
# WF_CONFIGS: comma list from the registry below (default = the full round-4 set)
_REGISTRY = {
    "legacy":     dict(tp_mult=2.4, ema_side_filter=False, pb_min=None),
    "v2629":      dict(tp_mult=1.8, ema_side_filter=True,  pb_min=0.60),
    "tp18":       dict(tp_mult=1.8, ema_side_filter=False, pb_min=None),
    "throttle":   dict(tp_mult=2.4, ema_side_filter=False, pb_min=None, family_throttle=True),
    "gate+stack": dict(tp_mult=1.8, ema_side_filter=True,  pb_min=0.60, family_throttle=True),
    "tp18+thr":   dict(tp_mult=1.8, ema_side_filter=False, pb_min=None, family_throttle=True),
}

CONFIGS = {k: _REGISTRY[k.strip()] for k in
           os.environ.get("WF_CONFIGS", "legacy,v2629,tp18,throttle,gate+stack,tp18+thr").split(",")}


def build_folds():
    m15 = load("m15.csv")
    t0 = m15[480]["t"]                       # burn-in ends ~Feb 12
    t_end = m15[-1]["t"]
    folds = []
    cur = t0
    n = 0
    while cur < t_end:
        nxt = cur + __import__("datetime").timedelta(days=FOLD_DAYS)
        # fold ends at the next boundary, or the dataset end for the last fold
        end = min(nxt, t_end)
        folds.append((f"F{n+1:02d}", cur, end))
        cur = nxt
        n += 1
    return folds


def tstat(rs):
    m = len(rs)
    mean = sum(rs) / m
    var = sum((x - mean) ** 2 for x in rs) / (m - 1) if m > 1 else 0.0
    return mean / (var ** 0.5 / m ** 0.5) if var > 0 else 0.0


def main():
    folds = build_folds()
    print(f"folds: {len(folds)} x {FOLD_DAYS}d  "
          f"({folds[0][1]:%m-%d} .. {folds[-1][2]:%m-%d})")
    results = {}
    for fname, start, end in folds:
        for cname, kw in CONFIGS.items():
            rep = certify(EQ, start=start, end=end, **kw)
            results.setdefault(cname, {})[fname] = {
                "n": rep["n"], "r": rep["total_r"], "wr": rep["win_rate"],
                "dd": rep["max_drawdown_pct"], "eq_final": rep["equity_final"],
            }
        line = "  ".join(f"{c}:{results[c][fname]['r']:+6.2f}" for c in CONFIGS)
        print(f"{fname} {line}")

    ref = "tp18" if "tp18" in results else next(iter(results))
    lg = sum(results[ref][f]["r"] for f in results[ref])
    print(f"\n== verdicts (round 4, {len(next(iter(results.values())))} folds; reference = {ref}) ==")
    verdicts = {}
    for cname in CONFIGS:
        if cname == ref:
            continue
        rs = [results[cname][f]["r"] for f in results["legacy"]]
        tot = sum(rs)
        pos = sum(1 for x in rs if x > 0)
        checks = {
            "V1 total>0": tot > 0,
            "V2 pos>=60%": pos >= 0.6 * len(rs),
            "V3 worst>-3": min(rs) > -3.0,
            "V4 beats tp18": tot > lg,
            "V5 median>0": sorted(rs)[len(rs) // 2] > 0,
            "V6 t>=1.5": tstat(rs) >= 1.5,
        }
        ok = all(checks.values())
        verdicts[cname] = {"ok": ok, "total_r": round(tot, 2), "pos_folds": pos,
                           "worst": round(min(rs), 2), "t": round(tstat(rs), 2),
                           "checks": {k: bool(v) for k, v in checks.items()}}
        flags = " ".join(f"[{'P' if v else 'F'}]{k.split()[0]}" for k, v in checks.items())
        print(f"  {cname:11s} total={tot:+8.2f}R pos={pos:2d}/{len(rs)} "
              f"worst={min(rs):+6.2f} t={tstat(rs):+4.2f}  {flags}  -> "
              f"{'VALIDATED' if ok else 'NOT VALIDATED'}")
    print(f"  {ref} total={lg:+8.2f}R (reference)")

    path = os.environ.get("WF_OUT", os.path.join(DATA, "walkforward_210d_r4_gate.json"))
    with open(path, "w") as f:
        json.dump({"round": 4, "fold_days": FOLD_DAYS, "equity": EQ,
                   "results": results, "verdicts": verdicts}, f, indent=1)
    print(f"artifact: {path}")


if __name__ == "__main__":
    main()
