"""Walk-Forward Validation for V10 H1+H4"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
from collections import Counter
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

def get_h4_regime(h1_time):
    for j in range(n4 - 1, -1, -1):
        if times4[j] <= h1_time:
            if j < 100 or np.isnan(ema_fast_4[j]): return 'RANGING'
            p4 = close4[j]
            if ema_fast_4[j] > ema_mid_4[j] > ema_slow_4[j] and p4 > ema_fast_4[j]: return 'BULLISH'
            elif ema_fast_4[j] < ema_mid_4[j] < ema_slow_4[j] and p4 < ema_fast_4[j]: return 'BEARISH'
            return 'RANGING'
    return 'RANGING'

def run_backtest(p, start_bar, end_bar):
    trades = []
    equity = 10000
    peak = equity
    consec_loss = 0
    cooldown = 0
    paused = False
    daily_pnl = 0
    day_start = times1[start_bar]

    i = start_bar
    while i < end_bar - 1:
        t = times1[i]
        ds = t - (t % 86400)
        if ds != day_start:
            day_start = ds; daily_pnl = 0; paused = False; consec_loss = 0
        if cooldown > 0: cooldown -= 1

        atr_now = atr_h1[i]
        if np.isnan(atr_now) or atr_now <= 0: i += 1; continue
        if paused or cooldown > 0: i += 1; continue

        regime = get_h4_regime(t)
        direction = 0
        sig_type = ''

        # PULLBACK
        if direction == 0 and regime in ('BULLISH', 'BEARISH'):
            d = 1 if regime == 'BULLISH' else -1
            pb = abs(close1[i-1] - ema_fast_h1[i-1])
            rsi_val = rsi_h1[i-1]
            atr_val = atr_h1[i-1]
            if not np.isnan(pb) and not np.isnan(atr_val) and atr_val > 0 and not np.isnan(rsi_val):
                if p['pullback_min'] * atr_val <= pb <= p['pullback_max'] * atr_val:
                    if (d > 0 and rsi_val <= p['rsi_buy_max']) or (d < 0 and rsi_val >= p['rsi_sell_min']):
                        if not np.isnan(ema_fast_h1[i]) and not np.isnan(ema_mid_h1[i]):
                            if d > 0 and ema_fast_h1[i] > ema_mid_h1[i]:
                                direction = d; sig_type = 'PULLBACK_LONG'
                            elif d < 0 and ema_fast_h1[i] < ema_mid_h1[i]:
                                direction = d; sig_type = 'PULLBACK_SHORT'

        # MOMENTUM
        if direction == 0 and p['use_momentum']:
            mom_dir = 0
            if regime == 'BULLISH': mom_dir = 1
            elif regime == 'BEARISH': mom_dir = -1
            elif regime == 'RANGING' and i >= 5:
                if not np.isnan(ema_fast_h1[i]) and not np.isnan(ema_fast_h1[i-5]):
                    eslope = ema_fast_h1[i] - ema_fast_h1[i-5]
                    if eslope > p['slope_thresh'] * atr_h1[i]: mom_dir = 1
                    elif eslope < -p['slope_thresh'] * atr_h1[i]: mom_dir = -1

            if mom_dir != 0 and i >= p['mom_lookback']:
                lb = p['mom_lookback']
                sh = np.max(high1[i-lb:i+1])
                sl_val = np.min(low1[i-lb:i+1])
                move_up = close1[i] - sl_val
                move_down = sh - close1[i]
                body = close1[i] - close1[i-1]
                rsi_val = rsi_h1[i]
                if not np.isnan(rsi_val):
                    if mom_dir > 0 and move_up > p['mom_min_move'] * atr_h1[i]:
                        if rsi_val > p['mom_rsi_buy'] and rsi_val < 72 and body > 0:
                            direction = 1; sig_type = 'MOMENTUM_LONG'
                    if mom_dir < 0 and move_down > p['mom_min_move'] * atr_h1[i]:
                        if rsi_val < p['mom_rsi_sell'] and rsi_val > 28 and body < 0:
                            direction = -1; sig_type = 'MOMENTUM_SHORT'

        if direction == 0: i += 1; continue

        entry = close1[i]
        stop_dist = p['atr_stop'] * atr_h1[i]
        tp_dist = p['atr_target'] * stop_dist
        max_stop = entry * 0.025
        if stop_dist > max_stop: stop_dist = max_stop
        if stop_dist < atr_h1[i] * 0.3: stop_dist = atr_h1[i] * 0.3
        sl_p = entry - stop_dist if direction > 0 else entry + stop_dist
        tp_p = entry + tp_dist if direction > 0 else entry - tp_dist

        loss_1lot = (stop_dist / tick_size) * tick_val
        if loss_1lot <= 0: i += 1; continue
        risk_money = equity * p['risk_pct']
        vol = risk_money / loss_1lot
        vol = max(info.volume_min, round(vol / info.volume_step) * info.volume_step)

        exit_price = None; exit_reason = ''; bars = 0
        sl_moved = sl_p; tp_moved = tp_p

        for j in range(i+1, min(i+p['hold_bars']+5, end_bar)):
            bars += 1
            if direction > 0:
                if low1[j] <= sl_moved: exit_price = sl_moved; exit_reason = 'STOP'; break
                if high1[j] >= tp_moved: exit_price = tp_moved; exit_reason = 'TARGET'; break
                if p['use_be']:
                    if high1[j] >= entry + p['be_trigger'] * atr_h1[i] and sl_moved < entry:
                        sl_moved = entry + 2 * point
                if p['use_trailing']:
                    if high1[j] >= entry + p['trail_start'] * atr_h1[i]:
                        new_sl = high1[j] - p['trail_dist'] * atr_h1[i]
                        if new_sl > sl_moved and new_sl > entry: sl_moved = new_sl
            else:
                if high1[j] >= sl_moved: exit_price = sl_moved; exit_reason = 'STOP'; break
                if low1[j] <= tp_moved: exit_price = tp_moved; exit_reason = 'TARGET'; break
                if p['use_be']:
                    if low1[j] <= entry - p['be_trigger'] * atr_h1[i] and sl_moved > entry:
                        sl_moved = entry - 2 * point
                if p['use_trailing']:
                    if low1[j] <= entry - p['trail_start'] * atr_h1[i]:
                        new_sl = low1[j] + p['trail_dist'] * atr_h1[i]
                        if new_sl < sl_moved and new_sl < entry: sl_moved = new_sl
            if bars >= p['hold_bars']:
                exit_price = close1[j]; exit_reason = 'TIME'; break

        if exit_price is None: i += 1; continue

        r_mult = (exit_price - entry) / stop_dist if direction > 0 else (entry - exit_price) / stop_dist
        pnl = risk_money * r_mult
        equity += pnl
        if equity > peak: peak = equity
        trades.append({'r_mult': r_mult, 'pnl': pnl, 'reason': exit_reason, 'regime': regime, 'sig_type': sig_type})

        if r_mult < 0: consec_loss += 1; cooldown = p['cooldown']
        else: consec_loss = 0
        if consec_loss >= p['max_consec_loss']: paused = True
        if daily_pnl < -equity * p['max_daily_loss_pct']: paused = True
        daily_pnl += pnl
        i += 1

    if not trades: return None

    wins = sum(1 for t in trades if t['r_mult'] > 0)
    total_r = sum(t['r_mult'] for t in trades)
    avg_r = np.mean([t['r_mult'] for t in trades])
    max_dd = (peak - equity) / peak * 100 if peak > 0 else 0
    wr = wins / len(trades) * 100
    pos_pnl = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    neg_pnl = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    pf = pos_pnl / neg_pnl if neg_pnl > 0 else 999
    days = (end_bar - start_bar) / 24
    tpd = len(trades) / days if days > 0 else 0

    return {
        'trades': len(trades), 'tpd': tpd, 'wr': wr, 'pf': pf,
        'total_r': total_r, 'avg_r': avg_r, 'max_dd': max_dd,
        'equity': equity,
    }

# Target config: ~4-5 trades/day with good quality
p = {
    'trend_only': False, 'use_momentum': True,
    'pullback_min': 0.10, 'pullback_max': 2.5, 'rsi_buy_max': 68, 'rsi_sell_min': 32,
    'require_ema_align': True,
    'mom_lookback': 12, 'mom_min_move': 0.8, 'mom_rsi_buy': 38, 'mom_rsi_sell': 62,
    'slope_thresh': 0.3,  # Higher slope = fewer RANGING trades
    'atr_stop': 1.5, 'atr_target': 2.0, 'hold_bars': 24, 'cooldown': 3,
    'use_trailing': True, 'trail_start': 1.0, 'trail_dist': 1.2,
    'use_be': True, 'be_trigger': 2.0, 'risk_pct': 0.004,
    'max_consec_loss': 3, 'max_daily_loss_pct': 0.025,
}

# Split: first 60 days train, last 30 days test
train_end = 200 + 60 * 24  # 60 days of H1 bars

print('='*70)
print('  WALK-FORWARD VALIDATION — V10 H1+H4')
print('='*70)
print()

# Train period
print('--- TRAINING PERIOD (first 60 days) ---')
train_result = run_backtest(p, 200, train_end)
if train_result:
    print(f'Trades: {train_result["trades"]} ({train_result["tpd"]:.1f}/day)')
    print(f'Win Rate: {train_result["wr"]:.1f}%')
    print(f'Profit Factor: {train_result["pf"]:.2f}')
    print(f'Total R: {train_result["total_r"]:+.1f}R')
    print(f'Max Drawdown: {train_result["max_dd"]:.1f}%')
else:
    print('No trades in training period')

print()

# Test period (out-of-sample)
print('--- TEST PERIOD (last 30 days, out-of-sample) ---')
test_result = run_backtest(p, train_end, n1)
if test_result:
    print(f'Trades: {test_result["trades"]} ({test_result["tpd"]:.1f}/day)')
    print(f'Win Rate: {test_result["wr"]:.1f}%')
    print(f'Profit Factor: {test_result["pf"]:.2f}')
    print(f'Total R: {test_result["total_r"]:+.1f}R')
    print(f'Max Drawdown: {test_result["max_dd"]:.1f}%')
else:
    print('No trades in test period')

print()

# Full period
print('--- FULL PERIOD (90 days) ---')
full_result = run_backtest(p, 200, n1)
if full_result:
    print(f'Trades: {full_result["trades"]} ({full_result["tpd"]:.1f}/day)')
    print(f'Win Rate: {full_result["wr"]:.1f}%')
    print(f'Profit Factor: {full_result["pf"]:.2f}')
    print(f'Total R: {full_result["total_r"]:+.1f}R')
    print(f'Max Drawdown: {full_result["max_dd"]:.1f}%')

print()

# Consistency check
if train_result and test_result:
    print('--- CONSISTENCY CHECK ---')
    train_tpd = train_result['tpd']
    test_tpd = test_result['tpd']
    train_wr = train_result['wr']
    test_wr = test_result['wr']
    train_pf = train_result['pf']
    test_pf = test_result['pf']
    
    print(f'Trades/day: Train={train_tpd:.1f} | Test={test_tpd:.1f} | Ratio={test_tpd/train_tpd:.2f}x')
    print(f'Win Rate:   Train={train_wr:.1f}% | Test={test_wr:.1f}% | Diff={test_wr-train_wr:+.1f}%')
    print(f'PF:         Train={train_pf:.2f} | Test={test_pf:.2f}')
    
    # Verdict
    if test_tpd > 0 and test_result['total_r'] > 0:
        print(f'\n✅ PASSED: Out-of-sample is profitable ({test_result["total_r"]:+.1f}R)')
        if test_wr >= train_wr * 0.8:
            print(f'✅ Win rate stable ({test_wr:.1f}% vs {train_wr:.1f}% train)')
        else:
            print(f'⚠️ Win rate dropped ({test_wr:.1f}% vs {train_wr:.1f}% train)')
    else:
        print(f'\n❌ FAILED: Out-of-sample not profitable')

mt5.shutdown()
