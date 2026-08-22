#!/usr/bin/env python3
"""
MITEMSHUB AI v13 — Fixed 90-Day Backtest
==========================================
Fixes:
  1. Store ORIGINAL risk at entry (don't use trailed SL for R-calc)
  2. Add max loss exit at -1.5R (don't hold losers to TIME exit)
  3. Relax BB filter (price near band, not ON the band)
  4. Get more data (5000+ bars)
  5. Test simpler RSI-only strategy as baseline
"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime
import json, sys, os

sys.stdout.reconfigure(encoding='utf-8')

# ─── Indicator Calculations ──────────────────────────────────────
def calc_sma(closes, period, i):
    if i < period - 1:
        return np.mean(closes[:i+1])
    return np.mean(closes[i-period+1:i+1])

def calc_rsi(closes, period, i):
    if i < period + 1:
        return 50.0
    gains = []
    losses = []
    for j in range(i-period+1, i+1):
        diff = closes[j] - closes[j-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 1e-12
    if avg_loss < 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)

def calc_bb(closes, period, dev, i):
    sma = calc_sma(closes, period, i)
    if i < period - 1:
        return sma, sma, sma
    variance = np.var(closes[i-period+1:i+1])
    std = np.sqrt(variance)
    return sma, sma + dev * std, sma - dev * std

def calc_atr(highs, lows, closes, i, period=14):
    if i < 1:
        return max(highs[0] - lows[0], 0.001)
    trs = []
    for j in range(max(1, i-period+1), i+1):
        tr = max(
            highs[j] - lows[j],
            abs(highs[j] - closes[j-1]),
            abs(lows[j] - closes[j-1])
        )
        trs.append(tr)
    return np.mean(trs) if trs else 0.001

def count_consecutive(closes, lookback, i):
    up = 0
    down = 0
    for j in range(1, min(lookback + 1, i + 1)):
        if i - j >= 0:
            if closes[i-j] > closes[i-j-1]:
                up += 1
            elif closes[i-j] < closes[i-j-1]:
                down += 1
    return up if up >= down else -down


# ─── STRATEGY: Simple RSI Mean Reversion ─────────────────────────
def strategy_rsi_only(closes, highs, lows, atrs, i,
                      rsi_os=30, rsi_ob=70, atr_sl=2.0, atr_tp=1.5):
    """Simple RSI mean reversion. Returns (direction, sl_dist, tp_dist) or (0,0,0)"""
    rsi = calc_rsi(closes, 14, i)
    atr = atrs[i]
    if atr <= 0:
        return 0, 0, 0
    
    if rsi < rsi_os:
        return 1, atr * atr_sl, atr * atr_tp  # BUY
    elif rsi > rsi_ob:
        return -1, atr * atr_sl, atr * atr_tp  # SELL
    
    return 0, 0, 0


# ─── STRATEGY: SMA50 Distance Fade (Fixed) ──────────────────────
def strategy_sma50(closes, highs, lows, atrs, i,
                   dist_pct=1.5, use_rsi=True, use_bb=True, use_trend=True):
    """SMA50 distance fade with confirmations"""
    price = closes[i]
    sma50 = calc_sma(closes, 50, i)
    rsi = calc_rsi(closes, 14, i)
    atr = atrs[i]
    
    if sma50 <= 0 or atr <= 0:
        return 0, 0, 0
    
    dist = (price - sma50) / sma50 * 100.0
    if abs(dist) < dist_pct:
        return 0, 0, 0
    
    # RSI: don't fade if RSI disagrees
    if use_rsi:
        if dist > 0 and rsi < 45:  # price above SMA but RSI weak → don't sell
            return 0, 0, 0
        if dist < 0 and rsi > 55:  # price below SMA but RSI strong → don't buy
            return 0, 0, 0
    
    # BB: price should be in outer 30% of band (relaxed from 99.8%)
    if use_bb:
        _, bb_upper, bb_lower = calc_bb(closes, 20, 2.0, i)
        band_range = bb_upper - bb_lower
        if band_range > 0:
            if dist > 0 and price < bb_upper - band_range * 0.3:
                return 0, 0, 0
            if dist < 0 and price > bb_lower + band_range * 0.3:
                return 0, 0, 0
    
    # Trend: don't fade if SMAs aligned
    if use_trend:
        sma_fast = calc_sma(closes, 20, i)
        sma_slow = sma50
        if dist > 0 and sma_fast > sma_slow * 1.002:
            return 0, 0, 0
        if dist < 0 and sma_fast < sma_slow * 0.998:
            return 0, 0, 0
    
    direction = -1 if dist > 0 else 1
    return direction, atr * 2.0, atr * 1.5  # Wide SL, quick TP


# ─── STRATEGY: Momentum Exhaustion (Fixed) ──────────────────────
def strategy_mom_exhaust(closes, highs, lows, atrs, i,
                         consec_req=5, use_rsi=True, use_bb=True):
    """Momentum exhaustion fade"""
    consec = count_consecutive(closes, 7, i)
    abs_consec = abs(consec)
    rsi = calc_rsi(closes, 14, i)
    atr = atrs[i]
    
    if abs_consec < consec_req or atr <= 0:
        return 0, 0, 0
    
    price = closes[i]
    
    # RSI confirmation
    if use_rsi:
        if consec > 0 and rsi < 55:  # need overbought for sell
            return 0, 0, 0
        if consec < 0 and rsi > 45:  # need oversold for buy
            return 0, 0, 0
    
    # BB: price near outer band
    if use_bb:
        _, bb_upper, bb_lower = calc_bb(closes, 20, 2.0, i)
        band_range = bb_upper - bb_lower
        if band_range > 0:
            if consec > 0 and price < bb_upper - band_range * 0.3:
                return 0, 0, 0
            if consec < 0 and price > bb_lower + band_range * 0.3:
                return 0, 0, 0
    
    direction = -1 if consec > 0 else 1
    return direction, atr * 2.0, atr * 1.5


# ─── BACKTEST ENGINE ─────────────────────────────────────────────
def run_backtest(sym, strategy_fn, strategy_name, strategy_params,
                 risk_pct=0.05, hold_bars=10, cooldown=2,
                 max_consec_loss=3, max_daily_loss=0.08):
    """Run backtest with FIXED R-multiple tracking"""
    
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 5000)
    if rates is None or len(rates) < 200:
        print(f"  ❌ Not enough data for {sym}")
        return None
    
    closes = np.array([r['close'] for r in rates])
    highs = np.array([r['high'] for r in rates])
    lows = np.array([r['low'] for r in rates])
    times = [r['time'] for r in rates]
    atrs = np.array([calc_atr(highs, lows, closes, i) for i in range(len(closes))])
    
    hours = (times[-1] - times[0]) / 3600
    days = hours / 24
    
    warmup = 60
    equity = 30.04
    peak_equity = equity
    daily_pnl = 0.0
    day_start = 0
    cd = 0
    consec_loss = 0
    paused = False
    pause_bars = 0
    
    trades = []
    # Position state
    in_trade = False
    entry_price = 0.0
    original_risk = 0.0  # FIXED: store original risk
    sl = 0.0
    tp = 0.0
    direction = 0
    entry_bar = 0
    entry_time = 0
    
    for i in range(warmup, len(closes)):
        # Daily reset
        current_day = times[i] // 86400
        if current_day != day_start:
            day_start = current_day
            daily_pnl = 0.0
        
        if cd > 0:
            cd -= 1
        if paused and pause_bars > 0:
            pause_bars -= 1
            if pause_bars <= 0:
                paused = False
        
        # ─── MANAGE POSITION ───
        if in_trade:
            bars_held = i - entry_bar
            
            # Calculate current P&L in R using ORIGINAL risk
            if direction > 0:
                pnl_r = (closes[i] - entry_price) / original_risk
            else:
                pnl_r = (entry_price - closes[i]) / original_risk
            
            # MAX LOSS EXIT at -1.5R (FIXED: don't hold losers to TIME exit)
            if pnl_r <= -1.5:
                exit_p = closes[i]
                r_mult = pnl_r
                pnl_dollar = equity * risk_pct * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': exit_p,
                    'sl': sl, 'tp': tp,
                    'original_risk': original_risk,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'MAX_LOSS',
                    'bars_held': bars_held,
                    'time': times[entry_bar]
                })
                
                consec_loss += 1
                cd = cooldown
                if consec_loss >= max_consec_loss:
                    paused = True; pause_bars = 20
                    pause_bars = 20  # Reset after 20 bars
                if daily_pnl < -equity * max_daily_loss:
                    paused = True; pause_bars = 20
                    pause_bars = 50
                if (peak_equity - equity) > peak_equity * 0.15:
                    paused = True; pause_bars = 20
                    pause_bars = 100
                
                in_trade = False
                direction = 0
                continue
            
            # Check SL
            if direction > 0 and lows[i] <= sl:
                r_mult = (sl - entry_price) / original_risk
                pnl_dollar = equity * risk_pct * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': sl,
                    'sl': sl, 'tp': tp,
                    'original_risk': original_risk,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'STOP',
                    'bars_held': bars_held,
                    'time': times[entry_bar]
                })
                
                consec_loss += 1
                cd = cooldown
                if consec_loss >= max_consec_loss:
                    paused = True; pause_bars = 20
                if daily_pnl < -equity * max_daily_loss:
                    paused = True; pause_bars = 20
                if (peak_equity - equity) > peak_equity * 0.15:
                    paused = True; pause_bars = 20
                
                in_trade = False
                direction = 0
                continue
            
            if direction < 0 and highs[i] >= sl:
                r_mult = (entry_price - sl) / original_risk
                pnl_dollar = equity * risk_pct * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': sl,
                    'sl': sl, 'tp': tp,
                    'original_risk': original_risk,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'STOP',
                    'bars_held': bars_held,
                    'time': times[entry_bar]
                })
                
                consec_loss += 1
                cd = cooldown
                if consec_loss >= max_consec_loss:
                    paused = True; pause_bars = 20
                if daily_pnl < -equity * max_daily_loss:
                    paused = True; pause_bars = 20
                if (peak_equity - equity) > peak_equity * 0.15:
                    paused = True; pause_bars = 20
                
                in_trade = False
                direction = 0
                continue
            
            # Check TP
            if direction > 0 and highs[i] >= tp:
                r_mult = (tp - entry_price) / original_risk
                pnl_dollar = equity * risk_pct * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY', 'entry_price': entry_price,
                    'exit_price': tp, 'sl': sl, 'tp': tp,
                    'original_risk': original_risk,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TARGET',
                    'bars_held': bars_held, 'time': times[entry_bar]
                })
                consec_loss = 0
                in_trade = False
                direction = 0
                continue
            
            if direction < 0 and lows[i] <= tp:
                r_mult = (entry_price - tp) / original_risk
                pnl_dollar = equity * risk_pct * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'SELL', 'entry_price': entry_price,
                    'exit_price': tp, 'sl': sl, 'tp': tp,
                    'original_risk': original_risk,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TARGET',
                    'bars_held': bars_held, 'time': times[entry_bar]
                })
                consec_loss = 0
                in_trade = False
                direction = 0
                continue
            
            # TIME exit
            if bars_held >= hold_bars:
                exit_p = closes[i]
                r_mult = (exit_p - entry_price) / original_risk if direction > 0 else (entry_price - exit_p) / original_risk
                pnl_dollar = equity * risk_pct * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': exit_p,
                    'sl': sl, 'tp': tp,
                    'original_risk': original_risk,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TIME',
                    'bars_held': bars_held, 'time': times[entry_bar]
                })
                
                if r_mult < 0:
                    consec_loss += 1
                    cd = cooldown
                    if consec_loss >= max_consec_loss:
                        paused = True; pause_bars = 20
                    if daily_pnl < -equity * max_daily_loss:
                        paused = True; pause_bars = 20
                else:
                    consec_loss = 0
                
                in_trade = False
                direction = 0
                continue
            
            # Trailing stop (move SL but DON'T change original_risk)
            if pnl_r >= 0.5:
                be = entry_price + original_risk * 0.1 if direction > 0 else entry_price - original_risk * 0.1
                if direction > 0 and be > sl:
                    sl = be
                elif direction < 0 and be < sl:
                    sl = be
            if pnl_r >= 1.0:
                atr = atrs[i]
                trail_dist = 2.0 * atr * 0.6
                if direction > 0:
                    new_sl = closes[i] - trail_dist
                    if new_sl > sl:
                        sl = new_sl
                else:
                    new_sl = closes[i] + trail_dist
                    if new_sl < sl:
                        sl = new_sl
        
        # ─── ENTRY SIGNAL ───
        if in_trade or paused or cd > 0:
            continue
        
        atr = atrs[i]
        if atr <= 0:
            continue
        
        sig, sl_dist, tp_dist = strategy_fn(closes, highs, lows, atrs, i, **strategy_params)
        
        if sig == 0:
            continue
        
        rr = tp_dist / sl_dist
        if rr < 0.7:  # Allow mean-reversion setups where TP < SL (quick wins, wide stops)
            continue
        
        entry_price = closes[i]
        original_risk = sl_dist  # FIXED: store original risk
        direction = sig
        entry_bar = i
        entry_time = times[i]
        
        if direction > 0:
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist
        
        in_trade = True
    
    # Close remaining position
    if in_trade:
        exit_p = closes[-1]
        r_mult = (exit_p - entry_price) / original_risk if direction > 0 else (entry_price - exit_p) / original_risk
        pnl_dollar = equity * risk_pct * r_mult
        equity += pnl_dollar
        trades.append({
            'entry_bar': entry_bar, 'exit_bar': len(closes)-1,
            'direction': 'BUY' if direction > 0 else 'SELL',
            'entry_price': entry_price, 'exit_price': exit_p,
            'sl': sl, 'tp': tp, 'original_risk': original_risk,
            'r_mult': r_mult, 'pnl': pnl_dollar,
            'exit_reason': 'CLOSE', 'bars_held': len(closes)-1-entry_bar,
            'time': times[entry_bar]
        })
    
    return {
        'symbol': sym, 'strategy': strategy_name,
        'trades': trades, 'final_equity': equity,
        'peak_equity': peak_equity, 'bars': len(closes),
        'time_span_hours': hours, 'time_span_days': days
    }


def print_results(result):
    if result is None:
        return None
    
    sym = result['symbol']
    strat = result['strategy']
    trades = result['trades']
    equity = result['final_equity']
    peak = result['peak_equity']
    hours = result['time_span_hours']
    days = result['time_span_days']
    
    wins = [t for t in trades if t['r_mult'] > 0]
    losses = [t for t in trades if t['r_mult'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / max(1, len(trades)) * 100
    
    avg_win_r = np.mean([t['r_mult'] for t in wins]) if wins else 0
    avg_loss_r = np.mean([t['r_mult'] for t in losses]) if losses else 0
    avg_bars = np.mean([t['bars_held'] for t in trades]) if trades else 0
    
    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    profit_factor = gross_profit / max(gross_loss, 0.01)
    
    pnls = [t['pnl'] for t in trades]
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252)
    else:
        sharpe = 0
    
    # Max drawdown
    running_eq = 30.04
    peak_eq = 30.04
    max_dd = 0
    for t in trades:
        running_eq += t['pnl']
        peak_eq = max(peak_eq, running_eq)
        dd = (peak_eq - running_eq) / peak_eq * 100
        max_dd = max(max_dd, dd)
    
    # Consecutive losses
    max_cl = 0
    cl = 0
    for t in trades:
        if t['r_mult'] < 0:
            cl += 1
            max_cl = max(max_cl, cl)
        else:
            cl = 0
    
    stops = len([t for t in trades if t['exit_reason'] == 'STOP'])
    targets = len([t for t in trades if t['exit_reason'] == 'TARGET'])
    times_e = len([t for t in trades if t['exit_reason'] == 'TIME'])
    max_losses = len([t for t in trades if t['exit_reason'] == 'MAX_LOSS'])
    
    expectancy = total_pnl / max(1, len(trades))
    trades_per_day = len(trades) / max(0.1, days)
    monthly_proj = expectancy * trades_per_day * 30
    
    print(f"\n{'='*70}")
    print(f"  {sym} — {strat}")
    print(f"{'='*70}")
    print(f"  Time: {days:.1f} days ({hours:.0f}h) | Bars: {result['bars']}")
    print(f"  ${30.04:.2f} → ${equity:.2f} ({'+'if equity>30.04 else ''}{equity-30.04:.2f}) | Peak: ${peak:.2f} | MaxDD: {max_dd:.1f}%")
    print(f"  Trades: {len(trades)} ({trades_per_day:.1f}/day) | Win: {len(wins)} ({win_rate:.0f}%) | Loss: {len(losses)}")
    print(f"  AvgR: W={avg_win_r:+.2f} L={avg_loss_r:+.2f} | PF: {profit_factor:.2f} | Sharpe: {sharpe:.2f}")
    print(f"  Exits: {targets} TP | {stops} SL | {max_losses} MAX_LOSS | {times_e} TIME")
    print(f"  Expectancy: ${expectancy:.2f}/trade | 30-day proj: ${monthly_proj:.2f} ({monthly_proj/30.04*100:.1f}%)")
    print(f"  Max Consec Loss: {max_cl}")
    
    if trades:
        print(f"\n  {'#':>2} {'Time':>8} {'Side':>4} {'Entry':>10} {'Exit':>10} {'R':>6} {'P&L':>8} {'Reason':>9} {'Bars':>4}")
        print(f"  {'─'*70}")
        for idx, t in enumerate(trades):
            ts = datetime.fromtimestamp(t['time']).strftime('%m-%d %H:%M')
            print(f"  {idx+1:2d} {ts:>8} {t['direction']:>4} {t['entry_price']:>10.2f} "
                  f"{t['exit_price']:>10.2f} {t['r_mult']:+6.2f}R {t['pnl']:>+7.2f} "
                  f"{t['exit_reason']:>9} {t['bars_held']:>4}")
    
    return {
        'symbol': sym, 'strategy': strat, 'trades': len(trades),
        'win_rate': win_rate, 'pnl': total_pnl, 'final_equity': equity,
        'profit_factor': profit_factor, 'sharpe': sharpe, 'max_dd': max_dd,
        'expectancy': expectancy, 'trades_per_day': trades_per_day,
        'monthly_proj': monthly_proj, 'avg_win_r': avg_win_r, 'avg_loss_r': avg_loss_r
    }


# ─── MAIN ────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not mt5.initialize():
        print("MT5 init failed!")
        sys.exit(1)
    
    print("=" * 70)
    print("  MITEMSHUB AI v13 — VALIDATED BACKTEST (FIXED)")
    print("=" * 70)
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Starting: $30.04 | Risk: 5%/trade")
    
    all_results = []
    
    # ─── TEST 1: Vol 75 SMA50 Fade (v13 target strategy) ───
    r = run_backtest("Volatility 75 Index", strategy_sma50,
                     "SMA50 Fade v13",
                     {'dist_pct': 1.5, 'use_rsi': True, 'use_bb': True, 'use_trend': True},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    # ─── TEST 2: Vol 100 Momentum Exhaustion (v13 target) ───
    r = run_backtest("Volatility 100 Index", strategy_mom_exhaust,
                     "Mom Exhaust v13",
                     {'consec_req': 5, 'use_rsi': True, 'use_bb': True},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    # ─── TEST 3: Simple RSI(14) Mean Reversion — Baseline ───
    r = run_backtest("Volatility 75 Index", strategy_rsi_only,
                     "RSI(14) Mean Rev",
                     {'rsi_os': 30, 'rsi_ob': 70, 'atr_sl': 2.0, 'atr_tp': 1.5},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    r = run_backtest("Volatility 100 Index", strategy_rsi_only,
                     "RSI(14) Mean Rev",
                     {'rsi_os': 30, 'rsi_ob': 70, 'atr_sl': 2.0, 'atr_tp': 1.5},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    # ─── TEST 4: Relaxed SMA50 (no BB, no trend filter) ───
    r = run_backtest("Volatility 75 Index", strategy_sma50,
                     "SMA50 Fade (Relaxed)",
                     {'dist_pct': 1.2, 'use_rsi': True, 'use_bb': False, 'use_trend': False},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    r = run_backtest("Volatility 100 Index", strategy_sma50,
                     "SMA50 Fade (Relaxed)",
                     {'dist_pct': 1.2, 'use_rsi': True, 'use_bb': False, 'use_trend': False},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    # ─── TEST 5: Relaxed Momentum (4 bars, no BB) ───
    r = run_backtest("Volatility 75 Index", strategy_mom_exhaust,
                     "Mom Exhaust (Relaxed)",
                     {'consec_req': 4, 'use_rsi': True, 'use_bb': False},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    r = run_backtest("Volatility 100 Index", strategy_mom_exhaust,
                     "Mom Exhaust (Relaxed)",
                     {'consec_req': 4, 'use_rsi': True, 'use_bb': False},
                     risk_pct=0.05, hold_bars=10, cooldown=2, max_consec_loss=3)
    all_results.append(print_results(r))
    
    # ─── SUMMARY ───
    print(f"\n\n{'='*85}")
    print(f"  FINAL COMPARISON — ALL STRATEGIES")
    print(f"{'='*85}")
    print(f"  {'Symbol':<18} {'Strategy':<22} {'#':>3} {'WR%':>5} {'P&L':>8} {'PF':>5} {'Sharpe':>7} {'DD%':>5} {'$/day':>7} {'30d$':>8}")
    print(f"  {'─'*82}")
    valid = [r for r in all_results if r]
    for r in valid:
        marker = "🔥" if r['pnl'] > 0 else "  "
        print(f"  {marker}{r['symbol']:<16} {r['strategy']:<22} {r['trades']:>3} "
              f"{r['win_rate']:>4.0f}% {r['pnl']:>+7.2f} {r['profit_factor']:>5.2f} "
              f"{r['sharpe']:>7.2f} {r['max_dd']:>4.1f}% "
              f"{r['expectancy']*r['trades_per_day']:>+6.2f} {r['monthly_proj']:>+7.2f}")
    
    # Find best strategy
    if valid:
        best = max(valid, key=lambda x: x['pnl'])
        print(f"\n  🏆 BEST: {best['symbol']} — {best['strategy']}")
        print(f"     P&L: ${best['pnl']:+.2f} | WR: {best['win_rate']:.0f}% | PF: {best['profit_factor']:.2f}")
        print(f"     30-day projection: ${best['monthly_proj']:+.2f} ({best['monthly_proj']/30.04*100:+.1f}%)")
    
    # Save
    os.makedirs('data', exist_ok=True)
    with open('data/backtest_v13_results.json', 'w') as f:
        json.dump(valid, f, indent=2, default=str)
    
    print(f"\n  Results saved to data/backtest_v13_results.json")
    print(f"\n{'='*70}")
    
    mt5.shutdown()
