#!/usr/bin/env python3
"""V100 M5 BREAKOUT DEEP DIVE — Fine-tune the winning strategy"""

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

print("=" * 80)
print("  V100 M5 BREAKOUT DEEP DIVE")
print("=" * 80)

# Get M5 data
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 5000)
closes = rates['close']
highs = rates['high']
lows = rates['low']
opens = rates['open']
times = rates['time']
n = len(closes)

print(f"  M5 bars: {n} ({n/288:.0f} days)")
print(f"  Date range: {datetime.fromtimestamp(times[0]).date()} → {datetime.fromtimestamp(times[-1]).date()}")

# ATR
atr = np.zeros(n)
for i in range(14, n):
    trs = []
    for j in range(i-13, i+1):
        tr = max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
        trs.append(tr)
    atr[i] = np.mean(trs)

avg_range = np.mean(highs - lows)
print(f"  Avg M5 range: {avg_range:.4f} price | ATR(14): {atr[-1]:.4f} price")

# === 1. M5 BAR STATISTICS ===
print(f"\n{'─'*80}")
print(f"  M5 BAR STATISTICS")
print(f"{'─'*80}")
ranges = highs - lows
bodies = np.abs(closes - opens)
body_dirs = np.sign(closes - opens)

print(f"  Bullish bars: {np.sum(body_dirs > 0)} ({np.sum(body_dirs > 0)/n*100:.1f}%)")
print(f"  Bearish bars: {np.sum(body_dirs < 0)} ({np.sum(body_dirs < 0)/n*100:.1f}%)")
print(f"  Doji (no body): {np.sum(body_dirs == 0)} ({np.sum(body_dirs == 0)/n*100:.1f}%)")
print(f"\n  Range distribution:")
for pct in [10, 25, 50, 75, 90, 95]:
    val = np.percentile(ranges, pct)
    print(f"    {pct}th pctl: {val:.4f} price ({val/dpp:.0f} pts) → ${val * 25 * dpp:.2f} at 25 lots")

# How often does a breakout of N-bar range work?
print(f"\n{'─'*80}")
print(f"  BREAKOUT ANALYSIS — What happens after price breaks N-bar range?")
print(f"{'─'*80}")

for lookback in [5, 10, 15, 20, 30]:
    wins = 0
    losses = 0
    total_pnl = 0
    
    for i in range(lookback + 10, n):
        recent_high = max(highs[i-lookback:i])
        recent_low = min(lows[i-lookback:i])
        body = closes[i] - opens[i]
        
        if closes[i] > recent_high and body > 0:
            # Bullish breakout
            # Check what happened in next 1-5 bars
            max_favorable = 0
            max_adverse = 0
            for j in range(1, min(6, n-i)):
                if closes[i+j] > closes[i]:
                    max_favorable = max(max_favorable, closes[i+j] - closes[i])
                else:
                    max_adverse = max(max_adverse, closes[i] - closes[i+j])
            
            # Simple TP/SL test
            tp = 5.0  # 5 price units target
            sl = 3.0  # 3 price units stop
            if max_favorable >= tp:
                pnl = tp - spread_price
                wins += 1
            elif max_adverse >= sl:
                pnl = -sl - spread_price
                losses += 1
            else:
                # Time exit at current
                pnl = (closes[i + min(5, n-i-1)] - closes[i]) - spread_price
                if pnl > 0: wins += 1
                else: losses += 1
            total_pnl += pnl * 25 * dpp
        
        elif closes[i] < recent_low and body < 0:
            # Bearish breakout
            max_favorable = 0
            max_adverse = 0
            for j in range(1, min(6, n-i)):
                if closes[i+j] < closes[i]:
                    max_favorable = max(max_favorable, closes[i] - closes[i+j])
                else:
                    max_adverse = max(max_adverse, closes[i+j] - closes[i])
            
            tp = 5.0
            sl = 3.0
            if max_favorable >= tp:
                pnl = tp - spread_price
                wins += 1
            elif max_adverse >= sl:
                pnl = -sl - spread_price
                losses += 1
            else:
                pnl = (closes[i] - closes[i + min(5, n-i-1)]) - spread_price
                if pnl > 0: wins += 1
                else: losses += 1
            total_pnl += pnl * 25 * dpp
    
    total = wins + losses
    wr = wins / total * 100 if total > 0 else 0
    avg = total_pnl / total if total > 0 else 0
    days = n / 288
    print(f"  Lookback={lookback:>2}: {total:>4} trades ({total/days:.1f}/day) | WR={wr:.1f}% | Total=${total_pnl:.2f} | Avg=${avg:.2f}")

# === 2. OPTIMAL SL/TP SWEEP ===
print(f"\n{'─'*80}")
print(f"  SL/TP OPTIMIZATION (M5 breakout, lookback=20, 25 lots)")
print(f"{'─'*80}")

lookback = 20
best_score = -999
best_combo = None

for sl_pt in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
    for tp_pt in [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0]:
        if tp_pt <= sl_pt:
            continue
        
        wins = 0
        losses = 0
        total_pnl = 0
        
        for i in range(lookback + 10, n):
            recent_high = max(highs[i-lookback:i])
            recent_low = min(lows[i-lookback:i])
            body = closes[i] - opens[i]
            
            if closes[i] > recent_high and body > 0:
                max_fav = 0
                max_adv = 0
                for j in range(1, min(10, n-i)):
                    move = closes[i+j] - closes[i]
                    if move > 0: max_fav = max(max_fav, move)
                    else: max_adv = max(max_adv, abs(move))
                
                if max_fav >= tp_pt:
                    pnl = tp_pt - spread_price
                    wins += 1
                elif max_adv >= sl_pt:
                    pnl = -sl_pt - spread_price
                    losses += 1
                else:
                    exit_bar = min(9, n-i-1)
                    pnl = closes[i+exit_bar] - closes[i] - spread_price
                    if pnl > 0: wins += 1
                    else: losses += 1
                total_pnl += pnl * 25 * dpp
            
            elif closes[i] < recent_low and body < 0:
                max_fav = 0
                max_adv = 0
                for j in range(1, min(10, n-i)):
                    move = closes[i] - closes[i+j]
                    if move > 0: max_fav = max(max_fav, move)
                    else: max_adv = max(max_adv, abs(move))
                
                if max_fav >= tp_pt:
                    pnl = tp_pt - spread_price
                    wins += 1
                elif max_adv >= sl_pt:
                    pnl = -sl_pt - spread_price
                    losses += 1
                else:
                    exit_bar = min(9, n-i-1)
                    pnl = closes[i] - closes[i+exit_bar] - spread_price
                    if pnl > 0: wins += 1
                    else: losses += 1
                total_pnl += pnl * 25 * dpp
        
        total = wins + losses
        if total < 5: continue
        wr = wins / total * 100
        days = n / 288
        pf = (wins * (tp_pt - spread_price)) / (losses * (sl_pt + spread_price)) if losses > 0 else 999
        
        # Score: P&L adjusted for risk
        score = total_pnl / max(losses * (sl_pt + spread_price) * 25 * dpp, 1)
        
        if total_pnl > 0 and score > best_score:
            best_score = score
            best_combo = (sl_pt, tp_pt, total, wr, total_pnl, pf, total/days)
        
        if total_pnl > 0:
            print(f"  SL={sl_pt:.1f} TP={tp_pt:.1f}: {total:>3} trades ({total/days:.1f}/day) WR={wr:.1f}% P&L=${total_pnl:.2f} PF={pf:.2f}")

# === 3. WALK-FORWARD ON BEST COMBO ===
if best_combo:
    sl_pt, tp_pt, total, wr, total_pnl, pf, tpd = best_combo
    print(f"\n{'─'*80}")
    print(f"  🏆 BEST COMBO: SL={sl_pt:.1f} TP={tp_pt:.1f} — WALK-FORWARD VALIDATION")
    print(f"{'─'*80}")
    
    split = int(n * 0.6)
    
    # Train
    wins_train = 0
    losses_train = 0
    pnl_train = 0
    for i in range(lookback + 10, split):
        recent_high = max(highs[i-lookback:i])
        recent_low = min(lows[i-lookback:i])
        body = closes[i] - opens[i]
        
        if closes[i] > recent_high and body > 0:
            max_fav = max((closes[i+j]-closes[i]) for j in range(1, min(10, split-i))) if split-i > 1 else 0
            max_adv = max((closes[i]-closes[i+j]) for j in range(1, min(10, split-i))) if split-i > 1 else 0
            if max_fav >= tp_pt:
                pnl_train += (tp_pt - spread_price) * 25 * dpp; wins_train += 1
            elif max_adv >= sl_pt:
                pnl_train += (-sl_pt - spread_price) * 25 * dpp; losses_train += 1
            else:
                ex = min(9, split-i-1)
                p = closes[i+ex] - closes[i] - spread_price
                pnl_train += p * 25 * dpp
                if p > 0: wins_train += 1
                else: losses_train += 1
        elif closes[i] < recent_low and body < 0:
            max_fav = max((closes[i]-closes[i+j]) for j in range(1, min(10, split-i))) if split-i > 1 else 0
            max_adv = max((closes[i+j]-closes[i]) for j in range(1, min(10, split-i))) if split-i > 1 else 0
            if max_fav >= tp_pt:
                pnl_train += (tp_pt - spread_price) * 25 * dpp; wins_train += 1
            elif max_adv >= sl_pt:
                pnl_train += (-sl_pt - spread_price) * 25 * dpp; losses_train += 1
            else:
                ex = min(9, split-i-1)
                p = closes[i] - closes[i+ex] - spread_price
                pnl_train += p * 25 * dpp
                if p > 0: wins_train += 1
                else: losses_train += 1
    
    # Test
    wins_test = 0
    losses_test = 0
    pnl_test = 0
    for i in range(split + lookback + 10, n):
        recent_high = max(highs[i-lookback:i])
        recent_low = min(lows[i-lookback:i])
        body = closes[i] - opens[i]
        
        if closes[i] > recent_high and body > 0:
            max_fav = max((closes[i+j]-closes[i]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            max_adv = max((closes[i]-closes[i+j]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            if max_fav >= tp_pt:
                pnl_test += (tp_pt - spread_price) * 25 * dpp; wins_test += 1
            elif max_adv >= sl_pt:
                pnl_test += (-sl_pt - spread_price) * 25 * dpp; losses_test += 1
            else:
                ex = min(9, n-i-1)
                p = closes[i+ex] - closes[i] - spread_price
                pnl_test += p * 25 * dpp
                if p > 0: wins_test += 1
                else: losses_test += 1
        elif closes[i] < recent_low and body < 0:
            max_fav = max((closes[i]-closes[i+j]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            max_adv = max((closes[i+j]-closes[i]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            if max_fav >= tp_pt:
                pnl_test += (tp_pt - spread_price) * 25 * dpp; wins_test += 1
            elif max_adv >= sl_pt:
                pnl_test += (-sl_pt - spread_price) * 25 * dpp; losses_test += 1
            else:
                ex = min(9, n-i-1)
                p = closes[i] - closes[i+ex] - spread_price
                pnl_test += p * 25 * dpp
                if p > 0: wins_test += 1
                else: losses_test += 1
    
    t_train = wins_train + losses_train
    t_test = wins_test + losses_test
    wr_train = wins_train / t_train * 100 if t_train > 0 else 0
    wr_test = wins_test / t_test * 100 if t_test > 0 else 0
    days_train = split / 288
    days_test = (n - split) / 288
    
    print(f"\n  TRAINING PERIOD ({days_train:.0f} days):")
    print(f"    Trades:     {t_train} ({t_train/days_train:.1f}/day)")
    print(f"    Win Rate:   {wr_train:.1f}%")
    print(f"    P&L:        ${pnl_train:.2f}")
    print(f"    $/day:      ${pnl_train/days_train:.2f}")
    
    print(f"\n  TEST PERIOD ({days_test:.0f} days) — OUT OF SAMPLE:")
    print(f"    Trades:     {t_test} ({t_test/days_test:.1f}/day)")
    print(f"    Win Rate:   {wr_test:.1f}%")
    print(f"    P&L:        ${pnl_test:.2f}")
    print(f"    $/day:      ${pnl_test/days_test:.2f}")
    
    print(f"\n  COMBINED:")
    print(f"    Total P&L:  ${pnl_train + pnl_test:.2f}")
    print(f"    Avg WR:     {(wr_train+wr_test)/2:.1f}%")
    
    # Projection
    avg_daily = pnl_test / days_test
    print(f"\n  📊 90-DAY PROJECTION:")
    print(f"    Daily avg:  ${avg_daily:.2f}")
    print(f"    30-day:     ${avg_daily * 30:.2f}")
    print(f"    60-day:     ${avg_daily * 60:.2f}")
    print(f"    90-day:     ${avg_daily * 90:.2f}")
    print(f"    ROI (90d):  {avg_daily * 90 / equity * 100:.0f}%")
    print(f"    Final eq:   ${equity + avg_daily * 90:.2f}")

# === 4. HOURLY PERFORMANCE ===
print(f"\n{'─'*80}")
print(f"  HOURLY PERFORMANCE (M5 breakout SL={best_combo[0]:.1f} TP={best_combo[1]:.1f})")
print(f"{'─'*80}")

sl_pt = best_combo[0]
tp_pt = best_combo[1]

for hour in range(24):
    # Get M5 bars for this hour
    hour_mask = [(datetime.fromtimestamp(t).hour == hour) for t in times]
    
    wins_h = 0
    losses_h = 0
    pnl_h = 0
    
    for i in range(lookback + 10, n):
        if not hour_mask[i]:
            continue
        
        recent_high = max(highs[i-lookback:i])
        recent_low = min(lows[i-lookback:i])
        body = closes[i] - opens[i]
        
        if closes[i] > recent_high and body > 0:
            max_fav = max((closes[i+j]-closes[i]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            max_adv = max((closes[i]-closes[i+j]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            if max_fav >= tp_pt:
                pnl_h += (tp_pt - spread_price) * 25 * dpp; wins_h += 1
            elif max_adv >= sl_pt:
                pnl_h += (-sl_pt - spread_price) * 25 * dpp; losses_h += 1
        elif closes[i] < recent_low and body < 0:
            max_fav = max((closes[i]-closes[i+j]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            max_adv = max((closes[i+j]-closes[i]) for j in range(1, min(10, n-i))) if n-i > 1 else 0
            if max_fav >= tp_pt:
                pnl_h += (tp_pt - spread_price) * 25 * dpp; wins_h += 1
            elif max_adv >= sl_pt:
                pnl_h += (-sl_pt - spread_price) * 25 * dpp; losses_h += 1
    
    total_h = wins_h + losses_h
    wr_h = wins_h / total_h * 100 if total_h > 0 else 0
    print(f"  {hour:02d}:00 → {total_h:>3} trades | WR={wr_h:>5.1f}% | P&L=${pnl_h:>7.2f} {'⭐' if pnl_h > 0 and total_h > 3 else ''}")

mt5.shutdown()
print(f"\n{'='*80}")
