"""MT5 tick data collector for EGARCH calibration.

Collects real tick data from Blueberry Markets via MT5 IPC connection
and saves it to CSV for EGARCH parameter fitting.

Usage:
    python -m synthetic_trader collect-ticks --symbol SYN100 --duration 300
    python -m synthetic_trader collect-ticks --symbol Volatility 100 Index --count 10000
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
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


# Symbol mapping: internal name → MT5 venue symbol
BLUEBERRY_SYMBOL_MAP: dict[str, str] = {
    "SYN50": "SYN50",
    "SYN75": "SYN75",
    "SYN100": "SYN100",
    "SURGE50": "SURGE50",
    "SURGE75": "SURGE75",
    "SURGE100": "SURGE100",
    "DROP50": "DROP50",
    "DROP75": "DROP75",
    "DROP100": "DROP100",
    "LEAP50": "LEAP50",
    "LEAP75": "LEAP75",
    "LEAP100": "LEAP100",
}

DERIV_SYMBOL_MAP: dict[str, str] = {
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
    "V75": "Boom 1000 Index",
    "V100": "Crash 1000 Index",
}


def get_venue_symbol(symbol: str) -> str:
    """Resolve internal symbol to MT5 venue symbol."""
    upper = symbol.upper()
    if upper in BLUEBERRY_SYMBOL_MAP:
        return BLUEBERRY_SYMBOL_MAP[upper]
    if symbol in DERIV_SYMBOL_MAP:
        return DERIV_SYMBOL_MAP[symbol]
    return symbol  # Pass through as-is
