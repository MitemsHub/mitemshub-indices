import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

mt5.initialize()

print("="*90)
print(" STEP INDEX: STRATEGY SWEEP (FIXED PnL) — ALL TIMEFRAMES")
print("="*90)

margin_per_lot = 7.83
pt_value = 1.0
equity = 22.75
lots = 2

for tf_name, tf, hold_max in [("M5", mt5.TIMEFRAME_M5, 48), ("M15", mt5.TIMEFRAME_M15, 32),
                                ("H1", mt5.TIMEFRAME_H1, 24), ("H4", mt5.TIMEFRAME_H4, 12)]:
    
    bars = mt5.copy_rates_from("Step Index", tf, datetime.now() - timedelta(days=90), 10000)
    if bars is None or len(bars) < 500: continue
    
    closes = np.array([b['close'] for b in bars])
    highs = np.array([b['high'] for b in bars])
    lows = np.array([b['low'] for b in bars])
    n = len(closes)
    
    print(f"\n{'='*90}")
    print(f" {tf_name} TIMEFRAME ({n} bars)")
    print(f"{'='*90}")
    
    def ema_data(data, period):
        r = np.full(len(data), np.nan)
        if len(data) < period: return r
        r[period-1] = np.mean(data[:period])
        alpha = 2.0 / (period + 1)
        for i in range(period, len(data)): r[i] = alpha * data[i] + (1-alpha) * r[i-1]
        return r
    
    def rsi_data(data, period=14):
        r = np.full(len(data), 50.0)
        for i in range(period, len(data)):
            d = np.diff(data[i-period:i+1])
            g = np.sum(d[d > 0]); l = -np.sum(d[d < 0])
            r[i] = 100 if l == 0 else 100 - 100/(1+g/l)
        return r
    
    ema20 = ema_data(closes, 20)
    ema50 = ema_data(closes, 50)
    ema100 = ema_data(closes, 100)
    rsi14 = rsi_data(closes, 14)
    
    tr = np.maximum(highs[1:]-lows[1:], np.maximum(np.abs(highs[1:]-closes[:-1]), np.abs(lows[1:]-closes[:-1])))
    tr = np.insert(tr, 0, 0)
    atr = np.zeros(n)
    if n > 14:
        atr[14] = np.mean(tr[1:15])
        for i in range(15, n): atr[i] = (atr[i-1]*13 + tr[i])/14
    
    warmup = 101
    
    def run_strategy(name, signal_fn, sl_mult, tp_mult, max_hold):
        trades = []; wins = 0
        pos = 0; entry = 0; orig_sl = 0; entry_bar = 0
        cur_eq = equity; peak_eq = equity; max_dd = 0
        
        for i in range(warmup, n-1):
            if atr[i] <= 0: continue
            
            if pos != 0:
                held = i - entry_bar
                p = closes[i]
                
                hit_sl = hit_tp = hit_time = False
                
                if pos > 0:
                    if p <= entry - orig_sl: hit_sl = True
                    elif p >= entry + orig_sl * tp_mult: hit_tp = True
                else:
                    if p >= entry + orig_sl: hit_sl = True
                    elif p <= entry - orig_sl * tp_mult: hit_tp = True
                
                if held >= max_hold: hit_time = True
                
                if hit_sl or hit_tp or hit_time:
                    price_pts = (p - entry) * pos
                    r_mult = price_pts / orig_sl if orig_sl > 0 else 0
                    if hit_tp: r_mult = tp_mult
                    elif hit_sl: r_mult = -1.0
                    pnl = price_pts * lots * pt_value
                    
                    trades.append({"r": r_mult, "pnl": pnl, "reason": "TP" if hit_tp else ("SL" if hit_sl else "TIME")})
                    cur_eq += pnl
                    if r_mult > 0: wins += 1
                    pos = 0; continue
                continue
            
            sig = signal_fn(i)
            if sig != 0:
                pos = sig; entry = closes[i]
                orig_sl = sl_mult * atr[i]
                entry_bar = i
        
        # Close remaining
        if pos != 0:
            p = closes[-1]
            price_pts = (p - entry) * pos
            r_mult = price_pts / orig_sl if orig_sl > 0 else 0
            pnl = price_pts * lots * pt_value
            trades.append({"r": r_mult, "pnl": pnl, "reason": "FINAL"})
            cur_eq += pnl
            if r_mult > 0: wins += 1
        
        nn = len(trades)
        wr = wins/nn*100 if nn > 0 else 0
        total_r = sum(t["r"] for t in trades)
        total_pnl = sum(t["pnl"] for t in trades)
        
        # Max DD
        run_eq = equity; pk = equity; mdd = 0
        for t in trades:
            run_eq += t["pnl"]
            if run_eq > pk: pk = run_eq
            dd = (pk - run_eq) / pk * 100 if pk > 0 else 0
            if dd > mdd: mdd = dd
        
        # Exit breakdown
        by_reason = {}
        for t in trades:
            r = t["reason"]
            if r not in by_reason: by_reason[r] = {"c": 0, "w": 0, "pnl": 0}
            by_reason[r]["c"] += 1
            by_reason[r]["pnl"] += t["pnl"]
            if t["r"] > 0: by_reason[r]["w"] += 1
        
        return nn, nn/90, wr, total_r, total_pnl, mdd, by_reason
    
    # ── STRATEGIES ──
    def sig_ema_cross(i):
        if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]: return 1
        if ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]: return -1
        return 0
    
    def sig_pullback(i):
        if ema20[i] > ema50[i] and closes[i] < ema20[i] and closes[i] > ema50[i] and rsi14[i] < 45 and closes[i] > closes[i-1]:
            return 1
        if ema20[i] < ema50[i] and closes[i] > ema20[i] and closes[i] < ema50[i] and rsi14[i] > 55 and closes[i] < closes[i-1]:
            return -1
        return 0
    
    def sig_triple(i):
        if ema20[i] > ema50[i] > ema100[i] and closes[i] > ema20[i] and 52 < rsi14[i] < 72:
            return 1
        if ema20[i] < ema50[i] < ema100[i] and closes[i] < ema20[i] and 28 < rsi14[i] < 48:
            return -1
        return 0
    
    def sig_rsi_ema(i):
        if rsi14[i] < 40 and rsi14[i] > rsi14[i-1] and ema20[i] > ema50[i] and closes[i] > ema50[i]:
            return 1
        if rsi14[i] > 60 and rsi14[i] < rsi14[i-1] and ema20[i] < ema50[i] and closes[i] < ema50[i]:
            return -1
        return 0
    
    def sig_momentum(i):
        body = closes[i] - closes[i-1]
        if ema20[i] > ema50[i] and body > atr[i]*0.3 and 50 < rsi14[i] < 75:
            return 1
        if ema20[i] < ema50[i] and body < -atr[i]*0.3 and 25 < rsi14[i] < 50:
            return -1
        return 0
    
    def sig_mean_rev(i):
        if closes[i] < ema50[i] - atr[i]*1.5 and rsi14[i] < 30: return 1
        if closes[i] > ema50[i] + atr[i]*1.5 and rsi14[i] > 70: return -1
        return 0
    
    strategies = [
        ("EMA Cross 20/50", sig_ema_cross, 1.5, 2.5, hold_max),
        ("Pullback EMA20+RSI", sig_pullback, 1.5, 2.5, hold_max),
        ("Triple EMA Trend", sig_triple, 1.5, 2.5, hold_max),
        ("RSI+EMA Confirm", sig_rsi_ema, 1.5, 2.5, hold_max),
        ("Momentum+Trend", sig_momentum, 1.5, 2.5, hold_max),
        ("Mean Reversion", sig_mean_rev, 2.0, 2.0, hold_max),
    ]
    
    print(f"\n  {'Strategy':<25} {'#':<5} {'T/D':<5} {'WR%':<6} {'R':<8} {'P&L':<10} {'DD%':<7} {'Exits'}")
    print(f"  {'-'*85}")
    
    best_pnl = -9999; best_name = ""; best_data = None
    for name, sig_fn, sl, tp, hold in strategies:
        nn, tday, wr, tr, pnl, dd, exits = run_strategy(name, sig_fn, sl, tp, hold)
        exit_str = " ".join(f"{k}:{v['c']}" for k, v in sorted(exits.items()))
        marker = ""
        if pnl > best_pnl:
            best_pnl = pnl; best_name = name; best_data = (nn, tday, wr, tr, pnl, dd)
        print(f"  {name:<25} {nn:<5} {tday:<5.1f} {wr:<6.1f} {tr:<+8.2f} ${pnl:<+9.2f} {dd:<6.1f}% {exit_str}")
    
    if best_data:
        print(f"\n  >>> BEST: {best_name}")
        print(f"      {best_data[0]} trades | {best_data[1]:.1f}/day | WR: {best_data[2]:.1f}% | R: {best_data[3]:+.2f} | P&L: ${best_data[4]:+.2f} | DD: {best_data[5]:.1f}%")

mt5.shutdown()
