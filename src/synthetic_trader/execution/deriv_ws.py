from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from itertools import count
from typing import Any

from synthetic_trader.domain import Tick


@dataclass(frozen=True)
class DerivCredentials:
    app_id: str
    token: str | None = None


class DerivWebSocketClient:
    """Thin Deriv WebSocket adapter.

    The decision engine remains broker-agnostic; this adapter only handles transport
    and payloads. Install the optional `live` dependency before using it.
    """

    def __init__(self, credentials: DerivCredentials) -> None:
        self.credentials = credentials
        self.endpoint = f"wss://ws.derivws.com/websockets/v3?app_id={credentials.app_id}"
        self._request_id = count(1)
        self._socket: Any | None = None

    async def __aenter__(self) -> "DerivWebSocketClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install optional live dependency: pip install -e .[live]") from exc

        self._socket = await websockets.connect(self.endpoint)
        if self.credentials.token:
            await self.authorize(self.credentials.token)

    async def close(self) -> None:
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

    async def ticks_history(self, symbol: str, count: int = 5000, end: str | int = "latest") -> list[Tick]:
        response = await self.request(
            {
                "ticks_history": symbol,
                "count": count,
                "end": end,
                "style": "ticks",
            }
        )
        history = response.get("history", {})
        times = history.get("times", [])
        prices = history.get("prices", [])
        return [Tick(symbol=symbol, epoch=float(epoch), price=float(price)) for epoch, price in zip(times, prices)]

    async def subscribe_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        if self._socket is None:
            raise RuntimeError("client is not connected")
        await self._socket.send(json.dumps({"ticks": symbol, "subscribe": 1}))
        async for raw in self._socket:
            message = json.loads(raw)
            if message.get("msg_type") == "tick":
                tick = message["tick"]
                yield Tick(symbol=symbol, epoch=float(tick["epoch"]), price=float(tick["quote"]))

    async def proposal(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = {"proposal": 1}
        request.update(payload)
        return await self.request(request)

    async def buy(self, proposal_id: str, price: float) -> dict[str, Any]:
        return await self.request({"buy": proposal_id, "price": price})

    async def sell(self, contract_id: int, price: float = 0.0) -> dict[str, Any]:
        return await self.request({"sell": contract_id, "price": price})
