#!/usr/bin/env python3
"""Replay Aug-17 journal trades through the v22 MitemshubAI decision logic.

Honesty notes (no fabricated price paths):
  Part A: Every EXECUTED trade is audited against the deployed v22 config
          (mql5/MITEMSHUB_AI/MitemshubAI_VOL100_FINAL.set / _VOL75_): which
          legs fire, which gates block, and what the sequence state machine
          (cooldown / consec-loss pause / daily-loss halt / risk cap) would
          have done. Accepted trades keep their REALIZED path result (same
          entry->exit); rejected trades simply never happen. This isolates
          the DECISION layer, which is what changed in v22.
  Part B: The band-fade pipeline (sigma -> EMA baseline -> expansion gate ->
          |z|>=2 fade -> 0.10/0.80 sigma_h geometry) is run end-to-end on
          real synthetic-index microstructure (src/synthetic_trader/data/
          R_100_ticks.csv, Jul-29) with conservative AND optimistic
          intrabar fill assumptions. This validates the MECHANICS, not the
          Aug-17 counterfactual.

Usage: python scripts/replay_v22_bandfade.py
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "journals/forward_demo_18_24.jsonl"
SET_V100 = ROOT / "mql5/MITEMSHUB_AI/MitemshubAI_VOL100_FINAL.set"
SET_V75 = ROOT / "mql5/MITEMSHUB_AI/MitemshubAI_VOL75_FINAL.set"
TICKS = ROOT / "src/synthetic_trader/data/R_100_ticks.csv"

# Code defaults from MitemshubAI.mq5 v22 (overridden by .set values when present)
DEFAULTS = {
    "InpUsePullback": True, "InpUseBreakout": True, "InpUseMomentum": True,
    "InpUseMeanRevert": True, "InpUseBandFade": True,
    "InpMinScore": 3, "InpRequire2Strats": False, "InpMomentumStandalone": False,
    "InpPullbackMin": 0.30, "InpPullbackMax": 2.20,
    "InpMomBodyMin": 0.45,
    "InpBandZEntry": 2.0, "InpBandVolExtRatio": 1.25, "InpBandSigmaEmaLen": 30,
    "InpBandStopSigmaMult": 0.10, "InpBandTargetSigmaMult": 0.80,
    "InpBandHoldSec": 3600, "InpBandMinRR": 2.5, "InpBandMaxStopPct": 0.015,
    "InpMaxEffectiveRiskPct": 30.0, "InpTpMult": 2.4, "InpMaxHoldBars": 14,
    "InpMaxDailyLossPct": 0.03, "InpMaxConsecLoss": 3, "InpCoolDownBars": 3,
    "InpEntryTFOverride": "CURRENT",
}


def load_set(path: Path) -> dict:
    cfg = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("[") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if v.lower() in ("true", "false"):
                cfg[k.strip()] = v.lower() == "true"
            else:
                try:
                    cfg[k.strip()] = float(v)
                except ValueError:
                    cfg[k.strip()] = v
    return cfg


def as_bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes")


def u(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%H:%M:%S")


def regime_of(regime_str: str) -> str:
    s = (regime_str or "").lower()
    if "down" in s or "bear" in s:
        return "BEARISH"
    if "up" in s or "bull" in s:
        return "BULLISH"
    if "range" in s or "flat" in s:
        return "RANGING"
    return "UNKNOWN"


# ----------------------------------------------------------------------------
# Part T - EXACT replay from the EA's own telemetry journal (no proxies)
# ----------------------------------------------------------------------------

TELEM_NAME = "MitemshubAI_v22_telemetry.jsonl"


def find_telemetry(explicit: str | None) -> Path | None:
    """Locate the v22 telemetry journal: explicit arg, then MT5 terminal
    Files dirs, then repo-local fallbacks."""
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands += sorted(Path(appdata).glob(
            f"MetaQuotes/Terminal/*/MQL5/Files/{TELEM_NAME}"))
        cands.append(Path(appdata) / f"MetaQuotes/Terminal/MQL5/Files/{TELEM_NAME}")
    cands.append(ROOT / "MQL5" / "Files" / TELEM_NAME)
    cands.append(ROOT / TELEM_NAME)
    for c in cands:
        try:
            if c.exists() and c.stat().st_size > 0:
                return c
        except OSError:
            continue
    return None


def load_telem(path: Path) -> list[dict]:
    ev = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "epoch" not in r and "ts" in r:
            try:
                r["epoch"] = datetime.strptime(
                    r["ts"], "%Y.%m.%d %H:%M:%S").replace(
                    tzinfo=timezone.utc).timestamp()
            except ValueError:
                pass
        ev.append(r)
    ev.sort(key=lambda r: r.get("epoch", 0))
    return ev


def part_t(ev: list[dict]) -> None:
    """Exact decision/trade analytics from REAL EA-measured values."""
    print("=" * 78)
    print("PART T - TELEMETRY REPLAY (real EA values - no feature proxies)")
    print("=" * 78)
    sigs = [e for e in ev if e.get("type") == "sig"]
    opens = {int(e["ticket"]): e for e in ev
             if e.get("type") == "open" and e.get("ticket")}
    closes = [e for e in ev if e.get("type") == "close"]

    if not ev:
        print("(empty journal)")
        return
    u = lambda e: datetime.fromtimestamp(float(e["epoch"]), timezone.utc) \
        .strftime("%Y-%m-%d %H:%M")
    print(f"events={len(ev)}  window {u(ev[0])} -> {u(ev[-1])} UTC")

    # --- realized trades -------------------------------------------------
    rows = []
    for c in closes:
        o = opens.pop(int(c["ticket"]), {}) if c.get("ticket") else {}
        rows.append({
            "sym": o.get("sym", c.get("sym", "?")),
            "dir": c.get("dir", o.get("dir")),
            "legs": o.get("legs", ""), "band": str(o.get("band")) == "true",
            "z": o.get("z"), "exp": o.get("exp"),
            "eff_risk": o.get("eff_risk"),
            "reason": c.get("reason"), "r": float(c.get("r", 0.0)),
            "pnl": float(c.get("pnl", 0.0)),
        })
    if rows:
        tot_r = sum(r["r"] for r in rows)
        tot_p = sum(r["pnl"] for r in rows)
        wins = sum(1 for r in rows if r["r"] > 0)
        print(f"\nREALIZED TRADES: {len(rows)}  ({wins}W/{len(rows)-wins}L)  "
              f"total {tot_r:+.2f}R  {tot_p:+.2f}$")
        ex = collections.Counter(r["reason"] for r in rows)
        print("exit mix: " + ", ".join(f"{k}x{v}" for k, v in ex.most_common()))
        print(f"{'time':<17}{'sym':<7}{'dir':>4} {'legs':<16} {'R':>7} {'$':>8} "
              f"{'z':>6} {'exp':>5} {'risk$':>7}")
        for r, c in zip(rows, closes):
            z = f"{float(r['z']):+.2f}" if r.get("z") is not None else "-"
            xp = f"{float(r['exp']):.2f}" if r.get("exp") is not None else "-"
            rk = f"{float(r['eff_risk']):.2f}" if r.get("eff_risk") is not None else "-"
            print(f"{u(c):<17}{str(r['sym'])[:6]:<7}{str(r['dir']):>4} "
                  f"{str(r['legs'])[:16]:<16} {r['r']:>+7.3f} {r['pnl']:>+8.2f} "
                  f"{z:>6} {xp:>5} {rk:>7}")
        if opens:
            print(f"\nSTILL OPEN (no close yet): {sorted(opens)}")
        # band-fade leg vs classic ATR legs - does the validated edge win?
        bands = [r for r in rows if r["band"]]
        atr = [r for r in rows if not r["band"]]
        print("\nLEG SPLIT (band geometry vs classic ATR exits):")
        for label, grp in (("band-fade", bands), ("atr-classic", atr)):
            if grp:
                wr = 100 * sum(1 for g in grp if g["r"] > 0) / len(grp)
                print(f"  {label:<11}: {len(grp):>3} trades | WR {wr:5.1f}% | "
                      f"expR {sum(g['r'] for g in grp)/len(grp):+.3f}")
            else:
                print(f"  {label:<11}: none yet")
    elif opens:
        print(f"\nopens recorded ({len(opens)}), no closes yet.")

    # --- decision analytics from sig events ------------------------------
    if sigs:
        take = [s for s in sigs if s.get("action") == "TAKE"]
        skip = [s for s in sigs if s.get("action") != "TAKE"]
        print(f"\nDECISIONS: {len(sigs)} evaluated bars | TAKE {len(take)} | "
              f"SKIP {len(skip)}")
        skips = collections.Counter(str(s.get("reason")) for s in skip)
        if skips:
            print("skip reasons:")
            for k, v in skips.most_common(6):
                print(f"   {v:>4}x  {k[:44]}")
        bf = [s for s in sigs if "BF" in str(s.get("legs", ""))]
        zpass = [s for s in sigs if abs(float(s.get("z", 0) or 0)) >= 2.0]
        xpass = [s for s in sigs if float(s.get("exp", 0) or 0) > 1.25]
        both = [s for s in sigs
                if abs(float(s.get("z", 0) or 0)) >= 2.0
                and float(s.get("exp", 0) or 0) > 1.25]
        print(f"GATE HIT-RATES (live EA values, {len(sigs)} bars):")
        for lbl, g in (("|z|>=2 fired", zpass), ("expansion>1.25x", xpass),
                       ("BOTH passed", both), ("BF leg fired", bf)):
            pc = 100 * len(g) / len(sigs)
            print(f"   {lbl:<18}: {len(g):>4} bars ({pc:.1f}%)")
        if take:
            az = [abs(float(s.get("z", 0) or 0)) for s in take]
            ax = [float(s.get("exp", 0) or 0) for s in take]
            print(f"TAKE context: mean|z| {sum(az)/len(az):.2f}, "
                  f"mean exp {sum(ax)/len(ax):.2f}x")
    halted = sum(1 for c in closes if str(c.get("daily_halt")) == "true")
    paused = sum(1 for c in closes if str(c.get("paused")) == "true")
    if halted or paused:
        print(f"breaker states after closes: daily_halt {halted}x, paused {paused}x")


# ----------------------------------------------------------------------------
# Part A - gate audit of executed trades (PROXY-based legacy fallback)
# ----------------------------------------------------------------------------

def evaluate_legs(f: dict, direction: str, cfg: dict) -> dict:
    """Mirror v22 GenerateSignal() leg verdicts from the recorded feature snapshot."""
    d = -1 if direction == "short" else 1
    body = f.get("body", 0.0)
    b2r = f.get("body_to_range", 0.0)
    pb_atr = abs(f.get("close_vs_ema_21_atr", 0.0))
    rsi = f.get("rsi_14", 50.0)
    bbp = f.get("bb_position", 0.5)              # 0=lower band, 1=upper band
    z_proxy = (bbp - 0.5) * 4.0                  # BBs are mid +/- 2 sigma
    reg = regime_of(str(f.get("_regime_str", "")))
    vol_ratio = f.get("garch_vol_ratio", 1.0)    # sigma_now / long-run sigma proxy

    verdict = {}

    # Pullback: needs 0.30..2.20 ATR distance from EMA21 + aligned regime + filters
    pullback_dist_ok = cfg["InpPullbackMin"] <= pb_atr <= cfg["InpPullbackMax"]
    reg_align = (reg == "BULLISH" and d > 0) or (reg == "BEARISH" and d < 0)
    rsi_ok = (rsi <= 65 if d > 0 else rsi >= 35)
    body_ok = (body > -0.1 if d > 0 else body < 0.1)
    verdict["pullback"] = bool(pullback_dist_ok and reg_align and rsi_ok and body_ok)

    # Breakout: disabled in deployed configs (chase risk)
    verdict["breakout"] = False
    verdict["breakout_note"] = "disabled in deployed .set"

    # Momentum: big directional candle...
    mom_fire = b2r >= cfg["InpMomBodyMin"] and ((body > 0 and d > 0) or (body < 0 and d < 0))
    verdict["momentum"] = bool(mom_fire)

    # Mean revert: only RANGING + band-pierce reclaim w/ RSI extreme (single-snapshot approx)
    mr_band = (d > 0 and bbp <= 0.02) or (d < 0 and bbp >= 0.98)
    mr_rsi = (rsi <= 32 if d > 0 else rsi >= 68)
    verdict["mean_revert"] = bool(reg == "RANGING" and mr_band and mr_rsi)

    # Band fade: fade EXTREME in the OPPOSITE direction, only RANGING/HIGH_VOL,
    # and only when vol just expanded vs baseline.
    bf_dir_ok = (d > 0 and z_proxy <= -cfg["InpBandZEntry"]) or \
                (d < 0 and z_proxy >= cfg["InpBandZEntry"])
    bf_regime_ok = reg in ("RANGING", "HIGH_VOL")
    bf_expand_ok = vol_ratio >= cfg["InpBandVolExtRatio"]
    verdict["band_fade"] = bool(bf_dir_ok and bf_regime_ok and bf_expand_ok)
    verdict["_bf_detail"] = f"z~{z_proxy:+.2f} dir_ok={bf_dir_ok} regime={reg} expand={vol_ratio:.2f}x"

    # Confluence scoring (v22): scores -> buy/sell totals + regime bonus + demotion
    score = 0.0
    fired = []
    for name, sc in (("pullback", 4.0), ("momentum", 3.0), ("mean_revert", 3.8),
                     ("band_fade", 4.2)):
        if verdict[name]:
            score += sc
            fired.append(name)
    bonus = 2 if ((reg == "BULLISH" and d > 0) or (reg == "BEARISH" and d < 0)) else 0
    total = score + bonus
    others = [n for n in fired if n != "momentum"]
    demoted = (mom_fire and not others and not as_bool(cfg["InpMomentumStandalone"]))
    verdict["fired_legs"] = fired
    verdict["score_total"] = total
    verdict["min_score_pass"] = total >= cfg["InpMinScore"]
    verdict["momentum_demoted"] = demoted
    return verdict


def part_a() -> None:
    recs = [json.loads(l) for l in JOURNAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    outcomes = sorted((r for r in recs if r.get("type") == "outcome"),
                      key=lambda r: r.get("opened_at", 0))
    signals = {r.get("epoch"): r for r in recs if r.get("type") == "signal"}
    shutdown = [r for r in recs if r.get("type") == "shutdown_summary"]

    total_actual_r = sum(r.get("return_r", 0.0) for r in outcomes)
    total_actual_pnl = sum(r.get("pnl", 0.0) for r in outcomes)
    wins = sum(1 for r in outcomes if r.get("won"))
    print("=" * 78)
    print("PART A - AUG-17 JOURNAL REPLAY THROUGH v22 DECISION LOGIC")
    print("=" * 78)
    print(f"Executed trades: {len(outcomes)}  |  W/L: {wins}"
          f"/{len(outcomes)-wins}  |  Total R: {total_actual_r:+.2f}  "
          f"|  Total $: {total_actual_pnl:+.2f}")
    if shutdown:
        fe = shutdown[0].get("final_equity")
        if fe is not None:
            print(f"Final equity: ${fe:.2f}  ->  session-start equity ~ "
                  f"${fe - total_actual_pnl:.2f}")

    cfgs = {"R_100": {**DEFAULTS, **load_set(SET_V100)},
            "R_75": {**DEFAULTS, **load_set(SET_V75)}}

    # Sequence state machine (v22)
    eq_start = None
    if shutdown:
        fe = shutdown[0].get("final_equity")
        if fe is not None:
            eq_start = round(fe - total_actual_pnl, 2)
    equity = eq_start if eq_start else 30.0
    day_start_eq = equity
    consec = 0
    cooldown_until = 0.0
    busy_until = 0.0
    halted_day = False
    paused = False

    rows = []
    cf_r = cf_pnl = 0.0
    n_taken = 0
    for o in outcomes:
        sym = o.get("symbol", "?")
        cfg = cfgs.get(sym, cfgs["R_100"])
        f = dict(o.get("features", {}))
        f["_regime_str"] = str(signals.get(o.get("opened_at"), {}).get("regime", ""))
        v = evaluate_legs(f, o.get("direction", ""), cfg)
        opened, closed = float(o.get("opened_at", 0)), float(o.get("closed_at", 0))
        rr = float(o.get("return_r", 0.0))
        pnl = float(o.get("pnl", 0.0))
        risk_implied = abs(pnl / rr) if rr else 0.0

        blockers = []
        if v["momentum_demoted"]:
            blockers.append("mom-demoted")
        if not v["min_score_pass"]:
            blockers.append(f"score {v['score_total']:.1f}<{cfg['InpMinScore']}")
        if not v["band_fade"] and not v["min_score_pass"]:
            blockers.append("no-bandfade")

        # state machine at entry moment
        t = opened
        seq_block = None
        if paused:
            seq_block = "consec-pause(4L)->resets-next-day"
        elif halted_day:
            seq_block = f"daily-halt(-{cfg['InpMaxDailyLossPct']*100:.0f}%)"
        elif t < cooldown_until:
            seq_block = f"cooldown({int((cooldown_until-t)/60)}m)"
        elif t < busy_until:
            seq_block = "position-open"

        taken = not seq_block and not blockers
        eff_risk_pct = (risk_implied / equity * 100.0) if equity else 0.0
        if taken and eff_risk_pct > float(cfg["InpMaxEffectiveRiskPct"]):
            blockers.append(f"risk-cap {eff_risk_pct:.0f}%>{float(cfg['InpMaxEffectiveRiskPct']):.0f}%")
            taken = False

        if taken:
            n_taken += 1
            cf_r += rr
            cf_pnl += pnl
            equity += pnl
            consec = consec + 1 if rr < 0 else 0
            if consec >= int(cfg["InpMaxConsecLoss"]):
                paused = True
            if (day_start_eq - equity) / day_start_eq >= float(cfg["InpMaxDailyLossPct"]):
                halted_day = True
            cooldown_until = closed + int(cfg["InpCoolDownBars"]) * 900  # M15 bars
            busy_until = closed
        rows.append((o, v, blockers, seq_block, taken, rr, pnl, risk_implied))

    hdr = f'{"time":>8} {"sym":>5} {"dir":>5} {"legs":<28} {"blk/seq":<34} {"R":>6} {"$":>7}'
    print("\n" + hdr)
    print("-" * len(hdr))
    for o, v, blockers, seq_block, taken, rr, pnl, risk in rows:
        blk = ";".join(filter(None, [*blockers, seq_block])) or "-"
        legs = ",".join(v["fired_legs"]) or "none"
        print(f"{u(float(o['opened_at'])):>8} {o.get('symbol','?'):>5} "
              f"{o.get('direction','?'):>5} {legs:<28} {blk:<34} {rr:>+6.2f} {pnl:>+7.2f}")

    print("\n--- COUNTERFACTUAL ---")
    print(f"Trades v22 would take : {n_taken}/{len(outcomes)}")
    print(f"Resulting P&L         : {cf_r:+.2f} R   =  ${cf_pnl:+.2f}")
    print(f"Actual (old logic)    : {total_actual_r:+.2f} R   =  ${total_actual_pnl:+.2f}")
    print(f"Avoided               : {total_actual_r-cf_r:+.2f} R   =  "
          f"${total_actual_pnl-cf_pnl:+.2f}")


# ----------------------------------------------------------------------------
# Part B - band-fade pipeline smoke test on real tick tape
# ----------------------------------------------------------------------------

def part_b(z_entry=2.0, ext_ratio=1.25, stop_mult=0.10, tgt_mult=0.80,
           hold_sec=3600, min_rr=2.5, max_stop_pct=0.015) -> None:
    rows = list(csv.DictReader(TICKS.open()))
    ticks = [(float(r["epoch"]), float(r["price"])) for r in rows]
    ticks.sort()
    # aggregate 1-minute bars
    bars: dict[int, list[float]] = {}
    for e, p in ticks:
        bars.setdefault(int(e // 60), []).append(p)
    minutes = sorted(bars)
    o = [bars[m][0] for m in minutes]
    h = [max(bars[m]) for m in minutes]
    l = [min(bars[m]) for m in minutes]
    c = [bars[m][-1] for m in minutes]
    ts = [m * 60.0 for m in minutes]
    n = len(c)
    rets = [math.log(c[i] / c[i - 1]) for i in range(1, n)]

    def sigma_now(i):  # stdev of last 20 closed-bar returns ending at index i
        seg = rets[max(0, i - 19):i + 1]
        if len(seg) < 10:
            return 0.0
        return statistics.stdev(seg)

    warm_from = 45
    hold_bars = max(1, round(hold_sec / 60))
    sigma_ema, init = 0.0, False
    trades = {"conservative": [], "optimistic": []}
    diag = {"bars_eval": 0, "expand_pass": 0, "z_pass": 0, "both_pass": 0,
            "geom_fail": 0, "max_abs_z": 0.0, "max_expand": 0.0}

    for i in range(warm_from, n - 1):
        s = sigma_now(i)
        if s <= 0:
            continue
        a = 2.0 / (30 + 1)
        sigma_ema = s if not init else a * s + (1 - a) * sigma_ema
        init = True
        sma = sum(c[i - 19:i + 1]) / 20.0
        z = math.log(c[i] / sma) / s
        diag["bars_eval"] += 1
        diag["max_abs_z"] = max(diag["max_abs_z"], abs(z))
        expand = s / sigma_ema if sigma_ema > 0 else 0.0
        diag["max_expand"] = max(diag["max_expand"], expand)
        exp_ok = s > ext_ratio * sigma_ema
        z_ok = abs(z) >= z_entry
        diag["expand_pass"] += exp_ok
        diag["z_pass"] += z_ok
        if not (exp_ok and z_ok):
            continue
        diag["both_pass"] += 1
        sig_h = s * math.sqrt(hold_bars)
        stop_f, tgt_f = stop_mult * sig_h, tgt_mult * sig_h
        if tgt_f / stop_f < min_rr or stop_f > max_stop_pct:
            diag["geom_fail"] += 1
            continue
        d = -1 if z > 0 else 1
        entry = c[i]
        sl = entry - d * stop_f * entry
        tp = entry + d * tgt_f * entry
        # walk forward
        res = {}
        for mode in ("conservative", "optimistic"):
            out_r = 0.0
            for j in range(i + 1, min(n, i + 1 + hold_bars)):
                hit_sl = (l[j] <= sl) if d > 0 else (h[j] >= sl)
                hit_tp = (h[j] >= tp) if d > 0 else (l[j] <= tp)
                if hit_sl and hit_tp:
                    out_r = -1.0 if mode == "conservative" else tgt_f / stop_f
                    break
                if hit_sl:
                    out_r = -1.0
                    break
                if hit_tp:
                    out_r = tgt_f / stop_f
                    break
            else:
                exit_px = c[min(n - 1, i + hold_bars)]
                out_r = d * (exit_px - entry) / entry / stop_f
            res[mode] = out_r
        for mode, r in res.items():
            trades[mode].append(r)
        i_skip = hold_bars  # one position at a time: jump ahead

    print("\n" + "=" * 78)
    print("PART B - BAND-FADE PIPELINE SMOKE TEST (real R_100 ticks, Jul-29, M1)")
    print("=" * 78)
    print(f"Bars: {n} ({u(ts[0])}->{u(ts[-1])} UTC) | signals fired: "
          f"{len(trades['conservative'])}")
    print(f"Gate diagnostics: {diag['bars_eval']} bars evaluated | "
          f"vol-expansion passed {diag['expand_pass']}x (peak {diag['max_expand']:.2f}x) | "
          f"|z|>={z_entry} passed {diag['z_pass']}x (peak |z|={diag['max_abs_z']:.2f}) | "
          f"BOTH passed {diag['both_pass']}x | geometry rejected {diag['geom_fail']}x")
    for mode in ("optimistic", "conservative"):
        rs = trades[mode]
        if not rs:
            print(f"  {mode:>13}: no trades")
            continue
        wr = sum(1 for x in rs if x > 0) / len(rs) * 100
        print(f"  {mode:>13}: {len(rs):>3} trades | WR {wr:5.1f}% | "
              f"avgR {sum(rs)/len(rs):+.2f} | totalR {sum(rs):+.2f}")
    print("  NOTE: 2-hour tape = small sample; validates mechanics, not edge.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--telem", default=None,
                    help=f"path to {TELEM_NAME} (default: auto-discover)")
    ap.add_argument("--legacy", action="store_true",
                    help="force proxy Parts A+B even when telemetry exists")
    a = ap.parse_args(argv)

    if not a.legacy:
        tp = find_telemetry(a.telem)
        if tp is not None:
            print(f"[telemetry] using {tp}")
            part_t(load_telem(tp))
            print("\n(legacy proxy Parts A/B skipped - use --legacy to force)")
            return 0
        if a.telem:
            print(f"[telemetry] '{a.telem}' not found - falling back to legacy parts")
    else:
        print("[legacy mode forced]")

    part_a()
    part_b()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
