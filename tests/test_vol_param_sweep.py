"""Tests for the vol-targeting parameter sweep (research/vol_param_sweep.py)."""

from __future__ import annotations

import math

import pytest

from synthetic_trader.domain import Tick
from synthetic_trader.research.vol_param_sweep import (
    FADE_STOP_MULT,
    FADE_TARGET_MULT,
    FADE_VOL_RATIO,
    FADE_Z_ENTRY,
    MOM_ABS_MULT,
    MOM_HOLD_BARS,
    MOM_STOP_MULT,
    MOM_TARGET_MULT,
    MOM_VOL_RATIO,
    MOM_Z_ENTRY,
    SweepResult,
    fade_grid,
    momentum_grid,
    print_sweep_report,
    run_sweep,
    run_sweep_for_csv,
    summarize_sweep,
)
from synthetic_trader.backtest.vol_reversion import dedupe_ticks


def _ticks(symbol: str = "R_75", n: int = 400) -> list[Tick]:
    """Quiet base, then a sustained elevated-vol regime (momentum-worthy)."""
    import math as _m

    closes: list[float] = []
    for i in range(120):
        closes.append(100.0 + 0.005 * _m.sin(i / 3.0))
    base = closes[-1]
    rng = [0.02, -0.018, 0.021, -0.019, 0.02, 0.017, -0.021, 0.019]
    for i in range(n - len(closes)):
        closes.append(base * _m.exp(rng[i % len(rng)]))
    return [Tick(symbol=symbol, epoch=float(i * 60), price=c) for i, c in enumerate(closes)]


# The default hold range spans 15..120 step 15 → 8 values.  A full default
# sweep is 108 fade + 2 × 648 momentum = 1404 configs, so the tests share one
# deterministic run through a module-scoped fixture instead of re-running the
# grid in every test.
N_HOLD = len(range(15, 121, 15))  # 8
N_MOM_PER_GATE = 3 * 3 * 3 * 3 * N_HOLD  # z x gate x stop x target x hold
N_FADE = 108
N_TOTAL = N_FADE + 2 * N_MOM_PER_GATE


@pytest.fixture(scope="module")
def sweep_rows():
    ticks = dedupe_ticks(_ticks())
    return run_sweep(ticks, symbol="R_75", timeframe_sec=60)


class TestGrids:
    def test_fade_grid_cartesian_size(self) -> None:
        grid = fade_grid()
        n_z = len([1.25, 1.5, 1.75, 2.0])
        n_vr = len([1.3, 1.55, 1.8])
        n_s = len([2.0, 2.5, 3.0])
        n_t = len([1.0, 1.5, 2.0])
        assert len(grid) == n_z * n_vr * n_s * n_t == 108
        # Every config carries the fixed tuned knobs.
        for cfg in grid[:5]:
            assert cfg.min_revert_signal == 0.02
            assert cfg.max_hold_bars == 30

    def test_fade_grid_covers_bounds(self) -> None:
        grid = fade_grid()
        zs = {cfg.z_entry for cfg in grid}
        vrs = {cfg.vol_extended_ratio for cfg in grid}
        ss = {cfg.stop_sigma_mult for cfg in grid}
        ts = {cfg.target_sigma_mult for cfg in grid}
        assert min(zs) == FADE_Z_ENTRY[0] and max(zs) == FADE_Z_ENTRY[1]
        assert min(vrs) == FADE_VOL_RATIO[0] and max(vrs) == FADE_VOL_RATIO[1]
        assert min(ss) == FADE_STOP_MULT[0] and max(ss) == FADE_STOP_MULT[1]
        assert min(ts) == FADE_TARGET_MULT[0] and max(ts) == FADE_TARGET_MULT[1]

    def test_momentum_grid_per_gate(self) -> None:
        ratio = momentum_grid("ratio")
        absolute = momentum_grid("absolute")
        n_z = len([0.5, 0.75, 1.0])
        n_s = len([1.0, 1.5, 2.0])
        n_t = len([2.0, 3.0, 4.0])
        assert len(ratio) == n_z * 3 * n_s * n_t * N_HOLD
        assert len(absolute) == n_z * 3 * n_s * n_t * N_HOLD
        assert all(c.mom_gate == "ratio" for c in ratio)
        assert all(c.mom_gate == "absolute" for c in absolute)
        # Ratio configs carry vol_min_ratio; absolute configs carry abs_sigma_mult.
        assert {round(c.vol_min_ratio, 2) for c in ratio} == {
            round(v, 2) for v in (1.15, 1.325, 1.5)
        }
        assert {c.abs_sigma_mult for c in absolute} == {1.5, 2.0, 2.5}
        assert MOM_ABS_MULT[0] == 1.5 and MOM_ABS_MULT[1] == 2.5
        # Time-stop geometry is a swept dimension (not pinned at 30), and the
        # default range must reach 120 — the §34 winner lives at holds 110–120.
        holds = {c.max_hold_bars for c in absolute}
        assert min(holds) == 15 and max(holds) == 120
        assert len(holds) == N_HOLD
        assert MOM_HOLD_BARS[0] == 15 and MOM_HOLD_BARS[1] == 120

    def test_momentum_grid_overrides(self) -> None:
        """Focused re-tune ranges override the module defaults per knob."""
        grid = momentum_grid(
            "absolute",
            z_entries=(0.5, 1.0, 0.5),
            stops=(0.75, 1.0, 0.25),
            targets=(2.0, 4.0, 2.0),
            holds=(10, 30, 10),
            ref_periods=(300, 900, 300),
            gate_ranges={"abs_sigma_mult": (1.5, 2.0, 0.5)},
        )
        zs = {c.z_entry for c in grid}
        stops = {c.stop_sigma_mult for c in grid}
        targets = {c.target_sigma_mult for c in grid}
        holds = {c.max_hold_bars for c in grid}
        abs_mults = {c.abs_sigma_mult for c in grid}
        ref_periods = {c.abs_ref_period for c in grid}
        assert zs == {0.5, 1.0}
        assert stops == {0.75, 1.0}
        assert targets == {2.0, 4.0}
        assert holds == {10, 20, 30}
        assert abs_mults == {1.5, 2.0}
        assert ref_periods == {300, 600, 900}
        # Cartesian size = 2 z x 2 abs x 2 stop x 2 target x 3 hold x 3 ref.
        assert len(grid) == 2 * 2 * 2 * 2 * 3 * 3 == 144


class TestSweep:
    def test_sweep_ranks_by_expectancy(self, sweep_rows) -> None:
        rows = sweep_rows
        assert len(rows) == N_TOTAL
        # Sorted descending by expectancy.
        exps = [r.expectancy_r for r in rows]
        assert exps == sorted(exps, reverse=True)
        # Labels cover both strategies.
        labels = {r.label for r in rows}
        assert "fade" in labels and "momentum:ratio" in labels and "momentum:absolute" in labels

    def test_sweep_strategies_filter(self) -> None:
        ticks = dedupe_ticks(_ticks())
        mom_only = run_sweep(
            ticks,
            symbol="R_75",
            timeframe_sec=60,
            strategies=("momentum",),
            gates=("absolute",),
        )
        assert len(mom_only) == N_MOM_PER_GATE
        assert all(r.label == "momentum:absolute" for r in mom_only)

        fade_only = run_sweep(
            ticks,
            symbol="R_75",
            timeframe_sec=60,
            strategies=("fade",),
            gates=("absolute",),
        )
        assert len(fade_only) == N_FADE
        assert all(r.label == "fade" for r in fade_only)

    def test_sweep_for_csv_roundtrip(self, tmp_path) -> None:
        """CLI path: run_sweep_for_csv must not choke on min_trades (the
        previous version passed it into run_sweep, which rejects it)."""
        import json

        ticks = dedupe_ticks(_ticks())
        csv_path = tmp_path / "ticks.csv"
        # Headerless epoch,symbol,price — the live collector format.
        csv_path.write_text(
            "\n".join(
                f"{t.epoch:.0f},{t.symbol},{t.price:.6f}" for t in ticks
            ),
            encoding="utf-8",
        )
        artifact = tmp_path / "sweep.json"
        # Tiny grid — the roundtrip only proves plumbing, not full-grid cost.
        report = run_sweep_for_csv(
            csv_path,
            symbol="R_75",
            timeframe_sec=60,
            min_trades=1,
            top_n=3,
            gates=("absolute",),
            strategies=("momentum",),
            momentum_ranges={
                "z_entries": (0.75, 1.0, 0.25),
                "stops": (1.5, 2.0, 0.5),
                "targets": (4.0, 5.0, 1.0),
                "holds": (110, 120, 10),
                "gate_ranges": {"abs_sigma_mult": (1.5, 1.5, 0.1)},
            },
            artifact_output_path=artifact,
        )
        # 2 z x 1 abs x 2 stop x 2 target x 2 hold = 16 configs.
        assert report["configs_tested"] == 16
        assert artifact.exists()
        persisted = json.loads(artifact.read_text(encoding="utf-8"))
        assert persisted["configs_tested"] == report["configs_tested"]

    def test_min_trades_filter(self, sweep_rows) -> None:
        rows = sweep_rows
        max_trades = max(r.trades for r in rows)
        # A floor below the max must yield a non-empty, correctly-filtered report.
        floor = max(1, max_trades - 1)
        report = summarize_sweep(rows, min_trades=floor, top_n=5)
        assert report["configs_tested"] == N_TOTAL
        assert report["top"], "floor below max_trades must leave at least one config"
        assert all(r["trades"] >= floor for r in report["top"])
        assert len(report["top"]) <= 5
        # A floor above the max must yield an empty report (honest filter).
        empty = summarize_sweep(rows, min_trades=max_trades + 1, top_n=5)
        assert empty["top"] == []
        assert empty["configs_with_min_trades"] == 0

    def test_report_shape_and_json_serializable(self, sweep_rows) -> None:
        import json

        rows = sweep_rows
        report = summarize_sweep(rows, min_trades=1, top_n=3)
        json.dumps(report)  # must not raise
        assert report["configs_tested"] == N_TOTAL
        assert len(report["top"]) == 3
        first = report["top"][0]
        for key in ("label", "trades", "win_rate", "expectancy_r", "net_pnl", "config"):
            assert key in first

    def test_print_report_runs(self, capsys, sweep_rows) -> None:
        rows = sweep_rows
        report = summarize_sweep(rows, min_trades=1, top_n=3)
        print_sweep_report(report, "R_75", 60)
        out = capsys.readouterr().out
        assert "sweep R_75 @ 60s" in out
        assert "best:" in out

    def test_print_report_caveat_when_thin(self, capsys) -> None:
        """A best config with < 20 trades must print an explicit significance
        caveat — a 7-trade +0.94R cell must not read as a verdict."""
        ticks = dedupe_ticks(_ticks())
        rows = run_sweep(ticks, symbol="R_75", timeframe_sec=60)
        # Force the best row to look thin, then confirm the caveat prints.
        thin = [
            SweepResult(
                label="momentum:absolute",
                config={},
                trades=7,
                signals=20,
                win_rate=0.71,
                profit_factor=5.6,
                expectancy_r=0.941,
                net_pnl=35.6,
                final_equity=1035.6,
                model_version="vol-momentum-v1",
            ),
            *[r for r in rows if r.trades >= 8][:4],
        ]
        report = summarize_sweep(thin, min_trades=1, top_n=5)
        print_sweep_report(report, "R_75", 300)
        out = capsys.readouterr().out
        assert "not statistically meaningful" in out

    def test_unknown_gate_rejected_before_running(self) -> None:
        import pytest

        ticks = dedupe_ticks(_ticks())
        with pytest.raises(ValueError):
            run_sweep(ticks, symbol="R_75", timeframe_sec=60, gates=("bogus",))

    def test_unknown_strategy_rejected(self) -> None:
        ticks = dedupe_ticks(_ticks())
        with pytest.raises(ValueError):
            run_sweep(ticks, symbol="R_75", timeframe_sec=60, strategies=("bogus",))

    def test_sweep_deterministic(self) -> None:
        ticks = dedupe_ticks(_ticks())
        # Tiny grid — determinism is proven with a handful of configs.
        ranges = {
            "z_entries": (0.75, 1.0, 0.25),
            "stops": (1.5, 2.0, 0.5),
            "targets": (4.0, 5.0, 1.0),
            "holds": (110, 120, 10),
            "gate_ranges": {"abs_sigma_mult": (1.5, 1.5, 0.1)},
        }
        a = run_sweep(ticks, symbol="R_75", timeframe_sec=60, momentum_ranges=ranges)
        b = run_sweep(ticks, symbol="R_75", timeframe_sec=60, momentum_ranges=ranges)
        # Fade 108 + ratio (3 vol defaults) 2*3*2*2*2=48 + absolute 16 = 172.
        assert len(a) == 172
        assert [r.expectancy_r for r in a] == [r.expectancy_r for r in b]

    def test_finite_metrics(self, sweep_rows) -> None:
        rows = sweep_rows
        for r in rows:
            assert math.isfinite(r.expectancy_r)
            assert math.isfinite(r.net_pnl)
