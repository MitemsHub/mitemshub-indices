#!/usr/bin/env python3
"""Offline A/B: v26.9 CONSTANT-λ spike-probability blend vs the legacy
'time-since-spike' (overdue) blend, on the EA's own recorded tick CSVs.

Replays CrashBoomEngine.OnTickFade in the ENGINE'S EXACT ORDER:
  manage open position (BE +1R, trail 0.7R, TP, SL gap-through, time exit
  1800s = InpMaxHoldBars 6 x M5) -> tick-spike SM on every tick (extension
  merging, ring recorded at spike detection) -> pending evaluation:
  full-retrace / 900s timeout / retrace-ceiling 0.60 expire -> retrace-entry
  window (ScaledFadeEntry, v26.8 base 0.4) -> burst-guard chain INSIDE
  if(m_burst_guard): cluster -> min-gap -> spike-prob > 0.70 -> SL/TP + min
  R:R 2.0 (RR-LOW consumes the spike) -> entry. One position at a time,
  spread paid on every round trip, no decisions across recording gaps.

The spike-probability model itself is rebuilt from the tick stream exactly
as CSpikeDetector computes it on live M5 bars (OnBar, lookback 20):
  - body EMA from |close-open| of closed bars (outlier-excluded mean over
    the last 50, needs >=5 non-spike bars, ring of 100)
  - grind walk: consecutive same-direction bars from the last closed bar,
    duration kept even if < 3 (component uses duration/25 regardless)
  - tick-speed ring: per-tick EMA(1/dt, 0.3) for dt < 10s; component =
    clamp(mean(last 10) / mean(prev 10) - 1)
  - bar-spike detection at 2.2x body EMA -> SAME event feeds the λ learner:
    inter-spike gap accumulator (bars), λ = EWMA(1/gap, alpha=0.05) trusted
    after 3 observed gaps, min observed gap tracked
OLD blend (what ran live on 2026-08-30, v25.9):  weights .30/.20/.25/.25
  comp4 = min(1, calendar_bars_since_spike/50), 0.5 if never spiked
NEW blend (v26.9 deployed):                      weights .35/.25/.25/.15
  comp4 = λ ramped over the refractory tail max(2, min_gap_obs), then flat
  λ forever; 0.05 until λ is learned

IMPORTANT scope note (mirrors the live code): on the TICK-FADE path the
spike-prob gate only runs when the burst guard is ON — the chain lives
inside if(m_burst_guard). So with Boom's deployed guard=OFF, tick fades are
prob-immune (OLD and NEW runs are identical there); the prob A/B on Boom is
only meaningful under the 08-30-era FIXED guard. The M5-fade SPIKE-AVOID
gate (always-on, both symbols) is out of scope for a tick replay — it can
only block more, never fewer, and is noted in the verdict.

Configs per session: prob model {old,new} x guard {NONE, FIXED 1800/2/600,
ADAPTIVE (λ-scaled geometry from the SAME learned λ)}. Deployed policy:
Crash = ADAPTIVE guard ON, Boom = guard OFF. Live-prob validation uses the
08-30 Experts-log entry prints (OLD model live: probs 0.02-0.26, the 0.70
gate never fired live that day).

Robustness on the headline pair: ATR x0.8/x1.2 and spread x1.5.

Usage:  python scripts/cb_spike_prob_backtest.py  (tee to
        artifacts/cb_spike_prob_results.txt for the record)
"""
from __future__ import annotations

import math
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cb_burst_guard_backtest import (          # validated replay helpers
    load_ticks, m5_atr_from_ticks, BurstRing, LIVE, GAP_S, BAR, TICK_SPIKE_PTS,
)

# ---- v26.8 DEPLOYED exit geometry (both .set files) -------------------------
FADE_R        = 0.40      # InpCBFadeR (ScaledFadeEntry base)
SL_MULT       = 0.30      # InpCBFadeSL x ATR
TP_MULT       = 4.00      # InpCBFadeTP x ATR
RETRACE_MAX   = 0.60      # CrashBoomStrategy v25.6 tune (confirmed live: EXPIRE @60%)
SPIKE_TIMEOUT = 900       # InpCBTickFadeTOSec
TIME_EXIT_S   = 6 * BAR   # InpMaxHoldBars=6 x M5 (v26.8 adopted 1800s hold)
MIN_RR        = 2.0       # GetMinRR
MAX_PROB      = 0.70      # InpCBMaxSpikeProb (deployed + profile AUTO value)
SPIKE_THRESH  = 2.2       # InpCBSpikeThreshold (bar-spike detector)
GRIND_LOOK    = 20        # engine OnBar(PERIOD_M5, 20, thresh)
SPREAD_PTS    = 0.483     # measured from the 08-30 recorded ticks (constant)

GUARD_WINDOW_S, GUARD_MAX_SPIKES, GUARD_MIN_GAP_S = 1800, 2, 600

# Live gate evidence, 2026-08-30 Experts log (OLD model ran live; every print
# was far below the 0.70 gate — the prob gate never blocked live that day).
LIVE_PROB = {
    "Crash": [(3.4, 0.14), (6.8, 0.14), (7.6, 0.14)],
    "Boom":  [(6.0, 0.15), (7.8, 0.14), (27.9, 0.02), (12.9, 0.05),
              (21.0, 0.07), (33.2, 0.26), (23.2, 0.14), (33.9, 0.02)],
}


def scaled_entry(jump: float) -> float:
    """CrashBoomStrategy.ScaledFadeEntry with the v26.8 base (0.4)."""
    lo = FADE_R * math.sqrt(12.0 / max(jump, 1.0))
    return max(0.18, min(0.40, lo))


class ProbModel:
    """Tick-stream replica of CSpikeDetector (OnTick + OnBar + blend)."""

    def __init__(self, mode: str):
        self.mode = mode                    # 'old' | 'new'
        self.speeds = deque(maxlen=100)     # per-tick ticks/sec ring
        self.bars = deque(maxlen=100)       # closed M5 bars: (open_k, body, dir)
        self.body_ema = 0.0
        self.tps = 0.0
        self.last_ts = 0
        self.cur = None                     # forming bar {'k','open','close'}
        self.spike_k = 0                    # open-bucket of last bar spike
        self.gap_bar = 0                    # closed bars since last spike
        self.gap_n = 0
        self.lam = 0.0                      # learned spikes/bar (EWMA 1/gap)
        self.min_gap = 0                    # shortest observed gap (bars)
        self.grind_dur = 0
        self.n_spikes = 0
        self.p = {"body": 0.0, "tick": 0.0, "grind": 0.0, "time": 0.0}

    # -- per tick ---------------------------------------------------------
    def on_tick(self, ts: int, bid: float):
        if self.last_ts > 0:
            dt = ts - self.last_ts
            if 0 < dt < 10:
                self.tps = 0.3 * (1.0 / dt) + 0.7 * self.tps
                self.speeds.append(self.tps)
        self.last_ts = ts
        k = ts - ts % BAR
        if self.cur is None:
            self.cur = {"k": k, "open": bid, "close": bid}
        elif k != self.cur["k"]:
            self._on_bar_close(self.cur)
            self.cur = {"k": k, "open": bid, "close": bid}
        else:
            self.cur["close"] = bid

    # -- per closed M5 bar (live OnBar order) ------------------------------
    def _on_bar_close(self, bar: dict):
        body = abs(bar["close"] - bar["open"])
        d = 1 if (bar["close"] - bar["open"]) > 0 else -1
        self.bars.append({"k": bar["k"], "body": body, "dir": d})

        if self.spike_k > 0:
            self.gap_bar += 1               # live: accumulate BEFORE spike check

        # body EMA recompute (outlier-excluded, ring<=50, >=5 non-spike bars)
        if len(self.bars) >= 10:
            recent = list(self.bars)[-50:]
            s, inc = 0.0, 0
            for b in recent:
                if self.body_ema <= 0 or b["body"] <= self.body_ema * 2.0:
                    s += b["body"]
                    inc += 1
            self.body_ema = s / inc if inc >= 5 else sum(x["body"] for x in recent) / len(recent)

        # bar-spike detection + λ learning (same event, live CSpikeDetector)
        if self.body_ema > 0 and body >= self.body_ema * SPIKE_THRESH:
            self.spike_k = bar["k"]
            self.n_spikes += 1
            if self.gap_bar > 0:
                g = float(self.gap_bar)
                self.lam = 1.0 / g if self.gap_n == 0 else 0.05 * (1.0 / g) + 0.95 * self.lam
                self.gap_n += 1
                if self.min_gap <= 0 or g < self.min_gap:
                    self.min_gap = g
            self.gap_bar = 0

        # grind walk (live UpdateGrind, lookback 20, from the last closed bar)
        dur, direction = 0, 0
        for b in reversed(list(self.bars)[-GRIND_LOOK:]):
            if dur == 0:
                direction, dur = b["dir"], 1
            elif b["dir"] == direction:
                dur += 1
            else:
                break
        self.grind_dur = dur

        # components (live UpdateProbabilities)
        if self.body_ema > 0 and len(self.bars) > 10:
            recent5 = sum(b["body"] for b in list(self.bars)[-5:]) / 5.0
            self.p["body"] = max(0.0, min(1.0, 1.0 - recent5 / self.body_ema))
        if len(self.speeds) > 20:
            s = list(self.speeds)
            r10 = sum(s[-10:]) / 10.0
            o10 = sum(s[-20:-10]) / 10.0
            if o10 > 0:
                self.p["tick"] = max(0.0, min(1.0, min(1.0, r10 / o10 - 1.0)))
        self.p["grind"] = min(1.0, self.grind_dur / 25.0)

        if self.mode == "old":
            # legacy: iBarShift(spike_bar_open) — calendar bars, capped /50
            if self.spike_k > 0:
                bars_since = max(1, int((bar["k"] + BAR - self.spike_k) // BAR))
                self.p["time"] = min(1.0, bars_since / 50.0)
            else:
                self.p["time"] = 0.5        # live: unknown = moderate
        else:
            if self.lam > 0 and self.gap_n >= 3:
                tail = max(2.0, float(self.min_gap))
                c = self.lam * (self.gap_bar / tail) if self.gap_bar < tail else self.lam
                self.p["time"] = min(1.0, c)
            else:
                self.p["time"] = self.lam if self.lam > 0 else 0.05

    def prob(self) -> float:
        w = (0.30, 0.20, 0.25, 0.25) if self.mode == "old" else (0.35, 0.25, 0.25, 0.15)
        pr = (w[0] * self.p["body"] + w[1] * self.p["tick"]
              + w[2] * self.p["grind"] + w[3] * self.p["time"])
        return max(0.0, min(1.0, pr))

    def mean_gap_sec(self) -> float:
        return (1.0 / self.lam) * BAR if (self.gap_n >= 3 and self.lam > 0) else 0.0


class AdaptiveGuard:
    """v26.9 λ-scaled burst guard — geometry from the SAME learned λ as the
    prob model (live: ActiveBurstGeometry reads the detector's λ)."""

    def __init__(self, model: ProbModel, win: int, max_spikes: int, min_gap: int):
        self.model = model
        self.times = []
        self.max_spikes = max_spikes
        self.fw, self.fg = win, min_gap

    def record(self, ts: float):
        self.times.append(ts)
        if len(self.times) > 8:
            self.times.pop(0)

    def geometry(self):
        mg = self.model.mean_gap_sec()
        if mg > 0:
            return (int(max(300, min(7200, 2.0 * mg))),
                    int(max(60, min(1800, 0.6 * mg))))
        return self.fw, self.fg

    def in_window(self, now: float) -> int:
        win, _ = self.geometry()
        return sum(1 for t in self.times if 0 <= now - t <= win)

    def gap_to_prev(self) -> int:
        return int(self.times[-1] - self.times[-2]) if len(self.times) >= 2 else 0

    def blocks(self, now: float):
        win, gap = self.geometry()
        iw = self.in_window(now)
        if iw >= self.max_spikes:
            return f"cluster={iw}/{self.max_spikes}@{win}s(λ {self.model.mean_gap_sec():.0f}s)"
        g = self.gap_to_prev()
        if gap > 0 and 0 < g < gap:
            return f"gap={g}s<{gap}s(λ)"
        return None


def simulate(ticks, is_crash: bool, atr: float, prob: ProbModel, guard,
             spread: float = SPREAD_PTS, gate: float = MAX_PROB):
    """Engine-order replay; returns (trades, skips, stats)."""
    trades, skips = [], []
    st = {"entries": 0, "prob_blocks": 0, "guard_blocks": 0, "rr_low": 0,
          "exp_full": 0, "exp_to": 0, "exp_ceiling": 0,
          "evals": 0, "gate_hits": 0, "max_prob": 0.0}
    pos = None
    cur = None
    block_key = None
    n = len(ticks)

    def close_pos(ts, price, reason):
        nonlocal pos
        if pos["dir"] > 0:
            r = (price - pos["entry"]) / pos["risk"]
        else:
            r = (pos["entry"] - (price + spread)) / pos["risk"]
        trades.append({"entry_t": pos["t_entry"], "exit_t": ts, "dir": pos["dir"],
                       "r": round(r, 3), "reason": reason, "jump": pos["jump"],
                       "retrace": pos["retrace"], "age": pos["age"],
                       "prob": pos["prob"], "comp4": pos["comp4"]})
        pos = None

    for i in range(1, n):
        ts, bid, _ = ticks[i]
        prob.on_tick(ts, bid)

        if ts - ticks[i - 1][0] > GAP_S:            # recording discontinuity
            if pos is not None:
                close_pos(ticks[i - 1][0], ticks[i - 1][1], "GAP")
            cur = None
            block_key = None
            continue

        # ---- manage open position (every tick) ----
        if pos is not None:
            gain = (bid - pos["entry"]) if pos["dir"] > 0 else (pos["entry"] - bid)
            pos["peak"] = max(pos["peak"], gain)
            gr = pos["peak"] / pos["risk"]
            if gr >= 1.0:
                if pos["dir"] > 0:
                    pos["sl"] = max(pos["sl"], pos["entry"],
                                    pos["entry"] + (pos["peak"] - 0.7 * pos["risk"]))
                else:
                    pos["sl"] = min(pos["sl"], pos["entry"],
                                    pos["entry"] - (pos["peak"] - 0.7 * pos["risk"]))
            if pos["dir"] > 0:
                if bid >= pos["tp"]:
                    close_pos(ts, pos["tp"], "TARGET")
                elif bid <= pos["sl"]:
                    close_pos(ts, bid, "STOP")
            else:
                if bid <= pos["tp"]:
                    close_pos(ts, pos["tp"], "TARGET")
                elif bid >= pos["sl"]:
                    close_pos(ts, bid, "STOP")
            if pos is not None and ts - pos["t_entry"] >= TIME_EXIT_S:
                close_pos(ts, bid, "TIME")

        # ---- tick-spike SM on every tick ----
        jump = bid - ticks[i - 1][1]
        hit = (jump <= -TICK_SPIKE_PTS) if is_crash else (jump >= TICK_SPIKE_PTS)
        if hit:
            if cur is None:
                cur = {"pre": ticks[i - 1][1], "peak": bid,
                       "jump": abs(jump), "t0": ts}
                if guard is not None:
                    guard.record(ts)
            else:
                deeper = (bid < cur["peak"]) if is_crash else (bid > cur["peak"])
                if deeper:
                    cur["peak"] = bid
                    cur["jump"] = abs(cur["peak"] - cur["pre"])
                    cur["t0"] = ts

        # ---- pending evaluation (live OnTickFade order) ----
        if cur is not None:
            retrace = ((bid - cur["peak"]) / cur["jump"]) if is_crash \
                else ((cur["peak"] - bid) / cur["jump"])
            age = ts - cur["t0"]
            full = (bid >= cur["pre"]) if is_crash else (bid <= cur["pre"])
            if full:
                cur = None; st["exp_full"] += 1; block_key = None
                continue
            if age > SPIKE_TIMEOUT:
                cur = None; st["exp_to"] += 1; block_key = None
                continue
            if retrace < scaled_entry(cur["jump"]):
                continue
            if retrace > RETRACE_MAX:
                cur = None; st["exp_ceiling"] += 1; block_key = None
                continue

            st["evals"] += 1
            p = prob.prob()
            st["max_prob"] = max(st["max_prob"], p)
            if p > gate:
                st["gate_hits"] += 1

            # burst-guard chain (cluster -> gap -> prob) — only when armed
            why = None
            if guard is not None:
                why = guard.blocks(ts)
                if why is None and p > gate:
                    why = f"prob={p:.2f}>{gate:.2f}"
            if why is not None:
                kind = "PROB" if why.startswith("prob") else "GUARD"
                key = (cur["t0"], why.split("=")[0][:7])
                if key != block_key:
                    skips.append((ts, f"{kind}:{why}", cur["jump"], p, prob.p["time"]))
                    if kind == "PROB":
                        st["prob_blocks"] += 1
                    else:
                        st["guard_blocks"] += 1
                    block_key = key
                continue                      # keep tracking (live semantics)

            entry_px = bid + (spread if is_crash else 0.0)
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
            if rr < MIN_RR:
                skips.append((ts, "RR-LOW", cur["jump"], p, prob.p["time"]))
                st["rr_low"] += 1
                cur = None; block_key = None   # RR-LOW consumes the spike
                continue

            st["entries"] += 1
            pos = {"dir": 1 if is_crash else -1, "entry": entry_px, "sl": sl,
                   "tp": tp, "risk": sl_d, "t_entry": ts, "jump": cur["jump"],
                   "retrace": retrace, "age": age, "peak": 0.0,
                   "prob": p, "comp4": prob.p["time"]}
            cur = None
            block_key = None

    if pos is not None:
        ts, bid, _ = ticks[-1]
        close_pos(ts, bid, "END")
    return trades, skips, st


def summarize(trades, st=None):
    if st is not None:
        base = (f"entries={st['entries']} blocks[prob={st['prob_blocks']} "
                f"guard={st['guard_blocks']}] rr_low={st['rr_low']} "
                f"expire[f={st['exp_full']} to={st['exp_to']} ceil={st['exp_ceiling']}] "
                f"gate_hits={st['gate_hits']}/{st['evals']} maxprob={st['max_prob']:.2f}")
    if not trades:
        return (base + " | no trades") if st is not None else "no trades"
    wins = [t for t in trades if t["r"] > 0]
    gl = sum(-t["r"] for t in trades if t["r"] < 0)
    gw = sum(t["r"] for t in trades if t["r"] > 0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    exits = {k: sum(1 for t in trades if t["reason"] == k)
             for k in ("TARGET", "STOP", "TIME", "GAP", "END") if any(t["reason"] == k for t in trades)}
    line = (f"trades={len(trades)} W/L={len(wins)}/{len(trades)-len(wins)} "
            f"R={sum(t['r'] for t in trades):+.2f} PF={gw/gl if gl > 0 else 99:.2f} "
            f"maxDD={dd:.2f} exits={exits}")
    return (base + " | " + line) if st is not None else line


def fmt_t(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def run_config(ticks, is_crash, atr, prob_mode, guard_kind, spread=SPREAD_PTS,
               atr_mult=1.0, gate=MAX_PROB):
    model = ProbModel(prob_mode)
    if guard_kind == "fixed":
        guard = BurstRing(GUARD_WINDOW_S, GUARD_MAX_SPIKES, GUARD_MIN_GAP_S)
    elif guard_kind == "adaptive":
        guard = AdaptiveGuard(model, GUARD_WINDOW_S, GUARD_MAX_SPIKES, GUARD_MIN_GAP_S)
    else:
        guard = None
    return simulate(ticks, is_crash, atr * atr_mult, model, guard, spread, gate), model


def trade_list(trades):
    out = []
    for t in trades:
        d = "BUY " if t["dir"] > 0 else "SELL"
        out.append(f"    {fmt_t(t['entry_t'])}->{fmt_t(t['exit_t'])} {d} "
                   f"jump={t['jump']:.1f} retrace={t['retrace']:.0%} age={t['age']}s "
                   f"prob={t['prob']:.2f}(c4={t['comp4']:.3f}) R={t['r']:+.2f} {t['reason']}")
    return out


def flips(a_trades, b_trades, label_a, label_b):
    """Entries present in A's stream but not B's (and vice versa), with R."""
    ka = {(round(t["entry_t"]), t["dir"]): t for t in a_trades}
    kb = {(round(t["entry_t"]), t["dir"]): t for t in b_trades}
    lines = []
    for k, t in sorted(ka.items()):
        if k not in kb:
            near = min((abs(t["entry_t"] - o["entry_t"]), o) for o in b_trades) \
                if b_trades else None
            nb = (f"  instead: {fmt_t(near[1]['entry_t'])} R={near[1]['r']:+.2f} "
                  f"Δt={near[0]}s") if near and near[0] <= 900 else "  instead: (nothing within 15min)"
            lines.append(f"    {label_a} ONLY: {fmt_t(t['entry_t'])} jump={t['jump']:.1f} "
                         f"prob={t['prob']:.2f} R={t['r']:+.2f}{nb}")
    for k, t in sorted(kb.items()):
        if k not in ka:
            near = min((abs(t["entry_t"] - o["entry_t"]), o) for o in a_trades) \
                if a_trades else None
            nb = (f"  instead: {fmt_t(near[1]['entry_t'])} R={near[1]['r']:+.2f} "
                  f"Δt={near[0]}s") if near and near[0] <= 900 else "  instead: (nothing within 15min)"
            lines.append(f"    {label_b} ONLY: {fmt_t(t['entry_t'])} jump={t['jump']:.1f} "
                         f"prob={t['prob']:.2f} R={t['r']:+.2f}{nb}")
    return lines or ["    none — identical entry sets"]


def run_session(title: str, glob: str, is_crash: bool, live_key: str | None):
    ticks = load_ticks(glob)
    is_live_day = live_key is not None and "20260830" in glob
    if len(ticks) < 500:
        print(f"\n[{title}] not enough ticks — skipped")
        return
    atr = m5_atr_from_ticks(ticks)
    t0, t1 = ticks[0][0], ticks[-1][0]
    print("\n" + "=" * 100)
    print(f"{title}  ticks={len(ticks)}  {fmt_t(t0)}->{fmt_t(t1)} UTC  ({(t1-t0)/3600:.1f}h)")
    print(f"ATR(14,M5)={atr:.2f}pts -> SL {SL_MULT*atr:.2f} / TP {TP_MULT*atr:.2f} pts | "
          f"spread {SPREAD_PTS}pts = {SPREAD_PTS/(SL_MULT*atr):.2f}R/rt")
    print("=" * 100)

    R = {}
    for pm in ("old", "new"):
        for gk in ("none", "fixed", "adaptive"):
            if gk == "none" and pm == "new":
                continue   # guard OFF => tick path prob-immune: identical to old
            (tr, sk, st), model = run_config(ticks, is_crash, atr, pm, gk)
            R[(pm, gk)] = (tr, sk, st, model)
            mg = model.mean_gap_sec()
            print(f"  [{pm:>4}+{gk:<8}] λ={model.lam:.4f}/bar (n={model.gap_n}, "
                  f"mg={mg:.0f}s, spikes={model.n_spikes})  {summarize(tr, st)}")

    # ---- headline comparisons ------------------------------------------
    if is_crash:
        pairs = [("old", "fixed", "OLD+FIXED (fixed-guard counterfactual)"),
                 ("old", "adaptive", "OLD+ADAPTIVE (λ-geometry, old blend)"),
                 ("new", "adaptive", "NEW+ADAPTIVE (DEPLOYED policy)")]
        print("\n  -- Crash headline configs (full trade lists) --")
        for pm, gk, label in pairs:
            tr, sk, st, _ = R[(pm, gk)]
            print(f"  [{label}] {summarize(tr, st)}")
            print("\n".join(trade_list(tr)))
            for s in sk:
                print(f"    {fmt_t(s[0])}  {s[1]}  jump={s[2]:.1f} prob={s[3]:.2f} c4={s[4]:.3f}")
        a, b = R[("old", "adaptive")][0], R[("new", "adaptive")][0]
        ra, rb = sum(t["r"] for t in a), sum(t["r"] for t in b)
        print(f"\n  -- PROB A/B at DEPLOYED guard (adaptive) --")
        print(f"    OLD total R={ra:+.2f}   NEW total R={rb:+.2f}   ΔR={rb - ra:+.2f}")
        print("    flips (NEW+ADAPTIVE vs OLD+ADAPTIVE):")
        print("\n".join(flips(a, b, "OLD", "NEW")))
        c = R[("old", "fixed")][0]
        print(f"    vs 08-30 live gates (OLD+FIXED R={sum(t['r'] for t in c):+.2f}): "
              f"deployed ΔR={sum(t['r'] for t in b) - sum(t['r'] for t in c):+.2f} "
              f"(guard+prob+λ-geo combined)")
        # comp4 evidence
        for pm in ("old", "new"):
            _, _, _, m = R[(pm, "adaptive")]
            c4s = [x["comp4"] for x in R[(pm, "adaptive")][0]]
            print(f"    comp4[{pm}] mean={sum(c4s)/len(c4s):.3f} max={max(c4s):.3f}"
                  if c4s else f"    comp4[{pm}] no entries")
        if is_live_day:
            live_chk(R, "Crash")
    else:
        pairs = [("old", "fixed", "OLD+FIXED (fixed-guard counterfactual)"),
                 ("new", "fixed", "NEW+FIXED (prob A/B counterfactual)"),
                 ("old", "none",   "guard OFF (DEPLOYED Boom — tick path prob-immune)")]
        print("\n  -- Boom headline configs (full trade lists) --")
        for pm, gk, label in pairs:
            tr, sk, st, _ = R[(pm, gk)]
            print(f"  [{label}] {summarize(tr, st)}")
            print("\n".join(trade_list(tr)))
            for s in sk:
                print(f"    {fmt_t(s[0])}  {s[1]}  jump={s[2]:.1f} prob={s[3]:.2f} c4={s[4]:.3f}")
        a, b = R[("old", "fixed")][0], R[("new", "fixed")][0]
        print(f"\n  -- PROB A/B under the 08-30-era FIXED guard --")
        print(f"    OLD total R={sum(t['r'] for t in a):+.2f}   "
              f"NEW total R={sum(t['r'] for t in b):+.2f}   "
              f"ΔR={sum(t['r'] for t in b) - sum(t['r'] for t in a):+.2f}")
        print("    flips (NEW+FIXED vs OLD+FIXED):")
        print("\n".join(flips(a, b, "OLD", "NEW")))
        for pm in ("old", "new"):
            c4s = [x["comp4"] for x in R[(pm, "fixed")][0]]
            print(f"    comp4[{pm}] mean={sum(c4s)/len(c4s):.3f} max={max(c4s):.3f}"
                  if c4s else f"    comp4[{pm}] no entries")
        if is_live_day:
            live_chk(R, "Boom")

    # ---- robustness on the headline pair --------------------------------
    print("\n  -- robustness (headline pair) --")
    if is_crash:
        h = [("old", "adaptive"), ("new", "adaptive")]
    else:
        h = [("old", "fixed"), ("new", "fixed")]
    for spread, slabel in ((SPREAD_PTS, "spread 1.0x"), (SPREAD_PTS * 1.5, "spread 1.5x")):
        for mult in (0.8, 1.0, 1.2):
            rs = []
            for pm, gk in h:
                (tr, _, _), _ = run_config(ticks, is_crash, atr, pm, gk, spread, mult)
                rs.append(sum(t["r"] for t in tr))
            print(f"    ATR x{mult:.1f} {slabel}: OLD={rs[0]:+.2f} NEW={rs[1]:+.2f} "
                  f"ΔR={rs[1]-rs[0]:+.2f}")

    # ---- gate sensitivity: at what gate level do the models diverge? ----
    print("\n  -- gate sensitivity (deployed guard geometry; entry sets can only "
          "shrink as the gate tightens) --")
    for g in (0.70, 0.50, 0.40, 0.30, 0.20):
        rs, pbs = [], []
        for pm, gk in h:
            (tr, sk, st), _ = run_config(ticks, is_crash, atr, pm, gk, gate=g)
            rs.append(sum(t["r"] for t in tr))
            pbs.append(st["prob_blocks"])
        print(f"    gate={g:.2f}: OLD R={rs[0]:+.2f} prob-blocks={pbs[0]:>2} | "
              f"NEW R={rs[1]:+.2f} prob-blocks={pbs[1]:>2} | ΔR={rs[1]-rs[0]:+.2f}")


def live_chk(R, symbol: str):
    """Compare sim prob at matched episodes vs the 08-30 Experts-log prints.
    Mismatches on cold-start entries (the OLD model's 0.5 'unknown' default + a
    cold body EMA in the per-file replay) are documented replay-fidelity
    limitations — BOTH sim models share the same detector state, so the A/B is
    unaffected; warm-state live prints are the authoritative OLD values."""
    print(f"\n  -- LIVE-PROB validation ({symbol}, 08-30 Experts log, OLD ran live) --")
    ref = R[("old", "fixed")][0]
    refnew = R[("new", "fixed")][0]
    for jump, lprob in LIVE_PROB[symbol]:
        m_old = min(ref, key=lambda t: abs(t["jump"] - jump), default=None)
        m_new = min(refnew, key=lambda t: abs(t["jump"] - jump), default=None)
        so = f"{m_old['prob']:.2f}" if m_old and abs(m_old["jump"] - jump) < 0.6 else "no-entry"
        sn = f"{m_new['prob']:.2f}" if m_new and abs(m_new["jump"] - jump) < 0.6 else "no-entry"
        print(f"    jump={jump:>5.1f}pts  live={lprob:.2f}  simOLD={so:>7}  simNEW={sn:>7}"
              + ("  <— replication verified" if so != "no-entry" and abs(float(so) - lprob) <= 0.02 else ""))


def main():
    run_session("CRASH 1000 — 2026-08-30", "MITEMSHUB_ticks_Crash_1000_Index_20260830.csv",
                True, "Crash")
    run_session("BOOM 1000 — 2026-08-30", "MITEMSHUB_ticks_Boom_1000_Index_20260830.csv",
                False, "Boom")
    run_session("BOOM 1000 — 2026-08-29", "MITEMSHUB_ticks_Boom_1000_Index_20260829.csv",
                False, None)


if __name__ == "__main__":
    main()
