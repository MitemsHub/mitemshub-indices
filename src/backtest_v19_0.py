#!/usr/bin/env python3
"""v19.0 Step Index M15 - Full scoring engine backtest with proper intra-bar simulation"""
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

print(f"=== {SYMBOL} v19.0 ===")
print(f"Point: {POINT} | TickVal: {TICK_VAL} | Spread: {SPREAD}")

# Parameters
EMA_F, EMA_M, EMA_S = 20, 50, 100
MIN_SCORE = 70
RISK_PCT = 0.01
SL_ATR_MULT = 1.5
TP_R_MULT = 2.0
MIN_SL_PTS = 2.0
MAX_SL_PTS = 15.0
MAX_HOLD = 16
BE_R = 0.8
TRAIL_R = 1.0
TRAIL_ATR = 0.8
LOCK_R = 1.5
LOCK_PTS = 1.0
MAX_TRADES = 5
SWING_LB = 5
STRUCT_BARS = 20

end = datetime(2026, 8, 23, 22, 0)
start = end - timedelta(days=90)
bars = mt5.copy_rates_range(SYMBOL, TF_ENTRY, start, end)
bars_r = mt5.copy_rates_range(SYMBOL, TF_REGIME, start, end)
print(f"Data: {len(bars)} M15 bars")

c = bars['close']; h = bars['high']; l = bars['low']; o = bars['open']; t = bars['time']
cr = bars_r['close']; tr = bars_r['time']

def ema(d, p):
    r = np.full(len(d), np.nan)
    if len(d) < p: return r
    r[p-1] = np.mean(d[:p]); m = 2.0/(p+1)
    for i in range(p, len(d)): r[i] = (d[i]-r[i-1])*m+r[i-1]
    return r

def calc_atr(hi, lo, cl, p):
    r = np.zeros(len(cl))
    for i in range(1, len(cl)):
        tr2 = max(hi[i]-lo[i], abs(hi[i]-cl[i-1]), abs(lo[i]-cl[i-1]))
        if i < p: r[i] = np.mean([max(hi[j]-lo[j], abs(hi[j]-cl[j-1]), abs(lo[j]-cl[j-1])) for j in range(1,i+1)])
        else: r[i] = (r[i-1]*(p-1)+tr2)/p
    return r

ef_e = ema(c, EMA_F); em_e = ema(c, EMA_M); es_e = ema(c, EMA_S)
atr_e = calc_atr(h, l, c, 14)
ef_r = ema(cr, EMA_F); em_r = ema(cr, EMA_M); es_r = ema(cr, EMA_S)

def get_regime(bt):
    idx = np.searchsorted(tr, bt, side='right') - 1
    if idx < 0 or idx >= len(cr): return 0
    if np.isnan(ef_r[idx]) or np.isnan(em_r[idx]) or np.isnan(es_r[idx]): return 0
    p = cr[idx]
    if ef_r[idx] > em_r[idx] > es_r[idx] and p > ef_r[idx]: return 1
    if ef_r[idx] < em_r[idx] < es_r[idx] and p < ef_r[idx]: return -1
    return 0

def detect_structure(i):
    """Detect swing points and structure"""
    lookback = STRUCT_BARS + 5
    if i < lookback: return 0, False  # direction, bos
    
    highs_arr = [h[i-j] for j in range(1, lookback+1)]
    lows_arr = [l[i-j] for j in range(1, lookback+1)]
    
    swing_highs = []
    swing_lows = []
    
    for k in range(SWING_LB, lookback - SWING_LB):
        # Swing high
        is_sh = all(highs_arr[k] > highs_arr[k-j] for j in range(1, SWING_LB+1) if k-j >= 0) and \
                all(highs_arr[k] > highs_arr[k+j] for j in range(1, min(SWING_LB+1, lookback-k)))
        if is_sh: swing_highs.append((k, highs_arr[k]))
        
        # Swing low
        is_sl2 = all(lows_arr[k] < lows_arr[k-j] for j in range(1, SWING_LB+1) if k-j >= 0) and \
                 all(lows_arr[k] < lows_arr[k+j] for j in range(1, min(SWING_LB+1, lookback-k)))
        if is_sl2: swing_lows.append((k, lows_arr[k]))
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return 0, False
    
    sh1, sh2 = swing_highs[0][1], swing_highs[1][1]
    sl1, sl2 = swing_lows[0][1], swing_lows[1][1]
    
    atr_val = atr_e[i] if i < len(atr_e) else 0
    bos_thresh = 0.5 * atr_val / POINT
    
    if sh1 > sh2 and sl1 > sl2:  # Bullish HH+HL
        bos = (sh1 - sh2) / POINT > bos_thresh
        return 1, bos
    elif sh1 < sh2 and sl1 < sl2:  # Bearish LH+LL
        bos = (sh2 - sh1) / POINT > bos_thresh
        return -1, bos
    
    return 0, False

def calc_score(i, direction):
    """Calculate 0-100 score"""
    if direction == 0: return 0
    
    score = 0
    
    # TREND (25 points)
    regime = get_regime(t[i])
    trend = 0
    if regime == direction: trend += 15
    elif regime == 0: trend += 5
    # EMA alignment
    if not np.isnan(ef_e[i]) and not np.isnan(em_e[i]) and not np.isnan(es_e[i]):
        if direction > 0 and ef_e[i] > em_e[i] > es_e[i]: trend += 10
        elif direction < 0 and ef_e[i] < em_e[i] < es_e[i]: trend += 10
        else: trend += 3
    trend = min(trend, 25)
    
    # STRUCTURE (25 points)
    struct_dir, bos = detect_structure(i)
    structure = 0
    if struct_dir == direction: structure += 15
    else: structure += 5
    if bos: structure += 10
    else: structure += 3
    structure = min(structure, 25)
    
    # Disqualify if structure contradicts
    if struct_dir != 0 and struct_dir != direction:
        return 0
    
    # MOMENTUM (15 points)
    momentum = 0
    price = c[i]; prev = c[i-1]; body = price - prev
    body_pct = abs(body) / atr_e[i] if atr_e[i] > 0 else 0
    if not np.isnan(ef_e[i]) and not np.isnan(em_e[i]):
        if direction > 0 and ef_e[i] > em_e[i]: momentum += 3
        elif direction < 0 and ef_e[i] < em_e[i]: momentum += 3
    if body_pct > 0.3: momentum += 2
    if body_pct > 0.5: momentum += 2
    # Consecutive
    consec = 0
    for k in range(1, 5):
        if i-k-1 < 0: break
        b = c[i-k] - c[i-k-1]
        if (direction > 0 and b > 0) or (direction < 0 and b < 0): consec += 1
        else: break
    momentum += min(consec, 5)
    momentum = min(momentum, 15)
    
    # VOLATILITY (15 points)
    vol = 0
    atr_pts = atr_e[i] / POINT if POINT > 0 else 0
    if atr_pts >= MIN_SL_PTS: vol += 4
    else: vol += 1
    if atr_pts >= 3: vol += 5
    if atr_pts <= MAX_SL_PTS: vol += 3
    if atr_pts < MAX_SL_PTS * 2: vol += 3
    vol = min(vol, 15)
    
    # LOCATION (10 points)
    loc = 0
    lookback2 = 20
    hh2 = max(h[i-j] for j in range(1, min(lookback2, i)+1))
    ll2 = min(l[i-j] for j in range(1, min(lookback2, i)+1))
    rng = hh2 - ll2
    if rng > 0:
        pos_in_range = (c[i] - ll2) / rng
        if direction > 0:
            if pos_in_range < 0.4: loc += 8
            elif pos_in_range < 0.6: loc += 5
            else: loc += 2
        else:
            if pos_in_range > 0.6: loc += 8
            elif pos_in_range > 0.4: loc += 5
            else: loc += 2
    loc = min(loc, 10)
    
    # CONFIRMATION (10 points)
    confirm = 0
    # Simplified: check direction of last 3 M15 bars
    if i >= 3:
        m5_aligned = all((direction > 0 and c[i-j] > c[i-j-1]) or (direction < 0 and c[i-j] < c[i-j-1]) for j in range(1, 4))
        if m5_aligned: confirm += 7
        else: confirm += 2
    confirm += 3  # Base for having data
    confirm = min(confirm, 10)
    
    total = trend + structure + momentum + vol + loc + confirm
    return total

# ═══ SIMULATION ═══
equity = ACCOUNT_BAL
trades = []
daily_trades = 0
day_start = 0
wins = 0; losses = 0; total_r = 0; total_pnl = 0
peak_eq = equity; max_dd = 0
target_exits = 0; stop_exits = 0; time_exits = 0
scores_used = []

pos = None  # {dir, entry, sl, tp, orig_sl_pts, bars_held, entry_score}

for i in range(300, len(c)):
    bar_day = t[i] // 86400
    if bar_day != day_start:
        day_start = bar_day
        daily_trades = 0

    # ── MANAGE ──
    if pos is not None:
        pos['bars_held'] += 1
        d = pos['dir']
        entry = pos['entry']
        sl = pos['sl']
        tp = pos['tp']
        orig_sl = pos['orig_sl_pts']
        
        bar_close = c[i]
        
        # Current R
        cur_r = (bar_close - entry) * d / POINT / orig_sl if orig_sl > 0 else 0
        
        # BE
        if cur_r >= BE_R:
            new_sl = entry + LOCK_PTS * POINT * d
            if d > 0 and new_sl > sl:
                sl = new_sl; pos['sl'] = sl
            elif d < 0 and new_sl < sl:
                sl = new_sl; pos['sl'] = sl
        
        # Trail
        if cur_r >= TRAIL_R:
            trail_dist = TRAIL_ATR * atr_e[i]
            if d > 0:
                new_sl = bar_close - trail_dist
                if new_sl > sl and new_sl > entry:
                    sl = new_sl; pos['sl'] = sl
            else:
                new_sl = bar_close + trail_dist
                if new_sl < sl and new_sl < entry:
                    sl = new_sl; pos['sl'] = sl
        
        # Lock
        if cur_r >= LOCK_R:
            lock_p = LOCK_PTS * POINT
            if d > 0:
                new_sl = entry + lock_p
                if new_sl > sl: sl = new_sl; pos['sl'] = sl
            else:
                new_sl = entry - lock_p
                if new_sl < sl: sl = new_sl; pos['sl'] = sl
        
        # Intra-bar exit check (direction-aware)
        bullish_bar = c[i] >= o[i]
        exit_p = None; reason = ""
        
        if d > 0:
            if bullish_bar:
                if h[i] >= tp: exit_p = tp; reason = "TARGET"
                elif l[i] <= sl: exit_p = sl; reason = "STOP"
            else:
                if l[i] <= sl: exit_p = sl; reason = "STOP"
                elif h[i] >= tp: exit_p = tp; reason = "TARGET"
        else:
            if bullish_bar:
                if h[i] >= sl: exit_p = sl; reason = "STOP"
                elif l[i] <= tp: exit_p = tp; reason = "TARGET"
            else:
                if l[i] <= tp: exit_p = tp; reason = "TARGET"
                elif h[i] >= sl: exit_p = sl; reason = "STOP"
        
        if exit_p is None and pos['bars_held'] >= MAX_HOLD:
            exit_p = bar_close; reason = "TIME"
        
        if exit_p is not None:
            exit_pts = (exit_p - entry) * d / POINT
            r = exit_pts / orig_sl if orig_sl > 0 else 0
            spread_cost = SPREAD * TICK_VAL / TICK_SIZE * POINT * pos['vol']
            pnl = exit_pts * TICK_VAL / TICK_SIZE * POINT * pos['vol'] - spread_cost
            
            equity += pnl; total_pnl += pnl; total_r += r
            if r > 0: wins += 1
            else: losses += 1
            if reason == "TARGET": target_exits += 1
            elif reason == "STOP": stop_exits += 1
            elif reason == "TIME": time_exits += 1
            
            trades.append({'dir': d, 'r': r, 'pnl': pnl, 'reason': reason,
                          'score': pos['entry_score'], 'bars': pos['bars_held']})
            scores_used.append(pos['entry_score'])
            
            if equity > peak_eq: peak_eq = equity
            dd = peak_eq - equity
            if dd > max_dd: max_dd = dd
            
            pos = None

    # ── ENTRY ──
    if pos is not None or daily_trades >= MAX_TRADES: continue
    if equity <= 0: break
    if i < 2 or np.isnan(atr_e[i-1]): continue
    
    regime = get_regime(t[i])
    if regime == 0: continue
    
    # Structure
    struct_dir, bos = detect_structure(i)
    if struct_dir != 0 and struct_dir != regime: continue
    
    direction = regime  # Use regime as primary direction
    
    # Score
    score = calc_score(i, direction)
    if score < MIN_SCORE: continue
    
    # Price action: must have bullish/bearish body
    body = c[i] - c[i-1]
    if direction > 0 and body <= 0: continue
    if direction < 0 and body >= 0: continue
    
    # RSI filter
    # Simple RSI calc
    if i >= 15:
        deltas = [c[i-j] - c[i-j-1] for j in range(14)]
        gains = np.mean([d for d in deltas if d > 0]) if any(d > 0 for d in deltas) else 0
        losses2 = np.mean([-d for d in deltas if d < 0]) if any(d < 0 for d in deltas) else 0.001
        rsi_val = 100 - 100/(1 + gains/losses2)
        if direction > 0 and rsi_val > 70: continue
        if direction < 0 and rsi_val < 30: continue
    
    # Volatility-aware SL
    atr_pts = atr_e[i] / POINT
    sl_atr = SL_ATR_MULT * atr_pts
    
    # Structure SL
    if direction > 0:
        struct_sl = (c[i] - min(l[i-j] for j in range(1, 7))) / POINT
    else:
        struct_sl = (max(h[i-j] for j in range(1, 7)) - c[i]) / POINT
    
    sl_pts = max(struct_sl, sl_atr)
    sl_pts = max(MIN_SL_PTS, min(MAX_SL_PTS, sl_pts))
    tp_pts = sl_pts * TP_R_MULT
    
    # Risk-based sizing
    entry_price = c[i]
    sl_dist = sl_pts * POINT
    risk_money = equity * RISK_PCT
    tick_val = TICK_VAL
    tick_size = TICK_SIZE
    if tick_size <= 0: continue
    ticks_to_sl = sl_dist / tick_size
    loss_per_lot = ticks_to_sl * tick_val
    if loss_per_lot <= 0: continue
    vol = risk_money / loss_per_lot
    
    minv = info.volume_min; maxv = info.volume_max; step = info.volume_step
    if step <= 0: step = 0.01
    vol = int(vol / step) * step
    vol = max(minv, min(maxv, vol))
    
    # Check margin
    margin = info.margin_initial if info.margin_initial > 0 else 7.83
    if vol * margin > equity * 0.90:
        vol = int(equity * 0.90 / margin / step) * step
        vol = max(minv, vol)
    
    sl_p = entry_price - sl_dist * direction
    tp_p = entry_price + tp_pts * POINT * direction
    
    pos = {'dir': direction, 'entry': entry_price, 'sl': sl_p, 'tp': tp_p,
           'orig_sl_pts': sl_pts, 'bars_held': 0, 'entry_score': score, 'vol': vol}
    daily_trades += 1

# Close remaining
if pos is not None:
    ep = c[-1]
    epts = (ep - pos['entry']) * pos['dir'] / POINT
    r = epts / pos['orig_sl_pts']
    pnl = epts * TICK_VAL / TICK_SIZE * POINT * pos['vol']
    equity += pnl; total_pnl += pnl; total_r += r
    if r > 0: wins += 1
    else: losses += 1
    trades.append({'dir': pos['dir'], 'r': r, 'pnl': pnl, 'reason': 'END', 'score': pos['entry_score'], 'bars': pos['bars_held']})

total = wins + losses
wr = wins/total*100 if total > 0 else 0

print(f"\n{'='*60}")
print(f"v19.0 STEP INDEX M15 — 90 DAY BACKTEST")
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

# By reason
for reason in ["TARGET", "STOP", "TIME"]:
    rt = [t for t in trades if t['reason'] == reason]
    if rt:
        rw = len([t for t in rt if t['r'] > 0])
        avg_r = np.mean([t['r'] for t in rt])
        print(f"  {reason}: {len(rt)} trades, {rw} wins ({rw/len(rt)*100:.0f}%), avg R={avg_r:+.3f}")

# Score distribution
if scores_used:
    print(f"\n--- Score Distribution ---")
    for lo in range(50, 100, 10):
        hi = lo + 10
        st = [t for t in trades if lo <= t['score'] < hi]
        if st:
            sw = len([t for t in st if t['r'] > 0])
            print(f"  Score {lo}-{hi}: {len(st)} trades, {sw} wins ({sw/len(st)*100:.0f}%), PnL=${sum(t['pnl'] for t in st):+.2f}")

# Economics
print(f"\n--- Economics ---")
if trades:
    avg_sl = np.mean([abs(t['r']) for t in trades]) if trades else 0
    avg_hold = np.mean([t['bars'] for t in trades])
    print(f"Avg hold: {avg_hold:.1f} bars = {avg_hold*15:.0f} min")
    print(f"Daily avg: ${total_pnl/90:.2f}/day")

mt5.shutdown()
