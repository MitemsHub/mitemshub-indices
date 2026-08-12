#!/usr/bin/env python3
"""A/B: the GARCH guard bug — frozen vs live garch_z_score, quantified.

The guard bug (`if log_return != 0.0 and observations > 0`) never allowed the
FIRST update(), so observations stayed 0, `update()` was never called and
`get_forecast()` returned the pristine defaults in every snapshot:
garch_z_score=0.0, garch_vol_ratio=1.0, garch_mean_revert_signal=0.0,
garch_vol_regime=1.0, garch_sigma=0.02.  The confidence components fell into
their neutral branches and the online ML model's garch features were constant
(dead weight).

This probe replays the REAL sniper capture twice on the current R_75 corpus:
  - FROZEN: ArchGarchForecaster.update patched to a no-op returning
    get_forecast() — byte-for-byte the old guard's behavior.
  - LIVE:   the fixed code (update from observation 1).
The online ML model is fresh per run and learns from outcomes in both; the
entry gate (UTC 12-24h & |range_z_50|<1.0) uses range_z_50 — untouched by the
freeze — so any difference is purely the garch features.

Usage: python _probe_garch_live.py [--timeframe 300]
"""
import argparse
import os
import sys
from statistics import mean

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "mql5"))
sys.path.insert(0, os.path.join(_HERE, "src"))

import tradequality_real_corpus_check as tqc  # noqa: E402
from tradequality_real_corpus_check import (  # noqa: E402
    CapturePaperBroker,
    clear_assembler_caches,
    dedupe_ticks,
    load_ticks_csv,
    run_sniper_ticks_captured,
    CORPUS_PATHS,
)
from synthetic_trader.features.arch_garch import ArchGarchForecaster  # noqa: E402

GARCH_KEYS = ("garch_z_score", "garch_vol_ratio", "garch_mean_revert_signal",
              "garch_vol_regime", "garch_sigma")


class GarchCaptureBroker(CapturePaperBroker):
    """Records each position's entry-time garch features for the A/B."""

    def __init__(self, config):
        super().__init__(config)
        self.features_by_pid = {}

    def submit(self, intent):
        pos = super().submit(intent)
        f = intent.signal.snapshot.features
        self.features_by_pid[pos.id] = {
            "epoch": intent.signal.snapshot.epoch,
            **{k: f.get(k, 0.0) for k in GARCH_KEYS},
        }
        return pos


def run_once(ticks, tf, frozen):
    """One full sniper capture.  Returns stats dict."""
    tqc.CapturePaperBroker = GarchCaptureBroker
    orig = None
    if frozen:
        # The old guard: update() never allowed -> get_forecast() always.
        orig = ArchGarchForecaster.update
        ArchGarchForecaster.update = lambda self, lr: self.get_forecast()
    clear_assembler_caches()
    try:
        outcomes, broker, signals, rejected, model = run_sniper_ticks_captured(
            ticks, tf)
    finally:
        if frozen:
            ArchGarchForecaster.update = orig
        clear_assembler_caches()

    n = len(outcomes)
    hit = (sum(1 for o in outcomes if o.won) / n) if n else 0.0
    gross = mean(o.return_r for o in outcomes) if n else 0.0
    feats = [broker.features_by_pid[o.position_id] for o in outcomes]
    zs = [f["garch_z_score"] for f in feats]
    return {
        "tag": "FROZEN" if frozen else "LIVE  ",
        "signals": signals,
        "rejected": rejected,
        "n": n,
        "hit": hit,
        "gross": gross,
        "net005": gross - 0.05,
        "net010": gross - 0.10,
        "z_mean": mean(zs) if zs else 0.0,
        "z_med": sorted(zs)[n // 2] if zs else 0.0,
        "z_share_gt1_5": (sum(1 for z in zs if abs(z) > 1.5) / n) if n else 0.0,
        "vr_mean": mean(f["garch_vol_ratio"] for f in feats) if feats else 0.0,
        "vr_share_neutral": (sum(1 for f in feats
                                 if abs(f["garch_vol_ratio"] - 1.0) < 1e-9) / n) if n else 0.0,
        "mr_mean": mean(f["garch_mean_revert_signal"] for f in feats) if feats else 0.0,
        "sigma_min": min((f["garch_sigma"] for f in feats), default=0.0),
        "sigma_max": max((f["garch_sigma"] for f in feats), default=0.0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", type=int, default=300)
    args = ap.parse_args()

    ticks = dedupe_ticks([
        t for p in CORPUS_PATHS if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    span = (max(t.epoch for t in ticks) - min(t.epoch for t in ticks)) / 86400
    print(f"[GARCH] loaded {len(ticks)} R_75 ticks ({span:.2f} days)")

    frozen = run_once(ticks, args.timeframe, frozen=True)
    print(f"[GARCH] frozen run: signals={frozen['signals']} "
          f"rejected={frozen['rejected']} closed={frozen['n']}")
    live = run_once(ticks, args.timeframe, frozen=False)
    print(f"[GARCH] live run:   signals={live['signals']} "
          f"rejected={live['rejected']} closed={live['n']}")

    print("\n[GARCH]              n   hit    gross  net@.05 net@.10  "
          "z_mean z_med |z|>1.5 vr_mean vr=1.0 mr_mean sigma")
    for r in (frozen, live):
        print(f"[GARCH] {r['tag']} {r['n']:>5} {r['hit']*100:>5.1f}% "
              f"{r['gross']:>+7.3f} {r['net005']:>+7.3f} {r['net010']:>+7.3f}  "
              f"{r['z_mean']:>6.2f} {r['z_med']:>5.2f} {r['z_share_gt1_5']*100:>6.1f}% "
              f"{r['vr_mean']:>7.3f} {r['vr_share_neutral']*100:>6.1f}% "
              f"{r['mr_mean']:>7.3f} {r['sigma_min']:.4f}-{r['sigma_max']:.4f}")

    dn = live["n"] - frozen["n"]
    print(f"\n[GARCH] trade delta (live-frozen): {dn:+d} "
          f"({dn / frozen['n'] * 100:+.1f}% if frozen>0)")
    print(f"[GARCH] exp delta: gross {live['gross'] - frozen['gross']:+.3f}R, "
          f"net@.05 {live['net005'] - frozen['net005']:+.3f}R")
    if live["n"] and frozen["n"]:
        print(f"[GARCH] hit delta: {(live['hit'] - frozen['hit']) * 100:+.1f}pp")


if __name__ == "__main__":
    main()
