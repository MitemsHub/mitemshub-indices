import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

mt5.initialize()

print("="*90)
print(" STEP INDEX: COMPREHENSIVE STRATEGY SWEEP — ALL TIMEFRAMES")
print("="*90)

margin_per_lot = 7.83
pt_value = 1.0
equity = 22.75
lots = 2

for tf_name, tf, hold_max in [("M5", mt5.TIMEFRAME_M5, 48), ("M15", mt5.TIMEFRAME_M15, 32),
                                ("H1", mt5.TIMEFRAME_H1, 24), ("H4", mt5.TIMEFRAME_H4, 12)]:
    
    bars = mt5.copy_rates_from("Step Index", tf, datetime.now() - timedelta(days=90), 10000)
    if bars is None or len(bars) < 500:
        continue
    
    closes = np.array([b['close'] for b in bars])
    highs = np.array([b['high'] for b in bars])
    lows = np.array([b['low'] for b in bars])
    times_arr = np.array([b['time'] for b in bars])
    n = len(closes)
    
    print(f"\n{'='*90}")
    print(f" {tf_name} TIMEFRAME ({n} bars)")
    print(f"{'='*90}")
    
    # Indicators
    def ema_data(data, period):
        r = np.full(len(data), np.nan)
        if len(data) < period: return r
        r[period-1] = np.mean(data[:period])
        alpha = 2.0 / (period + 1)
        for i in range(period, len(data)):
            r[i] = alpha * data[i] + (1 - alpha) * r[i-1]
        return r
    
    def rsi_data(data, period=14):
        r = np.full(len(data), 50.0)
        for i in range(period, len(data)):
            d = np.diff(data[i-period:i+1])
            g = np.sum(d[d > 0])
            l = -np.sum(d[d < 0])
            r[i] = 100 if l == 0 else 100 - 100/(1+g/l)
        return r
    
    ema20 = ema_data(closes, 20)
    ema50 = ema_data(closes, 50)
    ema100 = ema_data(closes, 100)
    rsi14 = rsi_data(closes, 14)
    
    # ATR
    tr = np.maximum(highs[1:]-lows[1:], np.maximum(np.abs(highs[1:]-closes[:-1]), np.abs(lows[1:]-closes[:-1])))
    tr = np.insert(tr, 0, 0)
    atr = np.zeros(n)
    if n > 14:
        atr[14] = np.mean(tr[1:15])
        for i in range(15, n): atr[i] = (atr[i-1]*13 + tr[i])/14
    
    warmup = 101
    
    def run_strategy(name, signal_fn, sl_mult, tp_mult, max_hold):
        trades = []; wins = 0
        pos = 0; entry = 0; sl_d = 0; entry_bar = 0; entry_time = 0
        peak_eq = equity; max_dd_pct = 0; cur_eq = equity
        
        for i in range(warmup, n-1):
            if atr[i] <= 0: continue
            
            if pos != 0:
                held = i - entry_bar
                price = closes[i]
                
                if pos > 0:
                    if price <= entry - sl_d:
                        r_mult = -1; pnl = r_mult * sl_d * lots * pt_value
                        trades.append({"r": r_mult, "pnl": pnl})
                        cur_eq += pnl; pos = 0; continue
                    if price >= entry + sl_d * tp_mult:
                        r_mult = tp_mult; pnl = r_mult * sl_d * lots * pt_value
                        trades.append({"r": r_mult, "pnl": pnl})
                        cur_eq += pnl; wins += 1; pos = 0; continue
                else:
                    if price >= entry + sl_d:
                        r_mult = -1; pnl = r_mult * sl_d * lots * pt_value
                        trades.append({"r": r_mult, "pnl": pnl})
                        cur_eq += pnl; pos = 0; continue
                    if price <= entry - sl_d * tp_mult:
                        r_mult = tp_mult; pnl = r_mult * sl_d * lots * pt_value
                        trades.append({"r": r_mult, "pnl": pnl})
                        cur_eq += pnl; wins += 1; pos = 0; continue
                
                if held >= max_hold:
                    pnl_pts = (price - entry) * pos
                    r_mult = pnl_pts / sl_d if sl_d > 0 else 0
                    pnl = pnl_pts * lots * pt_value
                    trades.append({"r": r_mult, "pnl": pnl})
                    cur_eq += pnl
                    if r_mult > 0: wins += 1
                    pos = 0; continue
                
                # Breakeven at 1x ATR
                if sl_mult > 0 and atr[i] > 0:
                    be = atr[i]
                    if pos > 0 and price >= entry + be and sl_d > 0:
                        sl_d = 0  # breakeven
                    elif pos < 0 and price <= entry - be and sl_d > 0:
                        sl_d = 0
                
                continue
            
            sig = signal_fn(i)
            if sig != 0:
                pos = sig
                entry = closes[i]
                sl_d = sl_mult * atr[i]
                entry_bar = i
                entry_time = times_arr[i]
        
        # Close remaining
        if pos != 0:
            pnl_pts = (closes[-1] - entry) * pos
            r_mult = pnl_pts / sl_d if sl_d > 0 else 0
            pnl = pnl_pts * lots * pt_value
            trades.append({"r": r_mult, "pnl": pnl})
            cur_eq += pnl
            if r_mult > 0: wins += 1
        
        # Calculate stats
        nn = len(trades)
        wr = wins/nn*100 if nn > 0 else 0
        total_r = sum(t["r"] for t in trades)
        total_pnl = sum(t["pnl"] for t in trades)
        
        # Max drawdown
        running = equity; peak = equity; max_dd = 0
        for t in trades:
            running += t["pnl"]
            if running > peak: peak = running
            dd = (peak - running) / peak * 100 if peak > 0 else 0
            if dd > max_dd: max_dd = dd
        
        return nn, nn/90, wr, total_r, total_pnl, max_dd
    
    # ── STRATEGY 1: EMA Crossover ──
    def signal_ema_cross(i):
        if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]: return 1
        if ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]: return -1
        return 0
    
    # ── STRATEGY 2: Pullback to EMA20 ──
    def signal_pullback(i):
        if ema20[i] > ema50[i] and closes[i] < ema20[i] and closes[i] > ema50[i] and rsi14[i] < 45 and closes[i] > closes[i-1]:
            return 1
        if ema20[i] < ema50[i] and closes[i] > ema20[i] and closes[i] < ema50[i] and rsi14[i] > 55 and closes[i] < closes[i-1]:
            return -1
        return 0
    
    # ── STRATEGY 3: Triple EMA Trend ──
    def signal_triple_ema(i):
        if ema20[i] > ema50[i] > ema100[i] and closes[i] > ema20[i] and rsi14[i] > 52 and rsi14[i] < 72:
            return 1
        if ema20[i] < ema50[i] < ema100[i] and closes[i] < ema20[i] and rsi14[i] < 48 and rsi14[i] > 28:
            return -1
        return 0
    
    # ── STRATEGY 4: RSI + EMA Confirmation ──
    def signal_rsi_ema(i):
        if rsi14[i] < 40 and rsi14[i-1] < rsi14[i] and ema20[i] > ema50[i] and closes[i] > ema50[i]:
            return 1
        if rsi14[i] > 60 and rsi14[i-1] > rsi14[i] and ema20[i] < ema50[i] and closes[i] < ema50[i]:
            return -1
        return 0
    
    # ── STRATEGY 5: Momentum + Trend ──
    def signal_momentum(i):
        body = closes[i] - closes[i-1]
        if ema20[i] > ema50[i] and body > atr[i] * 0.3 and rsi14[i] > 50 and rsi14[i] < 75:
            return 1
        if ema20[i] < ema50[i] and body < -atr[i] * 0.3 and rsi14[i] < 50 and rsi14[i] > 25:
            return -1
        return 0
    
    # ── STRATEGY 6: Mean Reversion (Counter-trend) ──
    def signal_mean_rev(i):
        if closes[i] < ema50[i] - atr[i] * 1.5 and rsi14[i] < 30:
            return 1
        if closes[i] > ema50[i] + atr[i] * 1.5 and rsi14[i] > 70:
            return -1
        return 0
    
    strategies = [
        ("EMA Cross 20/50", signal_ema_cross, 1.5, 2.5, hold_max),
        ("Pullback EMA20+RSI", signal_pullback, 1.5, 2.5, hold_max),
        ("Triple EMA Trend", signal_triple_ema, 1.5, 2.5, hold_max),
        ("RSI+EMA Confirm", signal_rsi_ema, 1.5, 2.5, hold_max),
        ("Momentum+Trend", signal_momentum, 1.5, 2.5, hold_max),
        ("Mean Reversion", signal_mean_rev, 2.0, 2.0, hold_max),
    ]
    
    print(f"\n  {'Strategy':<25} {'Trades':<7} {'T/Day':<7} {'WR%':<7} {'TotalR':<9} {'P&L':<10} {'MaxDD%':<7}")
    print(f"  {'-'*72}")
    
    best_pnl = -9999; best_name = ""
    for name, sig_fn, sl, tp, hold in strategies:
        nn, tday, wr, tr, pnl, dd = run_strategy(name, sig_fn, sl, tp, hold)
        marker = ""
        if pnl > best_pnl:
            best_pnl = pnl; best_name = name
        print(f"  {name:<25} {nn:<7} {tday:<7.1f} {wr:<7.1f} {tr:<+9.2f} ${pnl:<+9.2f} {dd:<7.1f}%")
    
    print(f"\n  >>> BEST: {best_name} (${best_pnl:+.2f})")

# ═══════════════════════════════════════════════════════════════
# ALSO TEST V100 ON M15 FOR COMPARISON
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*90}")
print(f" V100 M15 COMPARISON (for reference)")
print(f"{'='*90}")

v100_bars = mt5.copy_rates_from("Volatility 100 Index", mt5.TIMEFRAME_M15, datetime.now() - timedelta(days=90), 9000)
if v100_bars is not None:
    c = np.array([b['close'] for b in v100_bars])
    h = np.array([b['high'] for b in v100_bars])
    l = np.array([b['low'] for b in v100_bars])
    n = len(c)
    
    e20 = ema_data(c, 20); e50 = ema_data(c, 50)
    rsi = rsi_data(c, 14)
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    tr = np.insert(tr, 0, 0)
    atr_v = np.zeros(n)
    if n > 14:
        atr_v[14] = np.mean(tr[1:15])
        for i in range(15, n): atr_v[i] = (atr_v[i-1]*13 + tr[i])/14
    
    v100_pt = 0.01; v100_lots = 25; v100_margin = 0.62
    
    # EMA Cross on V100
    trades = []; wins = 0; pos = 0; entry = 0; sl_d = 0; entry_bar = 0
    for i in range(101, n-1):
        if atr_v[i] <= 0: continue
        if pos != 0:
            held = i - entry_bar
            p = c[i]
            if pos > 0:
                if p <= entry - sl_d: trades.append(-1); pos = 0; continue
                if p >= entry + sl_d * 2.5: trades.append(2.5); wins += 1; pos = 0; continue
            else:
                if p >= entry + sl_d: trades.append(-1); pos = 0; continue
                if p <= entry - sl_d * 2.5: trades.append(2.5); wins += 1; pos = 0; continue
            if held >= 32:
                r = (p - entry) * pos / sl_d if sl_d > 0 else 0
                trades.append(r)
                if r > 0: wins += 1
                pos = 0; continue
            continue
        if e20[i] > e50[i] and e20[i-1] <= e50[i-1]: pos = 1; entry = c[i]; sl_d = atr_v[i]*1.5; entry_bar = i
        elif e20[i] < e50[i] and e20[i-1] >= e50[i-1]: pos = -1; entry = c[i]; sl_d = atr_v[i]*1.5; entry_bar = i
    
    nn = len(trades); wr = wins/nn*100 if nn > 0 else 0; tr = sum(trades)
    # PnL for V100
    pnl = sum(r * sl_d_avg * v100_lots * v100_pt for r in trades) if trades else 0
    print(f"  V100 EMA Cross M15: {nn} trades | {nn/90:.1f}/day | WR: {wr:.1f}% | R: {tr:+.2f}")
    print(f"  Note: V100 at $0.01/pt vs Step Index at $1.00/pt = 100x less per point")

mt5.shutdown()
