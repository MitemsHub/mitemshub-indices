from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from itertools import count
from typing import Any

from synthetic_trader.domain import Tick


@dataclass(frozen=True)
class DerivCredentials:
    app_id: str
    token: str | None = None


# ── Deriv API symbol mapping ───────────────────────────────────────────────
# CRITICAL: The Deriv WebSocket API symbols for Volatility 75/100 (1s) Index
# DO NOT match Blueberry Markets MT5 pricing. The prices are fundamentally
# different instruments despite sharing similar names:
#
#   Deriv 1HZ75V  (Volatility 75 1s Index)  → trades at ~7,000
#   Blueberry Volatility 75 (SYN75)          → trades at ~1,542
#
#   Deriv 1HZ100V (Volatility 100 1s Index) → trades at ~280
#   Blueberry Volatility 100 (SYN100)        → trades at ~280
#
# When MT5 is configured and connected, the system pulls ticks DIRECTLY from
# the Blueberry Markets terminal (correct prices). Deriv API is only used as
# a FALLBACK when MT5 is not available — in which case the price levels will
# NOT match the broker's actual instrument pricing.
#
# Map: internal symbol → Deriv API symbol (fallback only)
DERIV_API_SYMBOL_MAP: dict[str, str] = {
    # 1HZ75V = Deriv's own Volatility 75 (1s) Index. Price levels are ~4.6x
    # higher than Blueberry Markets' "Blueberry Volatility 75" (~1,542).
    # Used for pattern analysis only — trade levels should come from MT5.
    "R_75": "1HZ75V",
    # 1HZ100V = Deriv's Volatility 100 (1s) Index. Price levels roughly match
    # Blueberry Markets' "Blueberry Volatility 100" (~280).
    "R_100": "1HZ100V",
}


def _deriv_api_symbol(symbol: str) -> str:
    """Map an internal symbol name to the correct Deriv WebSocket API symbol."""
    return DERIV_API_SYMBOL_MAP.get(symbol, symbol)


# One-time warning flag — only warn once per process lifetime to avoid spam
_DERIV_WARNING_SHOWN = False


def _warn_deriv_fallback() -> None:
    """Emit a visible warning when falling back to Deriv API (wrong prices)."""
    global _DERIV_WARNING_SHOWN
    if _DERIV_WARNING_SHOWN:
        return
    if not os.getenv("SYNTHETIC_MT5_SERVER"):
        _DERIV_WARNING_SHOWN = True
        print(
            "[deriv_ws] WARNING: MT5 not configured — using Deriv API fallback. "
            "Deriv 1HZ75V trades at ~7,000 but Blueberry Volatility 75 trades at "
            "~1,542. Trade levels will be WRONG until MT5 is configured. "
            "Set SYNTHETIC_MT5_SERVER, SYNTHETIC_MT5_LOGIN, SYNTHETIC_MT5_PASSWORD "
            "in .env.local.",
            file=sys.stderr,
            flush=True,
        )


class DerivWebSocketClient:
    """Thin Deriv WebSocket adapter.

    The decision engine remains broker-agnostic; this adapter only handles transport
    and payloads. Install the optional `live` dependency before using it.
    """

    def __init__(self, credentials: DerivCredentials, connect_timeout: float = 15.0) -> None:
        self.credentials = credentials
        self.endpoint = f"wss://ws.derivws.com/websockets/v3?app_id={credentials.app_id}"
        self._request_id = count(1)
        self._socket: Any | None = None
        self._connect_timeout = connect_timeout
        self._ping_task: asyncio.Task | None = None

    async def __aenter__(self) -> "DerivWebSocketClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        _warn_deriv_fallback()
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install optional live dependency: pip install -e .[live]") from exc

        self._socket = await asyncio.wait_for(
            websockets.connect(self.endpoint),
            timeout=self._connect_timeout,
        )
        if self.credentials.token:
            await self.authorize(self.credentials.token)

    async def close(self) -> None:
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            self._ping_task = None
        if self._socket is not None:
            await self._socket.close()
            self._socket = None

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("client is not connected")
        payload = dict(payload)
        payload["req_id"] = next(self._request_id)
        await self._socket.send(json.dumps(payload))
        while True:
            raw = await self._socket.recv()
            message = json.loads(raw)
            if message.get("req_id") == payload["req_id"]:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message

    async def authorize(self, token: str) -> dict[str, Any]:
        return await self.request({"authorize": token})

    async def ping_loop(self, interval_sec: int = 60) -> None:
        while True:
            await asyncio.sleep(interval_sec)
            await self.request({"ping": 1})

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]:
        api_symbol = _deriv_api_symbol(symbol)
        payload: dict[str, Any] = {
            "ticks_history": api_symbol,
            "count": count,
            "end": end,
            "style": "ticks",
        }
        if start is not None:
            payload["start"] = start
        response = await self.request(payload)
        history = response.get("history", {})
        times = history.get("times", [])
        prices = history.get("prices", [])
        return [Tick(symbol=symbol, epoch=float(epoch), price=float(price)) for epoch, price in zip(times, prices)]

    async def candles_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        granularity: int = 60,
    ) -> list[dict[str, float]]:
        """Fetch historical OHLC candles for a symbol.

        Unlike tick-style history (which only serves a rolling ~5000-tick
        buffer and ignores the ``end`` parameter), candle-style history pages
        back for days/weeks via ``end``. This is the only reliable way to
        reconstruct multi-day market history from the Deriv API.

        Returns a list of ``{"epoch", "open", "high", "low", "close"}`` dicts
        ordered newest-first (as served by the API).
        """
        api_symbol = _deriv_api_symbol(symbol)
        payload: dict[str, Any] = {
            "ticks_history": api_symbol,
            "count": count,
            "end": end,
            "style": "candles",
            "granularity": granularity,
        }
        response = await self.request(payload)
        candles = response.get("candles", [])
        result: list[dict[str, float]] = []
        for candle in candles:
            if isinstance(candle, dict):
                result.append(
                    {
                        "epoch": float(candle["epoch"]),
                        "open": float(candle["open"]),
                        "high": float(candle["high"]),
                        "low": float(candle["low"]),
                        "close": float(candle["close"]),
                    }
                )
            else:
                # Some API versions return arrays [epoch, open, high, low, close]
                result.append(
                    {
                        "epoch": float(candle[0]),
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                    }
                )
        return result

    async def subscribe_ticks(self, symbol: str, timeout: float = 20.0) -> AsyncIterator[Tick]:
        if self._socket is None:
            raise RuntimeError("client is not connected")
        api_symbol = _deriv_api_symbol(symbol)
        await self._socket.send(json.dumps({"ticks": api_symbol, "subscribe": 1}))
        deadline = asyncio.get_running_loop().time() + timeout
        async for raw in self._socket:
            message = json.loads(raw)
            if message.get("msg_type") == "tick":
                tick = message["tick"]
                yield Tick(symbol=symbol, epoch=float(tick["epoch"]), price=float(tick.get("quote", tick.get("bid", 0))))
            if asyncio.get_running_loop().time() > deadline:
                return

    async def proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = {"proposal": 1}
        request.update(payload)
        return await self.request(request)

    async def buy(self, proposal_id: str, price: float) -> dict[str, Any]:
        return await self.request({"buy": proposal_id, "price": price})

    async def sell(self, contract_id: int, price: float = 0.0) -> dict[str, Any]:
        return await self.request({"sell": contract_id, "price": price})
