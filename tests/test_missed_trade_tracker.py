"""Comprehensive tests for MissedTradeTracker.

Covers:
  - Recording: basic record, guard clauses (None price, None prob, zero ATR)
  - Deduplication: 5-minute cooldown per symbol
  - Resolution: time-window elapsed, price lookup, outcome evaluation
  - Calibration feedback math: long-lean vs short-lean prediction transform
  - Persistence: load/save pending records, outcomes file
  - Edge cases: empty price lookup, exception handling, summary introspection
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from synthetic_trader.live.missed_trade_tracker import (
    MissedTradeTracker,
    MissedTradeRecord,
    ResolutionResult,
    RESOLUTION_COOLDOWN_SEC,
    DEFAULT_RESOLUTION_MINUTES,
    MIN_ATR_MOVE_THRESHOLD,
)


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory for tracker files."""
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def tracker(tmp_data_dir: Path) -> MissedTradeTracker:
    """Create a tracker with a short resolution window for fast tests."""
    return MissedTradeTracker(
        missed_trades_path=tmp_data_dir / "missed_trades.jsonl",
        resolution_minutes=1,  # 1 minute for fast resolution
        min_atr_threshold=1.0,
    )


@pytest.fixture
def tracker_no_file() -> MissedTradeTracker:
    """Create a tracker that doesn't touch the filesystem."""
    return MissedTradeTracker(
        missed_trades_path=Path("/nonexistent/path/missed_trades.jsonl"),
        resolution_minutes=1,
        min_atr_threshold=1.0,
    )


# ── Recording Tests ──────────────────────────────────────────────


class TestRecording:
    def test_record_basic(self, tracker_no_file: MissedTradeTracker) -> None:
        """Basic record should add to pending list."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 1

    def test_record_stores_all_fields(self, tracker_no_file: MissedTradeTracker) -> None:
        """Recorded data should preserve all input fields."""
        tracker_no_file.record(
            symbol="R_75",
            model_long_probability=0.65,
            confidence=0.55,
            regime="trend_up",
            atr_14=2.3,
            current_price=1600.0,
            direction_bias="buy",
            features_summary={"hurst": 0.7, "entropy": 0.3},
        )
        record = tracker_no_file._pending[-1]
        assert record.symbol == "R_75"
        assert record.model_long_probability == 0.65
        assert record.confidence == 0.55
        assert record.regime == "trend_up"
        assert record.atr_14 == 2.3
        assert record.current_price == 1600.0
        assert record.direction_bias == "buy"
        assert record.features_summary == {"hurst": 0.7, "entropy": 0.3}
        assert record.resolved is False
        assert record.outcome is None

    def test_record_guard_none_probability(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should not record when model_long_probability is None."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=None,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 0

    def test_record_guard_none_price(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should not record when current_price is None."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=0,  # type: ignore[arg-type]
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 0

    def test_record_guard_negative_price(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should not record when current_price is negative."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=-100.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 0

    def test_record_guard_zero_atr(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should not record when atr_14 is zero or negative."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=0.0,
            current_price=256.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 0

    def test_record_multiple_symbols(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should be able to record multiple symbols."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        tracker_no_file.record(
            symbol="R_75",
            model_long_probability=0.58,
            confidence=0.45,
            regime="trend_up",
            atr_14=2.3,
            current_price=1600.0,
            direction_bias="buy",
        )
        assert tracker_no_file.pending_count == 2

    def test_record_custom_resolution_window(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should respect custom resolution_minutes parameter."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
            resolution_minutes=30,
        )
        record = tracker_no_file._pending[-1]
        assert record.resolution_window_sec == 30 * 60


# ── Deduplication Tests ──────────────────────────────────────────


class TestDeduplication:
    def test_dedup_same_symbol_within_5min(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should not record a second entry for the same symbol within 5 minutes."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        # Record again immediately
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.44,
            confidence=0.40,
            regime="range",
            atr_14=1.5,
            current_price=257.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 1  # deduplicated

    def test_no_dedup_different_symbols(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should NOT deduplicate across different symbols."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        tracker_no_file.record(
            symbol="R_75",
            model_long_probability=0.58,
            confidence=0.45,
            regime="trend_up",
            atr_14=2.3,
            current_price=1600.0,
            direction_bias="buy",
        )
        assert tracker_no_file.pending_count == 2

    def test_no_dedup_after_5min(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should NOT deduplicate if the previous record is older than 5 minutes."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        # Simulate 5+ minutes passing
        tracker_no_file._pending[0].recorded_at = time.time() - 301

        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.44,
            confidence=0.40,
            regime="range",
            atr_14=1.5,
            current_price=257.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 2

    def test_no_dedup_resolved_record(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should NOT deduplicate against a resolved record."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        # Mark as resolved
        tracker_no_file._pending[0].resolved = True

        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.44,
            confidence=0.40,
            regime="range",
            atr_14=1.5,
            current_price=257.0,
            direction_bias="none",
        )
        assert tracker_no_file.pending_count == 1  # only the new one (resolved not counted)


# ── Resolution Tests ─────────────────────────────────────────────


class TestResolution:
    def test_resolve_no_pending(self, tracker: MissedTradeTracker) -> None:
        """Resolve with no pending records should return empty result."""
        result = tracker.resolve(
            price_lookup=lambda sym: [],
            update_calibration=None,
        )
        assert result.resolved_count == 0

    def test_resolve_before_window_elapses(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should not resolve records before their window elapses."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        # Don't wait — resolve immediately
        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [(time.time(), 260.0)],
            update_calibration=None,
        )
        assert result.resolved_count == 0
        assert tracker_no_file.pending_count == 1

    def test_resolve_after_window_missed_opportunity(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should resolve as missed opportunity when price moves >= 1 ATR in predicted direction."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.60,  # leaning long
            confidence=0.45,
            regime="trend_up",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        recorded_at = now - 120  # 2 minutes ago (window is 1 min)
        tracker_no_file._pending[0].recorded_at = recorded_at
        window_end = recorded_at + 60  # resolution_window_sec = 60

        # Price moved up by 2 ATR (3.0 points) — all prices must be within window
        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [
                (recorded_at + 10, 256.5),
                (recorded_at + 30, 258.0),
                (recorded_at + 55, 259.0),
            ],
            update_calibration=None,
        )
        assert result.resolved_count == 1
        assert result.missed_opportunities == 1
        assert result.correct_stayouts == 0
        assert tracker_no_file.pending_count == 0

    def test_resolve_after_window_correct_stayout(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should resolve as correct stay-out when price doesn't move enough."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.60,  # leaning long
            confidence=0.45,
            regime="trend_up",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        recorded_at = now - 120
        tracker_no_file._pending[0].recorded_at = recorded_at

        # Price only moved up by 0.5 ATR (0.75 points) — not enough, all within window
        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [
                (recorded_at + 10, 256.3),
                (recorded_at + 30, 256.5),
                (recorded_at + 55, 256.75),
            ],
            update_calibration=None,
        )
        assert result.resolved_count == 1
        assert result.correct_stayouts == 1
        assert result.missed_opportunities == 0

    def test_resolve_empty_price_lookup(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should count as failed resolution when price_lookup returns empty."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.60,
            confidence=0.45,
            regime="trend_up",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        tracker_no_file._pending[0].recorded_at = now - 120

        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [],
            update_calibration=None,
        )
        assert result.failed_resolutions == 1
        assert result.resolved_count == 0

    def test_resolve_short_lean(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should correctly evaluate short-lean predictions (prob < 0.5)."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.35,  # leaning short
            confidence=0.45,
            regime="trend_down",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="sell",
        )
        recorded_at = now - 120
        tracker_no_file._pending[0].recorded_at = recorded_at

        # Price moved down by 2 ATR — missed short opportunity, all within window
        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [
                (recorded_at + 10, 255.5),
                (recorded_at + 30, 254.0),
                (recorded_at + 55, 253.0),
            ],
            update_calibration=None,
        )
        assert result.resolved_count == 1
        assert result.missed_opportunities == 1

    def test_resolve_neutral_lean(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should correctly evaluate neutral predictions (prob == 0.5)."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.50,  # neutral
            confidence=0.45,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        recorded_at = now - 120
        tracker_no_file._pending[0].recorded_at = recorded_at

        # Price moved up by 2 ATR — all within window
        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [
                (recorded_at + 10, 256.5),
                (recorded_at + 30, 258.0),
                (recorded_at + 55, 259.0),
            ],
            update_calibration=None,
        )
        assert result.resolved_count == 1
        # With prob == 0.5, model_lean_long is False, so it checks down-move
        # Since price went UP, not down, it's a correct stay-out
        assert result.correct_stayouts == 1


# ── Calibration Feedback Math Tests ──────────────────────────────


class TestCalibrationFeedback:
    def test_calibration_long_lean(self, tracker_no_file: MissedTradeTracker) -> None:
        """When model leaned long, prediction should be model_long_probability."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.65,
            confidence=0.50,
            regime="trend_up",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        recorded_at = now - 120
        tracker_no_file._pending[0].recorded_at = recorded_at

        cal_calls: list[tuple[float, int]] = []
        tracker_no_file.resolve(
            price_lookup=lambda sym: [(recorded_at + 30, 259.0)],  # 2 ATR up, within window
            update_calibration=lambda pred, outcome: cal_calls.append((pred, outcome)),
        )
        assert len(cal_calls) == 1
        pred, outcome = cal_calls[0]
        assert pred == pytest.approx(0.65, abs=0.001)
        assert outcome == 1  # missed opportunity

    def test_calibration_short_lean(self, tracker_no_file: MissedTradeTracker) -> None:
        """When model leaned short, prediction should be 1 - model_long_probability."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.35,
            confidence=0.50,
            regime="trend_down",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="sell",
        )
        recorded_at = now - 120
        tracker_no_file._pending[0].recorded_at = recorded_at

        cal_calls: list[tuple[float, int]] = []
        tracker_no_file.resolve(
            price_lookup=lambda sym: [(recorded_at + 30, 253.0)],  # 2 ATR down, within window
            update_calibration=lambda pred, outcome: cal_calls.append((pred, outcome)),
        )
        assert len(cal_calls) == 1
        pred, outcome = cal_calls[0]
        assert pred == pytest.approx(0.65, abs=0.001)  # 1 - 0.35 = 0.65
        assert outcome == 1  # missed opportunity

    def test_calibration_stayout_outcome(self, tracker_no_file: MissedTradeTracker) -> None:
        """When price didn't move enough, outcome should be 0."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.60,
            confidence=0.50,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        recorded_at = now - 120
        tracker_no_file._pending[0].recorded_at = recorded_at

        cal_calls: list[tuple[float, int]] = []
        tracker_no_file.resolve(
            price_lookup=lambda sym: [(recorded_at + 30, 256.5)],  # only 0.33 ATR up, within window
            update_calibration=lambda pred, outcome: cal_calls.append((pred, outcome)),
        )
        assert len(cal_calls) == 1
        pred, outcome = cal_calls[0]
        assert pred == pytest.approx(0.60, abs=0.001)
        assert outcome == 0  # correctly stayed out


# ── Persistence Tests ────────────────────────────────────────────


class TestPersistence:
    def test_persist_and_reload(self, tmp_data_dir: Path) -> None:
        """Should persist pending records and reload them on new tracker."""
        path = tmp_data_dir / "missed_trades.jsonl"
        tracker1 = MissedTradeTracker(
            missed_trades_path=path,
            resolution_minutes=60,
            min_atr_threshold=1.0,
        )
        tracker1.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        # Force persist
        tracker1._persist_pending()

        # Create new tracker from same file
        tracker2 = MissedTradeTracker(
            missed_trades_path=path,
            resolution_minutes=60,
            min_atr_threshold=1.0,
        )
        assert tracker2.pending_count == 1
        record = tracker2._pending[0]
        assert record.symbol == "R_100"
        assert record.model_long_probability == 0.42

    def test_persist_empty_does_not_create_file(self, tmp_data_dir: Path) -> None:
        """Should not create a file when there are no pending records."""
        path = tmp_data_dir / "missed_trades.jsonl"
        tracker = MissedTradeTracker(
            missed_trades_path=path,
            resolution_minutes=60,
            min_atr_threshold=1.0,
        )
        tracker._persist_pending()
        assert not path.exists()

    def test_outcomes_appended(self, tmp_data_dir: Path) -> None:
        """Resolved records should be appended to the outcomes file."""
        path = tmp_data_dir / "missed_trades.jsonl"
        tracker = MissedTradeTracker(
            missed_trades_path=path,
            resolution_minutes=1,
            min_atr_threshold=1.0,
        )
        now = time.time()
        tracker.record(
            symbol="R_100",
            model_long_probability=0.60,
            confidence=0.50,
            regime="trend_up",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        recorded_at = now - 120
        tracker._pending[0].recorded_at = recorded_at

        tracker.resolve(
            price_lookup=lambda sym: [(recorded_at + 30, 259.0)],  # within window
            update_calibration=None,
        )

        outcomes_path = tmp_data_dir / "missed_trade_outcomes.jsonl"
        assert outcomes_path.exists()
        lines = outcomes_path.read_text().strip().splitlines()
        assert len(lines) == 1
        outcome = json.loads(lines[0])
        assert outcome["symbol"] == "R_100"
        assert outcome["outcome"] == 1

    def test_load_skips_expired_records(self, tmp_data_dir: Path) -> None:
        """Should not load records whose resolution window has already elapsed."""
        path = tmp_data_dir / "missed_trades.jsonl"
        # Write an expired record directly
        expired_record = {
            "symbol": "R_100",
            "recorded_at": time.time() - 7200,  # 2 hours ago
            "resolution_window_sec": 3600,  # 1 hour window
            "current_price": 256.0,
            "model_long_probability": 0.42,
            "confidence": 0.38,
            "regime": "range",
            "atr_14": 1.5,
            "direction_bias": "none",
            "features_summary": {},
        }
        with path.open("w") as f:
            f.write(json.dumps(expired_record) + "\n")

        tracker = MissedTradeTracker(
            missed_trades_path=path,
            resolution_minutes=60,
            min_atr_threshold=1.0,
        )
        # The expired record should NOT be loaded (window elapsed)
        # Actually, looking at the code, it loads records where (now - recorded_at) < window_sec
        # For an expired record, this is False, so it won't be loaded
        # But we need to check what actually happens...
        # The code says: if (now - recorded_at) < window_sec: load it
        # So expired records (elapsed > window) are NOT loaded
        assert tracker.pending_count == 0

    def test_load_skips_resolved_records(self, tmp_data_dir: Path) -> None:
        """Should not load already-resolved records."""
        path = tmp_data_dir / "missed_trades.jsonl"
        resolved_record = {
            "symbol": "R_100",
            "recorded_at": time.time() - 60,
            "resolution_window_sec": 3600,
            "current_price": 256.0,
            "model_long_probability": 0.42,
            "confidence": 0.38,
            "regime": "range",
            "atr_14": 1.5,
            "direction_bias": "none",
            "features_summary": {},
            "resolved": True,
        }
        with path.open("w") as f:
            f.write(json.dumps(resolved_record) + "\n")

        tracker = MissedTradeTracker(
            missed_trades_path=path,
            resolution_minutes=60,
            min_atr_threshold=1.0,
        )
        assert tracker.pending_count == 0


# ── Edge Case Tests ──────────────────────────────────────────────


class TestEdgeCases:
    def test_resolve_exception_handling(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should handle exceptions in price_lookup gracefully."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.60,
            confidence=0.50,
            regime="trend_up",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        tracker_no_file._pending[0].recorded_at = now - 120

        def bad_lookup(sym: str) -> list[tuple[float, float]]:
            raise RuntimeError("CSV read failed")

        result = tracker_no_file.resolve(
            price_lookup=bad_lookup,
            update_calibration=None,
        )
        assert result.failed_resolutions == 1
        assert result.resolved_count == 0

    def test_summary_empty(self, tracker_no_file: MissedTradeTracker) -> None:
        """Summary should return zero counts when no records exist."""
        summary = tracker_no_file.summary()
        assert summary["pending_count"] == 0
        assert summary["symbols"] == []
        assert summary["oldest_pending_age_sec"] == 0
        assert summary["newest_pending_age_sec"] == 0

    def test_summary_with_records(self, tracker_no_file: MissedTradeTracker) -> None:
        """Summary should reflect pending records."""
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.42,
            confidence=0.38,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="none",
        )
        tracker_no_file.record(
            symbol="R_75",
            model_long_probability=0.58,
            confidence=0.45,
            regime="trend_up",
            atr_14=2.3,
            current_price=1600.0,
            direction_bias="buy",
        )
        summary = tracker_no_file.summary()
        assert summary["pending_count"] == 2
        assert set(summary["symbols"]) == {"R_100", "R_75"}

    def test_evaluate_outcome_no_window_prices(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should return (0, 0.0) when no prices fall within the resolution window."""
        now = time.time()
        record = MissedTradeRecord(
            symbol="R_100",
            recorded_at=now,
            resolution_window_sec=60,
            current_price=256.0,
            model_long_probability=0.60,
            confidence=0.50,
            regime="range",
            atr_14=1.5,
            direction_bias="buy",
        )
        # Prices all outside the window
        prices = [(now - 200, 250.0), (now - 150, 251.0)]
        outcome, move = tracker_no_file._evaluate_outcome(record, prices)
        assert outcome == 0
        assert move == 0.0

    def test_evaluate_outcome_atr_threshold_boundary(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should return missed opportunity exactly at the ATR threshold."""
        now = time.time()
        record = MissedTradeRecord(
            symbol="R_100",
            recorded_at=now,
            resolution_window_sec=60,
            current_price=256.0,
            model_long_probability=0.60,
            confidence=0.50,
            regime="range",
            atr_14=1.5,
            direction_bias="buy",
        )
        # Price moved exactly 1 ATR up
        prices = [(now, 256.0 + 1.5)]
        outcome, move = tracker_no_file._evaluate_outcome(record, prices)
        assert outcome == 1
        assert move == pytest.approx(1.0, abs=0.01)

    def test_multiple_resolutions(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should resolve multiple records in one call."""
        now = time.time()
        recorded_at = now - 120
        symbols = ["R_100", "R_75", "R_50"]
        for i, sym in enumerate(symbols):
            tracker_no_file.record(
                symbol=sym,
                model_long_probability=0.60,
                confidence=0.50,
                regime="range",
                atr_14=1.5,
                current_price=256.0 + i,
                direction_bias="buy",
            )
            tracker_no_file._pending[-1].recorded_at = recorded_at

        result = tracker_no_file.resolve(
            price_lookup=lambda sym: [(recorded_at + 30, 260.0)],  # within window
            update_calibration=None,
        )
        assert result.resolved_count == 3

    def test_resolution_cooldown(self, tracker_no_file: MissedTradeTracker) -> None:
        """Should skip resolution if called too frequently."""
        now = time.time()
        tracker_no_file.record(
            symbol="R_100",
            model_long_probability=0.60,
            confidence=0.50,
            regime="range",
            atr_14=1.5,
            current_price=256.0,
            direction_bias="buy",
        )
        tracker_no_file._pending[0].recorded_at = now - 120

        # First resolve should work
        result1 = tracker_no_file.resolve(
            price_lookup=lambda sym: [(now, 260.0)],
            update_calibration=None,
        )
        assert result1.resolved_count == 1

        # Record another and try to resolve immediately — should be blocked by cooldown
        tracker_no_file.record(
            symbol="R_75",
            model_long_probability=0.55,
            confidence=0.45,
            regime="range",
            atr_14=2.0,
            current_price=1600.0,
            direction_bias="buy",
        )
        tracker_no_file._pending[0].recorded_at = now - 120

        result2 = tracker_no_file.resolve(
            price_lookup=lambda sym: [(now, 1610.0)],
            update_calibration=None,
        )
        assert result2.resolved_count == 0  # blocked by cooldown
