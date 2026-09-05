"""Regime-gate study, round 3 — replication on the enlarged sample (pre-registered).

QUESTION. v2 (regime_gate_study_v2.json, calibration Feb-Jun / validation
Jun-Sep 2026) found two near-miss separators on 283 calibration PB trades:
    mid-|z| bucket (between calibration tertiles)   +0.203R vs tails −0.032R
    hour middle bucket (B1)                          +0.270R vs B0 +0.014R
The chosen |z|<=1.08 gate failed validation on economics (deleted 56% of
trades for +0.3R). This round asks ONLY the replication question, once the
paper ledgers add several weeks of live trades: do the same buckets separate
out-of-sample on LIVE paper fills?

PRE-REGISTERED REPLICATION RULES (fixed 2026-09-04, before paper data exists):
  Edges are FROZEN from the v2 calibration artifact (q1_features edges) —
  never re-fit on new data. If that artifact is missing, the study aborts
  rather than silently re-fitting.
  Sample gate: >= --min-n closed arm-A paper trades spanning >= --min-days.
  Features attach to paper trades by pairing each ledger OPEN to the harness
  trade (same tp18 config on refreshed bars) with nearest sig_t within 120s;
  unmatched paper trades are counted (signal-engine drift indicator) but
  excluded from bucket statistics.
  Replication criteria — ALL must hold for a VALIDATED candidate:
    R1  mid-|z| bucket mean R exceeds the complement by >= +0.10R on paper.
    R2  hour-B1 bucket mean R exceeds the complement by >= +0.10R on paper.
    R3  economics: keeping trades that pass (mid-z AND hour-B1) beats the
        all-trade paper mean by >= +0.15R per kept trade, with kept >= 40%
        of trades (looser than v2's G3: two-condition AND).
    R4  direction agreement: the same gaps must hold with the same sign at
        >= +0.05R on the harness companion sample over the paper window —
        a paper-only effect with contrary harness evidence is a red flag.
  VERDICT: VALIDATED-CANDIDATE (proceeds to EA-input design + its own
  walk-forward + paper A/B — never auto-deployed) or NO GATE (final at
  this sample size).
  INTERIM MODE (paper data below the sample gate): reports whether the v2
  separations survive on the full 210-day harness sample alone — an
  in-sample-extension sanity check, clearly labeled as such (weaker than
  true OOS).

Usage: python scripts/regime_gate_study_v3.py [--min-n 150] [--min-days 21]
Writes: artifacts/v75_replay/regime_gate_study_v3.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics as st
import sys
from bisect import bisect_left
from datetime import datetime, timezone

from artifact_spec import assert_spec_integrity, spec_block

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from certify_v75 import certify  # noqa: E402

DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")
OUT = os.path.join(DATA, "regime_gate_study_v3.json")
V2 = os.path.join(DATA, "regime_gate_study_v2.json")
EQ = 200.0
PAIR_TOL_S = 120
LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
ARM_A_MAGIC = "InpMagic=7788075"


def frozen_edges() -> dict:
    try:
        v2 = json.load(open(V2))
        e = v2["q1_features"]
        return {"z_abs": e["z_abs"]["edges"], "hour": e["hour"]["edges"]}
    except (OSError, KeyError) as ex:
        print(f"ABORT: v2 artifact edges unavailable ({ex}) — refusing to re-fit "
              "thresholds (pre-registered rule)")
        sys.exit(3)


def find_arm_a_ledger() -> str | None:
    """Prefer the terminal whose V75 chart carries arm-A magic 7788075."""
    best, fallback = None, None
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        path = os.path.join(td, "MQL5", "Files", LEDGER)
        if not os.path.exists(path):
            continue
        fallback = fallback or path
        for chr_f in glob.glob(os.path.join(td, "MQL5", "Profiles", "Charts", "*", "*.chr")):
            try:
                txt = open(chr_f, encoding="utf-16", errors="replace").read()
            except OSError:
                continue
            if "Volatility 75" in txt and ARM_A_MAGIC in txt:
                best = best or path
    return best or fallback


def load_paper_trades(path) -> list:
    """CLOSED trades only; strat from the OPEN row's tag; PB family only."""
    opens, out = {}, []
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if not p:
                continue
            if p[0] == "OPEN":
                opens[p[2]] = dict(epoch=int(p[1]), dir=int(p[3]),
                                   tag=p[11] if len(p) > 11 else "?")
            elif p[0] == "CLOSE":
                o = opens.pop(p[2], None)
                if o and o["tag"] in ("PB", "MOM+PB"):
                    out.append(dict(open_epoch=o["epoch"], r=float(p[5]),
                                    strat=o["tag"]))
    return out


def harness_trades_for(lo_dt, hi_dt) -> list:
    rep = certify(EQ, start=lo_dt, end=hi_dt, tp_mult=1.8)
    return [t for t in rep["trades"] if t["strat"] in ("PB", "MOM+PB")]


def attach_features(paper: list, harness: list):
    """Pair paper OPENs to harness sig_t (<=PAIR_TOL_S). Returns (matched, unmatched)."""
    h = sorted(harness, key=lambda t: datetime.fromisoformat(t["sig_t"]).timestamp())
    hts = [datetime.fromisoformat(t["sig_t"]).timestamp() for t in h]
    matched, unmatched = [], 0
    for p in paper:
        i = bisect_left(hts, p["open_epoch"])
        cand = None
        for j in (i - 1, i):
            if 0 <= j < len(h) and abs(hts[j] - p["open_epoch"]) <= PAIR_TOL_S:
                cand = h[j]
                break
        if cand is None:
            unmatched += 1
            continue
        matched.append({**p, "z": abs(cand["z"]),
                        "hour": datetime.fromisoformat(cand["sig_t"]).hour,
                        "reg": cand["reg"]})
    return matched, unmatched


def gap(trades, key, lo, hi) -> dict:
    """Mean R inside [lo,hi) vs the complement."""
    mid = [t["r"] for t in trades if lo <= key(t) < hi]
    rest = [t["r"] for t in trades if not (lo <= key(t) < hi)]
    return {"n_mid": len(mid), "mean_mid": round(st.mean(mid), 3) if mid else None,
            "n_rest": len(rest), "mean_rest": round(st.mean(rest), 3) if rest else None,
            "gap": round(st.mean(mid) - st.mean(rest), 3) if mid and rest else None}


def main():
    assert_spec_integrity()
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=150)
    ap.add_argument("--min-days", type=int, default=21)
    args = ap.parse_args()
    edges = frozen_edges()
    z0, z1 = edges["z_abs"]
    h0, h1_ = edges["hour"]
    print(f"frozen edges from v2 calibration: |z| mid=({z0:.3f},{z1:.3f}], hour B1=({h0},{h1_}]")

    zkey = lambda t: t["z"]
    hkey = lambda t: t["hour"] if "hour" in t else int(t["sig_t"][11:13])
    result = {"protocol": "pre-registered 2026-09-04, see module docstring",
              "edges": edges, "interim": None, "paper": None, "verdict": None}

    # ---- interim: does the full 210-day harness sample sustain v2? --------
    rep_full = certify(EQ, tp_mult=1.8)
    pb_full = [t for t in rep_full["trades"] if t["strat"] in ("PB", "MOM+PB")]
    gz = gap(pb_full, zkey, z0, z1)
    gh = gap(pb_full, hkey, h0, h1_)
    result["interim"] = {"n": len(pb_full), "z": gz, "hour": gh}
    print(f"\nINTERIM (harness 210d, in-sample extension, n={len(pb_full)} PB):")
    print(f"  mid-|z|: {gz['n_mid']}tr {gz['mean_mid']:+.3f}R vs rest {gz['n_rest']}tr "
          f"{gz['mean_rest']:+.3f}R -> gap {gz['gap']:+.3f}")
    print(f"  hour-B1: {gh['n_mid']}tr {gh['mean_mid']:+.3f}R vs rest {gh['n_rest']}tr "
          f"{gh['mean_rest']:+.3f}R -> gap {gh['gap']:+.3f}")

    # diagnostic CONTEXT, not a criterion: the v2 validation folds (F17-F26,
    # Jun 19..Sep 4) are the only clean-OOS slice that exists so far — the
    # edges were frozen on F01-F16 and never saw these trades.
    from walkforward_v75 import build_folds  # noqa: E402
    val_folds = build_folds()[16:]
    rep_oos = certify(EQ, start=val_folds[0][1], end=val_folds[-1][2], tp_mult=1.8)
    pb_oos = [t for t in rep_oos["trades"] if t["strat"] in ("PB", "MOM+PB")]
    oz, oh = gap(pb_oos, zkey, z0, z1), gap(pb_oos, hkey, h0, h1_)
    result["interim"]["oos_window_context"] = {
        "label": "v2 validation folds only (clean OOS for the frozen edges)",
        "n": len(pb_oos), "z": oz, "hour": oh}
    print(f"  [context: v2 validation folds only, clean OOS, n={len(pb_oos)}: "
          f"z gap {oz['gap']:+.3f}, hour gap {oh['gap']:+.3f}]")

    # ---- paper branch ------------------------------------------------------
    path = find_arm_a_ledger()
    if not path:
        print("\nNO PAPER LEDGER — the EA has not paper-traded yet. "
              "Verdict: KEEP COLLECTING (re-run after the reload produces weeks of trades)")
        result["verdict"] = "KEEP COLLECTING (no paper data)"
        _write(result)
        return
    paper = load_paper_trades(path)
    if not paper:
        print(f"\nledger exists but no closed PB trades yet -> KEEP COLLECTING")
        result["verdict"] = "KEEP COLLECTING (no closed paper trades)"
        _write(result)
        return
    days = (paper[-1]["open_epoch"] - paper[0]["open_epoch"]) / 86400
    print(f"\npaper: {len(paper)} closed PB trades over {days:.1f}d ({os.path.basename(os.path.dirname(os.path.dirname(path)))})")
    if len(paper) < args.min_n or days < args.min_days:
        print(f"SAMPLE GATE not met (need >= {args.min_n} trades / >= {args.min_days}d) "
              "-> KEEP COLLECTING; interim harness check above is informational only")
        result["verdict"] = f"KEEP COLLECTING ({len(paper)}/{args.min_n} trades, {days:.1f}/{args.min_days}d)"
        result["paper"] = {"n": len(paper), "days": round(days, 2)}
        _write(result)
        return

    lo_dt = datetime.fromtimestamp(paper[0]["open_epoch"], tz=timezone.utc)
    hi_dt = datetime.fromtimestamp(paper[-1]["open_epoch"] + 3600, tz=timezone.utc)
    harness = harness_trades_for(lo_dt, hi_dt)
    matched, unmatched = attach_features(paper, harness)
    print(f"feature attach: {len(matched)} matched, {unmatched} unmatched "
          f"(harness companion n={len(harness)})")
    result["paper"] = {"n": len(paper), "days": round(days, 2),
                       "matched": len(matched), "unmatched": unmatched}

    pz = gap(matched, zkey, z0, z1)
    ph = gap(matched, hkey, h0, h1_)
    keep = [t for t in matched if z0 <= t["z"] < z1 and h0 <= t["hour"] < h1_]
    kept_frac = len(keep) / len(matched) if matched else 0
    r3 = {"n_kept": len(keep), "kept_frac": round(kept_frac, 2),
          "mean_kept": round(st.mean([t["r"] for t in keep]), 3) if keep else None,
          "mean_all": round(st.mean([t["r"] for t in matched]), 3) if matched else None}
    r3["delta"] = round(r3["mean_kept"] - r3["mean_all"], 3) if keep else None
    hz = gap(harness, zkey, z0, z1)
    hh = gap(harness, hkey, h0, h1_)

    R1 = (pz["gap"] or -9) >= 0.10
    R2 = (ph["gap"] or -9) >= 0.10
    R3 = (r3["delta"] or -9) >= 0.15 and kept_frac >= 0.40
    R4 = ((hz["gap"] or -9) >= 0.05 and (hh["gap"] or -9) >= 0.05)
    result["paper"].update({"z": pz, "hour": ph, "economics": r3,
                            "harness_companion": {"z": hz, "hour": hh}})
    print("\n== replication criteria ==")
    print(f"  R1 mid-z gap on paper     : {pz['gap']:+.3f} (need >= +0.10) -> {R1}")
    print(f"  R2 hour-B1 gap on paper   : {ph['gap']:+.3f} (need >= +0.10) -> {R2}")
    print(f"  R3 economics (AND-keep)   : {r3['delta']:+.3f}R/trade over {r3['kept_frac']:.0%} "
          f"of trades (need >= +0.15 and >= 40%) -> {R3}")
    print(f"  R4 harness companion agree: z {hz['gap']:+.3f}, hour {hh['gap']:+.3f} "
          f"(need both >= +0.05) -> {R4}")
    result["verdict"] = ("VALIDATED-CANDIDATE — proceed to EA-input design, "
                         "dedicated walk-forward, then paper A/B"
                         if (R1 and R2 and R3 and R4) else
                         "NO GATE — separations do not replicate at this sample size")
    print(f"\nVERDICT: {result['verdict']}")
    _write(result)


def _write(result):
    result["spec"] = spec_block(artifact="regime_gate_study_v3")
    with open(OUT, "w") as f:
        json.dump(result, f, indent=1)
    print(f"artifact: {OUT}")


if __name__ == "__main__":
    main()
