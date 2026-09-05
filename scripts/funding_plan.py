"""Funding-growth plan: replay the certified trade sequence at several
starting balances, Monte-Carlo the loss-streak risk, and compare withdrawal
schedules.

Usage:
  python scripts/funding_plan.py                 # uses cert_report_fresh60_tp18.json
  python scripts/funding_plan.py --report FILE   # alternate cert report
  python scripts/funding_plan.py --perms 2000    # more Monte-Carlo shuffles

Outputs:
  artifacts/v75_replay/funding_plan.json
  artifacts/v75_replay/funding_plan.md

Methods:
  - Money layer is scripts/v75_money.py (exact EA entry chain: min-lot clamp,
    0.75^consec-loss scaling, 20% effective-risk cap, compounding equity).
  - Trades are shuffled as (sd, r) bundles so signal geometry stays paired
    with its own outcome.
  - "Floor-stuck" = equity below the V75 min-lot floor mid-run while trades
    remain, i.e. the account cannot take the next signal at all.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
from datetime import datetime

from v75_money import run_money_replay

FLOOR = 30.93          # V75 min-lot equity floor at the 20% cap (broker-exact)
BALANCES = (31.0, 50.0, 100.0, 200.0)


def week_key(t: str) -> str:
    return datetime.fromisoformat(t).strftime("%G-W%V")


def replay_with_withdrawals(trades: list[dict], policy: str, start: float) -> dict:
    """Drive the EA money chain trade-by-trade, withdrawing at week boundaries
    DURING the walk so every later trade is sized on post-withdrawal equity.

    compound : never withdraw
    bank100  : weekly, withdraw everything above a $100 working buffer
    bankhalf : weekly, withdraw half of the profit above the starting stake
    """
    from v75_money import MoneySim
    sim = MoneySim(start)
    eq, withdrawn, min_eq = start, 0.0, start
    n_taken = n_skip = 0
    wk = None
    ever_stuck = False
    for t in trades:
        d = sim.evaluate_entry(t["sd"])
        if d["trade"]:
            n_taken += 1
            money = d["eff_risk"] * t["r"]
            eq += money
            sim.eq = eq
            sim.consec = sim.consec + 1 if t["r"] <= 0 else 0
            min_eq = min(min_eq, eq)
        else:
            n_skip += 1
            if d.get("reason") == "min-lot-risk":
                ever_stuck = True
        # week-boundary withdrawal (checked after every trade)
        w = week_key(t["t"])
        if w != wk and wk is not None:
            cut = 0.0
            if policy == "bank100" and eq > 100.0:
                cut = eq - 100.0
            elif policy == "bankhalf" and eq > start:
                cut = (eq - start) / 2.0
            if cut > 0:
                eq -= cut; withdrawn += cut; sim.eq = eq
                min_eq = min(min_eq, eq)
        wk = w
    return {"final_eq": round(eq, 2), "withdrawn": round(withdrawn, 2),
            "min_eq": round(min_eq, 2), "taken": n_taken, "skipped": n_skip,
            "ever_stuck": ever_stuck,
            "total_wealth": round(eq + withdrawn, 2)}


def stuck_stats(detail: list[dict], start: float) -> dict:
    """How often the 20%-cap veto (min-lot risk) blocks trades, and whether
    the account ever spends the rest of the run below the floor."""
    taken_after_first_skip = False
    stuck_from = None
    n_skip = 0
    for row in detail:
        if row.get("taken"):
            if stuck_from is not None:
                taken_after_first_skip = True
        else:
            n_skip += 1
            if stuck_from is None:
                stuck_from = row["t"]
    return {"skipped": n_skip,
            "ever_stuck": stuck_from is not None,
            "recovered": taken_after_first_skip,
            "stuck_from": stuck_from}


def monte_carlo(trades: list[dict], eq0: float, perms: int) -> dict:
    rng = random.Random(20260904)
    finals, stuck, profits = [], 0, 0
    order = list(range(len(trades)))
    for _ in range(perms):
        rng.shuffle(order)
        seq = [trades[i] for i in order]
        res = run_money_replay(seq, eq0)
        finals.append(res["equity_final"])
        if res["equity_final"] > eq0:
            profits += 1
        if any((not r["taken"]) and r.get("reason") == "min-lot-risk"
               for r in res["detail"][:len(res["detail"])]):
            pass  # counted via stuck check below
        if stuck_stats(res["detail"], eq0)["ever_stuck"]:
            stuck += 1
    finals.sort()
    q = lambda p: finals[int(p * (len(finals) - 1))]
    return {"perms": perms,
            "p_profit": round(profits / perms, 3),
            "p_ever_stuck": round(stuck / perms, 3),
            "final_median": round(st.median(finals), 2),
            "final_p05": q(0.05),
            "final_p95": q(0.95),
            "final_worst": finals[0]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="artifacts/v75_replay/cert_report_fresh60_tp18.json")
    ap.add_argument("--perms", type=int, default=1000)
    args = ap.parse_args()

    trades = json.load(open(args.report))["trades"]
    out = {"source": args.report, "n_trades": len(trades), "balances": {}}

    for eq0 in BALANCES:
        res = run_money_replay(trades, eq0)
        det = res.pop("detail")
        wd = {p: replay_with_withdrawals(trades, p, eq0)
              for p in ("compound", "bank100", "bankhalf")}
        mc = monte_carlo(trades, eq0, args.perms)
        out["balances"][str(eq0)] = {
            "deterministic": res,
            "stuck": stuck_stats(det, eq0),
            "withdrawal": wd,
            "monte_carlo": mc,
        }

    os.makedirs("artifacts/v75_replay", exist_ok=True)
    json.dump(out, open("artifacts/v75_replay/funding_plan.json", "w"), indent=1)

    # ---- markdown ----
    L = ["# Funding-growth plan — V75 TP 1.8 certified sequence (60 days, 135 trades)", ""]
    L.append(f"Money layer = EA entry chain (min-lot clamp, 0.75^loss scaling, 20% cap); floor ${FLOOR:.2f}.")
    L.append(f"Monte Carlo: {args.perms} shuffles of the trade sequence.\n")
    L.append("| Start | Final (compound) | Max risk/trade | MC P(stuck) | MC median final | MC 5% worst |")
    L.append("|---|---|---|---|---|---|")
    for eq0 in BALANCES:
        b = out["balances"][str(eq0)]
        d, mc = b["deterministic"], b["monte_carlo"]
        L.append(f"| ${eq0:.0f} | ${d['equity_final']:.2f} | {d['max_risk_pct']:.1f}% | "
                 f"{mc['p_ever_stuck']*100:.0f}% | ${mc['final_median']:.2f} | ${mc['final_p05']:.2f} |")
    L.append("\n## Withdrawal schedules (60-day window, sized on post-withdrawal equity)")
    L.append("\n| Start | Policy | Final equity | Withdrawn | Total wealth | Lowest equity | Stuck? |")
    L.append("|---|---|---|---|---|---|---|")
    for eq0 in BALANCES:
        for p, v in out["balances"][str(eq0)]["withdrawal"].items():
            L.append(f"| ${eq0:.0f} | {p} | ${v['final_eq']:.2f} | ${v['withdrawn']:.2f} | "
                     f"${v['total_wealth']:.2f} | ${v['min_eq']:.2f} | {'yes' if v['ever_stuck'] else 'no'} |")
    md = "\n".join(L) + "\n"
    open("artifacts/v75_replay/funding_plan.md", "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
