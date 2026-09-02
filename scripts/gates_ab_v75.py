#!/usr/bin/env python3
"""Four-arm A/B: how would the v26.23 governor gates have changed the last
30 days of V75 trading on a $30 compounding account?

Arms (identical engine otherwise — 0.5% risk, lot floor, x0.75 loss scaling,
3-loss daily pause, win-rearm (no cooldown after wins, 3-bar cooldown after
losses), worst-case fills, per-bar spread, SL 1.7xATR + swing widen, TP 2.0x,
hold 20):
  A base        : no gates (pre-v26.23 behavior)
  B spread      : + spread gate (refuse entry when spread > 18% of stop)
  C conviction  : + conviction throttle (MinScore 3->4 while day net-negative)
  D both        : both gates

Autopsy: every signal an arm REFUSES is shadow-simulated to its own
completion (independent R) so the report can say exactly what the gate
skipped and what it would have done. Shadow trades share no state with the
arm (no cooldown/pause/sizing feedback) — they are the honest "what did the
gate skip" counterfactual.

Conviction throttle needs per-bar scores: the full 5-leg scoring pipeline is
recomputed here and ASSERTED to agree with the reference engine's direction
on every bar.
Writes artifacts/gates_ab_v75.json
"""
from __future__ import annotations

import csv
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
CSV_BARS = ART / "data" / "volatility_75_index_m15_40000bars.csv"
POINT = 0.01
TICK, TV = 0.01, 0.0001
EQUITY0 = 30.0
RISK = 0.005
SL_MULT, TP_MULT, HOLD = 1.7, 2.0, 20
SPREAD_GATE = 0.18
MIN_SCORE = 3
SCALE_F, SCALE_MIN = 0.75, 0.30
COOLDOWN_BARS = 3          # InpCoolDownBars (VOL75_FINAL) — losses only
DAYS = 30

spec = importlib.util.spec_from_file_location(
    "fwd_split_backtest", ROOT / "scripts" / "fwd_split_backtest.py")
fsb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fsb)


def load_bars():
    with open(CSV_BARS, newline="") as f:
        rd = csv.reader(f)
        col = {k: i for i, k in enumerate(next(rd))}
        data = list(rd)
    o, h, l, c = (np.array([float(r[col[k]]) for r in data])
                  for k in ("open", "high", "low", "close"))
    ts = np.array([int(float(r[col["ts"]])) for r in data], dtype=np.int64)
    spread = np.array([float(r[col["spread"]]) for r in data]) * POINT
    return o, h, l, c, ts, spread


def scores_pipeline(o, h, l, c, sig_ref):
    """Full buy/sell score recompute (EA-faithful), asserted vs reference dir."""
    n = len(c)
    e20, e50 = fsb.ema(c, 20), fsb.ema(c, 50)
    sig, a, reg = fsb.signals(o, h, l, c)
    w = 20
    roll_mean = np.convolve(c, np.ones(w) / w, mode="valid")
    roll_std = np.array([c[k - w + 1:k + 1].std() for k in range(w - 1, n)])
    z = np.concatenate((np.zeros(w - 1), (c[w - 1:] - roll_mean) / np.maximum(roll_std, 1e-12)))
    z = np.concatenate((np.zeros(1), z))[:-1]

    bs = np.zeros(n)
    ss = np.zeros(n)
    mism = 0
    for i in range(fsb.EMA_S + 2, n - 1):
        if reg[i] == 3 or not (a[i] > 0):
            continue
        lb, ls, sb, ssc = [], [], 0.0, 0.0
        mom = e20[i] - e20[i - 2]
        if abs(mom) > 0.25 * a[i]:
            if mom > 0:
                lb.append("MOM"); sb += 2.2
            else:
                ls.append("MOM"); ssc += 2.2
        if reg[i] == 1 and l[i] <= e20[i] * 1.0005 and c[i] > e50[i]:
            lb.append("PB"); sb += 2.5
        if reg[i] == 2 and h[i] >= e20[i] * 0.9995 and c[i] < e50[i]:
            ls.append("PB"); ssc += 2.5
        if abs(c[i] - e50[i]) > 2.0 * a[i]:
            if c[i] < e50[i]:
                lb.append("MR"); sb += 2.0
            else:
                ls.append("MR"); ssc += 2.0
        if z[i] <= -fsb.Z_ENTRY:
            lb.append("BF"); sb += 4.2
        if z[i] >= fsb.Z_ENTRY:
            ls.append("BF"); ssc += 4.2
        if lb == ["MOM"]:
            lb, sb = [], 0.0
        if ls == ["MOM"]:
            ls, ssc = [], 0.0
        if reg[i] == 1:
            sb += fsb.REGIME_BONUS
        if reg[i] == 2:
            ssc += fsb.REGIME_BONUS
        bs[i], ss[i] = sb, ssc
        d = 0
        if len(lb) >= 2 and sb >= MIN_SCORE and sb > ssc:
            d = 1
        elif len(ls) >= 2 and ssc >= MIN_SCORE and ssc > sb:
            d = -1
        if d != int(sig_ref[i]):
            mism += 1
    assert mism == 0, f"score pipeline disagrees with engine on {mism} bars"
    return bs, ss, a, reg, z


def geom_at(i, d, o, h, l, c, a):
    stop_d = SL_MULT * a[i]
    if d > 0:
        lo = l[max(0, i - 5):i].min()
        stop_d = max(stop_d, o[i + 1] - (lo - 0.15 * a[i]))
    else:
        hi = h[max(0, i - 5):i].max()
        stop_d = max(stop_d, (hi + 0.15 * a[i]) - o[i + 1])
    stop_d = max(stop_d, 0.5 * a[i])
    stop_d = min(stop_d, c[i] * 0.03)
    return stop_d, TP_MULT * stop_d


def shadow_r(i, d, o, h, l, c, a, spread):
    """Independent R of the trade the signal would have taken (no state shared)."""
    stop_d, tp_d = geom_at(i, d, o, h, l, c, a)
    sp = spread[i + 1]
    if d > 0:
        entry = o[i + 1] + sp / 2.0
        sl, tp = entry - stop_d, entry + tp_d
    else:
        entry = o[i + 1] - sp / 2.0
        sl, tp = entry + stop_d, entry - tp_d
    r = None
    j_end = min(i + 1 + HOLD, len(c))
    for j in range(i + 1, j_end):
        if d > 0:
            if l[j] <= sl:
                r = -1.0; break
            if h[j] >= tp:
                r = TP_MULT; break
        else:
            if h[j] >= sl:
                r = -1.0; break
            if l[j] <= tp:
                r = TP_MULT; break
    if r is None:
        j = j_end - 1
        r = d * (c[j] - (sp / 2.0) * d - entry) / stop_d
    return r - sp / stop_d


def run_engine(name, o, h, l, c, ts, spread, bs, ss, a, use_spread, use_conv, days=None):
    n = len(c)
    d_window = DAYS if days is None else days
    start = 110 if d_window == 0 else n - d_window * 96 - 2   # 0 = full history
    equity, consec = EQUITY0, 0
    day, daily_pnl = -1, 0.0
    paused_day = -1
    cooldown_until = -1          # bar index until which entries are blocked
    peak, maxdd = EQUITY0, 0.0
    trades, shadows = [], []
    throttle_bars = 0
    i = start
    while i < n - 2:
        t = int(ts[i])
        d_today = t // 86400
        if d_today != day:
            day, daily_pnl = d_today, 0.0
        # firing decision (flat only — occupancy enforced by skipping to close)
        d, score_used = 0, None
        if paused_day != d_today and i > cooldown_until:
            throttled = use_conv and daily_pnl < 0
            min_eff = MIN_SCORE + (1 if throttled else 0)
            if throttled:
                throttle_bars += 1
            if bs[i] >= MIN_SCORE and bs[i] > ss[i]:
                d, score_used = 1, bs[i]
            elif ss[i] >= MIN_SCORE and ss[i] > bs[i]:
                d, score_used = -1, ss[i]
            # v26.23 conviction throttle: signal passes the base bar but not
            # the raised bar -> REFUSED; shadow it before it can fire
            if d != 0 and throttled and score_used < min_eff:
                stop_d0, _ = geom_at(i, d, o, h, l, c, a)
                shadows.append((t, shadow_r(i, d, o, h, l, c, a, spread), "conviction",
                                float(score_used), spread[i + 1] / stop_d0))
                d = 0
        if d == 0:
            i += 1
            continue
        stop_d, tp_d = geom_at(i, d, o, h, l, c, a)
        sp = spread[i + 1]
        if use_spread and sp > SPREAD_GATE * stop_d:
            shadows.append((t, shadow_r(i, d, o, h, l, c, a, spread), "spread",
                           float(score_used), sp / stop_d))
            i += 1
            continue
        # --- sizing ---
        risk_money = equity * RISK
        vol = max(float(int(risk_money / ((stop_d / TICK) * TV) / 0.01) * 0.01), 0.01)
        if consec > 0:
            vol = max(float(int(vol * max(SCALE_F ** consec, SCALE_MIN) / 0.01) * 0.01), 0.01)
        eff_risk = vol * (stop_d / TICK) * TV
        if d > 0:
            entry = o[i + 1] + sp / 2.0
            sl, tp = entry - stop_d, entry + tp_d
        else:
            entry = o[i + 1] - sp / 2.0
            sl, tp = entry + stop_d, entry - tp_d
        r = None
        j_end = min(i + 1 + HOLD, n)
        close_j = None
        for j in range(i + 1, j_end):
            if d > 0:
                if l[j] <= sl:
                    r = -1.0; close_j = j; break
                if h[j] >= tp:
                    r = TP_MULT; close_j = j; break
            else:
                if h[j] >= sl:
                    r = -1.0; close_j = j; break
                if l[j] <= tp:
                    r = TP_MULT; close_j = j; break
        if r is None:
            close_j = j_end - 1
            r = d * (c[close_j] - (sp / 2.0) * d - entry) / stop_d
        r -= sp / stop_d
        equity += r * eff_risk
        daily_pnl += r * eff_risk
        peak = max(peak, equity)
        maxdd = max(maxdd, peak - equity)
        # v26.22 win-rearm: cooldown only after losses
        if r < 0:
            consec += 1
            cooldown_until = close_j + COOLDOWN_BARS
            if consec >= 3:
                paused_day = int(ts[close_j] // 86400)
                consec = 0
        else:
            consec = 0
        trades.append((t, r, eff_risk))
        i = close_j + 1
    return {"arm": name, "equity": equity, "trades": trades, "shadows": shadows,
            "maxdd": maxdd, "throttle_bars": throttle_bars}


def summarize(res):
    rs = [t[1] for t in res["trades"]]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x <= 0]
    gw, gl = sum(wins), sum(losses)
    return {"trades": len(rs), "wr": round(100 * len(wins) / len(rs), 1) if rs else 0.0,
            "pf": round(gw / gl, 2) if gl > 0 else None,
            "total_r": round(sum(rs), 2),
            "end_equity": round(res["equity"], 2),
            "ret_pct": round(100 * (res["equity"] / EQUITY0 - 1), 2),
            "maxdd_usd": round(res["maxdd"], 2),
            "shadows": len(res["shadows"]),
            "shadow_r": round(sum(s[1] for s in res["shadows"]), 2),
            "throttle_bars": res["throttle_bars"]}


def main() -> int:
    global DAYS
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30,
                    help="window length in days (0 = full history)")
    args = ap.parse_args()
    DAYS = args.days
    full = DAYS == 0

    o, h, l, c, ts, spread = load_bars()
    sig, _, _ = fsb.signals(o, h, l, c)
    bs, ss, a, reg, z = scores_pipeline(o, h, l, c, sig)

    arms = {}
    for name, us, uc in (("A_base", False, False), ("B_spread", True, False),
                         ("C_conviction", False, True), ("D_both", True, True)):
        res = run_engine(name, o, h, l, c, ts, spread, bs, ss, a, us, uc,
                         days=0 if full else DAYS)
        arms[name] = res
        s = summarize(res)
        print(f"{name:14s} trades={s['trades']:3d} WR={s['wr']:5.1f}% PF={s['pf']} "
              f"totalR={s['total_r']:+.2f} equity=${s['end_equity']:.2f} ({s['ret_pct']:+.2f}%) "
              f"maxDD=${s['maxdd_usd']:.2f} | refused={s['shadows']} "
              f"(shadow R {s['shadow_r']:+.2f}) | throttle-on {s['throttle_bars']} bars")

    print("\nAutopsy — refused signals and what they would have done:")
    for name in ("B_spread", "C_conviction", "D_both"):
        sh = arms[name]["shadows"]
        if not sh:
            print(f"  {name}: nothing refused")
            continue
        by_gate = {}
        for t, r, gate, sc, sr in sh:
            by_gate.setdefault(gate, []).append(r)
        for g, rs in by_gate.items():
            print(f"  {name}/{g}: {len(rs)} refused | shadow total {sum(rs):+.2f}R "
                  f"| would-be WR {100 * sum(1 for x in rs if x > 0) / len(rs):.0f}%")

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(),
           "window_days": DAYS,
           "window": [int(ts[110 if full else len(ts) - DAYS * 96 - 2]), int(ts[-1])],
           "arms": {k: summarize(v) for k, v in arms.items()},
           "shadows": {k: [(int(t), round(r, 3), g, round(sc, 2), round(sr, 3))
                           for t, r, g, sc, sr in v["shadows"]]
                       for k, v in arms.items()}}
    fname = "gates_ab_v75_full.json" if full else "gates_ab_v75.json"
    (ART / fname).write_text(json.dumps(out, indent=1))
    print(f"\nartifact -> artifacts/{fname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
