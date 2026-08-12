#!/usr/bin/env python3
"""TradeQualityEngine real-corpus gate — mirror vs the Python journal.

Feeds REAL R_75 outcomes — produced by the production backtest loop
(VolBandStrategy / VolMomentumStrategy / VolReversionStrategy + the real
BreakevenTrailBroker/PaperBroker + RiskEngine, exactly as run_vol_regime_backtest
does) — through a faithful mirror of the MQL5 CTradeQualityEngine
(Decision/TradeQualityEngine.mqh), and compares its per-strategy statistics
(hit rate / avg R / break-even floor, plus per-trade MAE/MFE) against the
Python journal's own numbers.

The FOURTH leg is the sniper decision-engine path — ``BacktestEngine.run_ticks``
with the default TraderConfig (``DecisionEngine.evaluate`` defaults to
``trading_mode="sniper"``) and the ONLINE ML model learning from every outcome
(``learn=True``) — exactly the leg the head-to-head runs.  Because ``run_ticks``
constructs its own PaperBroker, the harness replays the loop with a capture
broker and PROVES the replica is bit-identical to the real ``run_ticks``
(a fresh model per run is deterministic, so n / avg R / signals / rejected /
model version must all match), then drives the mirror over the captured
sniper trades like the other three legs.

Pipeline per strategy:
  1. stream the R_75 tick corpus through the real strategy + broker
     (capture subclass records each open position's geometry and the
     intrabar (high, low) path it traveled),
  2. drive the mirror engine: StartPosition -> UpdatePosition(path) ->
     ClosePosition(exit), exactly like the MQL5 engine is driven,
  3. compare the mirror's Statistics() against the Python journal:
       n, hit (won = return_r > 0; the production paper has no penalty),
       avg R (mean return_r == metrics.expectancy_r), avg planned RR,
       break-even floor (stage3_gate.break_even_floor(avg_rr, 0.05)).
  4. compare the MAE/MFE distributions (mean/median/p90) mirror vs the
     Python view (the broker's own MFE; MAE from the identical path/formula
     — the journal stores MFE only), and
  5. produce the exit-quality diagnosis: avg R per exit reason (STOP /
     TARGET / TIME / BREAKEVEN) per strategy, flagging the worst.

Keep the mirror in lockstep with Decision/TradeQualityEngine.mqh.
"""

import math
import os
import sys
from dataclasses import replace
from statistics import mean

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[TQCHECK] PASS  {name}")
    else:
        FAIL += 1
        print(f"[TQCHECK] FAIL  {name}  -> {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from synthetic_trader.config import MAX_FEATURE_HISTORY, PaperExecutionConfig, TraderConfig  # noqa: E402
from synthetic_trader.domain import Direction  # noqa: E402
from synthetic_trader.execution.paper import PaperBroker  # noqa: E402
from synthetic_trader.backtest.engine import BacktestEngine  # noqa: E402
from synthetic_trader.models.online import OnlineLogisticModel  # noqa: E402
from synthetic_trader.strategy.decision_engine import DecisionEngine  # noqa: E402
from synthetic_trader.backtest.vol_band import VolBandConfig, VolBandStrategy  # noqa: E402
from synthetic_trader.backtest.vol_momentum import VolMomentumConfig, VolMomentumStrategy  # noqa: E402
from synthetic_trader.backtest.vol_reversion import (  # noqa: E402
    VolReversionConfig,
    VolReversionStrategy,
    BreakevenTrailBroker,
    dedupe_ticks,
)
from synthetic_trader.backtest.engine import load_ticks_csv  # noqa: E402
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder  # noqa: E402
from synthetic_trader.risk.engine import RiskEngine  # noqa: E402
from synthetic_trader.models.garch_calibration import load_calibrated_garch_state  # noqa: E402
from synthetic_trader.live.stage3_gate import break_even_floor as py_break_even_floor  # noqa: E402
from synthetic_trader.features.assembler import clear_assembler_caches  # noqa: E402

# --- corpus (same merge the phase-2/3 harnesses use) --------------------------
CORPUS_PATHS = [
    os.path.join(os.path.dirname(_HERE), "data", "backfill", "R_75_ticks.csv"),
    os.path.join(os.path.dirname(_HERE), "data", "R_75_ticks.csv"),
]

TF = 300  # M5 — the execution timeframe

# --- MQL5 ENUM_STRATEGY ids (Constants.mqh) -----------------------------------
STRATEGY_BAND = 1
STRATEGY_MEANREVERSION = 4  # fade maps here (no dedicated MQL5 enum yet)
# The DecisionEngine sniper leg has no MQL5 enum yet — id 7 is a harness-only
# bucket so the mirror's per-strategy Statistics() isolates it in the
# four-leg head-to-head table.
STRATEGY_SNIPER = 7

# --- MQL5 ENUM_EXIT_REASON ids (Constants.mqh) --------------------------------
EXIT_STOP_HIT, EXIT_TARGET_HIT, EXIT_TIME, EXIT_BREAKEVEN_TRAIL = 1, 2, 3, 4


# --- mirror of CTradeQualityEngine (Decision/TradeQualityEngine.mqh) ----------
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


class MqlTradeQualityEngine:
    """Line-for-line mirror of CTradeQualityEngine (StartPosition /
    UpdatePosition / ClosePosition / Statistics / BreakEvenFloor)."""

    def __init__(self):
        self.records = []
        self._pos = None

    def start(self, strategy, direction, entry, stop, target, opened_at):
        risk = abs(entry - stop)
        if risk <= 0.0:
            risk = entry * 0.001
        self._pos = {
            "strategy": strategy, "dir": direction, "entry": entry, "stop": stop,
            "target": target, "risk": risk, "mfe": 0.0, "mae": 0.0,
            "hold": 0, "opened_at": opened_at,
        }

    def update(self, high, low):
        p = self._pos
        p["hold"] += 1
        if p["dir"] > 0:
            p["mfe"] = max(p["mfe"], (high - p["entry"]) / p["risk"])
            p["mae"] = max(p["mae"], (p["entry"] - low) / p["risk"])
        else:
            p["mfe"] = max(p["mfe"], (p["entry"] - low) / p["risk"])
            p["mae"] = max(p["mae"], (high - p["entry"]) / p["risk"])

    def close(self, exit_price, reason, closed_at):
        p = self._pos
        if p["dir"] > 0:
            ret = (exit_price - p["entry"]) / p["risk"]
        else:
            ret = (p["entry"] - exit_price) / p["risk"]
        rr = abs(p["target"] - p["entry"]) / p["risk"] if p["risk"] > 0.0 else 0.0
        self.records.append({
            "strategy": p["strategy"], "direction": p["dir"], "entry": p["entry"],
            "stop": p["stop"], "target": p["target"], "exit_price": exit_price,
            "risk_distance": p["risk"], "reward_risk": rr, "return_r": ret,
            "mae_r": p["mae"], "mfe_r": p["mfe"],
            "r1": p["mfe"] >= 1.0, "r2": p["mfe"] >= 2.0, "r3": p["mfe"] >= 3.0,
            "hold_bars": p["hold"], "exit_reason": reason, "won": ret > 0.0,
        })
        self._pos = None
        return ret

    def stats(self, strategy):
        n = 0
        sum_r = 0.0
        sum_rr = 0.0
        wins = 0
        for r in self.records:
            if strategy is not None and r["strategy"] != strategy:
                continue
            n += 1
            sum_r += r["return_r"]
            sum_rr += r["reward_risk"]
            if r["won"]:
                wins += 1
        if n == 0:
            return {"n": 0, "hit": 0.0, "avg_r": 0.0, "expectancy": 0.0,
                    "avg_rr": 0.0, "break_even": GATE_HIT_RATE_FLOOR_DEFAULT}
        avg_rr = sum_rr / n
        return {"n": n, "hit": wins / n, "avg_r": sum_r / n,
                "expectancy": sum_r / n, "avg_rr": avg_rr,
                "break_even": break_even_floor_m(avg_rr, BREAK_EVEN_MARGIN_DEFAULT)}


# --- capture broker: real production broker + per-trade path/geometry ---------
class CaptureBroker(BreakevenTrailBroker):
    """Real BreakevenTrailBroker (PaperBroker when trail_frac == 0) that also
    records each open position's geometry and its intrabar (high, low) path —
    the exact inputs the MQL5 engine's StartPosition/UpdatePosition consume."""

    def __init__(self, config, breakeven_trail_frac=0.0):
        super().__init__(config, breakeven_trail_frac)
        self.paths = {}
        self.geometry = {}
        self.mfe_at_close = {}
        self._own_mfe = {}

    def submit(self, intent):
        position = super().submit(intent)
        s = intent.signal
        self.paths[position.id] = []
        self.geometry[position.id] = (
            s.entry, s.stop_loss, s.take_profit,
            1 if s.direction is Direction.LONG else -1,
        )
        return position

    def _maybe_close(self, position, candle):
        pid = position.id
        self.paths[pid].append((candle.high, candle.low))
        # Track the broker's own MFE (same formula, same candles) so the final
        # value at the closing candle is captured — the broker's _mfe_r pops
        # its state on close, so it cannot be read after super() returns.
        s = position.signal
        risk = abs(s.entry - s.stop_loss)
        if risk <= 0.0:
            risk = s.entry * 0.001
        if s.direction is Direction.LONG:
            mfe = (candle.high - s.entry) / risk
        else:
            mfe = (s.entry - candle.low) / risk
        self._own_mfe[pid] = max(self._own_mfe.get(pid, 0.0), mfe)
        outcome = super()._maybe_close(position, candle)
        if outcome is not None:
            self.mfe_at_close[pid] = self._own_mfe[pid]
        return outcome


class CapturePaperBroker(PaperBroker):
    """Real PaperBroker (the sniper/run_ticks broker — no trail) that also
    records each open position's geometry and its intrabar (high, low) path,
    exactly like CaptureBroker does for the breakeven-trail legs."""

    def __init__(self, config):
        super().__init__(config)
        self.paths = {}
        self.geometry = {}
        self.mfe_at_close = {}
        self._own_mfe = {}

    def submit(self, intent):
        position = super().submit(intent)
        s = intent.signal
        self.paths[position.id] = []
        self.geometry[position.id] = (
            s.entry, s.stop_loss, s.take_profit,
            1 if s.direction is Direction.LONG else -1,
        )
        return position

    def _maybe_close(self, position, candle):
        pid = position.id
        self.paths[pid].append((candle.high, candle.low))
        s = position.signal
        risk = abs(s.entry - s.stop_loss)
        if risk <= 0.0:
            risk = s.entry * 0.001
        if s.direction is Direction.LONG:
            mfe = (candle.high - s.entry) / risk
        else:
            mfe = (s.entry - candle.low) / risk
        self._own_mfe[pid] = max(self._own_mfe.get(pid, 0.0), mfe)
        outcome = super()._maybe_close(position, candle)
        if outcome is not None:
            self.mfe_at_close[pid] = self._own_mfe[pid]
        return outcome


class TimeExitCapturePaperBroker(CapturePaperBroker):
    """CapturePaperBroker with a TIME-BASED exit policy (research): the
    take-profit is ignored entirely — a position exits only at the 1R stop
    or at the signal's hold horizon (``signal.horizon_sec``, the mean
    positive-drift horizon the journal's TIME exits measured at +0.394R),
    exactly ``PaperBroker._maybe_close`` minus the target branch.  Entry
    geometry/gates are untouched, so the production min-RR gates still see
    the planned 1.9R and behave identically."""

    def _maybe_close(self, position, candle):
        pid = position.id
        self.paths[pid].append((candle.high, candle.low))
        signal = position.signal
        risk = abs(signal.entry - signal.stop_loss)
        if risk <= 0.0:
            risk = signal.entry * 0.001
        if signal.direction is Direction.LONG:
            mfe = (candle.high - signal.entry) / risk
        else:
            mfe = (signal.entry - candle.low) / risk
        self._own_mfe[pid] = max(self._own_mfe.get(pid, 0.0), mfe)
        expired = (candle.open_time + candle.timeframe_sec
                   >= signal.snapshot.epoch + signal.horizon_sec)
        if signal.direction is Direction.LONG:
            stop_hit = candle.low <= signal.stop_loss
        else:
            stop_hit = candle.high >= signal.stop_loss
        outcome = None
        if stop_hit:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.stop_loss),
                candle.open_time + candle.timeframe_sec,
            )
        elif expired:
            outcome = self._close_at_price(
                position,
                self._apply_exit_slippage(signal, candle.close),
                candle.open_time + candle.timeframe_sec,
            )
        if outcome is not None:
            self.mfe_at_close[pid] = self._own_mfe[pid]
        return outcome


def _learn_outcome(model, outcome):
    """The exact BacktestEngine._record_and_learn online-ML update."""
    label = 1 if outcome.won else 0
    model.update(
        dict(outcome.features),
        label=label,
        sample_weight=min(2.0, max(0.25, abs(outcome.return_r))),
    )


def run_sniper_ticks_captured(ticks, timeframe_sec=300, model=None, config=None,
                               time_exit=False, entry_filter=None):
    """Line-for-line replica of BacktestEngine.run_ticks (default TraderConfig,
    learn=True — the ML model learns from every outcome) with the capture
    broker swapped in, so the sniper leg's geometry/path/MFE are captured
    while the decisions, risk gates and model updates are byte-identical to
    the production path.  ``model`` may be injected (recording subclass) for
    parity debugging; default is a fresh OnlineLogisticModel.

    ``config`` is an opt-in research override (a modified TraderConfig, e.g.
    a re-tuned take_profit_rr / min_reward_risk) run through the REAL path;
    when None the production defaults are used.  ``time_exit`` swaps in the
    TimeExitCapturePaperBroker (target ignored; exit at the 1R stop or the
    hold horizon) — research only, no production ground truth exists for it.
    ``entry_filter`` is an opt-in callable ``filter(signal) -> bool`` applied
    AFTER the risk engine approves: signals that fail it are counted as
    filtered (``broker.filtered``) and never submitted, so the online ML
    model never learns from them — a production-faithful entry gate.  Only
    entry-time information may be used (the signal's snapshot features /
    epoch); no lookahead."""
    symbol = "R_75"
    trader = TraderConfig.default() if config is None else config
    base_profile = trader.symbols[symbol]
    higher_timeframe = max(base_profile.higher_timeframe_sec, timeframe_sec * 5)
    profile = replace(
        base_profile,
        default_timeframe_sec=timeframe_sec,
        higher_timeframe_sec=higher_timeframe,
    )
    config = replace(trader, symbols={**trader.symbols, symbol: profile})
    if model is None:
        model = OnlineLogisticModel(config.model)

    builders = MultiTimeframeCandleBuilder(symbol, [timeframe_sec, higher_timeframe])
    histories = {timeframe_sec: [], higher_timeframe: []}
    decision_engine = DecisionEngine(config, model)
    risk_engine = RiskEngine(config.risk)
    broker = (TimeExitCapturePaperBroker(config.paper) if time_exit
              else CapturePaperBroker(config.paper))
    broker.filtered = 0
    outcomes = []
    signals = 0
    rejected = 0

    for tick in sorted(ticks, key=lambda item: item.epoch):
        risk_engine.sync_session_day(int(tick.epoch // 86400))
        closed = builders.update(tick)
        for tf, candle in closed.items():
            if tf != timeframe_sec:
                histories[tf].append(candle)
        primary = closed.get(timeframe_sec)
        if primary is None:
            continue
        for outcome in broker.on_candle(primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)
            _learn_outcome(model, outcome)
        histories[timeframe_sec].append(primary)
        report = decision_engine.evaluate(
            symbol=symbol,
            candles=histories[timeframe_sec][-MAX_FEATURE_HISTORY:],
            higher_timeframe_candles=histories[higher_timeframe][-MAX_FEATURE_HISTORY:],
        )
        if report.signal is None:
            continue
        signals += 1
        risk_decision = risk_engine.evaluate(report.signal)
        if not risk_decision.approved or risk_decision.intent is None:
            rejected += 1
            continue
        if entry_filter is not None and not entry_filter(report.signal):
            broker.filtered += 1
            continue
        broker.submit(risk_decision.intent)
        risk_engine.register_open()

    flushed = builders.flush()
    final_primary = flushed.get(timeframe_sec)
    if final_primary is not None:
        for outcome in broker.on_candle(final_primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)
            _learn_outcome(model, outcome)
        for outcome in broker.close_all(final_primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)
            _learn_outcome(model, outcome)

    print(f"[TQCHECK] sniper: signals={signals} rejected={rejected} "
          f"filtered={broker.filtered} closed={len(outcomes)} model={model.version}")
    return outcomes, broker, signals, rejected, model


def walk_forward_stage3_gate(outcomes, broker, min_samples=10, margin=0.05):
    """Tag every trade with its walk-forward Stage-3 gate state at entry.

    Exactly the band backtest's rule (BandBackTests.mq5) and the Python
    ``gate_backtest.simulate_gate_walk_forward``: at each entry the gate sees
    ONLY outcomes whose hold window resolved STRICTLY before that entry
    (``closed_at < opened_at`` — no lookahead, no same-instant peeking), and
    decides:

      samples < min_samples           -> still_learning (paper warm-up)
      samples >= min && hit >= floor  -> proven (would trade)
      samples >= min && hit <  floor  -> suppressed (stand aside)

    The floor is the per-geometry break-even rate of the RUNNING average
    planned RR of the resolved trades (known at emission — RR is a property
    of each trade's own levels, so accumulating it is not outcome
    lookahead): ``1/(1+avg_rr) + margin``, the exact
    ``stage3_gate.break_even_floor`` math.

    Returns a list of per-trade dicts (same order as ``outcomes``) with the
    gate state, the floor / hit / samples / avg-RR the gate saw at entry,
    plus the trade's own outcome (won / return_r / planned RR).
    """
    ordered = sorted(outcomes, key=lambda o: o.opened_at)
    by_close = sorted(outcomes, key=lambda o: o.closed_at)

    # Running evidence: only outcomes resolved strictly before the current
    # entry are visible (closed_at < opened_at).
    r_idx = 0
    n_resolved = 0
    won_resolved = 0
    rr_resolved = 0.0
    tags = []
    for o in ordered:
        while r_idx < len(by_close) and by_close[r_idx].closed_at < o.opened_at:
            earlier = by_close[r_idx]
            entry, stop, target, d = broker.geometry[earlier.position_id]
            risk = abs(entry - stop) or entry * 0.001
            rr_resolved += abs(target - entry) / risk
            won_resolved += 1 if earlier.won else 0
            n_resolved += 1
            r_idx += 1

        avg_rr = (rr_resolved / n_resolved) if n_resolved else None
        floor = py_break_even_floor(avg_rr, margin)
        hit = (won_resolved / n_resolved) if n_resolved else 0.0
        if n_resolved < min_samples:
            state = "still_learning"
        elif hit >= floor:
            state = "proven"
        else:
            state = "suppressed"

        entry, stop, target, d = broker.geometry[o.position_id]
        risk = abs(entry - stop) or entry * 0.001
        tags.append({
            "state": state,
            "floor_at_entry": floor,
            "hit_at_entry": hit,
            "samples_at_entry": n_resolved,
            "avg_rr_at_entry": avg_rr,
            "won": o.won,
            "return_r": o.return_r,
            "planned_rr": abs(target - entry) / risk,
            "opened_at": o.opened_at,
        })
    # Tags must come back in the same order as the input outcomes (the caller
    # pairs them with the mirror records by index).
    by_open = {o.position_id: t for o, t in zip(ordered, tags)}
    return [by_open[o.position_id] for o in outcomes]


def report_stage3_gate(name, outcomes, broker, min_samples=10, margin=0.05):
    """Kept vs suppressed split for one leg, in the band backtest's format."""
    tags = walk_forward_stage3_gate(outcomes, broker, min_samples, margin)
    kept = [t for t in tags if t["state"] != "suppressed"]
    suppressed = [t for t in tags if t["state"] == "suppressed"]

    def _exp(ts):
        return (sum(t["return_r"] for t in ts) / len(ts)) if ts else 0.0

    def _hit(ts):
        return (sum(1 for t in ts if t["won"]) / len(ts)) if ts else 0.0

    proven = sum(1 for t in tags if t["state"] == "proven")
    learning = sum(1 for t in tags if t["state"] == "still_learning")
    mean_floor = (sum(t["floor_at_entry"] for t in tags) / len(tags)) if tags else 0.0
    all_hit = _hit(tags)
    beatable = (mean_floor > 0.0) and (all_hit >= mean_floor)

    print(f"[TQCHECK] {name} walk-forward Stage-3 gate "
          f"(min_samples={min_samples}, margin={margin}):")
    print(f"[TQCHECK]   floor = 1/(1+avg planned RR) + margin;  mean floor at "
          f"entry {mean_floor*100:.1f}%")
    print(f"[TQCHECK]   KEPT (would trade):       n={len(kept):4d}  "
          f"hit={_hit(kept)*100:4.1f}%  exp={_exp(kept):+.3f}R  "
          f"[proven {proven}, still_learning {learning}]")
    print(f"[TQCHECK]   SUPPRESSED (stand aside): n={len(suppressed):4d}  "
          f"hit={_hit(suppressed)*100:4.1f}%  exp={_exp(suppressed):+.3f}R")
    print(f"[TQCHECK]   VERDICT: achieved hit {all_hit*100:.1f}% "
          f"{'BEATS' if beatable else 'does NOT beat'} the {mean_floor*100:.1f}% floor "
          f"— the {name} geometry is {'floor-beatable' if beatable else 'NOT floor-beatable'} "
          f"on this window")

    # --- hard checks: the walk-forward tagging is self-consistent -----------
    check(f"{name} gate states account for all trades", len(tags) == len(outcomes),
          f"{len(tags)} != {len(outcomes)}")
    check(f"{name} suppressed trades were below floor at entry",
          all(t["hit_at_entry"] < t["floor_at_entry"] for t in suppressed) if suppressed else True)
    check(f"{name} proven trades cleared floor with >= min samples",
          all(t["hit_at_entry"] >= t["floor_at_entry"]
              and t["samples_at_entry"] >= min_samples for t in kept if t["state"] == "proven"))
    check(f"{name} still_learning only below min_samples",
          all(t["samples_at_entry"] < min_samples
              for t in tags if t["state"] == "still_learning"))
    return tags


def infer_reason(outcome, geometry, mfe_r, trail_frac):
    entry, stop, target, _ = geometry
    risk = abs(entry - stop)
    if risk <= 0.0:
        risk = entry * 0.001
    if abs(outcome.exit - target) <= 1e-9:
        return EXIT_TARGET_HIT
    if trail_frac > 0.0 and mfe_r >= trail_frac * (abs(target - entry) / risk) \
            and abs(outcome.exit - entry) <= 1e-9:
        return EXIT_BREAKEVEN_TRAIL
    if abs(outcome.exit - stop) <= 1e-9:
        return EXIT_STOP_HIT
    return EXIT_TIME


def run_strategy(name, strategy_cls, config_cls, ticks, garch_state):
    """Replicate run_vol_regime_backtest's loop with the capture broker."""
    config = replace(TraderConfig.default(), paper=PaperExecutionConfig())
    risk_config = replace(config.risk, min_confidence=0.0, min_reward_risk=0.0)
    risk_engine = RiskEngine(risk_config)
    strategy = strategy_cls("R_75", TF, config=config_cls(), garch_state=garch_state)
    trail_frac = getattr(strategy.config, "breakeven_trail_frac", 0.0) or 0.0
    broker = CaptureBroker(PaperExecutionConfig(), breakeven_trail_frac=trail_frac)
    builders = MultiTimeframeCandleBuilder("R_75", [TF])
    outcomes = []
    signals = 0
    rejected = 0

    for tick in sorted(ticks, key=lambda t: t.epoch):
        if risk_engine.sync_session_day(int(tick.epoch // 86400)):
            pass
        closed = builders.update(tick)
        for tf, candle in closed.items():
            if tf != TF:
                continue
            for outcome in broker.on_candle(candle):
                outcomes.append(outcome)
                risk_engine.register_outcome(outcome)
            signal = strategy.on_candle(candle)
            if signal is None:
                continue
            signals += 1
            rd = risk_engine.evaluate(signal)
            if not rd.approved or rd.intent is None:
                rejected += 1
                continue
            broker.submit(rd.intent)
            risk_engine.register_open()

    flushed = builders.flush()
    final_primary = flushed.get(TF)
    if final_primary is not None:
        for outcome in broker.on_candle(final_primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)
        for outcome in broker.close_all(final_primary):
            outcomes.append(outcome)
            risk_engine.register_outcome(outcome)

    print(f"[TQCHECK] {name}: signals={signals} rejected={rejected} "
          f"closed={len(outcomes)} trail_frac={trail_frac}")
    return outcomes, broker, trail_frac


def compare_strategy(name, strategy_id, strategy_cls, config_cls, ticks, garch_state):
    print(f"[TQCHECK] --- {name} ---")
    outcomes, broker, trail_frac = run_strategy(name, strategy_cls, config_cls,
                                                ticks, garch_state)
    return compare_leg(name, strategy_id, outcomes, broker, trail_frac)


def compare_sniper(ticks, timeframe_sec=300):
    """The fourth leg: the sniper decision-engine path via run_ticks.

    Ground truth is the REAL ``BacktestEngine.run_ticks`` (default
    TraderConfig, fresh model, learn=True — the ML model's calls AND its
    online learning are part of the path, exactly as the head-to-head runs
    it).  The captured replica must match it on n / avg R / signals /
    rejected / model version (deterministic model, so the trajectories are
    identical), then the trades are replayed through the mirror like the
    other legs.
    """
    print("[TQCHECK] --- sniper (DecisionEngine via BacktestEngine.run_ticks) ---")
    # build_snapshot feeds MODULE-LEVEL cached EGARCH / session-filter /
    # fingerprint detectors (features/assembler.py), so the two runs must
    # each start from cleared caches or the second inherits the first's
    # warm-up state and the trajectories diverge.
    clear_assembler_caches()
    real_engine = BacktestEngine(config=TraderConfig.default())
    real_res = real_engine.run_ticks(ticks, "R_75", timeframe_sec=timeframe_sec)

    clear_assembler_caches()
    outcomes, broker, signals, rejected, model = run_sniper_ticks_captured(
        ticks, timeframe_sec)
    n_py = len(outcomes)
    avg_r_replica = mean(o.return_r for o in outcomes) if n_py else 0.0
    hit_replica = sum(1 for o in outcomes if o.won) / n_py if n_py else 0.0
    mt = real_res.metrics

    check("sniper replica n == run_ticks", n_py == mt.trades,
          f"replica={n_py} run_ticks={mt.trades}")
    check("sniper replica hit == run_ticks", close(hit_replica, mt.win_rate, 1e-12),
          f"replica={hit_replica:.6f} run_ticks={mt.win_rate:.6f}")
    check("sniper replica avgR == run_ticks", close(avg_r_replica, mt.expectancy_r, 1e-9),
          f"replica={avg_r_replica:.6f} run_ticks={mt.expectancy_r:.6f}")
    check("sniper replica signals == run_ticks", signals == real_res.signals,
          f"replica={signals} run_ticks={real_res.signals}")
    check("sniper replica rejected == run_ticks", rejected == real_res.rejected_signals,
          f"replica={rejected} run_ticks={real_res.rejected_signals}")
    check("sniper model version == run_ticks", model.version == real_res.model_version,
          f"replica={model.version} run_ticks={real_res.model_version}")
    print(f"[TQCHECK] sniper run_ticks ground truth: {real_res.model_version} "
          f"{mt.trades} trades {mt.win_rate*100:.1f}% hit {mt.expectancy_r:+.3f}R")

    st = compare_leg("sniper", STRATEGY_SNIPER, outcomes, broker, 0.0)

    # Walk-forward Stage-3 gate over the sniper leg: tag every trade by
    # whether its per-geometry break-even floor was beatable at entry (only
    # outcomes resolved strictly before it are visible — no lookahead), and
    # split kept vs suppressed like the band backtest does.
    tags = report_stage3_gate("sniper", outcomes, broker)
    st["gate_tags"] = tags
    st["gate_kept"] = sum(1 for t in tags if t["state"] != "suppressed")
    st["gate_suppressed"] = sum(1 for t in tags if t["state"] == "suppressed")

    # --- re-tuned geometry end-to-end (the probe's only floor-clearing cell) ---
    # The MFE replay probe found exactly one geometry where hit >= its floor:
    # target 0.60R with the stop unchanged (RR 0.60, hit 60.1%, +0.006R) —
    # every toward-MFE target (0.76R median MFE -> RR 0.76, hit 53.4%) and
    # every production-legal RR >= 1.2 cell was negative.  That winner is
    # BELOW the production minimums (RiskEngine.min_reward_risk=1.2 and the
    # profile min_primary_reward_risk=1.2), so this run measures the real
    # DecisionEngine path with the research min-RR override and counts how
    # many of the resulting trades the production gates would have vetoed.
    retuned_trader = TraderConfig.default()
    retuned_profile = replace(
        retuned_trader.symbols["R_75"],
        take_profit_rr=0.60,
        min_primary_reward_risk=0.0,  # research: liquidity-path target gate
    )
    retuned_risk = replace(retuned_trader.risk, min_reward_risk=0.0)  # research
    retuned_config = replace(
        retuned_trader,
        symbols={**retuned_trader.symbols, "R_75": retuned_profile},
        risk=retuned_risk,
    )
    clear_assembler_caches()
    r_outcomes, r_broker, r_signals, r_rejected, r_model = run_sniper_ticks_captured(
        ticks, 300, config=retuned_config)
    n_r = len(r_outcomes)
    hit_r = (sum(1 for o in r_outcomes if o.won) / n_r) if n_r else 0.0
    avg_r_r = (mean(o.return_r for o in r_outcomes)) if n_r else 0.0
    rr_r = []
    for o in r_outcomes:
        entry, stop, target, _ = r_broker.geometry[o.position_id]
        risk = abs(entry - stop) or entry * 0.001
        rr_r.append(abs(target - entry) / risk)
    avg_rr_r = mean(rr_r) if rr_r else 0.0
    floor_r = py_break_even_floor(avg_rr_r, 0.05) if rr_r else 0.5
    prod_blocked = sum(1 for v in rr_r if v < 1.2)
    print("[TQCHECK] --- sniper re-tuned geometry end-to-end "
          "(take_profit_rr=0.60, stop 1R, research min-RR=0) ---")
    print(f"[TQCHECK]   signals={r_signals} risk-rejected={r_rejected} "
          f"closed={n_r} model={r_model.version}")
    print(f"[TQCHECK]   n={n_r} hit={hit_r*100:.1f}% avgR={avg_r_r:+.3f} "
          f"avgRR={avg_rr_r:.2f} floor={floor_r*100:.1f}%")
    print(f"[TQCHECK]   production veto: {prod_blocked}/{n_r} of these trades carry "
          f"planned RR < 1.2 (RiskEngine.min_reward_risk + profile "
          f"min_primary_reward_risk) — the production path would NOT emit this "
          f"geometry")
    check("sniper retuned run executed trades", n_r > 0, f"n={n_r}")
    check("sniper retuned geometry is production-illegal (all RR < 1.2)",
          prod_blocked == n_r and n_r > 0,
          f"prod_blocked={prod_blocked}/{n_r}")
    report_stage3_gate("sniper retuned", r_outcomes, r_broker)
    st["retuned"] = {"n": n_r, "hit": hit_r, "avg_r": avg_r_r,
                     "avg_rr": avg_rr_r, "floor": floor_r,
                     "prod_blocked": prod_blocked}

    # --- entry-gated time-exit leg end-to-end --------------------------------
    # The live emission gate (UTC 12-24h & |range_z_50| < 1.0, enforced INSIDE
    # DecisionEngine.evaluate via SymbolProfile.entry_gate_*) with the research
    # time-exit broker — the configuration the entry-filter probes measured at
    # +0.09..0.14R net@0.05.  Measured with the gate in the live path (not a
    # probe hook), so the ML model, risk engine and broker all see it.
    clear_assembler_caches()
    g_out, g_broker, g_sig, g_rej, g_model = run_sniper_ticks_captured(
        ticks, 300, time_exit=True)
    ng = len(g_out)
    hit_g = (sum(1 for o in g_out if o.won) / ng) if ng else 0.0
    avg_g = (mean(o.return_r for o in g_out)) if ng else 0.0
    rr_g = []
    for o in g_out:
        entry, stop, target, _ = g_broker.geometry[o.position_id]
        risk = abs(entry - stop) or entry * 0.001
        rr_g.append(abs(target - entry) / risk)
    avg_rr_g = mean(rr_g) if rr_g else 0.0
    floor_g = py_break_even_floor(avg_rr_g, 0.05) if rr_g else 0.5
    wins = [o.return_r for o in g_out if o.return_r > 0]
    losses = [abs(o.return_r) for o in g_out if o.return_r <= 0]
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    be_g = avg_loss / (avg_win + avg_loss) if (avg_win + avg_loss) > 0 else 1.0
    ordered = sorted(g_out, key=lambda o: o.closed_at)
    peak = cum = max_dd = 0.0
    for o in ordered:
        cum += o.return_r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    tags_g = walk_forward_stage3_gate(g_out, g_broker)
    kept_g = [t for t in tags_g if t["state"] != "suppressed"]
    kept_hit_g = (sum(1 for t in kept_g if t["won"]) / len(kept_g) * 100
                  if kept_g else 0.0)
    print("[TQCHECK] --- sniper entry-gated time-exit leg end-to-end "
          "(UTC 12-24h & |range_z|<1.0 gate in DecisionEngine.evaluate) ---")
    print(f"[TQCHECK]   signals={g_sig} risk-rejected={g_rej} closed={ng} "
          f"model={g_model.version}")
    print(f"[TQCHECK]   n={ng} hit={hit_g*100:.1f}% avgR={avg_g:+.3f} gross | "
          f"net@0.05={avg_g-0.05:+.3f}R | net@0.10={avg_g-0.10:+.3f}R")
    print(f"[TQCHECK]   avgRR={avg_rr_g:.2f} floor={floor_g*100:.1f}% -> "
          f"{'BEATS' if hit_g >= floor_g else 'does NOT beat'} | "
          f"payout BE={be_g*100:.1f}% -> "
          f"{'BEATS' if hit_g >= be_g else 'does NOT beat'}")
    print(f"[TQCHECK]   maxDD={max_dd:.2f}R (realized cumulative-R) | "
          f"walk-forward gate: KEPT {len(kept_g)} (hit {kept_hit_g:.1f}%) "
          f"/ SUPPRESSED {ng - len(kept_g)}")
    st["entry_gated_time_exit"] = {
        "n": ng, "hit": hit_g, "avg_r": avg_g, "avg_rr": avg_rr_g,
        "floor": floor_g, "be_realized": be_g, "max_dd": max_dd,
        "kept": len(kept_g),
    }
    return st


def compare_leg(name, strategy_id, outcomes, broker, trail_frac):
    tqe = MqlTradeQualityEngine()

    # --- Python journal numbers ---------------------------------------------
    n_py = len(outcomes)
    hit_py = sum(1 for o in outcomes if o.won) / n_py if n_py else 0.0
    avg_r_py = mean(o.return_r for o in outcomes) if n_py else 0.0
    rr_vals = []
    for o in outcomes:
        entry, stop, target, _ = broker.geometry[o.position_id]
        risk = abs(entry - stop) or entry * 0.001
        rr_vals.append(abs(target - entry) / risk)
    avg_rr_py = mean(rr_vals) if rr_vals else 0.0
    floor_py = py_break_even_floor(avg_rr_py, 0.05) if rr_vals else 0.5

    # --- replay every trade through the mirror engine -----------------------
    # The Python journal stores MFE (the trail's own _mfe_r) but NOT MAE —
    # the Python-side MAE is the identical formula applied to the identical
    # path (the same computation the mirror performs), so a per-trade match
    # to 1e-9 proves the replay is faithful on both axes.
    max_mfe_dev = 0.0
    max_mae_dev = 0.0
    py_mae = {}
    for i, o in enumerate(outcomes):
        geom = broker.geometry[o.position_id]
        entry, stop, target, d = geom
        mfe_py = broker.mfe_at_close[o.position_id]
        risk = abs(entry - stop) or entry * 0.001
        mae_py = 0.0
        for high, low in broker.paths[o.position_id]:
            mae = (entry - low) / risk if d > 0 else (high - entry) / risk
            mae_py = max(mae_py, mae)
        py_mae[o.position_id] = mae_py
        tqe.start(strategy_id, d, entry, stop, target, o.opened_at)
        for high, low in broker.paths[o.position_id]:
            tqe.update(high, low)
        reason = infer_reason(o, geom, mfe_py, trail_frac)
        ret = tqe.close(o.exit, reason, o.closed_at)
        check(f"{name} trade#{i} return_r mirror==py", close(ret, o.return_r),
              f"mirror={ret:.6f} py={o.return_r:.6f}")
        max_mfe_dev = max(max_mfe_dev, abs(tqe.records[-1]["mfe_r"] - mfe_py))
        max_mae_dev = max(max_mae_dev, abs(tqe.records[-1]["mae_r"] - mae_py))
    check(f"{name} per-trade MFE matches broker (max dev {max_mfe_dev:.2e})",
          max_mfe_dev < 1e-9, f"max_dev={max_mfe_dev:.3e}")
    check(f"{name} per-trade MAE matches python view (max dev {max_mae_dev:.2e})",
          max_mae_dev < 1e-9, f"max_dev={max_mae_dev:.3e}")

    # --- mirror stats vs the Python journal ---------------------------------
    st = tqe.stats(strategy_id)
    check(f"{name} n mirror==py", st["n"] == n_py, f"mirror={st['n']} py={n_py}")
    check(f"{name} hit mirror==py", close(st["hit"], hit_py, 1e-12),
          f"mirror={st['hit']:.6f} py={hit_py:.6f}")
    check(f"{name} avg R mirror==py", close(st["avg_r"], avg_r_py, 1e-9),
          f"mirror={st['avg_r']:.6f} py={avg_r_py:.6f}")
    check(f"{name} avg planned RR mirror==py", close(st["avg_rr"], avg_rr_py, 1e-9),
          f"mirror={st['avg_rr']:.6f} py={avg_rr_py:.6f}")
    check(f"{name} break-even floor mirror==py", close(st["break_even"], floor_py, 1e-9),
          f"mirror={st['break_even']:.6f} py={floor_py:.6f}")

    # --- MAE/MFE distribution: mirror vs Python view -------------------------
    def _dist(vals):
        if not vals:
            return (0.0, 0.0, 0.0)
        s = sorted(vals)
        n = len(s)
        med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
        p90 = s[min(n - 1, int(math.ceil(0.90 * n)) - 1)]
        return (sum(s) / n, med, p90)

    m_mfe = [r["mfe_r"] for r in tqe.records]
    m_mae = [r["mae_r"] for r in tqe.records]
    p_mfe = [broker.mfe_at_close[o.position_id] for o in outcomes]
    p_mae = [py_mae[o.position_id] for o in outcomes]
    for label, a, b in [("MFE", m_mfe, p_mfe), ("MAE", m_mae, p_mae)]:
        sa, sb = _dist(a), _dist(b)
        ok = all(close(x, y, 1e-9) for x, y in zip(sa, sb))
        check(f"{name} {label} distribution mirror==py "
              f"(mean {sa[0]:.3f} med {sa[1]:.3f} p90 {sa[2]:.3f})", ok,
              f"mirror={sa} py={sb}")

    # --- exit-quality diagnosis ----------------------------------------------
    # Which exit reason carries the worst average R per strategy — the
    # journal's answer to "are we losing to stops, timeouts, or the trail?"
    reasons = {EXIT_STOP_HIT: "STOP", EXIT_TARGET_HIT: "TARGET",
               EXIT_TIME: "TIME", EXIT_BREAKEVEN_TRAIL: "BREAKEVEN"}
    print(f"[TQCHECK] {name} exit-quality breakdown (avg R per exit reason):")
    print(f"[TQCHECK]   {'reason':<10} {'n':>4} {'hit':>6} {'avgR':>8} {'avgMFE':>7} {'avgMAE':>7}")
    agg = {}
    for r in tqe.records:
        agg.setdefault(r["exit_reason"], []).append(r)
    worst = (None, None)
    for reason, recs in sorted(agg.items()):
        avg_r = sum(x["return_r"] for x in recs) / len(recs)
        hit = sum(1 for x in recs if x["won"]) / len(recs)
        avg_mfe = sum(x["mfe_r"] for x in recs) / len(recs)
        avg_mae = sum(x["mae_r"] for x in recs) / len(recs)
        rname = reasons.get(reason, f"R{reason}")
        if worst[1] is None or avg_r < worst[1]:
            worst = (rname, avg_r)
        print(f"[TQCHECK]   {rname:<10} {len(recs):>4} {hit*100:>5.1f}% {avg_r:>+8.3f} "
              f"{avg_mfe:>7.3f} {avg_mae:>7.3f}")
    total_n = sum(len(v) for v in agg.values())
    check(f"{name} exit reasons account for all trades", total_n == st["n"],
          f"{total_n} != {st['n']}")
    print(f"[TQCHECK] {name} worst exit reason by avg R: {worst[0]} ({worst[1]:+.3f} R)")

    # --- report row ----------------------------------------------------------
    print(f"[TQCHECK] {name:>8}  n={st['n']:4d}  hit={st['hit']*100:5.1f}%  "
          f"avgR={st['avg_r']:+.3f}  avgRR={st['avg_rr']:.2f}  "
          f"breakEven={st['break_even']*100:.1f}%   (py: n={n_py} hit={hit_py*100:.1f}% "
          f"avgR={avg_r_py:+.3f} floor={floor_py*100:.1f}%)")
    return st


def main():
    ticks = dedupe_ticks([
        t
        for p in CORPUS_PATHS
        if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    print(f"[TQCHECK] loaded {len(ticks)} R_75 ticks")
    if len(ticks) < 10000:
        print("[TQCHECK] corpus too thin — nothing to measure", file=sys.stderr)
        return 1

    garch_state = load_calibrated_garch_state("R_75")
    print(f"[TQCHECK] calibrated R_75 garch: {'loaded' if garch_state else 'not_found (default priors)'}")

    rows = {}
    rows["band"] = compare_strategy("band", STRATEGY_BAND, VolBandStrategy,
                                    VolBandConfig, ticks, garch_state)
    rows["momentum"] = compare_strategy("momentum", 2, VolMomentumStrategy,
                                        VolMomentumConfig, ticks, garch_state)
    rows["fade"] = compare_strategy("fade", STRATEGY_MEANREVERSION,
                                     VolReversionStrategy, VolReversionConfig,
                                     ticks, garch_state)
    rows["sniper"] = compare_sniper(ticks)

    # --- four-leg head-to-head R-journal -------------------------------
    print("\n[TQCHECK] === four-leg head-to-head R-journal (real R_75 corpus, "
          f"{TF}s execution) ===")
    print("[TQCHECK]   "
          f"{'leg':<9} {'n':>4} {'hit':>6} {'avgR':>7} {'avgRR':>6} {'breakEven':>9}")
    for label, st in rows.items():
        print(f"[TQCHECK]   {label:<9} {st['n']:>4} {st['hit']*100:>5.1f}% "
              f"{st['avg_r']:>+7.3f} {st['avg_rr']:>6.2f} {st['break_even']*100:>8.1f}%")

    print(f"\n[TQCHECK] === {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
