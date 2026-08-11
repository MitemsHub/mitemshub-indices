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
from synthetic_trader.backtest.vol_band import (
    VolBandConfig,
    run_vol_band_backtest,
)
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

# Band-geometry (vol-band) grid — the §36 live default geometry.  The
# verified cell (z 1.0 / vol 1.3 / stop 0.35σ / target 1.0σ / 2h hold) only
# traded 21 times on the 9.5-day corpus, so the grid sweeps the entry bar
# DOWN (z_entry 0.5-1.5, vol ratio 1.15-1.6) to find cells that trade more
# while keeping the geometry knobs that set the RR (stop/target σ mults) and
# the hold short enough to resolve calls fast.
BAND_Z_ENTRY = (0.25, 1.5, 0.25)       # 0.25, 0.5, 0.75, 1.0, 1.25, 1.5
# Vol gate range starts at 0.75 so the sweep can find the relaxed-gate cells
# (§47: gate 1.05-1.1 with the breakeven trail keeps +0.99R at ~4 trades/day
# while the old 1.15 floor skipped that entire region; §50 pushes below 1.0
# so the calm 0.86-vol regime is measurable at all).  Endpoint is 1.55, not
# 1.6: with a 0.1 step from a 0.75 base the sequence lands on 1.55 then 1.65,
# so a 1.6 endpoint would never be sampled (off-by-one in _arange's tolerance).
BAND_VOL_RATIO = (0.75, 1.55, 0.1)     # 0.75, 0.85, ..., 1.55
BAND_STOP_MULT = (0.2, 0.5, 0.1)       # 0.2, 0.3, 0.4, 0.5
BAND_TARGET_MULT = (0.6, 1.4, 0.2)     # 0.6, 0.8, 1.0, 1.2, 1.4
BAND_HOLD_SEC = (3600, 10800, 3600)    # 1h, 2h, 3h

# Other knobs held at their tuned defaults (see VolReversionConfig /
# VolMomentumConfig docstrings).
FIXED_FADE = {"min_revert_signal": 0.02, "max_hold_bars": 30}
FIXED_MOM = {"drift_cooldown_bars": 30}
FIXED_BAND = {"breakeven_trail_frac": 0.3}


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


def band_grid(
    *,
    z_entries: tuple[float, float, float] | None = None,
    vol_ratios: tuple[float, float, float] | None = None,
    stops: tuple[float, float, float] | None = None,
    targets: tuple[float, float, float] | None = None,
    holds: tuple[float, float, float] | None = None,
) -> list[VolBandConfig]:
    """Cartesian product of the vol-band knob ranges (all overridable).

    ``holds`` is in **seconds** (max_hold_sec), unlike the momentum grid's
    bar-based holds — the band hold is a wall-clock horizon for the
    zero-drawdown levels.
    """
    z_rng = z_entries or BAND_Z_ENTRY
    vr_rng = vol_ratios or BAND_VOL_RATIO
    s_rng = stops or BAND_STOP_MULT
    t_rng = targets or BAND_TARGET_MULT
    h_rng = holds or BAND_HOLD_SEC
    return [
        VolBandConfig(
            z_entry=z,
            vol_extended_ratio=vr,
            stop_sigma_mult=s,
            target_sigma_mult=t,
            max_hold_sec=int(h),
            **FIXED_BAND,
        )
        for z in _arange(*z_rng)
        for vr in _arange(*vr_rng)
        for s in _arange(*s_rng)
        for t in _arange(*t_rng)
        for h in _arange(*h_rng)
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
    band_ranges: dict[str, Any] | None = None,
    paper: PaperExecutionConfig | None = None,
    garch_state=None,
    max_daily_loss_fraction: float | None = None,
    max_consecutive_losses: int | None = None,
) -> list[SweepResult]:
    """Run the full grid and return every config's metrics, ranked by
    expectancy.  The ``min_trades`` floor is applied by
    :func:`summarize_sweep`, which builds the report.

    ``strategies`` restricts which families run (``fade`` / ``momentum`` /
    ``band``) — pass only ``("momentum",)`` for a focused momentum re-tune
    without the fade grid.  ``momentum_ranges`` forwards overridable knob
    ranges to :func:`momentum_grid` (gate-specific ranges under the
    ``"gate"`` key); ``band_ranges`` forwards overridable knob ranges to
    :func:`band_grid`.
    """
    for gate in gates:
        if gate not in ("ratio", "absolute"):
            raise ValueError(
                f"sweep supports momentum gates 'ratio' and 'absolute'; got {gate!r}"
            )
    for strat in strategies:
        if strat not in ("fade", "momentum", "band"):
            raise ValueError(
                f"sweep supports strategies 'fade', 'momentum', and 'band'; got {strat!r}"
            )
    base_config = TraderConfig.default()
    risk_overrides: dict[str, Any] = {}
    if max_daily_loss_fraction is not None:
        risk_overrides["max_daily_loss_fraction"] = max_daily_loss_fraction
    if max_consecutive_losses is not None:
        risk_overrides["max_consecutive_losses"] = max_consecutive_losses
    config = replace(
        base_config,
        paper=paper or PaperExecutionConfig(),
        risk=replace(base_config.risk, **risk_overrides) if risk_overrides else base_config.risk,
    )
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

    if "band" in strategies:
        for bc in band_grid(**(band_ranges or {})):
            res = run_vol_band_backtest(
                ticks,
                symbol=symbol,
                timeframe_sec=timeframe_sec,
                config=config,
                strategy_config=bc,
                garch_state=garch_state,
                paper=paper,
            )
            rows.append(SweepResult.from_backtest("band", bc, res))

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
            "max_hold_bars", "max_hold_sec", "min_revert_signal",
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
    band_ranges: dict[str, Any] | None = None,
    artifact_output_path: str | Path | None = None,
    max_daily_loss_fraction: float | None = None,
    max_consecutive_losses: int | None = None,
) -> dict[str, Any]:
    """Load ticks, run the sweep, optionally persist the report as JSON."""
    ticks = dedupe_ticks(load_ticks_csv(csv_path, default_symbol=symbol))
    # Realistic execution costs (matching backtest-vol §36): 0.05 absolute
    # price units ~ 5 real V75 ticks of slippage per side; 0.10 cash fee is
    # a realistic retail fee on synthetic indices.  The old 1.0/0.5 defaults
    # were 100-tick slippage and a fee ~10% of a $1k stake — they collapsed
    # every strategy and never represented a real execution.
    paper = PaperExecutionConfig(
        entry_slippage_ticks=0.05,
        exit_slippage_ticks=0.05,
        execution_penalty_per_trade=0.10,
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
        band_ranges=band_ranges,
        paper=paper,
        garch_state=garch_state,
        max_daily_loss_fraction=max_daily_loss_fraction,
        max_consecutive_losses=max_consecutive_losses,
    )
    report = summarize_sweep(rows, min_trades=min_trades, top_n=top_n)
    report["elapsed_sec"] = round(time.time() - t0, 1)
    if artifact_output_path is not None:
        out = Path(artifact_output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["artifact"] = str(out)
    return report
