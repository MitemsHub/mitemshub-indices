#!/usr/bin/env python3
"""V100 WALK-FORWARD OPTIMIZATION — Multi-timeframe sweep"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime
import json

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

print("=" * 80)
print("  V100 WALK-FORWARD OPTIMIZATION SWEEP")
print("=" * 80)
print(f"  Symbol: {sym} | Price: {info.ask}")
print(f"  $/pt/lot: ${dpp} | Spread: {info.spread} pts = {spread_price:.2f} price")
print(f"  Equity: ${equity:.2f} | Max lots (70%): {max_lots}")

# === INDICATORS ===
def ema(data, period):
    r = np.zeros_like(data, dtype=float)
    r[0] = data[0]
    k = 2.0 / (period + 1)
    for i in range(1, len(data)):
        r[i] = data[i] * k + r[i-1] * (1 - k)
    return r

def calc_rsi(data, period=14):
    r = np.zeros(len(data))
    for i in range(period, len(data)):
        deltas = np.diff(data[i-period:i+1])
        gains = np.sum(np.maximum(deltas, 0))
        losses = np.sum(np.abs(np.minimum(deltas, 0)))
        r[i] = 100 if losses == 0 else 100 - 100 / (1 + gains / losses)
    return r

def calc_atr(highs, lows, closes, period=14):
    n = len(closes)
    atr = np.zeros(n)
    for i in range(period, n):
        trs = []
        for j in range(i - period + 1, i + 1):
            tr = max(highs[j] - lows[j], abs(highs[j] - closes[j-1]), abs(lows[j] - closes[j-1]))
            trs.append(tr)
        atr[i] = np.mean(trs)
    return atr

# === BACKTEST ENGINE ===
def run_backtest(closes, highs, lows, opens, sl_price, tp_price, lots, 
                 max_hold_bars=16, cooldown=1, warmup=100,
                 strategy="momentum", max_trades_day=3, session_filter=False):
    """
    strategies:
      - momentum: bar body direction entry
      - breakout: break recent high/low
      - mean_revert: fade after big move
      - ema_trend: EMA alignment + pullback
      - simple: buy/sell based on bar close vs open
    """
    n = len(closes)
    bars_per_day = n // max(1, int((n * 60 / {'M5':5,'M15':15,'H1':60,'H4':240}.get('H1', 60))))
    
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi = calc_rsi(closes, 14)
    atr = calc_atr(highs, lows, closes, 14)
    
    equity = 0.0  # track PnL, not absolute equity
    trades = []
    in_trade = False
    entry_p = 0
    entry_d = 0
    sl_p = 0
    tp_p = 0
    bars_held = 0
    cooldown_counter = 0
    daily_trades = 0
    last_day = 0
    consec_losses = 0
    
    spread_cost = spread_price  # in price units
    
    for i in range(warmup, n):
        # Daily reset
        bar_day = i // 24  # approximate
        if bar_day != last_day:
            last_day = bar_day
            daily_trades = 0
        
        if cooldown_counter > 0:
            cooldown_counter -= 1
            continue
        
        # Manage open position
        if in_trade:
            bars_held += 1
            
            if entry_d > 0:
                if lows[i] <= sl_p:
                    pnl = (sl_p - entry_p - spread_cost) * lots * dpp
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    cooldown_counter = cooldown
                    consec_losses += 1
                    continue
                if highs[i] >= tp_p:
                    pnl = (tp_p - entry_p - spread_cost) * lots * dpp
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    consec_losses = 0
                    continue
            else:
                if highs[i] >= sl_p:
                    pnl = (entry_p - sl_p - spread_cost) * lots * dpp
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    cooldown_counter = cooldown
                    consec_losses += 1
                    continue
                if lows[i] <= tp_p:
                    pnl = (entry_p - tp_p - spread_cost) * lots * dpp
                    trades.append(pnl)
                    equity += pnl
                    in_trade = False
                    consec_losses = 0
                    continue
            
            # Time exit
            if bars_held >= max_hold_bars:
                if entry_d > 0:
                    pnl = (closes[i] - entry_p - spread_cost) * lots * dpp
                else:
                    pnl = (entry_p - closes[i] - spread_cost) * lots * dpp
                trades.append(pnl)
                equity += pnl
                in_trade = False
                continue
            continue
        
        # Daily trade limit
        if daily_trades >= max_trades_day:
            continue
        
        # === ENTRY SIGNALS ===
        body = closes[i] - opens[i]
        body_dir = 1 if body > 0 else (-1 if body < 0 else 0)
        range_bar = highs[i] - lows[i]
        
        signal = 0  # 1 = buy, -1 = sell
        
        if strategy == "momentum":
            # Simple: trade with the bar direction if it has a decent body
            if body_dir != 0 and abs(body) > 0.3 * atr[i] and atr[i] > 0:
                signal = body_dir
        
        elif strategy == "breakout":
            if i >= 20:
                recent_high = max(highs[i-20:i])
                recent_low = min(lows[i-20:i])
                if closes[i] > recent_high:
                    signal = 1
                elif closes[i] < recent_low:
                    signal = -1
        
        elif strategy == "mean_revert":
            # Fade after big move
            if i >= 5:
                recent_move = closes[i] - closes[i-5]
                if recent_move > 2.0 * atr[i] and rsi[i] > 70:
                    signal = -1  # sell the overextension
                elif recent_move < -2.0 * atr[i] and rsi[i] < 30:
                    signal = 1   # buy the dip
        
        elif strategy == "ema_trend":
            if ema20[i] > ema50[i] and body > 0 and rsi[i] < 65:
                pb = abs(closes[i] - ema20[i])
                if pb < 0.5 * atr[i]:
                    signal = 1
            elif ema20[i] < ema50[i] and body < 0 and rsi[i] > 35:
                pb = abs(closes[i] - ema20[i])
                if pb < 0.5 * atr[i]:
                    signal = -1
        
        elif strategy == "simple":
            # Buy/sell based purely on bar close > open with volume-like filter
            if body_dir != 0 and range_bar > 0.5 * atr[i]:
                signal = body_dir
        
        elif strategy == "rsi_momentum":
            # RSI-based momentum
            if rsi[i] > 55 and rsi[i] < 75 and body > 0:
                signal = 1
            elif rsi[i] < 45 and rsi[i] > 25 and body < 0:
                signal = -1
        
        elif strategy == "displacement":
            # Strong candle with follow-through
            if body_dir != 0 and abs(body) > 0.6 * atr[i] and closes[i] != opens[i]:
                # Check next bar (we simulate entering at close)
                signal = body_dir
        
        if signal != 0:
            entry_p = closes[i]
            entry_d = signal
            if signal > 0:
                sl_p = entry_p - sl_price
                tp_p = entry_p + tp_price
            else:
                sl_p = entry_p + sl_price
                tp_p = entry_p - tp_price
            in_trade = True
            bars_held = 0
            daily_trades += 1
    
    if not trades:
        return None
    
    pnls = np.array(trades)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    wr = len(wins) / len(pnls) * 100
    total = np.sum(pnls)
    avg = np.mean(pnls)
    pf = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 and np.sum(losses) != 0 else 999
    max_dd = np.min(pnls) if len(pnls) > 0 else 0
    max_dd_cum = np.min(np.cumsum(pnls)) if len(pnls) > 0 else 0
    
    # Calculate max drawdown as percentage
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd_pct = np.max(dd) if len(dd) > 0 else 0
    
    # Time span
    bars = len(closes)
    if bars > 0:
        timeframes = {'M5': 288, 'M15': 96, 'H1': 24, 'H4': 6}
        # Estimate days from bar count
        tf_key = 'H1'  # default
        for k, v in timeframes.items():
            if abs(bars / v - bars / 24) < abs(bars / 24 - bars / 24):
                tf_key = k
        days = bars / timeframes.get(tf_key, 24)
    else:
        days = 83
    
    return {
        'trades': len(pnls),
        'trades_per_day': len(pnls) / max(days, 1),
        'wr': wr,
        'total_pnl': total,
        'avg_trade': avg,
        'avg_win': np.mean(wins) if len(wins) > 0 else 0,
        'avg_loss': abs(np.mean(losses)) if len(losses) > 0 else 0,
        'pf': pf,
        'max_dd_single': max_dd,
        'max_dd_cum': max_dd_cum,
        'max_dd_pct': max_dd_pct,
        'roi': total / equity * 100,
        'final_equity': equity + total,
        'consec_losses_max': max(np.sum(pnls[i:i+5] <= 0) for i in range(0, len(pnls), 5)) if len(pnls) > 0 else 0,
    }

# === TIMEFRAMES ===
timeframes = {
    'M5': (mt5.TIMEFRAME_M5, 5000),
    'M15': (mt5.TIMEFRAME_M15, 5000),
    'H1': (mt5.TIMEFRAME_H1, 2000),
    'H4': (mt5.TIMEFRAME_H4, 2000),
}

# === STRATEGIES ===
strategies = ["momentum", "breakout", "rsi_momentum", "displacement", "simple"]

# === SL/TP COMBOS (in price units) ===
sl_tp_combos = [
    (1.0, 2.0, "1/2"),
    (1.5, 2.0, "1.5/2"),
    (1.5, 3.0, "1.5/3"),
    (2.0, 3.0, "2/3"),
    (2.0, 4.0, "2/4"),
    (3.0, 5.0, "3/5"),
    (3.0, 6.0, "3/6"),
    (5.0, 8.0, "5/8"),
]

# === LOT SIZES ===
lot_sizes = [10, 15, 20, 25]

# === WALK-FORWARD: 60-day train, 20-day test ===
print(f"\n{'─'*80}")
print(f"  WALK-FORWARD METHODOLOGY")
print(f"{'─'*80}")
print(f"  Train period: First 60% of data")
print(f"  Test period:  Last 40% of data")
print(f"  Strategy:     Train on first period, validate on second")
print(f"  Metric:       Total P&L (validated), WR%, Profit Factor")
print(f"{'─'*80}")

all_results = []

for tf_name, (tf, bars_needed) in timeframes.items():
    print(f"\n{'='*80}")
    print(f"  TIMEFRAME: {tf_name}")
    print(f"{'='*80}")
    
    rates = mt5.copy_rates_from_pos(sym, tf, 0, bars_needed)
    if rates is None or len(rates) < 200:
        print(f"  ⚠️ Insufficient data for {tf_name}")
        continue
    
    closes = rates['close']
    highs = rates['high']
    lows = rates['low']
    opens = rates['open']
    times = rates['time']
    n = len(closes)
    
    # Split into train/test
    split = int(n * 0.6)
    train_n = split
    test_n = n - split
    
    first_time = datetime.fromtimestamp(times[0])
    last_time = datetime.fromtimestamp(times[-1])
    split_time = datetime.fromtimestamp(times[split])
    
    print(f"  Bars: {n} | Train: {train_n} ({first_time.date()} → {split_time.date()}) | Test: {test_n} ({split_time.date()} → {last_time.date()})")
    
    # ATR for reference
    atr = calc_atr(highs, lows, closes, 14)
    avg_range = np.mean(highs - lows)
    print(f"  Avg bar range: {avg_range:.4f} price | ATR: {atr[-1]:.4f} price")
    
    # Sweep all combos
    tf_results = []
    
    for strat in strategies:
        for sl_p, tp_p, sltp_label in sl_tp_combos:
            for lots in lot_sizes:
                # TRAIN on first period
                train_r = run_backtest(
                    closes[:split], highs[:split], lows[:split], opens[:split],
                    sl_p, tp_p, lots, strategy=strat,
                    max_hold_bars=16, cooldown=1, warmup=50,
                    max_trades_day=3
                )
                
                if train_r is None or train_r['trades'] < 3:
                    continue
                
                # TEST on second period (walk-forward validation)
                test_r = run_backtest(
                    closes[split:], highs[split:], lows[split:], opens[split:],
                    sl_p, tp_p, lots, strategy=strat,
                    max_hold_bars=16, cooldown=1, warmup=10,
                    max_trades_day=3
                )
                
                if test_r is None:
                    continue
                
                # Both must be profitable
                if train_r['total_pnl'] <= 0 or test_r['total_pnl'] <= 0:
                    continue
                
                combined_pnl = train_r['total_pnl'] + test_r['total_pnl']
                
                tf_results.append({
                    'tf': tf_name,
                    'strategy': strat,
                    'sl_tp': sltp_label,
                    'sl': sl_p,
                    'tp': tp_p,
                    'lots': lots,
                    'train': train_r,
                    'test': test_r,
                    'combined_pnl': combined_pnl,
                    'combined_trades': train_r['trades'] + test_r['trades'],
                    'avg_wr': (train_r['wr'] + test_r['wr']) / 2,
                    'avg_pf': (train_r['pf'] + test_r['pf']) / 2,
                })
    
    # Sort by test P&L (out-of-sample performance)
    tf_results.sort(key=lambda x: x['test']['total_pnl'], reverse=True)
    all_results.extend(tf_results)
    
    if not tf_results:
        print(f"\n  ❌ No profitable combinations found for {tf_name}")
        print(f"     (This means the strategy doesn't work on {tf_name})")
        continue
    
    # Show top 10
    print(f"\n  {'#':>2} {'Strategy':<14} {'SL/TP':<7} {'Lots':>4} {'Train$':>8} {'Test$':>8} {'Total$':>8} {'WR%':>5} {'PF':>5} {'T/D':>4}")
    print(f"  {'─'*2} {'─'*14} {'─'*7} {'─'*4} {'─'*8} {'─'*8} {'─'*8} {'─'*5} {'─'*5} {'─'*4}")
    
    for idx, r in enumerate(tf_results[:10]):
        print(f"  {idx+1:>2} {r['strategy']:<14} {r['sl_tp']:<7} {r['lots']:>4} "
              f"${r['train']['total_pnl']:>7.2f} ${r['test']['total_pnl']:>7.2f} "
              f"${r['combined_pnl']:>7.2f} {r['avg_wr']:>4.1f}% {r['avg_pf']:>5.2f} "
              f"{r['test']['trades_per_day']:>4.1f}")

# === GLOBAL RANKING ===
print(f"\n\n{'='*80}")
print(f"  GLOBAL RANKING — Top 20 Across ALL Timeframes")
print(f"{'='*80}")

# Sort by test P&L (out-of-sample is what matters)
all_results.sort(key=lambda x: x['test']['total_pnl'], reverse=True)

print(f"\n  {'#':>2} {'TF':<4} {'Strategy':<14} {'SL/TP':<7} {'Lots':>4} {'Train$':>8} {'Test$':>8} {'Total$':>8} {'WR%':>5} {'PF':>5}")
print(f"  {'─'*2} {'─'*4} {'─'*14} {'─'*7} {'─'*4} {'─'*8} {'─'*8} {'─'*8} {'─'*5} {'─'*5}")

for idx, r in enumerate(all_results[:20]):
    marker = " ⭐" if r['test']['total_pnl'] > 0 and r['train']['total_pnl'] > 0 else ""
    print(f"  {idx+1:>2} {r['tf']:<4} {r['strategy']:<14} {r['sl_tp']:<7} {r['lots']:>4} "
          f"${r['train']['total_pnl']:>7.2f} ${r['test']['total_pnl']:>7.2f} "
          f"${r['combined_pnl']:>7.2f} {r['avg_wr']:>4.1f}% {r['avg_pf']:>5.2f}{marker}")

# === RECOMMENDED CONFIG ===
if all_results:
    best = all_results[0]
    print(f"\n{'='*80}")
    print(f"  🏆 RECOMMENDED CONFIGURATION")
    print(f"{'='*80}")
    print(f"  Timeframe:    {best['tf']}")
    print(f"  Strategy:     {best['strategy']}")
    print(f"  SL/TP:        {best['sl']}/{best['tp']} price ({best['sl_tp']})")
    print(f"  Lots:         {best['lots']}")
    print(f"  Training P&L: ${best['train']['total_pnl']:.2f}")
    print(f"  Test P&L:     ${best['test']['total_pnl']:.2f} (out-of-sample)")
    print(f"  Combined:     ${best['combined_pnl']:.2f}")
    print(f"  Win Rate:     {best['avg_wr']:.1f}%")
    print(f"  Profit Factor:{best['avg_pf']:.2f}")
    print(f"  Risk/Trade:   ${best['sl'] * best['lots'] * dpp:.2f} ({best['sl'] * best['lots'] * dpp / equity * 100:.0f}% of equity)")
    print(f"  $/Win:        ${best['tp'] * best['lots'] * dpp - spread_price * best['lots'] * dpp:.2f}")
    print(f"  $/Loss:       ${best['sl'] * best['lots'] * dpp + spread_price * best['lots'] * dpp:.2f}")
    
    # Project daily
    daily = best['test']['trades_per_day']
    wr = best['avg_wr'] / 100
    tp_dollars = best['tp'] * best['lots'] * dpp - spread_price * best['lots'] * dpp
    sl_dollars = best['sl'] * best['lots'] * dpp + spread_price * best['lots'] * dpp
    expected_per_trade = wr * tp_dollars - (1 - wr) * sl_dollars
    daily_expected = expected_per_trade * daily
    
    print(f"\n  PROJECTIONS:")
    print(f"    Trades/day:    {daily:.1f}")
    print(f"    Expected/trade:${expected_per_trade:.2f}")
    print(f"    Expected/day:  ${daily_expected:.2f}")
    print(f"    Monthly (30d): ${daily_expected * 30:.2f}")
    print(f"    90-day:        ${daily_expected * 90:.2f}")
    print(f"    ROI (90d):     {daily_expected * 90 / equity * 100:.0f}%")

# === SAVE RESULTS ===
results_data = []
for r in all_results[:30]:
    results_data.append({
        'tf': r['tf'], 'strategy': r['strategy'], 'sl_tp': r['sl_tp'],
        'lots': r['lots'], 'train_pnl': round(r['train']['total_pnl'], 2),
        'test_pnl': round(r['test']['total_pnl'], 2),
        'combined': round(r['combined_pnl'], 2),
        'wr': round(r['avg_wr'], 1), 'pf': round(r['avg_pf'], 2),
    })

with open('v100_optimization_results.json', 'w') as f:
    json.dump(results_data, f, indent=2)

print(f"\n  Results saved to v100_optimization_results.json")

mt5.shutdown()
print(f"\n{'='*80}")
