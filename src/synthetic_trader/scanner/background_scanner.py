from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from synthetic_trader.config import TraderConfig
from synthetic_trader.domain import Candle
from synthetic_trader.features.assembler import build_snapshot
from synthetic_trader.features.market_structure import market_structure_features
from synthetic_trader.features.regimes import classify_regime
from synthetic_trader.live.market_snapshot import analyze_live_snapshot
from synthetic_trader.strategy.decision_engine import DecisionEngine


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    timestamp: datetime
    regime: str
    structure_bias: float
    confidence: float
    direction_bias: str
    actionable: bool
    notes: tuple[str, ...]


@dataclass
class SymbolScannerState:
    symbol: str
    last_scan: datetime | None = None
    scan_count: int = 0
    last_regime: str = "unknown"
    last_structure_bias: float = 0.0
    last_direction: str = "none"
    consecutive_same_regime: int = 0
    alerts_triggered: int = 0


class BackgroundScanner:
    def __init__(
        self,
        config: TraderConfig,
        decision_engine: DecisionEngine,
        symbols: list[str],
        scan_interval_sec: int = 300,
        min_regime_change_confidence: float = 0.6,
    ) -> None:
        self.config = config
        self.decision_engine = decision_engine
        self.symbols = symbols
        self.scan_interval_sec = scan_interval_sec
        self.min_regime_change_confidence = min_regime_change_confidence
        self.states: dict[str, SymbolScannerState] = {
            symbol: SymbolScannerState(symbol=symbol) for symbol in symbols
        }
        self._running = False
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[[ScanResult], None]] = []

    def register_callback(self, callback: Callable[[ScanResult], None]) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _scan_loop(self) -> None:
        while self._running:
            for symbol in self.symbols:
                try:
                    await self._scan_symbol(symbol)
                except Exception:
                    pass
            await asyncio.sleep(self.scan_interval_sec)

    async def _scan_symbol(self, symbol: str) -> ScanResult:
        profile = self.config.symbols[symbol]
        state = self.states[symbol]

        ticks = await self._fetch_recent_ticks(symbol, count=5000)
        if not ticks:
            return ScanResult(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                regime="unknown",
                structure_bias=0.0,
                confidence=0.0,
                direction_bias="none",
                actionable=False,
                notes=("no tick data",),
            )

        builder = self._build_candles(ticks, profile)
        role_candles = {
            "bias": builder.get(profile.bias_timeframe_sec, []),
            "setup": builder.get(profile.setup_timeframe_sec, []),
            "confirmation": builder.get(profile.confirmation_timeframe_sec, []),
            "execution": builder.get(profile.execution_timeframe_sec, []),
        }

        execution_candles = role_candles["execution"]
        if len(execution_candles) < profile.min_history_candles:
            return ScanResult(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                regime="unknown",
                structure_bias=0.0,
                confidence=0.0,
                direction_bias="none",
                actionable=False,
                notes=(f"need {profile.min_history_candles} candles, have {len(execution_candles)}",),
            )

        report = self.decision_engine.evaluate(
            symbol=symbol,
            candles=execution_candles,
            role_candles=role_candles,
        )

        snapshot = build_snapshot(
            symbol=symbol,
            timeframe_sec=profile.execution_timeframe_sec,
            candles=execution_candles,
            higher_timeframe_candles=role_candles["confirmation"],
            extra_timeframes=role_candles,
        )

        regime = snapshot.regime.value
        structure = snapshot.structure
        structure_bias = structure.get("structure_bias", 0.0)
        direction_bias = "buy" if structure_bias > 0 else "sell" if structure_bias < 0 else "none"
        confidence = report.signal.confidence if report.signal else 0.0
        actionable = report.signal is not None

        notes = []
        if state.last_regime != regime:
            notes.append(f"regime changed: {state.last_regime} -> {regime}")
            state.consecutive_same_regime = 0
        else:
            state.consecutive_same_regime += 1

        if state.last_direction != direction_bias and direction_bias != "none":
            notes.append(f"direction bias changed: {state.last_direction} -> {direction_bias}")

        if actionable:
            notes.append("actionable setup detected")
            state.alerts_triggered += 1

        state.last_scan = datetime.utcnow()
        state.scan_count += 1
        state.last_regime = regime
        state.last_structure_bias = structure_bias
        state.last_direction = direction_bias

        result = ScanResult(
            symbol=symbol,
            timestamp=state.last_scan,
            regime=regime,
            structure_bias=structure_bias,
            confidence=confidence,
            direction_bias=direction_bias,
            actionable=actionable,
            notes=tuple(notes),
        )

        for callback in self._callbacks:
            try:
                callback(result)
            except Exception:
                pass

        return result

    async def _fetch_recent_ticks(self, symbol: str, count: int) -> list:
        from synthetic_trader.data.collector import deriv_credentials_from_env
        from synthetic_trader.execution.deriv_ws import DerivWebSocketClient
        from synthetic_trader.execution.venues import MarketDataClient

        credentials = deriv_credentials_from_env()
        async with DerivWebSocketClient(credentials) as client:
            ticks = await client.ticks_history(symbol=symbol, count=count, end="latest")
        return ticks

    def _build_candles(self, ticks: list, profile) -> dict[int, list[Candle]]:
        from synthetic_trader.data.candles import MultiTimeframeCandleBuilder

        timeframes = [
            profile.bias_timeframe_sec,
            profile.setup_timeframe_sec,
            profile.confirmation_timeframe_sec,
            profile.execution_timeframe_sec,
        ]
        builder = MultiTimeframeCandleBuilder(profile.symbol, timeframes)
        histories: dict[int, list[Candle]] = {tf: [] for tf in timeframes}

        for tick in ticks:
            closed = builder.update(tick)
            for tf, candle in closed.items():
                histories.setdefault(tf, []).append(candle)

        flushed = builder.flush()
        for tf, candle in flushed.items():
            histories.setdefault(tf, []).append(candle)

        return histories


async def run_background_scan(
    config: TraderConfig,
    symbols: list[str],
    duration_sec: int,
    scan_interval_sec: int = 300,
) -> list[ScanResult]:
    decision_engine = DecisionEngine(config)
    scanner = BackgroundScanner(
        config=config,
        decision_engine=decision_engine,
        symbols=symbols,
        scan_interval_sec=scan_interval_sec,
    )
    results: list[ScanResult] = []

    def collect(result: ScanResult) -> None:
        results.append(result)

    scanner.register_callback(collect)
    await scanner.start()
    await asyncio.sleep(duration_sec)
    await scanner.stop()
    return results