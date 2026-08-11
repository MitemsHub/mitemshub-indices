"""Tests for combined-regime A/B (research/combined_regime.py).

The probe showed stacking the ratio-gate momentum next to the band fade is
arithmetic dilution (they fire on the SAME candles in OPPOSITE directions).
These tests lock the productionized measurement: shared candle stream,
separate sub-accounts, overlap attribution, and the A/B verdict.
"""

from __future__ import annotations

import json
import math

import pytest

from synthetic_trader.backtest.vol_reversion import dedupe_ticks
from synthetic_trader.domain import Tick
from synthetic_trader.research.combined_regime import (
    LegSpec,
    ab_verdict,
    run_combined_legs,
    run_combined_pair,
)

# Same fixture shape as the vol-param sweep tests: quiet base, then a
# sustained elevated-vol regime that both the band fade and the ratio-gate
# momentum can react to.
def _ticks(symbol: str = "R_75", n: int = 500) -> list[Tick]:
    import math as _m

    closes: list[float] = []
    for i in range(120):
        closes.append(100.0 + 0.005 * _m.sin(i / 3.0))
    base = closes[-1]
    rng = [0.02, -0.018, 0.021, -0.019, 0.02, 0.017, -0.021, 0.019]
    for i in range(n - len(closes)):
        closes.append(base * _m.exp(rng[i % len(rng)]))
    return [Tick(symbol=symbol, epoch=float(i * 60), price=c) for i, c in enumerate(closes)]


@pytest.fixture(scope="module")
def ticks() -> list[Tick]:
    return dedupe_ticks(_ticks())


# The sweep fixture never fires the band fade (it is momentum-shaped), so
# the fixture pair is ratio-gate vs absolute-gate momentum — both fire on
# the same elevated-vol regime, giving real overlap candles in the SAME
# direction (both follow).
@pytest.fixture(scope="module")
def combined(ticks: list[Tick]):
    return run_combined_legs(
        ticks,
        "R_75",
        60,
        LegSpec("momentum", {"z_entry": 0.5, "vol_min_ratio": 1.05}, label="mom_loose"),
        LegSpec("momentum", {"z_entry": 0.5, "mom_gate": "absolute", "abs_sigma_mult": 1.5}, label="mom_abs"),
    )


class TestLegSpec:
    def test_invalid_strategy_raises(self) -> None:
        with pytest.raises(ValueError):
            LegSpec("sniper")  # type: ignore[arg-type]

    def test_effective_label_defaults_to_strategy(self) -> None:
        assert LegSpec("band").effective_label == "band"
        assert LegSpec("band", label="my_leg").effective_label == "my_leg"


class TestRun:
    def test_both_legs_report(self, combined) -> None:
        assert set(combined.legs) == {"mom_loose", "mom_abs"}
        for label, leg in combined.legs.items():
            assert leg.metrics.trades >= 0
            assert leg.signals >= 0

    def test_combined_metrics_are_the_union(self, combined) -> None:
        c = combined.combined_metrics
        n = sum(leg.metrics.trades for leg in combined.legs.values())
        assert c.trades == n

    def test_combined_equity_is_the_sum_of_leg_equities(self, combined) -> None:
        total_legs = sum(leg.equity for leg in combined.legs.values())
        assert abs(combined.combined_equity - (total_legs - 1000.0)) < 1e-6

    def test_sig_log_contains_both_labels(self, combined) -> None:
        labels = {s[1] for s in combined.sig_log}
        assert labels == {"mom_loose", "mom_abs"}


class TestOverlapAttribution:
    def test_overlap_stats_shape(self, combined) -> None:
        ov = combined.overlap_stats
        assert set(ov) >= {"candles_total", "both", "opposite_dir", "same_dir"}
        assert ov["both"] == ov["opposite_dir"] + ov["same_dir"]
        # Two momentum legs on the same elevated regime fire on shared
        # candles in the SAME direction (both follow the move).
        if ov["both"] > 0:
            assert ov["opposite_dir"] == 0

    def test_attribution_splits_pnl(self, combined) -> None:
        for label in combined.legs:
            ov = combined.attribution[f"{label}.overlap"]
            so = combined.attribution[f"{label}.standalone"]
            n_ov = combined.attribution_n[f"{label}.overlap"]
            n_so = combined.attribution_n[f"{label}.standalone"]
            assert n_ov + n_so == combined.legs[label].metrics.trades
            assert abs(ov + so - combined.legs[label].metrics.net_pnl) < 1e-6


class TestVerdict:
    def test_verdict_has_all_keys(self, combined) -> None:
        v = ab_verdict(combined)
        for key in (
            "composite",
            "net_status",
            "trades_status",
            "exp_status",
            "overlap_nature",
            "correlation_nature",
            "reason",
        ):
            assert key in v

    def test_same_direction_overlap_classified(self, combined) -> None:
        v = ab_verdict(combined)
        if combined.overlap_stats["both"] > 0:
            assert v["overlap_nature"] == "same_direction_overlap"


class TestPairPipeline:
    def test_full_pair_report_and_artifact(self, ticks: list[Tick], tmp_path) -> None:
        out = tmp_path / "combined.json"
        report = run_combined_pair(
            csv_path=_write_csv(ticks, tmp_path),
            symbol="R_75",
            timeframe_sec=60,
            leg_a=LegSpec("momentum", {"z_entry": 0.5, "vol_min_ratio": 1.05}, label="mom_loose"),
            leg_b=LegSpec("momentum", {"z_entry": 0.5, "mom_gate": "absolute", "abs_sigma_mult": 1.5}, label="mom_abs"),
            artifact_output_path=out,
        )
        assert report["symbol"] == "R_75"
        assert set(report["legs"]) == {"mom_loose", "mom_abs"}
        assert report["verdict"]["composite"] in {
            "adds_trades_and_net",
            "adds_trades_net_neutral",
            "dilutes_net",
            "no_change",
        }
        # Artifact round-trips.
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["combined"]["trades"] == report["combined"]["trades"]
        assert saved["overlap"] == report["overlap"]

    def test_daily_corr_reported(self, combined) -> None:
        if combined.daily_days >= 2:
            assert not math.isnan(combined.daily_corr)


def _write_csv(ticks: list[Tick], tmp_path) -> str:
    p = tmp_path / "ticks.csv"
    lines = ["epoch,symbol,price"]
    for t in ticks:
        lines.append(f"{t.epoch},{t.symbol},{t.price:.5f}")
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)
