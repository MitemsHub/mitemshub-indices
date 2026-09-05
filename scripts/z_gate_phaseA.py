"""Z-Gate Phase A — executes docs/Z_GATE_PROTOCOL.md mechanically.

PRE-REGISTRATION: the protocol (windows, gate forms, calibration pre-bar
C1-C3, validation criteria W1-W5, verdicts) was frozen in
docs/Z_GATE_PROTOCOL.md BEFORE any Phase-A data was examined. This script
adds no discretion: it fits the committed forms on the calibration half,
applies the pre-bar, spends the validation window at most once, and reports
the verdict whatever it is.

Data: artifacts/z_gate/ (pulled 2024-07-20 .. 2026-01-31 — zero overlap with
the burned Feb-Sep 2026 window).
Writes: artifacts/z_gate/phaseA_result.json (+ z_gate_edges.json when a form
validates — the frozen Phase-B input).
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from datetime import datetime, timezone as _UTC

os.environ.setdefault("CERT_DATA_DIR", os.path.join("artifacts", "z_gate"))
# z_gate data IS V75 (pulled via pull_v75_week) — declared explicitly so the
# spec-integrity guard (2026-09-05) passes: any custom data dir must state specs.
os.environ.setdefault("CERT_SPREAD", "18.5")
os.environ.setdefault("CERT_USD_PER_UNIT_PER_LOT", "1.009")
os.environ.setdefault("CERT_MIN_LOT", "0.01")
os.environ.setdefault("CERT_LOT_STEP", "0.01")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from certify_v75 import certify  # noqa: E402

OUT_DIR = os.path.join(HERE, "..", "artifacts", "z_gate")
EQ = 200.0
CAL_LO, CAL_HI = datetime(2024, 8, 1), datetime(2025, 7, 31)
VAL_LO, VAL_HI = datetime(2025, 8, 1), datetime(2026, 1, 31)
SEG_SPLIT = datetime(2025, 11, 1, tzinfo=_UTC.utc)   # two 3-month validation segments
C_GAP, C_MIN_BUCKET = 0.15, 120            # §3 calibration pre-bar
W_GAP, W_ECON, W_KEPT_FRAC, W_SEG_FLOOR = 0.15, 1.5, 0.30, -0.5  # §4


def pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def pb_trades(rep):
    return [t for t in rep["trades"] if t["strat"] in ("PB", "MOM+PB")]


def split_stats(trades, keep_fn):
    keep = [t for t in trades if keep_fn(t)]
    veto = [t for t in trades if not keep_fn(t)]
    return {
        "n_keep": len(keep), "n_veto": len(veto),
        "keep_mean": round(st.mean([t["r"] for t in keep]), 3) if keep else None,
        "veto_mean": round(st.mean([t["r"] for t in veto]), 3) if veto else None,
        "keep_total": round(sum(t["r"] for t in keep), 2),
        "all_total": round(sum(t["r"] for t in trades), 2),
        "gap": (round(st.mean([t["r"] for t in keep]) - st.mean([t["r"] for t in veto]), 3)
                if keep and veto else None),
    }


def main():
    result = {"protocol": "docs/Z_GATE_PROTOCOL.md (frozen 2026-09-04)",
              "calibration": {}, "validation": None, "verdict": None}

    print("== calibration run 2024-08-01 .. 2025-07-31 (tp18) ==")
    rep_cal = certify(EQ, start=CAL_LO, end=CAL_HI, tp_mult=1.8)
    cal = pb_trades(rep_cal)
    zs = [abs(t["z"]) for t in cal]
    print(f"calibration PB trades: {len(cal)}")
    z_lo, z_hi = pct(zs, 1 / 3), pct(zs, 2 / 3)
    med = pct(zs, 0.5)
    print(f"|z| tertiles: ({z_lo:.3f}, {z_hi:.3f}]  median {med:.3f}")

    forms = {
        "PRIMARY tertile-keep": (lambda t, lo=z_lo, hi=z_hi: lo < abs(t["z"]) <= hi,
                                 {"z_lo": z_lo, "z_hi": z_hi}),
        "FALLBACK median-keep": (lambda t, m=med: abs(t["z"]) <= m,
                                 {"z_lo": None, "z_hi": med}),
    }
    chosen = None
    for name, (fn, edges) in forms.items():
        s = split_stats(cal, fn)
        c1 = (s["gap"] or -9) >= C_GAP
        c2 = s["n_keep"] >= C_MIN_BUCKET
        c3 = s["n_veto"] >= C_MIN_BUCKET
        result["calibration"][name] = {**s, "edges": edges,
                                       "C1_gap>=0.15": c1, "C2_keep>=120": c2, "C3_veto>=120": c3}
        print(f"  {name}: keep {s['n_keep']}tr {s['keep_mean']:+.3f}R | veto {s['n_veto']}tr "
              f"{s['veto_mean']:+.3f}R | gap {s['gap']:+.3f}  "
              f"[C1 {c1} C2 {c2} C3 {c3}]")
        if c1 and c2 and c3 and chosen is None:
            chosen = (name, fn, edges)
        if name == "PRIMARY tertile-keep" and chosen is not None:
            break                     # FALLBACK evaluated only if PRIMARY fails

    if chosen is None:
        result["verdict"] = "NO GATE — both forms failed the calibration pre-bar; " \
                            "validation window NOT spent (protocol §3)"
        print("\nVERDICT: " + result["verdict"])
        _write(result)
        return

    name, fn, edges = chosen
    print(f"\n== validation run 2025-08-01 .. 2026-01-31 ({name}) — ONE SHOT ==")
    rep_val = certify(EQ, start=VAL_LO, end=VAL_HI, tp_mult=1.8)
    val = pb_trades(rep_val)
    s = split_stats(val, fn)
    seg1 = split_stats([t for t in val if datetime.fromisoformat(t["t"]) < SEG_SPLIT], fn)
    seg2 = split_stats([t for t in val if datetime.fromisoformat(t["t"]) >= SEG_SPLIT], fn)
    kept_frac = s["n_keep"] / len(val) if val else 0
    contrib = [seg1["keep_total"] - seg1["all_total"], seg2["keep_total"] - seg2["all_total"]]

    w1 = (s["gap"] or -9) >= W_GAP
    w2 = s["keep_total"] >= s["all_total"] + W_ECON
    w3 = kept_frac >= W_KEPT_FRAC
    w4 = all(c >= 0 for c in contrib)
    w5 = min(contrib) >= W_SEG_FLOOR
    ok = w1 and w2 and w3 and w4 and w5
    result["validation"] = {**s, "kept_frac": round(kept_frac, 3),
                            "segments": [{"window": "2025-08..10", **seg1},
                                         {"window": "2025-11..2026-01", **seg2}],
                            "segment_contrib": [round(c, 2) for c in contrib],
                            "W1_gap>=0.15": w1, "W2_econ>=+1.5R": w2,
                            "W3_kept>=30%": w3, "W4_both_seg>=0": w4,
                            "W5_worst>=-0.5R": w5}
    print(f"  keep {s['n_keep']}tr {s['keep_mean']:+.3f}R ({s['keep_total']:+.2f}R) | "
          f"veto {s['n_veto']}tr {s['veto_mean']:+.3f}R | all {s['all_total']:+.2f}R | "
          f"kept {kept_frac:.0%}")
    print(f"  segments contrib: {contrib[0]:+.2f}R / {contrib[1]:+.2f}R")
    print(f"  W1 {w1} | W2 {w2} | W3 {w3} | W4 {w4} | W5 {w5}")
    result["verdict"] = (f"HISTORICAL-CANDIDATE ({name}) — edges frozen, proceed to "
                         "Phase B paper replication per protocol §5" if ok else
                         f"NOT VALIDATED ({name}) — final for this protocol generation")
    print("\nVERDICT: " + result["verdict"])
    if ok:
        with open(os.path.join(OUT_DIR, "z_gate_edges.json"), "w") as f:
            json.dump({"form": name, "edges": edges,
                       "frozen": "2026-09-04, Phase A calibration — see docs/Z_GATE_PROTOCOL.md"}, f, indent=1)
        print("frozen edges: artifacts/z_gate/z_gate_edges.json")
    _write(result)


def _write(result):
    with open(os.path.join(OUT_DIR, "phaseA_result.json"), "w") as f:
        json.dump(result, f, indent=1)
    print("artifact: artifacts/z_gate/phaseA_result.json")


if __name__ == "__main__":
    main()
