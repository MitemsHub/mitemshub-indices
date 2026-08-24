#!/usr/bin/env python3
"""V100 PROPER BACKTEST — SL/TP in actual price units"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime

mt5.initialize()
sym = "Volatility 100 Index"
mt5.symbol_select(sym, True)
info = mt5.symbol_info(sym)
dollar_per_point = info.trade_tick_value / info.trade_tick_size * info.point
acc = mt5.account_info()

# margin per lot
margin_per_lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 1, info.ask)
if not margin_per_lot or margin_per_lot <= 0:
    margin_per_lot = info.ask * info.trade_contract_size / acc.leverage

equity = acc.equity
max_lots_70 = min(int(equity * 0.70 / margin_per_lot), info.volume_max) if margin_per_lot > 0 else 0

print(f"{'='*70}")
print(f"  V100 PROPER BACKTEST")
print(f"{'='*70}")
print(f"  Price:           {info.ask}")
print(f"  $/point/lot:     ${dollar_per_point}")
print(f"  Point:           {info.point} (1 pt = ${info.point * dollar_per_point} at 1 lot)")
print(f"  Spread:          {info.spread} pts = ${info.spread * dollar_per_point:.4f} at 1 lot")
print(f"  Equity:          ${equity:.2f}")
print(f"  Max lots (70%):  {max_lots_70}")
print(f"  Margin/lot:      ${margin_per_lot:.4f}")

# Get data
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2000)
closes = rates['close']
highs = rates['high']
lows = rates['low']
opens = rates['open']
n = len(closes)
print(f"  Data:            {n} H1 bars ({n/24:.0f} days)")

# Indicators
def ema(data, period):
    r = np.zeros_like(data, dtype=float)
    r[0] = data[0]
    k = 2.0 / (period + 1)
    for i in range(1, len(data)):
        r[i] = data[i] * k + r[i-1] * (1 - k)
    return r

ema20 = ema(closes, 20)
ema50 = ema(closes, 50)
ema100 = ema(closes, 100)

# ATR in price units
atr = np.zeros(n)
for i in range(14, n):
    trs = []
    for j in range(i-13, i+1):
        tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
        trs.append(tr)
    atr[i] = np.mean(trs)

# RSI
rsi = np.zeros(n)
for i in range(14, n):
    deltas = np.diff(closes[i-13:i+1])
    gains = np.sum(np.maximum(deltas, 0))
    losses = np.sum(np.abs(np.minimum(deltas, 0)))
    if losses > 0:
        rsi[i] = 100 - 100 / (1 + gains / losses)
    else:
        rsi[i] = 100

print(f"\n  ATR(H1):         {atr[-1]:.2f} price units = {atr[-1]/info.point:.0f} points")
print(f"  1.5×ATR SL:      {atr[-1]*1.5:.2f} = ${atr[-1]*1.5 * 25 * dollar_per_point:.2f} at 25 lots")
print(f"  2×SL TP:         {atr[-1]*3:.2f} = ${atr[-1]*3 * 25 * dollar_per_point:.2f} at 25 lots")

# Bar statistics
ranges = highs - lows
print(f"\n  Bar Range Stats:")
print(f"    Min: {np.min(ranges):.2f} | Max: {np.max(ranges):.2f} | Mean: {np.mean(ranges):.2f}")
print(f"    Median: {np.median(ranges):.2f} | Std: {np.std(ranges):.2f}")

for pct in [25, 50, 75, 90]:
    val = np.percentile(ranges, pct)
    print(f"    {pct}th percentile: {val:.2f} ({val/info.point:.0f} pts)")

# How often do various price moves happen?
print(f"\n  Price Move Frequency (H1 bars):")
for target in [1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0, 30.0, 50.0]:
    hits = np.sum(ranges >= target)
    pct = hits / n * 100
    at_25 = target * 25 * dollar_per_point
    print(f"    ≥{target:>5.1f} price: {hits:>4d}/{n} ({pct:>5.1f}%) → ${at_25:>7.2f} at 25 lots")

# Backtest
def run_bt(sl_price, tp_price, lots, max_hold=16):
    """SL/TP in price units"""
    eq = equity
    trades = []
    in_trade = False
    entry_p = 0
    entry_d = 0
    sl_p = 0
    tp_p = 0
    bars_held = 0
    cooldown = 0
    
    spread_cost = info.spread * info.point * lots * dollar_per_point / dollar_per_point  # in price terms
    spread_pts = info.spread * info.point  # spread in price units
    
    for i in range(250, n):
        if cooldown > 0:
            cooldown -= 1
            continue
        
        if eq <= 0:
            break
        
        if in_trade:
            bars_held += 1
            
            if entry_d > 0:
                # Check SL first (worst case)
                if lows[i] <= sl_p:
                    pnl = (sl_p - entry_p) * lots * dollar_per_point / info.point - spread_pts * lots * dollar_per_point / info.point
                    # Simpler: pnl = (exit - entry - spread) * lots * $/pt
                    actual_sl_pnl = (sl_p - entry_p - spread_pts) * lots * (dollar_per_point / info.point)
                    trades.append(('SL', actual_sl_pnl))
                    eq += actual_sl_pnl
                    in_trade = False
                    cooldown = 2
                    continue
                if highs[i] >= tp_p:
                    pnl = (tp_p - entry_p - spread_pts) * lots * (dollar_per_point / info.point)
                    trades.append(('TP', pnl))
                    eq += pnl
                    in_trade = False
                    continue
            else:
                if highs[i] >= sl_p:
                    pnl = (entry_p - sl_p - spread_pts) * lots * (dollar_per_point / info.point)
                    trades.append(('SL', pnl))
                    eq += pnl
                    in_trade = False
                    cooldown = 2
                    continue
                if lows[i] <= tp_p:
                    pnl = (entry_p - tp_p - spread_pts) * lots * (dollar_per_point / info.point)
                    trades.append(('TP', pnl))
                    eq += pnl
                    in_trade = False
                    continue
            
            if bars_held >= max_hold:
                # Time exit at current close
                if entry_d > 0:
                    pnl = (closes[i] - entry_p - spread_pts) * lots * (dollar_per_point / info.point)
                else:
                    pnl = (entry_p - closes[i] - spread_pts) * lots * (dollar_per_point / info.point)
                trades.append(('TIME', pnl))
                eq += pnl
                in_trade = False
                continue
            continue
        
        # Entry signals
        bullish = ema20[i] > ema50[i] > ema100[i]
        bearish = ema20[i] < ema50[i] < ema100[i]
        
        body = closes[i] - opens[i]
        pb = abs(closes[i] - ema20[i])
        
        # Breakout
        if bullish and closes[i] > max(highs[i-10:i]):
            entry_p = closes[i]
            entry_d = 1
            sl_p = entry_p - sl_price
            tp_p = entry_p + tp_price
            in_trade = True
            bars_held = 0
            continue
        if bearish and closes[i] < min(lows[i-10:i]):
            entry_p = closes[i]
            entry_d = -1
            sl_p = entry_p + sl_price
            tp_p = entry_p - tp_price
            in_trade = True
            bars_held = 0
            continue
        
        # Pullback
        if bullish and pb < 0.5 * atr[i] and body > 0 and rsi[i] < 65:
            entry_p = closes[i]
            entry_d = 1
            sl_p = entry_p - sl_price
            tp_p = entry_p + tp_price
            in_trade = True
            bars_held = 0
            continue
        if bearish and pb < 0.5 * atr[i] and body < 0 and rsi[i] > 35:
            entry_p = closes[i]
            entry_d = -1
            sl_p = entry_p + sl_price
            tp_p = entry_p - tp_price
            in_trade = True
            bars_held = 0
            continue
    
    if not trades:
        return None
    
    pnls = [t[1] for t in trades]
    wins = [p for p in pnls if p > 0]
    loss_list = [p for p in pnls if p <= 0]
    wr = len(wins) / len(pnls) * 100
    total = sum(pnls)
    avg = total / len(pnls)
    pf = sum(wins) / sum(abs(l) for l in loss_list) if loss_list and sum(abs(l) for l in loss_list) > 0 else 999
    max_dd = min(pnls)
    
    days = (n - 250) / 24
    
    return {
        'trades': len(pnls),
        't_day': len(pnls) / days,
        'wr': wr,
        'total': total,
        'avg': avg,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': abs(np.mean(loss_list)) if loss_list else 0,
        'pf': pf,
        'max_dd': max_dd,
        'eq': eq,
        'roi': total / equity * 100,
        'lots': lots,
        'sl': sl_price,
        'tp': tp_price,
        'risk_pct': sl_price * lots * dollar_per_point / info.point / equity * 100,
    }

print(f"\n{'='*70}")
print(f"  BACKTEST RESULTS")
print(f"{'='*70}")

# Key test: what lot sizes + SL/TP combos work?
atr_now = atr[-1]
scenarios = [
    # (sl_price, tp_price, lots, label)
    # Tight scalps — capture $2-$5 per win
    (2.0, 4.0, 25, "SL 2pt / TP 4pt / 25 lots"),
    (3.0, 6.0, 25, "SL 3pt / TP 6pt / 25 lots"),
    (5.0, 10.0, 25, "SL 5pt / TP 10pt / 25 lots"),
    # ATR-based
    (atr_now * 1.0, atr_now * 2.0, 25, f"SL 1.0×ATR / TP 2×SL / 25 lots"),
    (atr_now * 1.5, atr_now * 3.0, 25, f"SL 1.5×ATR / TP 2×SL / 25 lots"),
    # Medium sizing
    (3.0, 6.0, 15, "SL 3pt / TP 6pt / 15 lots"),
    (5.0, 10.0, 15, "SL 5pt / TP 10pt / 15 lots"),
    (atr_now * 1.0, atr_now * 2.0, 15, f"SL 1.0×ATR / TP 2×SL / 15 lots"),
    # Conservative
    (3.0, 6.0, 5, "SL 3pt / TP 6pt / 5 lots"),
    (5.0, 10.0, 5, "SL 5pt / TP 10pt / 5 lots"),
    # Very tight (high frequency target)
    (1.0, 2.0, 25, "SL 1pt / TP 2pt / 25 lots"),
    (1.5, 3.0, 25, "SL 1.5pt / TP 3pt / 25 lots"),
    (1.5, 3.0, 20, "SL 1.5pt / TP 3pt / 20 lots"),
    (1.5, 4.0, 25, "SL 1.5pt / TP 4pt / 25 lots"),
    (2.0, 5.0, 25, "SL 2pt / TP 5pt / 25 lots"),
    (2.0, 5.0, 20, "SL 2pt / TP 5pt / 20 lots"),
]

header = f"  {'Scenario':<30s} {'#':>3s} {'T/D':>4s} {'WR%':>5s} {'$P&L':>8s} {'ROI%':>6s} {'PF':>5s} {'MaxDD':>7s} {'Risk%':>6s}"
print(header)
print(f"  {'─'*30} {'─'*3} {'─'*4} {'─'*5} {'─'*8} {'─'*6} {'─'*5} {'─'*7} {'─'*6}")

best = None
for sl_p, tp_p, lots, label in scenarios:
    r = run_bt(sl_p, tp_p, lots)
    if r is None:
        print(f"  {label:<30s} {'0 trades':>3s}")
        continue
    
    print(f"  {label:<30s} {r['trades']:>3d} {r['t_day']:>4.1f} {r['wr']:>5.1f} ${r['total']:>7.2f} {r['roi']:>5.1f}% {r['pf']:>5.2f} ${abs(r['max_dd']):>6.2f} {r['risk_pct']:>5.1f}%")
    
    if best is None or r['total'] > best['total']:
        best = r
        best['label'] = label

print(f"\n{'─'*70}")
print(f"  BEST SCENARIO:")
if best:
    print(f"    {best['label']}")
    print(f"    Trades:     {best['trades']} ({best['t_day']:.1f}/day)")
    print(f"    Win Rate:   {best['wr']:.1f}%")
    print(f"    Total P&L:  ${best['total']:.2f} ({best['roi']:.1f}% ROI)")
    print(f"    Avg Win:    ${best['avg_win']:.2f}")
    print(f"    Avg Loss:   ${best['avg_loss']:.2f}")
    print(f"    Profit Factor: {best['pf']:.2f}")
    print(f"    Final Equity:  ${best['eq']:.2f}")

# Final answer: what's the realistic daily target?
print(f"\n{'─'*70}")
print(f"  REALISTIC DAILY TARGETS (V100, $22.75)")
print(f"{'─'*70}")

for lots_test in [5, 10, 15, 20, 25]:
    margin = lots_test * margin_per_lot
    risk_capital = equity - (equity - margin)  # = margin
    
    # Test different TP targets
    for tp in [1.0, 2.0, 3.0, 5.0]:
        tp_dollars = tp * lots_test * dollar_per_point / info.point
        sl_dollars = tp * 0.5 * lots_test * dollar_per_point / info.point  # 2:1 R:R
        
        # How often does V100 move tp points in one direction?
        directional_moves = 0
        for i in range(250, n):
            range_pts = highs[i] - lows[i]
            if range_pts >= tp:
                directional_moves += 1
        freq = directional_moves / (n - 250) * 100
        
        print(f"    {lots_test} lots, TP={tp:.1f}pt: ${tp_dollars:.2f}/win, SL=${sl_dollars:.2f}, hit rate={freq:.0f}%, margin=${margin:.2f}")

mt5.shutdown()
print(f"\n{'='*70}")
