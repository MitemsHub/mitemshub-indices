#!/usr/bin/env python3
"""Feed a real band backtest's OutcomeRecords through the Phase-8 analytics stack.

Same real-corpus mirror-harness pattern as phase6/phase7_real_corpus_check.py,
but for the Phase-8 Analytics/ folder (PerformanceAnalytics, ExpectancyEngine,
RegimeAnalytics):

  1. REPLICATION — replay the production band backtest loop (VolBandStrategy +
     RiskEngine + BreakevenTrailBroker) over the real R_75 tick corpus at the
     300s execution timeframe, capturing a per-trade OutcomeRecord (the MQL5
     struct shape: strategy/regime/direction/entry/stop/target/exit/risk/RR/
     return_r/MAE/MFE/r1-r3/hold_bars/exit_reason/won) plus a parallel
     confidence array (the Phase-5 depth-based setup quality the MQL5 band
     tester feeds the decision layer).
  2. PARITY — run the CLI `backtest-vol --mode band` on the same inputs and
     require trades / win_rate / expectancy_r to match the replication, so the
     capture is a REAL band backtest, not a toy.
  3. ANALYTICS — a one-to-one Python port of the Phase-8 MQL5 math
     (CPerformanceAnalytics::Metrics + the five splits, CExpectancyEngine::
     Verdict with the stage3_gate break-even floor, CRegimeAnalytics::*
     concentration/best/worst/alignment) run over those records, reporting the
     per-strategy / per-regime / per-confidence-bucket / per-exit-reason /
     per-direction expectancy breakdown.

Emits [PHASE8-ANALYTICS] machine lines for the verifier.

Run (from the repo root):
    python mql5/phase8_analytics_check.py [--csv data/backfill/R_75_ticks.csv]
        [--symbol R_75] [--timeframe 300] [--skip-cli]
"""

from __future__ import annotations

import argparse
import datetime
import math
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synthetic_trader.backtest.engine import load_ticks_csv  # noqa: E402
from synthetic_trader.backtest.vol_band import VolBandConfig, VolBandStrategy  # noqa: E402
from synthetic_trader.backtest.vol_reversion import (  # noqa: E402
    BreakevenTrailBroker,
    dedupe_ticks,
)
from synthetic_trader.config import PaperExecutionConfig, TraderConfig  # noqa: E402
from synthetic_trader.data.candles import MultiTimeframeCandleBuilder  # noqa: E402
from synthetic_trader.domain import Candle, Direction, TradeOutcome  # noqa: E402
from synthetic_trader.execution.paper import Position  # noqa: E402
from synthetic_trader.features.regimes import classify_regime  # noqa: E402
from synthetic_trader.models.garch_calibration import (  # noqa: E402
    load_calibrated_garch_state,
)
from synthetic_trader.risk.engine import RiskEngine  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# MQL5 enum mirrors (Core/Constants.mqh)
# ─────────────────────────────────────────────────────────────────────────────
REGIME_UNKNOWN, REGIME_TREND_UP, REGIME_TREND_DOWN, REGIME_RANGE, REGIME_COMPRESSION, \
    REGIME_EXPANSION, REGIME_HIGH_VOLATILITY, REGIME_LOW_VOLATILITY, REGIME_TRANSITION = range(9)

STRATEGY_NONE, STRATEGY_BAND = 0, 1

EXIT_NONE, EXIT_STOP_HIT, EXIT_TARGET_HIT, EXIT_TIME, EXIT_BREAKEVEN_TRAIL = range(5)

REGIME_NAMES = {
    REGIME_UNKNOWN: "UNKNOWN",
    REGIME_TREND_UP: "TREND_UP",
    REGIME_TREND_DOWN: "TREND_DOWN",
    REGIME_RANGE: "RANGE",
    REGIME_COMPRESSION: "COMPRESSION",
    REGIME_EXPANSION: "EXPANSION",
    REGIME_HIGH_VOLATILITY: "HIGH_VOLATILITY",
    REGIME_LOW_VOLATILITY: "LOW_VOLATILITY",
    REGIME_TRANSITION: "TRANSITION",
}
EXIT_NAMES = {
    EXIT_NONE: "NONE",
    EXIT_STOP_HIT: "STOP_HIT",
    EXIT_TARGET_HIT: "TARGET_HIT",
    EXIT_TIME: "TIME_EXIT",
    EXIT_BREAKEVEN_TRAIL: "BREAKEVEN_TRAIL",
}

# Decision/TradeQualityEngine.mqh + Analytics/ExpectancyEngine.mqh defaults.
GATE_HIT_RATE_FLOOR_DEFAULT = 0.50
BREAK_EVEN_MARGIN_DEFAULT = 0.05
BREAK_EVEN_FLOOR_MIN_DEFAULT = 0.10
BREAK_EVEN_FLOOR_MAX_DEFAULT = 0.60
# Phase-5 ConfidenceEngine: STRONG threshold for a formal setup (band always
# has entry/stop/target), port of PY_STRONG_WITH_SETUP.
PY_STRONG_WITH_SETUP = 0.52
# BandBackTests decision-layer inputs for the depth-based setup quality.
SETUP_QUALITY_MIN = 0.20
SETUP_QUALITY_MAX = 1.00
DEPTH_MAX = 3.00  # InpDepthMax: |z|/z_entry where setup quality saturates

ANALYTICS_MAX_STRATEGIES = 8
ANALYTICS_MAX_REGIMES = 12
ANALYTICS_MAX_EXIT_REASONS = 12

# ─────────────────────────────────────────────────────────────────────────────
# Phase-8 analytics port (one-to-one with the MQL5 .mqh implementations)
# ─────────────────────────────────────────────────────────────────────────────


def _py_regime(regime) -> int:
    """Map the Python domain Regime to the MQL5 ENUM_REGIME index.

    Note: ``str()`` on a ``class X(str, Enum)`` yields ``'X.MEMBER'`` (the
    enum repr), not the member value, so use ``.value`` explicitly."""
    key = regime.value if hasattr(regime, "value") else str(regime)
    return {
        "trend_up": REGIME_TREND_UP,
        "trend_down": REGIME_TREND_DOWN,
        "range": REGIME_RANGE,
        "volatile": REGIME_HIGH_VOLATILITY,
        "compression": REGIME_COMPRESSION,
        "unknown": REGIME_UNKNOWN,
    }.get(key, REGIME_UNKNOWN)


@dataclass
class BucketStats:
    """MQL5 Analytics/PerformanceAnalytics.mqh struct BucketStats."""

    n: int = 0
    wins: int = 0
    sum_r: float = 0.0

    def reset(self) -> None:
        self.n = 0
        self.wins = 0
        self.sum_r = 0.0

    def hit_rate(self) -> float:
        return self.wins / self.n if self.n > 0 else 0.0

    def avg_r(self) -> float:
        return self.sum_r / self.n if self.n > 0 else 0.0


@dataclass
class PerformanceSummary:
    """MQL5 Journal/PerformanceLogger.mqh struct PerformanceSummary (fields
    CPerformanceAnalytics::Metrics fills)."""

    trades: int = 0
    wins: int = 0
    losses: int = 0
    sum_r: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    win_rate: float = 0.0
    avg_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    max_consec_wins: int = 0
    max_consec_losses: int = 0
    avg_hold_bars: float = 0.0

    def reset(self) -> None:
        self.__init__()


@dataclass
class OutcomeRecord:
    """MQL5 Core/Constants.mqh struct OutcomeRecord."""

    strategy: int
    regime: int
    direction: int          # +1 long, -1 short
    entry: float
    stop_loss: float
    take_profit: float
    exit_price: float
    risk_distance: float
    reward_risk: float      # planned RR
    return_r: float
    mae_r: float
    mfe_r: float
    r1_reached: bool
    r2_reached: bool
    r3_reached: bool
    opened_at: float
    closed_at: float
    hold_bars: int
    exit_reason: int
    won: bool


class PerformanceAnalytics:
    """Port of CPerformanceAnalytics (Analytics/PerformanceAnalytics.mqh)."""

    @staticmethod
    def metrics(rows: list[OutcomeRecord]) -> PerformanceSummary:
        out = PerformanceSummary()
        cum = 0.0
        peak = 0.0
        streak = 0
        streak_sign = 0
        sum_hold = 0.0
        sum_win_r = 0.0
        sum_loss_r = 0.0
        for o in rows:
            out.trades += 1
            out.sum_r += o.return_r
            if o.won:
                out.wins += 1
                sum_win_r += o.return_r
                out.gross_profit += o.return_r
            else:
                out.losses += 1
                sum_loss_r += o.return_r
                out.gross_loss += -o.return_r
            sign = 1 if o.won else -1
            if sign == streak_sign:
                streak += 1
            else:
                if streak_sign > 0 and streak > out.max_consec_wins:
                    out.max_consec_wins = streak
                if streak_sign < 0 and streak > out.max_consec_losses:
                    out.max_consec_losses = streak
                streak = 1
                streak_sign = sign
            cum += o.return_r
            if cum > peak:
                peak = cum
            dd = peak - cum
            if dd > out.max_drawdown_r:
                out.max_drawdown_r = dd
            sum_hold += o.hold_bars
        if streak_sign > 0 and streak > out.max_consec_wins:
            out.max_consec_wins = streak
        if streak_sign < 0 and streak > out.max_consec_losses:
            out.max_consec_losses = streak
        if out.trades > 0:
            out.win_rate = out.wins / out.trades
            out.avg_r = out.sum_r / out.trades
            out.avg_win_r = sum_win_r / out.wins if out.wins > 0 else 0.0
            out.avg_loss_r = sum_loss_r / out.losses if out.losses > 0 else 0.0
            out.avg_hold_bars = sum_hold / out.trades
            out.profit_factor = out.gross_profit / out.gross_loss if out.gross_loss > 0.0 else 0.0
        return out

    @staticmethod
    def split_by_strategy(rows: list[OutcomeRecord]) -> list[BucketStats]:
        out = [BucketStats() for _ in range(ANALYTICS_MAX_STRATEGIES)]
        for o in rows:
            s = o.strategy
            if s < 0 or s >= ANALYTICS_MAX_STRATEGIES:
                s = 0
            out[s].n += 1
            out[s].sum_r += o.return_r
            if o.won:
                out[s].wins += 1
        return out

    @staticmethod
    def split_by_regime(rows: list[OutcomeRecord]) -> list[BucketStats]:
        out = [BucketStats() for _ in range(ANALYTICS_MAX_REGIMES)]
        for o in rows:
            r = o.regime
            if r < 0 or r >= ANALYTICS_MAX_REGIMES:
                r = 0
            out[r].n += 1
            out[r].sum_r += o.return_r
            if o.won:
                out[r].wins += 1
        return out

    @staticmethod
    def split_by_direction(rows: list[OutcomeRecord]) -> list[BucketStats]:
        out = [BucketStats(), BucketStats()]
        for o in rows:
            d = 0 if o.direction > 0 else 1
            out[d].n += 1
            out[d].sum_r += o.return_r
            if o.won:
                out[d].wins += 1
        return out

    @staticmethod
    def split_by_exit_reason(rows: list[OutcomeRecord]) -> list[BucketStats]:
        out = [BucketStats() for _ in range(ANALYTICS_MAX_EXIT_REASONS)]
        for o in rows:
            r = o.exit_reason
            if r < 0 or r >= ANALYTICS_MAX_EXIT_REASONS:
                r = EXIT_STOP_HIT
            out[r].n += 1
            out[r].sum_r += o.return_r
            if o.won:
                out[r].wins += 1
        return out

    @staticmethod
    def split_by_confidence(
        rows: list[OutcomeRecord], conf: list[float], strong_threshold: float
    ) -> list[BucketStats]:
        """out[0] = weak, out[1] = strong (MQL5 SplitByConfidence)."""
        out = [BucketStats(), BucketStats()]
        for o, c in zip(rows, conf):
            b = 1 if c >= strong_threshold else 0
            out[b].n += 1
            out[b].sum_r += o.return_r
            if o.won:
                out[b].wins += 1
        return out

    @staticmethod
    def print_metrics(label: str, m: PerformanceSummary) -> None:
        print(
            f"[ANALYTICS] {label}: {m.trades} trades ({m.wins}W/{m.losses}L) "
            f"hit={100.0 * m.win_rate:.1f}% exp={m.avg_r:+.3f}R sumR={m.sum_r:+.2f} "
            f"PF={m.profit_factor:.2f} maxDD={m.max_drawdown_r:.2f}R "
            f"avgWin={m.avg_win_r:+.2f}R avgLoss={m.avg_loss_r:+.2f}R "
            f"winStreak={m.max_consec_wins} lossStreak={m.max_consec_losses} "
            f"avgHold={m.avg_hold_bars:.1f}b"
        )

    @staticmethod
    def print_bucket(label: str, b: BucketStats) -> None:
        print(
            f"[ANALYTICS]   {label:<22s} n={b.n:4d} hit={100.0 * b.hit_rate():5.1f}% "
            f"exp={b.avg_r():+.3f}R sumR={b.sum_r:+.2f}R"
        )


class ExpectancyEngine:
    """Port of CExpectancyEngine (Analytics/ExpectancyEngine.mqh)."""

    @staticmethod
    def break_even_floor(reward_risk: float, margin: float) -> float:
        if reward_risk <= 0.0:
            return GATE_HIT_RATE_FLOOR_DEFAULT
        m = margin if margin >= 0.0 else BREAK_EVEN_MARGIN_DEFAULT
        raw = 1.0 / (1.0 + reward_risk) + m
        return max(BREAK_EVEN_FLOOR_MIN_DEFAULT, min(raw, BREAK_EVEN_FLOOR_MAX_DEFAULT))

    @staticmethod
    def verdict(
        rows: list[OutcomeRecord],
        min_samples: int,
        margin: float,
        strategy_filter: int | None = None,
    ) -> dict:
        n = 0
        sum_r = 0.0
        sum_rr = 0.0
        wins = 0
        for o in rows:
            if strategy_filter is not None and o.strategy != strategy_filter:
                continue
            n += 1
            sum_r += o.return_r
            sum_rr += o.reward_risk
            if o.won:
                wins += 1
        out = {
            "n": n,
            "hit_rate": 0.0,
            "avg_r": 0.0,
            "avg_rr": 0.0,
            "break_even_floor": GATE_HIT_RATE_FLOOR_DEFAULT,
            "beats_floor": False,
            "enough_samples": False,
        }
        if n == 0:
            return out
        out["hit_rate"] = wins / n
        out["avg_r"] = sum_r / n
        out["avg_rr"] = sum_rr / n
        out["break_even_floor"] = ExpectancyEngine.break_even_floor(out["avg_rr"], margin)
        out["enough_samples"] = n >= min_samples
        out["beats_floor"] = out["enough_samples"] and (out["hit_rate"] >= out["break_even_floor"])
        return out

    @staticmethod
    def verdict_string(v: dict) -> str:
        return (
            f"n={v['n']} hit={100.0 * v['hit_rate']:.1f}% floor={100.0 * v['break_even_floor']:.1f}% "
            f"-> {'BEATS' if v['beats_floor'] else 'does NOT beat'}"
        )


class RegimeAnalytics:
    """Port of CRegimeAnalytics (Analytics/RegimeAnalytics.mqh)."""

    @staticmethod
    def active_regimes(by_regime: list[BucketStats]) -> int:
        return sum(1 for b in by_regime if b.n > 0)

    @staticmethod
    def concentration(by_regime: list[BucketStats], total_trades: int) -> float:
        if total_trades <= 0:
            return 0.0
        top = max((b.n for b in by_regime), default=0)
        return top / total_trades

    @staticmethod
    def best_regime(by_regime: list[BucketStats]) -> int:
        best = -1
        best_exp = -1e9
        for r, b in enumerate(by_regime):
            if b.n == 0:
                continue
            e = b.avg_r()
            if e > best_exp:
                best_exp = e
                best = r
        return best

    @staticmethod
    def worst_regime(by_regime: list[BucketStats]) -> int:
        worst = -1
        worst_exp = 1e9
        for r, b in enumerate(by_regime):
            if b.n == 0:
                continue
            e = b.avg_r()
            if e < worst_exp:
                worst_exp = e
                worst = r
        return worst

    @staticmethod
    def alignment_share(rows: list[OutcomeRecord], required: int) -> float:
        if not rows:
            return 0.0
        aligned = sum(1 for o in rows if o.regime == required)
        return aligned / len(rows)

    @staticmethod
    def print_regime_table(by_regime: list[BucketStats]) -> None:
        print("[ANALYTICS] regime split:")
        for r, b in enumerate(by_regime):
            if b.n == 0:
                continue
            print(
                f"[ANALYTICS]   {REGIME_NAMES.get(r, str(r)):<18s} n={b.n:4d} "
                f"hit={100.0 * b.hit_rate():5.1f}% exp={b.avg_r():+.3f}R sumR={b.sum_r:+.2f}R"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Instrumented broker: exact BreakevenTrailBroker semantics + per-trade capture
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CapturedTrade:
    signal_entry: float
    signal_stop: float
    signal_target: float
    snapshot_regime: int
    depth: float
    setup_q: float
    raw_confidence: float


class CapturingTrailBroker(BreakevenTrailBroker):
    """Replicates BreakevenTrailBroker._maybe_close exactly, recording the exit
    reason (stop / breakeven-trail / target / time), MAE/MFE in R, and the
    entry-side metadata (depth, depth-based setup quality, raw confidence)."""

    def __init__(self, config: PaperExecutionConfig, breakeven_trail_frac: float = 0.0) -> None:
        super().__init__(config, breakeven_trail_frac=breakeven_trail_frac)
        self.captured: dict[str, CapturedTrade] = {}
        self.exit_reason: dict[str, int] = {}
        self.mae_r: dict[str, float] = {}
        self.mfe_r: dict[str, float] = {}
        # Final MAE/MFE stashed at close time (the live trackers are popped
        # immediately after closing, so the record builder reads these).
        self.final_mae_r: dict[str, float] = {}
        self.final_mfe_r: dict[str, float] = {}
        self.timeframe_sec: int = 300

    def register_entry(
        self,
        position: Position,
        depth: float,
        setup_q: float,
        raw_confidence: float,
    ) -> None:
        sig = position.signal
        self.captured[position.id] = CapturedTrade(
            signal_entry=sig.entry,
            signal_stop=sig.stop_loss,
            signal_target=sig.take_profit,
            snapshot_regime=_py_regime(sig.snapshot.regime),
            depth=depth,
            setup_q=setup_q,
            raw_confidence=raw_confidence,
        )
        self.mae_r[position.id] = 0.0
        self.mfe_r[position.id] = 0.0

    def _track_extremes(self, position: Position, candle: Candle) -> None:
        sig = position.signal
        risk = abs(sig.entry - sig.stop_loss)
        if risk <= 0.0:
            risk = sig.entry * 0.001
        if sig.direction is Direction.LONG:
            mfe = (candle.high - sig.entry) / risk
            mae = (sig.entry - candle.low) / risk
        else:
            mfe = (sig.entry - candle.low) / risk
            mae = (candle.high - sig.entry) / risk
        self.mfe_r[position.id] = max(self.mfe_r.get(position.id, 0.0), mfe)
        self.mae_r[position.id] = max(self.mae_r.get(position.id, 0.0), mae)

    def _maybe_close(self, position: Position, candle: Candle):
        # Exact copy of BreakevenTrailBroker._maybe_close (production code),
        # with the reason captured.  This is the whole reason for the subclass:
        # the base class does not expose which branch closed the trade.
        signal = position.signal
        risk_distance = abs(signal.entry - signal.stop_loss)
        if risk_distance <= 0.0:
            risk_distance = signal.entry * 0.001
        if signal.direction is Direction.LONG:
            mfe = (candle.high - signal.entry) / risk_distance
        else:
            mfe = (signal.entry - candle.low) / risk_distance
        self._mfe_r[position.id] = max(self._mfe_r.get(position.id, 0.0), mfe)
        self._track_extremes(position, candle)

        planned_rr = abs(signal.take_profit - signal.entry) / risk_distance
        trail_armed = (
            self.breakeven_trail_frac > 0.0
            and self._mfe_r[position.id] >= self.breakeven_trail_frac * planned_rr
        )
        effective_stop = signal.entry if trail_armed else signal.stop_loss

        expired = (
            candle.open_time + candle.timeframe_sec >= signal.snapshot.epoch + signal.horizon_sec
        )
        if signal.direction is Direction.LONG:
            stop_hit = candle.low <= effective_stop
            target_hit = candle.high >= signal.take_profit
        else:
            stop_hit = candle.high >= effective_stop
            target_hit = candle.low <= signal.take_profit

        if stop_hit and target_hit:
            reason = EXIT_BREAKEVEN_TRAIL if trail_armed else EXIT_STOP_HIT
            self.exit_reason[position.id] = reason
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, effective_stop),
                candle.open_time + candle.timeframe_sec,
            )
        if stop_hit:
            reason = EXIT_BREAKEVEN_TRAIL if trail_armed else EXIT_STOP_HIT
            self.exit_reason[position.id] = reason
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, effective_stop),
                candle.open_time + candle.timeframe_sec,
            )
        if target_hit:
            self.exit_reason[position.id] = EXIT_TARGET_HIT
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, signal.take_profit),
                candle.open_time + candle.timeframe_sec,
            )
        if expired:
            self.exit_reason[position.id] = EXIT_TIME
            return self._close_at_price(
                position,
                self._apply_exit_slippage(signal, candle.close),
                candle.open_time + candle.timeframe_sec,
            )
        return None

    def _close_at_price(self, position: Position, price: float, closed_at: float) -> TradeOutcome:
        self.final_mae_r[position.id] = self.mae_r.get(position.id, 0.0)
        self.final_mfe_r[position.id] = self.mfe_r.get(position.id, 0.0)
        outcome = super()._close_at_price(position, price, closed_at)
        self._mfe_r.pop(position.id, None)
        self.mae_r.pop(position.id, None)
        self.mfe_r.pop(position.id, None)
        return outcome


# ─────────────────────────────────────────────────────────────────────────────
# Band backtest replication (run_vol_regime_backtest loop + per-trade capture)
# ─────────────────────────────────────────────────────────────────────────────


def run_band_with_capture(
    ticks,
    symbol: str,
    timeframe_sec: int,
    config: TraderConfig,
    strategy: VolBandStrategy,
    broker: CapturingTrailBroker,
):
    """Replicates run_vol_regime_backtest's loop exactly, returning
    (outcomes, records, conf, signals, rejected, session_resets)."""
    builders = MultiTimeframeCandleBuilder(symbol, [timeframe_sec])
    risk_config = replace(config.risk, min_confidence=0.0, min_reward_risk=0.0)
    risk_engine = RiskEngine(risk_config)
    outcomes: list[TradeOutcome] = []
    records: list[OutcomeRecord] = []
    conf: list[float] = []
    signals = 0
    rejected = 0
    session_resets = 0
    candle_window: list[Candle] = []
    # As-of candle window at each ENTRY (live-path lookback discipline): the
    # live-path regime must be classified with the data available AT ENTRY,
    # not with the final window of the run.  Without this the harness passed
    # the final 500-candle window to _entry_regime, whose <= entry-time filter
    # returned an EMPTY window for every entry more than ~41h before run end
    # (len < 5 -> UNKNOWN for 24/28 entries — a harness bug, not the
    # classifier: classify_regime itself never emits UNKNOWN).
    entry_windows: dict[str, list] = {}

    for tick in sorted(ticks, key=lambda item: item.epoch):
        if risk_engine.sync_session_day(int(tick.epoch // 86400)):
            session_resets += 1
        closed = builders.update(tick)
        for tf, candle in closed.items():
            if tf != timeframe_sec:
                continue
            candle_window.append(candle)
            if len(candle_window) > 2000:
                candle_window.pop(0)
            for outcome in broker.on_candle(candle):
                outcomes.append(outcome)
                records.append(_to_record(outcome, broker, timeframe_sec, None))
                conf.append(0.0)  # patched below via position lookup
                risk_engine.register_outcome(outcome)

            signal = strategy.on_candle(candle)
            if signal is None:
                continue
            signals += 1
            risk_decision = risk_engine.evaluate(signal)
            if not risk_decision.approved or risk_decision.intent is None:
                rejected += 1
                continue
            position = broker.submit(risk_decision.intent)
            risk_engine.register_open()
            # Snapshot the as-of candle window for this entry's live-path
            # regime (copy — the rolling window keeps mutating).
            entry_windows[position.id] = list(candle_window)
            # Entry-side metadata: depth = |z|/z_entry, Phase-5 setup quality.
            z_dev = float(signal.snapshot.features.get("vol_z_dev", 0.0))
            z_entry = strategy.config.z_entry
            depth = abs(z_dev) / z_entry if z_entry > 0.0 else 1.0
            setup_q = SETUP_QUALITY_MIN + (SETUP_QUALITY_MAX - SETUP_QUALITY_MIN) * max(
                0.0, min(1.0, (depth - 1.0) / max(0.01, DEPTH_MAX - 1.0))
            )
            broker.register_entry(position, depth, setup_q, signal.confidence)

    flushed = builders.flush()
    final_primary = flushed.get(timeframe_sec)
    if final_primary is not None:
        for outcome in broker.on_candle(final_primary):
            outcomes.append(outcome)
            records.append(_to_record(outcome, broker, timeframe_sec, None))
            conf.append(0.0)
            risk_engine.register_outcome(outcome)
        for outcome in broker.close_all(final_primary):
            outcomes.append(outcome)
            records.append(_to_record(outcome, broker, timeframe_sec, None))
            conf.append(0.0)
            risk_engine.register_outcome(outcome)

    # Patch confidence from the captured per-position metadata, and attach the
    # live-path entry regime (classify_regime on the entry candle's window).
    for i, outcome in enumerate(outcomes):
        cap = broker.captured.get(outcome.position_id)
        if cap is not None:
            conf[i] = cap.setup_q
            records[i].regime = cap.snapshot_regime
            records[i].live_regime = _entry_regime(
                entry_windows.get(outcome.position_id, []),
                outcome.opened_at,
                timeframe_sec,
            )

    return outcomes, records, conf, signals, rejected, session_resets


def _to_record(
    outcome: TradeOutcome,
    broker: CapturingTrailBroker,
    timeframe_sec: int,
    _unused,
) -> OutcomeRecord:
    cap = broker.captured.get(outcome.position_id)
    entry = cap.signal_entry if cap else outcome.entry
    stop = cap.signal_stop if cap else outcome.entry * (1.0 + (1 if outcome.direction is Direction.SHORT else -1) * 0.001)
    target = cap.signal_target if cap else outcome.entry
    risk = abs(entry - stop)
    if risk <= 0.0:
        risk = entry * 0.001
    planned_rr = abs(target - entry) / risk
    hold_bars = int(round((outcome.closed_at - outcome.opened_at) / timeframe_sec))
    mfe = broker.final_mfe_r.get(outcome.position_id, 0.0)
    mae = broker.final_mae_r.get(outcome.position_id, 0.0)
    rec = OutcomeRecord(
        strategy=STRATEGY_BAND,
        regime=REGIME_HIGH_VOLATILITY,
        direction=1 if outcome.direction is Direction.LONG else -1,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        exit_price=outcome.exit,
        risk_distance=risk,
        reward_risk=planned_rr,
        return_r=outcome.return_r,
        mae_r=mae,
        mfe_r=mfe,
        r1_reached=mfe >= 1.0,
        r2_reached=mfe >= 2.0,
        r3_reached=mfe >= 3.0,
        opened_at=outcome.opened_at,
        closed_at=outcome.closed_at,
        hold_bars=max(1, hold_bars),
        exit_reason=broker.exit_reason.get(outcome.position_id, EXIT_NONE),
        won=outcome.won,
    )
    rec.live_regime = REGIME_UNKNOWN  # patched after capture in the runner
    return rec


# Note: OutcomeRecord gains a live_regime field for the supplementary axis —
# the MQL5 struct has no such field; this is harness-only metadata.
OutcomeRecord.live_regime = 0  # type: ignore[attr-defined]

_entry_regime_cache: dict[tuple[int, int], int] = {}


def _entry_regime(
    candle_window: list[Candle],
    opened_at: float,
    timeframe_sec: int,
) -> int:
    """classify_regime (live-path regime source) over the closed-candle window
    ending at the trade's entry candle.  ``candle_window`` MUST be the as-of
    window captured at entry (not the final window of the run) — see
    run_band_with_capture.  Deterministic + cached per entry bar."""
    key = (int(opened_at), timeframe_sec)
    if key in _entry_regime_cache:
        return _entry_regime_cache[key]
    # Live-path convention: classify over the closed-candle window as of the
    # signal bar's close (the entry candle's close == opened_at).
    window = [c for c in candle_window if c.open_time + c.timeframe_sec <= int(opened_at)]
    if len(window) < 5:
        _entry_regime_cache[key] = REGIME_UNKNOWN
        return REGIME_UNKNOWN
    regime, _feat, _notes = classify_regime(window[-200:])
    _entry_regime_cache[key] = _py_regime(regime)
    return _entry_regime_cache[key]


# ─────────────────────────────────────────────────────────────────────────────
# CLI parity (the "real band backtest" reference)
# ─────────────────────────────────────────────────────────────────────────────


def run_cli_reference(csv_path: str, symbol: str, timeframe: int) -> dict | None:
    cmd = [
        sys.executable,
        "-m",
        "synthetic_trader.cli",
        "backtest-vol",
        "--csv",
        csv_path,
        "--symbol",
        symbol,
        "--timeframe",
        str(timeframe),
        "--mode",
        "band",
        # Pin the realistic-cost basis explicitly (the Python-side broker
        # above hardcodes 0.05/0.05/0.10; the CLI reference must measure on
        # the same model regardless of the CLI's default args — audit
        # 2026-08-17).
        "--entry-slippage-ticks",
        "0.05",
        "--exit-slippage-ticks",
        "0.05",
        "--execution-penalty",
        "0.10",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=1500, cwd=str(ROOT)
    )
    out = proc.stdout
    section = out.split("=== vol-band (primary) ===")
    if len(section) < 2:
        print(f"[PARITY] CLI run produced no band primary section (rc={proc.returncode})")
        return None
    ref: dict = {}
    for line in section[1].splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        try:
            if v.endswith("%"):
                ref[k] = float(v[:-1]) / 100.0
            else:
                ref[k] = float(v)
        except ValueError:
            ref[k] = v
    return ref


# ─────────────────────────────────────────────────────────────────────────────


def _fmt_hms(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="data/backfill/R_75_ticks.csv")
    ap.add_argument("--symbol", default="R_75")
    ap.add_argument("--timeframe", type=int, default=300)
    ap.add_argument("--skip-cli", action="store_true", help="skip the CLI parity run")
    ap.add_argument("--min-samples", type=int, default=10, help="floor-gate min samples")
    ap.add_argument("--margin", type=float, default=0.05, help="break-even floor margin")
    args = ap.parse_args()

    csv_path = str(ROOT / args.csv)
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=args.symbol))
    print(f"[PHASE8-ANALYTICS] corpus={args.csv} ticks={len(ticks)} span="
          f"{_fmt_hms(ticks[0].epoch)} -> {_fmt_hms(ticks[-1].epoch)} tf={args.timeframe}s")

    paper = PaperExecutionConfig(
        entry_slippage_ticks=0.05,
        exit_slippage_ticks=0.05,
        execution_penalty_per_trade=0.10,
    )
    config = replace(TraderConfig.default(), paper=paper)
    band_config = VolBandConfig(
        z_entry=1.0,
        vol_extended_ratio=1.3,
        min_revert_signal=0.02,
        stop_sigma_mult=0.20,
        target_sigma_mult=0.80,
        max_hold_sec=3600,
        breakeven_trail_frac=0.3,
    )
    garch_state = load_calibrated_garch_state(args.symbol)
    print(f"calibrated_garch={'loaded' if garch_state is not None else 'not_found'}")

    strategy = VolBandStrategy(
        args.symbol,
        args.timeframe,
        config=band_config,
        garch_state=garch_state,
    )
    broker = CapturingTrailBroker(paper, breakeven_trail_frac=band_config.breakeven_trail_frac)
    broker.timeframe_sec = args.timeframe

    outcomes, records, conf, signals, rejected, session_resets = run_band_with_capture(
        ticks, args.symbol, args.timeframe, config, strategy, broker
    )

    from synthetic_trader.journal.trade_journal import metrics_from_outcomes

    m = metrics_from_outcomes(outcomes)
    print(f"[PHASE8-ANALYTICS] replication: trades={m.trades} win_rate={m.win_rate:.2%} "
          f"expectancy_r={m.expectancy_r:.3f} signals={signals} rejected={rejected} "
          f"session_resets={session_resets}")

    # ── Parity with the CLI (the real backtest) ──────────────────────────
    parity_ok = True
    if not args.skip_cli:
        ref = run_cli_reference(args.csv, args.symbol, args.timeframe)
        if ref is not None:
            # The CLI prints win_rate at 2 decimals and expectancy_r at 3, so
            # tolerance is the printed precision, not machine epsilon.
            checks = [
                ("trades", float(m.trades), 1e-6),
                ("win_rate", m.win_rate, 5e-4),
                ("expectancy_r", m.expectancy_r, 5e-4),
            ]
            for k, got, tol in checks:
                want = ref.get(k)
                ok = want is not None and abs(want - got) < tol
                parity_ok = parity_ok and ok
                print(f"[PARITY] {k}: replication={got:.6f} cli={want} {'OK' if ok else 'MISMATCH'}")
            print(f"[PARITY] verdict={'MATCH' if parity_ok else 'MISMATCH'}")
        else:
            parity_ok = False
    if not parity_ok:
        print("[PHASE8-ANALYTICS] FAIL — replication does not match the CLI band backtest")
        return 1

    # ── Phase-8 analytics over the OutcomeRecords ────────────────────────
    rows = records
    pa = PerformanceAnalytics
    summary = pa.metrics(rows)
    print()
    pa.print_metrics("band (all)", summary)

    print()
    print("[ANALYTICS] strategy split:")
    for s, b in enumerate(pa.split_by_strategy(rows)):
        if b.n == 0:
            continue
        pa.print_bucket("BAND_GEOMETRY" if s == STRATEGY_BAND else f"STRATEGY_{s}", b)

    by_regime = pa.split_by_regime(rows)
    RegimeAnalytics.print_regime_table(by_regime)
    ra = RegimeAnalytics
    active = ra.active_regimes(by_regime)
    conc = ra.concentration(by_regime, len(rows))
    best = ra.best_regime(by_regime)
    worst = ra.worst_regime(by_regime)
    print(f"[ANALYTICS] regime concentration: {100.0 * conc:.1f}% in the top regime "
          f"({REGIME_NAMES.get(best, '?')} best {by_regime[best].avg_r():+.3f}R | "
          f"{REGIME_NAMES.get(worst, '?')} worst {by_regime[worst].avg_r():+.3f}R), "
          f"{active} active regimes")

    print()
    print("[ANALYTICS] direction split:")
    for d, b in enumerate(pa.split_by_direction(rows)):
        if b.n == 0:
            continue
        pa.print_bucket("LONG" if d == 0 else "SHORT", b)

    print()
    print("[ANALYTICS] exit-reason split:")
    by_exit = pa.split_by_exit_reason(rows)
    for r, b in enumerate(by_exit):
        if b.n == 0:
            continue
        pa.print_bucket(EXIT_NAMES.get(r, str(r)), b)

    # ── ExpectancyEngine verdict (stage3_gate floor) per strategy ────────
    print()
    print("[ANALYTICS] expectancy verdict (min_samples=%d, margin=%.2f):"
          % (args.min_samples, args.margin))
    v = ExpectancyEngine.verdict(rows, args.min_samples, args.margin)
    print(f"[ANALYTICS]   band all: avg_rr={v['avg_rr']:.2f} " + ExpectancyEngine.verdict_string(v))

    # ── Confidence buckets ───────────────────────────────────────────────
    print()
    print("[ANALYTICS] confidence split (Phase-5 depth-based setup quality, "
          f"strong >= {PY_STRONG_WITH_SETUP}):")
    by_conf = pa.split_by_confidence(rows, conf, PY_STRONG_WITH_SETUP)
    pa.print_bucket("WEAK (marginal fade)", by_conf[0])
    pa.print_bucket("STRONG (deep extension)", by_conf[1])
    # Raw-signal confidence (the Python band's own Confidence()) for contrast.
    raw_conf = [cap.raw_confidence for cap in broker.captured.values()]
    if len(raw_conf) == len(rows):
        by_raw = pa.split_by_confidence(rows, raw_conf, PY_STRONG_WITH_SETUP)
        print("[ANALYTICS]   (raw signal confidence >= 0.52: "
              f"weak n={by_raw[0].n} strong n={by_raw[1].n} — "
              f"{'discriminating' if by_raw[1].n != len(rows) else 'uniformly STRONG (the depth fix is why)'})")

    # ── Supplementary live-path regime axis ──────────────────────────────
    print()
    print("[ANALYTICS] live-path regime at entry (classify_regime window):")
    live_by_regime: list[BucketStats] = [BucketStats() for _ in range(ANALYTICS_MAX_REGIMES)]
    for o in rows:
        r = o.live_regime
        live_by_regime[r].n += 1
        live_by_regime[r].sum_r += o.return_r
        if o.won:
            live_by_regime[r].wins += 1
    for r, b in enumerate(live_by_regime):
        if b.n == 0:
            continue
        pa.print_bucket(REGIME_NAMES.get(r, str(r)), b)

    # ── Alignment: band claims HIGH_VOLATILITY (snapshot) ────────────────
    align = ra.alignment_share(rows, REGIME_HIGH_VOLATILITY)
    print(f"[ANALYTICS] band regime alignment (recorded HIGH_VOLATILITY share): {100.0 * align:.1f}%")

    # ── Machine lines for the verifier ───────────────────────────────────
    beats = "yes" if v["beats_floor"] else "no"  # vocabulary is the gate's contract: beats=(yes|no)
    print(f"[PHASE8-ANALYTICS] band n={len(rows)} hit={100.0 * summary.win_rate:.1f}% "
          f"exp={summary.avg_r:+.3f}R sumR={summary.sum_r:+.2f}R maxDD={summary.max_drawdown_r:.2f}R "
          f"floor={100.0 * v['break_even_floor']:.1f}% beats={beats}")
    print(f"[PHASE8-ANALYTICS] buckets strong n={by_conf[1].n} exp={by_conf[1].avg_r():+.3f}R "
          f"hit={100.0 * by_conf[1].hit_rate():.1f}% | weak n={by_conf[0].n} "
          f"exp={by_conf[0].avg_r():+.3f}R hit={100.0 * by_conf[0].hit_rate():.1f}%")
    print(f"[PHASE8-ANALYTICS] regimes conc={100.0 * conc:.1f}% best={REGIME_NAMES.get(best, '?')} "
          f"worst={REGIME_NAMES.get(worst, '?')} align_highvol={100.0 * align:.1f}%")
    print(f"[PHASE8-ANALYTICS] exit stop n={by_exit[EXIT_STOP_HIT].n} "
          f"trail n={by_exit[EXIT_BREAKEVEN_TRAIL].n} target n={by_exit[EXIT_TARGET_HIT].n} "
          f"time n={by_exit[EXIT_TIME].n}")

    print()
    print("[PHASE8-ANALYTICS] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
