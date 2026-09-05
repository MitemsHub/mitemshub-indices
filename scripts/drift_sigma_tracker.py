"""Drift-vs-Sigma tracker — validation harness (protocol: docs/DRIFT_SIGMA_TRACKER.md).

Estimates, strictly causally, on the 2s step stream:
  sigma2(t) = EWMA std of 2s log-returns over the trailing hour (N=1800 steps)
  mu2(t)    = EWMA mean of the same window
  score(t)  = mu2(t) / sigma2(t)          (signed, dimensionless)

Pre-registered tests:
  K3  tick-EWMA sigma (hourly aggregate) vs incumbent M15 ATR(14): next-hour
      realized-vol forecast RMSE + MAE (~1350 pairs)
  K1  does |score| at hour start predict the signed drift of the NEXT hour?
      quintile monotonicity + aligned-spread t-stat over daily blocks
  K2  gating the certified TP-1.8 engine by conviction: fold-paired deltas,
      base arm must reproduce +13.23R/135 exactly

Run: python scripts/drift_sigma_tracker.py
Artifacts: artifacts/drift_sigma/*.json
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from certify_v75 import certify  # noqa: E402

OUT_DIR = "artifacts/drift_sigma"
TICK_FILES = [
    "artifacts/data/volatility_75_index_ticks_20260707_20260803.csv",
    "artifacts/data/volatility_75_index_ticks_20260803_20260902.csv",
]
N_WINDOW = 1800          # trailing 1h of 2s steps (frozen)
LAMBDA = 2.0 / (N_WINDOW + 1)   # EWMA weight matching the frozen window


def load_steps() -> pd.DataFrame:
    """Concatenate tick archives -> DataFrame[ms, mid]; 2s grid."""
    frames = []
    for f in TICK_FILES:
        d = pd.read_csv(f)
        d.columns = [c.strip().lower() for c in d.columns]
        tcol = "epoch_ms" if "epoch_ms" in d.columns else d.columns[0]
        d = d.rename(columns={tcol: "ms"})
        if d["ms"].iloc[0] < 1e11:
            d["ms"] = d["ms"] * 1000.0
        if "mid" not in d.columns:
            d["mid"] = (d["bid"] + d["ask"]) / 2.0
        frames.append(d[["ms", "mid"]])
    df = pd.concat(frames).sort_values("ms").reset_index(drop=True)
    # drop dup timestamps (seam between archives), keep last
    df = df.drop_duplicates(subset="ms", keep="last").reset_index(drop=True)
    return df


def ewma_run(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Causal EWMA mean/std over the full step series (init: first N steps)."""
    mean = np.zeros(len(x))
    var = np.zeros(len(x))
    m, v = x[0], x[:N_WINDOW].var()
    mean[:N_WINDOW] = m
    var[:N_WINDOW] = v
    for i in range(N_WINDOW, len(x)):
        m = m + LAMBDA * (x[i] - m)
        v = v + LAMBDA * ((x[i] - m) ** 2 - v)
        mean[i] = m
        var[i] = v
    std = np.sqrt(np.maximum(var, 1e-18))
    return mean, std


def hourly_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per-hour: score at hour START (causal) + realized next-hour drift/vol."""
    ms = df["ms"].values
    mid = df["mid"].values.astype(float)
    step = np.diff(np.log(mid))
    tstep = ms[1:]

    mean, std = ewma_run(step)

    hour_id = (tstep // 3_600_000).astype(np.int64)
    # first index of each hour: the tracker state available AT that moment
    firsts = np.unique(hour_id, return_index=True)[1]
    order = np.argsort(firsts)
    firsts = firsts[order]
    hours = hour_id[firsts]

    # realized next-hour drift & vol (steps in [first, first+N_WINDOW))
    drift_next = np.full(len(firsts), np.nan)
    vol_next = np.full(len(firsts), np.nan)
    for k, f in enumerate(firsts):
        seg = step[f:f + N_WINDOW]
        if len(seg) >= N_WINDOW // 2:
            drift_next[k] = seg.mean()
            vol_next[k] = seg.std()

    score = np.where(std[firsts] > 0, mean[firsts] / std[firsts], 0.0)
    return pd.DataFrame({
        "hour": hours,
        "score": score,
        "mu2": mean[firsts],
        "sigma2": std[firsts],
        "drift_next": drift_next,
        "vol_next": vol_next,
        "t_ms": tstep[firsts],
    })


# ---------------------------------------------------------------- K3
def k3(hf: pd.DataFrame, df: pd.DataFrame) -> dict:
    """Incumbent: M15 ATR(14) known at hour start (from last CLOSED bar).
    Challenger: EWMA sigma aggregated to a per-hour vol proxy:
        sigma_h(t) = sigma2(t) * sqrt(1800)  (per-hour sigma in log terms)."""
    sys.path.insert(0, HERE)
    from certify_v75 import load
    m15 = load("m15.csv")
    closes = [b["c"] for b in m15]
    from certify_v75 import wilder_atr
    atr = wilder_atr(m15, 14)
    m15_t = [b["t"] for b in m15]
    atr_series = pd.Series(atr, index=pd.to_datetime([m["t"] for m in m15]))

    ts = pd.to_datetime(hf["t_ms"], unit="ms", utc=True)
    # ATR of the last CLOSED M15 bar at each hour start: reindex 1ms BEFORE the
    # boundary so ffill lands on the bar that OPENED before it (a bar opening
    # exactly at the boundary is still forming and must not be used).
    atr_at = atr_series.reindex(atr_series.index.union(ts - pd.Timedelta("1ms"))).ffill().reindex(ts)

    # realized next-hour vol, both in comparable fractional terms
    real = hf["vol_next"].values * math.sqrt(N_WINDOW)   # per-hour log sigma
    # convert ATR (price units) to fraction of price
    price_at = df["mid"].values[np.searchsorted(df["ms"].values, hf["t_ms"].values)]
    atr_frac = atr_at.values / price_at
    chall = hf["sigma2"].values * math.sqrt(N_WINDOW)

    ok = ~(np.isnan(real) | np.isnan(atr_frac) | np.isnan(chall))
    real, atr_frac, chall = real[ok], atr_frac[ok], chall[ok]
    rmse_atr = float(np.sqrt(np.mean((atr_frac - real) ** 2)))
    rmse_ch = float(np.sqrt(np.mean((chall - real) ** 2)))
    mae_atr = float(np.mean(np.abs(atr_frac - real)))
    mae_ch = float(np.mean(np.abs(chall - real)))
    return {"n_hours": int(ok.sum()),
            "rmse_atr": round(rmse_atr, 6), "rmse_ewma": round(rmse_ch, 6),
            "mae_atr": round(mae_atr, 6), "mae_ewma": round(mae_ch, 6),
            "challenger_wins_rmse": bool(rmse_ch < rmse_atr),
            "challenger_wins_mae": bool(mae_ch < mae_atr),
            "k3_pass": bool(rmse_ch < rmse_atr and mae_ch < mae_atr)}


# ---------------------------------------------------------------- K1
def k1(hf: pd.DataFrame) -> dict:
    d = hf.dropna(subset=["drift_next"]).copy()
    d["aligned"] = d["drift_next"] * np.sign(d["score"])
    d["abscore"] = d["score"].abs()
    d["q"] = pd.qcut(d["abscore"], 5, labels=False, duplicates="drop")
    qmeans = d.groupby("q")["aligned"].mean()
    mono = bool(np.all(np.diff(qmeans.values) > 0))
    # daily blocks: paired spread topQ-bottomQ
    d["day"] = pd.to_datetime(d["t_ms"], unit="ms", utc=True).dt.date
    spreads = []
    for day, g in d.groupby("day"):
        if g["q"].nunique() < 5:
            continue
        top = g[g["q"] == 4]["aligned"].mean()
        bot = g[g["q"] == 0]["aligned"].mean()
        spreads.append(top - bot)
    arr = np.array(spreads)
    t = float(arr.mean() / (arr.std(ddof=1) / math.sqrt(len(arr)))) if len(arr) > 2 else 0.0
    # rank correlation |score| vs aligned drift (pandas impl — no scipy dep)
    rho = d["abscore"].corr(d["aligned"], method="spearman")
    return {"n_hours": len(d), "n_days": len(spreads),
            "quintile_means": [round(float(x), 5) for x in qmeans.values],
            "monotone": mono,
            "daily_spread_mean": round(float(arr.mean()), 5) if len(arr) else None,
            "daily_spread_t": round(t, 3),
            "spearman": round(float(rho), 4),
            "k1_pass": bool(mono and t >= 2.0)}


# ---------------------------------------------------------------- K2
def k2(hf: pd.DataFrame) -> dict:
    # conviction percentile per hour, trailing 30d (causal)
    hf = hf.sort_values("t_ms").reset_index(drop=True)
    conv = np.full(len(hf), np.nan)
    abscore = hf["score"].abs().values
    for i in range(len(hf)):
        lo = np.searchsorted(hf["t_ms"].values, hf["t_ms"].values[i] - 30 * 86_400_000)
        hist = abscore[lo:i]
        if len(hist) > 100:
            conv[i] = (hist < abscore[i]).mean()
    hf["conv"] = conv

    # hour -> score lookup for signal timestamps
    hour_map = {int(h): (s, c) for h, s, c in zip(hf["hour"], hf["score"], hf["conv"])}

    base = certify(50.0, tp_mult=1.8)
    trades = base["trades"]
    med = np.nanmedian(conv)
    # align each trade to the hour containing its SIGNAL time (entry decided at bar open)
    taken_g, taken_b = [], []
    for t in trades:
        import pandas as _pd
        sig_ms = int(_pd.Timestamp(t["sig_t"]).timestamp() * 1000)
        h = sig_ms // 3_600_000
        _, c = hour_map.get(h, (0.0, np.nan))
        gate = (not math.isnan(c)) and c >= med and abs(hour_map[h][0]) > 0
        (taken_g if gate else taken_b).append(t)

    def tot(ts):
        return round(sum(t["r"] for t in ts), 2)

    from certify_v75 import load
    m15 = load("m15.csv")
    t0, t1 = m15[480]["t"], m15[-1]["t"]
    span = t1 - t0
    deltas = []
    for i in range(8):
        fs = t0 + i * span / 8
        fe = t0 + (i + 1) * span / 8 if i < 7 else t1
        gb = [t for t in taken_g if fs <= _pd.Timestamp(t["t"]) < fe]
        bb = [t for t in taken_b if fs <= _pd.Timestamp(t["t"]) < fe]
        deltas.append(round(tot(gb) - tot(bb), 2))

    def tstat(rs):
        m = len(rs); mean = sum(rs) / m
        var = sum((x - mean) ** 2 for x in rs) / (m - 1) if m > 1 else 0
        return mean / (var ** 0.5 / m ** 0.5) if var > 0 else 0.0

    D = round(tot(taken_g) - tot(taken_b), 2)
    worst = min(deltas)
    t = round(tstat(deltas), 3)
    return {"base_check": {"total_r": base["total_r"], "n": base["n"]},
            "gated": {"total_r": tot(taken_g), "n": len(taken_g)},
            "blocked": {"total_r": tot(taken_b), "n": len(taken_b)},
            "median_conv": round(float(med), 4),
            "D": D, "fold_deltas": deltas, "t": t, "worst_fold": worst,
            "k2_pass": bool(D >= 1.5 and t >= 1.0 and worst >= -1.0)}


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load_steps()
    print(f"steps: {len(df):,}  span {(df['ms'].iloc[-1]-df['ms'].iloc[0])/3.6e6:.1f} h")
    hf = hourly_frame(df)
    hf.to_csv(os.path.join(OUT_DIR, "hourly_tracker.csv"), index=False)

    k3r = k3(hf, df)
    k1r = k1(hf)
    k2r = k2(hf)

    out = {"K1": k1r, "K2": k2r, "K3": k3r}
    passed = sum([k1r["k1_pass"], k2r["k2_pass"], k3r["k3_pass"]])
    out["verdict"] = ("ADOPT-EA-INTEGRATION (all three)" if passed == 3 else
                      f"KEEP-COLLECTING ({passed}/3 — two of three required to continue)" if passed == 2 else
                      f"CLOSED ({passed}/3)")
    json.dump(out, open(os.path.join(OUT_DIR, "tracker_validation.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
