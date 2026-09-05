"""First-trade drill: prove the paper-data path BEFORE the first real fill.

    python scripts/first_trade_drill.py

Generates synthetic ledgers in the EXACT EA v26.35 wire format (PaperLog:
OPEN,epoch,ticket,dir,entry,sl,tp,vol,eff_risk,orig_risk,max_hold,tag /
CLOSE,epoch,ticket,reason,exit,r,pnl,veq / EQ,veq; epochs in SECONDS) in
temp dirs, then runs the real downstream tools against them:

  S1  both arms empty            -> ab_adjudicate: KEEP COLLECTING (no data)
  S2  12 closed trades per arm   -> KEEP COLLECTING with ETA at observed rate
  S3  A wins, 40 paired trades   -> WINNER: A_tp18 (P1/P2/P3 all hold)
  S4  noisy deltas, no signal    -> INCONCLUSIVE (adjudicator refuses noise)
  S5  1.5d ledger vs 7d gate     -> reconciler KEEP COLLECTING, no broker pull
  S6  morning_status internals   -> parse_ledger integrity + cross-midnight
                                    journal gap pairing

Every scenario asserts its expected verdict line; any mismatch exits 1.
The drill is read-only for the real terminals and never touches broker data.
It DOES write the fixed-path artifacts (ab_adjudication.json,
paper_tick_reconciliation.json) while running, so the final step re-runs both
tools against the REAL terminal dirs to restore truthful artifacts.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))


def gen_ledger(path: str, seed: int, n_closed: int, start: datetime,
               mean_r: float, tp_mult: float, spacing_h: float,
               pair_epochs: list[int] | None = None) -> list[int]:
    """Write a synthetic wire-format ledger; return the OPEN epochs (seconds)."""
    rng = random.Random(seed)
    eq = 50.0
    epochs: list[int] = []
    base_entry = 49500.0
    with open(path, "w", newline="\n") as f:
        for i in range(n_closed):
            if pair_epochs is None:
                oe = int((start + timedelta(hours=i * spacing_h + rng.uniform(0, 0.4))).timestamp())
            else:
                oe = pair_epochs[i] + rng.randint(0, 30)
            epochs.append(oe)
            hold_s = rng.randint(900, 8 * 3600)
            ce = oe + hold_s
            ticket = 700_000_000 + seed * 1000 + i
            sd = 300.0 * rng.uniform(0.9, 1.4)
            direction = rng.choice([1, -1])
            entry = base_entry + rng.uniform(-400, 400)
            roll = rng.random()
            if roll < 0.46:                       # TARGET
                reason, r = "TARGET", round(tp_mult - rng.uniform(0.0, 0.15), 3)
            elif roll < 0.68:                     # STOP
                reason, r = "STOP", -1.0
            elif roll < 0.86:                     # BE/PLOCK rescues
                reason, r = "PLOCK", round(rng.uniform(-0.1, 0.6), 3)
            else:                                 # TIME exit
                reason, r = "TIME", round(rng.uniform(-0.4, 0.4), 3)
            # shift the arm's mean toward the requested expectancy
            r = round(r + mean_r, 3)
            eff_risk = 6.25
            pnl = round(eff_risk * r, 2)
            eq = round(eq + pnl, 2)
            vol, orig_risk, max_hold, tag = 0.01, round(sd, 2), 96, "PB"
            sl = entry - direction * sd
            tp = entry + direction * sd * tp_mult
            exit_p = entry + direction * sd * r
            f.write(f"OPEN,{oe},{ticket},{direction},{entry:.5f},{sl:.5f},{tp:.5f},"
                    f"{vol:.2f},{eff_risk:.2f},{orig_risk:.2f},{max_hold},{tag}\n")
            f.write(f"CLOSE,{ce},{ticket},{reason},{exit_p:.5f},{r:.3f},{pnl:.2f},{eq:.2f}\n")
            f.write(f"EQ,{eq:.2f}\n")
        # one live (never closed) OPEN row, like the real EA holds at most one
        oe = int((start + timedelta(hours=n_closed * spacing_h + 1)).timestamp())
        ticket = 700_000_000 + seed * 1000 + 999
        f.write(f"OPEN,{oe},{ticket},1,{base_entry:.5f},{base_entry - 510:.5f},"
                f"{base_entry + 918:.5f},0.01,6.25,510.00,96,BO\n")
    return epochs


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=300)
    return p.stdout + p.stderr


def verdict_of(out: str) -> str:
    for line in out.splitlines():
        if "VERDICT:" in line:
            return line.split("VERDICT:", 1)[1].strip()
    return "(no verdict)"


def scenario_dirs(base: str, name: str) -> tuple[str, str]:
    a = os.path.join(base, name, "A", "MQL5", "Files")
    b = os.path.join(base, name, "B", "MQL5", "Files")
    os.makedirs(a, exist_ok=True)
    os.makedirs(b, exist_ok=True)
    return a, b


def main() -> None:
    base = tempfile.mkdtemp(prefix="first_trade_drill_")
    start = datetime(2026, 9, 1, 9, 0, 0)
    ab = [PY, os.path.join("scripts", "ab_adjudicate.py")]
    print(f"drill root: {base}\n")

    # ---- S1: both arms empty -------------------------------------------
    print("S1: both arms empty")
    a1, b1 = scenario_dirs(base, "s1")
    out = run(ab + ["--a-dir", a1, "--b-dir", b1])
    check("S1 KEEP COLLECTING (no data)", "KEEP COLLECTING (an arm has no data)" in verdict_of(out))

    # ---- S2: few trades, ETA -------------------------------------------
    print("S2: 12 closed trades per arm")
    a2, b2 = scenario_dirs(base, "s2")
    gen_ledger(os.path.join(a2, LEDGER), 11, 12, start, 0.0, 1.8, 9.0)
    gen_ledger(os.path.join(b2, LEDGER), 22, 12, start, 0.0, 2.4, 9.0)
    out = run(ab + ["--a-dir", a2, "--b-dir", b2])
    v = verdict_of(out)
    check("S2 KEEP COLLECTING (below gate)", v.startswith("KEEP COLLECTING"), v[:70])
    check("S2 ETA projected", "ETA ~" in out)

    # ---- S3: A wins cleanly --------------------------------------------
    print("S3: 40 paired trades, arm A better by +0.35R/pair")
    a3, b3 = scenario_dirs(base, "s3")
    rng = random.Random(7)
    epochs3 = gen_ledger(os.path.join(a3, LEDGER), 31, 40, start, 0.15, 1.8, 7.0)
    # arm B: same signal epochs, per-pair delta ~ +0.35R in A's favor
    with open(os.path.join(b3, LEDGER), "w", newline="\n") as f:
        eq = 50.0
        for i, oe in enumerate(epochs3):
            ce = oe + random.Random(100 + i).randint(900, 8 * 3600)
            ticket = 700_500_000 + i
            r_b = round(0.15 + rng.gauss(0, 0.9) - 0.35, 3)
            pnl = round(6.25 * r_b, 2)
            eq = round(eq + pnl, 2)
            entry = 49500.0 + rng.uniform(-400, 400)
            exit_p = entry - 300.0 * r_b
            reason = "TARGET" if r_b > 0.5 else ("STOP" if r_b < -0.9 else "PLOCK")
            f.write(f"OPEN,{oe},{ticket},-1,{entry:.5f},{entry + 300:.5f},{entry - 720:.5f},"
                    f"0.01,6.25,300.00,96,PB\n")
            f.write(f"CLOSE,{ce},{ticket},{reason},{exit_p:.5f},{r_b:.3f},{pnl:.2f},{eq:.2f}\n")
            f.write(f"EQ,{eq:.2f}\n")
    out = run(ab + ["--a-dir", a3, "--b-dir", b3])
    v = verdict_of(out)
    check("S3 declares A_tp18", v.startswith("A_tp18 (TP 1.8) earns the TP setting"), v[:70])
    check("S3 integrity ok both arms", out.count("integrity=ok") == 2)

    # ---- S4: noisy deltas, no declared signal ---------------------------
    # B's r = A's r + symmetric noise: same outcomes, no embedded edge. (NOTE:
    # giving B a different tp_mult embeds a REAL 2.4-vs-1.8 winner-pay effect
    # the paired test correctly catches - that was drill-design error v1.)
    print("S4: 40 paired trades, B = A + symmetric noise (no real signal)")
    a4, b4 = scenario_dirs(base, "s4")
    rng4 = random.Random(42)
    eq_a = eq_b = 50.0
    with open(os.path.join(a4, LEDGER), "w", newline="\n") as fa, \
         open(os.path.join(b4, LEDGER), "w", newline="\n") as fb:
        for i in range(40):
            oe = int((start + timedelta(hours=i * 7.0 + rng4.uniform(0, 0.4))).timestamp())
            hold = rng4.randint(900, 8 * 3600)
            r_a = round(rng4.gauss(0.02, 1.0), 3)
            r_b = round(r_a + rng4.gauss(0.0, 0.9), 3)
            for f, r, eq_box, tk in ((fa, r_a, "a", 700_900_000 + i),
                                     (fb, r_b, "b", 700_950_000 + i)):
                pnl = round(6.25 * r, 2)
                if eq_box == "a":
                    eq_a = round(eq_a + pnl, 2)
                    eq = eq_a
                else:
                    eq_b = round(eq_b + pnl, 2)
                    eq = eq_b
                entry = 49500.0 + rng4.uniform(-400, 400)
                f.write(f"OPEN,{oe},{tk},1,{entry:.5f},{entry - 300:.5f},{entry + 540:.5f},"
                        f"0.01,6.25,300.00,96,PB\n")
                f.write(f"CLOSE,{oe + hold},{tk},TARGET,{entry + 300 * r:.5f},{r:.3f},{pnl:.2f},{eq:.2f}\n")
                f.write(f"EQ,{eq:.2f}\n")
    out = run(ab + ["--a-dir", a4, "--b-dir", b4])
    v = verdict_of(out)
    check("S4 INCONCLUSIVE (noise refused)", v.startswith("INCONCLUSIVE"), v[:70])

    # ---- S5: reconciler days-gate, no broker pull -----------------------
    print("S5: 1.5-day ledger vs 7-day reconciler gate")
    a5, _ = scenario_dirs(base, "s5")
    gen_ledger(os.path.join(a5, LEDGER), 51, 6, start, 0.0, 1.8, 6.0)
    t0 = datetime.now()
    out = run([PY, os.path.join("scripts", "reconcile_paper_ticks.py"),
               "--a-dir", a5, "--min-days", "7"])
    dt = (datetime.now() - t0).total_seconds()
    check("S5 KEEP COLLECTING (days gate)", "days of data" in out and "KEEP COLLECTING" in out,
          f"ran {dt:.1f}s")
    check("S5 no broker pull (fast exit)", dt < 20, f"{dt:.1f}s < 20s")

    # ---- S6: morning_status internals on synthetic data ------------------
    print("S6: morning_status ledger parser + cross-midnight gap pairing")
    spec = importlib.util.spec_from_file_location(
        "morning_status", os.path.join(HERE, "morning_status.py"))
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    a6, _ = scenario_dirs(base, "s6")
    led_path = os.path.join(a6, LEDGER)
    gen_ledger(led_path, 61, 5, start, 0.1, 1.8, 6.0)
    led = ms.parse_ledger(led_path)
    check("S6 parse_ledger: 5 closed, no problems",
          len(led["closed"]) == 5 and not led["problems"] and led["veq_last"] is not None)
    jd = os.path.join(base, "s6", "logs")
    os.makedirs(jd, exist_ok=True)
    d1, d2 = datetime(2026, 9, 4), datetime(2026, 9, 5)
    with open(os.path.join(jd, "20260904.log"), "w", encoding="utf-16") as f:
        f.write("MN\t1\t23:59:00.000\tNetwork\t'123': connection to DerivSVG-Server-03 lost\r\n")
    with open(os.path.join(jd, "20260905.log"), "w", encoding="utf-16") as f:
        f.write("QO\t0\t00:10:00.000\tNetwork\t'123': authorized on DerivSVG-Server-03 (ping: 50 ms)\r\n")
    gaps = ms.journal_gaps(jd, d1, d2)
    check("S6 cross-midnight gap paired (23:59->00:10, closed)",
          len(gaps) == 1 and not gaps[0]["open"]
          and gaps[0]["lost"].strftime("%H:%M:%S") == "23:59:00"
          and gaps[0]["back"].strftime("%H:%M:%S") == "00:10:00")

    # ---- cleanup + restore truthful real-state artifacts ----------------
    shutil.rmtree(base, ignore_errors=True)
    print("\nrestoring real-state artifacts (re-run against actual terminals)...")
    pp_spec = importlib.util.spec_from_file_location(
        "paper_pipeline", os.path.join(HERE, "paper_pipeline.py"))
    pp = importlib.util.module_from_spec(pp_spec)
    pp_spec.loader.exec_module(pp)
    a_real, b_real = pp.discover_arm_dirs()
    have_real = ((a_real and os.path.exists(os.path.join(a_real, LEDGER)))
                 or (b_real and os.path.exists(os.path.join(b_real, LEDGER))))
    if have_real:
        out = run(ab + ["--a-dir", a_real or b_real, "--b-dir", b_real or a_real])
        print("  ab_adjudicate (real): " + verdict_of(out))
        out = run([PY, os.path.join("scripts", "reconcile_paper_ticks.py"),
                   "--a-dir", a_real or b_real]
                  + (["--b-dir", b_real] if b_real else []))
        print("  reconcile (real):     " + verdict_of(out))
    else:
        # no real ledger anywhere yet: the truthful artifact state is ABSENT,
        # and the adjudicator skips its artifact write when a ledger is missing,
        # so remove any drill-polluted fixed-path artifacts
        for art in (os.path.join(ROOT, "artifacts", "v75_replay", "ab_adjudication.json"),
                    os.path.join(ROOT, "artifacts", "v75_replay", "paper_tick_reconciliation.json")):
            if os.path.exists(art):
                os.remove(art)
        print("  no real ledger yet - drill artifacts removed (truthful empty state)")

    print(f"\nDRILL RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL))
        sys.exit(1)
    print("ALL GREEN - the paper-data path is proven end to end.")


if __name__ == "__main__":
    main()
