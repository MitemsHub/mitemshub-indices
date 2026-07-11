from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from synthetic_trader.domain import Tick


class MarketDataClient(Protocol):
    async def __aenter__(self) -> "MarketDataClient": ...

    async def __aexit__(self, *_: object) -> None: ...

    async def ticks_history(
        self, symbol: str, count: int = 5000, end: str | int = "latest"
    ) -> list[Tick]: ...

    async def subscribe_ticks(self, symbol: str) -> AsyncIterator[Tick]: ...
