"""MT5 tick data collector for EGARCH calibration.

Collects real tick data from Deriv via MT5 IPC connection
and saves it to CSV for EGARCH parameter fitting.

Usage:
    python -m synthetic_trader collect-ticks --symbol SYN100 --duration 300
    python -m synthetic_trader collect-ticks --symbol Volatility 100 Index --count 10000
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class CollectedTicks:
    """Result of tick collection session."""
    symbol: str
    venue_symbol: str
    ticks_collected: int
    duration_sec: float
    output_path: str
    first_price: float
    last_price: float
    min_price: float
    max_price: float
    mean_spread: float
    price_range_pct: float

    def summary(self) -> str:
        return (
            f"symbol={self.symbol}\n"
            f"venue_symbol={self.venue_symbol}\n"
            f"ticks={self.ticks_collected}\n"
            f"duration={self.duration_sec:.1f}s\n"
            f"output={self.output_path}\n"
            f"first_price={self.first_price:.5f}\n"
            f"last_price={self.last_price:.5f}\n"
            f"min_price={self.min_price:.5f}\n"
            f"max_price={self.max_price:.5f}\n"
            f"mean_spread={self.mean_spread:.6f}\n"
            f"price_range={self.price_range_pct:.4f}%"
        )


def collect_ticks_from_mt5(
    symbol: str,
    venue_symbol: str,
    duration_sec: int = 300,
    max_ticks: int = 10000,
    output_path: str | Path = "data/calibration_ticks.csv",
    server: str | None = None,
    login: int | None = None,
    password: str | None = None,
    terminal_path: str | None = None,
) -> CollectedTicks:
    """Collect ticks from MT5 via IPC and save to CSV.

    Parameters
    ----------
    symbol : str
        Internal symbol name (e.g., "SYN100", "R_100")
    venue_symbol : str
        MT5 symbol name (e.g., "Volatility 100 Index")
    duration_sec : int
        How long to collect ticks (seconds)
    max_ticks : int
        Maximum number of ticks to collect
    output_path : str | Path
        CSV output path
    server, login, password, terminal_path : str, optional
        MT5 connection credentials
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise RuntimeError("MetaTrader5 module not available. Install MT5 terminal.")

    # Initialize MT5 connection
    init_kwargs = {}
    if terminal_path:
        init_kwargs["path"] = terminal_path

    if not mt5.initialize(**init_kwargs):
        error = mt5.last_error()
        raise RuntimeError(f"MT5 initialize failed: {error}")

    try:
        if login:
            authorized = mt5.login(
                login,
                password=password or "",
                server=server or "",
            )
            if not authorized:
                error = mt5.last_error()
                raise RuntimeError(f"MT5 login failed: {error}")

        # Subscribe to tick stream
        if not mt5.symbol_select(venue_symbol, True):
            error = mt5.last_error()
            raise RuntimeError(f"Failed to select {venue_symbol}: {error}")

        # Wait for tick data to be available
        time.sleep(1.0)

        # Check if symbol info is available
        symbol_info = mt5.symbol_info(venue_symbol)
        if symbol_info is None:
            raise RuntimeError(f"Symbol info not found for {venue_symbol}")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        prices: list[float] = []
        spreads: list[float] = []
        junk_skipped = 0
        start = time.time()
        last_tick_time = 0.0

        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["epoch", "symbol", "price", "bid", "ask", "spread",
                           "tick_direction", "volume_proxy", "last"])

            while (time.time() - start) < duration_sec and len(prices) < max_ticks:
                tick = mt5.copy_ticks(venue_symbol, 1, mt5.COPY_TICKS_INFO)

                if tick is None or len(tick) == 0:
                    time.sleep(0.01)
                    continue

                t = tick[0]
                epoch = t.time_msc / 1000.0
                bid = t.bid
                ask = t.ask
                price = (bid + ask) / 2.0
                spread = ask - bid

                # Skip duplicate ticks (same timestamp)
                if epoch <= last_tick_time:
                    time.sleep(0.005)
                    continue

                # ── Price sanity guard ─────────────────────────────
                # Intermittent MT5 read errors produce junk bid/ask (e.g.
                # ~6950 for R_75 which trades ~1850 — a 3.7x error) that
                # pollute the corpus and show bogus prices in the dashboard
                # feed.  Reject a tick whose mid deviates >50% from the
                # recent median (same rule the candle builder uses) so junk
                # never reaches the CSV in the first place.
                if len(prices) >= 10:
                    window = sorted(prices[-100:])
                    med = window[len(window) // 2]
                    if abs(price - med) / med > 0.5:
                        junk_skipped += 1
                        time.sleep(0.015)
                        continue

                last_tick_time = epoch

                # Determine tick direction
                if len(prices) > 0:
                    if price > prices[-1]:
                        direction = 1
                    elif price < prices[-1]:
                        direction = -1
                    else:
                        direction = 0
                else:
                    direction = 0

                # Volume proxy from tick volume
                volume_proxy = max(0.1, float(t.volume_real) if hasattr(t, 'volume_real') else 1.0)

                writer.writerow([
                    f"{epoch:.3f}",
                    symbol,
                    f"{price:.5f}",
                    f"{bid:.5f}",
                    f"{ask:.5f}",
                    f"{spread:.6f}",
                    direction,
                    f"{volume_proxy:.4f}",
                    "1" if len(prices) == 0 else "0",
                ])

                prices.append(price)
                spreads.append(spread)

                time.sleep(0.015)  # 15ms between polls (safe for all MT5 implementations)

        duration = time.time() - start
        mean_spread = sum(spreads) / max(len(spreads), 1)
        price_range = (max(prices) - min(prices)) / min(prices) * 100 if prices else 0.0

        if junk_skipped:
            print(
                f"[collector] {symbol}: skipped {junk_skipped} junk ticks "
                f"(price >50% off recent median) — source-level outlier guard",
                flush=True,
            )

        return CollectedTicks(
            symbol=symbol,
            venue_symbol=venue_symbol,
            ticks_collected=len(prices),
            duration_sec=duration,
            output_path=str(output),
            first_price=prices[0] if prices else 0.0,
            last_price=prices[-1] if prices else 0.0,
            min_price=min(prices) if prices else 0.0,
            max_price=max(prices) if prices else 0.0,
            mean_spread=mean_spread,
            price_range_pct=price_range,
        )

    finally:
        mt5.shutdown()


# Symbol mapping: internal name → MT5 venue symbol.
# Single authoritative map (a stale SYN-series dict used to shadow this one
# before the 2026-08-25 alignment audit removed it).
DERIV_SYMBOL_MAP: dict[str, str] = {
    # VERIFIED LIVE 2026-08-25 via scripts/mt5_probe.py against the actual
    # terminal (730 symbols enumerated): the display names exist and are
    # FULL-tradeable. There are NO "SYNxx" symbols on this terminal — the
    # earlier SYN claim was stale/wrong. (1s) variants exist alongside the
    # standard pairs and have DIFFERENT contract specs.
    # Also fixed here historically: V75/V100 were once mapped to Boom/Crash
    # 1000 — completely different one-directional instruments.
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
    "V75": "Volatility 75 Index",
    "V100": "Volatility 100 Index",
}


def get_venue_symbol(symbol: str) -> str:
    """Resolve internal symbol to MT5 venue symbol."""
    upper = symbol.upper()
    if upper in DERIV_SYMBOL_MAP:
        return DERIV_SYMBOL_MAP[upper]
    if symbol in DERIV_SYMBOL_MAP:
        return DERIV_SYMBOL_MAP[symbol]
    return symbol  # Pass through as-is


def fetch_m1_candles(
    symbol: str,
    *,
    since_epoch: float,
    venue_symbol: str | None = None,
    terminal_path: str | None = None,
    max_rates: int = 100_000,
) -> list[dict[str, float]]:
    """Fetch closed M1 OHLC candles from the Deriv MT5 terminal.

    Returns candles (each ``{'epoch', 'open', 'high', 'low', 'close'}``)
    ascending by epoch, covering ``[since_epoch, now]``.  The still-forming
    candle at the current minute boundary is NOT included (MT5's
    ``copy_rates_range`` returns it, but its OHLC is not final — consumers
    must wait for it to close).  An empty list means no history in range
    (e.g. mid-rollover or symbol not trading).

    This is the fetch core shared by the one-shot backfill
    (:func:`collect_mt5_candle_history`) and the continuous M1 capture
    loop (``data.m1_capture``).  When ``terminal_path`` is omitted, the
    terminal is resolved with the same registry/Program-Files scan the
    live MT5 path uses (``mt5_data._resolve_mt5_terminal_path``) so the
    Deriv terminal is preferred over other MT5 installs on the machine.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise RuntimeError("MetaTrader5 module not available. Install MT5 terminal.")

    venue = venue_symbol or get_venue_symbol(symbol)

    # Resolve the terminal executable: explicit arg, else the same scan the
    # live path uses (avoids silently attaching to the wrong MT5 install).
    resolved_terminal = terminal_path
    if not resolved_terminal:
        from synthetic_trader.execution.mt5_data import _resolve_mt5_terminal_path

        resolved_terminal = _resolve_mt5_terminal_path()

    init_kwargs = {}
    if resolved_terminal:
        init_kwargs["path"] = resolved_terminal

    if not mt5.initialize(**init_kwargs):
        error = mt5.last_error()
        raise RuntimeError(f"MT5 initialize failed: {error} (path: {resolved_terminal})")

    try:
        if not mt5.symbol_select(venue, True):
            error = mt5.last_error()
            raise RuntimeError(f"Failed to select {venue}: {error}")

        now = datetime.now(timezone.utc)
        start = datetime.fromtimestamp(since_epoch, tz=timezone.utc)
        rates = mt5.copy_rates_range(venue, mt5.TIMEFRAME_M1, start, now)
        if rates is None or len(rates) == 0:
            return []
        if len(rates) > max_rates:
            rates = rates[-max_rates:]

        candles: list[dict[str, float]] = []
        for row in rates:
            candles.append(
                {
                    "epoch": float(row["time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
        candles.sort(key=lambda c: c["epoch"])
        # Drop the still-forming candle at the current minute boundary.
        now_bucket = int(now.timestamp()) // 60 * 60
        candles = [c for c in candles if float(c["epoch"]) < now_bucket]
        # ── Garbage-row defense ───────────────────────────────────
        # ``copy_rates_range`` can hand back rows with uninitialised/garbage
        # values when the terminal is still downloading history for the
        # requested range (epochs near 0 or in the far future, prices of
        # 0.0/1.0/4.0).  These would poison the compounding corpus if merged
        # unfiltered, so drop anything that is not a plausible M1 candle:
        # epoch after year 2001, not in the future, and sane OHLC values.
        now_ts = now.timestamp()
        candles = [
            c for c in candles
            if 1_000_000_000 <= float(c["epoch"]) <= now_ts + 3600
            and min(float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])) > 0.0
        ]
        return candles
    finally:
        mt5.shutdown()


def collect_mt5_candle_history(
    symbol: str,
    days: float,
    output_path: str | Path,
    venue_symbol: str | None = None,
    terminal_path: str | None = None,
    max_rates: int = 100_000,
) -> "CollectedTicks":
    """Backfill *days* of 1-minute OHLC history from the MT5 terminal.

    Deriv's WebSocket API only serves a rolling ~5000-tick buffer and its
    candle symbols (1HZ75V / 1HZ100V) trade at DIFFERENT price levels than
    Deriv instruments (SYN75 / SYN100).  The only correct
    source of multi-day history for the instruments the user actually
    trades is the Deriv MT5 terminal itself — ``copy_rates_range``
    returns server-backed M1 OHLC that goes back days.

    The M1 candles are expanded into an OHLC-exact tick stream (4 ticks
    per candle, via ``candles_to_ticks``) so downstream candle builders
    at 60s/300s reproduce the original OHLC exactly — the same
    reconstruction used by the Deriv candle backfill.  M1 is always used
    as the base spacing so 60s and 300s candle builders stay correct
    (a 300s-sourced tick stream would put all 4 ticks inside the first
    60s sub-slice and break 60s builders).

    Returns a :class:`CollectedTicks` describing the written dataset.
    """
    from synthetic_trader.data.collector import candles_to_ticks
    from synthetic_trader.data.tick_store import normalize_ticks, write_ticks_csv

    if days <= 0:
        raise ValueError("days must be positive")

    # Resolve venue symbol on the terminal (SYN75/SYN100 for R_75/R_100)
    venue = venue_symbol or get_venue_symbol(symbol)
    now = datetime.now(timezone.utc)
    candles = fetch_m1_candles(
        symbol,
        since_epoch=(now - timedelta(days=days)).timestamp(),
        venue_symbol=venue_symbol,
        terminal_path=terminal_path,
        max_rates=max_rates,
    )
    if not candles:
        raise RuntimeError(
            f"No M1 rates returned for {venue} — symbol not visible "
            f"or history unavailable. Set SYNTHETIC_MT5_SYMBOL_MAP in .env.local."
        )

    # Always expand at 60s so 60s AND 300s downstream builders are correct.
    ticks = candles_to_ticks(symbol, candles, timeframe_sec=60)
    normalized, _ = normalize_ticks(ticks)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_ticks_csv(output, normalized, append=False)

    prices = [t.price for t in normalized]
    return CollectedTicks(
        symbol=symbol,
        venue_symbol=venue,
        ticks_collected=len(normalized),
        duration_sec=days * 86400.0,
        output_path=str(output),
        first_price=prices[0] if prices else 0.0,
        last_price=prices[-1] if prices else 0.0,
        min_price=min(prices) if prices else 0.0,
        max_price=max(prices) if prices else 0.0,
        mean_spread=0.0,
        price_range_pct=(
            (max(prices) - min(prices)) / min(prices) * 100 if prices else 0.0
        ),
    )
