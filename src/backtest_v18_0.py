#!/usr/bin/env python3
"""v18.0 Step Index M15 - FIXED backtest with proper intra-bar path simulation"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

if not mt5.initialize():
    print("MT5 init failed"); exit(1)

SYMBOL = "Step Index"
TF_ENTRY = mt5.TIMEFRAME_M15
TF_REGIME = mt5.TIMEFRAME_H1
ACCOUNT_BAL = 22.75

info = mt5.symbol_info(SYMBOL)
if info is None or not info.visible:
    mt5.symbol_select(SYMBOL, True)
    info = mt5.symbol_info(SYMBOL)

POINT = info.point
TICK_VAL = info.trade_tick_value
TICK_SIZE = info.trade_tick_size
SPREAD = info.spread
MARGIN_PER_LOT = info.margin_initial if info.margin_initial > 0 else 7.83

print(f"=== {SYMBOL} ===")
print(f"Point: {POINT} | TickVal: {TICK_VAL} | TickSize: {TICK_SIZE} | Spread: {SPREAD}")

# Parameters
EMA_FAST, EMA_MID, EMA_SLOW = 20, 50, 100
FIXED_TP_PTS = 2.0
FIXED_SL_PTS = 3.0
MOM_MIN_MOVE = 0.5
RSI_PERIOD = 14
RSI_BUY_MAX = 70.0
RSI_SELL_MIN = 30.0
ATR_PERIOD = 14
MIN_ATR_PTS = 5.0
MAX_HOLD = 8
BE_TRIGGER_PTS = 1.0
TRAIL_TRIGGER_PTS = 1.0
TRAIL_DIST_PTS = 0.5
SPREAD_COST = SPREAD * POINT

FIXED_VOL = 2.0
DOLLAR_PER_POINT = FIXED_VOL * TICK_VAL / TICK_SIZE * POINT
print(f"Vol: {FIXED_VOL} lots | ${DOLLAR_PER_POINT:.2f}/pt | TP=${FIXED_TP_PTS*DOLLAR_PER_POINT:.2f} SL=${FIXED_SL_PTS*DOLLAR_PER_POINT:.2f}")

end = datetime(2026, 8, 23, 22, 0)
start = end - timedelta(days=90)
bars = mt5.copy_rates_range(SYMBOL, TF_ENTRY, start, end)
bars_r = mt5.copy_rates_range(SYMBOL, TF_REGIME, start, end)
print(f"Data: {len(bars)} M15 bars, {len(bars_r)} H1 bars")

c = bars['close']
h = bars['high']
l = bars['low']
o = bars['open']
t = bars['time']
cr = bars_r['close']
tr = bars_r['time']

def ema(d, p):
    r = np.full(len(d), np.nan)
    if len(d) < p: return r
    r[p-1] = np.mean(d[:p])
    m = 2.0/(p+1)
    for i in range(p, len(d)): r[i] = (d[i]-r[i-1])*m+r[i-1]
    return r

def rsi(d, p):
    r = np.full(len(d), 50.0)
    dd = np.diff(d)
    for i in range(p, len(d)):
        g = dd[i-p:i]
        ups = np.mean(g[g>0]) if np.any(g>0) else 0
        dns = -np.mean(g[g<0]) if np.any(g<0) else 0.0001
        r[i] = 100-100/(1+ups/dns)
    return r

def atr_calc(hi, lo, cl, p):
    r = np.zeros(len(cl))
    for i in range(1, len(cl)):
        tr = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
        r[i] = tr if i < p else (r[i-1]*(p-1)+tr)/p
        if i < p: r[i] = np.mean([max(hi[j]-lo[j], abs(hi[j]-cl[j-1]), abs(lo[j]-cl[j-1])) for j in range(1,i+1)])
    return r

ef_e = ema(c, EMA_FAST)
em_e = ema(c, EMA_MID)
rsi_e = rsi(c, RSI_PERIOD)
atr_e = atr_calc(h, l, c, ATR_PERIOD)

ef_r = ema(cr, EMA_FAST)
em_r = ema(cr, EMA_MID)
es_r = ema(cr, EMA_SLOW)

def get_regime(bt):
    idx = np.searchsorted(tr, bt, side='right') - 1
    if idx < 0 or idx >= len(cr): return 0
    if np.isnan(ef_r[idx]) or np.isnan(em_r[idx]) or np.isnan(es_r[idx]): return 0
    p = cr[idx]
    if ef_r[idx] > em_r[idx] > es_r[idx] and p > ef_r[idx]: return 1
    if ef_r[idx] < em_r[idx] < es_r[idx] and p < ef_r[idx]: return -1
    return 0

# ═══ SIMULATION ═══
equity = ACCOUNT_BAL
trades = []
daily_trades = 0
day_start = 0
wins = 0; losses = 0; total_r = 0; total_pnl = 0
target_exits = 0; stop_exits = 0; time_exits = 0
peak_eq = equity; max_dd = 0

pos = None

for i in range(300, len(c)):
    bar_day = t[i] // 86400
    if bar_day != day_start:
        day_start = bar_day
        daily_trades = 0

    # ── MANAGE POSITION ──
    if pos is not None:
        pos['bars_held'] += 1
        d = pos['dir']
        entry = pos['entry']
        
        # Apply BE and trailing to SL
        sl = pos['sl']
        tp = pos['tp']
        
        # Check if bar range hits TP or SL
        # KEY FIX: For Step Index with 47pt bars and 2-3pt TP/SL,
        # we simulate intra-bar path using bar direction
        bar_open = o[i]
        bar_close = c[i]
        bar_high = h[i]
        bar_low = l[i]
        
        bullish_bar = bar_close >= bar_open
        
        # For a BUY position:
        # If bullish bar: price likely went UP first → check TP first
        # If bearish bar: price likely went DOWN first → check SL first
        # For SELL: reverse logic
        
        hit_tp = False
        hit_sl = False
        exit_price = None
        reason = ""
        
        if d > 0:  # BUY
            if bullish_bar:
                # Price went up first → check TP first
                if bar_high >= tp:
                    exit_price = tp; reason = "TARGET"; hit_tp = True
                elif bar_low <= sl:
                    exit_price = sl; reason = "STOP"; hit_sl = True
            else:
                # Price went down first → check SL first
                if bar_low <= sl:
                    exit_price = sl; reason = "STOP"; hit_sl = True
                elif bar_high >= tp:
                    exit_price = tp; reason = "TARGET"; hit_tp = True
        else:  # SELL
            if bullish_bar:
                # Price went up first → check SL first (for sell, SL is above)
                if bar_high >= sl:
                    exit_price = sl; reason = "STOP"; hit_sl = True
                elif bar_low <= tp:
                    exit_price = tp; reason = "TARGET"; hit_tp = True
            else:
                # Price went down first → check TP first (for sell, TP is below)
                if bar_low <= tp:
                    exit_price = tp; reason = "TARGET"; hit_tp = True
                elif bar_high >= sl:
                    exit_price = sl; reason = "STOP"; hit_sl = True
        
        # Time exit if no TP/SL hit
        if exit_price is None and pos['bars_held'] >= MAX_HOLD:
            exit_price = bar_close
            reason = "TIME"
        
        if exit_price is not None:
            exit_pts = (exit_price - entry) * d / POINT
            r_mult = exit_pts / pos['orig_sl_pts'] if pos['orig_sl_pts'] > 0 else 0
            pnl = exit_pts * DOLLAR_PER_POINT - SPREAD_COST * DOLLAR_PER_POINT / POINT * FIXED_VOL  # subtract spread
            
            # More accurate: spread is in points
            spread_dollars = SPREAD * DOLLAR_PER_POINT
            pnl = exit_pts * DOLLAR_PER_POINT - spread_dollars  # Spread cost always paid
            
            equity += pnl
            total_pnl += pnl
            total_r += r_mult
            if r_mult > 0: wins += 1
            else: losses += 1
            
            if reason == "TARGET": target_exits += 1
            elif reason == "STOP": stop_exits += 1
            elif reason == "TIME": time_exits += 1
            
            trades.append({'dir': d, 'entry': entry, 'exit': exit_price, 'reason': reason,
                          'r': r_mult, 'pnl': pnl, 'bars': pos['bars_held']})
            
            if equity > peak_eq: peak_eq = equity
            dd = peak_eq - equity
            if dd > max_dd: max_dd = dd
            
            pos = None

    # ── ENTRY ──
    if pos is not None or daily_trades >= 3: continue
    if equity <= 0: break
    if i < 2 or np.isnan(atr_e[i-1]) or atr_e[i-1] < MIN_ATR_PTS * POINT: continue

    regime = get_regime(t[i])
    price = c[i]
    prev = c[i-1]
    body = price - prev
    direction = 0; sig = ""
    
    if not np.isnan(ef_e[i]) and not np.isnan(em_e[i]) and not np.isnan(ef_e[i-1]) and not np.isnan(em_e[i-1]):
        if ef_e[i] > em_e[i] and ef_e[i-1] <= em_e[i-1]:
            if regime != -1 and rsi_e[i] < RSI_BUY_MAX and body > 0:
                direction = 1; sig = "EMACROSS_LONG"
        elif ef_e[i] < em_e[i] and ef_e[i-1] >= em_e[i-1]:
            if regime != 1 and rsi_e[i] > RSI_SELL_MIN and body < 0:
                direction = -1; sig = "EMACROSS_SHORT"

    if direction == 0:
        move = abs(body)
        if move >= MOM_MIN_MOVE * atr_e[i-1]:
            if body > 0 and regime != -1 and 45 < rsi_e[i] < RSI_BUY_MAX:
                direction = 1; sig = "MOMENTUM_LONG"
            elif body < 0 and regime != 1 and RSI_SELL_MIN < rsi_e[i] < 55:
                direction = -1; sig = "MOMENTUM_SHORT"

    if direction == 0: continue
    
    entry_price = c[i]
    sl_dist = FIXED_SL_PTS * POINT
    tp_dist = FIXED_TP_PTS * POINT
    
    pos = {
        'dir': direction, 'entry': entry_price,
        'sl': entry_price - sl_dist * direction,
        'tp': entry_price + tp_dist * direction,
        'orig_sl_pts': FIXED_SL_PTS, 'bars_held': 0,
    }
    daily_trades += 1

# Close remaining
if pos is not None:
    ep = c[-1]
    epts = (ep - pos['entry']) * pos['dir'] / POINT
    rm = epts / pos['orig_sl_pts']
    pnl = epts * DOLLAR_PER_POINT - SPREAD * DOLLAR_PER_POINT
    equity += pnl; total_pnl += pnl; total_r += rm
    if rm > 0: wins += 1
    else: losses += 1
    trades.append({'dir': pos['dir'], 'entry': pos['entry'], 'exit': ep, 'reason': 'END', 'r': rm, 'pnl': pnl, 'bars': pos['bars_held']})

total = wins + losses
wr = wins/total*100 if total > 0 else 0

print(f"\n{'='*60}")
print(f"v18.0 STEP INDEX M15 — 90 DAY BACKTEST (FIXED)")
print(f"{'='*60}")
print(f"Trades:     {total} ({total/90:.1f}/day)")
print(f"Wins:       {wins} | Losses: {losses}")
print(f"Win Rate:   {wr:.1f}%")
print(f"Total R:    {total_r:+.2f}")
print(f"Avg R:      {total_r/total:+.3f}" if total > 0 else "")
print(f"Net P&L:    ${total_pnl:+.2f}")
print(f"ROI:        {total_pnl/ACCOUNT_BAL*100:+.1f}%")
print(f"Final Eq:   ${equity:.2f}")
print(f"Peak Eq:    ${peak_eq:.2f}")
print(f"Max DD:     ${max_dd:.2f} ({max_dd/ACCOUNT_BAL*100:.1f}%)" if ACCOUNT_BAL > 0 else "")
print(f"\nExits:  Target={target_exits} Stop={stop_exits} Time={time_exits}")

buy_t = [t for t in trades if t['dir'] > 0]
sell_t = [t for t in trades if t['dir'] < 0]
bw = len([t for t in buy_t if t['r'] > 0])
sw = len([t for t in sell_t if t['r'] > 0])
print(f"\nBuys:  {len(buy_t)} ({bw}/{len(buy_t)} W = {bw/len(buy_t)*100:.0f}%) P&L=${sum(t['pnl'] for t in buy_t):+.2f}" if buy_t else "Buys:  0")
print(f"Sells: {len(sell_t)} ({sw}/{len(sell_t)} W = {sw/len(sell_t)*100:.0f}%) P&L=${sum(t['pnl'] for t in sell_t):+.2f}" if sell_t else "Sells: 0")

print(f"\n--- Economics at 2 lots ---")
print(f"Risk per trade:  ${FIXED_SL_PTS*DOLLAR_PER_POINT:.2f} (+ ${SPREAD*DOLLAR_PER_POINT:.2f} spread)")
print(f"Reward per trade: ${FIXED_TP_PTS*DOLLAR_PER_POINT:.2f}")
print(f"R:R Ratio:       1:{FIXED_TP_PTS/FIXED_SL_PTS:.2f}")
print(f"Break-even WR:   {FIXED_SL_PTS/(FIXED_SL_PTS+FIXED_TP_PTS)*100:.1f}%")
print(f"Avg hold:        {np.mean([t['bars'] for t in trades]):.1f} bars = {np.mean([t['bars'] for t in trades])*15:.0f} min")
print(f"Daily avg:       ${total_pnl/90:.2f}/day")

# Exit reason analysis
if trades:
    for reason in ["TARGET", "STOP", "TIME"]:
        rt = [t for t in trades if t['reason'] == reason]
        if rt:
            rw = len([t for t in rt if t['r'] > 0])
            avg_r = np.mean([t['r'] for t in rt])
            print(f"  {reason}: {len(rt)} trades, {rw} wins ({rw/len(rt)*100:.0f}%), avg R={avg_r:+.3f}")

mt5.shutdown()
