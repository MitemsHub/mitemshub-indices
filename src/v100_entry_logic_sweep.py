#!/usr/bin/env python3
"""V100 ENTRY LOGIC SWEEP — Test every known trading edge"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime

mt5.initialize()
sym = "Volatility 100 Index"
mt5.symbol_select(sym, True)
info = mt5.symbol_info(sym)
dpp = info.trade_tick_value / info.trade_tick_size * info.point
acc = mt5.account_info()
margin_per_lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 1, info.ask)
if not margin_per_lot or margin_per_lot <= 0:
    margin_per_lot = info.ask * info.trade_contract_size / acc.leverage
equity = acc.equity
max_lots = min(int(equity * 0.70 / margin_per_lot), info.volume_max)
spread_price = info.spread * info.point

# Get M5 data
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 5000)
closes = rates['close']
highs = rates['high']
lows = rates['low']
opens = rates['open']
n = len(closes)

# Also get H4 for regime
rates_h4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 500)
closes_h4 = rates_h4['close']
highs_h4 = rates_h4['high']
lows_h4 = rates_h4['low']
opens_h4 = rates_h4['open']
times_h4 = rates_h4['time']
n_h4 = len(closes_h4)

print("=" * 80)
print("  V100 ENTRY LOGIC SWEEP — Every known trading edge")
print("=" * 80)
print(f"  M5 bars: {n} | H4 bars: {n_h4}")

# === INDICATORS ===
def ema(data, period):
    r = np.zeros_like(data, dtype=float)
    r[0] = data[0]
    k = 2.0 / (period + 1)
    for i in range(1, len(data)):
        r[i] = data[i] * k + r[i-1] * (1 - k)
    return r

def rsi(data, period=14):
    r = np.zeros(len(data))
    for i in range(period, len(data)):
        deltas = np.diff(data[i-period:i+1])
        gains = np.sum(np.maximum(deltas, 0))
        losses = np.sum(np.abs(np.minimum(deltas, 0)))
        r[i] = 100 if losses == 0 else 100 - 100 / (1 + gains / losses)
    return r

def atr(highs, lows, closes, period=14):
    a = np.zeros(len(closes))
    for i in range(period, len(closes)):
        trs = [max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1])) for j in range(i-period+1, i+1)]
        a[i] = np.mean(trs)
    return a

def macd(data, fast=12, slow=26, signal=9):
    ema_fast = ema(data, fast)
    ema_slow = ema(data, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def stochastic(highs, lows, closes, k_period=14, d_period=3):
    n = len(closes)
    k = np.zeros(n)
    d = np.zeros(n)
    for i in range(k_period, n):
        lowest = min(lows[i-k_period+1:i+1])
        highest = max(highs[i-k_period+1:i+1])
        if highest != lowest:
            k[i] = (closes[i] - lowest) / (highest - lowest) * 100
        else:
            k[i] = 50
    for i in range(d_period, n):
        d[i] = np.mean(k[i-d_period+1:i+1])
    return k, d

def bollinger(data, period=20, std_mult=2):
    n = len(data)
    mid = np.zeros(n)
    upper = np.zeros(n)
    lower = np.zeros(n)
    for i in range(period, n):
        mid[i] = np.mean(data[i-period+1:i+1])
        std = np.std(data[i-period+1:i+1])
        upper[i] = mid[i] + std_mult * std
        lower[i] = mid[i] - std_mult * std
    return mid, upper, lower

# Calculate all indicators
ema20 = ema(closes, 20)
ema50 = ema(closes, 50)
ema100 = ema(closes, 100)
rsi14 = rsi(closes, 14)
atr14 = atr(highs, lows, closes, 14)
macd_line, macd_signal, macd_hist = macd(closes)
stoch_k, stoch_d = stochastic(highs, lows, closes)
bb_mid, bb_upper, bb_lower = bollinger(closes)

# H4 regime
ema20_h4 = ema(closes_h4, 20)
ema50_h4 = ema(closes_h4, 50)
ema100_h4 = ema(closes_h4, 100)

# H4 regime direction (map back to M5)
h4_regime = np.zeros(n_h4)
for i in range(100, n_h4):
    if ema20_h4[i] > ema50_h4[i] > ema100_h4[i]:
        h4_regime[i] = 1  # BULLISH
    elif ema20_h4[i] < ema50_h4[i] < ema100_h4[i]:
        h4_regime[i] = -1  # BEARISH
    else:
        h4_regime[i] = 0  # RANGING

# Map H4 regime to M5
h4_regime_m5 = np.zeros(n)
for i in range(n):
    # Find which H4 bar this M5 bar falls in
    m5_time = rates['time'][i]
    h4_idx = np.searchsorted(times_h4, m5_time, side='right') - 1
    h4_idx = max(0, min(h4_idx, n_h4 - 1))
    h4_regime_m5[i] = h4_regime[h4_idx]

# === BACKTEST ENGINE ===
def backtest(signals, lots=25, sl=1.0, tp=3.0, max_hold=10, warmup=100):
    """signals: array of 1 (buy), -1 (sell), 0 (no signal)"""
    equity_val = 0.0
    trades = []
    in_trade = False
    entry_p = 0
    entry_d = 0
    sl_p = 0
    tp_p = 0
    bars_held = 0
    
    for i in range(warmup, n):
        if in_trade:
            bars_held += 1
            if entry_d > 0:
                if lows[i] <= sl_p:
                    trades.append((sl_p - entry_p - spread_price) * lots * dpp)
                    in_trade = False
                    continue
                if highs[i] >= tp_p:
                    trades.append((tp_p - entry_p - spread_price) * lots * dpp)
                    in_trade = False
                    continue
            else:
                if highs[i] >= sl_p:
                    trades.append((entry_p - sl_p - spread_price) * lots * dpp)
                    in_trade = False
                    continue
                if lows[i] <= tp_p:
                    trades.append((entry_p - tp_p - spread_price) * lots * dpp)
                    in_trade = False
                    continue
            if bars_held >= max_hold:
                if entry_d > 0:
                    trades.append((closes[i] - entry_p - spread_price) * lots * dpp)
                else:
                    trades.append((entry_p - closes[i] - spread_price) * lots * dpp)
                in_trade = False
            continue
        
        if signals[i] != 0:
            entry_p = closes[i]
            entry_d = signals[i]
            if entry_d > 0:
                sl_p = entry_p - sl
                tp_p = entry_p + tp
            else:
                sl_p = entry_p + sl
                tp_p = entry_p - tp
            in_trade = True
            bars_held = 0
    
    if not trades:
        return None
    
    pnls = np.array(trades)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    days = n / 288
    
    return {
        'trades': len(pnls),
        't_day': len(pnls) / days,
        'wr': len(wins) / len(pnls) * 100,
        'total': np.sum(pnls),
        'avg': np.mean(pnls),
        'pf': np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 and np.sum(losses) != 0 else 999,
        'max_dd': np.min(pnls),
    }

# === DEFINE ALL ENTRY LOGICS ===
print(f"\n{'='*80}")
print(f"  TESTING ALL ENTRY LOGICS")
print(f"{'='*80}")

results = []

# --- 1. MOMENTUM ENTRIES ---
# 1a. Bar body momentum
signals = np.zeros(n)
for i in range(1, n):
    body = closes[i] - opens[i]
    if abs(body) > 0.4 * atr14[i]:
        signals[i] = 1 if body > 0 else -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Momentum: Bar Body", r))

# 1b. Consecutive bars momentum
signals = np.zeros(n)
for i in range(3, n):
    if all(closes[i-j] > opens[i-j] for j in range(3)):
        signals[i] = 1  # 3 consecutive bullish
    elif all(closes[i-j] < opens[i-j] for j in range(3)):
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Momentum: 3 Consecutive Bars", r))

# 1c. Momentum with volume (range expansion)
signals = np.zeros(n)
for i in range(2, n):
    body = closes[i] - opens[i]
    range_now = highs[i] - lows[i]
    range_prev = highs[i-1] - lows[i-1]
    if range_now > 1.5 * range_prev and abs(body) > 0.5 * atr14[i]:
        signals[i] = 1 if body > 0 else -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Momentum: Range Expansion", r))

# 1d. Price velocity (rate of change)
signals = np.zeros(n)
for i in range(5, n):
    velocity = (closes[i] - closes[i-5]) / 5
    if velocity > 0.3 * atr14[i]:
        signals[i] = 1
    elif velocity < -0.3 * atr14[i]:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Momentum: Price Velocity", r))

# --- 2. BREAKOUT ENTRIES ---
# 2a. N-bar breakout
signals = np.zeros(n)
for i in range(20, n):
    hh = max(highs[i-20:i])
    ll = min(lows[i-20:i])
    if closes[i] > hh:
        signals[i] = 1
    elif closes[i] < ll:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Breakout: 20-Bar Range", r))

# 2b. Bollinger squeeze breakout
signals = np.zeros(n)
for i in range(25, n):
    bb_width = (bb_upper[i] - bb_lower[i]) / bb_mid[i] if bb_mid[i] > 0 else 0
    prev_width = (bb_upper[i-5] - bb_lower[i-5]) / bb_mid[i-5] if bb_mid[i-5] > 0 else 0
    if bb_width < 0.5 * prev_width:  # Squeeze
        if closes[i] > bb_upper[i]:
            signals[i] = 1
        elif closes[i] < bb_lower[i]:
            signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Breakout: BB Squeeze", r))

# 2c. Donchian channel breakout (10-bar)
signals = np.zeros(n)
for i in range(10, n):
    hh = max(highs[i-10:i])
    ll = min(lows[i-10:i])
    mid = (hh + ll) / 2
    if closes[i] > hh:
        signals[i] = 1
    elif closes[i] < ll:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Breakout: Donchian 10", r))

# --- 3. MEAN REVERSION ENTRIES ---
# 3a. RSI overbought/oversold fade
signals = np.zeros(n)
for i in range(14, n):
    if rsi14[i] > 75 and rsi14[i-1] > 70:
        signals[i] = -1  # Sell overbought
    elif rsi14[i] < 25 and rsi14[i-1] < 30:
        signals[i] = 1   # Buy oversold
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("MeanRev: RSI Extreme", r))

# 3b. Bollinger band bounce
signals = np.zeros(n)
for i in range(20, n):
    if closes[i-1] < bb_lower[i-1] and closes[i] > bb_lower[i]:
        signals[i] = 1  # Bounce off lower band
    elif closes[i-1] > bb_upper[i-1] and closes[i] < bb_upper[i]:
        signals[i] = -1  # Bounce off upper band
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("MeanRev: BB Bounce", r))

# 3c. Price vs EMA20 mean reversion
signals = np.zeros(n)
for i in range(20, n):
    deviation = (closes[i] - ema20[i]) / atr14[i] if atr14[i] > 0 else 0
    if deviation < -1.5:
        signals[i] = 1  # Oversold vs EMA
    elif deviation > 1.5:
        signals[i] = -1  # Overbought vs EMA
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("MeanRev: EMA Deviation", r))

# 3d. Double top/bottom (simplified)
signals = np.zeros(n)
for i in range(20, n):
    recent_high = max(highs[i-20:i])
    recent_low = min(lows[i-20:i])
    # Double top: price hits high twice
    hits_high = sum(1 for j in range(i-20, i) if abs(highs[j] - recent_high) < 0.3 * atr14[i])
    hits_low = sum(1 for j in range(i-20, i) if abs(lows[j] - recent_low) < 0.3 * atr14[i])
    if hits_high >= 2 and closes[i] < recent_high - 0.5 * atr14[i]:
        signals[i] = -1  # Double top breakdown
    elif hits_low >= 2 and closes[i] > recent_low + 0.5 * atr14[i]:
        signals[i] = 1   # Double bottom breakout
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("MeanRev: Double Top/Bottom", r))

# --- 4. TREND-FOLLOWING ENTRIES ---
# 4a. EMA crossover
signals = np.zeros(n)
for i in range(1, n):
    if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]:
        signals[i] = 1
    elif ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Trend: EMA Crossover", r))

# 4b. MACD crossover
signals = np.zeros(n)
for i in range(1, n):
    if macd_hist[i] > 0 and macd_hist[i-1] <= 0:
        signals[i] = 1
    elif macd_hist[i] < 0 and macd_hist[i-1] >= 0:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Trend: MACD Crossover", r))

# 4c. Stochastic crossover
signals = np.zeros(n)
for i in range(1, n):
    if stoch_k[i] > stoch_d[i] and stoch_k[i-1] <= stoch_d[i-1] and stoch_k[i] < 80:
        signals[i] = 1
    elif stoch_k[i] < stoch_d[i] and stoch_k[i-1] >= stoch_d[i-1] and stoch_k[i] > 20:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Trend: Stochastic Crossover", r))

# 4d. Pullback to EMA20 in trend
signals = np.zeros(n)
for i in range(50, n):
    if ema50[i] > ema100[i]:  # Uptrend
        if abs(closes[i] - ema20[i]) < 0.3 * atr14[i] and closes[i] > ema20[i]:
            signals[i] = 1
    elif ema50[i] < ema100[i]:  # Downtrend
        if abs(closes[i] - ema20[i]) < 0.3 * atr14[i] and closes[i] < ema20[i]:
            signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Trend: EMA20 Pullback", r))

# --- 5. STRUCTURE ENTRIES ---
# 5a. Higher High / Higher Low (market structure)
signals = np.zeros(n)
swing_highs = []
swing_lows = []
for i in range(5, n-5):
    if all(highs[i] >= highs[i-j] for j in range(1, 6)) and all(highs[i] >= highs[i+j] for j in range(1, 6)):
        swing_highs.append((i, highs[i]))
    if all(lows[i] <= lows[i-j] for j in range(1, 6)) and all(lows[i] <= lows[i+j] for j in range(1, 6)):
        swing_lows.append((i, lows[i]))

signals = np.zeros(n)
for i in range(30, n):
    recent_sh = [h for idx, h in swing_highs if idx < i and idx > i-100]
    recent_sl = [l for idx, l in swing_lows if idx < i and idx > i-100]
    if len(recent_sh) >= 2 and len(recent_sl) >= 2:
        # Higher highs + higher lows = bullish
        if recent_sh[-1] > recent_sh[-2] and recent_sl[-1] > recent_sl[-2]:
            signals[i] = 1
        elif recent_sh[-1] < recent_sh[-2] and recent_sl[-1] < recent_sl[-2]:
            signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Structure: HH/HL Pattern", r))

# 5b. Break of structure
signals = np.zeros(n)
for i in range(30, n):
    recent_sh = [h for idx, h in swing_highs if idx < i and idx > i-50]
    recent_sl = [l for idx, l in swing_lows if idx < i and idx > i-50]
    if recent_sh and recent_sl:
        if closes[i] > max(recent_sh):
            signals[i] = 1  # BOS bullish
        elif closes[i] < min(recent_sl):
            signals[i] = -1  # BOS bearish
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Structure: Break of Structure", r))

# --- 6. COMBINATION ENTRIES ---
# 6a. Momentum + BB squeeze
signals = np.zeros(n)
for i in range(25, n):
    bb_width = (bb_upper[i] - bb_lower[i]) / bb_mid[i] if bb_mid[i] > 0 else 0
    body = closes[i] - opens[i]
    if bb_width < 0.03 and abs(body) > 0.3 * atr14[i]:
        signals[i] = 1 if body > 0 else -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Combo: Momentum + BB Squeeze", r))

# 6b. RSI + MACD alignment
signals = np.zeros(n)
for i in range(30, n):
    if rsi14[i] > 50 and rsi14[i] < 70 and macd_hist[i] > 0 and macd_hist[i] > macd_hist[i-1]:
        signals[i] = 1
    elif rsi14[i] < 50 and rsi14[i] > 30 and macd_hist[i] < 0 and macd_hist[i] < macd_hist[i-1]:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Combo: RSI + MACD", r))

# 6c. Breakout + H4 regime
signals = np.zeros(n)
for i in range(20, n):
    hh = max(highs[i-20:i])
    ll = min(lows[i-20:i])
    if closes[i] > hh and h4_regime_m5[i] >= 0:
        signals[i] = 1
    elif closes[i] < ll and h4_regime_m5[i] <= 0:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Combo: Breakout + H4 Trend", r))

# 6d. Multi-indicator confluence (3+ agree)
signals = np.zeros(n)
for i in range(100, n):
    buy_score = 0
    sell_score = 0
    # EMA alignment
    if ema20[i] > ema50[i]: buy_score += 1
    else: sell_score += 1
    # RSI
    if rsi14[i] > 50 and rsi14[i] < 70: buy_score += 1
    elif rsi14[i] < 50 and rsi14[i] > 30: sell_score += 1
    # MACD
    if macd_hist[i] > 0: buy_score += 1
    else: sell_score += 1
    # Stochastic
    if stoch_k[i] > stoch_d[i] and stoch_k[i] < 80: buy_score += 1
    elif stoch_k[i] < stoch_d[i] and stoch_k[i] > 20: sell_score += 1
    # BB position
    if closes[i] > bb_mid[i] and closes[i] < bb_upper[i]: buy_score += 1
    elif closes[i] < bb_mid[i] and closes[i] > bb_lower[i]: sell_score += 1
    
    if buy_score >= 4:
        signals[i] = 1
    elif sell_score >= 4:
        signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Combo: 4-Indicator Confluence", r))

# 6e. Price action + volume
signals = np.zeros(n)
for i in range(5, n):
    body = closes[i] - opens[i]
    range_bar = highs[i] - lows[i]
    # Strong bullish candle with good body ratio
    if body > 0 and range_bar > 0:
        body_ratio = body / range_bar
        if body_ratio > 0.7 and range_bar > 0.8 * atr14[i]:
            signals[i] = 1
    elif body < 0 and range_bar > 0:
        body_ratio = abs(body) / range_bar
        if body_ratio > 0.7 and range_bar > 0.8 * atr14[i]:
            signals[i] = -1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Combo: Price Action + Size", r))

# --- 7. SMART MONEY CONCEPTS ---
# 7a. Liquidity grab (sweep of highs/lows then reversal)
signals = np.zeros(n)
for i in range(20, n):
    recent_high = max(highs[i-20:i])
    recent_low = min(lows[i-20:i])
    # Grabbed high then reversed
    if highs[i] > recent_high and closes[i] < opens[i] and closes[i] < recent_high:
        signals[i] = -1
    # Grabbed low then reversed
    elif lows[i] < recent_low and closes[i] > opens[i] and closes[i] > recent_low:
        signals[i] = 1
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Smart: Liquidity Grab", r))

# 7b. Order block (last down candle before big up move)
signals = np.zeros(n)
for i in range(5, n):
    # Bullish order block: last bearish candle before strong bullish move
    if closes[i] > opens[i] and (closes[i] - opens[i]) > 1.0 * atr14[i]:
        # Look back for last bearish candle
        for j in range(i-1, max(i-5, 0), -1):
            if closes[j] < opens[j]:
                if lows[i] <= highs[j] + 0.2 * atr14[i]:
                    signals[i] = 1
                break
    elif closes[i] < opens[i] and (opens[i] - closes[i]) > 1.0 * atr14[i]:
        for j in range(i-1, max(i-5, 0), -1):
            if closes[j] > opens[j]:
                if highs[i] >= lows[j] - 0.2 * atr14[i]:
                    signals[i] = -1
                break
r = backtest(signals, sl=1.0, tp=3.0)
if r: results.append(("Smart: Order Block", r))

# === RESULTS ===
print(f"\n{'─'*80}")
print(f"  ALL RESULTS — Sorted by Total P&L (SL=1.0, TP=3.0, 25 lots)")
print(f"{'─'*80}")
print(f"\n  {'#':>2} {'Strategy':<32} {'Trades':>6} {'T/D':>5} {'WR%':>5} {'$P&L':>8} {'PF':>5}")
print(f"  {'─'*2} {'─'*32} {'─'*6} {'─'*5} {'─'*5} {'─'*8} {'─'*5}")

results.sort(key=lambda x: x[1]['total'], reverse=True)

for idx, (name, r) in enumerate(results):
    marker = " ✅" if r['total'] > 0 and r['wr'] > 50 else ""
    print(f"  {idx+1:>2} {name:<32} {r['trades']:>6} {r['t_day']:>5.1f} {r['wr']:>5.1f} ${r['total']:>7.2f} {r['pf']:>5.2f}{marker}")

# Now test winners with different SL/TP
print(f"\n{'─'*80}")
print(f"  TOP 5 — SL/TP OPTIMIZATION")
print(f"{'─'*80}")

top5 = [name for name, r in results[:5] if r['total'] > 0]

for name in top5:
    # Recreate the signals for this strategy
    signals = np.zeros(n)
    
    if "Bar Body" in name:
        for i in range(1, n):
            body = closes[i] - opens[i]
            if abs(body) > 0.4 * atr14[i]:
                signals[i] = 1 if body > 0 else -1
    elif "20-Bar" in name or "Donchian" in name:
        lb = 10 if "Donchian" in name else 20
        for i in range(lb, n):
            hh = max(highs[i-lb:i])
            ll = min(lows[i-lb:i])
            if closes[i] > hh: signals[i] = 1
            elif closes[i] < ll: signals[i] = -1
    elif "Liquidity" in name:
        for i in range(20, n):
            recent_high = max(highs[i-20:i])
            recent_low = min(lows[i-20:i])
            if highs[i] > recent_high and closes[i] < opens[i] and closes[i] < recent_high:
                signals[i] = -1
            elif lows[i] < recent_low and closes[i] > opens[i] and closes[i] > recent_low:
                signals[i] = 1
    elif "Confluence" in name:
        for i in range(100, n):
            buy_score = 0; sell_score = 0
            if ema20[i] > ema50[i]: buy_score += 1
            else: sell_score += 1
            if rsi14[i] > 50 and rsi14[i] < 70: buy_score += 1
            elif rsi14[i] < 50 and rsi14[i] > 30: sell_score += 1
            if macd_hist[i] > 0: buy_score += 1
            else: sell_score += 1
            if stoch_k[i] > stoch_d[i] and stoch_k[i] < 80: buy_score += 1
            elif stoch_k[i] < stoch_d[i] and stoch_k[i] > 20: sell_score += 1
            if closes[i] > bb_mid[i] and closes[i] < bb_upper[i]: buy_score += 1
            elif closes[i] < bb_mid[i] and closes[i] > bb_lower[i]: sell_score += 1
            if buy_score >= 4: signals[i] = 1
            elif sell_score >= 4: signals[i] = -1
    elif "Breakout + H4" in name:
        for i in range(20, n):
            hh = max(highs[i-20:i]); ll = min(lows[i-20:i])
            if closes[i] > hh and h4_regime_m5[i] >= 0: signals[i] = 1
            elif closes[i] < ll and h4_regime_m5[i] <= 0: signals[i] = -1
    elif "Price Action" in name:
        for i in range(5, n):
            body = closes[i] - opens[i]; range_bar = highs[i] - lows[i]
            if body > 0 and range_bar > 0:
                if body/range_bar > 0.7 and range_bar > 0.8 * atr14[i]: signals[i] = 1
            elif body < 0 and range_bar > 0:
                if abs(body)/range_bar > 0.7 and range_bar > 0.8 * atr14[i]: signals[i] = -1
    elif "Range Expansion" in name:
        for i in range(2, n):
            body = closes[i] - opens[i]; range_now = highs[i] - lows[i]; range_prev = highs[i-1] - lows[i-1]
            if range_now > 1.5 * range_prev and abs(body) > 0.5 * atr14[i]:
                signals[i] = 1 if body > 0 else -1
    elif "Velocity" in name:
        for i in range(5, n):
            velocity = (closes[i] - closes[i-5]) / 5
            if velocity > 0.3 * atr14[i]: signals[i] = 1
            elif velocity < -0.3 * atr14[i]: signals[i] = -1
    elif "BB Squeeze" in name and "Momentum" in name:
        for i in range(25, n):
            bb_width = (bb_upper[i] - bb_lower[i]) / bb_mid[i] if bb_mid[i] > 0 else 0
            body = closes[i] - opens[i]
            if bb_width < 0.03 and abs(body) > 0.3 * atr14[i]:
                signals[i] = 1 if body > 0 else -1
    
    print(f"\n  {name}:")
    for sl_val, tp_val in [(0.5, 1.5), (1.0, 2.0), (1.0, 3.0), (1.5, 3.0), (2.0, 4.0), (2.0, 6.0), (3.0, 6.0)]:
        r = backtest(signals, sl=sl_val, tp=tp_val)
        if r:
            print(f"    SL={sl_val:.1f} TP={tp_val:.1f}: {r['trades']:>4} trades WR={r['wr']:>5.1f}% ${r['total']:>7.2f} PF={r['pf']:.2f}")

mt5.shutdown()
print(f"\n{'='*80}")
