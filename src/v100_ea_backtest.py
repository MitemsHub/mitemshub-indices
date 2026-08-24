#!/usr/bin/env python3
"""V100 EA BACKTEST — Realistic test of our strategy on V100"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime

mt5.initialize()
sym = "Volatility 100 Index"
mt5.symbol_select(sym, True)
info = mt5.symbol_info(sym)
dollar_per_point = info.trade_tick_value / info.trade_tick_size * info.point

# Get margin info
margin_per_lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 1, info.ask)
if not margin_per_lot or margin_per_lot <= 0:
    acc = mt5.account_info()
    margin_per_lot = info.ask * info.trade_contract_size / acc.leverage

print(f"{'='*70}")
print(f"  V100 EA BACKTEST — v19 Strategy on V100 H1")
print(f"{'='*70}")
print(f"  $/point/lot:  ${dollar_per_point}")
print(f"  Spread:       {info.spread} pts (${info.spread * dollar_per_point:.2f} at 1 lot)")
print(f"  Margin/lot:   ${margin_per_lot:.4f}")

# === Test multiple lot sizes ===
equity_start = 22.75
equity = equity_start
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2000)
if rates is None:
    print("❌ No data")
    mt5.shutdown()
    exit(1)

closes = rates['close']
highs = rates['high']
lows = rates['low']
opens = rates['open']
times = rates['time']
n = len(closes)

print(f"\n  Data: {n} H1 bars ({n/24:.0f} days)")

# Calculate indicators
def ema(data, period):
    result = np.zeros_like(data, dtype=float)
    result[0] = data[0]
    k = 2.0 / (period + 1)
    for i in range(1, len(data)):
        result[i] = data[i] * k + result[i-1] * (1 - k)
    return result

ema20 = ema(closes, 20)
ema50 = ema(closes, 50)
ema100 = ema(closes, 100)
rsi_arr = np.zeros(n)
atr_arr = np.zeros(n)

# RSI
for i in range(14, n):
    deltas = closes[i-13:i+1]
    gains = np.sum(np.maximum(np.diff(deltas), 0))
    losses = np.sum(np.abs(np.minimum(np.diff(deltas), 0)))
    if losses > 0:
        rs = gains / losses
        rsi_arr[i] = 100 - 100 / (1 + rs)
    else:
        rsi_arr[i] = 100

# ATR
for i in range(14, n):
    trs = []
    for j in range(i-13, i+1):
        tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
        trs.append(tr)
    atr_arr[i] = np.mean(trs)

# === BACKTEST FUNCTION ===
def run_backtest(lots, sl_pts, tp_pts, warmup=250, label=""):
    """Simple backtest with EMA trend + pullback/breakout entry"""
    equity = equity_start
    trades = []
    in_trade = False
    entry_price = 0
    entry_dir = 0
    sl_price = 0
    tp_price = 0
    consec_losses = 0
    cooldown = 0
    
    for i in range(warmup, n):
        if cooldown > 0:
            cooldown -= 1
            continue
        
        if in_trade:
            if entry_dir > 0:
                if lows[i] <= sl_price:
                    pnl = (sl_price - entry_price) * lots * dollar_per_point - info.spread * lots * dollar_per_point
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    if pnl < 0: consec_losses += 1
                    else: consec_losses = 0
                    continue
                if highs[i] >= tp_price:
                    pnl = (tp_price - entry_price) * lots * dollar_per_point - info.spread * lots * dollar_per_point
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    consec_losses = 0
                    continue
            else:
                if highs[i] >= sl_price:
                    pnl = (entry_price - sl_price) * lots * dollar_per_point - info.spread * lots * dollar_per_point
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    if pnl < 0: consec_losses += 1
                    else: consec_losses = 0
                    continue
                if lows[i] <= tp_price:
                    pnl = (entry_price - tp_price) * lots * dollar_per_point - info.spread * lots * dollar_per_point
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    consec_losses = 0
                    continue
            
            # Early exit after 16 bars (time exit)
            continue
        
        if equity <= 0:
            break
        
        # Signal: EMA trend + pullback
        bullish = ema20[i] > ema50[i] > ema100[i] and closes[i] > ema20[i]
        bearish = ema20[i] < ema50[i] < ema100[i] and closes[i] < ema20[i]
        
        if bullish:
            # Pullback entry: price near EMA20
            pb = abs(closes[i] - ema20[i])
            if pb < 0.5 * atr_arr[i] and rsi_arr[i] < 65 and rsi_arr[i] > 40:
                entry_price = closes[i]
                entry_dir = 1
                sl_price = entry_price - sl_pts
                tp_price = entry_price + tp_pts
                in_trade = True
                continue
        
        if bearish:
            pb = abs(closes[i] - ema20[i])
            if pb < 0.5 * atr_arr[i] and rsi_arr[i] > 35 and rsi_arr[i] < 60:
                entry_price = closes[i]
                entry_dir = -1
                sl_price = entry_price + sl_pts
                tp_price = entry_price - tp_pts
                in_trade = True
                continue
    
    if not trades:
        return None
    
    wins = [t for t in trades if t > 0]
    losses_list = [t for t in trades if t <= 0]
    total_pnl = sum(trades)
    wr = len(wins) / len(trades) * 100
    avg_win = np.mean(wins) if wins else 0
    avg_loss = abs(np.mean(losses_list)) if losses_list else 0
    profit_factor = sum(wins) / sum(abs(l) for l in losses_list) if losses_list and sum(abs(l) for l in losses_list) > 0 else 999
    days = (n - warmup) / 24
    
    risk_per = lots * sl_pts * dollar_per_point / equity_start * 100
    
    return {
        'label': label,
        'lots': lots,
        'sl_pts': sl_pts,
        'tp_pts': tp_pts,
        'trades': len(trades),
        'trades_day': len(trades) / days,
        'wr': wr,
        'total_pnl': total_pnl,
        'avg_trade': total_pnl / len(trades),
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'pf': profit_factor,
        'max_dd': min(trades) if trades else 0,
        'risk_per': risk_per,
        'final_equity': equity_start + total_pnl,
        'roi': total_pnl / equity_start * 100,
    }

# === TEST SCENARIOS ===
print(f"\n{'─'*70}")
print(f"  BACKTEST RESULTS — V100 H1 (90 days)")
print(f"{'─'*70}")

scenarios = [
    # (lots, sl_pts, tp_pts, label)
    # Conservative: 0.35% risk
    (0.01, 500, 1000, "0.01 lot, 500/1000 pts"),
    (0.02, 500, 1000, "0.02 lot, 500/1000 pts"),
    # Medium
    (1.0, 200, 400, "1 lot, 200/400 pts"),
    (1.0, 300, 600, "1 lot, 300/600 pts"),
    (1.0, 500, 1000, "1 lot, 500/1000 pts"),
    # Aggressive
    (5.0, 100, 200, "5 lots, 100/200 pts"),
    (5.0, 200, 400, "5 lots, 200/400 pts"),
    (10.0, 100, 200, "10 lots, 100/200 pts"),
    (10.0, 150, 300, "10 lots, 150/300 pts"),
    (10.0, 200, 400, "10 lots, 200/400 pts"),
    # Max aggressive
    (25.0, 50, 100, "25 lots, 50/100 pts"),
    (25.0, 100, 200, "25 lots, 100/200 pts"),
]

print(f"\n  {'Scenario':<28s} {'Trades':>6s} {'T/Day':>5s} {'WR%':>5s} {'P&L':>9s} {'ROI%':>7s} {'PF':>5s} {'Risk%':>6s}")
print(f"  {'─'*28} {'─'*6} {'─'*5} {'─'*5} {'─'*9} {'─'*7} {'─'*5} {'─'*6}")

results = []
for lots, sl, tp, label in scenarios:
    r = run_backtest(lots, sl, tp, label=label)
    if r:
        results.append(r)
        risk_pct = r['risk_per']
        print(f"  {r['label']:<28s} {r['trades']:>6d} {r['trades_day']:>5.1f} {r['wr']:>5.1f} ${r['total_pnl']:>8.2f} {r['roi']:>6.1f}% {r['pf']:>5.2f} {risk_pct:>5.1f}%")

# Find the best scenario
print(f"\n{'─'*70}")
print(f"  ANALYSIS")
print(f"{'─'*70}")

# The key insight: what's the maximum $/trade on V100 with our equity?
acc = mt5.account_info()
print(f"\n  Account: ${equity_start:.2f} | Leverage: 1:{acc.leverage}")
print(f"  Max lots (70% margin): {int(equity_start*0.70/margin_per_lot)} lots")
print(f"  Margin/lot: ${margin_per_lot:.4f}")

# What's the realistic $ target?
for target_daily in [2, 5, 10, 20]:
    trades_per_day = 2.5  # average
    per_trade = target_daily / trades_per_day
    pts_needed = per_trade / (25 * dollar_per_point)  # at max volume
    print(f"\n  To make ${target_daily}/day:")
    print(f"    Need ${per_trade:.2f} per trade at {trades_per_day} trades/day")
    print(f"    At 25 lots: need {pts_needed:.0f} pts net after spread")
    print(f"    Spread eats: {info.spread} pts")
    print(f"    Need price to move: {pts_needed + info.spread:.0f} pts")
    print(f"    H1 ATR: {atr_arr[-1]:.0f} pts → TP is {pts_needed/atr_arr[-1]*100:.1f}% of ATR")

# Time-based analysis: how many H1 bars have enough movement?
for tp_pts in [50, 100, 200, 300, 500]:
    hits = 0
    for i in range(250, n):
        range_pts = highs[i] - lows[i]
        if range_pts >= tp_pts:
            hits += 1
    pct = hits / (n-250) * 100
    at_max_vol = tp_pts * 25 * dollar_per_point
    print(f"\n  H1 bars that reach {tp_pts} pts: {hits}/{n-250} ({pct:.1f}%) → ${at_max_vol:.2f} at 25 lots")

mt5.shutdown()
print(f"\n{'='*70}")
