#!/usr/bin/env python3
"""Phase-5 logic mirror — verifies the exact algorithms in MITEMSHUB_AI.

Replicates line-for-line:
  Decision/ConfidenceEngine.mqh   (Python confidence math + signal states)
  Decision/ScoringEngine.mqh      (weighted composite + sub-scores)
  Decision/TradeQualityEngine.mqh (R-multiple journal + break-even floor)

Two layers of validation:
  1. The mirror is checked against the REAL Python production code:
       - decision_engine._classify_signal_strength / _dynamic_min_confidence
         / _drift_confidence_penalty  (on a stub-constructed DecisionEngine)
       - live.stage3_gate.break_even_floor
  2. The mirror runs the same assertion matrix as Tests/Phase5Tests.mq5.

Keep this file in lockstep with the MQL5 side.
"""

import math
import os
import sys
from types import SimpleNamespace

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PHASE5] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PHASE5] FAIL  {name}  -> {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --- real Python production code (the reference) -----------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from synthetic_trader.strategy.decision_engine import (  # noqa: E402
    DecisionEngine as PyDecisionEngine,
)
from synthetic_trader.domain import Direction as PyDirection  # noqa: E402
from synthetic_trader.live.stage3_gate import break_even_floor as py_break_even_floor  # noqa: E402

# A stub DecisionEngine with the exact attributes the two methods read, so the
# REAL Python methods can run for the parity gate.
_py_de = object.__new__(PyDecisionEngine)
_py_de.calibration = SimpleNamespace(
    predictions=[0.1] * 100,
    brier_score=lambda: 0.18,
)
_py_de.model = SimpleNamespace(
    drift_resets=1,
    updates=110,
    drift_detector=SimpleNamespace(
        last_drift_step=10,
        steps_since_last_drift=lambda updates: 100,
    ),
)


# --- mirror of CConfidenceEngine ---------------------------------------------
PY_BASE_MIN_CONFIDENCE = 0.48
PY_MAX_RAISED_CONFIDENCE = 0.55
PY_BRIER_FLOOR = 0.25
PY_BRIER_CEIL = 0.10
PY_MIN_RAISE_SAMPLES = 30
PY_DRIFT_MAX_PENALTY = 0.02
PY_DRIFT_PENALTY_DECAY_STEPS = 500
PY_STRONG_WITH_SETUP = 0.52
PY_STRONG_WITHOUT_SETUP = 0.65

SIGNAL_WAIT, SIGNAL_STRONG_BUY, SIGNAL_WEAK_BUY, SIGNAL_WEAK_SELL, SIGNAL_STRONG_SELL = 0, 1, 2, 3, 4


def drift_penalty_m(steps_since):
    if steps_since < 0 or steps_since >= PY_DRIFT_PENALTY_DECAY_STEPS:
        return 0.0
    decay = 1.0 - steps_since / PY_DRIFT_PENALTY_DECAY_STEPS
    return PY_DRIFT_MAX_PENALTY * decay


def dynamic_min_m(brier, samples, drift_penalty):
    if samples < PY_MIN_RAISE_SAMPLES:
        return PY_BASE_MIN_CONFIDENCE
    # NOTE: the real Python has NO brier<0 guard — it simply clamps to
    # [BRIER_CEIL, BRIER_FLOOR].  The parity gate locks that behavior.
    brier_clamped = max(PY_BRIER_CEIL, min(PY_BRIER_FLOOR, brier))
    progress = (PY_BRIER_FLOOR - brier_clamped) / (PY_BRIER_FLOOR - PY_BRIER_CEIL)
    dynamic_min = PY_BASE_MIN_CONFIDENCE + progress * (PY_MAX_RAISED_CONFIDENCE - PY_BASE_MIN_CONFIDENCE)
    dynamic_min += drift_penalty
    return max(PY_BASE_MIN_CONFIDENCE, min(dynamic_min, PY_MAX_RAISED_CONFIDENCE + PY_DRIFT_MAX_PENALTY))


def blend_m(composite, candidate_confidence, w=0.5):
    c = candidate_confidence if 0.0 <= candidate_confidence <= 1.0 else composite
    return max(0.0, min(1.0, w * composite + (1.0 - w) * c))


def classify_m(confidence, min_confidence, has_formal_setup, is_long):
    threshold = PY_STRONG_WITH_SETUP if has_formal_setup else PY_STRONG_WITHOUT_SETUP
    if confidence >= threshold and has_formal_setup:
        return SIGNAL_STRONG_BUY if is_long else SIGNAL_STRONG_SELL
    if confidence >= min_confidence:
        return SIGNAL_WEAK_BUY if is_long else SIGNAL_WEAK_SELL
    return SIGNAL_WAIT


def gate_m(composite, candidate_confidence, has_formal_setup, is_long,
           brier, samples, steps_since):
    d = drift_penalty_m(steps_since)
    min_conf = dynamic_min_m(brier, samples, d)
    conf = blend_m(composite, candidate_confidence)
    return classify_m(conf, min_conf, has_formal_setup, is_long), min_conf


# --- mirror of CScoringEngine ------------------------------------------------
REGIME_UNKNOWN, REGIME_TREND_UP, REGIME_TREND_DOWN, REGIME_RANGE, REGIME_COMPRESSION, \
    REGIME_EXPANSION, REGIME_HIGH_VOLATILITY, REGIME_LOW_VOLATILITY, REGIME_TRANSITION = range(9)


def regime_alignment_m(current, required):
    if current == required:
        return 1.0
    trend_family = required in (REGIME_TREND_UP, REGIME_TREND_DOWN)
    range_family = required in (REGIME_RANGE, REGIME_COMPRESSION, REGIME_LOW_VOLATILITY)
    if trend_family and current in (REGIME_TREND_UP, REGIME_TREND_DOWN,
                                    REGIME_EXPANSION, REGIME_HIGH_VOLATILITY):
        return 0.7
    if range_family and current in (REGIME_RANGE, REGIME_COMPRESSION, REGIME_LOW_VOLATILITY):
        return 0.7
    if current in (REGIME_TRANSITION, REGIME_UNKNOWN):
        return 0.4
    return 0.2


def risk_score_m(reward_risk, min_rr, stop_pct, max_stop_pct):
    if reward_risk <= 0.0:
        return 0.0
    rr_ratio = min(1.0, reward_risk / min_rr) if min_rr > 0.0 else 1.0
    fit = 1.0
    if max_stop_pct > 0.0 and stop_pct > 0.0:
        fit = 1.0 if stop_pct <= max_stop_pct else max(0.0, max_stop_pct / stop_pct)
    return 0.7 * rr_ratio + 0.3 * fit


DEFAULT_SCORE_W = (0.30, 0.25, 0.10, 0.25, 0.10)


def composite_m(setup, regime, structure, risk, execution, w=DEFAULT_SCORE_W):
    s = w[0] * setup + w[1] * regime + w[2] * structure + w[3] * risk + w[4] * execution
    return max(0.0, min(1.0, s))


def evaluate_m(cand_setup, cand_required_regime, current_regime, structure_score,
               execution_score, cand_entry, cand_stop, cand_target):
    setup = max(0.0, min(1.0, cand_setup))
    regime = regime_alignment_m(current_regime, cand_required_regime)
    structure = structure_score if 0.0 <= structure_score <= 1.0 else 0.5
    execution = execution_score if 0.0 <= execution_score <= 1.0 else 1.0
    risk_dist = abs(cand_entry - cand_stop)
    stop_pct = risk_dist / cand_entry if (cand_entry > 0.0 and risk_dist > 0.0) else 0.0
    rr = abs(cand_target - cand_entry) / risk_dist if risk_dist > 0.0 else 0.0
    risk = risk_score_m(rr, 2.0, stop_pct, 0.015)
    comp = composite_m(setup, regime, structure, risk, execution)
    return {"setup": setup, "regime": regime, "structure": structure,
            "risk": risk, "execution": execution, "composite": comp}


# --- mirror of CTradeQualityEngine -------------------------------------------
GATE_HIT_RATE_FLOOR_DEFAULT = 0.50
BREAK_EVEN_MARGIN_DEFAULT = 0.05
BREAK_EVEN_FLOOR_MIN_DEFAULT = 0.10
BREAK_EVEN_FLOOR_MAX_DEFAULT = 0.60


def break_even_floor_m(reward_risk, margin):
    if reward_risk <= 0.0:
        return GATE_HIT_RATE_FLOOR_DEFAULT
    m = margin if margin >= 0.0 else BREAK_EVEN_MARGIN_DEFAULT
    raw = 1.0 / (1.0 + reward_risk) + m
    return max(BREAK_EVEN_FLOOR_MIN_DEFAULT, min(raw, BREAK_EVEN_FLOOR_MAX_DEFAULT))


class TradeSim:
    """Mirror of CTradeQualityEngine's position observation + R math."""

    def __init__(self):
        self.records = []

    def start(self, direction, entry, stop, target):
        self.dir = direction
        self.entry = entry
        self.stop = stop
        self.target = target
        self.risk = abs(entry - stop)
        if self.risk <= 0.0:
            self.risk = entry * 0.001
        self.mfe = 0.0
        self.mae = 0.0
        self.hold = 0

    def update(self, high, low):
        self.hold += 1
        if self.dir > 0:
            self.mfe = max(self.mfe, (high - self.entry) / self.risk)
            self.mae = max(self.mae, (self.entry - low) / self.risk)
        else:
            self.mfe = max(self.mfe, (self.entry - low) / self.risk)
            self.mae = max(self.mae, (high - self.entry) / self.risk)

    def close(self, exit_price):
        if self.dir > 0:
            ret = (exit_price - self.entry) / self.risk
        else:
            ret = (self.entry - exit_price) / self.risk
        rr = abs(self.target - self.entry) / self.risk if self.risk > 0.0 else 0.0
        self.records.append({
            "ret": ret, "mfe": self.mfe, "mae": self.mae, "rr": rr,
            "r1": self.mfe >= 1.0, "r2": self.mfe >= 2.0, "r3": self.mfe >= 3.0,
            "hold": self.hold, "won": ret > 0.0,
        })
        return ret


def main():
    # ===== Parity gate 1: classify vs the REAL Python method =============
    print("[PHASE5] --- parity: Classify vs real _classify_signal_strength ---")
    grid = [(0.70, 0.48, True, True), (0.52, 0.48, True, True),
            (0.51, 0.48, True, True), (0.65, 0.48, False, True),
            (0.64, 0.48, False, True), (0.40, 0.48, False, False),
            (0.80, 0.48, True, False), (0.60, 0.48, False, False),
            (0.55, 0.60, True, True), (0.30, 0.48, True, False)]
    py_names = {"wait": SIGNAL_WAIT, "strong_buy": SIGNAL_STRONG_BUY,
                "weak_buy": SIGNAL_WEAK_BUY, "weak_sell": SIGNAL_WEAK_SELL,
                "strong_sell": SIGNAL_STRONG_SELL}
    for conf, minc, setup, long_ in grid:
        py = _py_de._classify_signal_strength(
            confidence=conf, min_confidence=minc, has_formal_setup=setup,
            direction=PyDirection.LONG if long_ else PyDirection.SHORT)
        m = classify_m(conf, minc, setup, long_)
        check(f"classify conf={conf} minc={minc} setup={setup} long={long_} "
              f"(py={py})", m == py_names[py], f"mirror={m}")

    # ===== Parity gate 2: dynamic min-confidence + drift vs real Python ==
    print("[PHASE5] --- parity: DynamicMinConfidence + DriftPenalty vs real ---")
    for brier, steps in [(0.18, 100), (0.05, 0), (0.30, 0), (0.12, 250),
                         (0.18, 500), (-1.0, 100)]:
        py_min = _py_de._dynamic_min_confidence.__wrapped__ if hasattr(
            _py_de._dynamic_min_confidence, "__wrapped__") else None
        # run the real method against a freshly stubbed calibration
        _py_de.calibration.brier_score = lambda b=brier: b
        _py_de.calibration.predictions = [0.1] * 100
        _py_de.model.drift_detector.steps_since_last_drift = lambda updates, s=steps: s
        _py_de.model.drift_detector.last_drift_step = 1 if steps < 500 else None
        py_pen = _py_de._drift_confidence_penalty()
        py_dyn = _py_de._dynamic_min_confidence()
        m_pen = drift_penalty_m(steps)
        m_dyn = dynamic_min_m(brier, 100, m_pen)
        check(f"drift steps={steps} (py={py_pen:.6f})", close(m_pen, py_pen),
              f"mirror={m_pen:.6f}")
        check(f"dynamic_min brier={brier} steps={steps} (py={py_dyn:.6f})",
              close(m_dyn, py_dyn), f"mirror={m_dyn:.6f}")

    # ===== Parity gate 3: break-even floor vs real stage3_gate ===========
    print("[PHASE5] --- parity: BreakEvenFloor vs real stage3_gate ---")
    for rr in [None, 0.0, 1.0, 2.0, 3.0, 4.0, 10.0, 100.0]:
        py = py_break_even_floor(rr, 0.05)
        m = break_even_floor_m(rr if rr else 0.0, 0.05)
        check(f"break_even rr={rr} (py={py:.6f})", close(m, py), f"mirror={m:.6f}")

    # ===== Shared assertion matrix (lockstep with Phase5Tests.mq5) =======
    print("[PHASE5] --- shared assertion matrix ---")

    # --- ConfidenceEngine ---
    check("classify strong_buy w/ setup 0.70",
          classify_m(0.70, 0.48, True, True) == SIGNAL_STRONG_BUY)
    check("classify strong_buy boundary 0.52",
          classify_m(0.52, 0.48, True, True) == SIGNAL_STRONG_BUY)
    check("classify weak_buy below strong w/ setup 0.51",
          classify_m(0.51, 0.48, True, True) == SIGNAL_WEAK_BUY)
    check("classify weak_buy w/o setup 0.65 (not strong)",
          classify_m(0.65, 0.48, False, True) == SIGNAL_WEAK_BUY)
    check("classify wait below min",
          classify_m(0.40, 0.48, False, True) == SIGNAL_WAIT)
    check("classify strong_sell w/ setup",
          classify_m(0.80, 0.48, True, False) == SIGNAL_STRONG_SELL)
    check("classify weak_sell w/o setup",
          classify_m(0.60, 0.48, False, False) == SIGNAL_WEAK_SELL)
    check("classify strong_buy w/ setup at 0.55 even above raised min",
          classify_m(0.55, 0.60, True, True) == SIGNAL_STRONG_BUY)
    check("dynamic_min below sample threshold = 0.48",
          close(dynamic_min_m(0.18, 10, 0.0), 0.48))
    check("dynamic_min brier=0.18 -> 0.5126667",
          close(dynamic_min_m(0.18, 100, 0.0), 0.48 + (0.07 * (0.07 / 0.15)), 1e-9))
    check("dynamic_min brier=0.05 (clamped) -> 0.55",
          close(dynamic_min_m(0.05, 100, 0.0), 0.55))
    check("dynamic_min brier=0.30 (clamped) -> 0.48",
          close(dynamic_min_m(0.30, 100, 0.0), 0.48))
    check("dynamic_min negative brier clamped -> 0.55 (Python has no guard)",
          close(dynamic_min_m(-1.0, 100, 0.0), 0.55))
    check("drift penalty 0 steps -> 0.02",
          close(drift_penalty_m(0), 0.02))
    check("drift penalty 250 steps -> 0.01",
          close(drift_penalty_m(250), 0.01))
    check("drift penalty 500 steps -> 0.0",
          close(drift_penalty_m(500), 0.0))
    check("drift penalty 1000 steps -> 0.0",
          close(drift_penalty_m(1000), 0.0))
    check("gate() returns strong_buy + min 0.5127",
          gate_m(0.80, 0.90, True, True, 0.18, 100, 0)[0] == SIGNAL_STRONG_BUY)
    minc = gate_m(0.80, 0.90, True, True, 0.18, 100, 0)[1]
    check("gate() min_confidence = 0.5327 (0.5127 + drift penalty 0.02)",
          close(minc, 0.5326666667, 1e-6))

    # --- ScoringEngine ---
    check("regime alignment exact = 1.0",
          close(regime_alignment_m(REGIME_TREND_UP, REGIME_TREND_UP), 1.0))
    check("regime alignment trend family = 0.7",
          close(regime_alignment_m(REGIME_EXPANSION, REGIME_TREND_UP), 0.7))
    check("regime alignment range family = 0.7",
          close(regime_alignment_m(REGIME_COMPRESSION, REGIME_RANGE), 0.7))
    check("regime alignment transition = 0.4",
          close(regime_alignment_m(REGIME_TRANSITION, REGIME_TREND_DOWN), 0.4))
    check("regime alignment conflict = 0.2",
          close(regime_alignment_m(REGIME_TREND_DOWN, REGIME_RANGE), 0.2))
    check("risk score rr=4.0 stop-fit = 1.0",
          close(risk_score_m(4.0, 2.0, 0.005, 0.015), 1.0))
    check("risk score rr=1.0 = 0.65",
          close(risk_score_m(1.0, 2.0, 0.005, 0.015), 0.65))
    check("risk score rr=0 -> 0.0", close(risk_score_m(0.0, 2.0, 0.005, 0.015), 0.0))
    check("risk score stop over cap -> 0.85",
          close(risk_score_m(4.0, 2.0, 0.03, 0.015), 0.85))
    check("composite all 1.0 -> 1.0", close(composite_m(1, 1, 1, 1, 1), 1.0))
    check("composite (0.6,1,0.5,1,1) -> 0.83",
          close(composite_m(0.6, 1.0, 0.5, 1.0, 1.0), 0.83))
    ev = evaluate_m(0.8, REGIME_EXPANSION, REGIME_EXPANSION, 0.5, -1.0, 100.0, 99.5, 102.0)
    check("evaluate setup=0.8", close(ev["setup"], 0.8))
    check("evaluate regime=1.0", close(ev["regime"], 1.0))
    check("evaluate structure neutral 0.5", close(ev["structure"], 0.5))
    check("evaluate execution default 1.0", close(ev["execution"], 1.0))
    check("evaluate risk 1.0 (rr=4, stop 0.5%)", close(ev["risk"], 1.0))
    check("evaluate composite (0.8,1,0.5,1,1) -> 0.86",
          close(ev["composite"], 0.3 * 0.8 + 0.25 + 0.05 + 0.25 + 0.10))
    ev2 = evaluate_m(0.6, REGIME_RANGE, REGIME_TREND_DOWN, 0.2, 1.0, 100.0, 99.0, 101.0)
    check("evaluate2 regime conflict 0.2", close(ev2["regime"], 0.2))
    # risk: rr=1.0 -> 0.7*0.5 + 0.3*1.0 = 0.65; composite 0.5125
    check("evaluate2 risk 0.65", close(ev2["risk"], 0.65))
    check("evaluate2 composite 0.5125",
          close(ev2["composite"], 0.3 * 0.6 + 0.25 * 0.2 + 0.1 * 0.2 + 0.25 * 0.65 + 0.1))

    # --- TradeQualityEngine ---
    check("break_even rr=3 margin=0.05 -> 0.30",
          close(break_even_floor_m(3.0, 0.05), 0.30))
    check("break_even rr=1 -> 0.55", close(break_even_floor_m(1.0, 0.05), 0.55))
    check("break_even rr=0 -> 0.50", close(break_even_floor_m(0.0, 0.05), 0.50))
    check("break_even rr=10 -> 0.14091",
          close(break_even_floor_m(10.0, 0.05), 1.0 / 11.0 + 0.05, 1e-9))
    check("break_even rr=100 clamped -> 0.10",
          close(break_even_floor_m(100.0, 0.05), 0.10))

    sim = TradeSim()
    sim.start(1, 100.0, 99.5, 102.0)          # long, risk 0.5, planned rr 4.0
    sim.update(101.0, 99.8)                    # MFE 2.0R, MAE 0.4R
    r = sim.close(101.5)                       # target-side exit at +3.0R
    rec = sim.records[-1]
    check("trade long return_r = 3.0", close(r, 3.0))
    check("trade long mfe 2.0", close(rec["mfe"], 2.0))
    check("trade long mae 0.4", close(rec["mae"], 0.4))
    check("trade long r1+r2 reached, r3 not",
          rec["r1"] and rec["r2"] and not rec["r3"])
    check("trade long hold 1", rec["hold"] == 1)
    check("trade long won", rec["won"])

    sim.start(-1, 100.0, 100.5, 98.0)          # short, risk 0.5, planned rr 4.0
    sim.update(100.2, 99.0)                    # MFE 2.0R
    r2 = sim.close(99.0)                       # +2.0R
    check("trade short return_r = 2.0", close(r2, 2.0))
    check("trade short won", sim.records[-1]["won"])

    # statistics: 2 trades, both won, avg rr 4.0 -> hit 1.0, avg_r 2.5,
    # break-even floor = 1/5 + 0.05 = 0.25
    n = len(sim.records)
    hit = sum(1 for rc in sim.records if rc["won"]) / n
    avg_r = sum(rc["ret"] for rc in sim.records) / n
    avg_rr = sum(rc["rr"] for rc in sim.records) / n
    check("stats n=2", n == 2)
    check("stats hit 1.0", close(hit, 1.0))
    check("stats avg_r 2.5", close(avg_r, 2.5))
    check("stats avg_rr 4.0", close(avg_rr, 4.0))
    check("stats break_even 0.25", close(break_even_floor_m(avg_rr, 0.05), 0.25))

    print(f"\n[PHASE5] === {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
