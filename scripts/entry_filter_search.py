#!/usr/bin/env python3
"""Entry-filter search on banked V75 M15 bars — the honest protocol.

Engine: EA-faithful (VOL75_FINAL geometry — SL 1.7xATR + 5-bar swing widen,
floor 0.5xATR/stops-level, cap 3% price, TP 2.0xstop, hold 20 bars,
worst-case fills, per-bar broker spread charged per round trip).

Protocol (no peeking):
  1. Build the base trade list with per-trade decision-time features.
  2. Split trades 70/30 in-sample / out-of-sample BY TIME.
  3. Greedy forward filter selection on IN-SAMPLE ONLY
     (objective: expR, subject to >=150 IS trades; tie-break total R).
  4. The IS-selected chain is verified ONCE out-of-sample.
     Gates: OOS trades >= 60 | PF >= 1.15 | expR > 0 | maxDD <= 15R.
  5. Up to 4 IS-selected chains (menu variants) get their one OOS shot.
  6. Winner (if any) -> Monte-Carlo: 150 random 30-day windows, $30
     compounding account with loss-scaling + 3-loss daily pause.

Writes artifacts/entry_filter_search_v75.json
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
CSV_BARS = ART / "data" / "volatility_75_index_m15_40000bars.csv"
POINT = 0.01

SL_ATR_MULT = 1.7
TP_MULT = 2.0
MAX_HOLD_BARS = 20
IS_FRAC = 0.70
GATES = {"oos_trades_min": 60, "oos_pf_min": 1.15, "oos_dd_max_r": 15.0}

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


def build_trades(o, h, l, c, ts, spread, feats):
    """Base trade list with features + preset-exact geometry."""
    sig, a, _ = fsb.signals(o, h, l, c)
    n = len(c)
    trades = []
    i = 0
    while i < n - 1:
        d = sig[i]
        if d == 0 or a[i] <= 0:
            i += 1
            continue
        stop_d = SL_ATR_MULT * a[i]
        if d > 0:
            lo = l[max(0, i - 5):i].min()
            stop_d = max(stop_d, o[i + 1] - (lo - 0.15 * a[i]))
        else:
            hi = h[max(0, i - 5):i].max()
            stop_d = max(stop_d, (hi + 0.15 * a[i]) - o[i + 1])
        stop_d = max(stop_d, 0.5 * a[i])
        stop_d = min(stop_d, c[i] * 0.03)
        tp_d = TP_MULT * stop_d
        sp = spread[i + 1]
        if d > 0:
            entry = o[i + 1] + sp / 2.0
            sl, tp = entry - stop_d, entry + tp_d
        else:
            entry = o[i + 1] - sp / 2.0
            sl, tp = entry + stop_d, entry - tp_d
        r = None
        j_end = min(i + 1 + MAX_HOLD_BARS, n)
        for j in range(i + 1, j_end):
            if d > 0:
                if l[j] <= sl:
                    r = -1.0; break
                if h[j] >= tp:
                    r = tp_d / stop_d; break
            else:
                if h[j] >= sl:
                    r = -1.0; break
                if l[j] <= tp:
                    r = tp_d / stop_d; break
        if r is None:
            j = j_end - 1
            exit_p = c[j] - (sp / 2.0) * d
            r = d * (exit_p - entry) / stop_d
        r -= sp / stop_d
        trades.append({"i": i, "ts": int(ts[i]), "d": d, "r": r,
                       "spread_ratio": sp / stop_d, **{k: v[i] for k, v in feats.items()}})
        i = j + 1
    return trades


def stats(rows):
    if not rows:
        return {"trades": 0}
    rs = [t["r"] for t in rows]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x <= 0]
    gw, gl = sum(wins), sum(losses)
    cum = peak = dd = 0.0
    for x in rs:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    days = max((rows[-1]["ts"] - rows[0]["ts"]) / 86400.0, 1e-9)
    return {"trades": len(rs), "wr": round(100 * len(wins) / len(rs), 1),
            "pf": round(gw / gl, 2) if gl > 0 else 99.0,
            "exp_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 2),
            "max_dd_r": round(dd, 2), "trades_per_day": round(len(rs) / days, 2),
            "r_per_day": round(sum(rs) / days, 3)}


# ---------------- filter menu (name -> predicate factory over thresholds) ---
def legs_at_bars(o, h, l, c, e20, e50, z, a, reg, sig):
    """Replicate fwd_split_backtest.signals() leg logic per bar (EA-faithful).
    Returns per-bar frozenset of fired legs for the DECIDED direction; asserted
    against the reference engine's dir for 100% agreement."""
    n = len(c)
    e100 = fsb.ema(c, fsb.EMA_S)
    legs_out = [None] * n
    mism = 0
    for i in range(fsb.EMA_S + 2, n - 1):
        if reg[i] == 3 or not (a[i] > 0):
            legs_out[i] = frozenset()
            continue
        lb, ls, sb, ss = [], [], 0.0, 0.0
        mom = e20[i] - e20[i - 2]
        if abs(mom) > 0.25 * a[i]:
            (lb if mom > 0 else ls).append("MOM")
            sb += 2.2 if mom > 0 else 0
            ss += 2.2 if mom < 0 else 0
        if reg[i] == 1 and l[i] <= e20[i] * 1.0005 and c[i] > e50[i]:
            lb.append("PB"); sb += 2.5
        if reg[i] == 2 and h[i] >= e20[i] * 0.9995 and c[i] < e50[i]:
            ls.append("PB"); ss += 2.5
        if abs(c[i] - e50[i]) > 2.0 * a[i]:
            if c[i] < e50[i]: lb.append("MR"); sb += 2.0
            else:             ls.append("MR"); ss += 2.0
        if z[i] <= -fsb.Z_ENTRY: lb.append("BF"); sb += 4.2
        if z[i] >=  fsb.Z_ENTRY: ls.append("BF"); ss += 4.2
        if lb == ["MOM"]: lb, sb = [], 0.0
        if ls == ["MOM"]: ls, ss = [], 0.0
        if reg[i] == 1: sb += fsb.REGIME_BONUS
        if reg[i] == 2: ss += fsb.REGIME_BONUS
        d = 0
        if len(lb) >= 2 and sb >= fsb.MIN_SCORE and sb > ss: d = 1; legs_out[i] = frozenset(lb)
        elif len(ls) >= 2 and ss >= fsb.MIN_SCORE and ss > sb: d = -1; legs_out[i] = frozenset(ls)
        else: legs_out[i] = frozenset()
        if d != int(sig[i]):
            mism += 1
    assert mism == 0, f"leg recompute disagrees with engine on {mism} bars"
    return legs_out


def make_filters():
    return {
        "atr_rank_hi_090": lambda t: t["atr_rank"] >= 0.90,
        "atr_rank_hi_075": lambda t: t["atr_rank"] >= 0.75,
        "atr_rank_lo_025": lambda t: t["atr_rank"] <= 0.25,
        "hour_block_dead": lambda t: not (0 <= t["hour"] <= 3 or t["hour"] >= 21),
        "hour_block_0_6": lambda t: not (0 <= t["hour"] <= 6),
        "zext_ge_250": lambda t: t["z_ext"] >= 2.5,
        "zext_ge_200": lambda t: t["z_ext"] >= 2.0,
        "emasep_ge_010": lambda t: t["ema_sep_pct"] >= 0.10,
        "emasep_ge_020": lambda t: t["ema_sep_pct"] >= 0.20,
        "spread_le_020": lambda t: t["spread_ratio"] <= 0.020,
        "spread_le_030": lambda t: t["spread_ratio"] <= 0.030,
        "dayret_ext_150": lambda t: abs(t["day_return"]) >= 1.5,
        "dayret_ext_250": lambda t: abs(t["day_return"]) >= 2.5,
        "dayret_align_150": lambda t: abs(t["day_return"]) >= 1.5 and t["day_return"] * t["d"] > 0,
        # leg-composition filters (mechanism hypothesis: per-leg edges differ)
        "band_only":    lambda t: "BF" in t["legs"],
        "no_mom_leg":   lambda t: "MOM" not in t["legs"],
        "pb_or_band":   lambda t: ("BF" in t["legs"]) or ("PB" in t["legs"]),
    }


def main() -> int:
    o, h, l, c, ts, spread = load_bars()
    sig, a, reg = fsb.signals(o, h, l, c)

    # ---- decision-time features ----
    e20, e50 = fsb.ema(c, 20), fsb.ema(c, 50)
    w = 20
    roll_mean = np.convolve(c, np.ones(w) / w, mode="valid")
    roll_std = np.array([c[k - w + 1:k + 1].std() for k in range(w - 1, len(c))])
    z = np.concatenate((np.zeros(w - 1), (c[w - 1:] - roll_mean) / np.maximum(roll_std, 1e-12)))
    z = np.concatenate((np.zeros(1), z))[:-1]
    atr_rank = np.zeros(len(c))
    lb = 2000
    for k in range(len(c)):
        lo = max(0, k - lb)
        atr_rank[k] = (a[lo:k + 1] <= a[k]).mean() if k > 50 else 0.5
    hours = np.array([(t // 3600) % 24 for t in ts])
    day_ret = np.zeros(len(c))
    day_ret[96:] = (c[96:] - c[:-96]) / c[:-96] * 100.0

    feats = {"z_ext": np.abs(z), "ema_sep_pct": np.abs(e20 - e50) / c * 100.0,
             "atr_rank": atr_rank, "hour": hours, "day_return": day_ret}

    legs = legs_at_bars(o, h, l, c, e20, e50, z, a, reg, sig)
    trades = build_trades(o, h, l, c, ts, spread, feats)
    for t in trades:
        t["legs"] = legs[t["i"]]
    split = int(len(trades) * IS_FRAC)
    is_tr, oos_tr = trades[:split], trades[split:]
    base_is, base_oos = stats(is_tr), stats(oos_tr)
    print(f"base trades {len(trades)} | IS {base_is['trades']} (expR {base_is['exp_r']}) "
          f"| OOS {base_oos['trades']} (expR {base_oos['exp_r']}, PF {base_oos['pf']})")

    # per-leg IS diagnostics (selection decisions must use IS only)
    print("\nper-leg IS stats (composition of the fired set):")
    for lg in ("BF", "PB", "MR", "MOM"):
        rows = [t for t in is_tr if lg in t["legs"]]
        if rows:
            print(f"  {lg}: {stats(rows)}")

    menu = make_filters()
    attempts = []

    def greedy(objective):
        """Forward selection on IS; returns chain of filter names."""
        chain, cur = [], list(is_tr)
        best = objective(stats(cur))
        while True:
            cand_best = None
            for name, pred in menu.items():
                if name in chain:
                    continue
                p = stats([t for t in cur if pred(t)])
                if p.get("trades", 0) < 150:
                    continue
                sc = objective(p)
                if cand_best is None or sc > cand_best[0]:
                    cand_best = (sc, name, p)
            if cand_best is None or cand_best[0] <= best:
                break
            best, name, _ = cand_best
            chain.append(name)
            cur = [t for t in cur if menu[name](t)]
        return chain

    objectives = {
        "expR": lambda s: (s.get("exp_r", -9), s.get("total_r", 0)),
        "expR_x_act": lambda s: (s.get("exp_r", -9) * math.sqrt(max(s.get("trades_per_day", 0), 0.1)),
                                 s.get("exp_r", -9)),
    }
    verdict = None
    for oname, obj in objectives.items():
        chain = greedy(obj)
        sel_is = [t for t in is_tr if all(menu[f](t) for f in chain)]
        sel_oos = [t for t in oos_tr if all(menu[f](t) for f in chain)]
        s_is, s_oos = stats(sel_is), stats(sel_oos)
        fails = []
        if s_oos.get("trades", 0) < GATES["oos_trades_min"]: fails.append("trades<min")
        if s_oos.get("pf", 0) < GATES["oos_pf_min"]: fails.append("PF<1.15")
        if s_oos.get("exp_r", -1) <= 0: fails.append("expR<=0")
        if s_oos.get("max_dd_r", 99) > GATES["oos_dd_max_r"]: fails.append("DD>15R")
        ok = not fails
        attempts.append({"objective": oname, "chain": chain, "is": s_is, "oos": s_oos,
                         "oos_verdict": "PASS" if ok else "FAIL(" + ",".join(fails) + ")"})
        print(f"[{oname}] chain={chain or ['(none)']}")
        print(f"   IS : {s_is}")
        print(f"   OOS: {s_oos}  -> {attempts[-1]['oos_verdict']}")
        if ok:
            verdict = attempts[-1]
            break

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(),
           "symbol": "Volatility 75 Index", "bars": len(c),
           "geometry": {"sl": SL_ATR_MULT, "tp": TP_MULT, "hold": MAX_HOLD_BARS},
           "base": {"is": base_is, "oos": base_oos},
           "attempts": attempts, "winner": verdict}
    (ART / "entry_filter_search_v75.json").write_text(json.dumps(out, indent=1))

    if not verdict:
        print("\nVERDICT: no IS-selected chain passed OOS — reported honestly.")
        return 1

    # ---------------- Monte-Carlo with the winning chain ----------------
    preds = [menu[f] for f in verdict["chain"]]
    def pass_filter(idx, i, d):
        t = {"atr_rank": atr_rank[i], "hour": hours[i], "z_ext": abs(z[i]),
             "ema_sep_pct": feats["ema_sep_pct"][i], "day_return": day_ret[i],
             "d": d, "legs": legs[i], "spread_ratio": spread[i + 1] / max(1e-9, SL_ATR_MULT * a[i])}
        return all(p(t) for p in preds)

    tick, tv = 0.01, 0.10   # V75: point 0.01, tick value ~$0.10 per 1.0 lot per tick
    equity0 = 30.0
    n = len(c)
    rng = random.Random(7)
    starts = rng.sample(range(150, n - 30 * 96 - 2), 150)
    ends = []
    for s in starts:
        equity, consec, paused_day = equity0, 0, -1
        i = s
        end_pos = min(n - 1, s + 30 * 96)
        while i < end_pos - 1:
            d = sig[i]
            if d == 0 or a[i] <= 0 or not pass_filter(0, i, d):
                i += 1
                continue
            day = int(ts[i] // 86400)
            if day <= paused_day:
                i += 1
                continue
            stop_d = SL_ATR_MULT * a[i]
            if d > 0:
                lo = l[max(0, i - 5):i].min()
                stop_d = max(stop_d, o[i + 1] - (lo - 0.15 * a[i]))
            else:
                hi = h[max(0, i - 5):i].max()
                stop_d = max(stop_d, (hi + 0.15 * a[i]) - o[i + 1])
            stop_d = max(stop_d, 0.5 * a[i])
            stop_d = min(stop_d, c[i] * 0.03)
            tp_d = TP_MULT * stop_d
            sp = spread[i + 1]
            risk_money = equity * 0.005
            vol = math.floor(risk_money / ((stop_d / tick) * tv) / 0.01) * 0.01
            vol = max(vol, 0.01)
            if consec > 0:
                vol = max(math.floor(vol * max(0.75 ** consec, 0.30) / 0.01) * 0.01, 0.01)
            eff_risk = vol * (stop_d / tick) * tv
            if d > 0:
                entry = o[i + 1] + sp / 2.0
                sl, tp = entry - stop_d, entry + tp_d
            else:
                entry = o[i + 1] - sp / 2.0
                sl, tp = entry + stop_d, entry - tp_d
            r = None
            j_end = min(i + 1 + MAX_HOLD_BARS, end_pos)
            for j in range(i + 1, j_end):
                if d > 0:
                    if l[j] <= sl: r = -1.0; break
                    if h[j] >= tp: r = tp_d / stop_d; break
                else:
                    if h[j] >= sl: r = -1.0; break
                    if l[j] <= tp: r = tp_d / stop_d; break
            if r is None:
                j = j_end - 1
                r = d * (c[j] - (sp / 2.0) * d - entry) / stop_d
            r -= sp / stop_d
            equity += r * eff_risk
            consec = consec + 1 if r < 0 else 0
            if consec >= 3:
                paused_day = day
                consec = 0
            i = j + 1
        ends.append(equity)
    ends = np.array(ends)
    mc = {"windows": len(ends), "median_end": round(float(np.median(ends)), 2),
          "pct_profitable": round(float((ends > equity0).mean() * 100), 1),
          "p5": round(float(np.percentile(ends, 5)), 2),
          "p95": round(float(np.percentile(ends, 95)), 2),
          "worst": round(float(ends.min()), 2), "best": round(float(ends.max()), 2)}
    out["monte_carlo"] = mc
    (ART / "entry_filter_search_v75.json").write_text(json.dumps(out, indent=1))
    print(f"\nMonte-Carlo ({mc['windows']} x 30-day, $30, filters {' + '.join(verdict['chain']) or 'none'}):")
    print(f"  median ${mc['median_end']} | profitable {mc['pct_profitable']}% "
          f"| p5 ${mc['p5']} / p95 ${mc['p95']} | worst ${mc['worst']} / best ${mc['best']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
