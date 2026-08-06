"""Tests for the walk-forward Stage-3 gate backtest (research/gate_backtest.py)."""

from __future__ import annotations

import unittest

from synthetic_trader.research.gate_backtest import (
    CallRecord,
    GateBacktestResult,
    _aggregate,
    reward_risk_from_record,
    simulate_gate_walk_forward,
)


def _call(
    *,
    epoch: float,
    trigger: str = "setup_candidate",
    outcome: str | None = None,
    entry: float = 100.0,
    stop: float = 90.0,
    target: float = 130.0,
    hold_minutes: int = 1,
) -> CallRecord:
    record: dict[str, object] = {
        "symbol": "R_100",
        "generated_at": f"2026-07-11T00:{int(epoch // 60):02d}:{int(epoch % 60):02d}Z",
        "entry": entry,
        "execution_stop": stop,
        "primary_target": target,
        "hold_horizon_minutes": hold_minutes,
        "trade_status": "valid",
    }
    return CallRecord(
        generated_at_epoch=epoch,
        record=record,
        trigger_type=trigger,
        outcome_label=outcome,
    )


class SimulateGateWalkForwardTests(unittest.TestCase):
    def test_no_lookahead_first_calls_see_no_outcomes(self) -> None:
        """A call must never see its own (or a later) outcome."""
        calls = [
            _call(epoch=float(i * 100), outcome="stop_hit", hold_minutes=1)
            for i in range(12)
        ]
        simulate_gate_walk_forward(
            calls=calls,
            min_samples=10,
            hit_rate_floor=0.5,
            suppression_mode="suppress",
        )
        # Outcomes resolve at epoch + 60s.  Call 0 (t=0) resolves at 60; the
        # earliest emission after that is call 1 at t=100 -> sees only call 0.
        self.assertEqual(calls[0].samples_at_emission, 0)
        # Call 11 (t=1100) sees calls 0..10 (resolutions 60..1060 < 1100).
        self.assertEqual(calls[11].samples_at_emission, 11)
        self.assertEqual(calls[11].gate_state, "suppressed")  # 1/11 hit = 9% < 50%

    def test_good_trigger_kept_bad_trigger_suppressed(self) -> None:
        """A trigger clearing the floor is kept; one below it is suppressed."""
        calls: list[CallRecord] = []
        for i in range(20):
            good_outcome = "target_hit" if i % 10 != 0 else "stop_hit"  # ~90% hit
            bad_outcome = "stop_hit" if i % 10 != 0 else "target_hit"  # ~10% hit
            calls.append(_call(epoch=float(i * 100), trigger="good", outcome=good_outcome))
            calls.append(_call(epoch=float(i * 100 + 50), trigger="bad", outcome=bad_outcome))
        simulate_gate_walk_forward(
            calls=calls,
            min_samples=10,
            hit_rate_floor=0.5,
            suppression_mode="suppress",
        )
        good = [c for c in calls if c.trigger_type == "good"]
        bad = [c for c in calls if c.trigger_type == "bad"]
        # Once 10 outcomes accumulate, the gate must keep the good trigger and
        # suppress the bad one.
        self.assertTrue(any(c.gate_state == "suppressed" for c in bad))
        self.assertTrue(any(c.gate_state != "suppressed" for c in good))
        # The final calls carry the honest verdicts.
        self.assertEqual(bad[-1].gate_state, "suppressed")
        self.assertIn(good[-1].gate_state, ("gated", "annotated"))

    def test_annotate_mode_never_suppresses(self) -> None:
        calls = [
            _call(epoch=float(i * 100), trigger="bad", outcome="stop_hit")
            for i in range(15)
        ]
        simulate_gate_walk_forward(
            calls=calls,
            min_samples=10,
            hit_rate_floor=0.5,
            suppression_mode="annotate",
        )
        self.assertEqual(calls[-1].gate_state, "annotated")  # shown with honest rate
        self.assertEqual(calls[-1].evidence_status, "suppressed")  # data says below floor


class RewardRiskTests(unittest.TestCase):
    def test_derives_rr_from_levels(self) -> None:
        record: dict[str, object] = {
            "entry": 100.0,
            "execution_stop": 90.0,
            "primary_target": 130.0,
        }
        self.assertAlmostEqual(reward_risk_from_record(record), 3.0)

    def test_short_sell_rr(self) -> None:
        record: dict[str, object] = {
            "entry": 100.0,
            "execution_stop": 105.0,
            "primary_target": 90.0,
        }
        self.assertAlmostEqual(reward_risk_from_record(record), 2.0)

    def test_missing_levels_defaults_to_1(self) -> None:
        self.assertEqual(reward_risk_from_record({"entry": 100.0}), 1.0)


class AggregateTests(unittest.TestCase):
    def test_per_trigger_stats(self) -> None:
        result = GateBacktestResult(symbol="R_100", timeframe_sec=300)
        result.calls = [
            _call(epoch=1, trigger="t1", outcome="target_hit"),
            _call(epoch=2, trigger="t1", outcome="stop_hit"),
            _call(epoch=3, trigger="t2", outcome="target_hit"),
        ]
        for c in result.calls:
            c.gate_state = "suppressed" if c.trigger_type == "t1" else "annotated"
        _aggregate(result)
        self.assertEqual(result.per_trigger["t1"].kept, 0)
        self.assertEqual(result.per_trigger["t1"].suppressed, 2)
        self.assertEqual(result.per_trigger["t1"].suppressed_hit_rate, 0.5)
        self.assertEqual(result.per_trigger["t2"].kept, 1)
        self.assertEqual(result.per_trigger["t2"].kept_hit_rate, 1.0)
        self.assertEqual(len(result.kept_calls), 1)
        self.assertEqual(len(result.suppressed_calls), 2)


if __name__ == "__main__":
    unittest.main()
