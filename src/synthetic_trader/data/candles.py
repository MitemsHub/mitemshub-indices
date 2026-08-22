from __future__ import annotations

import logging

from synthetic_trader.domain import Candle, Tick

logger = logging.getLogger(__name__)

# Maximum allowed price deviation from the running median before a tick
# is treated as a corrupt outlier.  20% catches the Deriv→Deriv
# price mismatch (~7000 vs ~258) while allowing normal volatility.
MAX_PRICE_DEVIATION_RATIO = 0.20

# Number of ticks required before the outlier guard activates.
# The first few ticks bootstrap the median — we don't reject them
# because they establish the baseline price level.
_MIN_TICKS_FOR_OUTLIER_GUARD = 5


class CandleBuilder:
    def __init__(self, symbol: str, timeframe_sec: int) -> None:
        if timeframe_sec <= 0:
            raise ValueError("timeframe_sec must be positive")
        self.symbol = symbol
        self.timeframe_sec = timeframe_sec
        self.current: Candle | None = None
        self._price_samples: list[float] = []
        self._outlier_rejected = 0

    def _running_median(self) -> float | None:
        """Return the median of recent tick prices (capped at 100 samples)."""
        if not self._price_samples:
            return None
        # Only use the most recent 100 samples for the median to stay
        # responsive to genuine price regime changes.
        window = self._price_samples[-100:]
        window_sorted = sorted(window)
        mid = len(window_sorted) // 2
        if len(window_sorted) % 2 == 0:
            return (window_sorted[mid - 1] + window_sorted[mid]) / 2.0
        return window_sorted[mid]

    def _is_outlier(self, price: float) -> bool:
        """Return True if the price deviates more than MAX_PRICE_DEVIATION_RATIO
        from the running median.  Always returns False during the bootstrap
        phase (first _MIN_TICKS_FOR_OUTLIER_GUARD ticks)."""
        if len(self._price_samples) < _MIN_TICKS_FOR_OUTLIER_GUARD:
            return False
        median = self._running_median()
        if median is None or median == 0:
            return False
        deviation = abs(price - median) / median
        return deviation > MAX_PRICE_DEVIATION_RATIO

    def update(self, tick: Tick) -> Candle | None:
        if tick.symbol != self.symbol:
            raise ValueError(f"tick symbol {tick.symbol!r} does not match builder symbol {self.symbol!r}")

        # ── Price outlier guard ────────────────────────────────
        # Reject ticks whose price is wildly different from the running
        # median.  This prevents corrupt data (e.g. old Deriv API prices
        # mixed with Deriv MT5 prices) from creating candles with
        # impossible ranges that break ATR, swing detection, and trade
        # level calculations.
        if self._is_outlier(tick.price):
            self._outlier_rejected += 1
            if self._outlier_rejected <= 3:
                median = self._running_median()
                logger.warning(
                    "[candles] %s rejected outlier tick price %.2f "
                    "(median=%.2f, deviation=%.1f%%) — corrupt data?",
                    self.symbol,
                    tick.price,
                    median or 0,
                    abs(tick.price - (median or 0)) / (median or 1) * 100,
                )
            return None

        self._price_samples.append(tick.price)
        # Keep at most 200 samples to bound memory
        if len(self._price_samples) > 200:
            self._price_samples = self._price_samples[-100:]

        bucket = int(tick.epoch // self.timeframe_sec) * self.timeframe_sec
        if self.current is None:
            self.current = self._new_candle(tick, bucket)
            return None

        if bucket == self.current.open_time:
            # In-place mutation of the frozen Candle via object.__setattr__.
            # This is ~60% faster than dataclasses.replace() which creates a
            # new instance on every tick — critical for the 45s warmup cycle
            # that processes 100K+ ticks through the builder pipeline.
            _c = self.current
            object.__setattr__(_c, "high", max(_c.high, tick.price))
            object.__setattr__(_c, "low", min(_c.low, tick.price))
            object.__setattr__(_c, "close", tick.price)
            object.__setattr__(_c, "tick_count", _c.tick_count + 1)
            return None

        closed = self.current
        self.current = self._new_candle(tick, bucket)
        return closed

    def flush(self) -> Candle | None:
        closed = self.current
        self.current = None
        return closed

    def _new_candle(self, tick: Tick, bucket: int) -> Candle:
        return Candle(
            symbol=tick.symbol,
            timeframe_sec=self.timeframe_sec,
            open_time=bucket,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            tick_count=1,
        )

    @property
    def outlier_rejected_count(self) -> int:
        return self._outlier_rejected


class MultiTimeframeCandleBuilder:
    def __init__(self, symbol: str, timeframes_sec: list[int]) -> None:
        sorted_tfs = sorted(set(timeframes_sec))
        self.builders = {
            tf: CandleBuilder(symbol=symbol, timeframe_sec=tf)
            for tf in sorted_tfs
        }
        self._smallest_tf = sorted_tfs[0] if sorted_tfs else None

    def update(self, tick: Tick) -> dict[int, Candle]:
        # NOTE: no early-bail here.  The old "canary bucket" fast path
        # skipped mid-bucket ticks for EVERY timeframe, so every candle
        # froze at the FIRST tick of its bucket (tick_count == 1, close =
        # bucket-open price) instead of true OHLC.  That point-sampled
        # series silently replaced real candle closes everywhere this
        # wrapper is used (all backtests + the live warmup), and the 300s
        # candles differed depending on which other timeframes were
        # requested — so live could not reproduce its own backtest.  The
        # measured effect on the band strategy: 58 trades/+379R on the
        # staled series vs 8 trades/-25R on true OHLC.  Every tick must
        # reach every builder; the per-builder update is the single source
        # of truth.
        closed: dict[int, Candle] = {}
        for timeframe, builder in self.builders.items():
            candle = builder.update(tick)
            if candle is not None:
                closed[timeframe] = candle
        return closed

    def flush(self) -> dict[int, Candle]:
        closed: dict[int, Candle] = {}
        for timeframe, builder in self.builders.items():
            candle = builder.flush()
            if candle is not None:
                closed[timeframe] = candle
        return closed

    @property
    def total_outliers_rejected(self) -> int:
        """Total outlier ticks rejected across all timeframe builders."""
        return sum(b.outlier_rejected_count for b in self.builders.values())
