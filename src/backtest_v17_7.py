import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

mt5.initialize()
sym = "Volatility 100 Index"
info = mt5.symbol_info(sym)
if not info.visible: mt5.symbol_enable(sym)

point = info.point
tick_val = info.trade_tick_value
tick_size = info.trade_tick_size
min_vol = info.volume_min
dol_per_pt = tick_val / tick_size * point
margin_per_lot = mt5.order_calc_margin(0, sym, 1, mt5.symbol_info_tick(sym).ask)
if margin_per_lot <= 0: margin_per_lot = 0.62

print(f"V100: $/pt/lot=${dol_per_pt:.4f}, Margin/lot=${margin_per_lot:.2f}")

h1 = mt5.copy_rates_from(sym, mt5.TIMEFRAME_H1, datetime.now() - timedelta(days=90), 2200)
h4 = mt5.copy_rates_from(sym, mt5.TIMEFRAME_H4, datetime.now() - timedelta(days=90), 600)

opens_h1 = np.array([b['open'] for b in h1])
highs = np.array([b['high'] for b in h1])
lows  = np.array([b['low'] for b in h1])
closes = np.array([b['close'] for b in h1])
times = np.array([b['time'] for b in h1])
h4_closes = np.array([b['close'] for b in h4])
h4_times = np.array([b['time'] for b in h4])

print(f"Data: {len(h1)} H1, {len(h4)} H4 bars")

def ema(data, period):
    r = np.full(len(data), np.nan)
    if len(data) < period: return r
    r[period-1] = np.mean(data[:period])
    alpha = 2.0 / (period + 1)
    for i in range(period, len(data)):
        r[i] = alpha * data[i] + (1 - alpha) * r[i-1]
    return r

def calc_rsi(data, period=14):
    r = np.full(len(data), 50.0)
    for i in range(period, len(data)):
        deltas = np.diff(data[i-period:i+1])
        gains = np.sum(deltas[deltas > 0])
        losses = -np.sum(deltas[deltas < 0])
        r[i] = 100 if losses == 0 else 100 - 100 / (1 + gains/losses)
    return r

def calc_atr(h, l, c, period=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.insert(tr, 0, 0)
    r = np.zeros(len(tr))
    if len(tr) <= period: return r
    r[period] = np.mean(tr[1:period+1])
    for i in range(period+1, len(tr)):
        r[i] = (r[i-1] * (period-1) + tr[i]) / period
    return r

h4_ema20 = ema(h4_closes, 20)
h4_ema50 = ema(h4_closes, 50)
h4_ema100 = ema(h4_closes, 100)
ema20 = ema(closes, 20)
ema50 = ema(closes, 50)
ema100 = ema(closes, 100)
rsi14 = calc_rsi(closes, 14)
atr14 = calc_atr(highs, lows, closes, 14)

def get_h4_regime(t):
    idx = np.searchsorted(h4_times, t, side='right') - 1
    if idx < 2: return "NONE"
    ef = h4_ema20[idx-1] if not np.isnan(h4_ema20[idx-1]) else 0
    em = h4_ema50[idx-1] if not np.isnan(h4_ema50[idx-1]) else 0
    es = h4_ema100[idx-1] if not np.isnan(h4_ema100[idx-1]) else 0
    p = h4_closes[idx-1]
    if ef > em > es and p > ef: return "BULLISH"
    if ef < em < es and p < ef: return "BEARISH"
    return "RANGING"

# ── v17.7 Parameters (less selective) ──
equity = 22.75
peak_eq = equity
trades_list = []
ticket = None; tdir = 0; tentry = 0; tsl = 0; ttp = 0; trisk = 0; tvol = 1; theld = 0
cooldown = 0; consec_loss = 0; paused = False; last_day = 0
atr_hist = []
entry_time = 0

TREND_ONLY = False
MIN_EMA_SEP = 0.18
PB_MIN = 0.35; PB_MAX = 2.60
RSI_BUY = 68.0; RSI_SELL = 32.0
REQ_ALIGN = False
USE_BREAKOUT = True; BRK_LB = 8; BRK_BUF = 0.08
USE_MOMENTUM = True; MOM_LB = 10; MOM_MIN = 0.90; MOM_RSI_B = 50.0; MOM_RSI_S = 50.0; SLOPE = 0.30
ATR_LOW = 6.0; ATR_HIGH = 92.0
HOLD = 16; TP_MULT = 2.6; MAX_CONSEC = 3; COOL = 3
TRAIL_S = 1.0; TRAIL_D = 1.0; BE_T = 1.2
SL_Q = 1.50; SL_A = 1.80
RISK = 0.0035
EARLY_HOURS = 5; EARLY_MIN_R = 0.20

print(f"\n{'='*60}")
print(f" v17.7 Backtest: V100 H1+H4 | 90 days | ${equity:.2f}")
print(f" TrendOnly={TREND_ONLY} | EMA Sep={MIN_EMA_SEP} | RSI={int(RSI_SELL)}/{int(RSI_BUY)}")
print(f"{'='*60}\n")

for i in range(150, len(h1)-1):
    if atr14[i] <= 0 or np.isnan(atr14[i]): continue
    
    bar_day = times[i] // 86400
    if bar_day != last_day:
        last_day = bar_day
        paused = False
        consec_loss = 0
    
    atr_hist.append(atr14[i])
    if len(atr_hist) > 200: atr_hist = atr_hist[-200:]
    atr_pct = sum(1 for a in atr_hist if atr14[i] > a) / len(atr_hist) * 100 if len(atr_hist) >= 40 else 50.0
    if atr_pct > ATR_HIGH or atr_pct < ATR_LOW: continue
    
    # Manage position
    if ticket is not None:
        theld += 1
        bid = closes[i]; ask = closes[i]
        
        # Early exit
        hrs = (times[i] - entry_time) / 3600.0
        if hrs >= EARLY_HOURS:
            r_now = (bid - tentry) * tdir / trisk if trisk > 0 else 0
            if r_now < EARLY_MIN_R:
                pnl = r_now * trisk * tvol * dol_per_pt
                equity += pnl
                trades_list.append({"r": r_now, "pnl": pnl, "reason": "EARLY", "dir": tdir})
                if r_now <= 0: consec_loss += 1; cooldown = COOL
                else: consec_loss = 0
                if consec_loss >= MAX_CONSEC: paused = True
                ticket = None; theld = 0; continue
        
        # Breakeven
        if BE_T > 0 and atr14[i] > 0:
            be = BE_T * atr14[i]
            if tdir > 0 and bid >= tentry + be and tsl < tentry: tsl = tentry + 3 * point
            elif tdir < 0 and ask <= tentry - be and tsl > tentry: tsl = tentry - 3 * point
        
        # Trailing
        if TRAIL_S > 0 and atr14[i] > 0:
            ts = TRAIL_S * atr14[i]; td = TRAIL_D * atr14[i]
            if tdir > 0 and bid >= tentry + ts:
                nsl = bid - td
                if nsl > tsl and nsl > tentry: tsl = nsl
            elif tdir < 0 and ask <= tentry - ts:
                nsl = ask + td
                if nsl < tsl and nsl > tentry: tsl = nsl
        
        hit_sl = hit_tp = hit_time = False; exit_p = closes[i]
        if theld >= HOLD: hit_time = True; exit_p = closes[i]
        elif tdir > 0:
            if lows[i] <= tsl: hit_sl = True; exit_p = tsl
            elif highs[i] >= ttp: hit_tp = True; exit_p = ttp
        else:
            if highs[i] >= tsl: hit_sl = True; exit_p = tsl
            elif lows[i] <= ttp: hit_tp = True; exit_p = ttp
        
        if hit_sl or hit_tp or hit_time:
            r_mult = (exit_p - tentry) * tdir / trisk if trisk > 0 else 0
            pnl = r_mult * trisk * tvol * dol_per_pt
            equity += pnl
            reason = "TARGET" if hit_tp else ("STOP" if hit_sl else "TIME")
            trades_list.append({"r": r_mult, "pnl": pnl, "reason": reason, "dir": tdir})
            if r_mult <= 0: consec_loss += 1; cooldown = COOL
            else: consec_loss = 0
            if consec_loss >= MAX_CONSEC: paused = True
            ticket = None; theld = 0; continue
    
    if equity > peak_eq: peak_eq = equity
    if cooldown > 0: cooldown -= 1; continue
    if paused or ticket is not None: continue
    
    # Signal generation
    regime = get_h4_regime(times[i])
    if regime == "NONE": continue
    if TREND_ONLY and regime == "RANGING": continue
    
    ef = ema20[i-1] if not np.isnan(ema20[i-1]) else 0
    em = ema50[i-1] if not np.isnan(ema50[i-1]) else 0
    es = ema100[i-1] if not np.isnan(ema100[i-1]) else 0
    rv = rsi14[i-1]; av = atr14[i-1]
    price = closes[i-1]; body = closes[i-1] - closes[i-2] if i >= 2 else 0
    
    sig = ""; direction = 0
    
    # BREAKOUT
    if USE_BREAKOUT and i >= BRK_LB + 2:
        dir_b = 0
        if regime == "BULLISH": dir_b = 1
        elif regime == "BEARISH": dir_b = -1
        elif regime == "RANGING":
            ema_now = ema20[i-1] if not np.isnan(ema20[i-1]) else 0
            ema_prev = ema20[i-6] if i >= 6 and not np.isnan(ema20[i-6]) else 0
            slope = ema_now - ema_prev
            if slope > SLOPE * av: dir_b = 1
            elif slope < -SLOPE * av: dir_b = -1
        
        if dir_b != 0:
            hh = max(highs[i-k] for k in range(1, BRK_LB+1))
            ll = min(lows[i-k] for k in range(1, BRK_LB+1))
            buf = BRK_BUF * av
            if dir_b > 0 and price > hh + buf and body > 0 and rv < RSI_BUY:
                direction = 1; sig = "BREAKOUT_LONG"
            elif dir_b < 0 and price < ll - buf and body < 0 and rv > RSI_SELL:
                direction = -1; sig = "BREAKOUT_SHORT"
    
    # PULLBACK
    if direction == 0 and regime in ("BULLISH", "BEARISH"):
        dm = 1 if regime == "BULLISH" else -1
        pb = abs(price - ef)
        if pb >= PB_MIN * av and pb <= PB_MAX * av:
            if not ((dm > 0 and price > ef + 0.65*av) or (dm < 0 and price < ef - 0.65*av)):
                rsi_ok = (dm > 0 and rv <= RSI_BUY) or (dm < 0 and rv >= RSI_SELL)
                body_ok = (dm > 0 and body >= -0.12*av) or (dm < 0 and body <= 0.12*av)
                ema_ok = True
                if REQ_ALIGN:
                    if dm > 0: ema_ok = ef > em > es
                    else: ema_ok = ef < em < es
                if rsi_ok and body_ok and ema_ok:
                    direction = dm; sig = "PULLBACK_LONG" if dm > 0 else "PULLBACK_SHORT"
    
    # MOMENTUM
    if direction == 0 and USE_MOMENTUM and regime == "RANGING":
        ema_now = ema20[i-1] if not np.isnan(ema20[i-1]) else 0
        ema_prev = ema20[i-6] if i >= 6 and not np.isnan(ema20[i-6]) else 0
        slope = ema_now - ema_prev
        md = 0
        if slope > SLOPE * av: md = 1
        elif slope < -SLOPE * av: md = -1
        if md != 0:
            hh = max(highs[i-k] for k in range(1, min(MOM_LB+1, i)))
            ll = min(lows[i-k] for k in range(1, min(MOM_LB+1, i)))
            if md > 0 and (price-ll) > MOM_MIN*av and rv > MOM_RSI_B and body > 0:
                direction = 1; sig = "MOMENTUM_LONG"
            elif md < 0 and (hh-price) > MOM_MIN*av and rv < MOM_RSI_S and body < 0:
                direction = -1; sig = "MOMENTUM_SHORT"
    
    if direction == 0: continue
    
    # Open trade
    entry = closes[i]
    sl_mult = SL_A
    sl_dist = sl_mult * av
    
    if direction > 0 and i >= 6:
        sl_swing = min(lows[i-k] for k in range(1, 6))
        struct_sl = sl_swing - 0.15 * av
        sl_dist = max(sl_dist, entry - struct_sl)
    elif direction < 0 and i >= 6:
        sl_swing = max(highs[i-k] for k in range(1, 6))
        struct_sl = sl_swing + 0.15 * av
        sl_dist = max(sl_dist, struct_sl - entry)
    
    max_stop = entry * 0.028
    if sl_dist > max_stop: sl_dist = max_stop
    if sl_dist < av * 0.45: sl_dist = av * 0.45
    
    tp_dist = TP_MULT * sl_dist
    sl = entry - sl_dist if direction > 0 else entry + sl_dist
    tp = entry + tp_dist if direction > 0 else entry - tp_dist
    
    vol = int(equity * RISK / (sl_dist / tick_size * tick_val)) if tick_size > 0 and tick_val > 0 else int(min_vol)
    vol = max(int(min_vol), min(vol, 220))
    
    ticket = i; tdir = direction; tentry = entry; tsl = sl; ttp = tp
    trisk = sl_dist; tvol = vol; theld = 0; entry_time = times[i]

# Close remaining
if ticket is not None:
    exit_p = closes[-1]
    r_mult = (exit_p - tentry) * tdir / trisk if trisk > 0 else 0
    pnl = r_mult * trisk * tvol * dol_per_pt
    equity += pnl
    trades_list.append({"r": r_mult, "pnl": pnl, "reason": "FINAL", "dir": tdir})

# Results
n = len(trades_list)
win_count = sum(1 for t in trades_list if t['r'] > 0)
total_r = sum(t['r'] for t in trades_list)
total_pnl = sum(t['pnl'] for t in trades_list)
wr = win_count / n * 100 if n > 0 else 0

by_reason = {}
for t in trades_list:
    r = t['reason']
    if r not in by_reason: by_reason[r] = {"count": 0, "pnl": 0, "wins": 0}
    by_reason[r]["count"] += 1
    by_reason[r]["pnl"] += t['pnl']
    if t['r'] > 0: by_reason[r]["wins"] += 1

by_signal = {}
for t in trades_list:
    s = "LONG" if t['dir'] > 0 else "SHORT"
    if s not in by_signal: by_signal[s] = {"count": 0, "pnl": 0, "wins": 0}
    by_signal[s]["count"] += 1
    by_signal[s]["pnl"] += t['pnl']
    if t['r'] > 0: by_signal[s]["wins"] += 1

# Max drawdown
eq_curve = [22.75]
running_eq = 22.75
for t in trades_list:
    running_eq += t['pnl']
    eq_curve.append(running_eq)
peak = 22.75; max_dd = 0
for e in eq_curve:
    if e > peak: peak = e
    dd = (peak - e) / peak * 100 if peak > 0 else 0
    if dd > max_dd: max_dd = dd

# Walk-forward: first 60 days vs last 30 days
cutoff = len(h1) * 60 // 90
train = [t for t in trades_list if any(t_i < cutoff for t_i in [i for i, tt in enumerate(trades_list) if tt == t])]
test = [t for t in trades_list if t not in train]

print(f"{'='*60}")
print(f" 90-DAY BACKTEST RESULTS")
print(f"{'='*60}")
print(f" Trades:         {n} ({n/90:.1f}/day)")
print(f" Win Rate:       {wr:.1f}%")
print(f" Total R:        {total_r:+.2f}")
print(f" Starting:       $22.75")
print(f" Final:          ${equity:.2f}")
print(f" Net P&L:        ${total_pnl:+.2f}")
print(f" ROI:            {total_pnl/22.75*100:+.1f}%")
print(f" Peak Equity:    ${peak_eq:.2f}")
print(f" Max Drawdown:   {max_dd:.1f}%")
print(f"{'='*60}")
print(f" Exit Breakdown:")
for reason, data in sorted(by_reason.items()):
    wr_r = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
    print(f"   {reason:8s}: {data['count']:3d} trades | WR: {wr_r:.0f}% | P&L: ${data['pnl']:+.2f}")
print(f"{'='*60}")
print(f" Direction Breakdown:")
for sig, data in by_signal.items():
    wr_r = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
    print(f"   {sig:6s}: {data['count']:3d} trades | WR: {wr_r:.0f}% | P&L: ${data['pnl']:+.2f}")

# Monthly breakdown
from collections import defaultdict
monthly = defaultdict(lambda: {"count": 0, "pnl": 0, "wins": 0})
idx = 0
for t in trades_list:
    month = datetime.fromtimestamp(times[min(idx, len(times)-1)]).strftime('%Y-%m')
    monthly[month]["count"] += 1
    monthly[month]["pnl"] += t['pnl']
    if t['r'] > 0: monthly[month]["wins"] += 1
    idx += 1

print(f"\n Monthly Breakdown:")
for m in sorted(monthly.keys()):
    d = monthly[m]
    wr_m = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
    print(f"   {m}: {d['count']:2d} trades | WR: {wr_m:.0f}% | P&L: ${d['pnl']:+.2f}")

print(f"\n Sample trades (last 5):")
for t in trades_list[-5:]:
    print(f"   {'BUY' if t['dir']>0 else 'SELL':4s} {t['reason']:8s} R={t['r']:+.2f} P&L=${t['pnl']:+.2f}")

mt5.shutdown()
