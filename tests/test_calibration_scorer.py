from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from synthetic_trader.domain import Tick
from synthetic_trader.live.calibration_scorer import (
    fetch_prices_for_record,
    score_call_outcome,
    score_unresolved_records,
    score_unresolved_records_from_market,
    summarize_outcomes,
)


class FakeTickClient:
    def __init__(self, ticks: list[Tick]) -> None:
        self.ticks = ticks
        self.requests: list[dict[str, object]] = []

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]:
        self.requests.append(
            {
                "symbol": symbol,
                "count": count,
                "start": start,
                "end": end,
            }
        )
        return self.ticks


class FakeScoringClient:
    def __init__(self, batches: list[list[Tick] | Exception]) -> None:
        self.batches = batches
        self.calls = 0

    async def __aenter__(self) -> "FakeScoringClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]:
        batch = self.batches[self.calls]
        self.calls += 1
        if isinstance(batch, Exception):
            raise batch
        return batch


def test_fetch_prices_for_record_requests_generated_window_and_filters_ticks() -> None:
    record = {
        "symbol": "R_100",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
    }
    client = FakeTickClient(
        [
            Tick(symbol="R_100", epoch=1783850390.0, price=479.9),
            Tick(symbol="R_100", epoch=1783850400.0, price=480.1),
            Tick(symbol="R_100", epoch=1783852200.0, price=482.2),
            Tick(symbol="R_100", epoch=1783854000.0, price=483.4),
            Tick(symbol="R_100", epoch=1783854065.0, price=484.0),
        ]
    )

    prices = asyncio.run(fetch_prices_for_record(record=record, client=client))

    # (price, epoch) pairs — the scorer needs the timestamps to bucket ticks
    # into closed execution-timeframe candles for the stop-lock grace.
    assert prices == [
        (480.1, 1783850400.0),
        (482.2, 1783852200.0),
        (483.4, 1783854000.0),
    ]
    assert client.requests == [
        {
            "symbol": "R_100",
            "count": 5000,
            "start": 1783850400,
            "end": 1783854000,
        }
    ]


def test_score_call_outcome_returns_target_hit_when_primary_target_is_reached_first() -> None:
    prices = [100.0, 101.0, 102.5, 103.0]
    record = {
        "symbol": "R_100",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 102.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "target_hit"


def test_score_call_outcome_returns_stop_hit_when_execution_stop_is_reached_first() -> None:
    prices = [100.0, 99.4, 98.0, 97.5]
    record = {
        "symbol": "R_75",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 103.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "stop_hit"


def test_score_call_outcome_returns_rejected_but_price_ran_for_forming_call_that_would_have_moved() -> None:
    prices = [100.0, 100.8, 101.6, 102.2]
    record = {
        "symbol": "R_75",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": None,
        "execution_stop": None,
        "primary_target": None,
        "trade_status": "not_valid",
        "guardian_state": "forming",
        "current_close": 100.0,
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "rejected_but_price_ran"


def test_summarize_outcomes_groups_by_symbol_trigger_type_and_trade_status() -> None:
    outcomes = [
        {
            "symbol": "R_75",
            "trigger_type": "continuation_close",
            "trade_status": "valid",
            "outcome_label": "target_hit",
            "entry": 100.0,
            "execution_stop": 98.0,
            "primary_target": 102.0,
            "max_favorable_excursion": 120.0,
            "max_adverse_excursion": 30.0,
        },
        {
            "symbol": "R_75",
            "trigger_type": "continuation_close",
            "trade_status": "valid",
            "outcome_label": "stop_hit",
            "entry": 100.0,
            "execution_stop": 98.0,
            "primary_target": 102.0,
            "max_favorable_excursion": 40.0,
            "max_adverse_excursion": 90.0,
        },
        {
            "symbol": "R_100",
            "trigger_type": "reclaim_pullback",
            "trade_status": "valid",
            "outcome_label": "target_hit",
            "entry": 300.0,
            "execution_stop": 297.0,
            "primary_target": 305.0,
            "max_favorable_excursion": 8.0,
            "max_adverse_excursion": 2.0,
        },
        {
            "symbol": "R_75",
            "trigger_type": "continuation_close",
            "trade_status": "not_valid",
            "outcome_label": "rejected_but_price_ran",
            # Deliberately level-less: the scorer only produces this label
            # when the call never carried levels, so it must not count.
            "max_favorable_excursion": 60.0,
            "max_adverse_excursion": 10.0,
        },
    ]

    summary = summarize_outcomes(outcomes)

    assert summary[("R_75", "continuation_close", "valid")]["count"] == 2
    assert summary[("R_75", "continuation_close", "valid")]["target_hit_rate"] == 0.5
    assert summary[("R_75", "continuation_close", "valid")]["stop_hit_rate"] == 0.5
    # Level-less rows are not measured trades and must not appear as evidence.
    assert ("R_75", "continuation_close", "not_valid") not in summary
    assert summary[("R_100", "reclaim_pullback", "valid")]["target_hit_rate"] == 1.0


def test_summarize_outcomes_excludes_deriv_fallback_rows_as_evidence() -> None:
    """Outcomes scored through the Deriv API fallback are on the wrong price
    scale (1HZ75V ~7,000 vs SYN75 ~1,542) and must never feed the gate, even
    when they carry levels."""
    outcomes = [
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
        {
            "symbol": "R_75",
            "trigger_type": "setup_candidate",
            "trade_status": "valid",
            "outcome_label": "target_hit",
            "entry": 100.0,
            "execution_stop": 98.0,
            "primary_target": 102.0,
            "scoring_source": "mt5",
        },
    ]

    summary = summarize_outcomes(outcomes)

    key = ("R_75", "setup_candidate", "valid")
    assert key in summary
    assert summary[key]["count"] == 1
    assert summary[key]["target_hit_rate"] == 1.0


def test_summarize_outcomes_excludes_level_less_rows_as_evidence() -> None:
    """Regression: stale level-less outcomes (no entry/stop/target) must never
    count as evidence -- they would suppress a real call type with fake 0%
    evidence (the July-12 journal poisoned setup_candidate this way)."""
    outcomes = [
        {
            "symbol": "R_75",
            "trigger_type": "setup_candidate",
            "trade_status": "valid",
            "outcome_label": "forming_remained_correct",
            "entry": None,
            "execution_stop": None,
            "primary_target": None,
        }
        for _ in range(45)
    ]
    outcomes.append(
        {
            "symbol": "R_75",
            "trigger_type": "setup_candidate",
            "trade_status": "valid",
            "outcome_label": "target_hit",
            "entry": 100.0,
            "execution_stop": 98.0,
            "primary_target": 102.0,
        }
    )

    summary = summarize_outcomes(outcomes)

    key = ("R_75", "setup_candidate", "valid")
    assert key in summary
    assert summary[key]["count"] == 1
    assert summary[key]["target_hit_rate"] == 1.0


def test_score_unresolved_records_appends_only_records_old_enough_for_evaluation(tmp_path: Path) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '{"symbol":"R_100","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":102.0,"trade_status":"valid"}\n'
        '{"symbol":"R_75","generated_at":"2099-01-01T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":102.0,"trade_status":"valid"}\n',
        encoding="utf-8",
    )

    written = score_unresolved_records(
        calls_path=calls_path,
        outcomes_path=outcomes_path,
        now=datetime(2026, 7, 12, 11, 5, tzinfo=timezone.utc),
        price_lookup=lambda record: [100.0, 101.0, 102.2],
    )

    assert written == 1


def test_score_unresolved_records_from_market_writes_target_hit_and_counts_skip_and_failure(
    tmp_path: Path,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        "\n".join(
            [
                '{"symbol":"R_100","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":102.0,"trade_status":"valid"}',
                '{"symbol":"R_75","generated_at":"2026-07-12T11:30:00+00:00","hold_horizon_minutes":60,"entry":500.0,"execution_stop":497.0,"primary_target":505.0,"trade_status":"valid"}',
                '{"symbol":"R_75","generated_at":"2026-07-12T10:10:00+00:00","hold_horizon_minutes":60,"entry":600.0,"execution_stop":597.0,"primary_target":604.0,"trade_status":"valid"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    client = FakeScoringClient(
        [
            [
                Tick(symbol="R_100", epoch=1783850400.0, price=100.0),
                Tick(symbol="R_100", epoch=1783850700.0, price=101.2),
                Tick(symbol="R_100", epoch=1783851000.0, price=102.3),
            ],
            RuntimeError("transport_down"),
        ]
    )

    result = asyncio.run(
        score_unresolved_records_from_market(
            calls_path=calls_path,
            outcomes_path=outcomes_path,
            now=datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
            client_factory=lambda: client,
        )
    )

    written = [
        json.loads(line)
        for line in outcomes_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.scored_records == 1
    assert result.failed_records == 1
    assert result.skipped_records == 1
    assert written[0]["outcome_label"] == "target_hit"
    # A supplied client factory means Blueberry-scale scoring (MT5), which
    # must be stamped so the evidence aggregator can keep Deriv-fallback
    # (wrong-scale) rows out of the gate.
    assert written[0]["scoring_source"] == "mt5"


def test_score_unresolved_records_from_market_writes_stop_hit_when_stop_is_reached_first(
    tmp_path: Path,
) -> None:
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '{"symbol":"R_75","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":103.0,"trade_status":"valid"}\n',
        encoding="utf-8",
    )
    client = FakeScoringClient(
        [
            [
                Tick(symbol="R_75", epoch=1783850400.0, price=100.0),
                Tick(symbol="R_75", epoch=1783850700.0, price=99.1),
                Tick(symbol="R_75", epoch=1783851000.0, price=98.0),
                Tick(symbol="R_75", epoch=1783851300.0, price=103.5),
            ]
        ]
    )

    result = asyncio.run(
        score_unresolved_records_from_market(
            calls_path=calls_path,
            outcomes_path=outcomes_path,
            now=datetime(2026, 7, 12, 11, 30, tzinfo=timezone.utc),
            client_factory=lambda: client,
        )
    )

    written = [
        json.loads(line)
        for line in outcomes_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.scored_records == 1
    assert result.failed_records == 0
    assert result.skipped_records == 0
    assert written[0]["outcome_label"] == "stop_hit"


def test_score_call_outcome_stop_wick_in_forming_candle_without_closed_breach_is_neither() -> None:
    """Stop-lock grace: a wick through the stop inside the STILL-FORMING
    execution candle (no closed-candle breach) must score 'neither', not
    'stop_hit' — matching the guardian's plan-hold rule."""
    prices = [
        (100.0, 1000.0),  # closed bucket 1: no breach
        (100.2, 1200.0),
        (100.1, 1900.0),  # forming bucket 2: wicks to 97.5 then recovers
        (97.5, 2100.0),
        (100.3, 2300.0),
    ]
    record = {
        "symbol": "R_75",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 103.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "neither_reached"
    assert outcome["stop_reached"] is False
    assert outcome["stop_confirmed_on_closed_candle"] is False


def test_score_call_outcome_stop_confirmed_on_closed_candle_is_stop_hit() -> None:
    """A CLOSED execution candle trading through the stop confirms the
    stop-out even when price later recovers in the forming candle."""
    prices = [
        (100.0, 1000.0),  # closed bucket: low 97.5 breaches stop 98.0
        (97.5, 1200.0),
        (99.0, 1500.0),
        (100.5, 1900.0),  # forming bucket — recovered
        (100.8, 2200.0),
    ]
    record = {
        "symbol": "R_75",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 103.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "stop_hit"
    assert outcome["stop_reached"] is True
    assert outcome["stop_confirmed_on_closed_candle"] is True


def test_score_call_outcome_target_wins_over_stop_wick_in_same_closed_candle() -> None:
    """Within one closed candle a target touch beats a stop breach — the stop
    breach is a wick, not a confirmed stop-out, under the grace."""
    prices = [
        (100.0, 1000.0),  # closed bucket: wicks to 97.5 AND to 103.0
        (97.5, 1200.0),
        (103.0, 1500.0),
        (100.5, 1900.0),  # forming bucket
    ]
    record = {
        "symbol": "R_100",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 98.0,
        "primary_target": 102.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "target_hit"
    assert outcome["stop_confirmed_on_closed_candle"] is False


def test_score_call_outcome_sell_stop_confirmed_on_closed_high() -> None:
    """Sell direction: a closed candle HIGH at/above the stop confirms the
    stop-out, even with no direction_bias field (inferred from stop > entry)."""
    prices = [
        (100.0, 1000.0),  # closed bucket: high 102.5 >= stop 102.0
        (101.0, 1200.0),
        (102.5, 1500.0),
        (99.0, 1900.0),  # forming bucket
    ]
    record = {
        "symbol": "R_100",
        "generated_at": "2026-07-12T10:00:00+00:00",
        "hold_horizon_minutes": 60,
        "entry": 100.0,
        "execution_stop": 102.0,
        "primary_target": 97.0,
        "trade_status": "valid",
    }

    outcome = score_call_outcome(record=record, prices=prices)

    assert outcome["outcome_label"] == "stop_hit"
    assert outcome["stop_confirmed_on_closed_candle"] is True


def test_score_unresolved_records_from_market_applies_stop_lock_grace_and_tags_rule(
    tmp_path: Path,
) -> None:
    """The live MT5 path scores with the closed-candle grace: a stop wick
    inside the still-forming execution candle scores 'neither', and the row is
    tagged so the gate can tell grace-scored from legacy wick-scored rows."""
    calls_path = tmp_path / "calls.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    calls_path.write_text(
        '{"symbol":"R_75","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":103.0,"trade_status":"valid"}\n',
        encoding="utf-8",
    )
    # Epochs 1783850400/900 = bucket 1982056 (closed, benign) and
    # 1783851900/900 = bucket 1982057 (the LATEST bucket — the forming candle:
    # wicks to 97.5 then recovers, all inside it, so no closed candle ever
    # confirms the stop).
    client = FakeScoringClient(
        [
            [
                Tick(symbol="R_75", epoch=1783850400.0, price=100.0),
                Tick(symbol="R_75", epoch=1783850700.0, price=100.4),
                Tick(symbol="R_75", epoch=1783851900.0, price=100.1),
                Tick(symbol="R_75", epoch=1783852100.0, price=97.5),
                Tick(symbol="R_75", epoch=1783852150.0, price=100.3),
            ]
        ]
    )

    result = asyncio.run(
        score_unresolved_records_from_market(
            calls_path=calls_path,
            outcomes_path=outcomes_path,
            now=datetime(2026, 7, 12, 11, 30, tzinfo=timezone.utc),
            client_factory=lambda: client,
        )
    )

    written = [
        json.loads(line)
        for line in outcomes_path.read_text(encoding="utf-8").splitlines()
    ]
    assert result.scored_records == 1
    assert written[0]["outcome_label"] == "neither_reached"
    assert written[0]["stop_reached"] is False
    assert written[0]["stop_confirmed_on_closed_candle"] is False
    assert written[0]["scoring_rule"] == "closed_candle_grace"
    assert written[0]["execution_timeframe_sec"] == 900


def test_score_unresolved_records_from_market_raises_without_client_no_deriv_fallback(
    tmp_path: Path,
) -> None:
    """A missing client_factory is a hard error — there is no silent Deriv
    fallback.  Deriv 1HZ75V/1HZ100V are on the WRONG price scale vs the call
    levels (SYN75/SYN100), so scoring without the Blueberry MT5 client must
    never produce outcomes."""
    calls_path = tmp_path / "calls.jsonl"
    calls_path.write_text(
        '{"symbol":"R_75","generated_at":"2026-07-12T10:00:00+00:00","hold_horizon_minutes":60,"entry":100.0,"execution_stop":98.0,"primary_target":103.0,"trade_status":"valid"}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="client_factory"):
        asyncio.run(
            score_unresolved_records_from_market(
                calls_path=calls_path,
                outcomes_path=tmp_path / "outcomes.jsonl",
                now=datetime(2026, 7, 12, 11, 30, tzinfo=timezone.utc),
                client_factory=None,
            )
        )
    # No outcomes were written.
    assert not (tmp_path / "outcomes.jsonl").exists()
