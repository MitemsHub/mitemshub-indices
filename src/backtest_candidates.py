import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

mt5.initialize()

print("="*100)
print("PHASE 4: BACKTEST TOP CANDIDATES — SAME STRATEGY, DIFFERENT INSTRUMENTS")
print("Strategy: EMA 20/50 Crossover on M15, SL=1.5xATR, TP=2.5xSL, Max Hold=32 bars")
print("="*100)

equity = 22.75

# Top candidates to test
candidates = [
    ("Volatility 50 Index", 0.0001, 0.0001, 398, 190, 0.04),
    ("Volatility 25 Index", 0.001, 0.001, 23, 253, 0.67),
    ("Volatility 100 Index", 0.01, 0.01, 25, 26, 0.62),
    ("Step Index", 0.1, 1.0, 2, 1, 7.83),
    ("Volatility 10 Index", 0.001, 0.001, 16, 164, 0.96),
]

def calc_ema(data, period):
    ema = np.full(len(data), np.nan)
    if len(data) < period: return ema
    ema[period-1] = np.mean(data[:period])
    multiplier = 2.0 / (period + 1)
    for i in range(period, len(data)):
        ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
    return ema

def calc_rsi(data, period=14):
    rsi = np.full(len(data), 50.0)
    for i in range(period, len(data)):
        deltas = np.diff(data[i-period:i+1])
        gains = np.sum(deltas[deltas > 0])
        losses = -np.sum(deltas[deltas < 0])
        if losses == 0: rsi[i] = 100
        else: rsi[i] = 100 - 100 / (1 + gains / losses)
    return rsi

for sym_name, point, dollar_per_point, max_lots, spread_pts, margin_per_lot in candidates:
    print(f"\n{'='*80}")
    print(f"  TESTING: {sym_name}")
    print(f"  $/pt/lot: ${dollar_per_point} | Lots: {max_lots} | Spread: {spread_pts} pts | Margin: ${margin_per_lot}")
    print(f"{'='*80}")
    
    # Get 90 days of M15 data
    bars = mt5.copy_rates_from(sym_name, mt5.TIMEFRAME_M15, datetime.now() - timedelta(days=90), 9000)
    if bars is None or len(bars) < 500:
        print(f"  INSUFFICIENT DATA — skipping")
        continue
    
    closes = np.array([b['close'] for b in bars])
    highs = np.array([b['high'] for b in bars])
    lows = np.array([b['low'] for b in bars])
    times_arr = np.array([b['time'] for b in bars])
    n = len(closes)
    
    # Indicators
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema100 = calc_ema(closes, 100)
    rsi14 = calc_rsi(closes, 14)
    
    tr = np.maximum(highs[1:] - lows[1:], 
         np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    tr = np.insert(tr, 0, 0)
    atr = np.zeros(n)
    if n > 14:
        atr[14] = np.mean(tr[1:15])
        for i in range(15, n):
            atr[i] = (atr[i-1] * 13 + tr[i]) / 14
    
    # ── STRATEGY 1: Simple EMA Crossover ──
    trades1 = []; wins1 = 0; pos = 0; entry = 0; sl_dist = 0; entry_bar = 0
    for i in range(101, n-1):
        if atr[i] <= 0: continue
        if pos != 0:
            held = i - entry_bar
            p = closes[i]
            if pos > 0:
                if p <= entry - sl_dist:
                    trades1.append(-1.0); pos = 0; continue
                if p >= entry + sl_dist * 2.5:
                    trades1.append(2.5); wins1 += 1; pos = 0; continue
            else:
                if p >= entry + sl_dist:
                    trades1.append(-1.0); pos = 0; continue
                if p <= entry - sl_dist * 2.5:
                    trades1.append(2.5); wins1 += 1; pos = 0; continue
            if held >= 32:
                r = (p - entry) * pos / sl_dist if sl_dist > 0 else 0
                trades1.append(r)
                if r > 0: wins1 += 1
                pos = 0; continue
            continue
        
        if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]:
            pos = 1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
        elif ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]:
            pos = -1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
    
    n1 = len(trades1)
    wr1 = wins1/n1*100 if n1 > 0 else 0
    total_r1 = sum(trades1)
    
    # ── STRATEGY 2: EMA + RSI Filter ──
    trades2 = []; wins2 = 0; pos = 0; entry = 0; sl_dist = 0; entry_bar = 0
    for i in range(101, n-1):
        if atr[i] <= 0: continue
        if pos != 0:
            held = i - entry_bar
            p = closes[i]
            if pos > 0:
                if p <= entry - sl_dist:
                    trades2.append(-1.0); pos = 0; continue
                if p >= entry + sl_dist * 2.5:
                    trades2.append(2.5); wins2 += 1; pos = 0; continue
            else:
                if p >= entry + sl_dist:
                    trades2.append(-1.0); pos = 0; continue
                if p <= entry - sl_dist * 2.5:
                    trades2.append(2.5); wins2 += 1; pos = 0; continue
            if held >= 32:
                r = (p - entry) * pos / sl_dist if sl_dist > 0 else 0
                trades2.append(r)
                if r > 0: wins2 += 1
                pos = 0; continue
            continue
        
        # Buy: EMA cross up + RSI not overbought + price above EMA50
        if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1] and rsi14[i] < 70 and closes[i] > ema50[i]:
            pos = 1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
        # Sell: EMA cross down + RSI not oversold + price below EMA50
        elif ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1] and rsi14[i] > 30 and closes[i] < ema50[i]:
            pos = -1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
    
    n2 = len(trades2)
    wr2 = wins2/n2*100 if n2 > 0 else 0
    total_r2 = sum(trades2)
    
    # ── STRATEGY 3: Pullback in Trend ──
    trades3 = []; wins3 = 0; pos = 0; entry = 0; sl_dist = 0; entry_bar = 0
    for i in range(101, n-1):
        if atr[i] <= 0: continue
        if pos != 0:
            held = i - entry_bar
            p = closes[i]
            if pos > 0:
                if p <= entry - sl_dist:
                    trades3.append(-1.0); pos = 0; continue
                if p >= entry + sl_dist * 2.5:
                    trades3.append(2.5); wins3 += 1; pos = 0; continue
            else:
                if p >= entry + sl_dist:
                    trades3.append(-1.0); pos = 0; continue
                if p <= entry - sl_dist * 2.5:
                    trades3.append(2.5); wins3 += 1; pos = 0; continue
            if held >= 32:
                r = (p - entry) * pos / sl_dist if sl_dist > 0 else 0
                trades3.append(r)
                if r > 0: wins3 += 1
                pos = 0; continue
            continue
        
        # Buy pullback: uptrend + price dips to EMA20 + RSI < 50 + bullish candle
        if (ema20[i] > ema50[i] and closes[i] < ema20[i] and closes[i] > ema50[i] 
            and rsi14[i] < 50 and closes[i] > closes[i-1]):
            pos = 1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
        # Sell rally
        elif (ema20[i] < ema50[i] and closes[i] > ema20[i] and closes[i] < ema50[i] 
              and rsi14[i] > 50 and closes[i] < closes[i-1]):
            pos = -1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
    
    n3 = len(trades3)
    wr3 = wins3/n3*100 if n3 > 0 else 0
    total_r3 = sum(trades3)
    
    # Calculate dollar P&L for each strategy
    def calc_pnl(trades_list, lots, dollar_per_point, avg_sl_pts):
        pnl = 0
        for r in trades_list:
            pts = r * avg_sl_pts
            pnl += pts * lots * dollar_per_point
        return pnl
    
    # Estimate average SL in points
    avg_atr_pts = np.mean(atr[100:]) / point if point > 0 else 0
    avg_sl_pts = avg_atr_pts * 1.5
    
    pnl1 = calc_pnl(trades1, max_lots, dollar_per_point, avg_sl_pts)
    pnl2 = calc_pnl(trades2, max_lots, dollar_per_point, avg_sl_pts)
    pnl3 = calc_pnl(trades3, max_lots, dollar_per_point, avg_sl_pts)
    
    print(f"\n  Avg ATR: {avg_atr_pts:.1f} pts | Avg SL: {avg_sl_pts:.1f} pts")
    print(f"\n  {'Strategy':<25} {'Trades':<8} {'T/Day':<7} {'WR%':<7} {'TotalR':<9} {'P&L':<12}")
    print(f"  {'-'*68}")
    print(f"  {'EMA Crossover':<25} {n1:<8} {n1/90:<7.1f} {wr1:<7.1f} {total_r1:<+9.2f} ${pnl1:<+11.2f}")
    print(f"  {'EMA + RSI Filter':<25} {n2:<8} {n2/90:<7.1f} {wr2:<7.1f} {total_r2:<+9.2f} ${pnl2:<+11.2f}")
    print(f"  {'Pullback in Trend':<25} {n3:<8} {n3/90:<7.1f} {wr3:<7.1f} {total_r3:<+9.2f} ${pnl3:<+11.2f}")

print(f"\n{'='*100}")
print("SUMMARY: WHICH INSTRUMENT + STRATEGY COMBINATION IS BEST?")
print(f"{'='*100}")

mt5.shutdown()
