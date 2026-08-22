#!/usr/bin/env python3
"""
MITEMSHUB AI v14 — Walk-Forward Backtest
==========================================
Regime detection + pullback entry + compression breakout
Walk-forward validation across 3 windows

Targets:
  - Profit Factor > 1.20
  - Max Drawdown < 15-20%
  - Positive in most walk-forward windows
  - No single month responsible for most profits
"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime
import json, sys, os

sys.stdout.reconfigure(encoding='utf-8')

# ─── STRATEGY PARAMETERS (matching v14 EA) ──────────────────────
EMA_FAST      = 20
EMA_MID       = 50
EMA_SLOW      = 100
PULLBACK_MIN  = 0.3    # min pullback to EMA (ATR units)
PULLBACK_MAX  = 2.0    # max pullback to EMA
RSI_PERIOD    = 14
ATR_PERIOD    = 14
ATR_LOW_PCT   = 15.0
ATR_HIGH_PCT  = 85.0
COMPRESS_BARS = 20
COMPRESS_ATR  = 0.7
BREAKOUT_MIN  = 0.15
RISK_PER_TRADE= 0.005  # 0.5%
ATR_STOP      = 1.5
ATR_TARGET    = 2.0
HOLD_BARS     = 12     # 60 min on M5
MAX_DAILY_LOSS= 0.02
MAX_CONSEC    = 3
COOLDOWN      = 3


# ─── INDICATOR HELPERS ───────────────────────────────────────────
def calc_ema(closes, period):
    """Calculate EMA for entire array"""
    alpha = 2.0 / (period + 1.0)
    ema = np.zeros(len(closes))
    ema[0] = closes[0]
    for i in range(1, len(closes)):
        ema[i] = closes[i] * alpha + ema[i-1] * (1 - alpha)
    return ema

def calc_rsi(closes, period):
    """Calculate RSI"""
    rsi = np.full(len(closes), 50.0)
    for i in range(period, len(closes)):
        gains = []
        losses = []
        for j in range(i-period, i):
            diff = closes[j+1] - closes[j]
            if diff > 0:
                gains.append(diff)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(-diff)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss < 1e-12:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi

def calc_atr(highs, lows, closes, period):
    """Calculate ATR"""
    atr = np.zeros(len(closes))
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        if i < period:
            atr[i] = np.mean([max(highs[j]-lows[j], abs(highs[j]-closes[max(0,j-1)]), abs(lows[j]-closes[max(0,j-1)])) for j in range(1, i+1)])
        else:
            # Simple average of last `period` TR values
            trs = []
            for j in range(i-period+1, i+1):
                tr_val = max(
                    highs[j] - lows[j],
                    abs(highs[j] - closes[j-1]),
                    abs(lows[j] - closes[j-1])
                )
                trs.append(tr_val)
            atr[i] = np.mean(trs)
    return atr

def calc_atr_percentile(atr_values, lookback, i):
    """Calculate ATR percentile rank"""
    if i < lookback:
        return 50.0
    current = atr_values[i]
    count_below = np.sum(atr_values[i-lookback:i] < current)
    return count_below / lookback * 100.0


# ─── REGIME CLASSIFIER ──────────────────────────────────────────
def classify_regime(m15_close, m15_high, m15_low, m15_ema_fast, m15_ema_mid, m15_ema_slow, m15_atr_pct, i):
    """
    Classify market regime using M15 data
    Returns: 1=bullish, -1=bearish, 0=ranging, 2=high_vol, -2=no_trade
    """
    if i < EMA_SLOW:
        return -2  # no data
    
    price = m15_close[i]
    ema_f = m15_ema_fast[i]
    ema_m = m15_ema_mid[i]
    ema_s = m15_ema_slow[i]
    
    # ATR filter
    if m15_atr_pct[i] > ATR_HIGH_PCT:
        return 2  # high vol
    if m15_atr_pct[i] < ATR_LOW_PCT:
        return -2  # too quiet
    
    # EMA alignment
    if ema_f > ema_m > ema_s and price > ema_f:
        return 1  # bullish
    if ema_f < ema_m < ema_s and price < ema_f:
        return -1  # bearish
    
    return 0  # ranging


# ─── BACKTEST ENGINE ─────────────────────────────────────────────
def backtest_v14(m5_rates, m15_rates, symbol_name, start_idx=0, end_idx=None, label=""):
    """
    Run v14 backtest on a slice of data
    Returns list of trade dicts
    """
    if end_idx is None:
        end_idx = len(m5_rates['close'])
    
    # Extract M5 data
    closes = m5_rates['close'][start_idx:end_idx]
    highs = m5_rates['high'][start_idx:end_idx]
    lows = m5_rates['low'][start_idx:end_idx]
    times = m5_rates['time'][start_idx:end_idx]
    n = len(closes)
    
    # Calculate M5 indicators
    m5_atr = calc_atr(highs, lows, closes, ATR_PERIOD)
    m5_rsi = calc_rsi(closes, RSI_PERIOD)
    m5_ema20 = calc_ema(closes, EMA_FAST)
    
    # Extract M15 data (need to align to M5 time range)
    m15_closes = m15_rates['close']
    m15_highs = m15_rates['high']
    m15_lows = m15_rates['low']
    m15_times = m15_rates['time']
    
    # Calculate M15 EMAs
    m15_ema_fast = calc_ema(m15_closes, EMA_FAST)
    m15_ema_mid = calc_ema(m15_closes, EMA_MID)
    m15_ema_slow = calc_ema(m15_closes, EMA_SLOW)
    m15_atr = calc_atr(m15_highs, m15_lows, m15_closes, ATR_PERIOD)
    
    # M15 ATR percentile
    m15_atr_pct = np.full(len(m15_closes), 50.0)
    for i in range(ATR_PERIOD, len(m15_closes)):
        m15_atr_pct[i] = calc_atr_percentile(m15_atr, 200, i)
    
    # M5 ATR percentile
    m5_atr_pct = np.full(n, 50.0)
    for i in range(ATR_PERIOD, n):
        m5_atr_pct[i] = calc_atr_percentile(m5_atr, 200, i)
    
    # ATR history for compression detection
    atr_history = []
    
    # State
    equity = 30.04
    peak_equity = equity
    daily_pnl = 0.0
    day_start = 0
    cooldown = 0
    consec_loss = 0
    paused = False
    pause_bars = 0
    
    # Position
    in_trade = False
    entry_price = 0.0
    original_risk = 0.0
    sl = 0.0
    tp = 0.0
    direction = 0
    entry_bar = 0
    
    trades = []
    
    for i in range(EMA_SLOW + 10, n):
        # Daily reset
        current_day = times[i] // 86400
        if current_day != day_start:
            day_start = current_day
            daily_pnl = 0.0
        
        if cooldown > 0:
            cooldown -= 1
        if paused and pause_bars > 0:
            pause_bars -= 1
            if pause_bars <= 0:
                paused = False
        
        # Track ATR
        atr_history.append(m5_atr[i])
        if len(atr_history) > 500:
            atr_history.pop(0)
        
        # ─── MANAGE POSITION ───
        if in_trade:
            bars_held = i - entry_bar
            
            # Time exit
            if bars_held >= HOLD_BARS:
                exit_p = closes[i]
                r_mult = (exit_p - entry_price) / original_risk if direction > 0 else (entry_price - exit_p) / original_risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                if r_mult < 0:
                    consec_loss += 1
                    cooldown = COOLDOWN
                else:
                    consec_loss = 0
                
                if consec_loss >= MAX_CONSEC:
                    paused = True
                    pause_bars = 20
                if daily_pnl < -equity * MAX_DAILY_LOSS:
                    paused = True
                    pause_bars = 50
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'entry_time': times[entry_bar], 'exit_time': times[i],
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': exit_p,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TIME', 'bars_held': bars_held
                })
                in_trade = False
                direction = 0
                continue
            
            # SL check
            if direction > 0 and lows[i] <= sl:
                r_mult = (sl - entry_price) / original_risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                consec_loss += 1
                cooldown = COOLDOWN
                if consec_loss >= MAX_CONSEC:
                    paused = True
                    pause_bars = 20
                if daily_pnl < -equity * MAX_DAILY_LOSS:
                    paused = True
                    pause_bars = 50
                if (peak_equity - equity) > peak_equity * 0.10:
                    paused = True
                    pause_bars = 100
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'entry_time': times[entry_bar], 'exit_time': times[i],
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': sl,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'STOP', 'bars_held': bars_held
                })
                in_trade = False
                direction = 0
                continue
            
            if direction < 0 and highs[i] >= sl:
                r_mult = (entry_price - sl) / original_risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                consec_loss += 1
                cooldown = COOLDOWN
                if consec_loss >= MAX_CONSEC:
                    paused = True
                    pause_bars = 20
                if daily_pnl < -equity * MAX_DAILY_LOSS:
                    paused = True
                    pause_bars = 50
                if (peak_equity - equity) > peak_equity * 0.10:
                    paused = True
                    pause_bars = 100
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'entry_time': times[entry_bar], 'exit_time': times[i],
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': sl,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'STOP', 'bars_held': bars_held
                })
                in_trade = False
                direction = 0
                continue
            
            # TP check
            if direction > 0 and highs[i] >= tp:
                r_mult = (tp - entry_price) / original_risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                consec_loss = 0
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'entry_time': times[entry_bar], 'exit_time': times[i],
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': tp,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TARGET', 'bars_held': bars_held
                })
                in_trade = False
                direction = 0
                continue
            
            if direction < 0 and lows[i] <= tp:
                r_mult = (entry_price - tp) / original_risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                consec_loss = 0
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'entry_time': times[entry_bar], 'exit_time': times[i],
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': tp,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TARGET', 'bars_held': bars_held
                })
                in_trade = False
                direction = 0
                continue
            
            continue  # still in trade, skip entry
        
        # ─── ENTRY GATE ───
        if paused or cooldown > 0:
            continue
        
        atr = m5_atr[i]
        if atr <= 0:
            continue
        
        price = closes[i]
        rsi = m5_rsi[i]
        ema20_m5 = m5_ema20[i]
        
        # Find matching M15 bar
        m15_idx = -1
        for j in range(len(m15_times)-1, -1, -1):
            if m15_times[j] <= times[i]:
                m15_idx = j
                break
        
        if m15_idx < 0 or m15_idx < EMA_SLOW:
            continue
        
        # Classify regime
        regime = classify_regime(m15_closes, m15_highs, m15_lows,
                                  m15_ema_fast, m15_ema_mid, m15_ema_slow,
                                  m15_atr_pct, m15_idx)
        
        # No trade in bad regimes
        if regime == -2 or regime == 2:
            continue
        
        signal = 0
        signal_type = ""
        
        # ─── MODE 1: TRENDING → PULLBACK ENTRY ───
        if regime == 1 or regime == -1:
            d = 1 if regime == 1 else -1
            
            pullback_dist = abs(price - ema20_m5)
            if pullback_dist < PULLBACK_MIN * atr:
                continue
            if pullback_dist > PULLBACK_MAX * atr:
                continue
            
            # Price must be on correct side for pullback
            if d > 0 and price > ema20_m5 + atr:
                continue
            if d < 0 and price < ema20_m5 - atr:
                continue
            
            # RSI confirmation
            if d > 0 and rsi > 60:
                continue
            if d < 0 and rsi < 40:
                continue
            
            # Confirmation candle
            if i < 2:
                continue
            last_body = closes[i] - closes[i-1]
            if d > 0 and last_body <= 0:
                continue
            if d < 0 and last_body >= 0:
                continue
            
            # Gap check
            gap = abs(closes[i] - closes[i-1])
            if gap > atr * 0.5:
                continue
            
            signal = d
            signal_type = "PULLBACK_" + ("LONG" if d > 0 else "SHORT")
        
        # ─── MODE 2: RANGING → COMPRESSION BREAKOUT ───
        elif regime == 0 and len(atr_history) >= COMPRESS_BARS:
            # Check compression
            avg_atr = np.mean(atr_history[-100:]) if len(atr_history) >= 100 else np.mean(atr_history)
            if atr >= avg_atr * COMPRESS_ATR:
                continue
            
            # Find range
            range_high = max(highs[max(0,i-COMPRESS_BARS):i])
            range_low = min(lows[max(0,i-COMPRESS_BARS):i])
            range_size = range_high - range_low
            
            if range_size < atr * 0.5:
                continue
            
            # Breakout check
            if closes[i] > range_high + BREAKOUT_MIN * atr:
                # Bullish breakout
                candle_size = highs[i] - lows[i]
                if candle_size > atr * 2.0:
                    continue
                if rsi < 50:
                    continue
                signal = 1
                signal_type = "BREAKOUT_UP"
            elif closes[i] < range_low - BREAKOUT_MIN * atr:
                # Bearish breakout
                candle_size = highs[i] - lows[i]
                if candle_size > atr * 2.0:
                    continue
                if rsi > 50:
                    continue
                signal = -1
                signal_type = "BREAKOUT_DOWN"
        
        if signal == 0:
            continue
        
        # Calculate SL/TP
        entry = closes[i]
        sd = ATR_STOP * atr
        td = ATR_TARGET * atr
        
        max_stop = entry * 0.02
        if sd > max_stop:
            sd = max_stop
        if sd < atr * 0.5:
            sd = atr * 0.5
        
        if signal > 0:
            sl = entry - sd
            tp = entry + td
        else:
            sl = entry + sd
            tp = entry - td
        
        # Enter
        direction = signal
        entry_price = entry
        original_risk = sd
        entry_bar = i
        in_trade = True
    
    return trades, equity, peak_equity


def print_results(trades, equity, peak_equity, symbol, label, days):
    """Print detailed results"""
    if not trades:
        print(f"\n  {symbol} — {label}: NO TRADES")
        return None
    
    wins = [t for t in trades if t['r_mult'] > 0]
    losses = [t for t in trades if t['r_mult'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    wr = len(wins) / len(trades) * 100
    
    avg_win = np.mean([t['r_mult'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['r_mult'] for t in losses]) if losses else 0
    
    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    pf = gross_profit / max(gross_loss, 0.01)
    
    # Max drawdown
    running_eq = 30.04
    peak_eq = 30.04
    max_dd = 0
    for t in trades:
        running_eq += t['pnl']
        peak_eq = max(peak_eq, running_eq)
        dd = (peak_eq - running_eq) / peak_eq * 100
        max_dd = max(max_dd, dd)
    
    # Sharpe
    pnls = [t['pnl'] for t in trades]
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252)
    else:
        sharpe = 0
    
    # Consecutive losses
    max_cl = 0
    cl = 0
    for t in trades:
        if t['r_mult'] < 0:
            cl += 1
            max_cl = max(max_cl, cl)
        else:
            cl = 0
    
    # By exit reason
    stops = len([t for t in trades if t['exit_reason'] == 'STOP'])
    targets = len([t for t in trades if t['exit_reason'] == 'TARGET'])
    times_e = len([t for t in trades if t['exit_reason'] == 'TIME'])
    
    # By signal type
    pullbacks = len([t for t in trades if 'PULLBACK' in str(t.get('signal_type',''))])
    breakouts = len([t for t in trades if 'BREAKOUT' in str(t.get('signal_type',''))])
    
    expectancy = total_pnl / len(trades)
    trades_per_day = len(trades) / max(0.1, days)
    
    print(f"\n  {symbol} — {label}")
    print(f"  {'─'*60}")
    print(f"  ${30.04:.2f} → ${equity:.2f} ({'+'if equity>30.04 else ''}{equity-30.04:.2f}) | Peak: ${peak_equity:.2f} | MaxDD: {max_dd:.1f}%")
    print(f"  Trades: {len(trades)} ({trades_per_day:.1f}/day) | Win: {len(wins)} ({wr:.0f}%) | Loss: {len(losses)}")
    print(f"  AvgR: W={avg_win:+.2f} L={avg_loss:+.2f} | PF: {pf:.2f} | Sharpe: {sharpe:.2f}")
    print(f"  Exits: {targets} TP | {stops} SL | {times_e} TIME")
    print(f"  Expectancy: ${expectancy:.2f}/trade")
    print(f"  Max Consec Loss: {max_cl}")
    
    # Targets check
    pf_ok = "✅" if pf >= 1.20 else "❌"
    dd_ok = "✅" if max_dd < 20 else "❌"
    print(f"\n  TARGETS: PF>1.20 {pf_ok} ({pf:.2f}) | MaxDD<20% {dd_ok} ({max_dd:.1f}%)")
    
    return {
        'symbol': symbol, 'label': label, 'trades': len(trades),
        'win_rate': wr, 'pnl': total_pnl, 'final_equity': equity,
        'peak_equity': peak_equity, 'profit_factor': pf, 'sharpe': sharpe,
        'max_dd': max_dd, 'expectancy': expectancy, 'trades_per_day': trades_per_day,
        'avg_win_r': avg_win, 'avg_loss_r': avg_loss,
        'stops': stops, 'targets': targets, 'times': times_e,
        'max_consec_loss': max_cl
    }


# ─── MAIN ────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not mt5.initialize():
        print("MT5 init failed!")
        sys.exit(1)
    
    print("=" * 70)
    print("  MITEMSHUB AI v14 — WALK-FORWARD BACKTEST")
    print("  Regime Detection + Pullback Entry + Compression Breakout")
    print("=" * 70)
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Starting: $30.04 | Risk: 0.5%/trade | MaxDD: 2% daily")
    
    all_results = []
    
    for sym in ['Volatility 100 Index', 'Volatility 75 Index']:
        print(f"\n{'='*70}")
        print(f"  {sym}")
        print(f"{'='*70}")
        
        # Load data
        m5_rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 50000)
        m15_rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 20000)
        
        if m5_rates is None or m15_rates is None:
            print(f"  ❌ No data for {sym}")
            continue
        
        n_m5 = len(m5_rates)
        n_m15 = len(m15_rates)
        days = (m5_rates[-1]['time'] - m5_rates[0]['time']) / 86400
        
        print(f"  M5: {n_m5} bars ({days:.0f} days)")
        print(f"  M15: {n_m15} bars")
        
        # ─── WALK-FORWARD: 3 WINDOWS ───
        warmup = EMA_SLOW * 3 + 200  # need enough bars for indicators
        total_usable = n_m5 - warmup
        window_size = total_usable // 3
        
        print(f"\n  Walk-forward: 3 windows of ~{window_size} bars (~{window_size*5/1440:.0f} days)")
        
        window_results = []
        
        for w in range(3):
            w_start = warmup + w * window_size
            w_end = min(w_start + window_size, n_m5)
            
            if w_end - w_start < 100:
                continue
            
            w_days = (m5_rates[w_end-1]['time'] - m5_rates[w_start]['time']) / 86400
            w_start_date = datetime.fromtimestamp(m5_rates[w_start]['time']).strftime('%Y-%m-%d')
            w_end_date = datetime.fromtimestamp(m5_rates[w_end-1]['time']).strftime('%Y-%m-%d')
            
            print(f"\n  Window {w+1}: {w_start_date} to {w_end_date} ({w_days:.0f} days)")
            
            trades, equity, peak = backtest_v14(m5_rates, m15_rates, sym, w_start, w_end, f"Window {w+1}")
            
            r = print_results(trades, equity, peak, sym, f"Window {w+1} ({w_start_date} to {w_end_date})", w_days)
            if r:
                r['window'] = w + 1
                r['start_date'] = w_start_date
                r['end_date'] = w_end_date
                r['days'] = w_days
                window_results.append(r)
                all_results.append(r)
        
        # ─── FULL PERIOD ───
        print(f"\n  {'─'*60}")
        print(f"  FULL PERIOD:")
        trades, equity, peak = backtest_v14(m5_rates, m15_rates, sym, warmup, n_m5, "Full")
        r = print_results(trades, equity, peak, sym, "Full Period", days)
        if r:
            r['window'] = 0
            r['days'] = days
            all_results.append(r)
        
        # ─── WALK-FORWARD SUMMARY ───
        if window_results:
            print(f"\n  WALK-FORWARD SUMMARY:")
            print(f"  {'Window':<12} {'Trades':>6} {'WR%':>5} {'P&L':>8} {'PF':>5} {'MaxDD':>5}")
            print(f"  {'─'*45}")
            profitable_windows = 0
            for r in window_results:
                marker = "✅" if r['pnl'] > 0 else "❌"
                print(f"  {marker} Window {r['window']}: {r['trades']:>4} {r['win_rate']:>4.0f}% "
                      f"{r['pnl']:>+7.2f} {r['profit_factor']:>5.2f} {r['max_dd']:>4.1f}%")
                if r['pnl'] > 0:
                    profitable_windows += 1
            
            wr_pct = profitable_windows / len(window_results) * 100
            avg_pf = np.mean([r['profit_factor'] for r in window_results])
            avg_dd = np.mean([r['max_dd'] for r in window_results])
            
            print(f"\n  Walk-forward score: {profitable_windows}/{len(window_results)} windows profitable ({wr_pct:.0f}%)")
            print(f"  Average PF: {avg_pf:.2f} | Average MaxDD: {avg_dd:.1f}%")
            
            # Check if targets met
            if avg_pf >= 1.20 and avg_dd < 20 and profitable_windows >= 2:
                print(f"\n  🎯 WALK-FORWARD VALIDATION: PASSED ✅")
            else:
                print(f"\n  🎯 WALK-FORWARD VALIDATION: NEEDS MORE WORK ❌")
                if avg_pf < 1.20:
                    print(f"     PF {avg_pf:.2f} < 1.20 target")
                if avg_dd >= 20:
                    print(f"     MaxDD {avg_dd:.1f}% >= 20% target")
                if profitable_windows < 2:
                    print(f"     Only {profitable_windows}/{len(window_results)} windows profitable")
    
    # ─── FINAL SUMMARY ───
    print(f"\n\n{'='*70}")
    print(f"  FINAL SUMMARY — ALL RESULTS")
    print(f"{'='*70}")
    print(f"  {'Symbol':<18} {'Window':<10} {'Trades':>5} {'WR%':>5} {'P&L':>8} {'PF':>5} {'DD%':>5}")
    print(f"  {'─'*62}")
    for r in all_results:
        marker = "🔥" if r['pnl'] > 0 else "  "
        w = f"W{r['window']}" if r['window'] > 0 else "FULL"
        print(f"  {marker}{r['symbol']:<16} {w:<10} {r['trades']:>5} "
              f"{r['win_rate']:>4.0f}% {r['pnl']:>+7.2f} {r['profit_factor']:>5.2f} {r['max_dd']:>4.1f}%")
    
    # Save
    os.makedirs('data', exist_ok=True)
    with open('data/backtest_v14_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print(f"\n  Results saved to data/backtest_v14_results.json")
    print(f"\n{'='*70}")
    
    mt5.shutdown()
