from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from synthetic_trader.execution.venues import MarketDataClient


@dataclass(frozen=True)
class CalibrationScoringResult:
    scored_records: int = 0
    failed_records: int = 0
    skipped_records: int = 0


def _resolve_record_window(
    *,
    record: dict[str, object],
    window_minutes: int | None = None,
) -> tuple[datetime, datetime, int]:
    generated_at = datetime.fromisoformat(str(record["generated_at"]))
    hold_minutes = int(window_minutes or record.get("hold_horizon_minutes") or 60)
    window_end = generated_at + timedelta(minutes=hold_minutes)
    return generated_at, window_end, hold_minutes


async def fetch_prices_for_record(
    *,
    record: dict[str, object],
    client: MarketDataClient,
    window_minutes: int | None = None,
) -> list[float]:
    window_start, window_end, _ = _resolve_record_window(
        record=record,
        window_minutes=window_minutes,
    )
    start_epoch = int(window_start.timestamp())
    end_epoch = int(window_end.timestamp())
    ticks = await client.ticks_history(
        symbol=str(record["symbol"]),
        count=5000,
        start=start_epoch,
        end=end_epoch,
    )
    prices = [
        tick.price
        for tick in sorted(ticks, key=lambda item: item.epoch)
        if start_epoch <= int(tick.epoch) <= end_epoch
    ]
    if not prices:
        raise ValueError("empty_price_history")
    return prices


def _price_hits_target(*, price: float, entry: float, target: float) -> bool:
    if target >= entry:
        return price >= target
    return price <= target


def _price_hits_stop(*, price: float, entry: float, stop: float) -> bool:
    if stop <= entry:
        return price <= stop
    return price >= stop


def score_call_outcome(*, record: dict[str, object], prices: list[float]) -> dict[str, object]:
    entry = record.get("entry")
    stop = record.get("execution_stop")
    target = record.get("primary_target")
    current_close = record.get("current_close")
    max_favorable = max(prices) if prices else None
    max_adverse = min(prices) if prices else None

    if entry is not None and stop is not None and target is not None:
        entry_value = float(entry)
        stop_value = float(stop)
        target_value = float(target)
        label = "neither_reached"

        for price in prices:
            if _price_hits_target(price=price, entry=entry_value, target=target_value):
                label = "target_hit"
                break
            if _price_hits_stop(price=price, entry=entry_value, stop=stop_value):
                label = "stop_hit"
                break
    else:
        moved = False
        if current_close is not None and prices:
            reference_price = float(current_close)
            moved = any(abs(price - reference_price) > 1.0 for price in prices)
        label = "rejected_but_price_ran" if moved else "forming_remained_correct"

    return {
        "symbol": record.get("symbol"),
        "generated_at": record.get("generated_at"),
        "trigger_type": record.get("trigger_type"),
        "trade_status": record.get("trade_status"),
        "guardian_state": record.get("guardian_state"),
        "evaluation_time": datetime.now(timezone.utc).isoformat(),
        "outcome_window_minutes": record.get("hold_horizon_minutes") or 60,
        "entry": entry,
        "execution_stop": stop,
        "primary_target": target,
        "max_favorable_excursion": max_favorable,
        "max_adverse_excursion": max_adverse,
        "target_reached": label == "target_hit",
        "stop_reached": label == "stop_hit",
        "outcome_label": label,
    }


def load_jsonl_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _record_key(record: dict[str, object]) -> tuple[object, object]:
    return (record.get("symbol"), record.get("generated_at"))


async def score_unresolved_records_from_market(
    *,
    calls_path: Path,
    outcomes_path: Path,
    now: datetime,
    symbol: str | None = None,
    window_minutes: int | None = None,
    app_id: str | None = None,
    token: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> CalibrationScoringResult:
    existing_outcomes = load_jsonl_records(outcomes_path)
    resolved_keys = {_record_key(record) for record in existing_outcomes}
    result = CalibrationScoringResult()

    # No silent venue: scoring requires the Blueberry MT5 client because the
    # call levels (entry/stop/target) are measured on the SYN75/SYN100 scale.
    # Deriv's 1HZ75V/1HZ100V trade at a different price scale (~7,000 vs
    # ~1,542 for R_75) and would produce incomparable outcomes, so a missing
    # client is a hard error — never a fallback.
    if client_factory is None:
        raise RuntimeError(
            "score_unresolved_records_from_market requires client_factory "
            "(Blueberry MT5); the Deriv API fallback was removed because "
            "1HZ75V/1HZ100V are on the WRONG price scale"
        )
    factory = client_factory
    scoring_source = "mt5"

    async with factory() as client:
        for record in load_jsonl_records(calls_path):
            if symbol is not None and record.get("symbol") != symbol:
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records,
                    skipped_records=result.skipped_records + 1,
                )
                continue
            if _record_key(record) in resolved_keys:
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records,
                    skipped_records=result.skipped_records + 1,
                )
                continue

            generated_at, _, hold_minutes = _resolve_record_window(
                record=record,
                window_minutes=window_minutes,
            )
            if generated_at > now - timedelta(minutes=hold_minutes):
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records,
                    skipped_records=result.skipped_records + 1,
                )
                continue

            try:
                prices = await fetch_prices_for_record(
                    record=record,
                    client=client,
                    window_minutes=window_minutes,
                )
            except (KeyError, TypeError, ValueError, RuntimeError):
                result = CalibrationScoringResult(
                    scored_records=result.scored_records,
                    failed_records=result.failed_records + 1,
                    skipped_records=result.skipped_records,
                )
                continue

            outcome = score_call_outcome(record=record, prices=prices)
            outcome["scoring_source"] = scoring_source
            append_jsonl_record(outcomes_path, outcome)
            resolved_keys.add(_record_key(record))
            result = CalibrationScoringResult(
                scored_records=result.scored_records + 1,
                failed_records=result.failed_records,
                skipped_records=result.skipped_records,
            )

    return result


def run_score_unresolved_records_from_market(
    *,
    calls_path: Path,
    outcomes_path: Path,
    now: datetime,
    symbol: str | None = None,
    window_minutes: int | None = None,
    app_id: str | None = None,
    token: str | None = None,
    client_factory: Callable[[], MarketDataClient] | None = None,
) -> CalibrationScoringResult:
    return asyncio.run(
        score_unresolved_records_from_market(
            calls_path=calls_path,
            outcomes_path=outcomes_path,
            now=now,
            symbol=symbol,
            window_minutes=window_minutes,
            app_id=app_id,
            token=token,
            client_factory=client_factory,
        )
    )


def score_unresolved_records(
    *,
    calls_path: Path,
    outcomes_path: Path,
    now: datetime,
    price_lookup: Callable[[dict[str, object]], list[float]],
    symbol: str | None = None,
    window_minutes: int | None = None,
) -> int:
    existing_outcomes = load_jsonl_records(outcomes_path)
    resolved_keys = {_record_key(record) for record in existing_outcomes}
    written = 0

    for record in load_jsonl_records(calls_path):
        if symbol is not None and record.get("symbol") != symbol:
            continue
        if _record_key(record) in resolved_keys:
            continue
        generated_at, _, hold_minutes = _resolve_record_window(
            record=record,
            window_minutes=window_minutes,
        )
        if generated_at > now - timedelta(minutes=hold_minutes):
            continue
        outcome = score_call_outcome(record=record, prices=price_lookup(record))
        append_jsonl_record(outcomes_path, outcome)
        resolved_keys.add(_record_key(record))
        written += 1

    return written


def summarize_outcomes(
    outcomes: list[dict[str, object]],
) -> dict[tuple[str, str | None, str | None], dict[str, float | int]]:
    grouped: dict[tuple[str, str | None, str | None], list[dict[str, object]]] = {}
    for outcome in outcomes:
        # Only measured trade outcomes count as evidence.  A scored row is a
        # real outcome only when the call carried entry/stop/target levels:
        # level-less rows (the scorer's ``rejected_but_price_ran`` /
        # ``forming_remained_correct`` fallback for calls that never had
        # levels) would otherwise dilute the empirical rate with fake 0%
        # evidence and suppress real call types — the stale July-12 journal
        # poisoned ``setup_candidate`` exactly this way.
        #
        # Rows scored through the Deriv API fallback (``scoring_source ==
        # "deriv_fallback"``) are on the wrong price scale and are excluded
        # too — they are indistinguishable from real outcomes at the gate,
        # so the tag is the only honest way to keep them out.
        if (
            outcome.get("entry") is None
            or outcome.get("execution_stop") is None
            or outcome.get("primary_target") is None
            or outcome.get("scoring_source") == "deriv_fallback"
        ):
            continue
        key = (
            str(outcome.get("symbol")),
            outcome.get("trigger_type") if outcome.get("trigger_type") is None else str(outcome.get("trigger_type")),
            outcome.get("trade_status") if outcome.get("trade_status") is None else str(outcome.get("trade_status")),
        )
        grouped.setdefault(key, []).append(outcome)

    summary: dict[tuple[str, str | None, str | None], dict[str, float | int]] = {}
    for key, rows in grouped.items():
        count = len(rows)
        target_hits = sum(1 for row in rows if row.get("outcome_label") == "target_hit")
        stop_hits = sum(1 for row in rows if row.get("outcome_label") == "stop_hit")
        neither = sum(1 for row in rows if row.get("outcome_label") == "neither_reached")
        summary[key] = {
            "count": count,
            "target_hit_rate": target_hits / count,
            "stop_hit_rate": stop_hits / count,
            "neither_rate": neither / count,
            "avg_max_favorable_excursion": sum(float(row.get("max_favorable_excursion") or 0.0) for row in rows)
            / count,
            "avg_max_adverse_excursion": sum(float(row.get("max_adverse_excursion") or 0.0) for row in rows)
            / count,
        }
    return summary
