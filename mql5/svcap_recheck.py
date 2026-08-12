#!/usr/bin/env python3
"""Out-of-sample re-check of the svcap combined gate as the R_75 corpus
compounds past the 10.5-day measurement.

The 2026-08-11 sweep (10.5-day corpus) found the best balanced cell:
  svcap = UTC 12-24h & |range_z_50|<1.0 (production gate in
          DecisionEngine.evaluate)  +  |garch_z_score| <= 1.5 (entry_filter,
          research depth cap) with the TIME-exit broker:
          n=146, hit 52.1%, +0.161R gross, +0.111R net@0.05, +0.061R net@0.10,
          maxDD 5.85R, worst streak 5, walk-forward KEPT 146/146.

This script re-runs the SAME methodology on the CURRENT corpus (13.02 days
at last check — the out-of-sample growth) for both the sv cell (gate only)
and the svcap cell (gate + gz cap), and prints the delta vs the 10.5-day
values.  Fidelity is inherent: identical `run_sniper_ticks_captured` path,
fresh model per run (clear_assembler_caches), in-loop filtering (the ML
model never learns from filtered signals).

Usage:  python mql5/svcap_recheck.py [--timeframe 300]
"""
import argparse
import os
import sys
import time
from statistics import mean

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from tradequality_real_corpus_check import (  # noqa: E402
    clear_assembler_caches,
    dedupe_ticks,
    load_ticks_csv,
    run_sniper_ticks_captured,
    walk_forward_stage3_gate,
    CORPUS_PATHS,
)


def gz_cap_filter(signal, cap=1.5):
    """Research depth cap: |entry-bar garch z-score| <= 1.5, the sniper
    analog of the band's |z|/z_entry edge-depth measure."""
    feats = signal.snapshot.features
    return abs(feats.get("garch_z_score", 0.0)) <= cap


def stats(outcomes, broker):
    n = len(outcomes)
    hit = (sum(1 for o in outcomes if o.won) / n) if n else 0.0
    gross = mean(o.return_r for o in outcomes) if n else 0.0
    ordered = sorted(outcomes, key=lambda o: o.closed_at)
    peak = cum = max_dd = 0.0
    streak = worst = 0
    for o in ordered:
        cum += o.return_r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        if o.return_r <= 0.0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    tags = walk_forward_stage3_gate(outcomes, broker)
    kept = [t for t in tags if t["state"] != "suppressed"]
    return {
        "n": n, "hit": hit, "gross": gross,
        "net05": gross - 0.05, "net10": gross - 0.10,
        "max_dd": max_dd, "worst_streak": worst,
        "kept": len(kept), "suppressed": n - len(kept),
    }


# --- walk-forward gate contract (the scheduled-verification loop's check) ---
# Reference run (13.02-day corpus, 2026-08-12): svcap cell kept=147/147,
# suppressed=0 — the gate trades every signal of a gate-clean cell.  A
# suppressed-vs-kept REGRESSION (the gate starting to block a previously
# clean cell) must fail the loop visibly: --gate-check emits a strict
# [GATECHECK] PASS/FAIL/SKIP verdict with a nonzero exit code on FAIL.
GATE_CEILING = 0.10   # max allowed suppressed fraction of the svcap cell
GATE_MIN_N   = 30     # below this trade count the verdict is SKIP (thin corpus)


def run_cell(ticks, timeframe_sec, label, filt):
    """One real run_ticks pass with a fresh model; returns stats + run info."""
    clear_assembler_caches()
    t0 = time.time()
    out, broker, sig, rej, model = run_sniper_ticks_captured(
        ticks, timeframe_sec, time_exit=True, entry_filter=filt)
    st = stats(out, broker)
    st["seconds"] = time.time() - t0
    st["signals"] = sig
    st["rejected"] = rej
    st["filtered"] = getattr(broker, "filtered", 0)
    st["model"] = model.version
    print(f"[SVCAP] {label}: n={st['n']} hit={st['hit']*100:.1f}% "
          f"gross={st['gross']:+.3f}R net@0.05={st['net05']:+.3f}R "
          f"net@0.10={st['net10']:+.3f}R maxDD={st['max_dd']:.2f}R "
          f"streak={st['worst_streak']} kept={st['kept']}/{st['n']} "
          f"({st['seconds']:.0f}s, signals={sig} rejected={rej} "
          f"filtered={st['filtered']} model={model.version})", flush=True)
    return st


def gate_verdict(st, ceiling=GATE_CEILING, min_n=GATE_MIN_N):
    """Pure verdict for the gate contract — unit-testable without a run_ticks
    pass.  SKIP when the corpus is too thin, FAIL on a suppressed-vs-kept
    regression (gate blocking a previously clean cell), on zero kept trades,
    or on a gross expectancy regression.  Returns (verdict, [messages])."""
    n, suppressed, kept = st["n"], st["suppressed"], st["kept"]
    frac = suppressed / n if n else 1.0
    msgs = []
    if n < min_n:
        verdict = "SKIP"
        msgs.append(f"n={n} below min {min_n} — corpus too thin for a verdict")
    else:
        if frac > ceiling:
            msgs.append(f"suppressed {suppressed}/{n} ({frac*100:.1f}%) "
                        f"exceeds ceiling {ceiling*100:.0f}% — the walk-forward "
                        f"gate is blocking a previously gate-clean cell "
                        f"(suppressed-vs-kept regression)")
        if kept == 0:
            msgs.append("zero kept trades — the gate now suppresses everything")
        if st["net05"] <= -0.10:
            msgs.append(f"net@0.05 {st['net05']:+.3f}R well below the "
                        f"measured +0.111..0.160R band — expectancy regression")
        verdict = "FAIL" if msgs else "PASS"
    return verdict, msgs


def gate_check(ticks, timeframe_sec, ceiling=GATE_CEILING, min_n=GATE_MIN_N):
    """The scheduled-verification contract: run the svcap cell (the
    reference gate-clean configuration) and assert the walk-forward gate's
    suppressed-vs-kept split stays sane.  Returns the process exit code."""
    label = ("svcap gate-check (UTC 12-24h & |range_z|<1.0 & |garch_z|<=1.5, "
             "time-exit)")
    st = run_cell(ticks, timeframe_sec, label, lambda sig: gz_cap_filter(sig))
    verdict, msgs = gate_verdict(st, ceiling=ceiling, min_n=min_n)
    n, suppressed, kept = st["n"], st["suppressed"], st["kept"]
    frac = suppressed / n if n else 1.0
    print(f"[GATECHECK] {verdict}: svcap n={n} hit={st['hit']*100:.1f}% "
          f"exp={st['gross']:+.3f}R net@0.05={st['net05']:+.3f}R "
          f"kept={kept} suppressed={suppressed} ({frac*100:.1f}%)", flush=True)
    for m in msgs:
        print(f"[GATECHECK]   - {m}", flush=True)
    return 0 if verdict != "FAIL" else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", type=int, default=300)
    ap.add_argument("--gate-check", action="store_true",
                    help="emit the walk-forward gate contract (svcap cell) and "
                         "exit nonzero on a suppressed-vs-kept regression")
    ap.add_argument("--gate-ceiling", type=float, default=GATE_CEILING,
                    help="max allowed suppressed fraction (default 0.10)")
    ap.add_argument("--gate-min-n", type=int, default=GATE_MIN_N,
                    help="min trade count for a verdict (default 30)")
    args = ap.parse_args()

    ticks = dedupe_ticks([
        t for p in CORPUS_PATHS if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    span = (max(t.epoch for t in ticks) - min(t.epoch for t in ticks)) / 86400
    print(f"[SVCAP] loaded {len(ticks)} R_75 ticks ({span:.2f} days) "
          f"-- svcap was measured at 10.50 days", flush=True)

    if args.gate_check:
        sys.exit(gate_check(ticks, args.timeframe,
                            ceiling=args.gate_ceiling, min_n=args.gate_min_n))

    runs = [
        ("sv 12-24h/rz<1.0 (gate only)", None),
        ("svcap .../gz<=1.5 (gate + cap)", lambda sig: gz_cap_filter(sig)),
    ]
    results = {}
    for label, filt in runs:
        results[label] = run_cell(ticks, args.timeframe, label, filt)

    print("\n[SVCAP] out-of-sample vs the 10.5-day measurement:", flush=True)
    print("[SVCAP]   cell                    n   hit    gross  net@0.05 "
          "net@0.10  maxDD  streak  kept", flush=True)
    ref = {"sv": (149, 50.3, +0.142, +0.092, +0.042, 5.71, 5),
           "svcap": (146, 52.1, +0.161, +0.111, +0.061, 5.85, 5)}
    for label, st in results.items():
        key = "sv" if "gate only" in label else "svcap"
        r = ref[key]
        print(f"[SVCAP]   {label:24} {st['n']:>4} {st['hit']*100:>5.1f}% "
              f"{st['gross']:>+6.3f} {st['net05']:>+7.3f} {st['net10']:>+7.3f} "
              f"{st['max_dd']:>6.2f} {st['worst_streak']:>6} "
              f"{st['kept']:>3}/{st['n']}", flush=True)
        print(f"[SVCAP]     10.5d ref           {r[0]:>4} {r[1]:>5.1f}% "
              f"{r[2]:>+6.3f} {r[3]:>+7.3f} {r[4]:>+7.3f} "
              f"{r[5]:>6.2f} {r[6]:>6}", flush=True)
        d_hit = st["hit"] * 100 - r[1]
        d_net = st["net05"] - r[3]
        verdict = ("HOLDS" if st["net05"] > 0 and d_net > -0.03 else
                   "WEAKENED" if st["net05"] > 0 else "BROKEN")
        print(f"[SVCAP]     -> hit {d_hit:+.1f}pp, net@0.05 {d_net:+.3f}R "
              f"vs ref: {verdict}", flush=True)


if __name__ == "__main__":
    main()
