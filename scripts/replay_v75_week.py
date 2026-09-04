"""Replay MitemshubAI v26.24 signal + trade logic on real V75 M15/H1 candles.

Faithful port of MitemshubAI.mq5 (standard mode, VOL75_FINAL preset):
  - H1 EMA regime classifier (with M15-ATR separation term + ATR percentile
    NO_TRADE/HIGH_VOL gates, 120-bar lookback, 10/92 percentiles)
  - 5 strategy legs (PB/BO/MOM/MR/BF) with exact thresholds
  - lone-MOM demotion, composite scoring, regime +2, adaptive conviction
  - EGARCH(1,1) calibrated-fixed sigma + sigma EMA(30) + band-fade geometry
  - governor v26.24: all strategies enabled (bootstrap fix)
  - trade sim: next-bar-open entry, structural SL (1.7 ATR / 5-bar structure,
    floor 0.5 ATR, cap 3%), TP 2.4x (BF: sigma geometry), profit lock 0.5R,
    early cut -0.4R @6 bars, 20-bar hold (winner extension x1.5),
    breakeven + 0.7R trailing from +1R, 1-bar cooldown after losses.

Usage: python scripts/replay_v75_week.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "artifacts", "v75_replay")

# ---- VOL75_FINAL preset / EA constants -----------------------------------
EMA_FAST, EMA_MID, EMA_SLOW = 20, 50, 100
MIN_EMA_SEP = 0.20
ATR_PERIOD = 14
ATR_LOOKBACK = 120
ATR_LOW_PCT, ATR_HIGH_PCT = 10.0, 92.0
RSI_OB, RSI_OS = 68.0, 32.0
PB_MIN, PB_MAX = 0.30, 2.2
BO_BARS, BO_BUF = 12, 0.10
MOM_BODY_MIN = 0.45
BB_LEN = 20
SIGMA_EMA_LEN = 30
BAND_Z, BAND_EXT = 2.0, 1.25
BAND_STOP_SIG, BAND_TGT_SIG, BAND_HOLD_BARS = 0.10, 1.20, 4  # 3600s / M15
BAND_MAX_STOP_FRAC = 0.015
MIN_SCORE = 3
TP_MULT = 2.4
MAX_HOLD, EXTEND_MULT = 20, 1.5
EARLY_CUT_BARS, EARLY_CUT_R, HW_EARLY = 6, -0.40, 0.3
PLOCK_R = 0.5
TRAIL_START_R, TRAIL_DIST_R, BE_TRIGGER_R = 1.0, 0.7, 1.0
COOLDOWN_BARS = 1
# EGARCH calibrated-fixed (Market/GarchForecaster.mqh, r_75.json)
EG_OMEGA, EG_ALPHA, EG_GAMMA, EG_BETA = -1.115, 0.077, 0.011, 0.918
EG_LOGVAR0 = -7.824046010856292
EG_BUF, EG_WARM = 50, 50
E_ABSZ = 0.7979

BULL, BEAR, RANGE, HVOL, NOTRADE = 0, 1, 2, 3, 4
RNAME = {0: "BULLISH", 1: "BEARISH", 2: "RANGING", 3: "HIGH_VOL", 4: "NO_TRADE"}


def load(name):
    # CERT_DATA_DIR lets the same harness certify other Volatility symbols
    # (e.g. V100) without touching the V75 default.
    data_dir = os.environ.get("CERT_DATA_DIR", DATA)
    with open(os.path.join(data_dir, name)) as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append({
            "t": datetime.fromisoformat(r["time"]),
            "o": float(r["open"]), "h": float(r["high"]),
            "l": float(r["low"]), "c": float(r["close"]),
        })
    return out


def ema(vals, n):
    a = 2.0 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(a * v + (1 - a) * out[-1])
    return out


def wilder_atr(bars, n):
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["h"] - b["l"])
            continue
        pc = bars[i - 1]["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    atr = [trs[0]]
    for i in range(1, len(trs)):
        atr.append((atr[-1] * (n - 1) + trs[i]) / n)
    return atr


def wilder_rsi(closes, n=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out = [None] * n
    out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out  # index aligned to closes (first n entries None)


class Egarch:
    def __init__(self):
        self.log_var = EG_LOGVAR0
        self.obs = 0
        self.buf = []
        self.z = 0.0

    def update(self, lr):
        self.obs += 1
        if self.obs <= EG_BUF:
            self.buf.append(lr)
            if self.obs < 30:
                return math.exp(self.log_var / 2), False
            if self.obs == EG_BUF:
                msq = sum(x * x for x in self.buf) / EG_BUF
                self.log_var = math.log(max(msq, 1e-10))
        sigma_t = math.exp(min(max(self.log_var, -30.0), 5.0) / 2)
        z = lr / max(sigma_t, 1e-10)
        self.z = z
        shock = abs(z) - E_ABSZ
        self.log_var = min(max(EG_OMEGA + EG_ALPHA * shock + EG_GAMMA * z + EG_BETA * self.log_var, -30.0), 5.0)
        return math.exp(self.log_var / 2), self.obs >= EG_WARM


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band-ext", type=float, default=BAND_EXT,
                    help="BandFade expansion gate (EA: InpBandVolExtRatio, deployed 1.25)")
    ap.add_argument("--mom-standalone", action="store_true",
                    help="let lone MOM trade (EA: InpMomentumStandalone)")
    ap.add_argument("--tag", default="baseline", help="suffix for the report file")
    args = ap.parse_args()
    band_ext = args.band_ext
    mom_standalone = args.mom_standalone
    m15, h1 = load("m15.csv"), load("h1.csv")
    closes = [b["c"] for b in m15]
    eF, eM, eS = ema(closes, EMA_FAST), ema(closes, EMA_MID), ema(closes, EMA_SLOW)
    atr = wilder_atr(m15, ATR_PERIOD)
    rsi = wilder_rsi(closes)
    h1c = [b["c"] for b in h1]
    hF, hM, hS = ema(h1c, EMA_FAST), ema(h1c, EMA_MID), ema(h1c, EMA_SLOW)

    def h1_idx(t):
        lo, hi = 0, len(h1) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if h1[mid]["t"] <= t:
                lo = mid
            else:
                hi = mid - 1
        return lo

    garch = Egarch()
    sig_ema, sig_init = 0.0, False
    atr_hist: list[float] = []
    sma20 = [None] * len(m15)
    for i in range(BB_LEN - 1, len(m15)):
        sma20[i] = sum(closes[i - BB_LEN + 1:i + 1]) / BB_LEN
    bb_sd = [None] * len(m15)
    for i in range(BB_LEN - 1, len(m15)):
        m = sma20[i]
        bb_sd[i] = math.sqrt(sum((c - m) ** 2 for c in closes[i - BB_LEN + 1:i + 1]) / BB_LEN)

    START = 480  # ~5 days burn-in for indicators + GARCH warm
    trades = []
    skipped = []
    pos = None
    cooldown_until = -1
    day_r: dict[str, float] = {}

    def regime_at(i):
        j = h1_idx(m15[i]["t"])
        if h1[j]["t"] == m15[i]["t"] and j > 0:
            j -= 1  # EA reads closed H1 bar (shift 1)
        a = atr[i]
        if len(atr_hist) >= 40:
            look = atr_hist[-ATR_LOOKBACK:]
            pct = sum(1 for x in look if a > x) / len(look) * 100
        else:
            pct = 50.0
        if pct > ATR_HIGH_PCT:
            return HVOL, pct
        if pct < ATR_LOW_PCT:
            return NOTRADE, pct
        c = h1[j]["c"]
        sep = abs(hF[j] - hM[j]) / a if a > 0 else 0
        if hF[j] > hM[j] > hS[j] and c > hF[j] and sep >= MIN_EMA_SEP:
            return BULL, pct
        if hF[j] < hM[j] < hS[j] and c < hF[j] and sep >= MIN_EMA_SEP:
            return BEAR, pct
        return RANGE, pct

    for i in range(START, len(m15) - 1):
        b = m15[i]
        day = b["t"].strftime("%Y-%m-%d")
        # per-bar feeds (EA order): GARCH/sigma baseline -> telemetry -> regime
        if i >= 1:
            lr = math.log(closes[i] / closes[i - 1])
            sig_now, warm = garch.update(lr)
            if sig_init:
                a_s = 2.0 / (SIGMA_EMA_LEN + 1)
                sig_ema = a_s * sig_now + (1 - a_s) * sig_ema
            else:
                sig_ema, sig_init = sig_now, True
        reg, pct = regime_at(i)
        atr_hist.append(atr[i])
        if len(atr_hist) > ATR_LOOKBACK + 10:
            atr_hist.pop(0)

        z_dev = math.log(b["c"] / sma20[i]) / sig_now if sma20[i] else 0.0
        if warm:
            z_dev = garch.z
        exp_ratio = sig_now / sig_ema if sig_ema > 0 else 0.0

        # ---- manage open position on this bar (intrabar TP/SL, close mgmt) --
        if pos and i >= pos["entry_i"]:
            p = pos
            if p["dir"] < 0:
                hit_sl, hit_tp = b["h"] >= p["sl"], b["l"] <= p["tp"]
            else:
                hit_sl, hit_tp = b["l"] <= p["sl"], b["h"] >= p["tp"]
            if hit_sl and not hit_tp:
                trades[-1].update(exit="SL", exit_t=str(b["t"]), r=-1.0 + trades[-1]["r_extra"])
                pos = None
            elif hit_tp and not hit_sl:
                trades[-1].update(exit="TP", exit_t=str(b["t"]), r=p["tp_r"] + trades[-1]["r_extra"])
                trades[-1]["win"] = True
                pos = None
            elif hit_sl and hit_tp:  # conservative: SL first
                trades[-1].update(exit="SL(ambig)", exit_t=str(b["t"]), r=-1.0 + trades[-1]["r_extra"])
                pos = None
            else:
                best = (p["entry"] - b["l"]) / p["sd"] if p["dir"] < 0 else (b["h"] - p["entry"]) / p["sd"]
                r_close = (p["entry"] - b["c"]) / p["sd"] if p["dir"] < 0 else (b["c"] - p["entry"]) / p["sd"]
                p["hw"] = max(p["hw"], best)
                held = i - p["entry_i"]
                reason = None
                if p["hw"] >= 1.0 and 0 < r_close <= PLOCK_R:
                    reason = "PLOCK"
                elif held >= EARLY_CUT_BARS and r_close <= EARLY_CUT_R and p["hw"] < HW_EARLY:
                    reason = "ECUT"
                elif held >= MAX_HOLD:
                    if r_close > 0.2:
                        reason = None  # winner: let trailing handle it
                    elif held >= int(MAX_HOLD * EXTEND_MULT):
                        reason = None if r_close > 0.2 else "TIME_EXT"
                    else:
                        reason = "TIME"
                if reason:
                    r = r_close + trades[-1]["r_extra"]
                    trades[-1].update(exit=reason, exit_t=str(b["t"]), r=r)
                    trades[-1]["win"] = r > 0
                    pos = None
                    if r <= 0:
                        cooldown_until = i + COOLDOWN_BARS
                else:
                    if p["hw"] >= BE_TRIGGER_R:  # breakeven then trail
                        be = p["entry"] - 2e-6 if p["dir"] < 0 else p["entry"] + 2e-6
                        if (p["dir"] < 0 and be < p["sl"]) or (p["dir"] > 0 and be > p["sl"]):
                            p["sl"] = be
                    if p["hw"] >= TRAIL_START_R:
                        ns = b["c"] + TRAIL_DIST_R * p["sd"] if p["dir"] < 0 else b["c"] - TRAIL_DIST_R * p["sd"]
                        if (p["dir"] < 0 and ns < p["sl"]) or (p["dir"] > 0 and ns > p["sl"]):
                            p["sl"] = ns
                if pos and held >= int(MAX_HOLD * EXTEND_MULT) and r_close > 0.2:
                    pass  # let it run

        if pos is not None:
            day_r[day] = day_r.get(day, 0.0) + (trades[-1]["r"] if trades and trades[-1].get("exit") and trades[-1]["exit_t"].startswith(day) else 0.0)
            continue
        if i <= cooldown_until:
            continue

        # ---- signal evaluation (bar i = last closed bar) -------------------
        min_eff = MIN_SCORE + (1 if day_r.get(day, 0.0) < 0 else 0)
        legs = []
        # MOM
        rng_ = b["h"] - b["l"]
        body = b["c"] - b["o"]
        if rng_ > 0 and abs(body) / rng_ >= MOM_BODY_MIN:
            if body > 0 and abs(body) / rng_ > 0.55:
                legs.append(("MOM", 1, 3.0))
            elif body < 0 and abs(body) / rng_ > 0.55:
                legs.append(("MOM", -1, 3.0))
        # MR
        if reg == RANGE and i >= 1 and rsi[i] is not None:
            bb_l = sma20[i] - 2 * bb_sd[i]
            bb_u = sma20[i] + 2 * bb_sd[i]
            if closes[i - 1] <= bb_l and b["c"] > bb_l and rsi[i] < RSI_OS:
                legs.append(("MR", 1, 3.8))
            if closes[i - 1] >= bb_u and b["c"] < bb_u and rsi[i] > RSI_OB:
                legs.append(("MR", -1, 3.8))
        # BF
        bf_geo_ok, bf_stop_f, bf_tgt_f = False, 0.0, 0.0
        if reg in (RANGE, HVOL) and sig_init and warm:
            if exp_ratio > band_ext:
                if z_dev >= BAND_Z or z_dev <= -BAND_Z:
                    bars = BAND_HOLD_BARS
                    sigma_h = sig_now * math.sqrt(bars)
                    stop_f = BAND_STOP_SIG * sigma_h
                    tgt_f = BAND_TGT_SIG * sigma_h
                    if tgt_f / stop_f >= 2.5 and stop_f <= BAND_MAX_STOP_FRAC:
                        d = -1 if z_dev >= BAND_Z else 1
                        legs.append(("BF", d, 4.2))
                        bf_geo_ok, bf_stop_f, bf_tgt_f = True, stop_f, tgt_f
        # PB
        if reg in (BULL, BEAR) and rsi[i] is not None:
            d = 1 if reg == BULL else -1
            pb = abs(b["c"] - eF[i])
            if PB_MIN * atr[i] <= pb <= PB_MAX * atr[i]:
                ok = True
                if d > 0 and (rsi[i] > 65 or body < -0.1 * atr[i]):
                    ok = False
                if d < 0 and (rsi[i] < 35 or body > 0.1 * atr[i]):
                    ok = False
                if d > 0 and not eF[i] > eM[i]:
                    ok = False
                if d < 0 and not eF[i] < eM[i]:
                    ok = False
                if ok:
                    legs.append(("PB", d, 4.0))
        # BO
        if reg not in (NOTRADE, HVOL):
            hh = max(m15[k]["h"] for k in range(i - BO_BARS + 1, i + 1))
            ll = min(m15[k]["l"] for k in range(i - BO_BARS + 1, i + 1))
            buf = BO_BUF * atr[i]
            d = 1 if reg in (BULL, RANGE) else -1
            if d > 0 and b["c"] > hh + buf and body > 0:
                legs.append(("BO", 1, 3.5))
            if d < 0 and b["c"] < ll - buf and body < 0:
                legs.append(("BO", -1, 3.5))

        buy = sum(s for _, d, s in legs if d > 0)
        sell = sum(s for _, d, s in legs if d < 0)
        nbuy = sum(1 for _, d, _ in legs if d > 0)
        nsell = sum(1 for _, d, _ in legs if d < 0)
        # lone-MOM demotion
        if not mom_standalone:
            if nbuy == 1 and any(n == "MOM" and d > 0 for n, d, _ in legs):
                buy, nbuy = 0, 0
            if nsell == 1 and any(n == "MOM" and d < 0 for n, d, _ in legs):
                sell, nsell = 0, 0
        reg_bonus = 2 if reg == BULL else (-2 if reg == BEAR else 0)
        buy += max(reg_bonus, 0) * (1 if any(d > 0 for _, d, _ in legs) else 0)
        sell += max(-reg_bonus, 0) * (1 if any(d < 0 for _, d, _ in legs) else 0)

        ddir = 0
        if buy >= min_eff and buy > sell:
            ddir = 1
        elif sell >= min_eff and sell > buy:
            ddir = -1

        if ddir == 0:
            skipped.append({"t": str(b["t"]), "legs": "|".join(f"{n}{'+' if d > 0 else '-'}" for n, d, _ in legs),
                            "b": round(buy, 1), "s": round(sell, 1), "reg": RNAME[reg], "z": round(z_dev, 2),
                            "exp": round(exp_ratio, 3), "reason": "score/demote"})
            continue

        # ---- enter at next bar open ----------------------------------------
        nb = m15[i + 1]
        entry = nb["o"]
        if bf_geo_ok and any(n == "BF" for n, d, _ in legs if d == ddir):
            sd = bf_stop_f * entry
            td = bf_tgt_f * entry
        else:
            sd = 1.7 * atr[i]
            if ddir > 0:
                lo5 = min(m15[k]["l"] for k in range(i - 4, i + 1))
                sd = max(sd, entry - (lo5 - 0.15 * atr[i]))
            else:
                hi5 = max(m15[k]["h"] for k in range(i - 4, i + 1))
                sd = max(sd, (hi5 + 0.15 * atr[i]) - entry)
            sd = max(sd, 0.5 * atr[i])
            td = TP_MULT * sd
        sd = min(sd, entry * 0.03)
        strat = "+".join(n for n, d, _ in legs if d == ddir)
        trades.append({"t": str(nb["t"]), "sig_t": str(b["t"]), "strat": strat, "dir": "SELL" if ddir < 0 else "BUY",
                       "entry": round(entry, 2), "sd": round(sd, 2), "reg": RNAME[reg], "z": round(z_dev, 2),
                       "exp": round(exp_ratio, 3), "legs_b": round(buy, 1), "legs_s": round(sell, 1),
                       "r": 0.0, "exit": "OPEN", "exit_t": "", "r_extra": 0.0, "win": False})
        trades[-1]["tp_r"] = td / sd
        pos = {"entry_i": i + 1, "entry": entry, "sd": sd, "dir": ddir, "sl": entry - sd * ddir,
               "tp": entry + td * ddir, "hw": 0.0, "tp_r": td / sd}

    # close any still-open position at last bar close
    if pos:
        b = m15[-1]
        r = ((pos["entry"] - b["c"]) / pos["sd"]) if pos["dir"] < 0 else ((b["c"] - pos["entry"]) / pos["sd"])
        trades[-1].update(exit="EOD", exit_t=str(b["t"]), r=r + trades[-1]["r_extra"])
        trades[-1]["win"] = r > 0
        pos = None

    for t in trades:
        t.pop("r_extra", None), t.pop("tp_r", None)
    wins = [t for t in trades if t["r"] > 0]
    report = {
        "window": {"from": str(m15[START]["t"]), "to": str(m15[-1]["t"]), "bars": len(m15) - START},
        "trades": trades,
        "summary": {
            "n": len(trades), "wins": len(wins),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_r": round(sum(t["r"] for t in trades), 2),
            "by_strategy": {},
        },
        "skipped_with_legs": skipped[-90:],
    }
    by = report["summary"]["by_strategy"]
    for t in trades:
        by.setdefault(t["strat"], {"n": 0, "r": 0.0})
        by[t["strat"]]["n"] += 1
        by[t["strat"]]["r"] = round(by[t["strat"]]["r"] + t["r"], 2)
    os.makedirs(DATA, exist_ok=True)
    report["config"] = {"band_ext": band_ext, "mom_standalone": mom_standalone, "tag": args.tag}
    with open(os.path.join(DATA, f"replay_report_{args.tag}.json"), "w") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(DATA, f"skipped_all_{args.tag}.jsonl"), "w") as f:
        for s in skipped:
            f.write(json.dumps(s) + "\n")
    print(json.dumps(report["summary"], indent=1))
    for t in trades:
        print(f"{t['t']}  {t['dir']:<4} {t['strat']:<8} entry={t['entry']:>9.2f} sd={t['sd']:>7.2f} "
              f"reg={t['reg']:<8} z={t['z']:>6} exp={t['exp']}  -> {t['exit']:<9} R={t['r']:+.2f}")


if __name__ == "__main__":
    main()
