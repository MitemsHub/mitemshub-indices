#!/usr/bin/env python3
"""Sweep band-fade z-entry / timeframe / stop-multiplier for frequency-vs-profit.

Runs the REPO'S OWN band strategy (`run_vol_band_backtest`, EGARCH-based — the
same machinery behind the walk-forward research numbers) over:

  * SYNTHESIZED calibrated series per volatility tier (V75/V100), 1-min
    resolution, N days, GBM + AR(1) vol-clustering, post-hoc normalized so
    realized annualized vol matches the tier. Seeded -> reproducible.
  * OPTIONAL real ticks (--ticks-csv) as a live-microstructure sanity check.

Grid: z_entry x timeframe(M15/M30/H1) x stop_sigma_mult(0.10/0.20).
Risk-engine halts are RELAXED so cells measure raw edge, matching the
TESTER_BFONLY philosophy (halts are system behavior, already audited).

Gates (same philosophy as STRATEGY_TESTER_VALIDATION.md):
  PASS = trades>=30 AND profit_factor>=1.30 AND expectancy_r>=+0.15
Frontier = passing cells ranked by trades/day (highest sustainable frequency).

Usage:
  python scripts/sweep_bandfade_params.py                 # synth sweep
  python scripts/sweep_bandfade_params.py --days 90       # shorter/faster
  python scripts/sweep_bandfade_params.py --ticks-csv src/synthetic_trader/data/R_100_ticks.csv
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _cand in (ROOT / "src", ROOT):
    if (_cand / "synthetic_trader" / "backtest" / "vol_band.py").exists():
        sys.path.insert(0, str(_cand))
        break

from synthetic_trader.backtest.vol_band import VolBandConfig, run_vol_band_backtest  # noqa: E402
from synthetic_trader.backtest.engine import load_ticks_csv  # noqa: E402
from synthetic_trader.config import PaperExecutionConfig, RiskConfig, TraderConfig  # noqa: E402
from synthetic_trader.domain import Tick  # noqa: E402

# tier -> (annualized vol approximation, representative price)
TIERS = {
    "R_75": {"ann_vol": 0.75, "price": 1575.0},
    "R_100": {"ann_vol": 1.00, "price": 840.0},
}
Z_GRID = [1.0, 1.4, 1.8, 2.0, 2.2]
TF_GRID = [("M15", 900), ("M30", 1800), ("H1", 3600)]
STOP_GRID = [0.10, 0.20]
MIN_TRADES, MIN_PF, MIN_EXP_R = 30, 1.30, 0.15


def synth_ticks(symbol: str, days: int, seed: int) -> list[Tick]:
    """1-min GBM ticks with AR(1) log-vol clustering, variance-normalized."""
    tier = TIERS[symbol]
    rng = __import__("random").Random(seed)
    n = days * 1440
    base_sd = tier["ann_vol"] / math.sqrt(252.0 * 1440.0)

    # AR(1) unit-variance driver for the volatility multiplier
    phi, lam = 0.96, 0.50
    shocks: list[float] = []
    y = 0.0
    innov_sd = math.sqrt(1.0 - phi * phi)
    for _ in range(n):
        y = phi * y + rng.gauss(0.0, innov_sd)
        shocks.append(math.exp(lam * y - lam * lam / 2.0))

    raw = [rng.gauss(0.0, 1.0) * s for s in shocks]
    realized = math.sqrt(sum(r * r for r in raw)) or 1.0
    scale = base_sd * math.sqrt(n) / realized  # exact total-var match

    price, epoch0, out = tier["price"], 1_750_000_000.0, []
    p = price
    for i in range(n):
        p *= math.exp(raw[i] * scale)
        out.append(Tick(symbol=symbol, epoch=epoch0 + i * 60.0, price=round(p, 3)))
    return out


def relaxed_config() -> TraderConfig:
    risk = RiskConfig(
        max_daily_loss_fraction=0.99,
        max_consecutive_losses=9999,
        min_session_quality=0.0,
        session_filter_warmup=0,
        min_confidence=0.0,
    )
    cfg = TraderConfig.default()
    return replace(cfg, risk=risk)


def run_cell(ticks, symbol, tf_sec, z, stop, days, window=None) -> dict:
    strat = VolBandConfig(
        z_entry=z, stop_sigma_mult=stop, breakeven_trail_frac=0.0,
    )
    kwargs = {}
    if window is not None:
        kwargs["count_from_epoch"], kwargs["count_until_epoch"] = window
    res = run_vol_band_backtest(
        ticks, symbol, timeframe_sec=tf_sec,
        config=relaxed_config(), strategy_config=strat,
        paper=PaperExecutionConfig(),
        **kwargs,
    )
    m = res.metrics
    pf = m.profit_factor if m.profit_factor != float("inf") else 99.0
    return {
        "symbol": symbol, "tf": tf_sec, "z": z, "stop": stop,
        "trades": m.trades, "per_day": round(m.trades / days, 2),
        "wr": round(m.win_rate * 100.0, 1),
        "pf": round(pf, 2), "exp_r": round(m.expectancy_r, 3),
        "pnl": round(m.net_pnl, 2),
        "pass": bool(m.trades >= MIN_TRADES and pf >= MIN_PF
                     and m.expectancy_r >= MIN_EXP_R),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--ticks-csv", default=None, help="real tick CSV sanity check")
    ap.add_argument("--json", default="artifacts/bandfade_sweep.json")
    a = ap.parse_args(argv)

    results: list[dict] = []

    if a.ticks_csv:
        real = load_ticks_csv(a.ticks_csv, "R_100")
        span_days = max(1e-6, (real[-1].epoch - real[0].epoch) / 86400.0)
        print(f"[real] {len(real)} ticks, {span_days:.3f} days "
              f"(informational only - sample too small for gates)")
        for z in (1.4, 2.0):
            r = run_cell(real, "R_100", 900, z, 0.10, span_days)
            r["note"] = "REAL TICKS"
            results.append(r)
            print(f"  real z={z}: {r['trades']} trades, PF={r['pf']}, "
                  f"expR={r['exp_r']}")

    t0 = time.time()
    tick_cache: dict[str, list] = {}
    for sym in TIERS:
        ticks = synth_ticks(sym, a.days, seed=20260825 + hash(sym) % 1000)
        tick_cache[sym] = ticks
        print(f"\n[{sym}] {len(ticks)} synthesized 1-min ticks "
              f"({a.days}d, ann_vol~{TIERS[sym]['ann_vol']:.0%})")
        for tf_name, tf_sec in TF_GRID:
            for z in Z_GRID:
                for stop in STOP_GRID:
                    r = run_cell(ticks, sym, tf_sec, z, stop, a.days)
                    r["tf_name"] = tf_name
                    results.append(r)
                    flag = "PASS" if r["pass"] else "    "
                    print(f"  {tf_name} z={z:<3} stop={stop:<4} | "
                          f"{r['trades']:>4} tr ({r['per_day']:>5}/d) "
                          f"WR {r['wr']:>5}% PF {r['pf']:>5} expR {r['exp_r']:>+6.3f} {flag}")
        del ticks

    passing = [r for r in results if r.get("pass")]
    passing.sort(key=lambda r: (-r["per_day"], -r["pf"]))
    print("\n" + "=" * 78)
    print("FREQUENCY FRONTIER (passing gates: >=30 trades, PF>=1.30, expR>=+0.15)")
    print("=" * 78)
    if not passing:
        print("No cell passed. Either raise --days or accept lower-frequency configs.")
    for i, r in enumerate(passing[:10], 1):
        print(f"{i:>2}. {r['symbol']:<6} {r['tf_name']:<3} z={r['z']:<3} "
              f"stop={r['stop']:.2f} | {r['per_day']:>5} tr/day | "
              f"PF {r['pf']:>5} expR {r['exp_r']:>+6.3f} WR {r['wr']}%")

    # Walk-forward honesty: split the synth series in halves for the BEST
    # cell per symbol. An edge driven by one lucky half must be flagged.
    if a.days >= 60:
        print("\n--- WALK-FORWARD SPLIT (best cell per symbol) ---")
        seen_syms = set()
        for r in passing:
            if r["symbol"] in seen_syms or "note" in r:
                continue
            seen_syms.add(r["symbol"])
            sym_ticks = tick_cache[r["symbol"]]
            e0, e1 = sym_ticks[0].epoch, sym_ticks[-1].epoch
            mid = e0 + (e1 - e0) / 2.0
            halves = []
            for lo, hi in ((e0, mid), (mid, e1)):
                hr = run_cell(sym_ticks, r["symbol"], r["tf"], r["z"],
                              r["stop"], max(1e-9, (hi - lo) / 86400.0),
                              window=(lo, hi))
                halves.append(hr)
            (h1, h2) = halves
            ok = h1["exp_r"] > 0 and h2["exp_r"] > 0
            print(f"  {r['symbol']:<6} z={r['z']} stop={r['stop']:.2f} "
                  f"tf={r['tf_name']}: h1 expR {h1['exp_r']:+.3f} ({h1['trades']}tr) | "
                  f"h2 expR {h2['exp_r']:+.3f} ({h2['trades']}tr) "
                  f"-> {'BOTH HALVES POSITIVE' if ok else 'UNSTABLE - do not trust'}")

    base = [r for r in results if r["z"] == 2.0 and r["stop"] == 0.10
            and r["tf"] == 900 and "note" not in r]
    if base:
        b = base[0]
        print(f"\nEA-current-equivalent baseline (R_100-ish tiers, M15 z=2.0 stop=.10): "
              f"{b['trades']} trades, PF={b['pf']}, expR={b['exp_r']:+.3f}")
    print(f"\n[done in {time.time()-t0:.0f}s]")

    out = Path(a.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"[wrote] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
