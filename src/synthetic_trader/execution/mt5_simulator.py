"""In-memory MetaTrader5 module simulator — the Python CTrade-equivalent.

The MQL5 ``SynthCallExecutor`` EA executes through ``CTrade``: a FOK market
order filled at the current ask (buy) / bid (sell), SL/TP attached at entry,
``PositionModify`` for stop changes, and a market close by ticket.  This
simulator mirrors exactly that contract in Python so the
``Mt5LiveExecutionBackend`` can be exercised headlessly — paper->live parity
checks, rejection handling, and trailing-stop modify tests — without a
terminal.

It exposes the MetaTrader5-package surface the execution layer touches:
``order_send`` (TRADE_ACTION_DEAL open/close, TRADE_ACTION_SLTP modify),
``positions_get``, ``symbol_info``, ``symbol_info_tick``, ``terminal_info``,
``initialize``/``shutdown``.  Every ``order_send`` is logged, so a parity
harness can assert not just the outcome but the exact payloads sent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass
class FakeMt5Result:
    retcode: int
    order: int
    deal: int
    comment: str = "Request executed"
    volume: float = 0.0
    price: float = 0.0


@dataclass
class FakeMetaTrader5:
    """CTrade-equivalent MT5 module.  ``bid``/``ask`` move the fill price.

    ``reject_retcode`` — when set, every ``order_send`` returns that retcode
    (the order is NOT placed) so rejection paths can be exercised the same
    way a broker AT block or invalid-stops rejection would surface.
    """

    bid: float = 1700.0
    ask: float = 1700.0
    reject_retcode: int | None = None

    # MetaTrader5 constants (real values from the package).
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    RETCODE_DONE = 10009
    RETCODE_REJECT = 10014

    _positions: dict[int, dict] = field(default_factory=dict)
    _next_ticket: int = field(default=1000)
    order_send_calls: list[dict] = field(default_factory=list)

    # ── meta surface the execution layer touches ──────────────────────────
    def initialize(self, path=None, portable=False, timeout=0) -> bool:
        return True

    def shutdown(self) -> bool:
        return True

    def login(self, login=None, password=None, server=None) -> bool:
        return True

    def terminal_info(self) -> SimpleNamespace:
        return SimpleNamespace(
            path="fake-terminal", company="Fake", connected=True, trade_allowed=True,
        )

    def account_info(self) -> SimpleNamespace:
        return SimpleNamespace(login=1, equity=10_000.0, balance=10_000.0)

    def symbol_info(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(name=symbol, trade_mode=0)

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        return True

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(
            time=0,
            time_msc=int(time.time() * 1000),
            bid=self.bid,
            ask=self.ask,
            last=self.bid,
        )

    def last_error(self):
        return (0, "ok")

    # ── positions ─────────────────────────────────────────────────────────
    def positions_get(self, symbol=None):
        """Return open positions as MqlPosition-like SimpleNamespaces."""
        out = []
        for pos in self._positions.values():
            if symbol is not None and pos["symbol"] != symbol:
                continue
            out.append(
                SimpleNamespace(
                    ticket=pos["ticket"],
                    symbol=pos["symbol"],
                    type=pos["type"],
                    volume=pos["volume"],
                    price_open=pos["price_open"],
                    price_current=self.bid if pos["type"] == self.POSITION_TYPE_BUY else self.ask,
                    sl=pos.get("sl"),
                    tp=pos.get("tp"),
                    time=pos["time"],
                    magic=pos.get("magic", 0),
                    comment=pos.get("comment", ""),
                )
            )
        return tuple(out)

    def _result(self, retcode: int, order: int, deal: int, comment: str = "") -> FakeMt5Result:
        return FakeMt5Result(
            retcode=retcode, order=order, deal=deal,
            comment=comment or ("Request executed" if retcode == self.RETCODE_DONE else "Request rejected"),
        )

    # ── order_send (CTrade-equivalent) ────────────────────────────────────
    def order_send(self, payload: dict) -> FakeMt5Result:
        self.order_send_calls.append(dict(payload))
        if self.reject_retcode is not None:
            return self._result(self.reject_retcode, order=0, deal=0, comment="simulated rejection")

        action = payload.get("action")
        if action == self.TRADE_ACTION_DEAL:
            if payload.get("position") is None:
                return self._open(payload)
            return self._close(payload)
        if action == self.TRADE_ACTION_SLTP:
            return self._modify(payload)
        return self._result(self.RETCODE_REJECT, order=0, deal=0, comment="unsupported action")

    def _open(self, payload: dict) -> FakeMt5Result:
        ticket = self._next_ticket
        self._next_ticket += 1
        otype = payload["type"]
        fill = self.ask if otype == self.ORDER_TYPE_BUY else self.bid
        self._positions[ticket] = {
            "ticket": ticket,
            "symbol": payload["symbol"],
            "type": otype,
            "volume": float(payload["volume"]),
            "price_open": float(fill),
            "sl": payload.get("sl"),
            "tp": payload.get("tp"),
            "time": int(time.time()),
            "magic": int(payload.get("magic", 0)),
            "comment": payload.get("comment", ""),
        }
        return self._result(self.RETCODE_DONE, order=ticket, deal=ticket)

    def _close(self, payload: dict) -> FakeMt5Result:
        ticket = int(payload["position"])
        if ticket not in self._positions:
            return self._result(self.RETCODE_REJECT, order=ticket, deal=0, comment="position not found")
        del self._positions[ticket]
        return self._result(self.RETCODE_DONE, order=ticket, deal=ticket)

    def _modify(self, payload: dict) -> FakeMt5Result:
        ticket = int(payload["position"])
        pos = self._positions.get(ticket)
        if pos is None:
            return self._result(self.RETCODE_REJECT, order=ticket, deal=0, comment="position not found")
        if payload.get("sl") is not None:
            pos["sl"] = float(payload["sl"])
        if payload.get("tp") is not None:
            pos["tp"] = float(payload["tp"])
        return self._result(self.RETCODE_DONE, order=ticket, deal=ticket)

    # ── introspection helpers for tests / harnesses ───────────────────────
    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    def position_by_ticket(self, ticket: int) -> dict | None:
        return self._positions.get(ticket)
