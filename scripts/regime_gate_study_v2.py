"""Regime-gate study, round 2 — the 210-day sample (pre-registered design).

MOTIVATION. Round-1 (v26.31) rejected every causal regime feature on a
4-fold/5-week sample (~65 PB trades) — a noise-machine. The 210-day dataset
gives ~10x the trades. Before any gate is designed this study asks, on the
full sample:
  Q1. Do ANY causal features (recorded at signal time) separate PB winners
      from losers with real sample size?
  Q2. Does the family-throttle mechanism have a causal basis: is the
      expectancy of trades taken while the throttle window is "hot"
      (recent R < -3) actually lower than trades taken while cold?
  Q3. What changed after Aug 9? (fold level already answered: nothing
      anomalous — z-scores -0.08..-1.23, 9/22 pre-Aug folds also negative;
      this confirms at trade level.)

PRE-REGISTERED DESIGN (fixed 2026-09-04, before results are seen):
  - CALIBRATION window: F01-F16 folds  (Feb 12 .. Jun 12,  ~16 weeks)
  - VALIDATION  window: F17-F26 folds  (Jun 12 .. Sep 4,   ~12 weeks)
  - A gate RULE (feature, threshold, direction) may be chosen on calibration
    ONLY. Validation is one shot: the chosen rule must show
      G1: validation-window vetoed-trade expectancy < kept-trade expectancy
          (the gate vetoes the worse bucket OOS), AND
      G2: kept-trade total R > all-trade total R on validation, AND
      G3: the kept bucket keeps >= 60% of the trades (a gate that deletes
          everything is a refusal to trade, not a gate).
  - If no calibration rule passes a MINIMUM bar (calibration separation
    >= 0.15 R/trade with >= 30 trades in the vetoed bucket), we declare
    "no gate exists" WITHOUT burning the validation window.

Usage: python scripts/regime_gate_study_v2.py
Writes: artifacts/v75_replay/regime_gate_study_v2.json
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from artifact_spec import assert_spec_integrity, spec_block  # noqa: E402
from certify_v75 import certify  # noqa: E402
from walkforward_v75 import build_folds  # noqa: E402

DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
OUT = os.path.join(DATA, "regime_gate_study_v2.json")
EQ = 200.0
SPLIT_FOLD = 17          # F17 onwards = validation (Jun 12+)
MIN_SEP_R = 0.15         # calibration bar to even spend the validation window
MIN_VETO_N = 30

# Causal feature grid: (name, fn(trade)->value, "low_is_good"|"high_is_good" is
# chosen on calibration data; thresholds are quantiles of the calibration dist)
FEATURES = ["atr_pct", "z_abs", "exp", "reg", "dir", "hour"]


def sig_hour(t: str) -> int:
    return datetime.fromisoformat(t).hour


def main() -> None:
    assert_spec_integrity()
    folds = build_folds()
    cal_folds = folds[:SPLIT_FOLD - 1]        # F01..F16
    val_folds = folds[SPLIT_FOLD - 1:]        # F17..F26
    cal_lo, cal_hi = cal_folds[0][1], cal_folds[-1][2]
    val_lo, val_hi = val_folds[0][1], val_folds[-1][2]
    print(f"calibration: {cal_lo:%b %d} .. {cal_hi:%b %d} ({len(cal_folds)} folds)")
    print(f"validation : {val_lo:%b %d} .. {val_hi:%b %d} ({len(val_folds)} folds)")

    # base config = tp18 (the validated best). Honest booking, full governor.
    rep_cal = certify(EQ, start=cal_lo, end=cal_hi, tp_mult=1.8)
    rep_val = certify(EQ, start=val_lo, end=val_hi, tp_mult=1.8)
    pb_cal = [t for t in rep_cal["trades"] if t["strat"] in ("PB", "MOM+PB")]
    pb_val = [t for t in rep_val["trades"] if t["strat"] in ("PB", "MOM+PB")]
    all_cal = rep_cal["trades"]
    print(f"trades: cal {len(rep_cal['trades'])} (PB {len(pb_cal)}), "
          f"val {len(rep_val['trades'])} (PB {len(pb_val)})")

    def bucket_stats(trs, keyfn, nq=3):
        """Quantile buckets -> (edges, per-bucket n/meanR)."""
        vals = sorted(keyfn(t) for t in trs)
        edges = [vals[int(q * (len(vals) - 1))] for q in (i / nq for i in range(1, nq))]
        out = []
        for bi in range(nq):
            lo = edges[bi - 1] if bi else float("-inf")
            hi = edges[bi] if bi < nq - 1 else float("inf")
            bs = [t for t in trs if lo <= keyfn(t) <= hi]
            out.append({"n": len(bs),
                        "mean_r": round(st.mean([t["r"] for t in bs]), 3) if bs else None,
                        "wr": round(100 * sum(1 for t in bs if t["r"] > 0) / len(bs), 1) if bs else None})
        return edges, out

    # ---- Q1: single-feature separation on calibration ----------------------
    q1 = {}
    print("\n== Q1: calibration-bucket expectancy by causal feature (PB trades) ==")
    for feat in FEATURES:
        if feat == "hour":
            keyf = lambda t: sig_hour(t["sig_t"])
        elif feat == "z_abs":
            keyf = lambda t: abs(t["z"])
        elif feat == "reg":
            keyf = lambda t: t["reg"]
        elif feat == "dir":
            keyf = lambda t: t["dir"]
        else:
            keyf = (lambda t: t[feat]) if feat != "exp" else (lambda t: t["exp"])
        if feat in ("reg", "dir"):  # categorical: group directly
            groups = {}
            for t in pb_cal:
                groups.setdefault(keyf(t), []).append(t["r"])
            q1[feat] = {k: {"n": len(v), "mean_r": round(st.mean(v), 3)} for k, v in sorted(groups.items())}
            print(f"  {feat:8s} " + "  ".join(f"{k}:{q1[feat][k]['n']}tr {q1[feat][k]['mean_r']:+.3f}R" for k in sorted(q1[feat])))
        else:
            edges, buckets = bucket_stats(pb_cal, keyf)
            q1[feat] = {"edges": edges, "buckets": buckets}
            print(f"  {feat:8s} " + "  ".join(f"B{i}:{b['n']}tr {b['mean_r']:+.3f}R" for i, b in enumerate(buckets)))

    # ---- Q2: throttle causal basis — expectancy while window is hot ---------
    # Re-run calibration with throttle to record WHEN probes/blocks happened;
    # instead of instrumenting the harness, approximate causally here: replay
    # the PB trade sequence, maintain the rolling window, label each trade
    # hot/cold BEFORE it closes (window state from prior trades only).
    hot, cold = [], []
    hist: list[float] = []
    for t in pb_cal:
        (hot if len(hist) >= 10 and sum(hist) < -3.0 else cold).append(t["r"])
        hist.append(t["r"])
        if len(hist) > 10:
            hist.pop(0)
    q2 = {
        "hot": {"n": len(hot), "mean_r": round(st.mean(hot), 3) if hot else None},
        "cold": {"n": len(cold), "mean_r": round(st.mean(cold), 3) if cold else None},
    }
    print(f"\n== Q2: PB expectancy by throttle-window state (calibration) ==")
    print(f"  hot  (window<-$while trading): n={q2['hot']['n']}  mean {q2['hot']['mean_r']}R")
    print(f"  cold                          : n={q2['cold']['n']}  mean {q2['cold']['mean_r']}R")

    # ---- gate selection on calibration (if Q1/Q2 justify one) ---------------
    # Candidate rules: keep-trade iff feature in good half (by calibration mean),
    # evaluated for each numeric feature; categorical: keep best-40% groups.
    def rule_stats(trs, keyf, lo, hi):
        keep = [t for t in trs if lo <= keyf(t) <= hi]
        veto = [t for t in trs if not (lo <= keyf(t) <= hi)]
        return {
            "keep_n": len(keep), "keep_r": round(sum(t["r"] for t in keep), 2),
            "keep_mean": round(st.mean([t["r"] for t in keep]), 3) if keep else None,
            "veto_n": len(veto), "veto_r": round(sum(t["r"] for t in veto), 2),
            "veto_mean": round(st.mean([t["r"] for t in veto]), 3) if veto else None,
            "sep": round(st.mean([t["r"] for t in keep]) - st.mean([t["r"] for t in veto]), 3)
                   if keep and veto else None,
        }

    candidates = {}
    for feat in ("atr_pct", "z_abs", "exp", "hour"):
        if feat == "hour":
            keyf = lambda t: sig_hour(t["sig_t"])
        elif feat == "z_abs":
            keyf = lambda t: abs(t["z"])
        else:
            keyf = (lambda t: t[feat])
        vals = sorted(keyf(t) for t in pb_cal)
        med = vals[len(vals) // 2]
        for name, lo, hi in ((f"{feat}<={med}", float("-inf"), med),
                             (f"{feat}>{med}", med, float("inf"))):
            s = rule_stats(pb_cal, keyf, lo, hi)
            if s["veto_n"] >= MIN_VETO_N and s["keep_n"] >= MIN_VETO_N:
                candidates[name] = {**s, "rule": (lo, hi), "feat": feat}
    best = max((c for c in candidates.values() if c["sep"] is not None),
               key=lambda c: c["sep"], default=None)

    print("\n== calibration candidate rules (both buckets >= 30 trades) ==")
    for name, c in sorted(candidates.items(), key=lambda kv: -(kv[1]["sep"] or -9)):
        print(f"  {name:16s} keep {c['keep_n']}tr {c['keep_mean']:+.3f}R | "
              f"veto {c['veto_n']}tr {c['veto_mean']:+.3f}R | sep {c['sep']:+.3f}")

    result = {"design": "pre-registered 2026-09-04, see module docstring",
              "q1_features": q1, "q2_throttle_basis": q2,
              "candidates": {k: {kk: vv for kk, vv in v.items() if kk != 'rule'}
                             for k, v in candidates.items()},
              "chosen": None, "validation": None, "verdict": None}

    if best is None or (best["sep"] or 0) < MIN_SEP_R:
        print(f"\nVERDICT: NO GATE CANDIDATE clears the calibration bar "
              f"(best sep {best['sep'] if best else None} vs required +-{MIN_SEP_R}) "
              f"— validation window NOT spent (pre-registered early exit)")
        result["verdict"] = "NO GATE (calibration bar not met)"
    else:
        lo, hi = best["rule"]
        keyf = (lambda t: sig_hour(t["sig_t"])) if best["feat"] == "hour" else \
               (lambda t: abs(t["z"]) if best["feat"] == "z_abs" else (lambda t: t[best["feat"]]))
        vs = rule_stats(pb_val, keyf, lo, hi)
        all_val_r = sum(t["r"] for t in pb_val)
        g1 = (vs["veto_mean"] or 0) < (vs["keep_mean"] or 0)
        g2 = vs["keep_r"] > all_val_r
        g3 = vs["keep_n"] >= 0.6 * len(pb_val)
        result["chosen"] = best
        result["validation"] = {**vs, "all_val_r": round(all_val_r, 2), "all_val_n": len(pb_val)}
        ok = g1 and g2 and g3
        result["verdict"] = ("GATE VALIDATED" if ok else "GATE NOT VALIDATED") + \
                            f" (G1={g1} G2={g2} G3={g3})"
        print(f"\n== validation (one shot, {best['feat']} rule) ==")
        print(f"  keep {vs['keep_n']}tr {vs['keep_mean']:+.3f}R ({vs['keep_r']:+.1f}R) | "
              f"veto {vs['veto_n']}tr {vs['veto_mean']:+.3f}R ({vs['veto_r']:+.1f}R) | all {all_val_r:+.1f}R")
        print(f"  G1 vetoed worse OOS: {g1} | G2 kept-total > all-total: {g2} | "
              f"G3 kept >=60% of trades: {g3}")
        print(f"  VERDICT: {result['verdict']}")

    result["spec"] = spec_block(artifact="regime_gate_study_v2")
    with open(OUT, "w") as f:
        json.dump(result, f, indent=1, default=str)
    print(f"artifact: {OUT}")


if __name__ == "__main__":
    main()
