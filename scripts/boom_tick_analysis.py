#!/usr/bin/env python3
"""Boom 1000 live tick microstructure analysis vs 60-day backtest assumptions.

Sources:
  * artifacts/ticks/MITEMSHUB_ticks_Boom_1000_Index_*.csv  (live EA tick recorder)
  * artifacts/npz/Boom_1000_Index_M5.npy                    (60-day M5 cache)

Questions answered:
  1. Does the live tick feed match the 60-day backtest assumptions?
     (spike rate, spike body distribution, ATR, retrace probability)
  2. How many small-spike fade opportunities does the EA's 2.8x threshold skip?
  3. Are small spikes (lower threshold bands) fadeable profitably?
  4. How much entry-price edge does tick-triggered (intra-bar) entry capture
     versus waiting for the M5 close + retrace?

Usage:
    .venv/Scripts/python.exe scripts/boom_tick_analysis.py
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mt5_data import load_m5
from synthlib import slice_60d, detect_spikes, compute_atr

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
TICK_DIR = ART / "ticks"

# Deployed EA v25.1 fade parameters (BOOM1000_CB.set)
DEPLOYED = {
    "spike_threshold": 2.8,
    "retrace_lo": 0.30,
    "retrace_hi": 0.50,
    "sl_mult": 0.4,
    "tp_mult": 3.2,
    "cooldown": 1,
    "window": 5,        # bars after spike where fade entry is valid
    "exit_scan": 7,     # bars scanned for SL/TP hit
}

SWEEP_THRESHOLDS = [1.5, 1.8, 2.0, 2.2, 2.5, 2.8, 3.2, 3.6]


# ---------------------------------------------------------------------------
# Tick loading
# ---------------------------------------------------------------------------
def load_ticks() -> list[tuple[int, float]]:
    """Load (epoch, bid) from all tick CSVs, sorted by time."""
    rows: list[tuple[int, float]] = []
    for f in sorted(TICK_DIR.glob("MITEMSHUB_ticks_Boom_1000_Index_*.csv")):
        with open(f, newline="") as fh:
            for rec in csv.DictReader(fh):
                try:
                    rows.append((int(rec["ts"]), float(rec["bid"])))
                except (ValueError, KeyError):
                    continue
    rows.sort(key=lambda r: r[0])
    return rows


def tick_stats(ticks):
    """Basic tick-rate / delta distribution stats."""
    if len(ticks) < 100:
        return {}
    span_h = (ticks[-1][0] - ticks[0][0]) / 3600.0
    deltas = [ticks[i][1] - ticks[i - 1][1] for i in range(1, len(ticks))]
    pos = sorted(d for d in deltas if d > 0)
    neg = sorted(-d for d in deltas if d < 0)

    def pct(sorted_vals, p):
        if not sorted_vals:
            return 0.0
        return sorted_vals[min(int(len(sorted_vals) * p), len(sorted_vals) - 1)]

    return {
        "span_hours": round(span_h, 2),
        "ticks": len(ticks),
        "ticks_per_hour": round(len(ticks) / max(span_h, 1e-9), 0),
        "pos_delta_pct": {f"p{p}": round(pct(pos, p / 100.0), 4) for p in (50, 90, 99, 995, 999)},
        "neg_delta_pct": {f"p{p}": round(pct(neg, p / 100.0), 4) for p in (50, 90, 99)},
        "max_pos": round(pos[-1], 3) if pos else 0.0,
        "max_neg": round(neg[-1], 3) if neg else 0.0,
    }


def detect_tick_spikes(ticks, target_rate=1 / 1000):
    """Boom tick spike = large positive inter-tick jump.

    Threshold chosen so observed rate matches Deriv's '1 spike per 1000 ticks'.
    Returns (spike list, threshold). Each spike: dict(tick_idx, epoch, pre, post, jump).
    """
    deltas = [(i, ticks[i][1] - ticks[i - 1][1]) for i in range(1, len(ticks))]
    pos = sorted((d for _, d in deltas if d > 0), reverse=True)
    n_spikes = max(1, int(len(deltas) * target_rate))
    if len(pos) < n_spikes:
        return [], 0.0
    threshold = pos[n_spikes - 1]
    spikes = [
        {"tick_idx": i, "epoch": ticks[i][0], "pre": ticks[i - 1][1],
         "post": ticks[i][1], "jump": d}
        for i, d in deltas if d >= threshold
    ]
    return spikes, round(threshold, 3)


def spike_retrace_after_ticks(ticks, spikes, horizon_s=300):
    """For each tick spike, how far/fast does price retrace downward afterwards?

    Boom: spike UP, then slow decay. Retrace fraction = (post - min_low) / jump.
    Returns list of dicts with retrace fractions at 60s/120s/300s and time-to-30%.
    """
    out = []
    n = len(ticks)
    for sp in spikes:
        i0 = sp["tick_idx"]
        t0 = sp["epoch"]
        post = sp["post"]
        jump = sp["jump"]
        if jump <= 0:
            continue
        rec = {"epoch": t0, "jump": round(jump, 3)}
        marks = {60: None, 120: None, 300: None}
        t30 = None
        t50 = None
        for j in range(i0 + 1, n):
            dt = ticks[j][0] - t0
            if dt > horizon_s:
                break
            px = ticks[j][1]
            retr = (post - px) / jump
            for m in marks:
                if marks[m] is None and dt >= m:
                    marks[m] = round(retr, 3)
            if t30 is None and retr >= 0.30:
                t30 = dt
            if t50 is None and retr >= 0.50:
                t50 = dt
        rec.update({f"retrace_{m}s": marks[m] for m in marks},
                   t_to_30pct_s=t30, t_to_50pct_s=t50)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# M5 rebuild from ticks
# ---------------------------------------------------------------------------
def rebuild_m5(ticks, bucket=300):
    bars = {}
    for ts, bid in ticks:
        k = ts - ts % bucket
        b = bars.get(k)
        if b is None:
            bars[k] = {"epoch": k, "open": bid, "high": bid, "low": bid, "close": bid}
        else:
            b["high"] = max(b["high"], bid)
            b["low"] = min(b["low"], bid)
            b["close"] = bid
    return [bars[k] for k in sorted(bars)]


# ---------------------------------------------------------------------------
# Fade backtest (EA-faithful, parameterized)
# ---------------------------------------------------------------------------
def fade_sim(bars, spike_indices, atr_vals, p=DEPLOYED):
    """Post-spike fade, Boom 1000 (spike UP -> SELL). Mirrors EA v25.1 filters."""
    trades = []
    cooldown = 0
    opportunities = 0
    for sidx in spike_indices:
        spike = bars[sidx]
        body = abs(spike["close"] - spike["open"])
        spike_high = spike["high"]
        spike_low = spike["low"]
        if body <= 0:
            continue
        for j in range(sidx + 1, min(sidx + p["window"] + 1, len(bars))):
            if cooldown > 0:
                cooldown -= 1
                continue
            if j >= len(atr_vals) or atr_vals[j] <= 0:
                continue
            price = bars[j]["close"]
            if price >= spike_high:
                continue
            retrace = (spike_high - price) / body
            if not (p["retrace_lo"] <= retrace <= p["retrace_hi"]):
                continue
            opportunities += 1
            entry = price
            sl = entry + p["sl_mult"] * atr_vals[j]
            tp = entry - p["tp_mult"] * atr_vals[j]
            if tp > spike_low:
                tp = spike_low - atr_vals[j] * 0.2
            result, reason = None, "TIME"
            for k in range(j + 1, min(j + 1 + p["exit_scan"], len(bars))):
                if bars[k]["high"] >= sl:
                    result, reason = -1.0, "STOP"
                    break
                if bars[k]["low"] <= tp:
                    result, reason = p["tp_mult"] / p["sl_mult"], "TARGET"
                    break
            if result is None:
                k = min(j + p["exit_scan"], len(bars) - 1)
                result = (entry - bars[k]["close"]) / (sl - entry) if sl != entry else 0.0
            trades.append({
                "entry_epoch": bars[j]["epoch"], "r": result, "reason": reason,
                "spike_idx": sidx, "spike_body": body, "retrace": retrace,
            })
            cooldown = p["cooldown"]
            break
    return trades, opportunities


def stats_row(trades, days):
    if not trades:
        return {"trades": 0}
    wins = [t for t in trades if t["r"] > 0]
    losses = [t for t in trades if t["r"] < 0]
    gw = sum(t["r"] for t in wins)
    gl = sum(-t["r"] for t in losses)
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": len(trades),
        "per_day": round(len(trades) / days, 2),
        "wr": round(100 * len(wins) / len(trades), 1),
        "pf": round(gw / gl, 2) if gl > 0 else 99.0,
        "exp_r": round(sum(t["r"] for t in trades) / len(trades), 3),
        "max_dd": round(dd, 2),
        "exits": {k: sum(1 for t in trades if t["reason"] == k)
                  for k in ("TARGET", "STOP", "TIME")},
    }


# ---------------------------------------------------------------------------
def main():
    print("=" * 90)
    print("BOOM 1000 — LIVE TICK MICROSTRUCTURE vs 60-DAY BACKTEST ASSUMPTIONS")
    print("=" * 90)

    out: dict = {}

    # ---- Part 1: live ticks -------------------------------------------------
    ticks = load_ticks()
    if len(ticks) < 200:
        print("Not enough tick data (need >=200 rows in artifacts/ticks/).")
        return 1
    ts0 = datetime.fromtimestamp(ticks[0][0], tz=timezone.utc)
    ts1 = datetime.fromtimestamp(ticks[-1][0], tz=timezone.utc)
    print(f"\nLive ticks: {len(ticks)} rows  {ts0:%m-%d %H:%M} -> {ts1:%m-%d %H:%M} UTC")

    tstats = tick_stats(ticks)
    print(f"Tick rate: {tstats['ticks_per_hour']:.0f}/h  span {tstats['span_hours']}h")
    print(f"Tick delta pctiles  up:  {tstats['pos_delta_pct']}  max={tstats['max_pos']}")
    print(f"Tick delta pctiles  dn:  {tstats['neg_delta_pct']}  max={tstats['max_neg']}")

    spikes, thr = detect_tick_spikes(ticks)
    span_h = tstats["span_hours"]
    gaps_t = [spikes[i + 1]["tick_idx"] - spikes[i]["tick_idx"] for i in range(len(spikes) - 1)]
    gaps_m = [g * (span_h * 3600 / len(ticks)) / 60 for g in gaps_t]
    print(f"\nTick-level spikes: {len(spikes)}  threshold={thr:+.3f} pts "
          f"(rate={len(spikes)/max(tstats['ticks'],1)*1000:.2f}/1000 ticks, "
          f"{len(spikes)/max(span_h,1e-9):.1f}/h)")
    if gaps_m:
        print(f"Inter-spike gap: median={statistics.median(gaps_m):.0f}min "
              f"mean={statistics.mean(gaps_m):.0f}min")
    jump_sizes = sorted(s["jump"] for s in spikes)
    if jump_sizes:
        print(f"Spike jump pts: median={statistics.median(jump_sizes):.2f} "
              f"p25={jump_sizes[len(jump_sizes)//4]:.2f} p75={jump_sizes[3*len(jump_sizes)//4]:.2f} "
              f"max={jump_sizes[-1]:.2f}")

    retraces = spike_retrace_after_ticks(ticks, spikes)
    r60 = [r["retrace_60s"] for r in retraces if r["retrace_60s"] is not None]
    r120 = [r["retrace_120s"] for r in retraces if r["retrace_120s"] is not None]
    t30 = [r["t_to_30pct_s"] for r in retraces if r["t_to_30pct_s"] is not None]
    if r60:
        print(f"Retrace from spike peak: median@60s={statistics.median(r60)*100:.0f}% "
              f"median@120s={statistics.median(r120)*100 if r120 else 0:.0f}%")
    if t30:
        print(f"Time to 30% retrace: median={statistics.median(t30):.0f}s "
              f"({sum(1 for t in t30 if t <= 60)}/{len(t30)} within 60s)")

    out["ticks"] = {"stats": tstats, "spike_threshold": thr,
                    "spikes": len(spikes), "spikes_per_hour": round(len(spikes) / max(span_h, 1e-9), 2),
                    "retraces_sample": retraces[:5]}

    # ---- Part 2: rebuild M5 from ticks, compare vs cache ---------------------
    live_bars = rebuild_m5(ticks)
    live_spikes = detect_spikes(live_bars, DEPLOYED["spike_threshold"])
    live_spike_idx = [s["idx"] for s in live_spikes if s["is_spike"]]
    live_days = max((live_bars[-1]["epoch"] - live_bars[0]["epoch"]) / 86400.0, 0.2)
    print(f"\nRebuilt M5 bars from ticks: {len(live_bars)} "
          f"({live_days:.1f}d) -> EA-threshold spikes: {len(live_spike_idx)} "
          f"({len(live_spike_idx)/live_days:.1f}/day)")

    m5 = slice_60d(load_m5("Boom 1000 Index", "M5"), 60)
    days60 = (m5[-1]["epoch"] - m5[0]["epoch"]) / 86400.0
    atr60 = compute_atr(m5)
    atr_live_tail = [a for a in compute_atr(live_bars) if a > 0][-50:]
    atr60_tail = [a for a in atr60 if a > 0][-500:]
    print(f"ATR(14): 60d median={statistics.median(atr60_tail):.2f} | "
          f"live-ticks median={statistics.median(atr_live_tail):.2f} "
          f"({100*(statistics.median(atr_live_tail)/statistics.median(atr60_tail)-1):+.0f}% vs 60d)")

    # ---- Part 3: threshold sweep on 60-day data ------------------------------
    print("\n" + "-" * 90)
    print(f"SMALL-SPIKE SWEEP (60d, deployed fade params: retrace "
          f"{DEPLOYED['retrace_lo']:.2f}-{DEPLOYED['retrace_hi']:.2f}, "
          f"SL {DEPLOYED['sl_mult']}xATR, TP {DEPLOYED['tp_mult']}xATR)")
    print("-" * 90)
    sweep = []
    for thr in SWEEP_THRESHOLDS:
        idx = [s["idx"] for s in detect_spikes(m5, thr) if s["is_spike"]]
        trades, opps = fade_sim(m5, idx, atr60)
        row = {"threshold": thr, "spikes_per_day": round(len(idx) / days60, 2),
               "opportunities": opps, **stats_row(trades, days60)}
        sweep.append(row)
        sp = row.get("spikes_per_day", 0)
        if row.get("trades"):
            print(f"  thr>={thr:<4}: spikes/d={sp:>5}  opps={opps:>4}  "
                  f"trades={row['trades']:>4} ({row['per_day']}/d)  "
                  f"WR={row['wr']:>5}%  PF={row['pf']:>5}  ExpR={row['exp_r']:>+.3f}  "
                  f"MaxDD={row['max_dd']}")
        else:
            print(f"  thr>={thr:<4}: spikes/d={sp:>5}  opps={opps:>4}  trades=0")
    out["sweep_60d"] = sweep

    # Incremental micro-band (1.5-2.8): what do we ADD on top of deployed 2.8?
    big_idx = set(i for i in (s["idx"] for s in detect_spikes(m5, 2.8) if s["is_spike"]))
    micro_idx = [i for i in (s["idx"] for s in detect_spikes(m5, 1.5) if s["is_spike"]) if i not in big_idx]
    micro_trades, micro_opps = fade_sim(m5, micro_idx, atr60)
    micro = stats_row(micro_trades, days60)
    micro["spikes_per_day"] = round(len(micro_idx) / days60, 2)
    micro["opportunities"] = micro_opps
    print(f"\n  MICRO-ONLY band (1.5x<=body<2.8x, excluded from deployed): "
          f"spikes/d={micro.get('spikes_per_day',0)}  opps={micro_opps}")
    if micro.get("trades"):
        print(f"    -> trades={micro['trades']} ({micro['per_day']}/d)  WR={micro['wr']}%  "
              f"PF={micro['pf']}  ExpR={micro['exp_r']}  MaxDD={micro['max_dd']}  exits={micro['exits']}")
    out["micro_band_only"] = micro

    # ---- Part 4: tick-latency edge ------------------------------------------
    # For tick-level spikes: entry at first retrace tick vs M5-close entry.
    if retraces:
        fast30 = sum(1 for r in retraces if r["t_to_30pct_s"] is not None and r["t_to_30pct_s"] <= 60)
        print(f"\nTICK-ENTRY EDGE: {fast30}/{len(retraces)} tick-spikes reach 30% retrace "
              f"within 60s (median {statistics.median(t30) if t30 else 0:.0f}s) — "
              f"a tick-triggered fade enters minutes earlier than the M5-close entry.")

    # ---- Verdict -------------------------------------------------------------
    print("\n" + "=" * 90)
    dep = next(r for r in sweep if r["threshold"] == 2.8)
    mic = micro if micro.get("trades") else None
    print("VERDICT")
    print("=" * 90)
    print(f"Deployed 2.8x band: {dep.get('per_day', 0)}/day trades, PF={dep.get('pf')}, "
          f"ExpR={dep.get('exp_r')}")
    if mic:
        print(f"Micro band adds {mic.get('per_day', 0)/max(dep.get('per_day', 0.001), .001):.1f}x more setups: "
              f"PF={mic['pf']}, ExpR={mic['exp_r']}  "
              f"-> {'VIABLE micro-fade tier' if mic['pf'] >= 1.5 and mic['exp_r'] > 0.1 else 'MARGINAL — needs tighter filters or smaller risk'}")
    out_path = ART / "boom_tick_analysis.json"
    out_path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\n[wrote] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
