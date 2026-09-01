#!/usr/bin/env python3
"""Valuation replay: the 7 Boom 1000 fade entries REJECTED by the broker on
2026-08-30 (retcode 10016 'invalid stops' — stale v25.9 SL below the broker's
minimum stop distance), replayed with the DEPLOYED v26.8 geometry + the
OpenCBTrade clamps that now prevent rejection.

The 7 events come from the Experts log: each "Executing SELL" line (jump,
retrace, t=age) is followed by ORDER FAILED retcode=10016.

CLOCK CALIBRATION (validated): the Experts-log clock runs LOG_TO_TICK_OFFSET_S
= 3595s (~1h) AHEAD of the tick-CSV clock. Evidence: with log_t - 3595 - age,
5/7 windows land on a recorded spike within 5s, and the remaining 2 land on
spikes whose jump matches the logged jump exactly (6.0->5.98, 7.8->7.84). The
old 'same clock' assumption produced 7x 'no live episode'.

Replay per window (the EA was flat at each — the previous attempt was
rejected, so no position existed):
  1. rebuild the tick-spike SM forward from the recording start (extension
     merging, peak/jump/t0 exactly as the live SM tracks it)
  2. at the log timestamp, take the LIVE pending episode and continue
     evaluating with the DEPLOYED v26.8 geometry:
       - ScaledFadeEntry base 0.4 (v26.8; the log's retrace% was the v25.9
         0.3-base threshold firing point)
       - SL 0.3xATR CLAMPED to the broker minimum stop distance (the v26.6
         fix — this clamp is why the same entries are no longer rejected),
         TP 4.0xATR clamped past the pre-spike price, min R:R 2.0
  3. tick-by-tick exits: BE +1R / trail 0.7R / TP / gap-through SL / 1800s
  4. spread paid on round trip; $/R from the 08-30 reconciliation
Counterfactual overlap: if a prior counterfactual trade is still open at the
next window, that window is skipped (one position at a time).

The 22:50:55 fade that WAS accepted is real history (already journaled) and
is not re-simulated. Crash fades that evening executed normally.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cb_burst_guard_backtest import (          # validated replay helpers
    load_ticks, m5_atr_from_ticks, BAR, TICK_SPIKE_PTS, GAP_S,
)

# ---- v26.8 deployed geometry + OpenCBTrade clamps ---------------------------
FADE_R        = 0.40      # ScaledFadeEntry base (v26.8; log's retrace% was v25.9's 0.3-base firing point)
SL_MULT       = 0.30      # InpCBFadeSL x ATR
TP_MULT       = 4.00      # InpCBFadeTP x ATR
RETRACE_MAX   = 0.60
SPIKE_TIMEOUT = 900       # InpCBTickFadeTOSec
TIME_EXIT_S   = 6 * BAR   # 1800s hold
MIN_RR        = 2.0
SPREAD_PTS    = 0.483

# Boom 1000 broker minimum stop distance, measured 2026-08-30: the accepted
# 22:50:55 trade carried SL dist 4.112 = the floor (that is why it alone was
# accepted). OpenCBTrade now clamps the SL out to this floor — applied here.
BROKER_MIN_STOP = 4.112

# money: 08-30 reconciliation — the one real Boom trade lost $3.11 at -3.782R
R_TO_USD = 3.11 / 3.782
LOTS = 0.20

# The 7 rejected windows: Experts-log timestamps of the "Executing SELL"
# lines (each followed by ORDER FAILED retcode=10016). Same clock as ticks.
REJECTED = [
    (19, 39, 37, 6.0),    # jump=6.0pts retrace=40% t=156s
    (19, 50, 1, 7.8),     # jump=7.8pts retrace=59% t=314s
    (20, 30, 40, 27.9),   # jump=27.9pts retrace=20% t=381s
    (20, 55, 22, 12.9),   # jump=12.9pts retrace=29% t=251s
    (21, 10, 1, 21.0),    # jump=21.0pts retrace=46% t=687s
    (22, 11, 36, 33.2),   # jump=33.2pts retrace=18% t=396s
    (22, 28, 13, 23.2),   # jump=23.2pts retrace=22% t=356s
]

# Experts-log clock is 3595s ahead of the tick-CSV clock (see docstring).
LOG_TO_TICK_OFFSET_S = 3595


def scaled_entry(jump: float) -> float:
    lo = FADE_R * math.sqrt(12.0 / max(jump, 1.0))
    return max(0.18, min(0.40, lo))


def simulate_window(ticks, t_start: float, atr: float, spread: float = SPREAD_PTS):
    """Continue the LIVE pending spike episode from t_start (ABSOLUTE epoch) with
    the deployed geometry. Returns dict with r (trade), or {'skipped':...}, or None."""
    n = len(ticks)
    i0 = next((i for i, t in enumerate(ticks) if t[0] >= t_start), None)
    if i0 is None or i0 == 0:
        return None

    # rebuild the spike SM forward, capturing the episode alive at t_start
    # (episodes expire like the live SM: full retrace, timeout, or gap)
    cur = None
    for i in range(1, i0 + 1):
        ts, bid, _ = ticks[i]
        if ts > t_start:
            break
        if cur is not None and (ts - cur["t0"] > SPIKE_TIMEOUT or bid <= cur["pre"]):
            cur = None
        jump = bid - ticks[i - 1][1]
        if jump >= TICK_SPIKE_PTS:            # Boom: upward tick spike
            if cur is None:
                cur = {"pre": ticks[i - 1][1], "peak": bid,
                       "jump": abs(jump), "t0": ts}
            elif bid > cur["peak"]:
                cur["peak"] = bid
                cur["jump"] = abs(cur["peak"] - cur["pre"])
                cur["t0"] = ts

    if cur is None:
        return None
    # sanity: log says episode age t= (156..687s) at the order time
    age_at_log = t_start - cur["t0"]

    # continue evaluating from t_start with deployed geometry
    for i in range(i0, n):
        ts, bid, _ = ticks[i]
        retrace = (cur["peak"] - bid) / cur["jump"]
        age = ts - cur["t0"]
        if bid <= cur["pre"] or age > SPIKE_TIMEOUT or retrace > RETRACE_MAX:
            return {"no_entry": f"expired (age={age:.0f}s, retrace={retrace:.0%})",
                    "age_at_log": age_at_log, "t0": cur["t0"], "jump": cur["jump"]}
        if retrace < scaled_entry(cur["jump"]):
            continue
        # retrace-entry reached -> build the trade with clamped geometry
        entry_px = bid                                   # SELL: enter at bid
        entry_t = ts
        sl_d = SL_MULT * atr
        sl = max(entry_px + sl_d, entry_px + BROKER_MIN_STOP)   # broker clamp
        tp = entry_px - TP_MULT * atr
        if tp > cur["pre"]:
            tp = cur["pre"] - 0.2 * atr
        if (entry_px - tp) / (sl - entry_px) < MIN_RR:
            return {"no_entry": f"RR-LOW (retrace {retrace:.0%})",
                    "age_at_log": age_at_log, "t0": cur["t0"], "jump": cur["jump"]}
        # tick-by-tick exit
        risk = sl - entry_px
        peak_gain = 0.0
        for j in range(i, n):
            ts2, bid2, _ = ticks[j]
            if j > i and ts2 - ticks[j - 1][0] > GAP_S:
                return _close(entry_px, risk, ticks[j - 1][1], ts2, cur, "GAP", spread, entry_t)
            gain = entry_px - bid2
            peak_gain = max(peak_gain, gain)
            sl_eff = sl
            if peak_gain / risk >= 1.0:                  # BE at +1R, trail 0.7R
                sl_eff = min(sl, entry_px, entry_px - (peak_gain - 0.7 * risk))
            if bid2 <= tp:
                return _close(entry_px, risk, tp, ts2, cur, "TARGET", spread, entry_t)
            elif bid2 >= sl_eff:
                return _close(entry_px, risk, bid2, ts2, cur, "STOP", spread, entry_t)
            if ts2 - ticks[i][0] >= TIME_EXIT_S:
                return _close(entry_px, risk, bid2, ts2, cur, "TIME", spread, entry_t)
        return _close(entry_px, risk, ticks[-1][1], ticks[-1][0], cur, "END", spread, entry_t)
    return None


def _close(entry, risk, exit_px, ts, cur, reason, spread, entry_t=None):
    r = (entry - (exit_px + spread)) / risk
    return {"t0": cur["t0"], "jump": cur["jump"], "entry": entry,
            "exit": exit_px, "exit_t": ts, "entry_t": entry_t or ts,
            "r": round(r, 3), "reason": reason}


def fmt_t(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def run_set(ticks, atr, spread=SPREAD_PTS, atr_mult=1.0):
    """Run all 7 windows with one-position-at-a-time overlap handling."""
    day0 = ticks[0][0] - ticks[0][0] % 86400   # tick CSVs start at 00:00 UTC
    rows, open_until = [], 0.0
    for (h, m, s, jlog) in REJECTED:
        log_t = h * 3600 + m * 60 + s
        # calibrate log clock -> tick clock, then anchor to the tick day (epoch)
        t_start = day0 + log_t - LOG_TO_TICK_OFFSET_S
        if t_start < open_until:
            rows.append({"hms": (h, m, s), "jlog": jlog,
                         "no_entry": f"busy (prior counterfactual open until {fmt_t(open_until)})"})
            continue
        r = simulate_window(ticks, t_start, atr * atr_mult, spread)
        if r and "r" in r:
            open_until = r["exit_t"]
        rows.append({"hms": (h, m, s), "jlog": jlog, **(r or {"no_entry": "no live episode"})})
    return rows


def report(rows, label):
    tot_r = sum(r["r"] for r in rows if "r" in r)
    n_tr = sum(1 for r in rows if "r" in r)
    print(f"\n--- {label} ---")
    for r in rows:
        lh = "%02d:%02d:%02d" % r["hms"]
        if "r" in r:
            print(f"  {lh}  jump={r['jlog']:>5.1f}  -> spike {fmt_t(r['t0'])}  entry {fmt_t(r['entry_t'])}->{fmt_t(r['exit_t'])} "
                  f"entry={r['entry']:.2f} exit={r['exit']:.2f} R={r['r']:+.2f} "
                  f"${r['r']*R_TO_USD:+.2f}  {r['reason']}")
        elif "no_entry" in r:
            print(f"  {lh}  jump={r['jlog']:>5.1f}  -> no entry: {r['no_entry']}")
        else:
            print(f"  {lh}  jump={r['jlog']:>5.1f}  -> {r.get('skipped', '???')}")
    print(f"  => trades={n_tr}  totalR={tot_r:+.2f}  total ${tot_r*R_TO_USD:+.2f}")
    return tot_r


def main():
    ticks = load_ticks("MITEMSHUB_ticks_Boom_1000_Index_20260830.csv")
    if len(ticks) < 500:
        print("ticks missing"); sys.exit(1)
    atr = m5_atr_from_ticks(ticks)
    print("=" * 96)
    print("REJECTED-WINDOWS VALUATION — Boom 1000, 2026-08-30 evening: the 7 broker-rejected fades")
    print("replayed with the DEPLOYED v26.8 geometry + OpenCBTrade clamps (the clamp is why the")
    print("broker no longer rejects them). Log clock = tick clock + 3595s (calibrated: 5/7 windows")
    print("land on recorded spikes within 5s; the other 2 match logged jump exactly).")
    print(f"ticks={len(ticks)}  ATR(14,M5)={atr:.2f}pts -> SL {SL_MULT*atr:.2f} "
          f"(clamp floor {BROKER_MIN_STOP}) / TP {TP_MULT*atr:.2f} | spread {SPREAD_PTS}pts "
          f"| ${R_TO_USD:.3f}/R @ {LOTS} lots")
    print("=" * 96)

    tot = report(run_set(ticks, atr), "DEPLOYED geometry")
    for label, kw in (("ATR x0.8", {"atr_mult": 0.8}),
                      ("ATR x1.2", {"atr_mult": 1.2}),
                      ("spread x1.5", {"spread": SPREAD_PTS * 1.5})):
        report(run_set(ticks, atr, **kw), label)

    print("\nNOTES:")
    print("- Counterfactual: entries fire at the recorded retrace point with today's clamped SL;")
    print("  v26.8's deeper entry anchor (0.4 base vs the log's v25.9 0.3) means some windows")
    print("  need a deeper retrace than 08-30 price gave before expiry — those print 'expired'.")
    print("- One position at a time: if a prior counterfactual trade is still open at the next")
    print("  window, that window is skipped (marked 'busy').")
    print("- The accepted 22:50:55 fade is real history (journaled) and not re-simulated.")


if __name__ == "__main__":
    main()
