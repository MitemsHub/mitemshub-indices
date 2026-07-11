from __future__ import annotations

import math
from statistics import mean, pstdev

from synthetic_trader.domain import Candle


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(denominator) < 1e-12:
        return default
    return numerator / denominator


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    window = values[-period:]
    return mean(window)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    current = values[0]
    for value in values[1:]:
        current = alpha * value + (1.0 - alpha) * current
    return current


def rolling_std(values: list[float], period: int) -> float:
    window = values[-period:]
    if len(window) < 2:
        return 0.0
    return pstdev(window)


def zscore(value: float, values: list[float], period: int) -> float:
    window = values[-period:]
    if len(window) < 2:
        return 0.0
    sigma = pstdev(window)
    return safe_div(value - mean(window), sigma)


def rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes[-period - 1 : -1], closes[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = mean(gains)
    avg_loss = mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def true_ranges(candles: list[Candle]) -> list[float]:
    if not candles:
        return []
    ranges = [candles[0].range]
    for previous, current in zip(candles[:-1], candles[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return ranges


def atr(candles: list[Candle], period: int = 14) -> float:
    ranges = true_ranges(candles)
    if not ranges:
        return 0.0
    return mean(ranges[-period:])


def linear_slope(values: list[float], period: int) -> float:
    window = values[-period:]
    n = len(window)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = mean(window)
    numerator = sum((i - x_mean) * (value - y_mean) for i, value in enumerate(window))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    return safe_div(numerator, denominator)


def percentile_rank(value: float, values: list[float]) -> float:
    if not values:
        return 0.5
    below = sum(1 for item in values if item <= value)
    return below / len(values)


def candle_feature_set(candles: list[Candle]) -> dict[str, float]:
    if not candles:
        return {}

    closes = [candle.close for candle in candles]
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    bodies = [candle.body for candle in candles]
    ranges = [candle.range for candle in candles]
    last = candles[-1]
    atr_14 = atr(candles, 14)
    atr_50 = atr(candles, 50)
    ema_9 = ema(closes, 9)
    ema_21 = ema(closes, 21)
    ema_50 = ema(closes, 50)
    slope_20 = linear_slope(closes, 20)
    last_return = safe_div(closes[-1] - closes[-2], closes[-2]) if len(closes) > 1 else 0.0
    log_return = math.log(closes[-1] / closes[-2]) if len(closes) > 1 and closes[-2] > 0 else 0.0
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    position_in_range = safe_div(last.close - recent_low, recent_high - recent_low, 0.5)

    return {
        "close": last.close,
        "last_return": last_return,
        "log_return": log_return,
        "range": last.range,
        "body": last.body,
        "body_to_range": safe_div(last.body_abs, last.range),
        "upper_wick_to_range": safe_div(last.high - max(last.open, last.close), last.range),
        "lower_wick_to_range": safe_div(min(last.open, last.close) - last.low, last.range),
        "rsi_14": rsi(closes, 14),
        "ema_9": ema_9,
        "ema_21": ema_21,
        "ema_50": ema_50,
        "ema_9_21_spread_atr": safe_div(ema_9 - ema_21, atr_14),
        "ema_21_50_spread_atr": safe_div(ema_21 - ema_50, atr_14),
        "slope_20_atr": safe_div(slope_20, atr_14),
        "atr_14": atr_14,
        "atr_50": atr_50,
        "atr_ratio": safe_div(atr_14, atr_50, 1.0),
        "range_z_50": zscore(last.range, ranges, 50),
        "body_z_50": zscore(last.body_abs, [abs(item) for item in bodies], 50),
        "realized_vol_20": rolling_std([candle.body for candle in candles], 20),
        "position_in_20_range": clamp(position_in_range, 0.0, 1.0),
        "close_vs_ema_21_atr": safe_div(last.close - ema_21, atr_14),
        "close_vs_ema_50_atr": safe_div(last.close - ema_50, atr_14),
    }
