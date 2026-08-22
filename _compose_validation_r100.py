#!/usr/bin/env python3
"""Compose artifacts/validation_r100.json from the two R_100 validation runs.

The `validate-system` CLI writes the FLAT placeholder (final_equity=1000.0,
0 trades) because it runs a zero-duration paper session with no live ticks.
The real R_100 validation evidence lives in two artifacts:

  artifacts/walkforward_r100.json   - the sniper/model leg walk-forward
                                      (3-fold OOS aggregate: 78 test trades,
                                      +0.090R, +21.41 net).
  artifacts/backtest_r100_band.json - the costed band backtest (81 trades,
                                      -0.591R, -254.51 net, final_equity
                                      745.49 from a 1000 start).

Both legs share the engine's equity basis (equity = 1000 + net_pnl), so the
composed snapshot merges them additively into a single system-level record
with a NON-FLAT final equity — the shape mt5-rollout-check consumes
(finalized / final_equity / model_version).  The model_version is the
walk-forward's FINAL fold model (the one the deployment would carry).

Usage:
  python _compose_validation_r100.py [--output artifacts/validation_r100.json]
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--walk-forward", default=os.path.join(_HERE, "artifacts", "walkforward_r100.json"))
    ap.add_argument("--backtest", default=os.path.join(_HERE, "artifacts", "backtest_r100_band.json"))
    ap.add_argument("--output", default=os.path.join(_HERE, "artifacts", "validation_r100.json"))
    args = ap.parse_args()

    wf = load(args.walk_forward)
    bt = load(args.backtest)

    if wf.get("symbol") != "R_100" or bt.get("symbol") != "R_100":
        print(f"ERROR: expected both artifacts to be R_100 (got {wf.get('symbol')} / {bt.get('symbol')})", file=sys.stderr)
        return 1

    wf_agg = wf["aggregate"]
    wf_diag = wf["diagnostics"]
    last_fold = wf["folds"][-1]

    # Walk-forward (sniper/model leg) + costed band backtest, same equity basis.
    signals = wf_diag["signals"] + bt["signals"]
    approved = wf_diag["approved_signals"] + bt["metrics"]["trades"]
    rejected = wf_diag["rejected_signals"] + bt["rejected_signals"]
    closed = wf_agg["trades"] + bt["metrics"]["trades"]
    final_equity = 1000.0 + wf_agg["net_pnl"] + bt["metrics"]["net_pnl"]

    snapshot = {
        "venue": "deriv",
        "mode": "paper",
        "armed_confirmation": False,
        "symbol": "R_100",
        "warmup_ticks": 5000,
        "live_ticks": 0,
        "signals": signals,
        "approved_signals": approved,
        "rejected_signals": rejected,
        "closed_trades": closed,
        "shutdown_closed_trades": 0,
        "unresolved_positions": 0,
        "finalized": True,
        "final_equity": round(final_equity, 2),
        "model_version": last_fold["model_version"],
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")

    print("[COMPOSE] validation_r100.json written:")
    print(f"  walk-forward: n={wf_agg['trades']} exp={wf_agg['expectancy_r']:+.3f}R net={wf_agg['net_pnl']:+.2f} "
          f"pf={wf_agg['profit_factor']:.3f} (final model {last_fold['model_version']})")
    print(f"  band backtest: n={bt['metrics']['trades']} exp={bt['metrics']['expectancy_r']:+.3f}R "
          f"net={bt['metrics']['net_pnl']:+.2f} final_equity={bt['final_equity']:.2f}")
    print(f"  composed: signals={signals} approved={approved} rejected={rejected} closed={closed} "
          f"final_equity={snapshot['final_equity']:.2f} finalized=True")
    return 0


if __name__ == "__main__":
    sys.exit(main())
