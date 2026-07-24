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


def hurst_exponent(values: list[float], max_lag: int = 20) -> float:
    if len(values) < max_lag + 10:
        return 0.5
    lags = list(range(2, min(max_lag, len(values) // 2)))
    if not lags:
        return 0.5
    tau = []
    for lag in lags:
        diff = [values[i + lag] - values[i] for i in range(len(values) - lag)]
        if diff:
            tau.append(math.sqrt(sum(d * d for d in diff) / len(diff)))
        else:
            tau.append(0.0)
    if len(tau) < 2 or all(t == 0 for t in tau):
        return 0.5
    log_lags = [math.log(lag) for lag in lags]
    log_tau = [math.log(t) if t > 0 else 0.0 for t in tau]
    n = len(log_lags)
    x_mean = mean(log_lags)
    y_mean = mean(log_tau)
    numerator = sum((log_lags[i] - x_mean) * (log_tau[i] - y_mean) for i in range(n))
    denominator = sum((log_lags[i] - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.5
    return clamp(numerator / denominator * 2.0, 0.0, 1.0)


def shannon_entropy(values: list[float], bins: int = 10) -> float:
    if len(values) < bins:
        return 0.0
    min_v, max_v = min(values), max(values)
    if max_v == min_v:
        return 0.0
    bin_edges = [min_v + (max_v - min_v) * i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - min_v) / (max_v - min_v) * bins))
        counts[idx] += 1
    total = sum(counts)
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy / math.log2(bins)


def volatility_clustering(returns: list[float], period: int = 20) -> float:
    if len(returns) < period + 1:
        return 0.0
    abs_returns = [abs(r) for r in returns[-period:]]
    squared_returns = [r * r for r in returns[-period:]]
    mean_abs = mean(abs_returns)
    mean_sq = mean(squared_returns)
    if mean_abs == 0:
        return 0.0
    return clamp(mean_sq / (mean_abs * mean_abs), 0.0, 5.0)


def realized_volatility(returns: list[float], period: int) -> float:
    window = returns[-period:]
    if len(window) < 2:
        return 0.0
    return pstdev(window) * math.sqrt(len(window))


def keltner_channels(candles: list[Candle], period: int = 20, mult: float = 2.0) -> tuple[float, float, float]:
    if len(candles) < period:
        return (0.0, 0.0, 0.0)
    typical_prices = [(c.high + c.low + c.close) / 3.0 for c in candles[-period:]]
    middle = mean(typical_prices)
    atr_val = atr(candles[-period:], period)
    upper = middle + mult * atr_val
    lower = middle - mult * atr_val
    return (upper, middle, lower)


def donchian_channels(candles: list[Candle], period: int = 20) -> tuple[float, float, float]:
    if len(candles) < period:
        return (0.0, 0.0, 0.0)
    upper = max(c.high for c in candles[-period:])
    lower = min(c.low for c in candles[-period:])
    middle = (upper + lower) / 2.0
    return (upper, middle, lower)


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

    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]

    hurst = hurst_exponent(closes) if len(closes) >= 50 else 0.5
    entropy = shannon_entropy(returns[-50:]) if len(returns) >= 50 else 0.0
    vol_cluster = volatility_clustering(returns) if len(returns) >= 20 else 0.0
    realized_vol = realized_volatility(returns, 20) if len(returns) >= 20 else 0.0

    kc_upper, kc_middle, kc_lower = keltner_channels(candles)
    dc_upper, dc_middle, dc_lower = donchian_channels(candles)

    kc_position = safe_div(last.close - kc_lower, kc_upper - kc_lower, 0.5) if kc_upper != kc_lower else 0.5
    dc_position = safe_div(last.close - dc_lower, dc_upper - dc_lower, 0.5) if dc_upper != dc_lower else 0.5

    atr_ratio = safe_div(atr_14, atr_50, 1.0)
    atr_z = 0.0
    if len(candles) >= 20 and atr_50 > 0:
        atr_z = (atr_14 - atr_50) / (atr_50 * 0.1 + 1e-9)

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
        "atr_ratio": atr_ratio,
        "atr_z_20": atr_z,
        "range_z_50": zscore(last.range, ranges, 50),
        "body_z_50": zscore(last.body_abs, [abs(item) for item in bodies], 50),
        "realized_vol_20": realized_vol,
        "position_in_20_range": clamp(position_in_range, 0.0, 1.0),
        "close_vs_ema_21_atr": safe_div(last.close - ema_21, atr_14),
        "close_vs_ema_50_atr": safe_div(last.close - ema_50, atr_14),
        "hurst_exponent": hurst,
        "entropy": entropy,
        "volatility_clustering": vol_cluster,
        "kc_position": kc_position,
        "dc_position": dc_position,
    }
