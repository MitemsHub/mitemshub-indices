from __future__ import annotations

import os
from pathlib import Path

from synthetic_trader.config import DEFAULT_DERIV_APP_ID
from synthetic_trader.data.tick_store import TickDatasetReport, inspect_ticks, normalize_ticks, write_ticks_csv
from synthetic_trader.domain import Tick
from synthetic_trader.execution.deriv_ws import DerivCredentials, DerivWebSocketClient


def deriv_credentials_from_env(app_id: str | None = None, token: str | None = None) -> DerivCredentials:
    resolved_app_id = app_id or os.getenv("DERIV_APP_ID") or DEFAULT_DERIV_APP_ID
    return DerivCredentials(app_id=resolved_app_id, token=token or os.getenv("DERIV_API_TOKEN"))


async def collect_history(
    symbol: str,
    count: int,
    output_path: str | Path,
    app_id: str | None = None,
    token: str | None = None,
    append: bool = True,
    batch_size: int = 5000,
) -> TickDatasetReport:
    if count <= 0:
        raise ValueError("count must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    credentials = deriv_credentials_from_env(app_id=app_id, token=token)
    collected: list[Tick] = []
    end: str | int = "latest"
    async with DerivWebSocketClient(credentials) as client:
        while len(collected) < count:
            request_count = min(batch_size, count - len(collected))
            batch = await client.ticks_history(symbol=symbol, count=request_count, end=end)
            batch = [tick for tick in batch if tick.symbol == symbol]
            if not batch:
                break

            collected.extend(batch)
            earliest = min(tick.epoch for tick in batch)
            next_end = int(earliest) - 1
            if end != "latest" and next_end >= int(end):
                break
            end = next_end

    normalized, _ = normalize_ticks(collected)
    normalized = normalized[-count:]
    write_ticks_csv(output_path, normalized, append=append)
    return inspect_ticks(normalized, symbol=symbol)


def merge_tick_batches(*batches: list[Tick]) -> list[Tick]:
    merged: list[Tick] = []
    for batch in batches:
        merged.extend(batch)
    return sorted(merged, key=lambda item: (item.symbol, item.epoch, item.price))
