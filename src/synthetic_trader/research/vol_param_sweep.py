"""Systematic parameter sweep for the vol-targeting backtest modes.

The head-to-head (§16, §23) verdicts are limited by tiny trade counts — 2–14
trades over 7 days at the default gates.  This module runs a **systematic
grid sweep** over the strategy knobs (``z_entry``, vol-ratio gate, stop /
target sigma multipliers) for both the fade (:mod:`vol_reversion`) and the
momentum (:mod:`vol_momentum`) modes, and ranks every config by expectancy
subject to a minimum-trades floor — so the operator can find the config
that is both profitable AND has enough samples to mean something.

Design:

- **In-process and fast.**  Every config is a fresh strategy instance fed
  through the same shared ``run_vol_regime_backtest`` pipeline (PaperBroker
  + RiskEngine), but all inside one Python process — no CLI subprocess
  overhead.  The default grid (~1,400 configs with the swept
  ``max_hold_bars`` dimension, §34) completes in roughly 1.5–7 minutes per
  symbol/timeframe depending on corpus size.
- **Exhaustive but prunable.**  ``run_sweep`` accepts the grid bounds and
  builds the Cartesian product; ``--min-trades`` drops thin configs from the
  report (a config with 2 trades can't support a profitability claim).
- **Deterministic.**  Same ticks, same seeds → identical results every run.

Usage (via the CLI)::

    python -m synthetic_trader.cli sweep-vol --csv data/backfill/R_75_ticks.csv \
        --symbol R_75 --timeframe 60 --min-trades 8
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from synthetic_trader.backtest.engine import BacktestResult, load_ticks_csv
from synthetic_trader.backtest.vol_momentum import (
    VolMomentumConfig,
    run_vol_momentum_backtest,
)
from synthetic_trader.backtest.vol_reversion import (
    VolReversionConfig,
    dedupe_ticks,
    run_vol_reversion_backtest,
)
from synthetic_trader.config import PaperExecutionConfig, TraderConfig

# ── Grid bounds ─────────────────────────────────────────────────────────
# (start, stop, step) per knob — tune these to widen/narrow the sweep.
FADE_Z_ENTRY = (1.25, 2.0, 0.25)       # 1.25, 1.5, 1.75, 2.0
FADE_VOL_RATIO = (1.3, 1.8, 0.25)      # 1.3, 1.55, 1.8
FADE_STOP_MULT = (2.0, 3.0, 0.5)       # 2.0, 2.5, 3.0
FADE_TARGET_MULT = (1.0, 2.0, 0.5)     # 1.0, 1.5, 2.0

MOM_Z_ENTRY = (0.5, 1.0, 0.25)         # 0.5, 0.75, 1.0
MOM_VOL_RATIO = (1.15, 1.5, 0.175)     # 1.15, 1.325, 1.5
MOM_ABS_MULT = (1.5, 2.5, 0.5)         # 1.5, 2.0, 2.5
MOM_STOP_MULT = (1.0, 2.0, 0.5)        # 1.0, 1.5, 2.0
MOM_TARGET_MULT = (2.0, 4.0, 1.0)      # 2.0, 3.0, 4.0
# Time-stop geometry (primary candles).  Swept since the re-tune (§24→§34):
# the default 30 bars at 300s only gives a momentum winner 2.5h to run.
# The §34 re-tune found the winning region at holds 110–120, so the default
# range must reach 120 or a plain sweep would never surface it.
MOM_HOLD_BARS = (15, 120, 15)          # 15, 30, ..., 120

# Other knobs held at their tuned defaults (see VolReversionConfig /
# VolMomentumConfig docstrings).
FIXED_FADE = {"min_revert_signal": 0.02, "max_hold_bars": 30}
FIXED_MOM = {"drift_cooldown_bars": 30}


def _arange(start: float, stop: float, step: float) -> list[float]:
    """Inclusive range for floats (avoids 0.3 float-accumulation artifacts)."""
    out: list[float] = []
    v = start
    while v <= stop + 1e-9:
        out.append(round(v, 6))
        v += step
    return out


def fade_grid() -> list[VolReversionConfig]:
    """Cartesian product of the fade knob ranges."""
    return [
        VolReversionConfig(
            z_entry=z,
            vol_extended_ratio=vr,
            stop_sigma_mult=s,
            target_sigma_mult=t,
            **FIXED_FADE,
        )
        for z in _arange(*FADE_Z_ENTRY)
        for vr in _arange(*FADE_VOL_RATIO)
        for s in _arange(*FADE_STOP_MULT)
        for t in _arange(*FADE_TARGET_MULT)
    ]


def momentum_grid(
    gate: str,
    *,
    z_entries: tuple[float, float, float] | None = None,
    stops: tuple[float, float, float] | None = None,
    targets: tuple[float, float, float] | None = None,
    holds: tuple[float, float, float] | None = None,
    ref_periods: tuple[float, float, float] | None = None,
    gate_ranges: dict[str, tuple[float, float, float]] | None = None,
) -> list[VolMomentumConfig]:
    """Cartesian product of the momentum knob ranges for one gate.

    Every knob range is overridable for a focused re-tune (the defaults
    mirror the module-level grid constants).  ``gate_ranges`` supplies the
    gate-specific knob (``vol_min_ratio`` for ``ratio``, ``abs_sigma_mult``
    for ``absolute``) — anything not given falls back to the constants.
    ``ref_periods`` sweeps ``abs_ref_period`` (the absolute gate's slow
    long-run-sigma baseline EMA period, default 600) — mapping the region
    around the +0.303R cell in both gate dimensions (§35).
    """
    if gate == "ratio":
        gate_values: list[dict[str, float]] = [
            {"vol_min_ratio": vr}
            for vr in _arange(*(gate_ranges or {}).get("vol_min_ratio", MOM_VOL_RATIO))
        ]
    elif gate == "absolute":
        gate_values = [
            {"abs_sigma_mult": a}
            for a in _arange(*(gate_ranges or {}).get("abs_sigma_mult", MOM_ABS_MULT))
        ]
    else:
        raise ValueError(f"unknown momentum gate {gate!r}")

    z_rng = z_entries or MOM_Z_ENTRY
    s_rng = stops or MOM_STOP_MULT
    t_rng = targets or MOM_TARGET_MULT
    h_rng = holds or MOM_HOLD_BARS
    # Default pins abs_ref_period at 600 — MUST mirror the
    # VolMomentumConfig.abs_ref_period default or the sweep drifts silently.
    rp_rng = ref_periods or (600.0, 600.0, 600.0)

    out: list[VolMomentumConfig] = []
    for gate_kw in gate_values:
        for z in _arange(*z_rng):
            for s in _arange(*s_rng):
                for t in _arange(*t_rng):
                    for h in _arange(*h_rng):
                        for rp in _arange(*rp_rng):
                            out.append(
                                VolMomentumConfig(
                                    z_entry=z,
                                    mom_gate=gate,
                                    stop_sigma_mult=s,
                                    target_sigma_mult=t,
                                    max_hold_bars=int(h),
                                    abs_ref_period=int(rp),
                                    **gate_kw,
                                    **FIXED_MOM,
                                )
                            )
    return out


@dataclass(frozen=True)
class SweepResult:
    """One grid point: the config, its backtest metrics, and a label."""

    label: str
    config: dict[str, Any]
    trades: int
    signals: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    net_pnl: float
    final_equity: float
    model_version: str

    @classmethod
    def from_backtest(
        cls, label: str, config: object, result: BacktestResult
    ) -> "SweepResult":
        cfg = asdict(config) if hasattr(config, "__dataclass_fields__") else vars(config)
        return cls(
            label=label,
            config=cfg,
            trades=result.metrics.trades,
            signals=result.signals,
            win_rate=result.metrics.win_rate,
            profit_factor=result.metrics.profit_factor,
            expectancy_r=result.metrics.expectancy_r,
            net_pnl=result.metrics.net_pnl,
            final_equity=result.final_equity,
            model_version=result.model_version,
        )


def run_sweep(
    ticks: list,
    symbol: str,
    timeframe_sec: int,
    *,
    gates: tuple[str, ...] = ("ratio", "absolute"),
    strategies: tuple[str, ...] = ("fade", "momentum"),
    momentum_ranges: dict[str, Any] | None = None,
    paper: PaperExecutionConfig | None = None,
    garch_state=None,
) -> list[SweepResult]:
    """Run the full grid and return every config's metrics, ranked by
    expectancy.  The ``min_trades`` floor is applied by
    :func:`summarize_sweep`, which builds the report.

    ``strategies`` restricts which families run (``fade`` / ``momentum``) —
    pass only ``("momentum",)`` for a focused momentum re-tune without the
    fade grid.  ``momentum_ranges`` forwards overridable knob ranges to
    :func:`momentum_grid` (gate-specific ranges under the ``"gate"`` key).
    """
    for gate in gates:
        if gate not in ("ratio", "absolute"):
            raise ValueError(
                f"sweep supports momentum gates 'ratio' and 'absolute'; got {gate!r}"
            )
    for strat in strategies:
        if strat not in ("fade", "momentum"):
            raise ValueError(
                f"sweep supports strategies 'fade' and 'momentum'; got {strat!r}"
            )
    config = replace(TraderConfig.default(), paper=paper or PaperExecutionConfig())
    rows: list[SweepResult] = []

    if "fade" in strategies:
        for fc in fade_grid():
            res = run_vol_reversion_backtest(
                ticks,
                symbol=symbol,
                timeframe_sec=timeframe_sec,
                config=config,
                strategy_config=fc,
                garch_state=garch_state,
                paper=paper,
            )
            rows.append(SweepResult.from_backtest("fade", fc, res))

    if "momentum" in strategies:
        for gate in gates:
            for mc in momentum_grid(gate, **momentum_ranges or {}):
                res = run_vol_momentum_backtest(
                    ticks,
                    symbol=symbol,
                    timeframe_sec=timeframe_sec,
                    config=config,
                    strategy_config=mc,
                    garch_state=garch_state,
                    paper=paper,
                )
                rows.append(SweepResult.from_backtest(f"momentum:{gate}", mc, res))

    rows.sort(key=lambda r: r.expectancy_r, reverse=True)
    return rows


def summarize_sweep(
    rows: list[SweepResult],
    *,
    min_trades: int = 1,
    top_n: int = 10,
) -> dict[str, Any]:
    """Build a JSON-serializable report: top configs + grid stats."""
    eligible = [r for r in rows if r.trades >= min_trades]
    top = eligible[:top_n]
    return {
        "configs_tested": len(rows),
        "configs_with_min_trades": len(eligible),
        "min_trades_floor": min_trades,
        "top": [
            {
                "label": r.label,
                "trades": r.trades,
                "signals": r.signals,
                "win_rate": r.win_rate,
                "profit_factor": r.profit_factor,
                "expectancy_r": r.expectancy_r,
                "net_pnl": r.net_pnl,
                "final_equity": r.final_equity,
                "model_version": r.model_version,
                "config": r.config,
            }
            for r in top
        ],
    }


def print_sweep_report(report: dict[str, Any], symbol: str, timeframe_sec: int) -> None:
    print(f"== sweep {symbol} @ {timeframe_sec}s ==")
    print(
        f"configs={report['configs_tested']} "
        f"with>={report['min_trades_floor']} trades={report['configs_with_min_trades']}"
    )
    print(f"{'label':<14} {'trades':>6} {'WR':>6} {'PF':>6} {'ExpR':>7} {'net':>8}")
    for r in report["top"]:
        print(
            f"{r['label']:<14} {r['trades']:>6} {r['win_rate']:>5.0%} "
            f"{r['profit_factor']:>6.2f} {r['expectancy_r']:>7.3f} {r['net_pnl']:>8.2f}"
        )
    best = report["top"][0] if report["top"] else None
    if best is not None:
        print(f"\nbest: {best['label']} expectancy={best['expectancy_r']:.3f} "
              f"trades={best['trades']} WR={best['win_rate']:.0%}")
        if best["trades"] < 20:
            print(
                f"  caveat: only {best['trades']} trades — not statistically "
                "meaningful yet; re-run after the corpus compounds"
            )
        KEYS = (
            "z_entry", "vol_extended_ratio", "vol_min_ratio", "abs_sigma_mult",
            "abs_ref_period", "mom_gate", "stop_sigma_mult", "target_sigma_mult",
            "max_hold_bars", "min_revert_signal",
        )
        shown = {k: v for k, v in best["config"].items() if k in KEYS}
        print(f"  config={json.dumps(shown)}")


def run_sweep_for_csv(
    csv_path: str | Path,
    symbol: str,
    timeframe_sec: int,
    *,
    min_trades: int = 1,
    top_n: int = 10,
    gates: tuple[str, ...] = ("ratio", "absolute"),
    strategies: tuple[str, ...] = ("fade", "momentum"),
    momentum_ranges: dict[str, Any] | None = None,
    artifact_output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load ticks, run the sweep, optionally persist the report as JSON."""
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    paper = PaperExecutionConfig(
        entry_slippage_ticks=1.0,
        exit_slippage_ticks=1.0,
        execution_penalty_per_trade=0.5,
    )
    from synthetic_trader.models.garch_calibration import load_calibrated_garch_state

    garch_state = load_calibrated_garch_state(symbol)
    t0 = time.time()
    rows = run_sweep(
        ticks,
        symbol=symbol,
        timeframe_sec=timeframe_sec,
        gates=gates,
        strategies=strategies,
        momentum_ranges=momentum_ranges,
        paper=paper,
        garch_state=garch_state,
    )
    report = summarize_sweep(rows, min_trades=min_trades, top_n=top_n)
    report["elapsed_sec"] = round(time.time() - t0, 1)
    if artifact_output_path is not None:
        out = Path(artifact_output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["artifact"] = str(out)
    return report
