#!/usr/bin/env python3
"""Cross-validate the MQL5 Phase-2 RegimeEngine against the Python
RegimeShiftDetector (HMM + CUSUM) on REAL R_75 closes from the tick corpus.

The two engines classify different axes:
  - MQL5 RegimeEngine (mql5/MITEMSHUB_AI/Regime/): directional/structure
    regime (TREND_UP/DOWN, RANGE, COMPRESSION, EXPANSION, TRANSITION) on a
    200-bar window, fed ATR percentile + ATR ratio from the VolatilityEngine.
  - Python RegimeShiftDetector (src/synthetic_trader/models/regime_detector.py):
    streaming 3-state volatility HMM (LOW/NORMAL/HIGH) + CUSUM structural-break
    alerts on per-bar log returns.

This harness maps the MQL5 labels onto the volatility axis and measures
agreement, then prints the disagreements with context so they can be
reconciled before Phase 3 builds on the regime layer.

The MQL5-side math comes from the phase2_logic_check.py mirror (exec'd from
its definitions section, so it stays in lockstep with the MQL5 code).
"""

import csv
import math
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

# --- load the mirror's definitions WITHOUT running its test block ------------
# phase2_logic_check.py runs its Phase-2 assertions at module level, so exec
# only the definitions portion (everything before the TESTS marker).
_MIRROR_SRC = open(os.path.join(_HERE, "phase2_logic_check.py"), encoding="utf-8").read()
_MIRROR_NS: dict = {}
exec(_MIRROR_SRC.split("# ============================ TESTS")[0], _MIRROR_NS)
mql5_classify = _MIRROR_NS["classify"]

# --- Python side -------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from synthetic_trader.models.regime_detector import RegimeShiftDetector  # noqa: E402

# --- config (mirrors MITEMSHUB_AI Core/Config.mqh defaults) ------------------
ATR_PERIOD = 14          # DEFAULT_ATR_PERIOD
REGIME_LOOKBACK = 200    # DEFAULT_REGIME_LOOKBACK
ATR_WINDOW = 100         # percentile/ratio reference window
TF = 300                 # M5 — the execution timeframe the engine runs on
STEP = 5                 # window slide (bars)
HMM_WARMUP = 400         # skip comparisons until the HMM has adapted

CORPUS_PATHS = [
    os.path.join(_HERE, "..", "data", "backfill", "R_75_ticks.csv"),
    os.path.join(_HERE, "..", "data", "R_75_ticks.csv"),
]


# --- MQL5 VolatilityEngine replication (Wilder ATR + percentile + ratio) -----
def wilder_atr_series(hlc):
    """hlc: list of (high, low, close). Returns one Wilder ATR per bar."""
    atrs = []
    atr = None
    prev_close = 0.0
    for high, low, close in hlc:
        tr = high - low
        if prev_close > 0.0:
            tr = max(tr, abs(high - prev_close), abs(low - prev_close))
        if atr is None:
            atr = tr
        else:
            atr = (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        atrs.append(atr)
        prev_close = close
    return atrs


def atr_percentile(atrs, i, window=ATR_WINDOW):
    win = atrs[max(0, i - window + 1): i + 1]
    if len(win) < 2:
        return 0.5
    cur = atrs[i]
    return sum(1 for a in win if a < cur) / len(win)


def atr_ratio(atrs, i, window=ATR_WINDOW):
    win = atrs[max(0, i - window + 1): i + 1]
    if len(win) < 2:
        return 1.0
    mean = sum(win) / len(win)
    return atrs[i] / mean if mean > 0.0 else 1.0


# --- corpus -> M5 bars --------------------------------------------------------
def load_m5_bars(paths):
    ticks = []
    seen = set()
    for p in paths:
        if not os.path.exists(p):
            print(f"  (missing corpus: {p})", file=sys.stderr)
            continue
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            prev = None
            for row in reader:
                try:
                    epoch = float(row[0])
                    price = float(row[2])
                except (ValueError, IndexError):
                    continue
                if not (100.0 <= price <= 5000.0):
                    continue  # clip venue junk (Deriv-scale leaks etc.)
                if prev is not None and abs(price - prev) / prev > 0.30:
                    continue  # single-tick jump ~3.7x is corrupted data
                k = round(epoch, 6)
                if k in seen:
                    continue
                seen.add(k)
                ticks.append((epoch, price))
                prev = price
    ticks.sort(key=lambda t: t[0])
    bars = []  # (bucket, open, high, low, close)
    for epoch, price in ticks:
        bucket = int(epoch // TF)
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            bars[-1] = (bucket, b[1], max(b[2], price), min(b[3], price), price)
        else:
            bars.append((bucket, price, price, price, price))
    return bars


# --- label mapping ------------------------------------------------------------
# MQL5 labels -> volatility bucket (the axis the Python HMM measures).
_MQL5_TO_VOL = {
    "COMPRESSION": "LOW",
    "RANGE": "NORMAL",
    "TREND_UP": "NORMAL",
    "TREND_DOWN": "NORMAL",
    "EXPANSION": "HIGH",
}


def mql5_vol_bucket(label, ratio):
    if label == "TRANSITION":
        # a transition towards higher vol (ATR ratio rising) is a HIGH call,
        # towards lower vol a LOW call; ambiguous stays NORMAL.
        if ratio > 1.05:
            return "HIGH"
        if ratio < 0.95:
            return "LOW"
        return "NORMAL"
    return _MQL5_TO_VOL[label]


_PY_TO_VOL = {0: "LOW", 1: "NORMAL", 2: "HIGH"}  # MarketState.LOW/NORMAL/HIGH


def main():
    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    if len(bars) < REGIME_LOOKBACK + HMM_WARMUP:
        print(f"not enough bars ({len(bars)})", file=sys.stderr)
        return 1
    closes = [b[4] for b in bars]
    hlc = [(b[2], b[3], b[4]) for b in bars]
    atrs = wilder_atr_series(hlc)
    span_h = len(bars) * TF / 3600.0
    print(f"bars={len(bars)}  ({span_h:.1f} hours of M5)  "
          f"close range {min(closes):.2f}..{max(closes):.2f}")

    # --- stream the Python detector once; record state + CUSUM alerts --------
    det = RegimeShiftDetector()
    py_states = []        # per bar index i (after feeding bar i's return)
    cusum_alert_bars = [] # bar indices where a cusum_shift fired
    for i in range(1, len(closes)):
        lr = math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0.0 else 0.0
        state, _scale, alerts = det.update(lr)
        py_states.append(int(state))
        for a in alerts:
            if a.alert_type == "cusum_shift":
                cusum_alert_bars.append(i)

    # --- classify every window with both engines ------------------------------
    rows = []  # (bar_i, mql5_label, py_bucket, mql5_bucket, atr_pct, atr_ratio, price)
    for i in range(REGIME_LOOKBACK, len(closes), STEP):
        if i < HMM_WARMUP:
            continue
        win = closes[i - REGIME_LOOKBACK + 1: i + 1]
        ap = atr_percentile(atrs, i)
        ar = atr_ratio(atrs, i)
        mql5_label = mql5_classify(win, ap, ar)[0]
        py_bucket = _PY_TO_VOL[py_states[i - 1]]
        mql5_bucket = mql5_vol_bucket(mql5_label, ar)
        rows.append((i, mql5_label, py_bucket, mql5_bucket, ap, ar, closes[i]))

    n = len(rows)
    agree = sum(1 for r in rows if r[2] == r[3])
    print(f"\nwindows compared: {n}   vol-bucket agreement: {agree} / {n} "
          f"({100.0 * agree / n:.1f}%)")

    # --- confusion: MQL5 label x Python bucket --------------------------------
    print("\n=== confusion (MQL5 label x Python vol bucket), counts ===")
    labels = ["TREND_UP", "TREND_DOWN", "RANGE", "COMPRESSION", "EXPANSION", "TRANSITION"]
    hdr = "label        " + "".join(f"{b:>8}" for b in ("LOW", "NORMAL", "HIGH")) + "   total"
    print(hdr)
    conf = Counter((r[1], r[2]) for r in rows)
    per_label_total = Counter(r[1] for r in rows)
    for lab in labels:
        c = conf.get((lab, "LOW"), 0), conf.get((lab, "NORMAL"), 0), conf.get((lab, "HIGH"), 0)
        print(f"{lab:<12}" + "".join(f"{x:>8}" for x in c) + f"   {per_label_total[lab]:>5}")

    # --- per-label agreement on the vol bucket --------------------------------
    print("\n=== per-MQL5-label vol-bucket agreement ===")
    for lab in labels:
        tot = per_label_total[lab]
        if tot == 0:
            continue
        ok = sum(1 for r in rows if r[1] == lab and r[2] == r[3])
        print(f"{lab:<12} {ok:>4}/{tot:<5} ({100.0 * ok / tot:5.1f}%)")

    # --- TRANSITION vs CUSUM --------------------------------------------------
    trans_rows = [r for r in rows if r[1] == "TRANSITION"]
    if trans_rows:
        recent_cusum = sum(
            1 for r in trans_rows
            if any(b >= r[0] - 30 and b <= r[0] for b in cusum_alert_bars)
        )
        print(f"\n=== TRANSITION vs CUSUM (structural break) ===")
        print(f"MQL5 TRANSITION windows: {len(trans_rows)}; "
              f"with a Python CUSUM alert in the prior 30 bars: {recent_cusum} "
              f"({100.0 * recent_cusum / len(trans_rows):.0f}%)")
    py_cusum_total = len(cusum_alert_bars)
    print(f"total Python CUSUM alerts over the corpus: {py_cusum_total}")

    # --- disagreement samples with context ------------------------------------
    print("\n=== first 18 disagreements (bar, time, price, ATR%, ratio, MQL5 -> py) ===")
    shown = 0
    for r in rows:
        if r[2] != r[3]:
            hour = r[0] * TF / 3600.0
            print(f"  bar {r[0]:>5} (t+{hour:7.1f}h) px {r[6]:8.2f} atr% {r[4]:.2f} "
                  f"ratio {r[5]:.2f}  {r[1]:<12} -> py {r[2]}")
            shown += 1
            if shown >= 18:
                break

    # --- summary line for the reconciliation -----------------------------------
    print("\n=== reconciliation summary ===")
    for lab in labels:
        tot = per_label_total[lab]
        if tot == 0:
            continue
        ok = sum(1 for r in rows if r[1] == lab and r[2] == r[3])
        dominant_py = max(("LOW", "NORMAL", "HIGH"),
                          key=lambda b: conf.get((lab, b), 0))
        print(f"{lab:<12} agree {100.0 * ok / tot:5.1f}%  "
              f"dominant python bucket: {dominant_py}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
