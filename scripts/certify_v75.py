"""Certification harness: full v26.26 system (signals + governor + money) on real V75 bars.

Differences vs scripts/replay_v75_week.py (all verified against source + preset):
  - TP multiplier 2.0        (VOL75_FINAL.set InpTpMult=2.0; replay had 2.4)
  - cooldown 3 bars after a loss, 0 after a win (preset + v26.22 win-rearm)
  - Breakout leg DISABLED    (preset InpUseBreakout=false; replay fired BO legs)
  - BandFade spread-gate veto (v26.23: skip when spread > 18% of stop; live V75
    spread ~18.5 units vs BF stop ~22 units -> every BF entry vetoed, exactly
    as observed in the VPS logs)
  - conviction throttle (v26.23): MinScore +1 while the day's realized PnL < 0
  - consecutive-loss pause: 3 losses in a row -> paused until next day (v23)
  - auto-disable: combo with >=20 trades and negative expectancy stops trading,
    every 10th signal probes (v26.20)
  - v26.25/v26.26 money layer (scripts/v75_money.py): calibrated tick value,
    min-lot clamp, 20% real-risk cap, 0.75^consec volume scaling, compounding

Usage: python scripts/certify_v75.py [--equity 50] [--tag cert50] [--time-blocks 3,14,20]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from replay_v75_week import (  # noqa: E402
    load, ema, wilder_atr, wilder_rsi, Egarch, DATA,
    EMA_FAST, EMA_MID, EMA_SLOW, MIN_EMA_SEP, ATR_PERIOD, ATR_LOOKBACK,
    ATR_LOW_PCT, ATR_HIGH_PCT, RSI_OB, RSI_OS, PB_MIN, PB_MAX,
    MOM_BODY_MIN, BB_LEN, SIGMA_EMA_LEN, BAND_Z, BAND_EXT,
    BAND_STOP_SIG, BAND_TGT_SIG, BAND_HOLD_BARS, BAND_MAX_STOP_FRAC,
    MIN_SCORE, MAX_HOLD, EXTEND_MULT, EARLY_CUT_BARS, EARLY_CUT_R,
    HW_EARLY, PLOCK_R, TRAIL_START_R, TRAIL_DIST_R, BE_TRIGGER_R,
    BULL, BEAR, RANGE, HVOL, NOTRADE, RNAME,
)
from v75_money import run_money_replay  # noqa: E402  (kept for the pure money sim)

TP_MULT_CERT = 2.4          # InpTpMult — v26.27 preset aligned to the OOS-validated value
COOLDOWN_LOSS = 3           # InpCoolDownBars (win-rearm: 0 after winners)
SPREAD_V75 = float(os.environ.get("CERT_SPREAD", "18.5"))
                            # live measured spread, index units (env: CERT_SPREAD)
SPREAD_GATE_FRAC = float(os.environ.get("CERT_SPREAD_GATE_FRAC", "0.18"))
                            # InpMaxSpreadATRFrac (env: CERT_SPREAD_GATE_FRAC)
# ---- v26.36 cost model: fills pay the spread (default ON) ------------------
# Bar prices are broker mids; a BUY fills at ask (mid + half), a SELL at bid
# (mid - half); the exit pays the other half, so every round trip costs
# exactly SPREAD_V75 index units. Stop/TP geometry anchors to the REAL fill
# (same distances, same R multiples) like the EA's server-side stops.
# CERT_COST_LEGACY=1 reproduces the pre-2026-09-05 cost-blind engine.
PAY_SPREAD_IN_PNL = os.environ.get("CERT_COST_LEGACY", "0") != "1"
HALF_SPREAD = 0.5 * SPREAD_V75
USD_PER_UNIT_PER_LOT = float(os.environ.get("CERT_USD_PER_UNIT_PER_LOT", "1.009"))
MIN_LOT = float(os.environ.get("CERT_MIN_LOT", "0.01"))
LOT_STEP = float(os.environ.get("CERT_LOT_STEP", "0.01"))
MAX_CONSEC_LOSS = 3         # InpMaxConsecLoss -> pause until next day
AUTO_DISABLE_N = 20         # InpMinTradesToJudge
PROBE_EVERY = 10            # InpProbeEveryN
THROTTLE_K = 10             # family throttle: rolling window size
THROTTLE_R = -3.0           # family throttle: suspend when window R below this
THROTTLE_PROBE = 5          # family throttle: every Nth blocked signal probes
START = 480                 # ~5 days indicator/GARCH burn-in


def certify(equity0: float, blocked_hours: set[int] | None = None, *,
            stop_mult: float = 1.0, be_trigger: float = BE_TRIGGER_R,
            plock_hw: float = 1.0, plock_z: float = PLOCK_R,
            ema_side_filter: bool = False,            pb_min: float | None = None,
            pb_max: float | None = None, legacy_sl: bool = False,
            tp_mult: float = TP_MULT_CERT,
            start=None, end=None,
            family_throttle: bool = False,
            mom_standalone: bool = False,
            pay_spread: bool = PAY_SPREAD_IN_PNL) -> dict:
    blocked_hours = blocked_hours or set()
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
    bb_sd = [None] * len(m15)
    for i in range(BB_LEN - 1, len(m15)):
        sma20[i] = sum(closes[i - BB_LEN + 1:i + 1]) / BB_LEN
        bb_sd[i] = math.sqrt(sum((c - sma20[i]) ** 2 for c in closes[i - BB_LEN + 1:i + 1]) / BB_LEN)

    trades, veto = [], []
    funnel = {"score": 0, "spread-gate": 0, "risk-cap": 0, "paused": 0,
              "auto-disable": 0, "time-block": 0, "family-throttle": 0}
    pos = None
    cooldown_until = -1
    consec = 0
    paused = False
    eq = equity0
    # walk-forward window: slice the trade loop, keep full-history indicator burn-in
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=m15[0]["t"].tzinfo)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=m15[0]["t"].tzinfo)
    i_lo, i_hi = START, len(m15) - 1
    if start is not None:
        i_lo = max(i_lo, next((k for k, b in enumerate(m15) if b["t"] >= start), i_hi))
    if end is not None:
        i_hi = min(i_hi, next((k for k, b in enumerate(m15) if b["t"] > end), i_hi) - 1)
    day_pnl: dict[str, float] = {}
    ledger: dict[str, dict] = {}          # combo -> {n, r}
    disabled: set[str] = set()
    probe_counter: dict[str, int] = {}
    # v26.31 candidate: outcome-adaptive FAMILY throttle. The walk-forward
    # showed no causal regime feature separates PB wins from losses, but the
    # family's own recent R does. Rule: when the last THROTTLE_K PB-family
    # trades sum below THROTTLE_R, PB-family signals need a probe (every
    # THROTTLE_PROBE-th) until the window recovers. No fitted regime constants.
    fam_hist: list[float] = []
    fam_blocked = False
    fam_probe = 0

    def regime_at(i):
        j = h1_idx(m15[i]["t"])
        if h1[j]["t"] == m15[i]["t"] and j > 0:
            j -= 1
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

    for i in range(i_lo, i_hi):
        b = m15[i]
        day = b["t"].strftime("%Y-%m-%d")
        prev_day = m15[i - 1]["t"].strftime("%Y-%m-%d")
        if day != prev_day and paused:
            paused = False          # EA: new session day lifts the pause

        # per-bar feeds
        if i >= 1:
            lr = math.log(closes[i] / closes[i - 1])
            sig_now, warm = garch.update(lr)
            if sig_init:
                a_s = 2.0 / (SIGMA_EMA_LEN + 1)
                sig_ema = a_s * sig_now + (1 - a_s) * sig_ema
            else:
                sig_ema, sig_init = sig_now, True
        reg, _pct = regime_at(i)
        atr_hist.append(atr[i])
        if len(atr_hist) > ATR_LOOKBACK + 10:
            atr_hist.pop(0)

        z_dev = math.log(b["c"] / sma20[i]) / sig_now if sma20[i] else 0.0
        if warm:
            z_dev = garch.z
        exp_ratio = sig_now / sig_ema if sig_ema > 0 else 0.0

        # ---- manage open position ------------------------------------------
        if pos and i >= pos["entry_i"]:
            p = pos
            if p["dir"] < 0:
                hit_sl, hit_tp = b["h"] >= p["sl"], b["l"] <= p["tp"]
            else:
                hit_sl, hit_tp = b["l"] <= p["sl"], b["h"] >= p["tp"]
            closed = False
            if hit_sl and not hit_tp:
                # HONEST booking: exit at the ACTUAL stop level, which BE/trailing
                # may have moved since entry (the EA books the real fill price).
                # legacy_sl reproduces the old -1.0R-always accounting artifact.
                r = (-1.0 + p["r_extra"]) if legacy_sl else (
                    p["dir"] * (p["sl"] - p["entry"]) / p["sd"] + p["r_extra"])
                reason = "BE" if abs(r) < 0.05 else "SL"
                closed = True
            elif hit_tp and not hit_sl:
                r = p["tp_r"] + p["r_extra"]; reason = "TP"; closed = True
            elif hit_sl and hit_tp:
                r = (-1.0 + p["r_extra"]) if legacy_sl else (
                    p["dir"] * (p["sl"] - p["entry"]) / p["sd"] + p["r_extra"])
                reason = "SL(ambig)"; closed = True
            if not closed:
                best = (p["entry"] - b["l"]) / p["sd"] if p["dir"] < 0 else (b["h"] - p["entry"]) / p["sd"]
                r_close = (p["entry"] - b["c"]) / p["sd"] if p["dir"] < 0 else (b["c"] - p["entry"]) / p["sd"]
                p["hw"] = max(p["hw"], best)
                held = i - p["entry_i"]
                reason = None
                if p["hw"] >= plock_hw and 0 < r_close <= plock_z:
                    reason = "PLOCK"
                elif held >= EARLY_CUT_BARS and r_close <= EARLY_CUT_R and p["hw"] < HW_EARLY:
                    reason = "ECUT"
                elif held >= MAX_HOLD:
                    if r_close > 0.2:
                        reason = None
                    elif held >= int(MAX_HOLD * EXTEND_MULT):
                        reason = None if r_close > 0.2 else "TIME_EXT"
                    else:
                        reason = "TIME"
                if reason:
                    r = r_close + p["r_extra"]; closed = True
                else:
                    if p["hw"] >= be_trigger:
                        be = p["entry"] - 2e-6 if p["dir"] < 0 else p["entry"] + 2e-6
                        if (p["dir"] < 0 and be < p["sl"]) or (p["dir"] > 0 and be > p["sl"]):
                            p["sl"] = be
                    if p["hw"] >= TRAIL_START_R:
                        ns = b["c"] + TRAIL_DIST_R * p["sd"] if p["dir"] < 0 else b["c"] - TRAIL_DIST_R * p["sd"]
                        if (p["dir"] < 0 and ns < p["sl"]) or (p["dir"] > 0 and ns > p["sl"]):
                            p["sl"] = ns
            if closed:
                t = trades[-1]
                t.update(exit=reason, exit_t=str(b["t"]), r=round(r, 3), win=r > 0)
                pos = None
                # ---- EA close bookkeeping ---------------------------------
                eq += t["eff_risk"] * r
                consec = 0 if r > 0 else consec + 1
                if consec >= MAX_CONSEC_LOSS:
                    paused = True
                day_pnl.setdefault(day, 0.0)
                day_pnl[day] += t["eff_risk"] * r
                led = ledger.setdefault(t["strat"], {"n": 0, "r": 0.0})
                led["n"] += 1; led["r"] += r
                if (t["strat"] not in disabled and led["n"] >= AUTO_DISABLE_N
                        and led["r"] / led["n"] < 0.0):
                    disabled.add(t["strat"])
                if family_throttle and t["strat"] in ("PB", "MOM+PB"):
                    fam_hist.append(r)
                    if len(fam_hist) > THROTTLE_K:
                        fam_hist.pop(0)
                    fam_blocked = (len(fam_hist) >= THROTTLE_K
                                   and sum(fam_hist) < THROTTLE_R)
                cooldown_until = i if r > 0 else i + COOLDOWN_LOSS   # win-rearm

        if pos is not None or i <= cooldown_until:
            continue

        # ---- signal evaluation ----------------------------------------------
        if b["t"].hour in blocked_hours:
            funnel["time-block"] += 1
            continue
        if paused:
            funnel["paused"] += 1
            continue

        min_eff = MIN_SCORE + (1 if day_pnl.get(day, 0.0) < 0 else 0)  # conviction
        legs = []
        rng_ = b["h"] - b["l"]
        body = b["c"] - b["o"]
        if rng_ > 0 and abs(body) / rng_ >= MOM_BODY_MIN:
            if body > 0 and abs(body) / rng_ > 0.55:
                legs.append(("MOM", 1, 3.0))
            elif body < 0 and abs(body) / rng_ > 0.55:
                legs.append(("MOM", -1, 3.0))
        if reg == RANGE and i >= 1 and rsi[i] is not None:
            bb_l = sma20[i] - 2 * bb_sd[i]
            bb_u = sma20[i] + 2 * bb_sd[i]
            if closes[i - 1] <= bb_l and b["c"] > bb_l and rsi[i] < RSI_OS:
                legs.append(("MR", 1, 3.8))
            if closes[i - 1] >= bb_u and b["c"] < bb_u and rsi[i] > RSI_OB:
                legs.append(("MR", -1, 3.8))
        bf_geo_ok, bf_stop_f, bf_tgt_f = False, 0.0, 0.0
        if reg in (RANGE, HVOL) and sig_init and warm:
            if exp_ratio > BAND_EXT:
                if z_dev >= BAND_Z or z_dev <= -BAND_Z:
                    bars = BAND_HOLD_BARS
                    sigma_h = sig_now * math.sqrt(bars)
                    stop_f = BAND_STOP_SIG * sigma_h
                    tgt_f = BAND_TGT_SIG * sigma_h
                    if tgt_f / stop_f >= 2.5 and stop_f <= BAND_MAX_STOP_FRAC:
                        d = -1 if z_dev >= BAND_Z else 1
                        legs.append(("BF", d, 4.2))
                        bf_geo_ok, bf_stop_f, bf_tgt_f = True, stop_f, tgt_f
        if reg in (BULL, BEAR) and rsi[i] is not None:
            d = 1 if reg == BULL else -1
            pb = abs(b["c"] - eF[i])
            lo_pb = (PB_MIN if pb_min is None else pb_min) * atr[i]
            hi_pb = (PB_MAX if pb_max is None else pb_max) * atr[i]
            if lo_pb <= pb <= hi_pb:
                ok = True
                if ema_side_filter:
                    # only take the pullback while price is still on the trend side
                    # of EMA20 (a close through EMA20 = pullback already failed)
                    if d > 0 and b["c"] <= eF[i]:
                        ok = False
                    if d < 0 and b["c"] >= eF[i]:
                        ok = False
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
        # BO leg omitted: preset InpUseBreakout=false

        buy = sum(s for _, d, s in legs if d > 0)
        sell = sum(s for _, d, s in legs if d < 0)
        nbuy = sum(1 for _, d, _ in legs if d > 0)
        nsell = sum(1 for _, d, _ in legs if d < 0)
        # v26.23 lone-momentum demotion (deployed rule). mom_standalone=True
        # (InpMomentumStandalone) disables it — registered duel arm only.
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
            funnel["score"] += 1
            continue

        strat = "+".join(n for n, d, _ in legs if d == ddir)

        # ---- governor: auto-disable + probe ----------------------------------
        if strat in disabled:
            probe_counter[strat] = probe_counter.get(strat, 0) + 1
            if probe_counter[strat] % PROBE_EVERY != 0:
                funnel["auto-disable"] += 1
                continue
        # ---- v26.31 candidate: family throttle (PB-family rolling window) -----
        # (MOM+PB always contains a PB leg; lone-MOM is demoted before this point,
        # so keying on the PB leg covers exactly PB and MOM+PB.)
        if family_throttle and fam_blocked and any(n == "PB" for n, d, _ in legs):
            fam_probe += 1
            if fam_probe % THROTTLE_PROBE != 0:
                funnel["family-throttle"] += 1
                continue

        # ---- stop geometry ----------------------------------------------------
        nb = m15[i + 1]
        entry = nb["o"]
        if pay_spread:
            entry = entry + HALF_SPREAD * ddir   # BUY fills at ask, SELL at bid
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
            sd *= stop_mult
            td = tp_mult * sd
        sd = min(sd, entry * 0.03)

        # ---- governor: spread gate (v26.23, exact rule) ------------------------
        if SPREAD_GATE_FRAC > 0 and SPREAD_V75 > SPREAD_GATE_FRAC * sd:
            funnel["spread-gate"] += 1
            veto.append({"t": str(nb["t"]), "strat": strat, "sd": round(sd, 1),
                         "reason": f"spread {SPREAD_V75} > {SPREAD_GATE_FRAC*100:.0f}% of {sd:.1f}"})
            continue

        # ---- v26.26 money chain (per-symbol env: CERT_USD_PER_UNIT_PER_LOT,
        # CERT_MIN_LOT, CERT_LOT_STEP — V75 defaults preserved) ----------------
        risk_money = eq * 0.005
        risk_per_lot = sd * USD_PER_UNIT_PER_LOT
        vol = risk_money / risk_per_lot
        vol = (int(vol / LOT_STEP)) * LOT_STEP
        vol = round(vol, 6)
        if vol < MIN_LOT:
            vol = MIN_LOT
        scale = max(0.75 ** consec, 0.30) if consec > 0 else 1.0
        vol = round(vol * scale, 6)
        if vol < MIN_LOT:
            vol = MIN_LOT
        eff_risk = vol * risk_per_lot
        if eff_risk > eq * 0.20:
            funnel["risk-cap"] += 1
            veto.append({"t": str(nb["t"]), "strat": strat, "sd": round(sd, 1),
                         "reason": f"min-lot risk ${eff_risk:.2f} > cap ${eq*0.20:.2f}"})
            continue

        trades.append({"t": str(nb["t"]), "sig_t": str(b["t"]), "strat": strat,
                       "dir": "SELL" if ddir < 0 else "BUY", "entry": round(entry, 2),
                       "sd": round(sd, 2), "reg": RNAME[reg], "z": round(z_dev, 2),
                       "exp": round(exp_ratio, 3), "atr_pct": round(_pct, 1),
                       "r": 0.0, "exit": "OPEN",
                       "exit_t": "", "r_extra": (-SPREAD_V75 / sd) if pay_spread else 0.0,
                       "win": False,
                       "vol": vol, "eff_risk": round(eff_risk, 2),
                       "risk_pct": round(eff_risk / eq * 100, 1)})
        trades[-1]["tp_r"] = td / sd
        pos = {"entry_i": i + 1, "entry": entry, "sd": sd, "dir": ddir,
               "sl": entry - sd * ddir, "tp": entry + td * ddir,
               "hw": 0.0, "tp_r": td / sd, "r_extra": trades[-1]["r_extra"]}

    if pos:
        b = m15[i_hi]   # mark at the window's last evaluated bar, not the file end
        r = ((pos["entry"] - b["c"]) / pos["sd"]) if pos["dir"] < 0 else ((b["c"] - pos["entry"]) / pos["sd"])
        trades[-1].update(exit="EOD", exit_t=str(b["t"]), r=round(r + trades[-1]["r_extra"], 3), win=r > 0)
        pos = None

    for t in trades:
        t.pop("r_extra", None), t.pop("tp_r", None)

    # equity curve stats
    eqc, peak, maxdd = equity0, equity0, 0.0
    for t in trades:
        eqc += t["eff_risk"] * t["r"]
        peak = max(peak, eqc)
        maxdd = max(maxdd, (peak - eqc) / peak * 100)
    wins = [t for t in trades if t["r"] > 0]
    streak = worst = 0
    for t in trades:
        streak = streak + 1 if t["r"] <= 0 else 0
        worst = max(worst, streak)
    return {
        "equity0": equity0, "equity_final": round(eqc, 2),
        "n": len(trades), "wins": len(wins),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_r": round(sum(t["r"] for t in trades), 2),
        "total_pnl": round(eqc - equity0, 2),
        "max_drawdown_pct": round(maxdd, 1),
        "worst_loss_streak": worst,
        "max_risk_pct": max((t["risk_pct"] for t in trades), default=0),
        "funnel": funnel,
        "by_strategy": {k: {"n": v["n"], "r": round(v["r"], 2)}
                        for k, v in sorted(ledger.items())},
        "auto_disabled": sorted(disabled),
        "trades": trades,
        "veto_sample": veto[-40:],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=50.0)
    ap.add_argument("--tag", default="cert")
    ap.add_argument("--blocks", default="", help="comma-separated hours to block, e.g. 3,14,20")
    ap.add_argument("--stop-mult", type=float, default=1.0, help="scale stop distance (1.0 = preset)")
    ap.add_argument("--be-trigger", type=float, default=BE_TRIGGER_R)
    ap.add_argument("--plock-hw", type=float, default=1.0, help="high-water R to arm PLOCK (1.0 = v26.27)")
    ap.add_argument("--plock-z", type=float, default=PLOCK_R)
    ap.add_argument("--ema-side-filter", action="store_true",
                    help="PB veto when close is through EMA20 against the trend")
    ap.add_argument("--pb-min", type=float, default=None)
    ap.add_argument("--pb-max", type=float, default=None)
    ap.add_argument("--tp-mult", type=float, default=TP_MULT_CERT,
                    help="TP in R (2.4 = v26.27 preset)")
    ap.add_argument("--family-throttle", action="store_true",
                    help="v26.31 candidate: suspend PB-family on rolling -3R/10 window")
    ap.add_argument("--legacy-sl", action="store_true",
                    help="reproduce v26.27 accounting (SL always -1.0R even after BE)")
    ap.add_argument("--start", default="", help="window start (ISO date/time, e.g. 2026-08-09)")
    ap.add_argument("--end", default="", help="window end (exclusive, ISO)")
    args = ap.parse_args()
    blocks = {int(h) for h in args.blocks.split(",") if h.strip()} if args.blocks else set()
    rep = certify(args.equity, blocks, stop_mult=args.stop_mult,
                  be_trigger=args.be_trigger, plock_hw=args.plock_hw,
                  plock_z=args.plock_z, ema_side_filter=args.ema_side_filter,
                  pb_min=args.pb_min, pb_max=args.pb_max, legacy_sl=args.legacy_sl,
                  tp_mult=args.tp_mult,
                  start=datetime.fromisoformat(args.start) if args.start else None,
                  end=datetime.fromisoformat(args.end) if args.end else None,
                  family_throttle=args.family_throttle)
    rep["blocked_hours"] = sorted(blocks)
    path = os.path.join(DATA, f"cert_report_{args.tag}.json")
    with open(path, "w") as f:
        json.dump(rep, f, indent=1)
    s = {k: v for k, v in rep.items() if k not in ("trades", "veto_sample")}
    print(json.dumps(s, indent=1))
    print(f"\nreport: {path}")
    for t in rep["trades"]:
        print(f"{t['t']} {t['dir']:<4} {t['strat']:<8} entry={t['entry']:>9.2f} sd={t['sd']:>6.1f} "
              f"vol={t['vol']:.2f} risk={t['risk_pct']:>4.1f}% {t['exit']:<9} R={t['r']:+.2f} "
              f"Rg={t['r']-t.get('r_extra',0.0):+.2f} $={t['eff_risk']*t['r']:+7.2f}")


if __name__ == "__main__":
    main()
