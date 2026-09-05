"""Critique replication: Tests A & C + drift audit (docs/CRITIQUE_REPLICATION.md).

Registered 2026-09-05 BEFORE execution. One pass; every number reported.

  python scripts/critique_replication.py

Outputs: artifacts/critique_replication/results.json + stdout summary.
"""
from __future__ import annotations

import json
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "critique_replication")
os.makedirs(OUT, exist_ok=True)

Q_GRID = [4, 8, 16, 32, 64, 128, 256]
N_SURR = 500
RNG = np.random.default_rng(20260905)


def vr(q: int, r1: np.ndarray) -> float:
    """Overlapping variance ratio VR(q) = Var(q-step)/(q*Var(1-step))."""
    v1 = np.var(r1, ddof=1)
    if v1 <= 0:
        return float("nan")
    c = np.cumsum(np.insert(r1, 0, 0.0))
    rq = c[q:] - c[:-q]
    return float(np.var(rq, ddof=1) / (q * v1))


def vr_with_band(r1: np.ndarray, q_grid=Q_GRID, n_surr: int = N_SURR):
    obs = {q: vr(q, r1) for q in q_grid}
    bands = {q: [] for q in q_grid}
    for _ in range(n_surr):
        s = r1 * RNG.choice([-1.0, 1.0], size=len(r1))
        for q in q_grid:
            bands[q].append(vr(q, s))
    ci = {q: (float(np.percentile(bands[q], 2.5)), float(np.percentile(bands[q], 97.5)))
          for q in q_grid}
    out = {}
    for q in q_grid:
        lo, hi = ci[q]
        out[q] = {"vr": obs[q], "ci_lo": lo, "ci_hi": hi,
                  "sig": bool(obs[q] < lo or obs[q] > hi)}
    return out


def thirds_split(ts: np.ndarray):
    t33, t66 = np.percentile(ts, [33.333, 66.667])
    return [(ts <= t33), (ts > t33) & (ts <= t66), (ts > t66)]


# ---------------------------------------------------------------- tick lake
tick_files = [
    "artifacts/data/volatility_75_index_ticks_20260707_20260803.csv",
    "artifacts/data/volatility_75_index_ticks_20260803_20260902.csv",
]
tick_files = [f for f in tick_files if os.path.exists(os.path.join(ROOT, f))]
frames = []
for f in tick_files:
    d = pd.read_csv(os.path.join(ROOT, f))
    if "ts" in d.columns:  # July archive: epoch SECONDS, has mid already
        d = d.rename(columns={"ts": "epoch_ms"})
        if d["epoch_ms"].iloc[0] < 1e12:
            d["epoch_ms"] = d["epoch_ms"] * 1000
        d["mid"] = (d["bid"] + d["ask"]) / 2.0 if "mid" not in d.columns else d["mid"]
    else:
        d["mid"] = (d["bid"] + d["ask"]) / 2.0
    frames.append(d)
tk = pd.concat(frames, ignore_index=True).sort_values("epoch_ms").reset_index(drop=True)
tk["mid"] = (tk["bid"] + tk["ask"]) / 2.0
dt_ms = np.diff(tk["epoch_ms"].values)
median_dt = float(np.median(dt_ms))
grid_uniform = float(np.mean(np.abs(dt_ms - median_dt) <= 2000))

logmid = np.log(tk["mid"].values)
r1_tick = np.diff(logmid)
ts_tick = tk["epoch_ms"].values

tick_vr = vr_with_band(r1_tick)
# thirds consistency (pooled surrogate bands per third)
third_res = {}
ts_ret = ts_tick[1:]  # each return i is realized AT tick i+1
for name, mask in zip(("t1", "t2", "t3"), thirds_split(ts_ret)):
    third_res[name] = vr_with_band(r1_tick[mask])

# ------------------------------------------------------------------ H1 bars
def load_h1(path):
    d = pd.read_csv(path)
    d["time"] = pd.to_datetime(d["time"], utc=True, format="ISO8601")
    return d.sort_values("time").reset_index(drop=True)

h1_19m = load_h1(os.path.join(ROOT, "artifacts/z_gate/h1.csv"))
h1_fresh = load_h1(os.path.join(ROOT, "artifacts/v75_replay/h1.csv"))

h1_19m_vr = vr_with_band(np.diff(np.log(h1_19m["close"].values)))
h1_fresh_vr = vr_with_band(np.diff(np.log(h1_fresh["close"].values)))

# ------------------------------------------------- Test C: EA regime mirror
def wilder_atr(d: pd.DataFrame, period: int = 14) -> np.ndarray:
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    pc = np.insert(c[:-1], 0, c[0])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().values


def ema(x: np.ndarray, period: int) -> np.ndarray:
    return pd.Series(x).ewm(alpha=2.0 / (period + 1), adjust=False).mean().values


def classify_ea(d: pd.DataFrame) -> np.ndarray:
    """Exact mirror of EA ClassifyRegime() (H1, evaluated on each closed bar)."""
    c = d["close"].values
    ef, em, es = ema(c, 20), ema(c, 50), ema(c, 100)
    atr = wilder_atr(d)
    # ATR trailing percentile, 120-bar window incl. current, strict-greater count
    pct = np.full(len(c), 50.0)
    for i in range(len(c)):
        if i < 39:
            pct[i] = 50.0          # EA: fewer than 40 samples -> default 50
            continue
        lo = max(0, i - 119)
        w = atr[lo:i + 1]
        pct[i] = 100.0 * np.count_nonzero(atr[i] > w) / len(w)
    sep = np.abs(ef - em) / atr
    reg = np.full(len(c), 3)  # 3=RANGING
    reg[pct > 90.0] = 4       # 4=HIGH_VOL
    reg[pct < 8.0] = 0        # 0=NO_TRADE
    bull = (ef > em) & (em > es) & (c > ef) & (sep >= 0.22) & (reg == 3)
    bear = (ef < em) & (em < es) & (c < ef) & (sep >= 0.22) & (reg == 3)
    reg[bull] = 1
    reg[bear] = 2
    return reg


RNAMES = {0: "NO_TRADE", 1: "BULLISH", 2: "BEARISH", 3: "RANGING", 4: "HIGH_VOL"}


def test_c(d: pd.DataFrame, label: str):
    reg = classify_ea(d)
    c = d["close"].values
    atr = wilder_atr(d)
    res = {}
    for horizon in (4, 8):
        fwd = np.full(len(c), np.nan)
        fwd[:-horizon] = c[horizon:] - c[:-horizon]
        rows = {}
        for r in (0, 1, 2, 3, 4):
            m = (reg == r) & ~np.isnan(fwd)
            n = int(m.sum())
            if n < 30:
                rows[RNAMES[r]] = {"n": n}
                continue
            x = fwd[m]
            t = x.mean() / (x.std(ddof=1) / np.sqrt(n))
            # ATR-normalized drift + atr terciles within regime
            an = (x / atr[m]).mean()
            qs = np.quantile(atr[m], [1 / 3, 2 / 3])
            terc = {}
            for tname, tmask in (("lo", atr[m] <= qs[0]),
                                 ("mid", (atr[m] > qs[0]) & (atr[m] <= qs[1])),
                                 ("hi", atr[m] > qs[1])):
                xv = x[tmask]
                terc[tname] = {"mean": float(xv.mean()),
                               "t": float(xv.mean() / (xv.std(ddof=1) / np.sqrt(len(xv))))}
            rows[RNAMES[r]] = {"n": n, "mean_pts": float(x.mean()),
                               "t": float(t), "atr_norm": float(an),
                               "terciles": terc}
        res[f"h{horizon}"] = rows
    return {label: res}


test_c_19m = test_c(h1_19m, "era_19m_2024-07_2026-02")
test_c_fresh = test_c(h1_fresh, "era_fresh_2026-07_2026-09")

# -------------------------------------------------------------- drift audit
def drift_audit(d: pd.DataFrame, label: str):
    c = d["close"].values
    yrs = (d["time"].iloc[-1] - d["time"].iloc[0]).total_seconds() / (365.25 * 24 * 3600)
    tot_ret = c[-1] / c[0] - 1.0
    log_drift_h = np.diff(np.log(c)).mean()
    ann = log_drift_h * 24 * 365.25
    r1 = np.diff(np.log(c))
    t = r1.mean() / (r1.std(ddof=1) / np.sqrt(len(r1)))
    return {"label": label, "start": str(d["time"].iloc[0]), "end": str(d["time"].iloc[-1]),
            "p0": float(c[0]), "p1": float(c[-1]), "total_return_pct": float(tot_ret * 100),
            "ann_log_drift_pct": float(ann * 100), "hourly_t": float(t), "years": yrs}


da_19m = drift_audit(h1_19m, "19m")
da_fresh = drift_audit(h1_fresh, "fresh")

results = {
    "tick_grid": {"n_ticks": int(len(tk)), "files": tick_files,
                  "median_dt_ms": median_dt, "uniform_frac": grid_uniform,
                  "span": [str(pd.to_datetime(ts_tick[0], unit="ms")),
                           str(pd.to_datetime(ts_tick[-1], unit="ms"))]},
    "TEST_A_tick": tick_vr,
    "TEST_A_tick_thirds": third_res,
    "TEST_A_h1_19m": h1_19m_vr,
    "TEST_A_h1_fresh": h1_fresh_vr,
    "TEST_C": {**test_c_19m, **test_c_fresh},
    "DRIFT_AUDIT": {"era_19m": da_19m, "era_fresh": da_fresh},
}
with open(os.path.join(OUT, "results.json"), "w") as f:
    json.dump(results, f, indent=1)

# ------------------------------------------------------------------ summary
print(f"tick lake: {len(tk):,} ticks, median dt {median_dt:.0f}ms, uniform {grid_uniform:.4f}")
print("\nTEST A - variance ratios (surrogate 95% CI)")
for lbl, res in (("tick(2s)", tick_vr), ("H1 19m", h1_19m_vr), ("H1 fresh", h1_fresh_vr)):
    sigs = [f"q={q}:{'SIG' if v['sig'] else '.'}" for q, v in res.items()]
    print(f"  {lbl:9s} " + "  ".join(f"q={q}: {v['vr']:.3f} [{v['ci_lo']:.3f},{v['ci_hi']:.3f}]"
          for q, v in res.items()))
print("\nTEST A - tick thirds consistency:")
for name, res in third_res.items():
    sig_qs = [q for q, v in res.items() if v["sig"]]
    dirs = {("trend" if res[q]["vr"] > 1 else "rev") for q in sig_qs}
    print(f"  {name}: significant at q={sig_qs} dirs={dirs or '-'}")
print("\nTEST C - forward drift by EA regime (points, t-stat):")
for era, hor in test_c_19m.items():
    for hz, rows in hor.items():
        line = "  ".join(f"{k}:n={v['n']},t={v.get('t', float('nan')):.2f}" if v.get("t") is not None
                         else f"{k}:n={v['n']}" for k, v in rows.items())
        print(f"  [{era} {hz}] {line}")
print("\nDRIFT AUDIT:")
for k, v in results["DRIFT_AUDIT"].items():
    print(f"  {v['label']}: {v['p0']:.0f} -> {v['p1']:.0f} ({v['total_return_pct']:+.1f}%), "
          f"ann drift {v['ann_log_drift_pct']:+.2f}%/yr, hourly t={v['hourly_t']:.2f}")
print("\nsaved ->", os.path.join(OUT, "results.json"))
