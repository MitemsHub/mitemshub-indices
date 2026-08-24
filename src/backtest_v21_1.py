#!/usr/bin/env python3
"""v21.1 BACKTEST — Clean, no globals"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime

mt5.initialize()
sym = "Volatility 100 Index"
mt5.symbol_select(sym, True)
info = mt5.symbol_info(sym)
dpp = info.trade_tick_value / info.trade_tick_size * info.point
acc = mt5.account_info()
equity = acc.equity
spread = info.spread * info.point

print("=" * 70)
print("  v21.1 BACKTEST — V100 H1")
print("=" * 70)

# Data
rates_h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2000)
c = rates_h1['close']; h = rates_h1['high']; l = rates_h1['low']; o = rates_h1['open']
times = rates_h1['time']
n = len(c)

rates_h4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 500)
c4 = rates_h4['close']; t4 = rates_h4['time']

def ema_arr(data, period):
    r = np.zeros_like(data, dtype=float); r[0] = data[0]; k = 2.0/(period+1)
    for i in range(1, len(data)): r[i] = data[i]*k + r[i-1]*(1-k)
    return r

def rsi_arr(data, period=14):
    r = np.zeros(len(data))
    for i in range(period, len(data)):
        d = np.diff(data[i-period:i+1])
        g = np.sum(np.maximum(d, 0)); lo = np.sum(np.abs(np.minimum(d, 0)))
        r[i] = 100 if lo == 0 else 100 - 100/(1+g/lo)
    return r

def atr_arr(highs, lows, closes, period=14):
    a = np.zeros(len(closes))
    for i in range(period, len(closes)):
        trs = [max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1])) for j in range(i-period+1, i+1)]
        a[i] = np.mean(trs)
    return a

# Indicators
e20 = ema_arr(c, 20); e50 = ema_arr(c, 50); e100 = ema_arr(c, 100)
rs = rsi_arr(c, 14); at = atr_arr(h, l, c, 14)
e20_4 = ema_arr(c4, 20); e50_4 = ema_arr(c4, 50); e100_4 = ema_arr(c4, 100)

# BB
bb_mid = np.zeros(n); bb_up = np.zeros(n); bb_lo = np.zeros(n)
for i in range(20, n):
    bb_mid[i] = np.mean(c[i-20:i]); std = np.std(c[i-20:i])
    bb_up[i] = bb_mid[i] + 2*std; bb_lo[i] = bb_mid[i] - 2*std

def get_regime(idx):
    t = times[idx]; hi = np.searchsorted(t4, t, side='right')-1
    hi = max(0, min(hi, len(c4)-1))
    if e20_4[hi]>e50_4[hi]>e100_4[hi]: return 1
    if e20_4[hi]<e50_4[hi]<e100_4[hi]: return -1
    return 0

def run_backtest(risk_pct, lots_fixed, start, end):
    """Run backtest for given params and period"""
    trades = []; open_pos = False; entry_p=0; entry_d=0; sl_p=0; tp_p=0
    bh=0; cd=0; cl=0; paused=False; td=0; ld=0; lots=1.0
    ah = np.zeros(150); ahc = 0

    for i in range(max(start, 250), end):
        bd = i//24
        if bd != ld: ld=bd; td=0; paused=False
        if cd > 0: cd -= 1
        if paused: continue

        if ahc < 150: ah[ahc]=at[i]; ahc+=1

        regime = get_regime(i)
        if ahc >= 40:
            pct = sum(1 for j in range(max(0,ahc-120), ahc) if at[i]>ah[j])/min(120,ahc)*100
            if pct > 90 or pct < 8: regime = -99

        if open_pos:
            bh += 1
            if entry_d > 0:
                if l[i] <= sl_p:
                    trades.append((sl_p - entry_p - spread) * lots * dpp)
                    open_pos=False; cd=3; cl+=1; continue
                if h[i] >= tp_p:
                    trades.append((tp_p - entry_p - spread) * lots * dpp)
                    open_pos=False; cl=0; continue
            else:
                if h[i] >= sl_p:
                    trades.append((entry_p - sl_p - spread) * lots * dpp)
                    open_pos=False; cd=3; cl+=1; continue
                if l[i] <= tp_p:
                    trades.append((entry_p - tp_p - spread) * lots * dpp)
                    open_pos=False; cl=0; continue
            if bh >= 14:
                pnl = ((c[i]-entry_p) if entry_d>0 else (entry_p-c[i]) - spread) * lots * dpp
                trades.append(pnl); open_pos=False
            continue

        if td >= 4: continue

        price = c[i]; body = price - o[i]; rng = h[i]-l[i]; prev = c[i-1] if i>0 else price
        if rng <= 0: continue

        # === STRATEGIES ===
        dirs = [0,0,0,0]; sc = [0.0,0.0,0.0,0.0]

        # Pullback
        if regime in [1,-1]:
            d = 1 if regime==1 else -1
            pb = abs(price - e20[i])
            if 0.30*at[i] <= pb <= 2.20*at[i]:
                ok = True
                if d>0 and (rs[i]>65 or body<-0.1*at[i]): ok=False
                if d<0 and (rs[i]<35 or body>0.1*at[i]): ok=False
                if d>0 and e20[i]<=e50[i]: ok=False
                if d<0 and e20[i]>=e50[i]: ok=False
                if ok: dirs[0]=d; sc[0]=4.0

        # Breakout
        if regime != -99 and i >= 14:
            bars = 12
            hh = max(h[i-j] for j in range(bars)); ll = min(l[i-j] for j in range(bars))
            buf = 0.10 * at[i]
            bd_dir = 1 if regime in [1,0] else -1
            if bd_dir>0 and price>hh+buf and body>0: dirs[1]=1; sc[1]=3.5
            if bd_dir<0 and price<ll-buf and body<0: dirs[1]=-1; sc[1]=3.5

        # Momentum
        ratio = abs(body)/rng
        if ratio >= 0.55 and ratio > 0.45:
            dirs[2] = 1 if body>0 else -1; sc[2]=3.0

        # Mean Revert
        if regime == 0:
            if prev <= bb_lo[i] and price > bb_lo[i] and rs[i] < 32: dirs[3]=1; sc[3]=3.8
            if prev >= bb_up[i] and price < bb_up[i] and rs[i] > 68: dirs[3]=-1; sc[3]=3.8

        bs=0; ss=0; bc=0; sc2=0
        for j in range(4):
            if dirs[j]>0: bs+=int(sc[j]); bc+=1
            if dirs[j]<0: ss+=int(sc[j]); sc2+=1
        if regime==1: bs+=2
        if regime==-1: ss+=2

        fd=0
        if bs>=5 and bs>ss and bc>=2: fd=1
        elif ss>=5 and ss>bs and sc2>=2: fd=-1
        if fd==0: continue

        # SL/TP
        sd = 1.7 * at[i]
        if fd>0:
            lo = min(l[max(0,i-j)] for j in range(min(6,i)))
            sd = max(sd, price-(lo-0.15*at[i]))
        else:
            hi2 = max(h[max(0,i-j)] for j in range(min(6,i)))
            sd = max(sd, (hi2+0.15*at[i])-price)
        if sd > price*0.03: sd = price*0.03
        if sd < at[i]*0.5: sd = at[i]*0.5

        if fd>0: sl_p=price-sd; tp_p=price+2.5*sd
        else: sl_p=price+sd; tp_p=price-2.5*sd

        # Volume
        if lots_fixed: lots = lots_fixed
        else:
            rm = equity * risk_pct
            lpl = (sd/info.trade_tick_size)*info.trade_tick_value
            if lpl <= 0: continue
            lots = rm/lpl
            lots = max(info.volume_min, min(lots, info.volume_max))
            lots = round(lots, 2)

        entry_p=price; entry_d=fd; open_pos=True; bh=0; td+=1

    # Close remaining
    if open_pos:
        ep = c[min(end-1, n-1)]
        trades.append(((ep-entry_p) if entry_d>0 else (entry_p-ep) - spread)*lots*dpp)

    if not trades: return None

    p = np.array(trades); w = p[p>0]; lo2 = p[p<=0]
    return {
        'trades': len(p), 'wr': len(w)/len(p)*100, 'total': np.sum(p),
        'pf': np.sum(w)/abs(np.sum(lo2)) if len(lo2)>0 and np.sum(lo2)!=0 else 999,
        'max_dd': np.min(p), 'lots': lots, 't_day': len(p)/((end-max(start,250))/24),
    }

# === MAIN RESULTS ===
print(f"\n  {'Risk':>6s} {'Lots':>8s} {'#':>4s} {'T/D':>5s} {'WR%':>6s} {'$P&L':>9s} {'ROI%':>7s} {'PF':>5s}")
print(f"  {'─'*6} {'─'*8} {'─'*4} {'─'*5} {'─'*6} {'─'*9} {'─'*7} {'─'*5}")

all_r = []
for rp in [0.004, 0.01, 0.02]:
    for lf in [None, 5, 10, 15, 20, 25]:
        r = run_backtest(rp, lf, 0, n)
        if r:
            r['risk'] = rp; all_r.append(r)
            print(f"  {rp*100:>5.1f}% {r['lots']:>8} {r['trades']:>4d} {r['t_day']:>5.1f} {r['wr']:>5.1f}% ${r['total']:>8.2f} {r['total']/equity*100:>6.1f}% {r['pf']:>5.2f}")

# Best
best = max(all_r, key=lambda x: x['total'])
print(f"\n{'─'*70}")
print(f"  BEST: Risk={best['risk']*100:.1f}% | Lots={best['lots']} | WR={best['wr']:.1f}% | Total=${best['total']:.2f}")

# Walk-forward
print(f"\n{'─'*70}")
print(f"  WALK-FORWARD VALIDATION (60/40 split)")
print(f"{'─'*70}")

split = int(n * 0.6)
train = run_backtest(best['risk'], best['lots'] if isinstance(best['lots'], (int,float)) else None, 0, split)
test = run_backtest(best['risk'], best['lots'] if isinstance(best['lots'], (int,float)) else None, split, n)

if train:
    print(f"  TRAIN (60%): {train['trades']} trades ({train['t_day']:.1f}/day) | WR={train['wr']:.1f}% | ${train['total']:.2f} | PF={train['pf']:.2f}")
if test:
    print(f"  TEST  (40%): {test['trades']} trades ({test['t_day']:.1f}/day) | WR={test['wr']:.1f}% | ${test['total']:.2f} | PF={test['pf']:.2f}")

if train and test:
    days_test = (n - split) / 24
    daily = test['total'] / days_test
    print(f"\n  90-DAY PROJECTION (from test period):")
    print(f"    Daily avg:  ${daily:.2f}")
    print(f"    30-day:     ${daily*30:.2f}")
    print(f"    90-day:     ${daily*90:.2f}")
    print(f"    ROI (90d):  {daily*90/equity*100:.0f}%")

mt5.shutdown()
print(f"\n{'='*70}")
