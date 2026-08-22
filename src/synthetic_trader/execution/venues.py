from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from synthetic_trader.domain import Tick


class MarketDataClient(Protocol):
    async def __aenter__(self) -> "MarketDataClient": ...

    async def __aexit__(self, *_: object) -> None: ...

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]: ...

    # NOTE: subscribe_ticks is an async generator (uses yield) in both
    # Mt5TickClient and DerivWebSocketClient, so it returns AsyncIterator[Tick]
    # directly, not a coroutine.  Using plain def (not async def) in the
    # protocol matches the actual runtime type.
    def subscribe_ticks(self, symbol: str, timeout: float = 20.0) -> AsyncIterator[Tick]: ...
