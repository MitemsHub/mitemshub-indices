"""v17.3 FIXED Backtest — Correct PnL with actual volume"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta, timezone
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
min_vol = info.volume_min
vol_step = info.volume_step
max_vol = info.volume_max

# V10: tick_value=0.001, tick_size=0.001, point=0.001
# Dollar per point per lot = tick_val/tick_size * point = 1.0
# At 0.50 lots: $0.50 per point
dollar_per_point_per_lot = tick_val / tick_size * point
print(f"V10: tick_val={tick_val}, tick_size={tick_size}, point={point}")
print(f"Dollar per point per lot: ${dollar_per_point_per_lot:.4f}")
print(f"Min volume: {min_vol} lots → ${dollar_per_point_per_lot * min_vol:.2f}/point")
print()

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
    'max_consec_loss': 3, 'max_daily_loss_pct': 0.10,  # 10% daily loss limit
    'use_session_sl': True, 'sl_quiet': 1.40, 'sl_active': 1.60,
    'quiet_start': 0, 'quiet_end': 7,
    'early_exit_hours': 6, 'early_exit_min_r': 0.15,
}

def is_quiet_hour(t):
    dt = datetime.fromtimestamp(t, tz=timezone.utc)
    h = dt.hour
    if p['quiet_start'] < p['quiet_end']:
        return p['quiet_start'] <= h < p['quiet_end']
    return h >= p['quiet_start'] or h < p['quiet_end']

def get_h4_regime(h1_time):
    for j in range(n4 - 1, -1, -1):
        if times4[j] <= h1_time:
            if j < 100 or np.isnan(ema_fast_4[j]): return 'RANGING', 0
            p4 = close4[j]
            sep = abs(ema_fast_4[j] - ema_mid_4[j])
            if ema_fast_4[j] > ema_mid_4[j] > ema_slow_4[j] and p4 > ema_fast_4[j] and sep >= p['min_ema_sep']:
                return 'BULLISH', sep
            elif ema_fast_4[j] < ema_mid_4[j] < ema_slow_4[j] and p4 < ema_fast_4[j] and sep >= p['min_ema_sep']:
                return 'BEARISH', sep
            return 'RANGING', sep
    return 'RANGING', 0

atr_hist = []

STARTING_EQUITY = 22.75
trades = []
equity = STARTING_EQUITY
peak = equity
consec_loss = 0
cooldown = 0
paused = False
daily_pnl = 0
day_start_idx = 250
trade_log = []

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
    if len(atr_hist) > 150: atr_hist.pop(0)
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
    stop_mult = p['sl_quiet'] if is_quiet_hour(t) else p['sl_active']
    stop_dist = stop_mult * atr_now
    tp_dist = p['atr_target'] * stop_dist
    max_stop = entry * 0.03
    if stop_dist > max_stop: stop_dist = max_stop
    if stop_dist < atr_now * 0.4: stop_dist = atr_now * 0.4

    sl_p = entry - stop_dist if direction > 0 else entry + stop_dist
    tp_p = entry + tp_dist if direction > 0 else entry - tp_dist

    # Volume: use minimum volume (0.50 lots) since equity is small
    vol = min_vol

    # Actual dollar risk per trade
    actual_risk_dollar = vol * stop_dist * dollar_per_point_per_lot

    exit_price = None; exit_reason = ''
    sl_moved = sl_p
    exit_bar = i
    for j in range(i+1, min(i+p['hold_bars']+5, n1)):
        hours_open = (times1[j] - times1[i]) / 3600.0
        if hours_open >= p['early_exit_hours']:
            cur = close1[j]
            r_now = (cur - entry) / stop_dist if direction > 0 else (entry - cur) / stop_dist
            if r_now < p['early_exit_min_r']:
                exit_price = cur; exit_reason = 'EARLY'; exit_bar = j; break

        if direction > 0:
            if low1[j] <= sl_moved: exit_price = sl_moved; exit_reason = 'STOP'; exit_bar = j; break
            if high1[j] >= tp_p: exit_price = tp_p; exit_reason = 'TARGET'; exit_bar = j; break
            if p['use_be'] and high1[j] >= entry + p['be_trigger'] * atr_now and sl_moved < entry:
                sl_moved = entry + 3*point
            if p['use_trailing'] and high1[j] >= entry + p['trail_start'] * atr_now:
                new_sl = high1[j] - p['trail_dist'] * atr_now
                if new_sl > sl_moved and new_sl > entry: sl_moved = new_sl
        else:
            if high1[j] >= sl_moved: exit_price = sl_moved; exit_reason = 'STOP'; exit_bar = j; break
            if low1[j] <= tp_p: exit_price = tp_p; exit_reason = 'TARGET'; exit_bar = j; break
            if p['use_be'] and low1[j] <= entry - p['be_trigger'] * atr_now and sl_moved > entry:
                sl_moved = entry - 3*point
            if p['use_trailing'] and low1[j] <= entry - p['trail_start'] * atr_now:
                new_sl = low1[j] + p['trail_dist'] * atr_now
                if new_sl < sl_moved and new_sl > entry: sl_moved = new_sl
        if j >= i + p['hold_bars']:
            exit_price = close1[j]; exit_reason = 'TIME'; exit_bar = j; break

    if exit_price is None: continue

    # CORRECT PnL calculation using actual volume
    price_move = (exit_price - entry) * direction
    pnl = price_move * vol * dollar_per_point_per_lot
    r_mult = price_move / stop_dist

    equity += pnl
    if equity > peak: peak = equity

    entry_dt = datetime.fromtimestamp(times1[i], tz=timezone.utc)
    exit_dt = datetime.fromtimestamp(times1[exit_bar], tz=timezone.utc)
    hold_hrs = (times1[exit_bar] - times1[i]) / 3600.0

    trades.append({
        'r': r_mult, 'pnl': pnl, 'reason': exit_reason, 'regime': regime, 'sig': sig_type,
        'entry': entry, 'exit': exit_price, 'vol': vol, 'eq_after': equity,
        'entry_time': entry_dt, 'exit_time': exit_dt, 'hold_hrs': hold_hrs,
        'risk_dollar': actual_risk_dollar
    })
    trade_log.append(f"  #{len(trades):3d} {entry_dt.strftime('%m-%d %H:%M')} {sig_type:18s} {'BUY' if direction>0 else 'SELL'} @ {entry:.2f} → {exit_price:.2f} | {exit_reason:6s} | R={r_mult:+.3f} | PnL=${pnl:+.2f} | Eq=${equity:.2f}")

    if r_mult < 0:
        consec_loss += 1; cooldown = p['cooldown']
    else: consec_loss = 0
    if consec_loss >= p['max_consec_loss']: paused = True
    if daily_pnl < -equity * p['max_daily_loss_pct']: paused = True
    daily_pnl += pnl

# ============ RESULTS ============
print('='*80)
print('  v17.3 FIXED BACKTEST — Volatility 10 Index — H1 Entry + H4 Regime')
print(f'  Period: {start.strftime("%Y-%m-%d")} → {end.strftime("%Y-%m-%d")} (90 days)')
print(f'  Starting Equity: ${STARTING_EQUITY:.2f}')
print(f'  Volume: {min_vol} lots (minimum — fixed for small account)')
print('='*80)
print()

if trades:
    wins = sum(1 for t in trades if t['r'] > 0)
    total_r = sum(t['r'] for t in trades)
    avg_r = np.mean([t['r'] for t in trades])
    max_eq = max(t['eq_after'] for t in trades)
    min_eq = min(t['eq_after'] for t in trades)
    max_dd = (peak - min_eq) / peak * 100 if peak > 0 else 0
    max_dd_dollar = peak - min_eq
    wr = wins / len(trades) * 100
    pos_pnl = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    neg_pnl = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    pf = pos_pnl / neg_pnl if neg_pnl > 0 else 999
    days = (n1 - 250) / 24
    tpd = len(trades) / days
    net_pnl = equity - STARTING_EQUITY
    roi = net_pnl / STARTING_EQUITY * 100
    avg_trade = net_pnl / len(trades)
    avg_win = pos_pnl / wins if wins > 0 else 0
    avg_loss = neg_pnl / (len(trades) - wins) if (len(trades) - wins) > 0 else 0

    print(f'  Total Trades:     {len(trades)} ({tpd:.1f}/day)')
    print(f'  Win Rate:         {wr:.1f}% ({wins}W / {len(trades)-wins}L)')
    print(f'  Profit Factor:    {pf:.2f}')
    print(f'  Total R:          {total_r:+.1f}R')
    print(f'  Avg R/Trade:      {avg_r:+.3f}R')
    print()
    print(f'  ── Dollar Performance ──')
    print(f'  Net P&L:          ${net_pnl:+.2f}')
    print(f'  ROI:              {roi:+.1f}%')
    print(f'  Avg Win:          ${avg_win:+.2f}')
    print(f'  Avg Loss:         ${avg_loss:+.2f}')
    print(f'  Avg Trade:        ${avg_trade:+.2f}')
    print(f'  Risk/Trade:       ${trades[0]["risk_dollar"]:.2f}')
    print()
    print(f'  ── Equity ──')
    print(f'  Starting:         ${STARTING_EQUITY:.2f}')
    print(f'  Peak:             ${peak:.2f}')
    print(f'  Final:            ${equity:.2f}')
    print(f'  Max Drawdown:     ${max_dd_dollar:.2f} ({max_dd:.1f}%)')

    print()
    print('  ── Signal Breakdown ──')
    sigs = {}
    for t in trades:
        s = t['sig']
        if s not in sigs: sigs[s] = {'n': 0, 'w': 0, 'r': 0, 'pnl': 0}
        sigs[s]['n'] += 1; sigs[s]['r'] += t['r']; sigs[s]['pnl'] += t['pnl']
        if t['r'] > 0: sigs[s]['w'] += 1
    for s, v in sorted(sigs.items()):
        wr_s = v['w']/v['n']*100 if v['n'] > 0 else 0
        print(f'    {s:20s}: {v["n"]:3d} trades | WR {wr_s:5.1f}% | R={v["r"]:+6.1f} | PnL=${v["pnl"]:+7.2f}')

    print()
    print('  ── Exit Reasons ──')
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = {'n': 0, 'pnl': 0}
        reasons[r]['n'] += 1; reasons[r]['pnl'] += t['pnl']
    for r, v in sorted(reasons.items()):
        print(f'    {r:10s}: {v["n"]:3d} ({v["n"]/len(trades)*100:4.1f}%) | PnL=${v["pnl"]:+7.2f}')

    # Forward projection
    print()
    print('='*80)
    print('  FORWARD TEST PROJECTION')
    print('='*80)
    print()
    avg_daily_pnl = net_pnl / days
    avg_monthly_pnl = avg_daily_pnl * 30

    print(f'  Based on {days:.0f}-day backtest:')
    print(f'    Avg trades/day:  {tpd:.1f}')
    print(f'    Avg P&L/day:     ${avg_daily_pnl:+.2f}')
    print(f'    Avg P&L/month:   ${avg_monthly_pnl:+.2f}')
    print(f'    Current equity:  ${equity:.2f}')
    print()

    # 12-month compounding projection
    sim_eq = equity
    print('  Monthly Compounding Projection:')
    for month in range(1, 13):
        monthly_return = avg_monthly_pnl * (sim_eq / STARTING_EQUITY)
        sim_eq += monthly_return
        if month in [1, 2, 3, 6, 9, 12]:
            print(f'    Month {month:2d}: ${sim_eq:8.2f} (total ROI: {(sim_eq-STARTING_EQUITY)/STARTING_EQUITY*100:+.0f}%)')

    print()
    print(f'  Projected 12-month equity: ${sim_eq:.2f}')
    print(f'  Projected 12-month ROI:    {(sim_eq-STARTING_EQUITY)/STARTING_EQUITY*100:+.0f}%')
else:
    print('  No trades generated')

print()
print('='*80)
mt5.shutdown()
