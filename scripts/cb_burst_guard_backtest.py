#!/usr/bin/env python3
"""Offline backtest of the v26.0 tick-fade SPIKE-BURST GUARD on the EA's own
recorded Boom/Crash 1000 tick CSVs (artifacts/ticks/).

Replays the deployed v25.7 tick fast-fade exactly as wired in the live EA
(OnTickFade): tick spike detection with extension merging (tracked on every
tick, fired only when flat), size-scaled retrace entry (ScaledFadeEntry),
retrace-quality ceiling, pending-spike timeout, SL 0.4xATR / TP 3.2xATR
clamped past the pre-spike price, min R:R 2.0, tick-by-tick exits (BE at +1R,
trail 1R->0.7R, TP, SL with spike gap-through fills, 40-min time exit),
one position at a time, spread paid on every round trip. Then re-runs the
same trade stream with the v26.0 burst guard (cluster count + min gap, wired
after the retrace checks exactly as in CrashBoomEngine.OnTickFade) and sweeps
guard parameters. Baseline on the 08-30 Crash file is cross-checked against
the three LIVE trades the EA actually took that day.

Honesty notes:
  * Only the cluster/min-gap guard rules are replayed — the live spike-prob
    gate (bar-based) needs the M5 spike model and is out of scope here; it
    can only block MORE entries, never fewer.
  * ATR(14) is rebuilt from the tick stream itself; a +/-20% ATR sweep shows
    how sensitive the verdict is to the volatility estimate.
  * One to three days of recorded data -> directional evidence, not proof.

Usage:
    python scripts/cb_burst_guard_backtest.py
"""
from __future__ import annotations

import csv
import math
import sys
from datetime import datetime, timezone

# NOTE ON TIMEZONES: every epoch second in the tick CSVs is already MT5
# SERVER-clock time. datetime.fromtimestamp(ts, tz=timezone.utc) is used as a
# NO-SHIFT passthrough to render it; the 'UTC' in the tz argument does NOT
# mean the values are UTC. The Experts log clock drifts ~+3595s ahead of the
# tick-recorder clock (log buffering) — never 'correct' one against the other.
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TICK_DIR = ROOT / "artifacts" / "ticks"
if not TICK_DIR.exists():
    print("artifacts/ticks/ not found — copy the EA's MITEMSHUB_ticks_*.csv files there first.")
    sys.exit(1)

# ---- Deployed EA parameters (v25.7 tick fast-fade + v26.0 guard defaults) ----
TICK_SPIKE_PTS = 3.0       # InpCBTickSpikePts
FADE_R = 0.30              # InpCBFadeR (scaled-entry base)
RETRACE_MAX = 0.50         # GetFadeRetraceMax (v25.6 tuned)
SL_MULT = 0.4              # InpCBFadeSL x ATR
TP_MULT = 3.2              # InpCBFadeTP x ATR (Crash chart value)
MIN_RR = 2.0               # GetMinRR
SPIKE_TIMEOUT_S = 900      # InpCBTickFadeTOSec (v25.6)
TIME_EXIT_S = 8 * 300      # InpMaxHoldBars 8 x M5
BAR = 300                  # M5 seconds
SPREAD_PTS = 0.483         # measured from the 08-30 recorded ticks (constant)
GAP_S = 300                # recording-gap threshold: beyond this, the tick stream
                           # is discontinuous (terminal closed) — no spike/fade
                           # decisions across a gap; open positions are closed at
                           # the last pre-gap price with reason GAP.

# TIMEZONE MODEL (single source of truth — do not duplicate):
#   * Tick CSVs record MT5 SERVER-clock epoch seconds. The tz=timezone.utc in
#     fmt_t()/cross_check() is a deliberate NO-SHIFT passthrough for raw epoch
#     seconds; it does NOT mean the values are UTC.
#   * The Experts log clock runs +3595s (~1h) ahead of the tick-CSV clock.
#     Verified on 08-30 data: 5/7 log-referenced spike windows land within 5s
#     of recorded spikes when shifted by -3595s. This is a log-buffering
#     artifact, not a timezone difference — never 'correct' one against the other.
#   * Convert Experts log timestamps -> tick CSV timestamps:  csv_ts = log_ts - LOG_OFFSET_S.
LOG_OFFSET_S = 3595

# Explicit passthrough zone for rendering raw MT5-server epoch seconds.
SERVER_PASSTHROUGH_TZ = timezone.utc

# Live CB-TICKFADE executions on 2026-08-30 (server time), from the terminal
# Experts log — the offline sim is cross-checked against these. Crash stopped
# after 3 trades (DAILY-HALT was still active live that day).
LIVE = {
    "Crash": [(18, 50, 41, 3.4), (19, 23, 57, 6.8), (19, 35, 6, 7.6)],
    "Boom": [(18, 39, 37, 6.0), (18, 50, 1, 7.8), (19, 30, 40, 27.9),
             (19, 55, 22, 12.9), (20, 10, 1, 21.0), (21, 11, 36, 33.2),
             (21, 28, 13, 23.2)],
}

# v26.0 burst guard defaults (as wired into the live EA)
GUARD_WINDOW_S = 1800
GUARD_MAX_SPIKES = 2
GUARD_MIN_GAP_S = 600


def load_ticks(symbol_glob: str):
    rows = []
    for f in sorted(TICK_DIR.glob(symbol_glob)):
        with open(f, newline="") as fh:
            for rec in csv.DictReader(fh):
                try:
                    rows.append((int(rec["ts"]), float(rec["bid"]), float(rec["ask"])))
                except (ValueError, KeyError):
                    continue
    rows.sort(key=lambda r: r[0])
    return rows


def m5_atr_from_ticks(ticks) -> float:
    """ATR(14) on M5 bars rebuilt from the tick stream (Wilder smoothing)."""
    bars = {}
    for ts, bid, _ in ticks:
        k = ts - ts % BAR
        b = bars.setdefault(k, {"open": bid, "high": bid, "low": bid, "close": bid})
        b["high"] = max(b["high"], bid)
        b["low"] = min(b["low"], bid)
        b["close"] = bid
    trs, prev_close = [], None
    for k in sorted(bars):
        b = bars[k]
        tr = b["high"] - b["low"]
        if prev_close is not None:
            tr = max(tr, abs(b["high"] - prev_close), abs(b["low"] - prev_close))
        trs.append(tr)
        prev_close = b["close"]
    if len(trs) < 20:
        return 0.0
    atr = sum(trs[:14]) / 14.0
    for tr in trs[14:]:
        atr = (13.0 * atr + tr) / 14.0
    return atr


def scaled_fade_entry(jump: float) -> float:
    """CrashBoomStrategy.ScaledFadeEntry verbatim."""
    lo = FADE_R * math.sqrt(12.0 / max(jump, 1.0))
    return max(0.18, min(0.40, lo))


class BurstRing:
    """Mirror of the v26.0 burst ring in CrashBoomEngine."""

    def __init__(self, window: int, max_spikes: int, min_gap: int):
        self.times = []
        self.window = window
        self.max_spikes = max_spikes
        self.min_gap = min_gap

    def record(self, ts: float):
        self.times.append(ts)
        if len(self.times) > 8:
            self.times.pop(0)

    def in_window(self, now: float) -> int:
        return sum(1 for t in self.times if 0 <= now - t <= self.window)

    def gap_to_prev(self) -> int:
        if len(self.times) < 2:
            return 0
        return int(self.times[-1] - self.times[-2])

    def blocks(self, now: float):
        if self.in_window(now) >= self.max_spikes:
            return f"cluster={self.in_window(now)}/{self.max_spikes}@{self.window}s"
        gap = self.gap_to_prev()
        if self.min_gap > 0 and 0 < gap < self.min_gap:
            return f"gap={gap}s<{self.min_gap}s"
        return None


class AdaptiveRing:
    """v26.9 λ-scaled burst guard — mirror of CrashBoomEngine.ActiveBurstGeometry.

    Learns the mean inter-spike gap exactly like the EA's SpikeDetector: EWMA of
    1/gap in M5 bars (alpha=0.05), trusted after 3 observed gaps, mean gap =
    1/λ × 300s. Then scales the cluster geometry: window = 2.0 × mean gap,
    min-gap = 0.6 × mean gap (clamped 300-7200s / 60-1800s). Falls back to the
    fixed inputs until learned. NOTE: the EA learns cadence from the M5
    bar-spike detector while the guard counts tick spikes — on these indices
    the 1000-tick spike is the same event, so the cadence matches.
    """

    def __init__(self, window: int, max_spikes: int, min_gap: int):
        self.times = []
        self.max_spikes = max_spikes
        self.fixed_window = window
        self.fixed_min_gap = min_gap
        self.lam = 0.0        # spikes per M5 bar (EWMA of 1/gap_bars, α=0.05)
        self.n = 0
        self.prev_spike = 0.0

    def record(self, ts: float):
        self.times.append(ts)
        if len(self.times) > 8:
            self.times.pop(0)
        if self.prev_spike > 0:
            gap_bars = max(1, round((ts - self.prev_spike) / BAR))
            self.lam = (1.0 / gap_bars) if self.n == 0 else \
                (0.05 * (1.0 / gap_bars) + 0.95 * self.lam)
            self.n += 1
        self.prev_spike = ts

    def mean_gap_sec(self) -> float:
        return (1.0 / self.lam) * BAR if (self.n >= 3 and self.lam > 0) else 0.0

    def geometry(self):
        mg = self.mean_gap_sec()
        if mg > 0:
            return (int(max(300, min(7200, 2.0 * mg))),
                    int(max(60,  min(1800, 0.6 * mg))))
        return self.fixed_window, self.fixed_min_gap

    def in_window(self, now: float) -> int:
        win, _ = self.geometry()
        return sum(1 for t in self.times if 0 <= now - t <= win)

    def gap_to_prev(self) -> int:
        if len(self.times) < 2:
            return 0
        return int(self.times[-1] - self.times[-2])

    def blocks(self, now: float):
        win, gap = self.geometry()
        if self.in_window(now) >= self.max_spikes:
            mg = self.mean_gap_sec()
            return f"cluster={self.in_window(now)}/{self.max_spikes}@{win}s(λ-scaled mg={mg:.0f}s)"
        gapv = self.gap_to_prev()
        if gap > 0 and 0 < gapv < gap:
            return f"gap={gapv}s<{gap}s(λ-scaled)"
        return None


class FacadeGatedRing:
    """Facade-gated guard variant (this study): blocks tick-fades ONLY while
    the learned fade expectancy is negative — no cluster/min-gap geometry at
    all. Mirrors the EA's CbSpikeFacade() learning loop: EWMA of realized R
    per fade (alpha=0.15, ~7-trade memory), gate active when expectancy <
    floor (default -0.10R, matching InpCBMinExpectancy) after min_trades.
    The gate also OPENS as soon as expectancy recovers above the floor, so a
    bad night throttles further fades but a recovered edge re-enables them.
    record(ts, r) feeds the realized R of each executed fade.
    """

    def __init__(self, floor: float = -0.10, alpha: float = 0.15,
                 min_trades: int = 4):
        self.floor = floor
        self.alpha = alpha
        self.min_trades = min_trades
        self.expect = 0.0
        self.n = 0
        self.blocked_n = 0

    def record(self, ts: float, r: float | None = None):
        if r is None:
            return
        self.n += 1
        self.expect = r if self.n <= 2 else \
            (self.alpha * r + (1.0 - self.alpha) * self.expect)

    def blocks(self, now: float):
        if self.n < self.min_trades:
            return None
        if self.expect < self.floor:
            return f"facade expect={self.expect:+.2f}<{self.floor} n={self.n}"
        return None


def simulate(ticks, is_crash: bool, atr: float,
             guard: BurstRing | AdaptiveRing | FacadeGatedRing | None,
             re_max: float = RETRACE_MAX):
    """Full-state-machine replay (EA order: manage pos -> spike SM -> pending).

    FacadeGatedRing feedback: every CLOSED fade trade feeds its realized R
    back into the ring via guard.record(ts, r) so the learned expectancy
    updates exactly like the EA's UpdateCbSpikeLearning after each close.
    """
    trades, skipped = [], []
    pos = None
    cur = None          # pending fade target {pre, peak, jump, t0}
    last_block_t0 = 0   # dedup skip log per pending episode
    n = len(ticks)
    is_facade = isinstance(guard, FacadeGatedRing)

    def close_pos(ts, price, reason):
        nonlocal pos
        if pos["dir"] > 0:                      # long: entered at ask, exits at bid
            r = (price - pos["entry"]) / pos["risk_pts"]
        else:                                   # short: entered at bid, exits at ask
            r = (pos["entry"] - (price + SPREAD_PTS)) / pos["risk_pts"]
        trades.append({"entry_t": pos["t_entry"], "exit_t": ts,
                       "dir": pos["dir"], "entry": pos["entry"], "r": round(r, 2),
                       "reason": reason, "jump": pos["jump"],
                       "retrace": pos["retrace"], "age": pos["age"]})
        if is_facade:
            guard.record(ts, round(r, 2))       # feed realized R back to the EWMA
        pos = None

    for i in range(1, n):
        ts, bid, _ = ticks[i]

        # ---- recording-gap discontinuity: never trade across a gap ----
        if ts - ticks[i - 1][0] > GAP_S:
            if pos is not None:
                close_pos(ticks[i - 1][0], ticks[i - 1][1], "GAP")
            cur = None
            continue

        # ---- manage open position (every tick) ----
        if pos is not None:
            gain = (bid - pos["entry"]) if pos["dir"] > 0 else (pos["entry"] - bid)
            pos["peak_gain"] = max(pos["peak_gain"], gain)
            gr = pos["peak_gain"] / pos["risk_pts"]
            if gr >= 1.0:                       # BE at +1R, trail from +1R (0.7R dist)
                if pos["dir"] > 0:
                    pos["sl"] = max(pos["sl"], pos["entry"],
                                    pos["entry"] + (pos["peak_gain"] - 0.7 * pos["risk_pts"]))
                else:
                    pos["sl"] = min(pos["sl"], pos["entry"],
                                    pos["entry"] - (pos["peak_gain"] - 0.7 * pos["risk_pts"]))
            if pos["dir"] > 0:
                if bid >= pos["tp"]:
                    close_pos(ts, pos["tp"], "TARGET")
                elif bid <= pos["sl"]:
                    close_pos(ts, bid, "STOP")  # gap-through fills included
            else:
                if bid <= pos["tp"]:
                    close_pos(ts, pos["tp"], "TARGET")
                elif bid >= pos["sl"]:
                    close_pos(ts, bid, "STOP")
            if pos is not None and ts - pos["t_entry"] >= TIME_EXIT_S:
                close_pos(ts, bid, "TIME")

        # ---- spike state machine on EVERY tick (even while holding) ----
        jump_tick = bid - ticks[i - 1][1]
        hit = (jump_tick <= -TICK_SPIKE_PTS) if is_crash else (jump_tick >= TICK_SPIKE_PTS)
        if hit:
            if cur is None:
                cur = {"pre": ticks[i - 1][1], "peak": bid,
                       "jump": abs(jump_tick), "t0": ts}
                if guard is not None:
                    guard.record(ts)
            else:
                deeper = (bid < cur["peak"]) if is_crash else (bid > cur["peak"])
                if deeper:
                    cur["peak"] = bid
                    cur["jump"] = abs(cur["peak"] - cur["pre"])
                    cur["t0"] = ts

        # ---- pending evaluation (expire checks always, fire only when flat) ----
        if cur is not None:
            retrace = ((bid - cur["peak"]) / cur["jump"]) if is_crash \
                else ((cur["peak"] - bid) / cur["jump"])
            age = ts - cur["t0"]
            full = (bid >= cur["pre"]) if is_crash else (bid <= cur["pre"])
            if full or age > SPIKE_TIMEOUT_S or retrace > re_max:
                cur = None
            elif pos is None and retrace >= scaled_fade_entry(cur["jump"]):
                entry_px = bid + (SPREAD_PTS if is_crash else 0.0)
                sl_d = SL_MULT * atr
                tp_d = TP_MULT * atr
                if is_crash:
                    sl = entry_px - sl_d
                    tp = entry_px + tp_d
                    if tp < cur["pre"]:
                        tp = cur["pre"] + 0.2 * atr
                    rr = (tp - entry_px) / max(entry_px - sl, 1e-9)
                else:
                    sl = entry_px + sl_d
                    tp = entry_px - tp_d
                    if tp > cur["pre"]:
                        tp = cur["pre"] - 0.2 * atr
                    rr = (entry_px - tp) / max(sl - entry_px, 1e-9)
                why = guard.blocks(ts) if guard is not None else None
                if rr < MIN_RR:
                    skipped.append((ts, "RR-LOW", cur["jump"]))
                    cur = None
                elif why is not None:
                    if cur["t0"] != last_block_t0:      # one log per episode
                        skipped.append((ts, f"GUARD:{why}", cur["jump"]))
                        last_block_t0 = cur["t0"]
                else:
                    pos = {"dir": 1 if is_crash else -1, "entry": entry_px,
                           "sl": sl, "tp": tp, "risk_pts": sl_d, "t_entry": ts,
                           "jump": cur["jump"], "retrace": retrace, "age": age,
                           "peak_gain": 0.0}
                    cur = None                          # consume the spike

    if pos is not None:
        ts, bid, _ = ticks[-1]
        close_pos(ts, bid, "END")
    return trades, skipped


def cross_check(trades, symbol: str):
    """Compare simulated entries vs the LIVE CB-TICKFADE executions (Experts log)."""
    live = LIVE.get(symbol, [])
    live_ts = [(h * 3600 + m * 60 + s, j) for h, m, s, j in live]
    sim_ts = [t["entry_t"] % 86400 for t in trades]
    matched, missed, extra = [], [], []
    for lts, lj in live_ts:
        hit = next((s for s in sim_ts if abs(s - lts) <= 5), None)
        (matched if hit is not None else missed).append(lts)
    for s in sim_ts:
        if not any(abs(s - lts) <= 5 for lts, _ in live_ts):
            extra.append(s)
    def f(t):
        return fmt_t(t)
    print(f"  LIVE cross-check: {len(matched)}/{len(live_ts)} live entries reproduced"
          f"; missed by sim: {[f(t) for t in missed] or '-'}; sim-only: {[f(t) for t in extra] or '-'}")


def summarize(trades):
    if not trades:
        return "no trades"
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    exits = {k: sum(1 for t in trades if t["reason"] == k) for k in ("TARGET", "STOP", "TIME", "END")}
    return (f"trades={len(trades)} W/L={len(wins)}/{len(trades) - len(wins)} "
            f"totalR={sum(t['r'] for t in trades):+.2f} PF={gw / gl if gl > 0 else 99:.2f} "
            f"maxDD={dd:.2f} exits={exits}")


def fmt_t(ts: float) -> str:
    """Format epoch seconds as MT5 SERVER time (labeled 'srv' in output).

    The tick CSVs record MT5-server-clock epoch seconds. timezone.utc is a
    deliberate passthrough (no shift) — calling it 'UTC' was misleading and
    caused the log-vs-CSV offset confusion on 08-31; the Experts log clock
    runs ~+3595s ahead of the tick-recorder clock, which is a LOG buffering
    artifact, not a timezone difference."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def run_symbol(name: str, glob: str, is_crash: bool, re_max: float, symbol: str, live_date: str | None = None):
    ticks = load_ticks(glob)
    if len(ticks) < 500:
        print(f"\n[{name}] not enough ticks — skipped")
        return
    t0, t1 = ticks[0][0], ticks[-1][0]
    print("\n" + "=" * 96)
    print(f"{name}  ticks={len(ticks)}  {fmt_t(t0)}->{fmt_t(t1)} srv  ({(t1 - t0) / 3600:.1f}h)")
    print("=" * 96)

    atr = m5_atr_from_ticks(ticks)
    print(f"ATR(14, M5 from ticks) = {atr:.2f} pts -> SL {SL_MULT * atr:.2f}, TP {TP_MULT * atr:.2f} pts "
          f"| spread {SPREAD_PTS} pts = {SPREAD_PTS / (SL_MULT * atr):.2f}R per round trip")

    # --- ATR robustness ----------------------------------------------------
    print(f"\n--- ATR robustness (guard OFF, retrace ceiling {re_max:.0%}) ---")
    for mult in (0.8, 1.0, 1.2):
        tr, _ = simulate(ticks, is_crash, atr * mult, None, re_max)
        print(f"  ATR x{mult:.1f} ({atr * mult:.2f}): {summarize(tr)}")

    # --- Baseline (guard OFF) -----------------------------------------------
    tr0, sk0 = simulate(ticks, is_crash, atr, None, re_max)
    if live_date and live_date in glob:
        cross_check(tr0, symbol)   # live list is from this date only
    print("\n--- BASELINE (guard OFF, ATR 1.0x) ---")
    for t in tr0:
        d = "BUY " if t["dir"] > 0 else "SELL"
        print(f"  {fmt_t(t['entry_t'])} -> {fmt_t(t['exit_t'])}  {d} jump={t['jump']:.1f} "
              f"retrace={t['retrace']:.0%} age={t['age']}s  R={t['r']:+.2f}  {t['reason']}")
    print(f"  => {summarize(tr0)}")
    if sk0:
        kinds = sorted(set(s[1].split(":")[0] for s in sk0))
        print(f"  pre-entry skips: {len(sk0)} {kinds}")

    # --- Guard ON (deployed defaults) ---------------------------------------
    ring = BurstRing(GUARD_WINDOW_S, GUARD_MAX_SPIKES, GUARD_MIN_GAP_S)
    trg, skg = simulate(ticks, is_crash, atr, ring, re_max)
    print(f"\n--- GUARD ON (window={GUARD_WINDOW_S}s max={GUARD_MAX_SPIKES} gap={GUARD_MIN_GAP_S}s) ---")
    for t in trg:
        d = "BUY " if t["dir"] > 0 else "SELL"
        print(f"  {fmt_t(t['entry_t'])} -> {fmt_t(t['exit_t'])}  {d}  R={t['r']:+.2f}  {t['reason']}")
    blocks = [s for s in skg if s[1].startswith("GUARD:")]
    for s in blocks:
        print(f"  {fmt_t(s[0])}  BLOCKED  {s[1]}  (spike jump={s[2]:.1f})")
    print(f"  => {summarize(trg)}   (guard blocks: {len(blocks)})")
    delta = sum(t["r"] for t in trg) - sum(t["r"] for t in tr0)
    print(f"  DELTA R vs baseline: {delta:+.2f}")

    # --- v26.9 λ-scaled ADAPTIVE guard --------------------------------------
    #    Cluster geometry scales with the symbol's MEASURED spike cadence:
    #    window = 2.0 × mean gap, min-gap = 0.6 × mean gap, learned online
    #    during the replay exactly as the EA learns it (EWMA 1/gap, α=0.05,
    #    trusted at 3 gaps, fixed 1800/600 fallback before that).
    aring = AdaptiveRing(GUARD_WINDOW_S, GUARD_MAX_SPIKES, GUARD_MIN_GAP_S)
    tra, ska = simulate(ticks, is_crash, atr, aring, re_max)
    mg = aring.mean_gap_sec()
    if mg > 0:
        print(f"\n--- GUARD ADAPTIVE (λ-scaled: learned mean gap {mg:.0f}s = {mg/60:.1f}min "
              f"from {aring.n} gaps → window {aring.geometry()[0]}s, min-gap {aring.geometry()[1]}s) ---")
    else:
        print(f"\n--- GUARD ADAPTIVE (mean gap not learned: only {aring.n} spike(s) in file — fixed fallback) ---")
    for t in tra:
        d = "BUY " if t["dir"] > 0 else "SELL"
        print(f"  {fmt_t(t['entry_t'])} -> {fmt_t(t['exit_t'])}  {d}  R={t['r']:+.2f}  {t['reason']}")
    ablocks = [s for s in ska if s[1].startswith("GUARD:")]
    for s in ablocks:
        print(f"  {fmt_t(s[0])}  BLOCKED  {s[1]}  (spike jump={s[2]:.1f})")
    print(f"  => {summarize(tra)}   (guard blocks: {len(ablocks)})")
    adelta = sum(t["r"] for t in tra) - sum(t["r"] for t in tr0)
    print(f"  DELTA R vs baseline: {adelta:+.2f}   (vs fixed guard: {adelta - delta:+.2f})")

    # --- v26.13 FACADE-GATED guard (this study) -----------------------------
    #    Blocks tick-fades ONLY while the learned fade expectancy is negative
    #    (EWMA of realized R, α=0.15, ~7-trade memory; gate active when
    #    expectancy < floor after min_trades) — no cluster/min-gap geometry.
    #    Every closed fade feeds its realized R back into the EWMA, mirroring
    #    the EA's UpdateCbSpikeLearning after each close.
    fring = FacadeGatedRing(floor=-0.10, alpha=0.15, min_trades=4)
    trf, skf = simulate(ticks, is_crash, atr, fring, re_max)
    print(f"\n--- GUARD FACADE-GATED (expectancy floor {fring.floor:+.2f}R, α={fring.alpha}, "
          f"min_trades={fring.min_trades}; {fring.blocked_n} fades seen) ---")
    for t in trf:
        d = "BUY " if t["dir"] > 0 else "SELL"
        print(f"  {fmt_t(t['entry_t'])} -> {fmt_t(t['exit_t'])}  {d}  R={t['r']:+.2f}  {t['reason']}")
    fblocks = [s for s in skf if s[1].startswith("GUARD:")]
    for s in fblocks:
        print(f"  {fmt_t(s[0])}  BLOCKED  {s[1]}")
    print(f"  => {summarize(trf)}   (guard blocks: {len(fblocks)})")
    fdelta = sum(t["r"] for t in trf) - sum(t["r"] for t in tr0)
    print(f"  DELTA R vs baseline: {fdelta:+.2f}   (vs fixed guard: {fdelta - delta:+.2f})")

    # --- Facade-gated guard (this study) -------------------------------------
    fring = FacadeGatedRing(floor=-0.10, alpha=0.15, min_trades=4)
    trf, skf = simulate(ticks, is_crash, atr, fring, re_max)
    print(f"\n--- GUARD FACADE-GATED (expectancy floor {fring.floor:+.2f}R, α={fring.alpha}, "
          f"min_trades={fring.min_trades}; {fring.blocked_n} fades seen) ---")
    for t in trf:
        d = "BUY " if t["dir"] > 0 else "SELL"
        print(f"  {fmt_t(t['entry_t'])} -> {fmt_t(t['exit_t'])}  {d}  R={t['r']:+.2f}  {t['reason']}")
    fblocks = [s for s in skf if s[1].startswith("GUARD:")]
    for s in fblocks:
        print(f"  {fmt_t(s[0])}  BLOCKED  {s[1]}")
    print(f"  => {summarize(trf)}   (guard blocks: {len(fblocks)})")
    fdelta = sum(t["r"] for t in trf) - sum(t["r"] for t in tr0)
    print(f"  DELTA R vs baseline: {fdelta:+.2f}   (vs fixed guard: {fdelta - delta:+.2f})")

    # --- Parameter sweep -----------------------------------------------------
    print("\n--- GUARD PARAMETER SWEEP ---")
    print(f"{'window':>7} {'max':>4} {'gap':>5} | {'trades':>6} {'R':>7} {'blocks':>6} | trade Rs")
    for window in (900, 1800, 2700):
        for mx in (2, 3):
            for gap in (0, 300, 600, 900):
                r2 = BurstRing(window, mx, gap)
                tr, sk, = simulate(ticks, is_crash, atr, r2, re_max)
                nb = sum(1 for s in sk if s[1].startswith("GUARD:"))
                tot = sum(t["r"] for t in tr)
                detail = ",".join(f"{t['r']:+.1f}" for t in tr) or "-"
                print(f"{window:>7} {mx:>4} {gap:>5} | {len(tr):>6} {tot:>+7.2f} {nb:>6} | {detail}")


def main():
    import re
    # Auto-discover all recorded tick CSVs instead of hardcoding dates.
    # Group by (symbol, date) so each session gets its own replay pass.
    sessions = {}
    for f in sorted(TICK_DIR.glob("MITEMSHUB_ticks_*.csv")):
        m = re.match(r"MITEMSHUB_ticks_(\w+?)_(\d{8})\.csv", f.name)
        if not m:
            continue
        sym, date = m.group(1), m.group(2)
        key = (sym, date)
        sessions.setdefault(key, []).append(f)
    if not sessions:
        print("No MITEMSHUB_ticks_*.csv files found in artifacts/ticks/")
        sys.exit(1)
    for (sym, date), files in sorted(sessions.items()):
        glob_pat = f"MITEMSHUB_ticks_{sym}_{date}.csv"
        is_crash = "Crash" in sym
        re_max = 0.50 if is_crash else 0.60
        live_date = date if date == "20260830" else None
        label = f"{sym.upper()} 1000 — {date}"
        run_symbol(label, glob_pat, is_crash, re_max, sym, live_date)


if __name__ == "__main__":
    main()
