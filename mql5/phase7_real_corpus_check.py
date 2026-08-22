#!/usr/bin/env python3
"""Phase-7 execution-layer cross-validation on the REAL R_75 corpus.

The mocked-retcode gate (Tests/Phase7Tests.mq5) proves the Execution layer's
request -> retcode -> verify-fill lifecycle against a scripted transport, and
execution_parity_check.py proves the paper<->MT5 parity contract on hand-picked
states.  This harness closes the gap the Phase-2/3/6 harnesses closed: a
STATEFUL REPLAY over the real tick corpus where the MQL5 Execution engine
mirror and the REAL production Python execution backend process the same
signal stream, and their order-manager veto tallies and exit-reason splits are
compared after every decision and outcome.

The two lanes:

  PYTHON lane (production):  SimulatedExecutionBackend -> PaperBroker - the
      exact backend paper_runner.py journals into live_paper.jsonl.  Wick-based
      exits (a candle low/high trade-through stops/targets), stop-first on the
      same bar, 1h horizon time exit, NO breakeven trail.  This is the
      "Python journal" reference.
  MQL5 lane (mirror):        a faithful Python transcription of the Phase-7
      ExecutionEngine + PositionManager (ExecutionEngine.Execute gates 1-6,
      PositionManager.UpdateBar closed-candle exits, BE trail arming at
      trail_frac x planned RR, stop-first, time exit).  The mirror has a
      wick_mode flag so aligned mode exercises the EXACT PaperBroker semantics
      (trail off) and defaults mode runs the production closed-candle + trail
      configuration.

Modes (the phase-6 pattern):

  --aligned   shared execution config (gates off, wick, no trail, 1h time
              exit) -> both lanes must agree on every entry and exit.
              PLUS a sub-check: the min-RR 1.2 gate against
              TradeSignal.reward_risk (the known float-boundary footgun).
  --defaults  each side at its production behavior: Python PaperBroker (wick,
              no trail) vs MQL5 closed-candle + BE trail + the band's
              execution gates (min-RR 1.2 boundary, broker stops level,
              spread cap).  Reports the honest divergence: per-gate veto
              tallies (Python would submit everything), and the closed-candle
              grace + trail conversions vs the Python journal's wick numbers.

Position lifecycle: ONE open position at a time (max_open=1 - the engine's
execution default).  Both lanes open the SAME entry set (aligned: every flat
signal bar; defaults: every flat signal bar that passes the MQL5 gates) and
each lane resolves its own exits from real closed candles.
"""

import argparse
import csv
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from synthetic_trader.config import PaperExecutionConfig  # noqa: E402
from synthetic_trader.domain import (  # noqa: E402
    Candle,
    Direction,
    FeatureSnapshot,
    OrderIntent,
    Regime,
    TradeSignal,
)
from synthetic_trader.live.execution_backends import SimulatedExecutionBackend  # noqa: E402

# --- config -------------------------------------------------------------------
TF = 300                       # M5 - the execution timeframe
ATR_PERIOD = 14
WARMUP = 300                   # bars before the first signal (ATR + z windows)
Z_WINDOW = 50                  # rolling range-z reference window
MOM_BARS = 3                   # momentum lookback for the signal direction
K_STOP = 0.75                  # stop distance in ATR
K_TGT = 0.90                   # target distance in ATR  (RR = 0.9/0.75 = 1.2)
HORIZON_BARS = 12              # 1h time exit (Python horizon_sec = 12 * TF)
STAKE = 50.0

# SYN75 fixture values (Tests/* use CSymbolAdapter::FillFixture)
POINT = 0.01                   # digits=2
STOPS_LEVEL = 30               # broker stops level, in points
SPREAD_CAP_POINTS = 2000.0     # ExecutionConfig default (fixture spread ~1080)

# Band production execution defaults (Constants.mqh)
BAND_TRAIL_FRAC = 0.3
BAND_HOLD_SEC = 3600

CORPUS_PATHS = [
    os.path.join(_HERE, "..", "data", "backfill", "R_75_ticks.csv"),
    os.path.join(_HERE, "..", "data", "R_75_ticks.csv"),
]


# --- corpus -> M5 bars (same loader as the phase-2/3/6 harnesses) -------------
def load_m5_bars(paths):
    ticks = []
    seen = set()
    for p in paths:
        if not os.path.exists(p):
            print(f"  (missing corpus: {p})", file=sys.stderr)
            continue
        with open(p, newline="", encoding="utf-8") as f:
            next(f, None)  # header
            prev = None
            for row in csv.reader(f):
                try:
                    epoch = float(row[0])
                    price = float(row[2])
                    spread = float(row[3]) if len(row) > 3 else 0.0
                except (ValueError, IndexError):
                    continue
                if not (100.0 <= price <= 5000.0):
                    continue
                if prev is not None and abs(price - prev) / prev > 0.30:
                    continue  # single-tick jump ~3.7x is corrupted data
                k = round(epoch, 6)
                if k in seen:
                    continue
                seen.add(k)
                ticks.append((epoch, price, spread))
                prev = price
    ticks.sort(key=lambda t: t[0])
    bars = []
    for epoch, price, spread in ticks:
        bucket = int(epoch // TF)
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            bars[-1] = (bucket, b[1], max(b[2], price), min(b[3], price), price,
                        max(b[5], spread))
        else:
            bars.append((bucket, price, price, price, price, spread))
    return bars


def wilder_atr_series(hlc):
    atrs = []
    atr = None
    prev_close = 0.0
    for high, low, close in hlc:
        tr = high - low
        if prev_close > 0.0:
            tr = max(tr, abs(high - prev_close), abs(low - prev_close))
        atr = tr if atr is None else (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        atrs.append(atr)
        prev_close = close
    return atrs


# --- deterministic signal stream from real bars -------------------------------
def build_signals(bars, atrs):
    """One signal per bar i >= WARMUP.  No RNG: direction is 3-bar momentum,
    confidence scales with |momentum|/ATR, RR fixed 1.2, stop/target from ATR,
    range_z_50 from the real rolling range distribution (phase-6 stream)."""
    ranges = [b[2] - b[3] for b in bars]
    sigs = []
    for i in range(WARMUP, len(bars)):
        close = bars[i][4]
        mom = close - bars[i - MOM_BARS][4]
        atr = atrs[i]
        d = Direction.LONG if mom >= 0.0 else Direction.SHORT
        conf = min(0.95, max(0.40, 0.50 + 0.45 * min(1.0, abs(mom) / max(atr, 1e-9))))
        win = ranges[max(0, i - Z_WINDOW + 1): i + 1]
        mean = sum(win) / len(win)
        std = (sum((r - mean) ** 2 for r in win) / len(win)) ** 0.5
        z = (ranges[i] - mean) / std if std > 1e-9 else 0.0
        sigs.append(dict(
            i=i, epoch=float(bars[i][0]) * TF, close=close, atr=atr,
            direction=d, confidence=conf,
            stop=close - (K_STOP * atr if d == Direction.LONG else -K_STOP * atr),
            target=close + (K_TGT * atr if d == Direction.LONG else -K_TGT * atr),
            range_z=z,
            signal_strength="strong" if conf >= 0.60 else "weak",
        ))
    return sigs


def candle_at(bars, i):
    b = bars[i]
    return Candle(
        symbol="R_75", timeframe_sec=TF,
        open_time=int(b[0]) * TF,
        open=b[1], high=b[2], low=b[3], close=b[4],
        tick_count=1,
    )


def make_py_signal(sig):
    return TradeSignal(
        symbol="R_75",
        direction=sig["direction"],
        confidence=sig["confidence"],
        min_confidence=0.48,
        entry=sig["close"],
        stop_loss=sig["stop"],
        take_profit=sig["target"],
        horizon_sec=HORIZON_BARS * TF,
        snapshot=FeatureSnapshot(
            symbol="R_75", epoch=sig["epoch"], timeframe_sec=TF,
            features={"range_z_50": sig["range_z"]},
            regime=Regime.UNKNOWN, structure={},
        ),
        rationale=("phase7-real-corpus-replay",),
        signal_strength=sig["signal_strength"],
    )


def make_intent(sig):
    return OrderIntent(signal=make_py_signal(sig), stake=STAKE, max_loss=STAKE)


# --- execution gates mirror (ExecutionEngine.Execute steps 1-6) ---------------
def exec_gates(sig, cfg, bid, ask):
    """Replicates ExecutionEngine.Execute gates.  Returns None (pass) or the
    veto reason string (mirror of the m_last_log texts)."""
    # 3. spread guard
    if cfg["spread_cap_pts"] > 0.0 and POINT > 0.0 and ask > bid:
        if (ask - bid) / POINT > cfg["spread_cap_pts"]:
            return "spread guard"
    # 4. price sanity
    if sig["direction"] == Direction.LONG and bid <= sig["stop"]:
        return "price below stop"
    if sig["direction"] == Direction.SHORT and ask >= sig["stop"]:
        return "price above stop"
    # 5. broker stops level (CStopManager::MeetsStopsLevel)
    if STOPS_LEVEL > 0 and POINT > 0.0:
        if abs(sig["close"] - sig["stop"]) / POINT < STOPS_LEVEL:
            return "stop within broker stops level"
    # 5. min-RR floor (CTakeProfitManager::MeetsMinRR)
    if cfg["min_rr"] > 0.0:
        risk = abs(sig["close"] - sig["stop"])
        reward = abs(sig["target"] - sig["close"])
        if risk <= 0.0 or reward <= 0.0 or reward / risk < cfg["min_rr"]:
            return "planned RR below floor"
    return None


# --- PositionManager mirror (PositionManager.UpdateBar transcription) ---------
def mql_update_bar(st, high, low, close, bar_open, bar_sec, wick, trail_frac,
                   hold_sec):
    """One closed bar through the PositionManager lifecycle.  Returns
    (reason, exit_price) or (None, None) while holding.  Mirror of
    PositionManager.mqh UpdateBar(): MFE/MAE in price units, BE-trail arming
    at mfe_r >= trail_frac x planned_rr, effective stop = entry when armed,
    stop-first on the same bar, time exit at hold_sec."""
    if st["dir"] > 0:
        st["mfe"] = max(st["mfe"], high - st["entry"])
        st["mae"] = max(st["mae"], st["entry"] - low)
    else:
        st["mfe"] = max(st["mfe"], st["entry"] - low)
        st["mae"] = max(st["mae"], high - st["entry"])
    mfe_r = st["mfe"] / st["risk"] if st["risk"] > 0.0 else 0.0

    # breakeven trail arming (one time)
    if trail_frac > 0.0 and not st["armed"] and mfe_r >= trail_frac * st["planned_rr"]:
        st["armed"] = True
    eff_stop = st["entry"] if st["armed"] else st["stop"]

    # exit checks - wick (PaperBroker parity) or closed-candle close (production)
    if wick:
        stop_hit = (low <= eff_stop) if st["dir"] > 0 else (high >= eff_stop)
        target_hit = (high >= st["target"]) if st["dir"] > 0 else (low <= st["target"])
    else:
        stop_hit = (close <= eff_stop) if st["dir"] > 0 else (close >= eff_stop)
        target_hit = (close >= st["target"]) if st["dir"] > 0 else (close <= st["target"])
    expired = hold_sec > 0 and (bar_open + bar_sec) >= st["opened_at"] + hold_sec

    if stop_hit and target_hit:
        return ("BREAKEVEN_TRAIL" if st["armed"] else "STOP_HIT"), eff_stop
    if stop_hit:
        return ("BREAKEVEN_TRAIL" if st["armed"] else "STOP_HIT"), eff_stop
    if target_hit:
        return "TARGET_HIT", st["target"]
    if expired:
        return "TIME_EXIT", close
    return None, None


def open_state(sig, bar):
    risk = abs(sig["close"] - sig["stop"])
    if risk <= 0.0:
        risk = sig["close"] * 0.001          # degenerate guard (parity)
    return dict(
        i=sig["i"],
        dir=1 if sig["direction"] == Direction.LONG else -1,
        entry=sig["close"], stop=sig["stop"], target=sig["target"],
        risk=risk,
        planned_rr=abs(sig["target"] - sig["close"]) / risk if risk > 0.0 else 0.0,
        mfe=0.0, mae=0.0, armed=False,
        opened_at=sig["epoch"],                 # Python anchor (snapshot.epoch)
    )


def realized_r(st, exit_price):
    if st["risk"] <= 0.0:
        return 0.0
    return ((exit_price - st["entry"]) / st["risk"] if st["dir"] > 0
            else (st["entry"] - exit_price) / st["risk"])


# --- Python lane: the REAL production SimulatedExecutionBackend ---------------
def python_reason(sig, bar):
    """Derive the exit reason the PaperBroker used, from the closing candle -
    the branch order mirrors PaperBroker._maybe_close (stop-first)."""
    long = sig["direction"] == Direction.LONG
    stop_hit = (bar.low <= sig["stop"]) if long else (bar.high >= sig["stop"])
    target_hit = (bar.high >= sig["target"]) if long else (bar.low <= sig["target"])
    if stop_hit:
        return "STOP_HIT"
    if target_hit:
        return "TARGET_HIT"
    return "TIME_EXIT"


def run_lane_python(entries, bars):
    backend = SimulatedExecutionBackend(config=PaperExecutionConfig())
    entry_by_bar = {e["i"]: e for e in entries}
    pos = None
    outcomes = []                       # (entry_bar, reason, exit_price, r)
    for i in range(WARMUP, len(bars)):
        if pos is not None:
            outs = backend.on_candle(candle_at(bars, i))
            for o in outs:
                outcomes.append((pos["i"], python_reason(pos, candle_at(bars, i)),
                                 o.exit, o.return_r))
                pos = None
        if pos is None and i in entry_by_bar:
            backend.submit(make_intent(entry_by_bar[i]))
            pos = entry_by_bar[i]
    return outcomes


# --- MQL5 mirror lane ----------------------------------------------------------
def run_lane_mql(entries, bars, wick, trail_frac, hold_sec):
    entry_by_bar = {e["i"]: e for e in entries}
    pos = None
    outcomes = []                       # (entry_bar, reason, exit_price, r)
    for i in range(WARMUP, len(bars)):
        if pos is not None:
            b = bars[i]
            reason, price = mql_update_bar(pos, b[2], b[3], b[4],
                                           int(b[0]) * TF, TF,
                                           wick, trail_frac, hold_sec)
            if reason is not None:
                outcomes.append((pos["i"], reason, price, realized_r(pos, price)))
                pos = None
        if pos is None and i in entry_by_bar:
            pos = open_state(entry_by_bar[i], bars[i])
    return outcomes


def split_stats(outcomes):
    by = Counter()
    sum_r = Counter()
    for _, reason, _p, r in outcomes:
        by[reason] += 1
        sum_r[reason] += r
    n = len(outcomes)
    hit = sum(1 for _e, _r, _p, r in outcomes if r > 0.0)
    return dict(n=n, hit=hit, by=by, sum_r=sum_r)


def print_split(title, st):
    total = st["n"]
    print(f"  {title:<22} n={total:>4}  hit={100.0 * st['hit'] / max(1, total):5.1f}%  "
          f"sumR={sum(st['sum_r'].values()):+7.2f}  "
          f"exp={sum(st['sum_r'].values()) / max(1, total):+.3f}R")
    for reason in ("STOP_HIT", "TARGET_HIT", "TIME_EXIT", "BREAKEVEN_TRAIL"):
        c = st["by"].get(reason, 0)
        if c:
            print(f"      {reason:<16} n={c:>4}  avgR={st['sum_r'][reason] / c:+.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["aligned", "defaults"], default="aligned")
    args = ap.parse_args()
    aligned = args.mode == "aligned"

    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    if len(bars) < WARMUP + HORIZON_BARS + 20:
        print(f"not enough bars ({len(bars)})", file=sys.stderr)
        return 1
    closes = [b[4] for b in bars]
    hlc = [(b[2], b[3], b[4]) for b in bars]
    atrs = wilder_atr_series(hlc)
    span_h = len(bars) * TF / 3600.0
    print(f"bars={len(bars)}  ({span_h:.1f} hours of M5)  "
          f"close range {min(closes):.2f}..{max(closes):.2f}")

    sigs = build_signals(bars, atrs)
    print(f"signals: {len(sigs)}  (every bar from {WARMUP}, RR 1.2, "
          f"stop {K_STOP}A, target {K_TGT}A, time exit {HORIZON_BARS} bars)")

    if aligned:
        # --- ALIGNED: gates off, wick, no trail - behavioral parity ----------
        print("\nmode: ALIGNED (shared execution config - gates off, wick "
              "exits, no trail, 1h time exit)\n")
        entries = sigs                                   # every signal enters
        py = run_lane_python(entries, bars)
        mq = run_lane_mql(entries, bars, wick=True, trail_frac=0.0,
                          hold_sec=HORIZON_BARS * TF)
        by_entry_py = {e[0]: e for e in py}
        by_entry_mq = {e[0]: e for e in mq}

        n = len(entries)
        agree = 0
        skipped = 0
        reason_mismatch = Counter()
        for k, sig in enumerate(entries):
            i = sig["i"]
            p = by_entry_py.get(i)
            m = by_entry_mq.get(i)
            if p is None and m is None:
                skipped += 1      # both lanes flat-skip (max_open=1) - agreement
                continue
            if p is None or m is None:
                reason_mismatch["one lane never exited"] += 1
                continue
            if (p[1] == m[1] and abs(p[2] - m[2]) <= 1e-9
                    and abs(p[3] - m[3]) <= 1e-9):
                agree += 1
            else:
                reason_mismatch[f"{p[1]} vs {m[1]}"] += 1
        print(f"=== AXIS 1 - entry + exit parity ===  {agree} / {n} "
              f"({100.0 * agree / n:.1f}%) identical (entry bar, reason, "
              f"exit price, realized R); {skipped} entries both lanes "
              f"flat-skipped (max_open=1)")
        for k, c in reason_mismatch.most_common():
            print(f"    {c:>4}  {k}")

        # exit-reason split, both lanes (must be identical)
        ps, ms = split_stats(py), split_stats(mq)
        print("\n=== AXIS 2 - exit-reason split (aligned) ===")
        print_split("Python journal", ps)
        print_split("MQL5 mirror", ms)

        # sub-check: the min-RR 1.2 float boundary (phase-6 finding at the
        # execution layer) - Python TradeSignal.reward_risk vs the MQL5 gate.
        rr_veto_p = sum(1 for s in sigs if make_py_signal(s).reward_risk < 1.2)
        rr_veto_m = sum(1 for s in sigs if exec_gates(
            s, dict(spread_cap_pts=0.0, min_rr=1.2), s["close"], s["close"]) ==
            "planned RR below floor")
        print(f"\n=== AXIS 3 - min-RR 1.2 boundary parity ===\n"
              f"  Python TradeSignal.reward_risk < 1.2 : {rr_veto_p} signals\n"
              f"  MQL5 MeetsMinRR gate vetoes          : {rr_veto_m} signals\n"
              f"  boundary disagreement                : {abs(rr_veto_p - rr_veto_m)}")

        traded = n - skipped
        line = (f"[PHASE7-REAL] mode=aligned bars={len(bars)} signals={len(sigs)} "
                f"parity={agree}/{traded} ({100.0 * agree / max(1, traded):.1f}%)")
        line += (f" trades_py={ps['n']} trades_mq={ms['n']} "
                 f"sumR_py={sum(ps['sum_r'].values()):+.2f} "
                 f"sumR_mq={sum(ms['sum_r'].values()):+.2f} "
                 f"rr_boundary_disagree={abs(rr_veto_p - rr_veto_m)}")
        print("\n" + line)
        return 0

    # --- DEFAULTS: production behaviors - honest divergence -------------------
    print("\nmode: DEFAULTS (Python PaperBroker: wick, no trail  vs  "
          "MQL5: closed-candle, BE trail 0.3, gates on)\n")
    cfg = dict(spread_cap_pts=SPREAD_CAP_POINTS, min_rr=1.2)
    veto = Counter()
    entries = []
    last_bar = None
    for sig in sigs:
        i = sig["i"]
        # one position at a time: an entry only at a flat bar.  The previous
        # entry's earliest possible exit is its own bar + 1, so a bar is
        # "flat" iff the last entry bar is not the previous bar... the exact
        # flatness is resolved inside the lane runs; here we just apply the
        # gates to every signal and let the lanes enforce max_open=1.
        bid = bars[i][4]
        ask = bid + bars[i][5]                     # real corpus spread
        reason = exec_gates(sig, cfg, bid, ask)
        if reason is None:
            entries.append(sig)
        else:
            veto[reason] += 1
    print(f"=== AXIS 1 - execution-gate veto tallies (defaults) ===\n"
          f"  signals: {len(sigs)}   MQL5 gates approve: {len(entries)}   "
          f"vetoed: {len(sigs) - len(entries)}   (Python backend submits ALL)")
    for reason, c in veto.most_common():
        print(f"    {reason:<32} {c:>5}")
    full_floor = sum(1 for s in sigs if exec_gates(
        s, dict(spread_cap_pts=0.0, min_rr=2.0), s["close"], s["close"]) is None)
    print(f"  note: at the band's full production floor (min_rr 2.0, "
          f"DEFAULT_BAND_MIN_TARGET_RR) only {full_floor}/{len(sigs)} of these "
          f"RR-1.2 signals would pass - the execution floor is stricter than "
          f"the stream.")

    # both lanes run the SAME entry set (the MQL5-approved trades) so the
    # exit split measures the exit-policy divergence, not an entry difference.
    py = run_lane_python(entries, bars)
    mq = run_lane_mql(entries, bars, wick=False, trail_frac=BAND_TRAIL_FRAC,
                      hold_sec=BAND_HOLD_SEC)
    ps, ms = split_stats(py), split_stats(mq)

    print("\n=== AXIS 2 - exit-reason split, same entry set ===")
    print_split("Python journal (wick)", ps)
    print_split("MQL5 (closed-candle+trail)", ms)

    # attribution: wick scratches saved by the closed-candle grace
    by_entry_py = {e[0]: e for e in py}
    by_entry_mq = {e[0]: e for e in mq}
    grace = 0
    trail = 0
    both = 0
    for i in set(by_entry_py) & set(by_entry_mq):
        p, m = by_entry_py[i], by_entry_mq[i]
        both += 1
        if p[1] == "STOP_HIT" and m[1] != "STOP_HIT":
            grace += 1
        if m[1] == "BREAKEVEN_TRAIL":
            trail += 1
    print(f"\n=== AXIS 3 - divergence attribution (shared entries {both}) ===\n"
          f"  wick-stops in the Python journal spared by the closed-candle "
          f"grace: {grace}\n"
          f"  exits the MQL5 BE trail converted (BREAKEVEN_TRAIL): {trail}")

    line = (f"[PHASE7-REAL] mode=defaults bars={len(bars)} signals={len(sigs)} "
            f"approved={len(entries)} vetoed={len(sigs) - len(entries)} "
            f"trades_py={ps['n']} trades_mq={ms['n']} "
            f"sumR_py={sum(ps['sum_r'].values()):+.2f} "
            f"sumR_mq={sum(ms['sum_r'].values()):+.2f} "
            f"grace_saved={grace} trail_converted={trail}")
    print("\n" + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
