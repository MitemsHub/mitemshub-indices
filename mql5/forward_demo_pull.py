#!/usr/bin/env python3
"""Pull report for the forward-demo pass — gate decisions, fills, hit-rate read.

Parses journals/forward_demo_18_24.jsonl and prints:
  1. Gate decisions — decision_skip reasons by count (the gate firing ledger).
  2. Signals — every emitted plan: time, direction, entry/stop/target, RR,
     confidence, regime (the "calls" the pass made).
  3. Fill quality — for each outcome: planned vs actual entry (slippage),
     realized RR vs planned RR, hold duration, exit type (won/lost).
  4. Hit-rate read — wins/total vs the reference 58.2% cell (n=67,
     +0.242R @ RR 1.2), with a binomial 95% CI so a small n is read honestly.

Record epochs are broker SERVER time (UTC+3); times are printed as UTC.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_JOURNAL = _HERE.parent / "journals" / "forward_demo_18_24.jsonl"
REFERENCE_HIT = 0.582   # the 18-24h & |range_z|<1.5 cell: n=67, hit 58.2%, +0.242R@1.2
REFERENCE_N = 67
SERVER_OFFSET_H = 3.0   # Deriv server = UTC+3; journal epochs are server time


def _utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch - SERVER_OFFSET_H * 3600.0, timezone.utc).isoformat(
        timespec="seconds")


def _binomial_ci(n: int, k: int) -> tuple[float, float]:
    """Wilson score interval (honest for tiny n)."""
    if n == 0:
        return 0.0, 0.0
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    args = ap.parse_args()

    recs = []
    with open(args.journal, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    types = Counter(r.get("type") for r in recs)
    skips = [r for r in recs if r.get("type") == "decision_skip"]
    signals = [r for r in recs if r.get("type") == "signal"]
    outcomes = [r for r in recs if r.get("type") == "outcome"]
    rejects = [r for r in recs if r.get("type") == "rejection"]

    print(f"=== FORWARD-PASS PULL  {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z ===")
    print(f"journal records: {len(recs)}  (skips={len(skips)} signals={len(signals)} "
          f"outcomes={len(outcomes)} rejections={len(rejects)} "
          f"other={sum(types.values()) - len(skips) - len(signals) - len(outcomes) - len(rejects)})")

    # ── 1. gate decisions ───────────────────────────────────────────────
    print("\n=== 1. GATE DECISIONS (decision_skip reasons) ===")
    reason_counts = Counter()
    for r in skips:
        reason = "; ".join(r.get("reasons", [])) or "(no reason)"
        reason_counts[reason] += 1
    for reason, c in reason_counts.most_common():
        print(f"  {c:>4}  {reason}")
    if skips:
        first_t, last_t = skips[0].get("epoch"), skips[-1].get("epoch")
        print(f"  ledger span: {_utc(first_t)}Z -> {_utc(last_t)}Z  "
              f"({(last_t - first_t) / 3600.0:.1f}h)")

    # ── 2. signals (the calls) ──────────────────────────────────────────
    print("\n=== 2. SIGNALS (plans emitted) ===")
    if not signals:
        print("  (none yet)")
    for i, s in enumerate(signals, 1):
        rr = s.get("reward_risk")
        print(f"  #{i} {_utc(s.get('epoch', 0))}Z {s.get('direction','?'):<5} "
              f"entry={s.get('entry')} stop={s.get('stop_loss')} "
              f"target={s.get('take_profit')} RR={rr:.2f} conf={s.get('confidence'):.2f} "
              f"regime={s.get('regime')}")

    # ── 3. fill quality ─────────────────────────────────────────────────
    print("\n=== 3. FILL QUALITY (outcomes) ===")
    if not outcomes:
        print("  (none yet)")
    for i, o in enumerate(outcomes, 1):
        dur_min = (o.get("closed_at", 0) - o.get("opened_at", 0)) / 60.0
        slip = abs(o.get("exit", 0) - o.get("entry", 0))  # not real slippage; see note
        print(f"  #{i} {_utc(o.get('opened_at', 0))}Z {o.get('direction','?'):<5} "
              f"entry={o.get('entry')} exit={o.get('exit')} "
              f"r={o.get('return_r'):+.2f} pnl={o.get('pnl'):+.2f} "
              f"dur={dur_min:.0f}min won={o.get('won')}")
    if outcomes:
        print("  note: simulated backend fills at the plan's entry (zero slippage by "
              "construction); fill quality = plan integrity (entry/stop/target as emitted).")

    # ── 4. hit-rate read vs the 58.2% cell ──────────────────────────────
    print("\n=== 4. HIT-RATE READ vs 58.2% cell ===")
    if not outcomes:
        print("  no closed trades yet — nothing to compare")
    else:
        won = sum(1 for o in outcomes if o.get("won"))
        n = len(outcomes)
        hit = won / n
        lo, hi = _binomial_ci(n, won)
        exp = sum(o.get("return_r", 0.0) for o in outcomes) / n
        print(f"  closed trades: {n}  wins: {won}  hit: {hit * 100:.1f}%  "
              f"(95% CI {lo * 100:.1f}-{hi * 100:.1f}%)  avg R: {exp:+.3f}")
        print(f"  reference cell: {REFERENCE_HIT * 100:.1f}% hit / +0.242R (n={REFERENCE_N})")
        gap = hit - REFERENCE_HIT
        verdict = "tracking" if abs(gap) <= 0.10 else (
            "ABOVE cell (n too small to trust)" if gap > 0 else "BELOW cell")
        print(f"  gap: {gap * 100:+.1f}pp  verdict: {verdict}  "
              f"(n={n} is not statistically decisive — Wilson CI above)")

    print(f"\n[FWD-PULL] records={len(recs)} skips={len(skips)} signals={len(signals)} "
          f"outcomes={len(outcomes)} wins={sum(1 for o in outcomes if o.get('won'))} "
          f"hit={sum(1 for o in outcomes if o.get('won')) / len(outcomes) * 100:.1f}%"
          if outcomes else
          f"[FWD-PULL] records={len(recs)} skips={len(skips)} signals={len(signals)} "
          f"outcomes=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
