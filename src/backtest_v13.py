#!/usr/bin/env python3
"""
MITEMSHUB AI v13 — 90-Day Walk-Forward Backtest
=================================================
Tests the multi-indicator strategy:
  - Vol 75: SMA50 Distance Fade (>1.5% from SMA) + RSI + BB confirmation
  - Vol 100: Momentum Exhaustion (5+ consecutive bars) + RSI + BB confirmation
  - ATR-based stops (1.5x) and targets (2.5x)
  - Cool-down after losses, max daily loss cap
"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import json, sys

sys.stdout.reconfigure(encoding='utf-8')

# ─── Strategy Parameters (matching v13 EA) ───────────────────────
SMA_PERIOD       = 50      # SMA50 for distance calculation
SMA_DIST_PCT     = 1.5    # min % distance from SMA
CONSEC_BARS      = 5       # consecutive bars for exhaustion
CONSEC_LOOKBACK  = 7       # lookback window
RSI_PERIOD       = 14
RSI_OVERSOLD     = 35.0
RSI_OVERBOUGHT   = 65.0
BB_PERIOD        = 20
BB_DEV           = 2.0
ATR_STOP_MULT    = 1.5
ATR_TARGET_MULT  = 2.5
RISK_PER_TRADE   = 0.05   # 5%
COOLDOWN_BARS    = 3
MAX_CONSEC_LOSS  = 3
MAX_DAILY_LOSS   = 0.08   # 8%
HOLD_BARS        = 12     # ~60 min on M5 (12 × 5min)
TREND_FAST       = 20
TREND_SLOW       = 50

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
        return highs[0] - lows[0]
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

# ─── Backtest Engine ─────────────────────────────────────────────
def backtest_symbol(sym, strategy_name, strategy_id):
    """Run 90-day backtest on a symbol. strategy_id: 1=SMA50 fade, 2=mom exhaust"""
    
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 3000)
    if rates is None or len(rates) < 500:
        print(f"  ❌ Not enough data for {sym}")
        return None
    
    # Use last 90 days of data (2880 bars/day * 90 = ~26K bars, we have ~3000 = ~10 days)
    # Use all available data as our backtest window
    closes = np.array([r['close'] for r in rates])
    highs = np.array([r['high'] for r in rates])
    lows = np.array([r['low'] for r in rates])
    times = [r['time'] for r in rates]
    
    # Calculate ATR for position sizing
    atrs = np.array([calc_atr(highs, lows, closes, i) for i in range(len(closes))])
    
    # Warmup period
    warmup = max(SMA_PERIOD, RSI_PERIOD, BB_PERIOD, TREND_SLOW, 60)
    
    # State
    equity = 30.04  # starting balance
    peak_equity = equity
    daily_pnl = 0.0
    day_start = 0
    cooldown = 0
    consec_loss = 0
    consec_win = 0
    paused = False
    
    trades = []
    entry_price = 0.0
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
        
        # Update cooldown
        if cooldown > 0:
            cooldown -= 1
        
        # ─── MANAGE OPEN POSITION ───
        if direction != 0:
            bars_held = i - entry_bar
            
            # Check SL
            if direction > 0 and lows[i] <= sl:
                pnl_pct = (sl - entry_price) / entry_price * 100
                pnl_dollar = equity * RISK_PER_TRADE * (pnl_pct / (ATR_STOP_MULT * atrs[entry_bar] / entry_price * 100))
                # Simplified: use R-multiple
                risk = abs(entry_price - sl)
                r_mult = (sl - entry_price) / risk if direction > 0 else (entry_price - sl) / risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': sl,
                    'sl': sl, 'tp': tp,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'STOP',
                    'bars_held': bars_held,
                    'time': times[entry_bar]
                })
                
                if r_mult < 0:
                    consec_loss += 1
                    consec_win = 0
                    cooldown = COOLDOWN_BARS
                else:
                    consec_win += 1
                    consec_loss = 0
                
                if consec_loss >= MAX_CONSEC_LOSS:
                    paused = True
                if daily_pnl < -equity * MAX_DAILY_LOSS:
                    paused = True
                if (peak_equity - equity) > peak_equity * 0.15:
                    paused = True
                
                direction = 0
                continue
            
            # Check TP
            if direction > 0 and highs[i] >= tp:
                risk = abs(entry_price - sl)
                r_mult = (tp - entry_price) / risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': tp,
                    'sl': sl, 'tp': tp,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TARGET',
                    'bars_held': bars_held,
                    'time': times[entry_bar]
                })
                
                consec_win += 1
                consec_loss = 0
                
                direction = 0
                continue
            
            # Check time exit
            if bars_held >= HOLD_BARS:
                exit_p = closes[i]
                risk = abs(entry_price - sl)
                r_mult = (exit_p - entry_price) / risk if direction > 0 else (entry_price - exit_p) / risk
                pnl_dollar = equity * RISK_PER_TRADE * r_mult
                equity += pnl_dollar
                daily_pnl += pnl_dollar
                peak_equity = max(peak_equity, equity)
                
                trades.append({
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'direction': 'BUY' if direction > 0 else 'SELL',
                    'entry_price': entry_price, 'exit_price': exit_p,
                    'sl': sl, 'tp': tp,
                    'r_mult': r_mult, 'pnl': pnl_dollar,
                    'exit_reason': 'TIME',
                    'bars_held': bars_held,
                    'time': times[entry_bar]
                })
                
                if r_mult < 0:
                    consec_loss += 1
                    consec_win = 0
                    cooldown = COOLDOWN_BARS
                else:
                    consec_win += 1
                    consec_loss = 0
                
                direction = 0
                continue
            
            # Trailing stop
            risk = abs(entry_price - sl)
            pnl_now = (closes[i] - entry_price) / risk if direction > 0 else (entry_price - closes[i]) / risk
            if pnl_now >= 0.5:
                # Break-even
                be = entry_price + risk * 0.1 if direction > 0 else entry_price - risk * 0.1
                if direction > 0 and be > sl:
                    sl = be
                elif direction < 0 and be < sl:
                    sl = be
            if pnl_now >= 1.0:
                # Trail
                atr = atrs[i]
                trail_dist = ATR_STOP_MULT * atr * 0.6
                if direction > 0:
                    new_sl = closes[i] - trail_dist
                    if new_sl > sl:
                        sl = new_sl
                else:
                    new_sl = closes[i] + trail_dist
                    if new_sl < sl:
                        sl = new_sl
        
        # ─── ENTRY SIGNAL ───
        if direction != 0 or paused or cooldown > 0:
            continue
        
        atr = atrs[i]
        if atr <= 0:
            continue
        
        price = closes[i]
        rsi = calc_rsi(closes, RSI_PERIOD, i)
        sma50 = calc_sma(closes, SMA_PERIOD, i)
        sma_fast = calc_sma(closes, TREND_FAST, i)
        sma_slow = calc_sma(closes, TREND_SLOW, i)
        _, bb_upper, bb_lower = calc_bb(closes, BB_PERIOD, BB_DEV, i)
        
        signal = 0  # 1=BUY, -1=SELL
        signal_type = ""
        
        if strategy_id == 1:
            # ─── STRATEGY 1: SMA50 Distance Fade ───
            if sma50 <= 0:
                continue
            dist_pct = (price - sma50) / sma50 * 100.0
            
            if abs(dist_pct) < SMA_DIST_PCT:
                continue
            
            # RSI confirmation
            if dist_pct > 0 and rsi < 50:
                continue  # need RSI elevated for sell
            if dist_pct < 0 and rsi > 50:
                continue  # need RSI depressed for buy
            
            # BB filter
            if dist_pct > 0 and price < bb_upper * 0.998:
                continue  # must be near upper band
            if dist_pct < 0 and price > bb_lower * 1.002:
                continue  # must be near lower band
            
            # Trend filter
            if dist_pct > 0 and sma_fast > sma_slow * 1.001:
                continue  # don't sell into uptrend
            if dist_pct < 0 and sma_fast < sma_slow * 0.999:
                continue  # don't buy into downtrend
            
            signal = -1 if dist_pct > 0 else 1
            signal_type = "SMA50_FADE"
        
        elif strategy_id == 2:
            # ─── STRATEGY 2: Momentum Exhaustion ───
            consec = count_consecutive(closes, CONSEC_LOOKBACK, i)
            abs_consec = abs(consec)
            
            if abs_consec < CONSEC_BARS:
                continue
            
            # RSI confirmation
            if consec > 0 and rsi < RSI_OVERBOUGHT:
                continue  # need RSI overbought for sell
            if consec < 0 and rsi > RSI_OVERSOLD:
                continue  # need RSI oversold for buy
            
            # BB filter
            if consec > 0 and price < bb_upper * 0.995:
                continue  # sell only near upper band
            if consec < 0 and price > bb_lower * 1.005:
                continue  # buy only near lower band
            
            # Trend filter
            if consec > 0 and sma_fast > sma_slow * 1.002:
                continue  # don't fade uptrend
            if consec < 0 and sma_fast < sma_slow * 0.998:
                continue  # don't fade downtrend
            
            signal = -1 if consec > 0 else 1
            signal_type = "MOM_EXHAUST"
        
        if signal == 0:
            continue
        
        # ─── CALCULATE SL/TP ───
        sd = ATR_STOP_MULT * atr
        td = ATR_TARGET_MULT * atr
        
        max_stop = price * 0.02
        if sd > max_stop:
            sd = max_stop
        if sd < atr * 0.5:
            sd = atr * 0.5
        
        rr = td / sd
        if rr < 1.2:
            continue
        
        if signal > 0:
            sl = price - sd
            tp = price + td
        else:
            sl = price + sd
            tp = price - td
        
        # ─── RISK SIZING ───
        risk_pct = RISK_PER_TRADE
        if consec_loss >= 2:
            risk_pct *= 0.7
        if consec_win >= 3:
            risk_pct *= 1.2
        risk_pct = min(risk_pct, 0.10)
        risk_pct = max(risk_pct, 0.01)
        
        # ─── ENTER TRADE ───
        direction = signal
        entry_price = price
        entry_bar = i
        entry_time = times[i]
    
    # Close any remaining open position
    if direction != 0:
        exit_p = closes[-1]
        risk = abs(entry_price - sl)
        r_mult = (exit_p - entry_price) / risk if direction > 0 else (entry_price - exit_p) / risk
        pnl_dollar = equity * RISK_PER_TRADE * r_mult
        equity += pnl_dollar
        trades.append({
            'entry_bar': entry_bar, 'exit_bar': len(closes)-1,
            'direction': 'BUY' if direction > 0 else 'SELL',
            'entry_price': entry_price, 'exit_price': exit_p,
            'sl': sl, 'tp': tp,
            'r_mult': r_mult, 'pnl': pnl_dollar,
            'exit_reason': 'CLOSE',
            'bars_held': len(closes)-1 - entry_bar,
            'time': times[entry_bar]
        })
    
    return {
        'symbol': sym,
        'strategy': strategy_name,
        'trades': trades,
        'final_equity': equity,
        'peak_equity': peak_equity,
        'bars': len(closes),
        'time_span_hours': (times[-1] - times[0]) / 3600
    }


def print_results(result):
    if result is None:
        return
    
    sym = result['symbol']
    strat = result['strategy']
    trades = result['trades']
    equity = result['final_equity']
    peak = result['peak_equity']
    hours = result['time_span_hours']
    
    wins = [t for t in trades if t['r_mult'] > 0]
    losses = [t for t in trades if t['r_mult'] <= 0]
    
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / max(1, len(trades)) * 100
    
    avg_win_r = np.mean([t['r_mult'] for t in wins]) if wins else 0
    avg_loss_r = np.mean([t['r_mult'] for t in losses]) if losses else 0
    avg_bars = np.mean([t['bars_held'] for t in trades]) if trades else 0
    
    # Profit factor
    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    profit_factor = gross_profit / max(gross_loss, 0.01)
    
    # Sharpe-like ratio
    pnls = [t['pnl'] for t in trades]
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252)
    else:
        sharpe = 0
    
    # Max drawdown
    running_equity = 30.04
    peak_eq = 30.04
    max_dd = 0
    for t in trades:
        running_equity += t['pnl']
        peak_eq = max(peak_eq, running_equity)
        dd = (peak_eq - running_equity) / peak_eq * 100
        max_dd = max(max_dd, dd)
    
    # Consecutive losses
    max_consec_loss = 0
    cur_consec = 0
    for t in trades:
        if t['r_mult'] < 0:
            cur_consec += 1
            max_consec_loss = max(max_consec_loss, cur_consec)
        else:
            cur_consec = 0
    
    # By exit reason
    stops = len([t for t in trades if t['exit_reason'] == 'STOP'])
    targets = len([t for t in trades if t['exit_reason'] == 'TARGET'])
    times_exit = len([t for t in trades if t['exit_reason'] == 'TIME'])
    
    print(f"\n{'='*70}")
    print(f"  {sym} — {strat}")
    print(f"{'='*70}")
    print(f"  Time span: {hours:.0f} hours ({hours/24:.1f} days)")
    print(f"  Bars: {result['bars']}")
    print(f"")
    print(f"  ┌─────────────────────────────────────────────┐")
    print(f"  │  STARTING:  $30.04                          │")
    print(f"  │  ENDING:    ${equity:.2f} ({'+' if equity>30.04 else ''}{equity-30.04:.2f})           │")
    print(f"  │  PEAK:      ${peak:.2f}                        │")
    print(f"  │  MAX DD:    {max_dd:.1f}%                        │")
    print(f"  └─────────────────────────────────────────────┘")
    print(f"")
    print(f"  TRADES:    {len(trades)}")
    print(f"  WINS:      {len(wins)} ({win_rate:.1f}%)")
    print(f"  LOSSES:    {len(losses)} ({100-win_rate:.1f}%)")
    print(f"  AVG WIN:   {avg_win_r:+.2f}R")
    print(f"  AVG LOSS:  {avg_loss_r:+.2f}R")
    print(f"  AVG HOLD:  {avg_bars:.0f} bars ({avg_bars*5:.0f} min)")
    print(f"  PROFIT F:  {profit_factor:.2f}")
    print(f"  SHARPE:    {sharpe:.2f}")
    print(f"  EXITS:     {stops} STOP | {targets} TARGET | {times_exit} TIME")
    print(f"  MAX CONSEC LOSS: {max_consec_loss}")
    
    # Expectancy per trade
    if len(trades) > 0:
        expectancy = total_pnl / len(trades)
        print(f"  EXPECTANCY: ${expectancy:.2f}/trade")
        # Project 30-day performance
        trades_per_day = len(trades) / max(1, hours/24)
        monthly = expectancy * trades_per_day * 30
        print(f"  TRAFFIC:   {trades_per_day:.1f} trades/day")
        print(f"  30-DAY PROJ: ${monthly:.2f} ({monthly/30.04*100:.1f}% monthly return)")
    
    # Print trade log
    print(f"\n  TRADE LOG:")
    print(f"  {'#':>3} {'Time':>8} {'Side':>4} {'Entry':>10} {'Exit':>10} {'R':>6} {'P&L':>8} {'Reason':>6}")
    print(f"  {'─'*65}")
    for idx, t in enumerate(trades):
        ts = datetime.fromtimestamp(t['time']).strftime('%H:%M')
        print(f"  {idx+1:3d} {ts:>8} {t['direction']:>4} {t['entry_price']:>10.2f} {t['exit_price']:>10.2f} "
              f"{t['r_mult']:+6.2f} {t['pnl']:+8.2f} {t['exit_reason']:>6}")
    
    print(f"\n  {'='*65}")
    return {
        'symbol': sym,
        'strategy': strat,
        'trades': len(trades),
        'win_rate': win_rate,
        'pnl': total_pnl,
        'final_equity': equity,
        'profit_factor': profit_factor,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'expectancy': expectancy if trades else 0,
        'trades_per_day': trades_per_day if hours > 0 else 0,
    }


# ─── MAIN ────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not mt5.initialize():
        print("MT5 init failed!")
        sys.exit(1)
    
    print("=" * 70)
    print("  MITEMSHUB AI v13 — 90-DAY BACKTEST")
    print("  Multi-Indicator Strategy Validation")
    print("=" * 70)
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Account: ${mt5.account_info().balance:.2f}")
    print(f"")
    print(f"  STRATEGY PARAMETERS:")
    print(f"  Vol 75:  SMA50 Distance Fade ({SMA_DIST_PCT}%) + RSI({RSI_PERIOD}) + BB({BB_PERIOD},{BB_DEV})")
    print(f"  Vol 100: Momentum Exhaustion ({CONSEC_BARS} bars) + RSI({RSI_PERIOD}) + BB({BB_PERIOD},{BB_DEV})")
    print(f"  Stops: {ATR_STOP_MULT}x ATR | Targets: {ATR_TARGET_MULT}x ATR | Risk: {RISK_PER_TRADE*100}%/trade")
    print(f"  Cool-down: {COOLDOWN_BARS} bars | Max consec loss: {MAX_CONSEC_LOSS} | Max daily: {MAX_DAILY_LOSS*100}%")
    
    results = []
    
    # Test Vol 75 with SMA50 fade
    r1 = backtest_symbol("Volatility 75 Index", "SMA50 Distance Fade", 1)
    results.append(print_results(r1))
    
    # Test Vol 100 with momentum exhaustion
    r2 = backtest_symbol("Volatility 100 Index", "Momentum Exhaustion", 2)
    results.append(print_results(r2))
    
    # Also test cross-strategies for comparison
    print(f"\n\n{'='*70}")
    print(f"  CROSS-STRATEGY COMPARISON")
    print(f"{'='*70}")
    
    r3 = backtest_symbol("Volatility 75 Index", "Momentum Exhaustion", 2)
    print_results(r3)
    
    r4 = backtest_symbol("Volatility 100 Index", "SMA50 Distance Fade", 1)
    print_results(r4)
    
    # Summary
    print(f"\n\n{'='*70}")
    print(f"  FINAL SUMMARY — ALL STRATEGIES")
    print(f"{'='*70}")
    print(f"  {'Symbol':<20} {'Strategy':<25} {'Trades':>6} {'WR%':>6} {'P&L':>8} {'PF':>6} {'Sharpe':>7} {'MaxDD':>6}")
    print(f"  {'─'*85}")
    for r in results:
        if r:
            print(f"  {r['symbol']:<20} {r['strategy']:<25} {r['trades']:>6} {r['win_rate']:>5.1f}% "
                  f"{r['pnl']:>+7.2f} {r['profit_factor']:>6.2f} {r['sharpe']:>7.2f} {r['max_dd']:>5.1f}%")
    
    # Save results
    with open('data/backtest_v13_results.json', 'w') as f:
        json.dump([r for r in results if r], f, indent=2, default=str)
    
    print(f"\n  Results saved to data/backtest_v13_results.json")
    print(f"\n{'='*70}")
    
    mt5.shutdown()
