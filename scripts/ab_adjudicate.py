"""A/B adjudication for the two V75 paper arms (TP 1.8 FINAL vs TP 2.4 TP24).

Pre-registered decision rule (fixed 2026-09-04, before any paper data exists):
  DATA GATE : each arm needs >= 30 closed paper trades. Below that: KEEP
              COLLECTING, with a projected ETA from the observed trade rate.
  PAIRING   : arms share the signal engine and the broker clock (TimeCurrent),
              so trades are paired by OPEN epoch within 90 seconds.
              NOTE: ledger epochs are SECONDS (TimeCurrent), not ms — verified
              against the EA writer 2026-09-04 (earlier ms assumption fixed).
  DECISION  : the TP winner is declared only if ALL hold:
                P1. paired mean R delta (A - B) has |t| >= 1.0
                P2. sign(paired delta) == sign(total R difference)
                P3. neither arm shows a ledger-integrity failure
              Otherwise: KEEP COLLECTING / INCONCLUSIVE.
  SCOPE     : this adjudicates TP only. The veto/depth stack question was
              already settled by the 210-day walk-forward (~33R drag, OFF in
              both arms) — do not resurrect it on paper subsamples.

Usage:
  python scripts/ab_adjudicate.py --a-dir "<terminalA>/MQL5/Files" \
                                  --b-dir "<terminalB>/MQL5/Files"
  (arm A = VOL75_FINAL / TP 1.8 / magic 7788075, arm B = VOL75_TP24 / TP 2.4 /
   magic 7788100; each must run in its own terminal instance — the ledger
   files are symbol-tagged, not instance-tagged.)

Writes: artifacts/v75_replay/ab_adjudication.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone

from artifact_spec import assert_spec_integrity, spec_block

LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
OUT = os.path.join("artifacts", "v75_replay", "ab_adjudication.json")
PAIR_TOL_S = 90           # pairing tolerance in SECONDS (ledger epochs are seconds)
MIN_TRADES = 30
T_DECLARE = 1.0
ARM_A_MAGIC = 7788075
ARM_B_MAGIC = 7788100


def parse_ledger(path):
    """Returns (trades, veq_curve, integrity) — trades: dicts with epoch/r/pnl/reason/magic."""
    trades, curve, problems = [], [], []
    open_rows = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split(",")
            if not parts or parts[0] == "OPEN":
                if parts and parts[0] == "OPEN":
                    open_rows[parts[2]] = {"epoch": int(parts[1]), "tag": parts[11] if len(parts) > 11 else "?"}
            elif parts[0] == "CLOSE":
                # CLOSE,epoch,ticket,reason,exit,r,pnl,veq
                tk = parts[2]
                o = open_rows.pop(tk, None)
                trades.append({
                    "epoch": int(parts[1]), "ticket": tk, "reason": parts[3],
                    "r": float(parts[5]), "pnl": float(parts[6]), "veq": float(parts[7]),
                    "open_epoch": o["epoch"] if o else None, "tag": o["tag"] if o else "?",
                })
            elif parts[0] == "EQ":
                curve.append(float(parts[1]))
    # integrity: OPEN rows never closed (other than a dangling live trade) and
    # monotone veq bookkeeping
    if len(open_rows) > 1:
        problems.append(f"{len(open_rows)} OPEN rows without CLOSE (live trade + {len(open_rows)-1} dangling)")
    for a, b in zip(curve, curve[1:]):
        if abs(b - a) > 1e9:
            problems.append("veq discontinuity")
            break
    return trades, curve, problems


def arm_stats(trades, curve):
    if not trades:
        return {}
    rs = [t["r"] for t in trades]
    days = (trades[-1]["epoch"] - trades[0]["epoch"]) / 86400
    peak = trough = curve[0] if curve else 0.0
    dd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return {
        "n": len(trades),
        "total_r": round(sum(rs), 2),
        "mean_r": round(sum(rs) / len(rs), 3),
        "wr": round(100 * sum(1 for x in rs if x > 0) / len(rs), 1),
        "pnl": round(sum(t["pnl"] for t in trades), 2),
        "veq_max_dd": round(dd, 2),
        "days": round(days, 2),
        "trades_per_day": round(len(trades) / days, 2) if days > 0 else None,
        "reasons": {k: sum(1 for t in trades if t["reason"] == k)
                    for k in sorted({t["reason"] for t in trades})},
    }


def pair(trades_a, trades_b):
    """Greedy nearest-epoch pairing within tolerance.

    Pairs on the OPEN epoch (the pre-registered rule: arms share the signal
    engine, so signals align; CLOSE epochs diverge because the arms hold for
    different durations under different TP geometry). Falls back to the close
    epoch only when a CLOSE row had no matching OPEN row."""
    def oe(t):
        return t["open_epoch"] if t.get("open_epoch") is not None else t["epoch"]
    b = sorted(trades_b, key=oe)
    used = set()
    pairs = []
    for ta in trades_a:
        ta_e = oe(ta)
        best, best_d = None, None
        for j, tb in enumerate(b):
            if j in used:
                continue
            d = abs(oe(tb) - ta_e)
            if d <= PAIR_TOL_S and (best_d is None or d < best_d):
                best, best_d = j, d
        if best is not None:
            used.add(best)
            pairs.append((ta, b[best]))
    return pairs


def tstat(deltas):
    m = len(deltas)
    if m < 2:
        return 0.0
    mean = sum(deltas) / m
    var = sum((x - mean) ** 2 for x in deltas) / (m - 1)
    return mean / math.sqrt(var / m) if var > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir", required=True, help="arm A (TP 1.8 FINAL) terminal Files dir")
    ap.add_argument("--b-dir", required=True, help="arm B (TP 2.4 TP24) terminal Files dir")
    args = ap.parse_args()

    assert_spec_integrity()
    out = {"rule": "see module docstring; pre-registered 2026-09-04",
           "spec": spec_block(artifact="ab_adjudication", tp_mult="A=1.8 / B=2.4"),
           "arms": {}, "pairs": None, "verdict": None}
    data = {}
    for name, d in (("A_tp18", args.a_dir), ("B_tp24", args.b_dir)):
        path = os.path.join(d, LEDGER)
        if not os.path.exists(path):
            print(f"arm {name}: NO LEDGER at {path} — the EA has not paper-traded yet")
            data[name] = None
            continue
        trades, curve, problems = parse_ledger(path)
        st = arm_stats(trades, curve)
        st["integrity"] = problems or "ok"
        st["path"] = path
        data[name] = (trades, curve, problems)
        out["arms"][name] = st
        print(f"arm {name}: n={st['n']} totalR={st['total_r']:+.2f} meanR={st['mean_r']:+.3f} "
              f"WR={st['wr']}% pnl=${st['pnl']:+.2f} dd=${st['veq_max_dd']:.2f} "
              f"{st['days']}d ({st['trades_per_day']}/day) integrity={st['integrity']}")

    if not data.get("A_tp18") or not data.get("B_tp24"):
        print("\nVERDICT: KEEP COLLECTING (an arm has no data)")
        out["verdict"] = "KEEP COLLECTING (an arm has no data)"
        with open(OUT, "w") as f:
            json.dump(out, f, indent=1)
        print(f"artifact: {OUT}")
        return

    ta, ca, pa = data["A_tp18"]
    tb, cb, pb = data["B_tp24"]
    pairs = pair(ta, tb)
    deltas = [x["r"] - y["r"] for x, y in pairs]
    t = tstat(deltas)
    dR = sum(x["r"] for x in ta) - sum(y["r"] for y in tb)
    mean_d = round(sum(deltas) / len(deltas), 3) if deltas else None
    out["pairs"] = {"n_pairs": len(pairs), "mean_delta_r": mean_d,
                    "t": round(t, 2), "total_r_diff": round(dR, 2)}
    if deltas:
        print(f"\npaired: {len(pairs)} pairs, mean dR={mean_d:+.3f} t={t:+.2f} "
              f"| totalR diff (A-B)={dR:+.2f}")
    else:
        print(f"\npaired: 0 pairs within {PAIR_TOL_S}s of OPEN epoch — the arms' "
              f"signals did not align; check clocks/signal sharing")

    gate = []
    for name, tr in (("A_tp18", ta), ("B_tp24", tb)):
        if len(tr) < MIN_TRADES:
            rate = arm_stats(tr, ca)["trades_per_day"] or 0
            eta = math.ceil((MIN_TRADES - len(tr)) / rate) if rate > 0 else None
            gate.append(f"{name} has {len(tr)}/{MIN_TRADES} trades"
                        + (f" — ETA ~{eta}d at current rate" if eta else ""))
    if gate:
        print("\nVERDICT: KEEP COLLECTING — " + "; ".join(gate))
        out["verdict"] = "KEEP COLLECTING"
    else:
        p1 = abs(t) >= T_DECLARE
        p2 = (dR > 0) == (sum(deltas) > 0) if deltas else False
        p3 = not pa and not pb
        out["checks"] = {"P1 |t|>=1.0": p1, "P2 sign agreement": p2, "P3 integrity": p3}
        if p1 and p2 and p3:
            win = "A_tp18 (TP 1.8)" if dR > 0 else "B_tp24 (TP 2.4)"
            print(f"\nVERDICT: {win} earns the TP setting (paired t={t:+.2f}, dR={dR:+.2f})")
            out["verdict"] = f"WINNER: {win}"
        else:
            print(f"\nVERDICT: INCONCLUSIVE (P1={p1} P2={p2} P3={p3}) — keep both arms running")
            out["verdict"] = "INCONCLUSIVE"

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(f"artifact: {OUT}")


if __name__ == "__main__":
    main()
