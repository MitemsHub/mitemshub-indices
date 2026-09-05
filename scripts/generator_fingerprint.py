"""Generator fingerprint study — reverse-engineering the V75 tick generator.

Question (user directive): understand how the tick generator works —
mathematically, statistically — and whether ANY tick-level edge exists, or
whether the only real edge lives at the M15 scale the EA trades.

Tests the random-walk / constant-volatility null rigorously:
  T1  inter-tick interval distribution (engineering fingerprint: clock)
  T2  tick jump-size distribution (fat tails? discrete step machine?)
  T3  return autocorrelation at tick level, lag 1..100 (momentum/mean-reversion?)
  T4  variance ratio across aggregations 1s..1h (random-walk test at scale)
  T5  run/burst-length distribution vs memoryless expectation (bursty generator?)
  T6  volatility clustering: |r| autocorrelation (is vol forecastable? GARCH support)
  T7  time-of-day vol stability ("constant volatility" claim test)

Output: artifacts/generator/fingerprint.json + printed verdict per test.
The verdicts decide where edge CAN live before any strategy is built.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

TICK_FILE = "artifacts/data/volatility_75_index_ticks_20260803_20260902.csv"
OUT_DIR = "artifacts/generator"


def load_ticks(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = "epoch_ms" if "epoch_ms" in df.columns else df.columns[0]
    df = df.rename(columns={tcol: "ms"})
    # accept epoch seconds or milliseconds (2s-grid recorder archives use seconds)
    if df["ms"].iloc[0] < 1e11:
        df["ms"] = df["ms"] * 1000.0
    df = df.sort_values("ms").reset_index(drop=True)
    if "mid" not in df.columns:
        df["mid"] = (df["bid"] + df["ask"]) / 2.0
    df["dt"] = df["ms"].diff()
    df["jump"] = df["mid"].diff()
    return df


def acf(x: np.ndarray, lags: np.ndarray) -> np.ndarray:
    x = x - x.mean()
    n = len(x)
    denom = float((x * x).sum())
    return np.array([float((x[:-k] * x[k:]).sum()) / denom for k in lags])


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load_ticks(TICK_FILE)
    n = len(df)
    span_h = (df["ms"].iloc[-1] - df["ms"].iloc[0]) / 3_600_000.0
    out = {"file": TICK_FILE, "ticks": int(n), "span_hours": round(span_h, 2),
           "generated_utc": datetime.now(timezone.utc).isoformat()}

    # T1 — inter-tick intervals
    dt = df["dt"].dropna()
    dt = dt[dt > 0]
    out["T1_intervals"] = {
        "median_ms": float(dt.median()),
        "p05_ms": float(dt.quantile(0.05)),
        "p95_ms": float(dt.quantile(0.95)),
        "ticks_per_min": round(n / (span_h * 60.0), 1),
        "gaps_over_60s": int((dt > 60_000).sum()),
    }

    # T2 — jump sizes
    j = df["jump"].dropna()
    out["T2_jumps"] = {
        "mean_pts": float(j.mean()),
        "std_pts": float(j.std()),
        "skew": float(j.skew()),
        "kurtosis": float(j.kurt()),
        "p01_abs": float(j.abs().quantile(0.01)),
        "p99_abs": float(j.abs().quantile(0.99)),
        "updown_balance": float((j > 0).mean()),
    }

    # T3 — return autocorrelation at tick level
    r = j.values.astype(float)
    lags = np.arange(1, 101)
    a = acf(r, lags)
    # significance band ~ 1.96/sqrt(N)
    band = 1.96 / np.sqrt(n)
    sig = int((np.abs(a) > band).sum())
    out["T3_tick_acf"] = {
        "lag1": round(float(a[0]), 5),
        "lag2": round(float(a[1]), 5),
        "lag5": round(float(a[4]), 5),
        "lag10": round(float(a[9]), 5),
        "lag50": round(float(a[49]), 5),
        "significant_of_100": sig,
        "band": round(float(band), 5),
        "max_abs": round(float(np.abs(a).max()), 5),
    }

    # T4 — variance ratios at aggregations (VR(q) = Var(r_q) / (q Var(r_1)); ~1 = RW)
    ms = df["ms"].values
    mid = df["mid"].values
    vr = {}
    for label, sec in (("1s", 1), ("5s", 5), ("30s", 30), ("1m", 60),
                       ("5m", 300), ("15m", 900), ("1h", 3600)):
        # resample by bucketing
        step = sec * 1000
        b = (ms // step).astype(np.int64)
        # last price per bucket
        idx = np.unique(b, return_index=True)[1]
        buckets = b[idx]
        # need last tick per bucket — use pandas for clarity
        s = pd.Series(mid, index=b)
        last = s.groupby(level=0).last()
        rr = np.diff(np.log(last.values.astype(float)))
        r1_base = np.diff(np.log(mid.astype(float)))
        q = max(1.0, sec * 1000.0 / float(dt.median()))
        var1 = np.var(r1_base[-500_000:]) if len(r1_base) > 500_000 else np.var(r1_base)
        vr[label] = round(float(np.var(rr) / (q * var1)), 4)
    out["T4_variance_ratio"] = vr

    # T5 — run lengths (same-sign consecutive jumps)
    sign = np.sign(r)
    sign = sign[sign != 0]
    changes = np.where(np.diff(sign) != 0)[0]
    runs = np.diff(np.concatenate(([-1], changes, [len(sign) - 1])))
    counts = np.bincount(runs)
    n_runs = len(runs)
    memless = {k: round(float(counts[k] / n_runs), 4) for k in range(1, 6)}
    # memoryless geometric with p = P(flip) estimated from data
    p_flip = 1.0 - (sign == np.roll(sign, 1))[1:].mean()
    geo = {k: round((1 - p_flip) ** (k - 1) * p_flip, 4) for k in range(1, 6)}
    out["T5_runs"] = {
        "p_flip": round(float(p_flip), 5),
        "obs_dist_1to5": memless,
        "memless_dist_1to5": geo,
        "max_run": int(runs.max()),
        "runs_over_20": int((runs > 20).sum()),
    }

    # T6 — volatility clustering (|r| ACF)
    ar = acf(np.abs(r), np.array([1, 5, 10, 50, 100, 500]))
    out["T6_vol_acf"] = {f"lag{k}": round(float(v), 5) for k, v in zip(
        [1, 5, 10, 50, 100, 500], ar)}

    # T7 — time-of-day vol stability
    hrs = pd.to_datetime(df["ms"], unit="ms", utc=True).dt.hour
    ret_s = pd.Series(np.abs(r), index=hrs.iloc[1:].values)
    by_hour = ret_s.groupby(level=0).mean()
    out["T7_hourly_vol"] = {
        "mean_abs_jump_by_hour": {int(k): round(float(v), 4)
                                  for k, v in by_hour.items()},
        "max_min_ratio": round(float(by_hour.max() / by_hour.min()), 3),
    }

    json.dump(out, open(os.path.join(OUT_DIR, "fingerprint.json"), "w"), indent=1)

    # printed verdicts
    print(f"ticks: {n:,} over {span_h:.1f}h\n")
    print("T1 clock:", out["T1_intervals"])
    print("\nT2 jumps:", out["T2_jumps"])
    print("\nT3 tick ACF:", out["T3_tick_acf"])
    print("   -> ", "MEMORYLESS (no tick-momentum edge)" if out["T3_tick_acf"]["max_abs"] < 3 * band
          else "STRUCTURE FOUND — investigate")
    print("\nT4 variance ratios (>1 momentum, <1 mean-reversion):", vr)
    print("\nT5 runs:", json.dumps(out["T5_runs"], indent=1))
    print("\nT6 vol ACF:", out["T6_vol_acf"])
    print("   -> ", "VOL CLUSTERING PRESENT (vol is forecastable)" if abs(out["T6_vol_acf"]["lag50"]) > 3 * band
          else "no vol memory at tick scale")
    print("\nT7 hourly vol max/min ratio:", out["T7_hourly_vol"]["max_min_ratio"])


if __name__ == "__main__":
    main()
