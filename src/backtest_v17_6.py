import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

mt5.initialize()
sym = "Volatility 100 Index"
info = mt5.symbol_info(sym)
if not info.visible:
    mt5.symbol_enable(sym)

point = info.point
digits = info.digits
tick_val = info.trade_tick_value
tick_size = info.trade_tick_size
min_vol = info.volume_min

margin_per_lot = mt5.order_calc_margin(0, sym, 1, mt5.symbol_info_tick(sym).ask)
if margin_per_lot <= 0:
    margin_per_lot = 0.62

dol_per_pt = tick_val / tick_size * point
print(f"V100: $/pt/lot={dol_per_pt:.4f}, Margin/lot=${margin_per_lot:.2f}, MinVol={min_vol}")

# ── Fetch data ──
h1 = mt5.copy_rates_from(sym, mt5.TIMEFRAME_H1, datetime.now() - timedelta(days=90), 2200)
h4 = mt5.copy_rates_from(sym, mt5.TIMEFRAME_H4, datetime.now() - timedelta(days=90), 600)

opens_h1 = np.array([b['open'] for b in h1])
highs = np.array([b['high'] for b in h1])
lows  = np.array([b['low'] for b in h1])
closes = np.array([b['close'] for b in h1])
times = np.array([b['time'] for b in h1])
h4_closes = np.array([b['close'] for b in h4])
h4_times = np.array([b['time'] for b in h4])

print(f"Got {len(h1)} H1 bars, {len(h4)} H4 bars")

# ── Indicators ──
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
        if losses == 0: r[i] = 100
        else: r[i] = 100 - 100 / (1 + gains/losses)
    return r

def calc_atr(highs, lows, closes, period=14):
    tr = np.maximum(highs[1:] - lows[1:],
         np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    tr = np.insert(tr, 0, 0)
    r = np.full(len(tr), 0.0)
    if len(tr) <= period: return r
    r[period] = np.mean(tr[1:period+1])
    for i in range(period+1, len(tr)):
        r[i] = (r[i-1] * (period-1) + tr[i]) / period
    return r

# H4 indicators for regime
h4_ema20 = ema(h4_closes, 20)
h4_ema50 = ema(h4_closes, 50)
h4_ema100 = ema(h4_closes, 100)

# H1 indicators for entry
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

# ── Params ──
equity = 22.75
peak_eq = equity
trades_list = []

# Trade state
ticket = None; tdir = 0; tentry = 0; tsl = 0; ttp = 0; trisk = 0; tbar = 0; theld = 0; tvol = 1
cooldown = 0; consec_loss = 0; paused = False; last_day = 0
atr_hist = []

# Strategy params
TREND_ONLY = True
MIN_EMA_SEP = 0.30
PULLBACK_MIN = 0.40; PULLBACK_MAX = 2.50
RSI_BUY_MAX = 65.0; RSI_SELL_MIN = 35.0
REQUIRE_EMA_ALIGN = False
USE_BREAKOUT = True; BREAKOUT_LB = 10; BREAKOUT_BUF = 0.10
HOLD_BARS = 16; ATR_TARGET = 2.6
MAX_CONSEC = 3; COOL_BARS = 3
TRAIL_START = 1.0; TRAIL_DIST = 1.0; BE_TRIG = 1.2
SL_Q = 1.50; SL_A = 1.80
ATR_LOW = 10.0; ATR_HIGH = 88.0

print(f"\n=== V17.6 Backtest: V100 H1+H4 | 90 days | ${equity:.2f} | TrendOnly={TREND_ONLY} ===\n")

for i in range(150, len(h1)-1):
    if atr14[i] <= 0 or np.isnan(atr14[i]):
        continue
    
    bar_day = times[i] // 86400
    if bar_day != last_day:
        last_day = bar_day
        paused = False  # Daily reset
        consec_loss = 0
    
    # ATR percentile
    atr_hist.append(atr14[i])
    if len(atr_hist) > 200: atr_hist = atr_hist[-200:]
    atr_pct = sum(1 for a in atr_hist if atr14[i] > a) / len(atr_hist) * 100 if len(atr_hist) >= 40 else 50.0
    
    if atr_pct > ATR_HIGH or atr_pct < ATR_LOW:
        continue
    
    # ── Manage existing position ──
    if ticket is not None:
        theld += 1
        bid = closes[i]
        ask = closes[i]
        
        # Breakeven
        if BE_TRIG > 0 and atr14[i] > 0:
            be = BE_TRIG * atr14[i]
            if tdir > 0 and bid >= tentry + be and tsl < tentry:
                tsl = tentry + 3 * point
            elif tdir < 0 and ask <= tentry - be and tsl > tentry:
                tsl = tentry - 3 * point
        
        # Trailing
        if TRAIL_START > 0 and atr14[i] > 0:
            ts = TRAIL_START * atr14[i]
            td = TRAIL_DIST * atr14[i]
            if tdir > 0 and bid >= tentry + ts:
                nsl = bid - td
                if nsl > tsl and nsl > tentry: tsl = nsl
            elif tdir < 0 and ask <= tentry - ts:
                nsl = ask + td
                if nsl < tsl and nsl > tentry: tsl = nsl
        
        # Check exits
        hit_sl = False; hit_tp = False; hit_time = False
        
        if theld >= HOLD_BARS:
            hit_time = True
            exit_p = closes[i]
        elif tdir > 0:
            if lows[i] <= tsl: hit_sl = True; exit_p = tsl
            elif highs[i] >= ttp: hit_tp = True; exit_p = ttp
            else: exit_p = closes[i]
        else:
            if highs[i] >= tsl: hit_sl = True; exit_p = tsl
            elif lows[i] <= ttp: hit_tp = True; exit_p = ttp
            else: exit_p = closes[i]
        
        if hit_sl or hit_tp or hit_time:
            r_mult = (exit_p - tentry) * tdir / trisk if trisk > 0 else 0
            pnl = r_mult * trisk * tvol * dol_per_pt
            equity += pnl
            wr = "WIN" if r_mult > 0 else "LOSS"
            reason = "TARGET" if hit_tp else ("STOP" if hit_sl else "TIME")
            trades_list.append({"r": r_mult, "pnl": pnl, "reason": reason, "dir": tdir})
            
            if r_mult <= 0:
                consec_loss += 1
                cooldown = COOL_BARS
            else:
                consec_loss = 0
            
            if consec_loss >= MAX_CONSEC:
                paused = True
            
            ticket = None; theld = 0
            continue
    
    if equity > peak_eq: peak_eq = equity
    
    # Skip conditions
    if cooldown > 0: cooldown -= 1; continue
    if paused or ticket is not None: continue
    
    # ── Signal generation ──
    regime = get_h4_regime(times[i])
    if regime == "NONE": continue
    if TREND_ONLY and regime == "RANGING": continue
    
    ef = ema20[i-1] if not np.isnan(ema20[i-1]) else 0
    em = ema50[i-1] if not np.isnan(ema50[i-1]) else 0
    es = ema100[i-1] if not np.isnan(ema100[i-1]) else 0
    rv = rsi14[i-1]
    av = atr14[i-1]
    price = closes[i-1]
    body = closes[i-1] - closes[i-2] if i >= 2 else 0
    
    sig_type = ""; direction = 0
    
    # BREAKOUT (in trending regimes)
    if USE_BREAKOUT and regime in ("BULLISH", "BEARISH") and i >= BREAKOUT_LB + 1:
        hh = max(highs[i-k] for k in range(1, BREAKOUT_LB+1))
        ll = min(lows[i-k] for k in range(1, BREAKOUT_LB+1))
        buf = BREAKOUT_BUF * av
        
        if regime == "BULLISH" and price > hh + buf and body > 0 and rv < RSI_BUY_MAX:
            direction = 1; sig_type = "BREAKOUT_LONG"
        elif regime == "BEARISH" and price < ll - buf and body < 0 and rv > RSI_SELL_MIN:
            direction = -1; sig_type = "BREAKOUT_SHORT"
    
    # PULLBACK (trending)
    if direction == 0 and regime in ("BULLISH", "BEARISH"):
        dm = 1 if regime == "BULLISH" else -1
        pb = abs(price - ef)
        if pb >= PULLBACK_MIN * av and pb <= PULLBACK_MAX * av:
            rsi_ok = (dm > 0 and rv <= RSI_BUY_MAX) or (dm < 0 and rv >= RSI_SELL_MIN)
            body_ok = (dm > 0 and body >= -0.10 * av) or (dm < 0 and body <= 0.10 * av)
            ema_ok = True
            if REQUIRE_EMA_ALIGN:
                if dm > 0: ema_ok = ef > em > es
                else: ema_ok = ef < em < es
            if rsi_ok and body_ok and ema_ok:
                direction = dm
                sig_type = "PULLBACK_LONG" if dm > 0 else "PULLBACK_SHORT"
    
    if direction == 0: continue
    
    # ── Open trade ──
    entry = closes[i]
    sl_mult = SL_A
    sl_dist = sl_mult * av
    
    # Structure SL
    if direction > 0 and i >= 5:
        sl_swing = min(lows[i-k] for k in range(1, 6))
        struct_sl = sl_swing - 0.2 * av
        sl_dist = max(sl_dist, entry - struct_sl)
    elif direction < 0 and i >= 5:
        sl_swing = max(highs[i-k] for k in range(1, 6))
        struct_sl = sl_swing + 0.2 * av
        sl_dist = max(sl_dist, struct_sl - entry)
    
    max_stop = entry * 0.03
    if sl_dist > max_stop: sl_dist = max_stop
    if sl_dist < av * 0.4: sl_dist = av * 0.4
    
    tp_dist = ATR_TARGET * sl_dist
    sl = entry - sl_dist if direction > 0 else entry + sl_dist
    tp = entry + tp_dist if direction > 0 else entry - tp_dist
    
    # Volume: 70% margin
    vol = int(equity * 0.70 / margin_per_lot)
    vol = max(int(min_vol), min(vol, 220))
    
    ticket = i
    tdir = direction; tentry = entry; tsl = sl; ttp = tp
    trisk = sl_dist; tbar = i; theld = 0; tvol = vol

# Close remaining
if ticket is not None:
    exit_p = closes[-1]
    r_mult = (exit_p - tentry) * tdir / trisk if trisk > 0 else 0
    pnl = r_mult * trisk * tvol * dol_per_pt
    equity += pnl
    trades_list.append({"r": r_mult, "pnl": pnl, "reason": "FINAL", "dir": tdir})

# ── Results ──
n = len(trades_list)
wins = sum(1 for t in trades_list if t['r'] > 0)
losses_count = sum(1 for t in trades_list if t['r'] <= 0)
total_r = sum(t['r'] for t in trades_list)
total_pnl = sum(t['pnl'] for t in trades_list)
wr = wins / n * 100 if n > 0 else 0

# Exit breakdown
by_reason = {}
for t in trades_list:
    r = t['reason']
    if r not in by_reason: by_reason[r] = {"count": 0, "pnl": 0, "wins": 0}
    by_reason[r]["count"] += 1
    by_reason[r]["pnl"] += t['pnl']
    if t['r'] > 0: by_reason[r]["wins"] += 1

# By signal type
# Count regime
regimes_seen = {"BULLISH": 0, "BEARISH": 0, "RANGING": 0}

print(f"{'='*55}")
print(f" V17.6 Backtest Results — V100 H1+H4 — $22.75")
print(f"{'='*55}")
print(f" Trades:         {n} ({n/90:.1f}/day)")
print(f" Win Rate:       {wr:.1f}%")
print(f" Total R:        {total_r:+.2f}")
print(f" Starting:       $22.75")
print(f" Final:          ${equity:.2f}")
print(f" Net P&L:        ${total_pnl:+.2f}")
print(f" ROI:            {total_pnl/22.75*100:+.1f}%")
dd = (peak_eq - min(t['pnl'] for _ in [0])) / peak_eq * 100 if peak_eq > 0 else 0
print(f" Peak Equity:    ${peak_eq:.2f}")
print(f"{'='*55}")
print(f" Exit Breakdown:")
for reason, data in sorted(by_reason.items()):
    wr_r = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
    print(f"   {reason:12s}: {data['count']:3d} trades | WR: {wr_r:.0f}% | P&L: ${data['pnl']:+.2f}")

# Sample trades
print(f"\n Sample trades (last 5):")
for t in trades_list[-5:]:
    print(f"   {'BUY' if t['dir']>0 else 'SELL':4s} {t['reason']:8s} R={t['r']:+.2f} P&L=${t['pnl']:+.2f}")

mt5.shutdown()
