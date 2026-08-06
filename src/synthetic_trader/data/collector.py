from __future__ import annotations

import os
import time
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


def candles_to_ticks(
    symbol: str,
    candles: list[dict[str, float]],
    timeframe_sec: int = 60,
) -> list[Tick]:
    """Reconstruct a faithful tick stream from OHLC candles.

    The Deriv API only serves a rolling ~5000-tick buffer for tick-style
    history, but candle-style history pages back for days. This helper turns
    a candle series into 4 ticks per candle (open/high/low/close) placed
    inside the candle's time bucket so that ``CandleBuilder`` reproduces the
    exact OHLC. Used to backfill multi-day market history.
    """
    if timeframe_sec <= 0:
        raise ValueError("timeframe_sec must be positive")
    ticks: list[Tick] = []
    for candle in candles:
        epoch = float(candle["epoch"])
        bucket = int(epoch // timeframe_sec) * timeframe_sec
        o = float(candle["open"])
        h = float(candle["high"])
        l = float(candle["low"])
        c = float(candle["close"])
        # Offsets keep the 4 ticks inside the same bucket and in a stable
        # order; the builder takes max/min across the bucket so OHLC is exact.
        ticks.append(Tick(symbol=symbol, epoch=bucket + 0.01, price=o))
        ticks.append(Tick(symbol=symbol, epoch=bucket + 0.26, price=h))
        ticks.append(Tick(symbol=symbol, epoch=bucket + 0.51, price=l))
        ticks.append(Tick(symbol=symbol, epoch=bucket + 0.76, price=c))
    return ticks


async def collect_candle_history(
    symbol: str,
    days: float,
    output_path: str | Path,
    app_id: str | None = None,
    token: str | None = None,
    granularity: int = 60,
    batch_size: int = 5000,
) -> TickDatasetReport:
    """Backfill *days* of 1-minute OHLC history and write it as tick CSV.

    Deriv's tick-style ``ticks_history`` cannot page back in time (it only
    serves a recent rolling buffer), so multi-day history must come from
    candle-style requests paged via the ``end`` parameter, then reconstructed
    into an OHLC-exact tick stream with :func:`candles_to_ticks`.

    The candle granularity (default 60s) becomes the base tick spacing, so
    downstream candle builders at >= granularity reproduce the original OHLC
    exactly. Higher timeframes (300s) are built from these ticks too.
    """
    if days <= 0:
        raise ValueError("days must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    credentials = deriv_credentials_from_env(app_id=app_id, token=token)
    cutoff = time.time() - days * 86400
    candles: list[dict[str, float]] = []
    end: str | int = "latest"
    async with DerivWebSocketClient(credentials) as client:
        while True:
            batch = await client.candles_history(
                symbol=symbol,
                count=batch_size,
                end=end,
                granularity=granularity,
            )
            if not batch:
                break
            candles.extend(batch)
            earliest = min(float(c["epoch"]) for c in batch)
            if earliest <= cutoff:
                break
            end = int(earliest) - 1

    candles = [c for c in candles if float(c["epoch"]) >= cutoff]
    candles.sort(key=lambda c: float(c["epoch"]))
    ticks = candles_to_ticks(symbol, candles, timeframe_sec=granularity)
    normalized, _ = normalize_ticks(ticks)
    write_ticks_csv(output_path, normalized, append=False)
    return inspect_ticks(normalized, symbol=symbol)
