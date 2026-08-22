#!/usr/bin/env python3
"""Phase-6 risk-layer cross-validation on the REAL R_75 corpus.

The stateless parity gate (phase6_logic_check.py) proves the MQL5 mirror's
stake formula, lot conversion and veto reasons match Python on hand-picked
states.  This harness closes the gap the Phase-2 (regime) and Phase-3
(structure) harnesses closed: a STATEFUL REPLAY over the real tick corpus,
where both risk engines process the same signal stream and their per-event
state is compared after every decision and outcome.

The two engines are configured identically on the SHARED gates in --aligned
mode (the honest behavioral comparison), and separately at their own
production defaults in --defaults mode (which quantifies how far the MQL5
Constants.mqh risk limits drift from Python's RiskConfig defaults).

Shared gates (both engines, same thresholds):
  max open positions, consecutive-loss circuit breaker, daily loss fraction,
  confidence >= min, reward/risk >= min, volatility z <= max

MQL5-only gates (RiskEngine.mqh / RiskLimits.mqh, no Python equivalent):
  equity drawdown (15%), daily-peak drawdown (8%), trades/hour (3),
  trades/day (10), decision-layer WEAK/WAIT verdict veto, exposure manager

Gate-threshold divergences at defaults:
  daily loss    Python 2%  vs MQL5 5%     (Python stricter)
  consecutive   Python 4   vs MQL5 5      (Python stricter)

The MQL5-side math comes from the phase6_logic_check.py mirror (exec'd from
its definitions section, so it stays in lockstep with the MQL5 code).  The
composite gate order replicates CRiskEngine.Evaluate() in RiskEngine.mqh.

Position lifecycle: each engine is its OWN authority (it opens when IT
approves).  Exits use the closed-candle convention (only a CLOSED candle's
close can stop/target a position — no wick scratches), plus a 12-bar (1h)
time exit.  The outcome simulation is shared and deterministic, so the only
state divergence between the two engines comes from gate behavior.
"""

import argparse
import csv
import math
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

# --- load the mirror's definitions WITHOUT running its test block ------------
_MIRROR_SRC = open(os.path.join(_HERE, "phase6_logic_check.py"), encoding="utf-8").read()
_MIRROR_NS: dict = {"__file__": os.path.join(_HERE, "phase6_logic_check.py")}
exec(_MIRROR_SRC.split("def main():")[0], _MIRROR_NS)
stake_m = _MIRROR_NS["stake_m"]
lots_m = _MIRROR_NS["lots_m"]
LimitsM = _MIRROR_NS["LimitsM"]
drawdown_m = _MIRROR_NS["drawdown_m"]
ExposureM = _MIRROR_NS["ExposureM"]
MODE_NETTING = _MIRROR_NS["MODE_NETTING"]

# --- Python side (the real production risk engine) ----------------------------
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from synthetic_trader.config import RiskConfig  # noqa: E402
from synthetic_trader.domain import (  # noqa: E402
    Direction,
    FeatureSnapshot,
    Regime,
    TradeOutcome,
    TradeSignal,
)
from synthetic_trader.risk.engine import RiskEngine as PyRiskEngine  # noqa: E402

# --- config -------------------------------------------------------------------
TF = 300                       # M5 — the execution timeframe
ATR_PERIOD = 14
WARMUP = 300                   # bars before the first signal (ATR + z windows)
Z_WINDOW = 50                  # rolling range-z reference window
MOM_BARS = 3                   # momentum lookback for the signal direction
K_STOP = 0.75                  # stop distance in ATR
K_TGT = 0.90                   # target distance in ATR  (RR = 0.9/0.75 = 1.2)
HORIZON_BARS = 12              # 1h time exit
START_EQUITY = 1000.0

# Python RiskConfig defaults (the reference side)
PY = RiskConfig()

# MQL5 Constants.mqh defaults (the side under test)
MQL_DEFAULTS = dict(
    max_daily_loss=0.05, max_daily_dd=0.08, max_equity_dd=0.15,
    max_consecutive=5, max_open=1, max_trades_hour=3, max_trades_day=10,
)

CORPUS_PATHS = [
    os.path.join(_HERE, "..", "data", "backfill", "R_75_ticks.csv"),
    os.path.join(_HERE, "..", "data", "R_75_ticks.csv"),
]


# --- corpus -> M5 bars (same loader as the phase-2/3 harnesses) ---------------
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
                ticks.append((epoch, price))
                prev = price
    ticks.sort(key=lambda t: t[0])
    bars = []
    for epoch, price in ticks:
        bucket = int(epoch // TF)
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            bars[-1] = (bucket, b[1], max(b[2], price), min(b[3], price), price)
        else:
            bars.append((bucket, price, price, price, price))
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
    range_z_50 from the real rolling range distribution."""
    ranges = [b[2] - b[3] for b in bars]          # high - low per bar
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
            stop=close - (0.75 * atr if d == Direction.LONG else -0.75 * atr),
            target=close + (0.90 * atr if d == Direction.LONG else -0.90 * atr),
            range_z=z,
            signal_strength="strong" if conf >= 0.60 else "weak",
        ))
    return sigs


def simulate_outcome(sig, bars, i0):
    """Closed-candle exit convention: only a closed candle's close can hit
    stop/target (no wick scratches); time exit at HORIZON_BARS.  Returns
    (exit_close, return_r, exit_idx)."""
    entry = sig["close"]
    dist = abs(sig["stop"] - entry)
    d = sig["direction"]
    for j in range(i0 + 1, min(i0 + 1 + HORIZON_BARS, len(bars))):
        c = bars[j][4]
        if d == Direction.LONG:
            if c <= sig["stop"]:
                return c, -1.0, j
            if c >= sig["target"]:
                return c, (sig["target"] - entry) / dist, j
        else:
            if c >= sig["stop"]:
                return c, -1.0, j
            if c <= sig["target"]:
                return c, (entry - sig["target"]) / dist, j
    j = min(i0 + HORIZON_BARS, len(bars) - 1)
    c = bars[j][4]
    return c, (d.value == "long" and 1 or -1) * (c - entry) / dist, j


# --- composite mirror of CRiskEngine.Evaluate (RiskEngine.mqh gate order) -----
def mirror_evaluate(sig, limits, exposure, veto_weak, min_conf=0.48,
                    min_rr=1.2, max_z=3.0):
    """Replicates the RiskEngine.mqh gate sequence.  Returns (approved, reason)."""
    if limits.emergency:
        return False, "EMERGENCY_STOP active"
    if limits.max_open > 0 and limits.open >= limits.max_open:
        return False, "max open positions reached"
    if limits.max_consecutive > 0 and limits.consecutive >= limits.max_consecutive:
        return False, "consecutive-loss circuit breaker active"
    if limits.max_daily_loss > 0 and limits.daily_dd_fraction() >= limits.max_daily_loss:
        return False, "daily loss limit reached"
    if limits.max_equity_dd > 0 and limits.equity_dd_fraction() >= limits.max_equity_dd:
        return False, "equity drawdown limit reached"
    if limits.max_daily_dd > 0 and limits.daily_peak_dd_fraction() >= limits.max_daily_dd:
        return False, "daily peak drawdown limit reached"
    if limits.max_trades_day > 0 and limits.trades_today >= limits.max_trades_day:
        return False, "max trades/day reached"
    if limits.max_trades_hour > 0 and limits.trades_hour >= limits.max_trades_hour:
        return False, "max trades/hour reached"
    if veto_weak and sig["signal_strength"] == "weak":
        return False, "decision-layer WEAK verdict"
    if sig["confidence"] < min_conf:
        return False, "signal confidence below risk threshold"
    # reward/risk — same formula as TradeSignal.reward_risk (the MQL5 side
    # computes rr from the candidate levels exactly like Python's property).
    rr = (abs(sig["target"] - sig["close"]) / abs(sig["close"] - sig["stop"])
          if abs(sig["close"] - sig["stop"]) > 1e-12 else 0.0)
    if rr < min_rr:
        return False, "reward/risk below minimum"
    if sig["range_z"] > max_z:
        return False, "current candle volatility is statistically extreme"
    if not exposure.can_open(1 if sig["direction"] == Direction.LONG else -1):
        return False, "exposure limit reached (netting/exposure)"
    return True, ""


def make_py_signal(sig):
    return TradeSignal(
        symbol="R_75",
        direction=sig["direction"],
        confidence=sig["confidence"],
        min_confidence=PY.min_confidence,
        entry=sig["close"],
        stop_loss=sig["stop"],
        take_profit=sig["target"],
        horizon_sec=HORIZON_BARS * TF,
        snapshot=FeatureSnapshot(
            symbol="R_75", epoch=sig["epoch"], timeframe_sec=TF,
            features={"range_z_50": sig["range_z"]},
            regime=Regime.UNKNOWN, structure={},
        ),
        rationale=("phase6-real-corpus-replay",),
        signal_strength=sig["signal_strength"],
    )


def run_replay(sigs, bars, mql_cfg, aligned):
    """Both engines consume the SAME input stream and the SAME position
    lifecycle — the lifecycle is driven by the PYTHON engine (the production
    caller), and the mirror's state advances with identical open/outcome
    events.  This is the phase-2/3 pattern: same input, compare outputs, so
    every downstream divergence is a gate/threshold/counter difference, not
    a drifted lifecycle.  Returns per-event rows plus counters."""
    py = PyRiskEngine(PY)
    veto_weak = mql_cfg.pop("veto_weak", False)
    lm = LimitsM(**mql_cfg)
    lm.equity = lm.peak = lm.day_start = lm.day_peak = START_EQUITY
    ex = ExposureM(mode=MODE_NETTING,
                   max_open=mql_cfg.get("max_open", 0),
                   max_exposure=0.5)
    ex.equity = START_EQUITY
    if aligned:   # disable MQL5-only gates that have no Python counterpart
        for k in ("max_daily_dd", "max_equity_dd", "max_trades_hour", "max_trades_day"):
            setattr(lm, k, 0)

    rows = []
    veto_m = Counter()
    veto_p = Counter()
    pos = None      # the single (Python-driven) open position
    day_m = day_p = None
    primed = False
    wins = losses = 0
    rollovers = 0
    day_start_d = 0

    for k, sig in enumerate(sigs):
        i = sig["i"]
        hour = int((sig["epoch"] // 3600) % 24)
        day = int(sig["epoch"] // 86400)

        # 1) close the position at its simulated exit bar — BOTH engines
        #    register the SAME outcome (stateful parity is the point).
        if pos is not None and pos["close_at_bar"] == i:
            e = pos
            py.register_outcome(TradeOutcome(
                position_id=f"py-{e['entry_k']}", symbol="R_75",
                direction=e["direction"], entry=e["entry"], exit=e["exit"],
                pnl=e["pnl"], return_r=e["r"], opened_at=e["opened_at"],
                closed_at=sig["epoch"], features={}, won=e["won"]))
            lm.register_outcome(e["pnl"], e["r"])
            ex.register_close(1 if e["direction"] == Direction.LONG else -1)
            wins += 1 if e["won"] else 0
            losses += 0 if e["won"] else 1
            pos = None

        # 2) session-day sync both sides (mirror equity tracks the Python
        #    equity path — same trades, same money).  Python's sync_session_day
        #    lazily primes on its FIRST call (no reset), so the harness must
        #    prime it at the first signal too — otherwise the first real day
        #    rollover is swallowed and Python's daily reset runs one day late.
        if not primed:
            py.sync_session_day(day)
            primed = True
        elif day_p != day:
            if py.sync_session_day(day):
                rollovers += 1
        day_p = day
        if day_m != day:
            lm.sync(hour, day)
            day_m = day
        lm.set_equity(py.state.equity, hour, day)
        if abs(py.state.day_start_equity - lm.day_start) > 1e-9:
            day_start_d += 1

        # 3) both engines evaluate the SAME candidate at the SAME state
        pdec = py.evaluate(make_py_signal(sig))
        p_approved = pdec.approved
        p_reason = pdec.reasons[0] if pdec.reasons else ""
        p_stake = pdec.intent.stake if pdec.approved and pdec.intent else 0.0
        veto_p["approved" if p_approved else p_reason] += 1

        m_approved, m_reason = mirror_evaluate(sig, lm, ex, veto_weak)
        if m_approved:
            m_stake = stake_m(lm.equity, 0.005, sig["confidence"], 0.48, 1.0, 0.35)
            veto_m["approved"] += 1
        else:
            m_stake = 0.0
            veto_m[m_reason] += 1

        # 4) lifecycle advance — driven by the PYTHON engine
        if p_approved and pos is None:
            exit_close, r, j = simulate_outcome(sig, bars, i)
            won = r > 0.0
            pnl = (p_stake * r) if r > -1.0 else -p_stake
            py.register_open()
            lm.register_open()
            ex.register_open(1 if sig["direction"] == Direction.LONG else -1)
            pos = dict(entry_k=k, close_at_bar=j, r=r, exit=exit_close,
                       pnl=pnl, won=won, direction=sig["direction"],
                       entry=sig["close"], opened_at=sig["epoch"])

        # --- per-event comparison ------------------------------------------------
        rows.append(dict(
            i=i, hour=hour, close=sig["close"], conf=sig["confidence"],
            z=sig["range_z"], strength=sig["signal_strength"],
            p_approved=p_approved, p_reason=p_reason, p_stake=p_stake,
            m_approved=m_approved, m_reason=m_reason, m_stake=m_stake,
            p_consec=py.state.consecutive_losses, m_consec=lm.consecutive,
            p_dd=py.daily_drawdown_fraction(), m_dd=lm.daily_dd_fraction(),
            p_open=py.state.open_positions, m_open=lm.open,
            p_day_start=py.state.day_start_equity, m_day_start=lm.day_start,
            equity_p=py.state.equity, equity_m=lm.equity,
        ))

    return dict(rows=rows, veto_m=veto_m, veto_p=veto_p,
                rollovers=rollovers, day_start_d=day_start_d,
                wins=wins, losses=losses, trades=wins + losses,
                final_p=py.state.equity, final_m=lm.equity)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["aligned", "defaults"], default="aligned",
                    help="aligned = shared gates at Python values; "
                         "defaults = each side at its own production defaults")
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
    print(f"signals: {len(sigs)}  (every bar from {WARMUP}, "
          f"RR 1.2, stop {K_STOP}A, target {K_TGT}A, time exit {HORIZON_BARS} bars)")

    if aligned:
        mql_cfg = dict(max_daily_loss=PY.max_daily_loss_fraction,
                       max_consecutive=PY.max_consecutive_losses,
                       max_open=PY.max_open_positions, veto_weak=False)
        label = "ALIGNED (shared gates at Python RiskConfig values)"
    else:
        mql_cfg = dict(MQL_DEFAULTS, veto_weak=True)
        label = "DEFAULTS (MQL5 Constants.mqh vs Python RiskConfig)"
    print(f"\nmode: {label}\n")

    r = run_replay(sigs, bars, mql_cfg, aligned)
    rows = r["rows"]
    n = len(rows)

    # --- Axis 1: veto agreement ------------------------------------------------
    agree = sum(1 for x in rows if x["p_approved"] == x["m_approved"])
    print(f"=== AXIS 1 — veto agreement ===  {agree} / {n} ({100.0 * agree / n:.1f}%)")
    print("contingency  MQL5 \\\\ python    veto    approve   total")
    conf = Counter((x["m_approved"], x["p_approved"]) for x in rows)
    for m in (False, True):
        c = conf.get((m, False), 0), conf.get((m, True), 0)
        print(f"{'approve' if m else 'veto':>16}  {c[0]:>6}  {c[1]:>9}   {c[0] + c[1]:>5}")

    # veto tally per gate, both sides
    print("\n=== per-gate veto tally ===\n  MQL5 mirror:")
    for reason, c in r["veto_m"].most_common():
        print(f"    {reason:<55} {c:>5}")
    print("  Python engine:")
    for reason, c in r["veto_p"].most_common():
        print(f"    {reason:<55} {c:>5}")

    # --- Axis 2: disagreement attribution ---------------------------------------
    dis = [x for x in rows if x["p_approved"] != x["m_approved"]]
    att = Counter()
    for x in dis:
        if x["p_approved"] and not x["m_approved"]:
            key = f"MQL5 vetoed ({x['m_reason'] or '?'}) — Python approved"
        else:
            key = f"Python vetoed ({x['p_reason'] or '?'}) — MQL5 approved"
        att[key] += 1
    print(f"\n=== AXIS 2 — disagreement attribution ({len(dis)} bars) ===")
    for k, c in att.most_common():
        print(f"  {c:>5}  {k}")
    shown = 0
    print("\nfirst 10 disagreements (bar, hour, close, conf, z, strength, m -> p):")
    for x in dis:
        print(f"  bar {x['i']:>5} h{x['hour']:>2} px {x['close']:8.2f} "
              f"conf {x['conf']:.2f} z {x['z']:+.2f} {x['strength']:<5} "
              f"{'APPROVE' if x['m_approved'] else 'veto':<7} -> "
              f"{'APPROVE' if x['p_approved'] else 'veto'}")
        shown += 1
        if shown >= 10:
            break

    # --- Axis 3: stake parity (both approve) ------------------------------------
    both = [x for x in rows if x["p_approved"] and x["m_approved"]]
    ok = sum(1 for x in both if abs(x["p_stake"] - x["m_stake"]) <= 0.0051)
    print(f"\n=== AXIS 3 — stake parity (both approve: {len(both)} signals) ===")
    print(f"mirror stake vs Python rounded stake within 0.005: "
          f"{ok} / {len(both)} ({100.0 * ok / max(1, len(both)):.1f}%)")
    gaps = [x for x in both if abs(x["p_stake"] - x["m_stake"]) > 0.0051]
    for x in gaps[:5]:
        print(f"  gap bar {x['i']}: m={x['m_stake']:.3f} p={x['p_stake']:.3f}")

    # --- Axis 4: stateful limits parity (every event) ---------------------------
    s_ok = sum(1 for x in rows
               if x["p_consec"] == x["m_consec"]
               and abs(x["p_dd"] - x["m_dd"]) <= 1e-3
               and x["p_open"] == x["m_open"])
    print(f"\n=== AXIS 4 — stateful limits parity (per-event state) ===")
    print(f"consecutive-loss + daily-dd (tol 1e-3) + open counts identical: "
          f"{s_ok} / {n} ({100.0 * s_ok / n:.1f}%)")
    consec_d = [x for x in rows if x["p_consec"] != x["m_consec"]]
    dd_d = [x for x in rows if abs(x["p_dd"] - x["m_dd"]) > 1e-3]
    open_d = [x for x in rows if x["p_open"] != x["m_open"]]
    print(f"  consecutive divergence: {len(consec_d)} events"
          f"  daily-dd divergence: {len(dd_d)} events"
          f"  open-count divergence: {len(open_d)} events")
    for x in consec_d[:5]:
        print(f"    consec bar {x['i']}: m={x['m_consec']} p={x['p_consec']}")

    # --- Axis 5: session-day rollover --------------------------------------------
    print(f"\n=== AXIS 5 — session-day rollover ===")
    print(f"day transitions: {r['rollovers']}  events where the two engines' "
          f"day_start_equity disagree: {r['day_start_d']}")

    # --- outcomes + final state ----------------------------------------------------
    print(f"\n=== outcomes (Python-driven lifecycle) ===")
    print(f"trades: {r['trades']} ({r['wins']}W / {r['losses']}L)  "
          f"final equity {r['final_p']:.2f}  (mirror tracks the same equity: {r['final_m']:.2f})")

    # machine line for the verifier
    print(f"\n[PHASE6-REAL] mode={args.mode} bars={len(bars)} signals={len(sigs)} "
          f"veto_agree={agree}/{n} ({100.0 * agree / n:.1f}%) "
          f"stake_ok={ok}/{len(both)} state_ok={s_ok}/{n} "
          f"disagree={len(dis)} trades={r['trades']} final={r['final_p']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
