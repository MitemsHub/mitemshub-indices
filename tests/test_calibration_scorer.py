from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

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

    assert prices == [480.1, 482.2, 483.4]
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
            "max_favorable_excursion": 120.0,
            "max_adverse_excursion": 30.0,
        },
        {
            "symbol": "R_75",
            "trigger_type": "continuation_close",
            "trade_status": "valid",
            "outcome_label": "stop_hit",
            "max_favorable_excursion": 40.0,
            "max_adverse_excursion": 90.0,
        },
        {
            "symbol": "R_100",
            "trigger_type": "reclaim_pullback",
            "trade_status": "valid",
            "outcome_label": "target_hit",
            "max_favorable_excursion": 8.0,
            "max_adverse_excursion": 2.0,
        },
        {
            "symbol": "R_75",
            "trigger_type": "continuation_close",
            "trade_status": "not_valid",
            "outcome_label": "rejected_but_price_ran",
            "max_favorable_excursion": 60.0,
            "max_adverse_excursion": 10.0,
        },
    ]

    summary = summarize_outcomes(outcomes)

    assert summary[("R_75", "continuation_close", "valid")]["count"] == 2
    assert summary[("R_75", "continuation_close", "valid")]["target_hit_rate"] == 0.5
    assert summary[("R_75", "continuation_close", "valid")]["stop_hit_rate"] == 0.5
    assert summary[("R_75", "continuation_close", "not_valid")]["count"] == 1
    assert summary[("R_100", "reclaim_pullback", "valid")]["target_hit_rate"] == 1.0


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
