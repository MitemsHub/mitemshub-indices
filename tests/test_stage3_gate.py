"""Tests for the Stage-3 empirical gate (synthetic_trader.live.stage3_gate)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from synthetic_trader.live.stage3_gate import (
    GATE_HIT_RATE_FLOOR,
    MIN_STAGE3_SAMPLES,
    apply_stage3_gate,
    build_stage3_block,
    load_empirical_summary,
    load_horizon_verdict,
    resolve_trigger_type,
    sizing_ladder,
    _env_mode,
    PROVEN_ONLY_MODE,
    _env_bool,
)


def _verdicts_file(path: Path, symbol: str = "R_75", calibrated: bool = True) -> Path:
    verdict = (
        {"verdict": "calibrated", "windows": 40, "coverage_p50": 0.5, "coverage_p90": 0.9}
        if calibrated
        else {"verdict": "needs_more_data_or_tuning", "windows": 40, "coverage_p50": 0.2, "coverage_p90": 0.8}
    )
    path.write_text(
        json.dumps({symbol: {"4h": verdict, "6h": verdict}}) + "\n",
        encoding="utf-8",
    )
    return path


def _write_outcomes(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _scored(
    symbol: str,
    trigger_type: str,
    label: str,
    trade_status: str = "valid",
) -> dict:
    return {
        "symbol": symbol,
        "trigger_type": trigger_type,
        "trade_status": trade_status,
        "outcome_label": label,
        # Level-bearing rows: only measured trade outcomes count as evidence
        # (level-less rows are excluded by summarize_outcomes).
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 103.0,
        "max_favorable_excursion": 10.0,
        "max_adverse_excursion": 5.0,
    }


def test_break_even_floor_math() -> None:
    """Break-even floor = 1/(1+reward:risk) + margin, clamped to safe bounds.
    A 3R setup must clear ~30% (1/4 + 5%), not an unreachable 50%.
    """
    from synthetic_trader.live.stage3_gate import (
        BREAK_EVEN_FLOOR_MAX,
        BREAK_EVEN_FLOOR_MIN,
        break_even_floor,
    )

    assert abs(break_even_floor(3.0) - 0.30) < 1e-9          # 1/(1+3) + 0.05
    assert abs(break_even_floor(2.0) - (1 / 3 + 0.05)) < 1e-9  # ~38.3%
    assert abs(break_even_floor(1.0) - 0.55) < 1e-9          # 1/(1+1) + 0.05
    # Unknown geometry falls back to the conservative flat floor.
    assert break_even_floor(None) == GATE_HIT_RATE_FLOOR
    assert break_even_floor(0.0) == GATE_HIT_RATE_FLOOR
    assert break_even_floor(-3.0) == GATE_HIT_RATE_FLOOR
    # Degenerate geometry can never produce a meaningless floor.  A tiny RR
    # demands a near-100% hit rate -> clamps to the MAX; a huge RR can almost
    # never lose -> clamps to the MIN.
    assert break_even_floor(0.01) == BREAK_EVEN_FLOOR_MAX
    assert break_even_floor(1000.0) == BREAK_EVEN_FLOOR_MIN


def test_average_reward_risk_from_outcomes(tmp_path: Path) -> None:
    """The live gate derives the break-even floor from the scored outcomes'
    REAL geometry (same level filter as summarize_outcomes), not just the
    current call's reward:risk.
    """
    from synthetic_trader.live.stage3_gate import average_reward_risk

    path = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        path,
        [
            _scored("R_75", "continuation_close", "target_hit"),  # RR 1.5 (100/98/103)
            _scored("R_75", "continuation_close", "stop_hit"),  # RR 1.5
            _scored("R_75", "other_trigger", "target_hit"),  # different trigger
            {"symbol": "R_75", "trigger_type": "continuation_close", "outcome_label": "target_hit"},  # no levels -> ignored
            {
                "symbol": "R_75",
                "trigger_type": "continuation_close",
                "outcome_label": "target_hit",
                "entry": 100.0,
                "execution_stop": 98.0,
                "primary_target": 103.0,
                "scoring_source": "deriv_fallback",  # fallback rows are not evidence
            },
        ],
    )
    rr = average_reward_risk(
        symbol="R_75", trigger_type="continuation_close", outcomes_path=path
    )
    assert rr is not None
    assert abs(rr - 1.5) < 1e-9
    # No level-bearing evidence for this trigger -> None (the gate then falls
    # back to the current call's own reward:risk).
    assert (
        average_reward_risk(
            symbol="R_75", trigger_type="no_such_trigger", outcomes_path=path
        )
        is None
    )


def test_build_stage3_block_defaults_to_break_even_floor(tmp_path: Path) -> None:
    """No explicit floor -> the per-trigger BREAK-EVEN floor is computed from
    the call's own reward:risk (no outcomes yet) and surfaced transparently.
    """
    snapshot = {
        "symbol": "R_75",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.65,
        "reward_risk": 3.0,
    }
    block = build_stage3_block(snapshot, outcomes_path=tmp_path / "missing.jsonl")
    assert block["floor_basis"] == "break_even"
    assert block["break_even_rr"] == 3.0
    assert abs(block["hit_rate_floor"] - 0.30) < 1e-9


def test_build_stage3_block_explicit_floor_wins(tmp_path: Path) -> None:
    """An explicit hit_rate_floor always wins and is marked 'configured'."""
    snapshot = {
        "symbol": "R_75",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
        "reward_risk": 3.0,
    }
    block = build_stage3_block(
        snapshot, outcomes_path=tmp_path / "missing.jsonl", hit_rate_floor=0.5
    )
    assert block["floor_basis"] == "configured"
    assert block["hit_rate_floor"] == 0.5
    assert block["break_even_rr"] is None


def test_gate_break_even_floor_flips_40pct_3r_to_gated(tmp_path: Path) -> None:
    """THE FLIP: a 3R trigger with a 40% market-verified hit rate was
    suppressed under the old flat 50% floor (unreachable for 3R geometry).
    Its break-even floor is ~30%, so 40% clears it -> gated (kept).
    """
    outcomes = tmp_path / "outcomes.jsonl"
    rows = []
    for _ in range(4):
        rows.append(
            {
                "symbol": "R_75",
                "trigger_type": "continuation_close",
                "trade_status": "valid",
                "outcome_label": "target_hit",
                "entry": 100.0,
                "execution_stop": 99.0,  # risk 1
                "primary_target": 103.0,  # reward 3 -> RR 3.0
            }
        )
    for _ in range(6):
        rows.append(
            {
                "symbol": "R_75",
                "trigger_type": "continuation_close",
                "trade_status": "valid",
                "outcome_label": "stop_hit",
                "entry": 100.0,
                "execution_stop": 99.0,
                "primary_target": 103.0,
            }
        )
    _write_outcomes(outcomes, rows)
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
    }
    block = build_stage3_block(
        snapshot, outcomes_path=outcomes, verdict_cache_path=verdicts
    )
    assert block["empirical_sample_count"] == 10
    assert block["empirical_target_hit_rate"] == 0.4
    assert block["floor_basis"] == "break_even"
    assert block["break_even_rr"] == 3.0
    assert abs(block["hit_rate_floor"] - 0.30) < 1e-9
    assert block["state"] == "gated"  # 40% >= 30% + calibrated horizon
    assert block["below_floor"] is False

    # Same evidence under the legacy flat 0.5 bar -> suppressed.
    flat = build_stage3_block(
        snapshot,
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        hit_rate_floor=0.5,
    )
    assert flat["state"] == "suppressed"
    assert flat["below_floor"] is True


def test_load_empirical_summary_ignores_level_less_and_fallback_evidence(tmp_path: Path) -> None:
    """Regression: stale level-less outcomes (July-12 era) and Deriv-fallback
    outcomes are NOT evidence.  They poisoned (symbol, trigger_type) buckets
    with fake 0% and suppressed every real setup_candidate call — the gate
    must resolve no_data when only such rows exist."""
    path = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        path,
        [
            {"symbol": "R_75", "trigger_type": "setup_candidate", "trade_status": "valid", "outcome_label": "forming_remained_correct"},
            {"symbol": "R_75", "trigger_type": "setup_candidate", "trade_status": "valid", "outcome_label": "rejected_but_price_ran"},
            {
                "symbol": "R_75",
                "trigger_type": "setup_candidate",
                "trade_status": "valid",
                "outcome_label": "target_hit",
                "entry": 100.0,
                "execution_stop": 98.0,
                "primary_target": 102.0,
                "scoring_source": "deriv_fallback",
            },
        ],
    )

    summary = load_empirical_summary(
        symbol="R_75",
        trigger_type="setup_candidate",
        outcomes_path=path,
    )

    assert summary["count"] == 0
    assert summary["target_hit_rate"] is None


def test_load_empirical_summary_rolls_up_across_statuses(tmp_path: Path) -> None:
    path = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        path,
        [
            _scored("R_75", "continuation_close", "target_hit", "valid"),
            _scored("R_75", "continuation_close", "target_hit", "valid"),
            _scored("R_75", "continuation_close", "stop_hit", "valid"),
            _scored("R_75", "continuation_close", "target_hit", "not_valid"),
            _scored("R_75", "reclaim_pullback", "stop_hit", "valid"),
            _scored("R_100", "continuation_close", "target_hit", "valid"),
        ],
    )

    summary = load_empirical_summary(
        symbol="R_75",
        trigger_type="continuation_close",
        outcomes_path=path,
    )
    assert summary["count"] == 4
    assert summary["target_hit_rate"] == 0.75  # 3/4
    assert summary["stop_hit_rate"] == 0.25

    missing = load_empirical_summary(
        symbol="R_75",
        trigger_type="no_such_trigger",
        outcomes_path=path,
    )
    assert missing["count"] == 0
    assert missing["target_hit_rate"] is None


def test_load_empirical_summary_missing_journal(tmp_path: Path) -> None:
    summary = load_empirical_summary(
        symbol="R_75",
        trigger_type="anything",
        outcomes_path=tmp_path / "does_not_exist.jsonl",
    )
    assert summary["count"] == 0
    assert summary["target_hit_rate"] is None


def test_load_horizon_verdict_rich_dict_form(tmp_path: Path) -> None:
    path = tmp_path / "forecast_verdicts.jsonl"
    path.write_text(
        json.dumps(
            {
                "R_75": {
                    "4h": {"verdict": "calibrated", "windows": 42, "coverage_p50": 0.52, "coverage_p90": 0.91},
                    "6h": {"verdict": "calibrated", "windows": 38, "coverage_p50": 0.48, "coverage_p90": 0.89},
                },
                "R_100": {
                    "4h": {"verdict": "needs_more_data_or_tuning", "windows": 31, "coverage_p50": 0.24, "coverage_p90": 0.80},
                    "6h": {"verdict": "needs_more_data_or_tuning", "windows": 29, "coverage_p50": 0.23, "coverage_p90": 0.79},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    r75 = load_horizon_verdict(symbol="R_75", verdict_cache_path=path)
    assert r75["verdict"] == "calibrated"  # both horizons calibrated
    assert r75["verdict_4h"] == "calibrated"
    assert r75["windows"] == 42
    assert r75["coverage_p50"] == 0.52
    assert r75["coverage_p90"] == 0.91

    r100 = load_horizon_verdict(symbol="R_100", verdict_cache_path=path)
    assert r100["verdict"] == "needs_more_data_or_tuning"


def test_load_horizon_verdict_legacy_string_form(tmp_path: Path) -> None:
    path = tmp_path / "forecast_verdicts.jsonl"
    path.write_text(
        json.dumps({"R_75": {"4h": "calibrated", "6h": "calibrated"}}) + "\n",
        encoding="utf-8",
    )
    result = load_horizon_verdict(symbol="R_75", verdict_cache_path=path)
    assert result["verdict"] == "calibrated"
    assert result["windows"] is None  # legacy form has no validation data


def test_load_horizon_verdict_missing_cache(tmp_path: Path) -> None:
    result = load_horizon_verdict(
        symbol="R_75",
        verdict_cache_path=tmp_path / "missing.jsonl",
    )
    assert result["verdict"] is None
    assert result["coverage_p50"] is None


def test_gate_insufficient_data_keeps_model_confidence(tmp_path: Path) -> None:
    path = tmp_path / "outcomes.jsonl"
    _write_outcomes(path, [_scored("R_75", "continuation_close", "target_hit")])

    snapshot = {
        "symbol": "R_75",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.71,
    }
    block = build_stage3_block(snapshot, outcomes_path=path)
    assert block["state"] == "insufficient_data"
    assert block["empirical_sample_count"] == 1
    assert block["model_confidence"] == 0.71
    assert block["display_confidence"] == 0.71

    applied = apply_stage3_gate(dict(snapshot), outcomes_path=path)
    assert applied["confidence"] == 0.71
    assert applied["stage3"]["state"] == "insufficient_data"


def test_gate_gated_when_rate_clears_and_calibrated(tmp_path: Path) -> None:
    outcomes = tmp_path / "outcomes.jsonl"
    rows = [
        _scored("R_75", "continuation_close", "target_hit")
        for _ in range(int(MIN_STAGE3_SAMPLES * GATE_HIT_RATE_FLOOR) + 1)
    ]
    rows += [
        _scored("R_75", "continuation_close", "stop_hit")
        for _ in range(MIN_STAGE3_SAMPLES - len(rows))
    ]
    _write_outcomes(outcomes, rows)

    verdicts = tmp_path / "forecast_verdicts.jsonl"
    verdicts.write_text(
        json.dumps(
            {
                "R_75": {
                    "4h": {"verdict": "calibrated", "windows": 40, "coverage_p50": 0.5, "coverage_p90": 0.9},
                    "6h": {"verdict": "calibrated", "windows": 40, "coverage_p50": 0.5, "coverage_p90": 0.9},
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = {"symbol": "R_75", "execution_trigger_type": "continuation_close", "confidence": 0.65}
    block = build_stage3_block(snapshot, outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert block["state"] == "gated"
    assert block["empirical_sample_count"] == MIN_STAGE3_SAMPLES
    assert block["below_floor"] is False
    # Model confidence is replaced by the empirical hit rate.
    expected_rate = block["empirical_target_hit_rate"]
    assert block["display_confidence"] == expected_rate
    assert block["model_confidence"] == 0.65

    applied = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert applied["confidence"] == expected_rate
    assert applied["stage3"]["state"] == "gated"
    assert applied["stage3"]["horizon_verdict"] == "calibrated"


def test_gate_suppressed_when_below_floor(tmp_path: Path) -> None:
    """Enough samples + a market-verified rate BELOW the floor -> the call type
    is suppressed (state=suppressed, evidence_status=suppressed) and the call
    is downgraded to stand_aside by apply_stage3_gate.
    """
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [
            _scored("R_75", "continuation_close", "stop_hit")
            for _ in range(MIN_STAGE3_SAMPLES)
        ],
    )
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")

    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
    }
    block = build_stage3_block(snapshot, outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert block["state"] == "suppressed"
    assert block["evidence_status"] == "suppressed"
    assert block["empirical_target_hit_rate"] == 0.0
    assert block["display_confidence"] == 0.0
    assert block["suppressed_call"] == "buy_candidate"
    assert "suppressed" in block["note"].lower()

    applied = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert applied["call"] == "stand_aside"  # never surfaced as a candidate
    assert applied["stage3"]["state"] == "suppressed"
    assert applied["stage3"]["suppressed_call"] == "buy_candidate"


def test_suppression_mode_suppress_downgrades_explicitly(tmp_path: Path) -> None:
    """Explicit suppression_mode='suppress' behaves like the default: the
    below-floor call type is held back and the block records the mode.
    """
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES)],
    )
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
    }
    block = build_stage3_block(
        snapshot,
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        suppression_mode="suppress",
    )
    assert block["state"] == "suppressed"
    assert block["evidence_status"] == "suppressed"
    assert block["suppression_mode"] == "suppress"
    assert block["below_floor"] is True
    assert block["suppressed_call"] == "buy_candidate"

    applied = apply_stage3_gate(
        dict(snapshot),
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        suppression_mode="suppress",
    )
    assert applied["call"] == "stand_aside"
    assert applied["stage3"]["suppression_mode"] == "suppress"
    assert applied["stage3"]["below_floor"] is True
    assert applied["suppressed_reason"]


def test_suppression_mode_annotate_keeps_below_floor_call(tmp_path: Path) -> None:
    """Annotate mode: the same below-floor evidence annotates instead of acting —
    the call is still emitted as a candidate with its honest (low) rate, and
    evidence_status stays 'suppressed' so the dashboard can show the truth.
    """
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES)],
    )
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
    }
    block = build_stage3_block(
        snapshot,
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        suppression_mode="annotate",
    )
    assert block["state"] == "annotated"
    assert block["evidence_status"] == "suppressed"  # truth axis unchanged
    assert block["suppression_mode"] == "annotate"
    assert block["below_floor"] is True  # downstream marker in both modes
    assert block["empirical_target_hit_rate"] == 0.0
    assert block["display_confidence"] == 0.0  # honest rate still shown
    assert block["suppressed_call"] is None  # nothing was held back
    assert "annotate" in block["note"]

    applied = apply_stage3_gate(
        dict(snapshot),
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        suppression_mode="annotate",
    )
    # The candidate is still emitted — annotate mode does not downgrade.
    assert applied["call"] == "buy_candidate"
    assert applied["stage3"]["state"] == "annotated"
    assert applied["stage3"]["evidence_status"] == "suppressed"
    assert applied["stage3"]["below_floor"] is True
    assert "suppressed_reason" not in applied  # not held back, no stale reason


def test_sizing_ladder_gated_full() -> None:
    sizing = sizing_ladder(
        state="gated", evidence_status="proven", hit_rate=0.62, hit_rate_floor=0.5
    )
    assert sizing["level"] == "full"
    assert sizing["multiplier"] == 1.0
    assert sizing["basis"] == "gated"


def test_sizing_ladder_annotated_positive_half() -> None:
    sizing = sizing_ladder(
        state="annotated", evidence_status="proven", hit_rate=0.62, hit_rate_floor=0.5
    )
    assert sizing["level"] == "half"
    assert sizing["multiplier"] == 0.5
    # The half fraction is configurable.
    sizing2 = sizing_ladder(
        state="annotated", evidence_status="proven", hit_rate=0.62,
        hit_rate_floor=0.5, half_multiplier=0.35,
    )
    assert sizing2["multiplier"] == 0.35


def test_sizing_ladder_below_floor_paper_only() -> None:
    sizing = sizing_ladder(
        state="annotated", evidence_status="suppressed", hit_rate=0.3, hit_rate_floor=0.5
    )
    assert sizing["level"] == "paper_only"
    assert sizing["multiplier"] == 0.0


def test_sizing_ladder_insufficient_data_paper_only() -> None:
    still_learning = sizing_ladder(
        state="insufficient_data", evidence_status="still_learning",
        hit_rate=0.6, hit_rate_floor=0.5,
    )
    assert still_learning["level"] == "paper_only"
    assert still_learning["multiplier"] == 0.0
    no_data = sizing_ladder(
        state="insufficient_data", evidence_status="no_data",
        hit_rate=None, hit_rate_floor=0.5,
    )
    assert no_data["level"] == "paper_only"
    assert no_data["multiplier"] == 0.0


def test_sizing_ladder_suppressed_stand_aside() -> None:
    sizing = sizing_ladder(
        state="suppressed", evidence_status="suppressed", hit_rate=0.2, hit_rate_floor=0.5
    )
    assert sizing["level"] == "stand_aside"
    assert sizing["multiplier"] == 0.0


def test_sizing_ladder_never_crashes_on_none_rate() -> None:
    """The ladder must tolerate hit_rate=None in every branch (the gate's
    internal path always has a rate for still_learning, but the function is
    public — a defensive call must not raise).
    """
    for state, ev in [
        ("insufficient_data", "still_learning"),
        ("insufficient_data", "no_data"),
        ("annotated", "proven"),
        ("annotated", "suppressed"),
        ("gated", "proven"),
        ("suppressed", "suppressed"),
    ]:
        sizing = sizing_ladder(
            state=state, evidence_status=ev, hit_rate=None, hit_rate_floor=0.5
        )
        assert sizing["level"] in ("full", "half", "paper_only", "stand_aside")
        assert isinstance(sizing["multiplier"], float)


def test_gate_stamps_size_multiplier_on_alert(tmp_path: Path) -> None:
    """apply_stage3_gate stamps the empirical size multiplier and label on the
    alert so the risk layer and dashboard can consume them directly.
    """
    outcomes = tmp_path / "outcomes.jsonl"
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    # Gated scenario: calibrated + above-floor -> full size.
    rows = [
        _scored("R_75", "continuation_close", "target_hit")
        for _ in range(int(MIN_STAGE3_SAMPLES * GATE_HIT_RATE_FLOOR) + 1)
    ]
    rows += [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES - len(rows))]
    _write_outcomes(outcomes, rows)
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
    }
    applied = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert applied["size_multiplier"] == 1.0
    assert applied["position_sizing_empirical"] == "full"
    assert applied["stage3"]["sizing"]["level"] == "full"

    # No-data scenario: no verdict yet -> paper only (zero multiplier).
    empty = apply_stage3_gate(
        dict(snapshot), outcomes_path=tmp_path / "missing.jsonl", verdict_cache_path=verdicts
    )
    assert empty["size_multiplier"] == 0.0
    assert empty["position_sizing_empirical"] == "paper_only"


def test_suppression_mode_env_knob() -> None:
    """The operator-facing env knob resolves to a valid mode with fallback."""
    with patch.dict(os.environ, {"SYNTH_GATE_SUPPRESSION_MODE": "annotate"}):
        assert _env_mode() == "annotate"
    with patch.dict(os.environ, {"SYNTH_GATE_SUPPRESSION_MODE": "suppress"}):
        assert _env_mode() == "suppress"
    with patch.dict(os.environ, {"SYNTH_GATE_SUPPRESSION_MODE": "bogus"}):
        assert _env_mode() == "suppress"  # invalid -> safe default
    with patch.dict(os.environ, {}, clear=False):
        assert _env_mode() == "suppress"  # unset -> default


def test_proven_only_env_knob() -> None:
    """SYNTH_GATE_PROVEN_ONLY resolves to a boolean with a safe default."""
    assert PROVEN_ONLY_MODE is False  # module default is off
    for raw in ("1", "true", "yes", "on", "TRUE"):
        with patch.dict(os.environ, {"SYNTH_GATE_PROVEN_ONLY": raw}):
            assert _env_bool("SYNTH_GATE_PROVEN_ONLY", False) is True
    for raw in ("0", "false", "no", "off", "", "bogus"):
        with patch.dict(os.environ, {"SYNTH_GATE_PROVEN_ONLY": raw}):
            assert _env_bool("SYNTH_GATE_PROVEN_ONLY", False) is False


def test_sizing_ladder_proven_only_forces_paper_only() -> None:
    """Proven-only mode: ANY evidence_status other than 'proven' is forced to
    paper-only (0.0) — the strictest belt, independent of the state machine.
    """
    # still_learning would otherwise be paper-only anyway — but now it is
    # forced with the explicit proven_only basis (never full/half).
    still_learning = sizing_ladder(
        state="insufficient_data", evidence_status="still_learning",
        hit_rate=0.6, hit_rate_floor=0.5, proven_only=True,
    )
    assert still_learning["level"] == "paper_only"
    assert still_learning["multiplier"] == 0.0
    assert still_learning["basis"] == "proven_only"

    # suppressed: stand_aside normally — proven_only forces paper_only.
    suppressed = sizing_ladder(
        state="suppressed", evidence_status="suppressed",
        hit_rate=0.2, hit_rate_floor=0.5, proven_only=True,
    )
    assert suppressed["level"] == "paper_only"
    assert suppressed["multiplier"] == 0.0

    no_data = sizing_ladder(
        state="insufficient_data", evidence_status="no_data",
        hit_rate=None, hit_rate_floor=0.5, proven_only=True,
    )
    assert no_data["level"] == "paper_only"
    assert no_data["multiplier"] == 0.0


def test_sizing_ladder_proven_only_keeps_proven_sizes() -> None:
    """Proven-only mode does NOT touch market-proven calls: gated stays full
    and annotated-above-floor stays half — only non-proven is forced down.
    """
    gated = sizing_ladder(
        state="gated", evidence_status="proven", hit_rate=0.62, hit_rate_floor=0.5,
        proven_only=True,
    )
    assert gated["level"] == "full"
    assert gated["multiplier"] == 1.0

    annotated = sizing_ladder(
        state="annotated", evidence_status="proven", hit_rate=0.62, hit_rate_floor=0.5,
        proven_only=True,
    )
    assert annotated["level"] == "half"
    assert annotated["multiplier"] == 0.5


def test_proven_only_gate_stamps_execution_allowed_false(tmp_path: Path) -> None:
    """With proven_only on, a still_learning call carries execution_allowed
    False + paper-only sizing on the alert; a proven call stays allowed.
    """
    outcomes = tmp_path / "outcomes.jsonl"
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "target_hit") for _ in range(3)],  # still learning
    )
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.65,
    }
    block = build_stage3_block(
        snapshot, outcomes_path=outcomes, verdict_cache_path=verdicts, proven_only=True
    )
    assert block["proven_only"] is True
    assert block["evidence_status"] == "still_learning"
    assert block["execution_allowed"] is False
    assert block["sizing"]["level"] == "paper_only"

    applied = apply_stage3_gate(
        dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts, proven_only=True
    )
    assert applied["execution_allowed"] is False
    assert applied["size_multiplier"] == 0.0
    assert applied["position_sizing_empirical"] == "paper_only"

    # Proven evidence (enough samples above the floor): execution stays on.
    rows = [
        _scored("R_75", "continuation_close", "target_hit")
        for _ in range(int(MIN_STAGE3_SAMPLES * GATE_HIT_RATE_FLOOR) + 1)
    ]
    rows += [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES - len(rows))]
    _write_outcomes(outcomes, rows)
    proven = apply_stage3_gate(
        dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts, proven_only=True
    )
    assert proven["stage3"]["evidence_status"] == "proven"
    assert proven["execution_allowed"] is True
    assert proven["size_multiplier"] == 1.0


def test_proven_only_overrides_annotate_escape_hatch(tmp_path: Path) -> None:
    """Proven-only is the strictest belt: even in annotate mode a below-floor
    call is forced paper-only (the annotate escape hatch is closed).
    """
    outcomes = tmp_path / "outcomes.jsonl"
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES)],
    )
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
    }
    block = build_stage3_block(
        snapshot,
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        suppression_mode="annotate",
        proven_only=True,
    )
    assert block["state"] == "annotated"  # still shown (annotate)
    assert block["evidence_status"] == "suppressed"  # truth axis unchanged
    assert block["execution_allowed"] is False  # but execution is CLOSED
    assert block["sizing"]["level"] == "paper_only"
    assert block["sizing"]["multiplier"] == 0.0

    applied = apply_stage3_gate(
        dict(snapshot),
        outcomes_path=outcomes,
        verdict_cache_path=verdicts,
        suppression_mode="annotate",
        proven_only=True,
    )
    # The call is still shown (annotate) — proven-only holds execution, not
    # visibility — but the submit path sees execution_allowed=False.
    assert applied["call"] == "buy_candidate"
    assert applied["execution_allowed"] is False
    assert applied["size_multiplier"] == 0.0


def test_gate_backtest_proven_only_marks_paper_only(tmp_path: Path) -> None:
    """backtest-gate --proven-only marks non-proven calls paper_only so the
    held-vs-executed verdict measures the strict belt.
    """
    from synthetic_trader.research.gate_backtest import (
        CallRecord,
        simulate_gate_walk_forward,
    )

    calls = [
        CallRecord(
            generated_at_epoch=1000.0 + i * 4000.0,
            record={
                "symbol": "R_75",
                "hold_horizon_minutes": 60,
                "trade_status": "valid",
                "entry": 100.0,
                "execution_stop": 99.0,
                "primary_target": 103.0,
            },
            trigger_type="continuation_close",
        )
        for i in range(4)
    ]
    # All outcomes resolve to target hits (above floor) — but only the LAST
    # call has enough PRIOR evidence to be proven; the first is no_data.
    for i in range(3):
        calls[i].outcome_label = "target_hit"

    simulate_gate_walk_forward(
        calls=calls,
        min_samples=10,
        hit_rate_floor=0.5,
        suppression_mode="suppress",
        proven_only=True,
    )
    # The first call had zero prior outcomes -> no_data -> paper_only.
    assert calls[0].gate_state == "paper_only"
    assert calls[0].evidence_status == "no_data"
    # None accumulated enough prior samples to be proven here (min 10) —
    # everything stays paper-only under the strict belt.
    assert all(c.gate_state == "paper_only" for c in calls[1:])

    # Without proven_only the same calls keep the plain gate states.
    for call in calls:
        call.gate_state = None
    simulate_gate_walk_forward(
        calls=calls,
        min_samples=10,
        hit_rate_floor=0.5,
        suppression_mode="suppress",
        proven_only=False,
    )
    assert calls[0].gate_state == "insufficient_data"
    assert calls[0].evidence_status == "no_data"


def test_gate_clears_stale_suppressed_reason_on_reuse(tmp_path: Path) -> None:
    """A snapshot re-gated after the journal improves must not keep a stale
    suppression reason from an earlier suppressed pass.
    """
    outcomes = tmp_path / "outcomes.jsonl"
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.6,
        "suppressed_reason": "stale reason from a previous pass",
    }
    # First pass: below-floor evidence -> suppressed (reason kept).
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES)],
    )
    applied = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert applied["call"] == "stand_aside"
    assert applied.get("suppressed_reason")
    # Second pass on the same snapshot: the journal now clears the floor.
    rows = [
        _scored("R_75", "continuation_close", "target_hit")
        for _ in range(int(MIN_STAGE3_SAMPLES * GATE_HIT_RATE_FLOOR) + 1)
    ]
    rows += [_scored("R_75", "continuation_close", "stop_hit") for _ in range(MIN_STAGE3_SAMPLES - len(rows))]
    _write_outcomes(outcomes, rows)
    reapplied = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert reapplied["call"] == "buy_candidate"
    assert reapplied["stage3"]["below_floor"] is False
    assert "suppressed_reason" not in reapplied


def test_gate_block_carries_suppression_mode_default(tmp_path: Path) -> None:
    """The block always records which mode produced the decision."""
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "target_hit")],
    )
    snapshot = {"symbol": "R_75", "execution_trigger_type": "continuation_close", "confidence": 0.71}
    block = build_stage3_block(snapshot, outcomes_path=outcomes)
    assert block["suppression_mode"] in ("suppress", "annotate")
    # Invalid overrides fall back to the module default rather than raising.
    block2 = build_stage3_block(
        snapshot, outcomes_path=outcomes, suppression_mode="nonsense"
    )
    assert block2["suppression_mode"] in ("suppress", "annotate")


def test_gate_annotated_when_horizon_uncalibrated_but_rate_clears(tmp_path: Path) -> None:
    """Rate clears the floor but the horizon verdict is not calibrated ->
    annotated (evidence is positive, but the horizon bar is missing).
    """
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [
            _scored("R_75", "continuation_close", "target_hit")
            for _ in range(MIN_STAGE3_SAMPLES)
        ],
    )
    verdicts = _verdicts_file(tmp_path / "forecast_verdicts.jsonl", calibrated=False)
    snapshot = {"symbol": "R_75", "execution_trigger_type": "continuation_close", "confidence": 0.6}
    block = build_stage3_block(snapshot, outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert block["state"] == "annotated"
    assert block["evidence_status"] == "proven"
    assert block["empirical_target_hit_rate"] == 1.0
    assert "horizon verdict not calibrated" in block["note"]


def test_gate_evidence_status_still_learning(tmp_path: Path) -> None:
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "target_hit") for _ in range(3)],
    )
    snapshot = {"symbol": "R_75", "execution_trigger_type": "continuation_close", "confidence": 0.71}
    block = build_stage3_block(snapshot, outcomes_path=outcomes)
    assert block["state"] == "insufficient_data"
    assert block["evidence_status"] == "still_learning"
    assert block["empirical_sample_count"] == 3
    assert block["min_samples"] == MIN_STAGE3_SAMPLES
    assert block["display_confidence"] == 0.71  # model confidence kept


def test_gate_evidence_status_no_data(tmp_path: Path) -> None:
    snapshot = {"symbol": "R_75", "execution_trigger_type": "continuation_close", "confidence": 0.5}
    block = build_stage3_block(
        snapshot, outcomes_path=tmp_path / "missing.jsonl"
    )
    assert block["state"] == "insufficient_data"
    assert block["evidence_status"] == "no_data"


def test_gate_configurable_thresholds_override(tmp_path: Path) -> None:
    """Per-call min_samples / hit_rate_floor must override the module defaults."""
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "stop_hit") for _ in range(5)],
    )
    snapshot = {"symbol": "R_75", "execution_trigger_type": "continuation_close", "confidence": 0.6}
    # With a floor of 0.5 and min_samples of 5: 5 samples, 0% hit rate -> suppressed.
    block = build_stage3_block(
        snapshot,
        outcomes_path=outcomes,
        min_samples=5,
        hit_rate_floor=0.5,
    )
    assert block["state"] == "suppressed"
    assert block["min_samples"] == 5
    assert block["hit_rate_floor"] == 0.5
    # With min_samples=20 the same evidence is still learning.
    block2 = build_stage3_block(
        snapshot,
        outcomes_path=outcomes,
        min_samples=20,
        hit_rate_floor=0.5,
    )
    assert block2["state"] == "insufficient_data"
    assert block2["evidence_status"] == "still_learning"


def test_resolve_trigger_type_prefers_execution_trigger() -> None:
    assert resolve_trigger_type({"execution_trigger_type": "continuation_close", "alert_type": "setup_candidate"}) == "continuation_close"
    assert resolve_trigger_type({"alert_type": "context_update"}) == "context_update"
    assert resolve_trigger_type({}) == "unknown"


def test_apply_stage3_gate_best_effort_on_bad_symbol(tmp_path: Path) -> None:
    snapshot = {"confidence": 0.5}  # no symbol
    applied = apply_stage3_gate(dict(snapshot), outcomes_path=tmp_path / "x.jsonl")
    assert applied["stage3"]["state"] == "insufficient_data"
    assert applied["confidence"] == 0.5


def _rich_verdicts_file(path: Path) -> Path:
    """Verdict cache in the CURRENT shape (written by get_horizon_forecast_stats):
    per-horizon tuned multipliers + live forecast bands.
    """
    horizon = {
        "verdict": "calibrated",
        "windows": 42,
        "coverage_p50": 0.51,
        "coverage_p90": 0.9,
        "p50_mult": 1.52,
        "p90_mult": 2.44,
        "forecast": {
            "current_close": 51240.1,
            "range_p50_price": 310.5,
            "range_p90_price": 820.0,
            "expected_low_p50": 51090.0,
            "expected_high_p50": 51400.0,
            "expected_low_p90": 50820.0,
            "expected_high_p90": 51660.0,
            "projected_sigma_avg": 0.0041,
            "confidence": 0.8,
            "vol_trend": "stable",
        },
    }
    path.write_text(
        json.dumps({"R_75": {"4h": horizon, "6h": dict(horizon)}}) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_horizon_verdict_carries_tuned_multipliers_and_bands(tmp_path: Path) -> None:
    """The rich cache (written after tune-bands) exposes the tuned 60s p50/p90
    multipliers AND the live band numbers, not just the verdict label.
    """
    path = _rich_verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    result = load_horizon_verdict(symbol="R_75", verdict_cache_path=path)
    assert result["verdict"] == "calibrated"
    assert result["p50_mult"] == 1.52
    assert result["p90_mult"] == 2.44
    four_h = result["horizons"]["4h"]
    assert four_h["verdict"] == "calibrated"
    assert four_h["p50_mult"] == 1.52
    assert four_h["p90_mult"] == 2.44
    assert four_h["forecast"]["range_p50_price"] == 310.5
    assert four_h["forecast"]["expected_high_p90"] == 51660.0
    assert result["horizons"]["6h"]["forecast"]["vol_trend"] == "stable"


def test_gate_payload_carries_calibrated_multipliers(tmp_path: Path) -> None:
    """apply_stage3_gate attaches the tuned multipliers + live bands to the
    operator-facing call payload (stage3.horizon_forecast / stage3.p50_mult).
    """
    outcomes = tmp_path / "outcomes.jsonl"
    _write_outcomes(
        outcomes,
        [_scored("R_75", "continuation_close", "target_hit") for _ in range(MIN_STAGE3_SAMPLES)],
    )
    verdicts = _rich_verdicts_file(tmp_path / "forecast_verdicts.jsonl")
    snapshot = {
        "symbol": "R_75",
        "call": "buy_candidate",
        "execution_trigger_type": "continuation_close",
        "confidence": 0.65,
    }
    block = build_stage3_block(snapshot, outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert block["state"] == "gated"
    assert block["p50_mult"] == 1.52
    assert block["p90_mult"] == 2.44
    assert block["horizon_forecast"]["4h"]["forecast"]["range_p90_price"] == 820.0

    applied = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=verdicts)
    assert applied["stage3"]["p50_mult"] == 1.52
    assert applied["stage3"]["p90_mult"] == 2.44
    assert applied["stage3"]["horizon_forecast"]["4h"]["forecast"]["current_close"] == 51240.1
    # Legacy-shaped cache (no multipliers/bands) still works — verdicts
    # surface, multipliers/bands degrade to absent.
    legacy = _verdicts_file(tmp_path / "legacy_verdicts.jsonl")
    applied_legacy = apply_stage3_gate(dict(snapshot), outcomes_path=outcomes, verdict_cache_path=legacy)
    assert applied_legacy["stage3"]["p50_mult"] is None
    assert applied_legacy["stage3"]["p90_mult"] is None
    assert applied_legacy["stage3"]["horizon_forecast"]["4h"]["verdict"] == "calibrated"
    assert "p50_mult" not in applied_legacy["stage3"]["horizon_forecast"]["4h"]
    assert "forecast" not in applied_legacy["stage3"]["horizon_forecast"]["4h"]


def test_verdict_cache_round_trip_persists_multipliers(tmp_path: Path) -> None:
    """End-to-end: the stats writer (_persist_verdict_cache — the tail of the
    tune-bands path) persists the multipliers + bands, and the gate's reader
    (load_horizon_verdict) returns exactly what was written.
    """
    from synthetic_trader.scripts.horizon_forecast_stats import _persist_verdict_cache

    engine_root = tmp_path / "engine"
    stats: dict[str, object] = {
        "R_75": {
            "symbol": "R_75",
            "timeframe_sec": 60,
            "tick_csv": "data/backfill/R_75_ticks.csv",
            "ticks": 40320,
            "garch_calibrated": True,
            "error": None,
            "horizons": {
                "4h": {
                    "horizon_sec": 14400,
                    "verdict": "calibrated",
                    "multipliers_applied": True,
                    "p50_mult": 1.48,
                    "p90_mult": 2.37,
                    "validation": {"windows": 41, "coverage_p50": 0.49, "coverage_p90": 0.91},
                    "forecast": {
                        "current_close": 7481.2,
                        "range_p50_price": 45.3,
                        "range_p90_price": 118.9,
                        "expected_low_p50": 7458.0,
                        "expected_high_p50": 7505.0,
                        "expected_low_p90": 7421.0,
                        "expected_high_p90": 7541.0,
                        "projected_sigma_avg": 0.0039,
                        "confidence": 0.82,
                        "vol_trend": "falling",
                    },
                },
                "6h": {
                    "horizon_sec": 21600,
                    "verdict": "calibrated",
                    "multipliers_applied": True,
                    "p50_mult": 1.51,
                    "p90_mult": 2.41,
                    "validation": {"windows": 39, "coverage_p50": 0.5, "coverage_p90": 0.9},
                    "forecast": {
                        "current_close": 7481.2,
                        "range_p50_price": 55.1,
                        "range_p90_price": 144.2,
                        "expected_low_p50": 7453.0,
                        "expected_high_p50": 7509.0,
                        "expected_low_p90": 7409.0,
                        "expected_high_p90": 7553.0,
                        "projected_sigma_avg": 0.0039,
                        "confidence": 0.82,
                        "vol_trend": "falling",
                    },
                },
            },
        }
    }
    _persist_verdict_cache(engine_root, stats)

    cache_path = engine_root / "data" / "forecast_verdicts.json"
    assert cache_path.exists()
    result = load_horizon_verdict(symbol="R_75", verdict_cache_path=cache_path)
    assert result["verdict"] == "calibrated"
    # Overall multipliers resolve to the 4h values.
    assert result["p50_mult"] == 1.48
    assert result["p90_mult"] == 2.37
    # Both horizons carry their own tuned multipliers + live band numbers.
    assert result["horizons"]["4h"]["p50_mult"] == 1.48
    assert result["horizons"]["4h"]["forecast"]["range_p90_price"] == 118.9
    assert result["horizons"]["6h"]["p90_mult"] == 2.41
    assert result["horizons"]["6h"]["forecast"]["expected_high_p90"] == 7553.0
    assert result["horizons"]["6h"]["forecast"]["vol_trend"] == "falling"
