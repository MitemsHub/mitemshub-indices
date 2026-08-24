#!/usr/bin/env python3
"""v21.1 BACKTEST on M5 — test different thresholds"""

import MetaTrader5 as mt5
import numpy as np

mt5.initialize()
sym = "Volatility 100 Index"
mt5.symbol_select(sym, True)
info = mt5.symbol_info(sym)
dpp = info.trade_tick_value / info.trade_tick_size * info.point
equity = mt5.account_info().equity
spread = info.spread * info.point

print("=" * 70)
print("  v21.1 BACKTEST — V100 M5")
print("=" * 70)

# M5 data
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 5000)
c = rates['close']; hi = rates['high']; lo = rates['low']; o = rates['open']; tm = rates['time']
n = len(c)

# H1 for regime (M5 -> H1)
rates_h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2000)
c1 = rates_h1['close']; t1 = rates_h1['time']
e20_1 = np.zeros(len(c1)); e50_1 = np.zeros(len(c1)); e100_1 = np.zeros(len(c1))

def ema(data, period):
    r = np.zeros_like(data, dtype=float); r[0]=data[0]; k=2.0/(period+1)
    for i in range(1,len(data)): r[i]=data[i]*k+r[i-1]*(1-k)
    return r

e20_1 = ema(c1, 20); e50_1 = ema(c1, 50); e100_1 = ema(c1, 100)

# M5 indicators
e20 = ema(c, 20); e50 = ema(c, 50); e100 = ema(c, 100)
rs = np.zeros(n)
for i in range(14, n):
    d = np.diff(c[i-14:i+1]); g = np.sum(np.maximum(d,0)); lo2 = np.sum(np.abs(np.minimum(d,0)))
    rs[i] = 100 if lo2==0 else 100-100/(1+g/lo2)

at = np.zeros(n)
for i in range(14, n):
    trs = [max(hi[j]-lo[j], abs(hi[j]-c[j-1]), abs(lo[j]-c[j-1])) for j in range(i-13, i+1)]
    at[i] = np.mean(trs)

bb_up = np.zeros(n); bb_lo = np.zeros(n)
for i in range(20, n):
    m = np.mean(c[i-20:i]); s = np.std(c[i-20:i])
    bb_up[i] = m+2*s; bb_lo[i] = m-2*s

def get_regime(idx):
    t = tm[idx]; hi2 = np.searchsorted(t1, t, side='right')-1
    hi2 = max(0, min(hi2, len(c1)-1))
    if e20_1[hi2]>e50_1[hi2]>e100_1[hi2]: return 1
    if e20_1[hi2]<e50_1[hi2]<e100_1[hi2]: return -1
    return 0

def run_test(min_score, require_2, risk_pct, lots_fixed, start, end):
    trades=[]; op=False; ep=0; ed=0; sld=0; tpd=0
    bh=0; cd=0; cl=0; paused=False; td=0; ld=0; lots=1.0
    ah=np.zeros(150); ahc=0; tecs=0; tes=0; tss=0

    for i in range(max(start, 250), end):
        bd = i//288  # M5 bars per day
        if bd!=ld: ld=bd; td=0; paused=False
        if cd>0: cd-=1
        if paused: continue
        if ahc<150: ah[ahc]=at[i]; ahc+=1

        regime = get_regime(i)
        if ahc>=40:
            pct = sum(1 for j in range(max(0,ahc-120),ahc) if at[i]>ah[j])/min(120,ahc)*100
            if pct>90 or pct<8: regime=-99

        if op:
            bh+=1
            if ed>0:
                if lo[i]<=sld: trades.append((sld-ep-spread)*lots*dpp); op=False; cd=3; cl+=1; tss+=1; continue
                if hi[i]>=tpd: trades.append((tpd-ep-spread)*lots*dpp); op=False; cl=0; tecs+=1; continue
            else:
                if hi[i]>=sld: trades.append((ep-sld-spread)*lots*dpp); op=False; cd=3; cl+=1; tss+=1; continue
                if lo[i]<=tpd: trades.append((ep-tpd-spread)*lots*dpp); op=False; cl=0; tecs+=1; continue
            if bh>=28:
                pnl = ((c[i]-ep) if ed>0 else (ep-c[i])-spread)*lots*dpp
                trades.append(pnl); op=False; tes+=1
            continue

        if td>=4: continue

        price=c[i]; body=price-o[i]; rng=hi[i]-lo[i]; prev=c[i-1] if i>0 else price
        if rng<=0: continue

        dirs=[0,0,0,0]; sc=[0.,0.,0.,0]

        # Pullback
        if regime in [1,-1]:
            d=1 if regime==1 else -1; pb=abs(price-e20[i])
            if 0.30*at[i]<=pb<=2.20*at[i]:
                ok=True
                if d>0 and (rs[i]>65 or body<-0.1*at[i]): ok=False
                if d<0 and (rs[i]<35 or body>0.1*at[i]): ok=False
                if d>0 and e20[i]<=e50[i]: ok=False
                if d<0 and e20[i]>=e50[i]: ok=False
                if ok: dirs[0]=d; sc[0]=4.0

        # Breakout
        if regime!=-99 and i>=14:
            bars=12; hh=max(hi[i-j] for j in range(bars)); ll=min(lo[i-j] for j in range(bars))
            buf=0.10*at[i]; bd2=1 if regime in [1,0] else -1
            if bd2>0 and price>hh+buf and body>0: dirs[1]=1; sc[1]=3.5
            if bd2<0 and price<ll-buf and body<0: dirs[1]=-1; sc[1]=3.5

        # Momentum
        ratio=abs(body)/rng
        if ratio>=0.55 and ratio>0.45: dirs[2]=1 if body>0 else -1; sc[2]=3.0

        # Mean Revert
        if regime==0:
            if prev<=bb_lo[i] and price>bb_lo[i] and rs[i]<32: dirs[3]=1; sc[3]=3.8
            if prev>=bb_up[i] and price<bb_up[i] and rs[i]>68: dirs[3]=-1; sc[3]=3.8

        bs=0; ss=0; bc=0; sc2=0
        for j in range(4):
            if dirs[j]>0: bs+=int(sc[j]); bc+=1
            if dirs[j]<0: ss+=int(sc[j]); sc2+=1
        if regime==1: bs+=2
        if regime==-1: ss+=2

        fd=0
        if bs>=min_score and bs>ss:
            if not require_2 or bc>=2: fd=1
        elif ss>=min_score and ss>bs:
            if not require_2 or sc2>=2: fd=-1
        if fd==0: continue

        sd=1.7*at[i]
        if fd>0:
            lo2=min(lo[max(0,i-j)] for j in range(min(6,i)))
            sd=max(sd,price-(lo2-0.15*at[i]))
        else:
            hi2=max(hi[max(0,i-j)] for j in range(min(6,i)))
            sd=max(sd,(hi2+0.15*at[i])-price)
        if sd>price*0.03: sd=price*0.03
        if sd<at[i]*0.5: sd=at[i]*0.5

        if fd>0: sld=price-sd; tpd=price+2.5*sd
        else: sld=price+sd; tpd=price-2.5*sd

        if lots_fixed: lots=lots_fixed
        else:
            rm=equity*risk_pct; lpl=(sd/info.trade_tick_size)*info.trade_tick_value
            if lpl<=0: continue
            lots=rm/lpl; lots=max(info.volume_min,min(lots,info.volume_max)); lots=round(lots,2)

        ep=price; ed=fd; op=True; bh=0; td+=1

    if op:
        ep2=c[min(end-1,n-1)]
        trades.append(((ep2-ep) if ed>0 else (ep-ep2)-spread)*lots*dpp)

    if not trades: return None
    p=np.array(trades); w=p[p>0]; lo2=p[p<=0]
    return {
        'trades':len(p), 'wr':len(w)/len(p)*100, 'total':np.sum(p),
        'pf':np.sum(w)/abs(np.sum(lo2)) if len(lo2)>0 and np.sum(lo2)!=0 else 999,
        'max_dd':np.min(p), 't_day':len(p)/((end-max(start,250))/288),
        'tecs':tecs, 'tes':tes, 'tss':tss,
    }

# === TEST DIFFERENT CONFIGS ===
print(f"\n  {'Score':>5s} {'2+?':>4s} {'Lots':>6s} {'#':>4s} {'T/D':>5s} {'WR%':>6s} {'$P&L':>9s} {'PF':>5s} {'T/S/Tm':>8s}")
print(f"  {'─'*5} {'─'*4} {'─'*6} {'─'*4} {'─'*5} {'─'*6} {'─'*9} {'─'*5} {'─'*8}")

configs = [
    (3, False, 25), (3, True, 25), (4, False, 25), (4, True, 25),
    (5, False, 25), (5, True, 25), (3, False, 10), (3, True, 10),
    (4, False, 10), (5, True, 10), (5, False, 5), (5, True, 5),
]

all_r = []
for ms, r2, lf in configs:
    r = run_test(ms, r2, 0.01, lf, 0, n)
    if r:
        r['ms']=ms; r['r2']=r2; r['lf']=lf; all_r.append(r)
        print(f"  {ms:>5d} {'Y' if r2 else 'N':>4s} {lf:>6d} {r['trades']:>4d} {r['t_day']:>5.1f} {r['wr']:>5.1f}% ${r['total']:>8.2f} {r['pf']:>5.2f} {r['tecs']}/{r['tss']}/{r['tes']}")

# Best
if all_r:
    best = max(all_r, key=lambda x: x['total'])
    print(f"\n{'─'*70}")
    print(f"  BEST: Score={best['ms']} 2+={best['r2']} Lots={best['lf']} | WR={best['wr']:.1f}% | Total=${best['total']:.2f} | PF={best['pf']:.2f}")

    # Walk-forward
    print(f"\n{'─'*70}")
    print(f"  WALK-FORWARD (60/40)")
    print(f"{'─'*70}")
    split = int(n * 0.6)
    train = run_test(best['ms'], best['r2'], 0.01, best['lf'], 0, split)
    test = run_test(best['ms'], best['r2'], 0.01, best['lf'], split, n)
    if train:
        print(f"  TRAIN: {train['trades']} trades ({train['t_day']:.1f}/day) WR={train['wr']:.1f}% ${train['total']:.2f} PF={train['pf']:.2f}")
    if test:
        print(f"  TEST:  {test['trades']} trades ({test['t_day']:.1f}/day) WR={test['wr']:.1f}% ${test['total']:.2f} PF={test['pf']:.2f}")
    if train and test:
        days_test = (n-split)/288
        daily = test['total']/days_test
        print(f"\n  PROJECTION:")
        print(f"    Daily: ${daily:.2f} | 30d: ${daily*30:.2f} | 90d: ${daily*90:.2f} | ROI: {daily*90/equity*100:.0f}%")

mt5.shutdown()
print(f"\n{'='*70}")
