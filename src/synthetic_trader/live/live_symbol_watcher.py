from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedSymbolState:
    symbol: str
    call: str
    state: str
    confidence: float | None
    regime: str | None
    market_thesis: str
    entry_area: str | None
    entry: float | None
    stop_area: str | None
    stop_loss: float | None
    target_area: str | None
    take_profit: float | None
    reward_risk: float | None
    invalidates_if: str
    next_trigger: str
    current_close: float | None
    call_age_seconds: int
    generated_at: str


class LiveSymbolWatcherStore:
    def __init__(self) -> None:
        self._states: dict[str, PreparedSymbolState] = {}

    def update(self, state: PreparedSymbolState) -> None:
        self._states[state.symbol] = state

    def get(self, symbol: str) -> PreparedSymbolState | None:
        return self._states.get(symbol)
