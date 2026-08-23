"""Backtest v17.3 — V10 H1+H4 with Session SL + Early Exit"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import sys
sys.stdout.reconfigure(encoding='utf-8')

mt5.initialize()
end = datetime(2026, 8, 23)
start = end - timedelta(days=90)

rates_h1 = mt5.copy_rates_range('Volatility 10 Index', mt5.TIMEFRAME_H1, start, end)
rates_h4 = mt5.copy_rates_range('Volatility 10 Index', mt5.TIMEFRAME_H4, start, end)
info = mt5.symbol_info('Volatility 10 Index')
point = info.point
tick_val = info.trade_tick_value
tick_size = info.trade_tick_size

n1 = len(rates_h1)
close1 = np.array([r['close'] for r in rates_h1])
high1 = np.array([r['high'] for r in rates_h1])
low1 = np.array([r['low'] for r in rates_h1])
times1 = np.array([r['time'] for r in rates_h1])
n4 = len(rates_h4)
close4 = np.array([r['close'] for r in rates_h4])
times4 = np.array([r['time'] for r in rates_h4])

def ema(data, period):
    result = np.full(len(data), np.nan)
    alpha = 2.0 / (period + 1)
    result[period-1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i-1]
    return result

def calc_atr(high, low, close, period):
    result = np.full(len(close), np.nan)
    tr = np.zeros(len(close))
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    result[period-1] = np.mean(tr[:period])
    alpha = 2.0 / (period + 1)
    for i in range(period, len(close)):
        result[i] = alpha * tr[i] + (1 - alpha) * result[i-1]
    return result

def calc_rsi(close, period):
    result = np.full(len(close), np.nan)
    gains = np.zeros(len(close))
    losses = np.zeros(len(close))
    for i in range(1, len(close)):
        diff = close[i] - close[i-1]
        if diff > 0: gains[i] = diff
        else: losses[i] = -diff
    if len(close) <= period: return result
    avg_g = np.mean(gains[1:period+1])
    avg_l = np.mean(losses[1:period+1])
    if avg_l > 0: result[period] = 100 - 100/(1 + avg_g/avg_l)
    for i in range(period+1, len(close)):
        avg_g = (avg_g * (period-1) + gains[i]) / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
        if avg_l > 0: result[i] = 100 - 100/(1 + avg_g/avg_l)
    return result

atr_h1 = calc_atr(high1, low1, close1, 14)
rsi_h1 = calc_rsi(close1, 14)
ema_fast_h1 = ema(close1, 20)
ema_mid_h1 = ema(close1, 50)
ema_slow_h1 = ema(close1, 100)
ema_fast_4 = ema(close4, 20)
ema_mid_4 = ema(close4, 50)
ema_slow_4 = ema(close4, 100)

# v17.3 parameters
p = {
    'pullback_min': 0.40, 'pullback_max': 2.20,
    'rsi_buy_max': 62.0, 'rsi_sell_min': 38.0,
    'min_ema_sep': 0.25,
    'use_momentum': True, 'mom_lookback': 10, 'mom_min_move': 1.0,
    'mom_rsi_buy': 52.0, 'mom_rsi_sell': 48.0, 'slope_thresh': 0.35,
    'atr_target': 2.5, 'hold_bars': 18,
    'cooldown': 3, 'use_trailing': True,
    'trail_start': 0.9, 'trail_dist': 0.9,
    'use_be': True, 'be_trigger': 1.1,
    'risk_pct': 0.004, 'max_consec_loss': 3,
    'max_daily_loss_pct': 0.025,
    # v17.3 session SL
    'use_session_sl': True, 'sl_quiet': 1.40, 'sl_active': 1.60,
    'quiet_start': 0, 'quiet_end': 7,
    # v17.3 early exit
    'early_exit_hours': 6, 'early_exit_min_r': 0.15,
}

def is_quiet_hour(t):
    """Check if UTC hour is in quiet session"""
    dt = datetime.utcfromtimestamp(t)
    h = dt.hour
    if p['quiet_start'] < p['quiet_end']:
        return p['quiet_start'] <= h < p['quiet_end']
    return h >= p['quiet_start'] or h < p['quiet_end']

def get_h4_regime(h1_time):
    for j in range(n4 - 1, -1, -1):
        if times4[j] <= h1_time:
            if j < 100 or np.isnan(ema_fast_4[j]): return 'RANGING', 0
            p4 = close4[j]
            atr4_val = 1.0
            sep = abs(ema_fast_4[j] - ema_mid_4[j]) / atr4_val
            if ema_fast_4[j] > ema_mid_4[j] > ema_slow_4[j] and p4 > ema_fast_4[j] and sep >= p['min_ema_sep']:
                return 'BULLISH', sep
            elif ema_fast_4[j] < ema_mid_4[j] < ema_slow_4[j] and p4 < ema_fast_4[j] and sep >= p['min_ema_sep']:
                return 'BEARISH', sep
            return 'RANGING', sep
    return 'RANGING', 0

atr_hist = []
atr_lookback = 150

trades = []
equity = 10000.0
peak = equity
consec_loss = 0
cooldown = 0
paused = False
daily_pnl = 0
day_start_idx = 250

for i in range(250, n1 - p['hold_bars'] - 5):
    t = times1[i]
    ds = int(t // 86400)
    if ds != int(times1[day_start_idx] // 86400):
        day_start_idx = i
        daily_pnl = 0
        paused = False
        consec_loss = 0
    if cooldown > 0: cooldown -= 1

    atr_now = atr_h1[i]
    if np.isnan(atr_now) or atr_now <= 0: continue

    atr_hist.append(atr_now)
    if len(atr_hist) > atr_lookback: atr_hist.pop(0)
    if len(atr_hist) < 40: continue

    below = sum(1 for a in atr_hist if atr_now > a)
    pct = below / len(atr_hist) * 100.0
    if pct > 90.0 or pct < 8.0: continue
    if paused or cooldown > 0: continue

    regime, sep = get_h4_regime(t)
    if regime not in ('BULLISH', 'BEARISH'): continue

    emaF = ema_fast_h1[i]
    emaM = ema_mid_h1[i]
    emaS = ema_slow_h1[i]
    rsi_val = rsi_h1[i]
    price = close1[i]

    if np.isnan(emaF) or np.isnan(emaM) or np.isnan(emaS) or np.isnan(rsi_val): continue

    direction = 0
    sig_type = ''
    d = 1 if regime == 'BULLISH' else -1
    pb = abs(price - emaF)
    if p['pullback_min'] * atr_now <= pb <= p['pullback_max'] * atr_now:
        if (d > 0 and price <= emaF + 0.7 * atr_now) or (d < 0 and price >= emaF - 0.7 * atr_now):
            if (d > 0 and rsi_val <= p['rsi_buy_max']) or (d < 0 and rsi_val >= p['rsi_sell_min']):
                if (d > 0 and emaF > emaM > emaS) or (d < 0 and emaF < emaM < emaS):
                    body = price - close1[i-1]
                    if (d > 0 and body >= -0.15 * atr_now) or (d < 0 and body <= 0.15 * atr_now):
                        direction = d
                        sig_type = 'PULLBACK_LONG' if d > 0 else 'PULLBACK_SHORT'

    if direction == 0 and p['use_momentum']:
        mom_dir = 0
        if i >= 6:
            slope = ema_fast_h1[i] - ema_fast_h1[i-6]
            if slope > p['slope_thresh'] * atr_now: mom_dir = 1
            elif slope < -p['slope_thresh'] * atr_now: mom_dir = -1
        if mom_dir != 0 and i >= p['mom_lookback']:
            hh = max(high1[i-p['mom_lookback']:i+1])
            ll = min(low1[i-p['mom_lookback']:i+1])
            move_up = price - ll
            move_dn = hh - price
            body = price - close1[i-1]
            if mom_dir > 0 and move_up > p['mom_min_move'] * atr_now and rsi_val > p['mom_rsi_buy'] and body > 0:
                direction = 1; sig_type = 'MOMENTUM_LONG'
            elif mom_dir < 0 and move_dn > p['mom_min_move'] * atr_now and rsi_val < p['mom_rsi_sell'] and body < 0:
                direction = -1; sig_type = 'MOMENTUM_SHORT'

    if direction == 0: continue

    entry = price
    # Session-specific SL
    stop_mult = p['sl_quiet'] if is_quiet_hour(t) else p['sl_active']
    stop_dist = stop_mult * atr_now
    tp_dist = p['atr_target'] * stop_dist
    max_stop = entry * 0.03
    if stop_dist > max_stop: stop_dist = max_stop
    if stop_dist < atr_now * 0.4: stop_dist = atr_now * 0.4

    sl_p = entry - stop_dist if direction > 0 else entry + stop_dist
    tp_p = entry + tp_dist if direction > 0 else entry - tp_dist

    risk_money = equity * p['risk_pct']
    loss_1lot = (stop_dist / tick_size) * tick_val
    if loss_1lot <= 0: continue
    vol = risk_money / loss_1lot
    vol = max(info.volume_min, round(vol / info.volume_step) * info.volume_step)

    exit_price = None; exit_reason = ''
    sl_moved = sl_p
    for j in range(i+1, min(i+p['hold_bars']+5, n1)):
        # Early exit check
        hours_open = (times1[j] - times1[i]) / 3600.0
        if hours_open >= p['early_exit_hours']:
            cur = close1[j]
            r_now = (cur - entry) / stop_dist if direction > 0 else (entry - cur) / stop_dist
            if r_now < p['early_exit_min_r']:
                exit_price = cur; exit_reason = 'EARLY'; break

        if direction > 0:
            if low1[j] <= sl_moved: exit_price = sl_moved; exit_reason = 'STOP'; break
            if high1[j] >= tp_p: exit_price = tp_p; exit_reason = 'TARGET'; break
            if p['use_be'] and high1[j] >= entry + p['be_trigger'] * atr_now and sl_moved < entry:
                sl_moved = entry + 3*point
            if p['use_trailing'] and high1[j] >= entry + p['trail_start'] * atr_now:
                new_sl = high1[j] - p['trail_dist'] * atr_now
                if new_sl > sl_moved and new_sl > entry: sl_moved = new_sl
        else:
            if high1[j] >= sl_moved: exit_price = sl_moved; exit_reason = 'STOP'; break
            if low1[j] <= tp_p: exit_price = tp_p; exit_reason = 'TARGET'; break
            if p['use_be'] and low1[j] <= entry - p['be_trigger'] * atr_now and sl_moved > entry:
                sl_moved = entry - 3*point
            if p['use_trailing'] and low1[j] <= entry - p['trail_start'] * atr_now:
                new_sl = low1[j] + p['trail_dist'] * atr_now
                if new_sl < sl_moved and new_sl > entry: sl_moved = new_sl
        if j >= i + p['hold_bars']:
            exit_price = close1[j]; exit_reason = 'TIME'; break

    if exit_price is None: continue

    r_mult = (exit_price - entry) / stop_dist if direction > 0 else (entry - exit_price) / stop_dist
    pnl = risk_money * r_mult
    equity += pnl
    if equity > peak: peak = equity
    trades.append({'r': r_mult, 'pnl': pnl, 'reason': exit_reason, 'regime': regime, 'sig': sig_type})

    if r_mult < 0:
        consec_loss += 1; cooldown = p['cooldown']
    else: consec_loss = 0
    if consec_loss >= p['max_consec_loss']: paused = True
    if daily_pnl < -equity * p['max_daily_loss_pct']: paused = True
    daily_pnl += pnl

if trades:
    wins = sum(1 for t in trades if t['r'] > 0)
    total_r = sum(t['r'] for t in trades)
    avg_r = np.mean([t['r'] for t in trades])
    max_dd = (peak - equity) / peak * 100 if peak > 0 else 0
    wr = wins / len(trades) * 100
    pos_pnl = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    neg_pnl = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    pf = pos_pnl / neg_pnl if neg_pnl > 0 else 999
    days = (n1 - 250) / 24
    tpd = len(trades) / days

    print('='*60)
    print('  v17.3 BACKTEST — V10 H1+H4 (90 days)')
    print('='*60)
    print(f'Trades: {len(trades)} ({tpd:.1f}/day)')
    print(f'Win Rate: {wr:.1f}%')
    print(f'Profit Factor: {pf:.2f}')
    print(f'Total R: {total_r:+.1f}R')
    print(f'Avg R: {avg_r:+.3f}')
    print(f'Max Drawdown: {max_dd:.1f}%')
    print(f'Final Equity: ${equity:,.2f}')

    print()
    print('Signal Breakdown:')
    sigs = {}
    for t in trades:
        s = t['sig']
        if s not in sigs: sigs[s] = {'n': 0, 'w': 0, 'r': 0}
        sigs[s]['n'] += 1; sigs[s]['r'] += t['r']
        if t['r'] > 0: sigs[s]['w'] += 1
    for s, v in sorted(sigs.items()):
        wr_s = v['w']/v['n']*100 if v['n'] > 0 else 0
        print(f'  {s:20s}: {v["n"]:4d} trades | WR {wr_s:.0f}% | R={v["r"]:+.1f}')

    print()
    print('Exit Reasons:')
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = 0
        reasons[r] += 1
    for r, c in sorted(reasons.items()):
        print(f'  {r:10s}: {c} ({c/len(trades)*100:.0f}%)')

    print()
    print('Regime Breakdown:')
    regimes = {}
    for t in trades:
        rg = t['regime']
        if rg not in regimes: regimes[rg] = {'n': 0, 'r': 0}
        regimes[rg]['n'] += 1; regimes[rg]['r'] += t['r']
    for rg, v in sorted(regimes.items()):
        print(f'  {rg:10s}: {v["n"]} trades | R={v["r"]:+.1f}')
else:
    print('No trades generated')

mt5.shutdown()
