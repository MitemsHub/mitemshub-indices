"""
v15 Long-Period Validation: Full 7-month history + 45-day forward test.
Uses ENTIRE available data (Jan 12 – Aug 23, 2026).
Walk-forward: train on first ~190 days, validate last 45 days pure OOS.
"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import json, sys

sys.stdout.reconfigure(encoding='utf-8')

SYMBOLS = {
    'Volatility 75 Index': {
        'point': 0.01, 'digits': 2, 'tick_val': 0.0001, 'tick_size': 0.01,
        'spread_pts': 1656, 'min_lot': 0.01, 'step': 0.001,
    },
    'Volatility 100 Index': {
        'point': 0.01, 'digits': 2, 'tick_val': 0.0001, 'tick_size': 0.01,
        'spread_pts': 26, 'min_lot': 0.01, 'step': 0.001,
    },
}

OPT_V75 = {
    'ema_fast': 20, 'ema_mid': 50, 'ema_slow': 100,
    'pullback_min': 0.25, 'pullback_max': 1.8,
    'rsi_period': 14, 'rsi_buy_max': 58, 'rsi_sell_min': 42,
    'atr_period': 14, 'atr_lookback': 200,
    'atr_low_pct': 12, 'atr_high_pct': 88,
    'compress_bars': 18, 'compress_atr_mult': 0.65, 'breakout_min': 0.12,
    'risk_pct': 0.005, 'atr_stop': 2.0, 'atr_target': 2.8,
    'hold_bars': 14, 'cooldown': 4, 'max_consec_loss': 3,
    'use_trailing': True, 'trail_start': 0.8, 'trail_dist': 0.7,
    'use_be': True, 'be_trigger': 1.0,
}

OPT_V100 = {
    'ema_fast': 20, 'ema_mid': 50, 'ema_slow': 100,
    'pullback_min': 0.30, 'pullback_max': 2.0,
    'rsi_period': 14, 'rsi_buy_max': 56, 'rsi_sell_min': 44,
    'atr_period': 14, 'atr_lookback': 200,
    'atr_low_pct': 12, 'atr_high_pct': 88,
    'compress_bars': 18, 'compress_atr_mult': 0.65, 'breakout_min': 0.12,
    'risk_pct': 0.003, 'atr_stop': 1.8, 'atr_target': 2.8,
    'hold_bars': 14, 'cooldown': 4, 'max_consec_loss': 3,
    'use_trailing': True, 'trail_start': 0.8, 'trail_dist': 0.7,
    'use_be': True, 'be_trigger': 1.2,
}


def ema(data, period):
    result = np.full(len(data), np.nan)
    if len(data) < period: return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result

def rsi(close, period):
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    if len(close) < period + 1: return avg_gain
    avg_gain[period] = np.mean(gain[1:period + 1])
    avg_loss[period] = np.mean(loss[1:period + 1])
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    return 100.0 - 100.0 / (1.0 + rs)

def atr(high, low, close, period):
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    result = np.full(len(close), np.nan)
    if len(close) < period: return result
    result[period - 1] = np.mean(tr[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(close)):
        result[i] = tr[i] * k + result[i - 1] * (1 - k)
    return result

def calc_atr_percentile(current, atr_history, lookback=200):
    valid = atr_history[~np.isnan(atr_history)]
    if len(valid) < 50: return 50.0
    recent = valid[-min(lookback, len(valid)):]
    return float(np.sum(current > recent) / len(recent) * 100.0)


def run_backtest(m5_data, m15_data, specs, params, start_idx=250):
    close5 = m5_data['close']
    high5 = m5_data['high']
    low5 = m5_data['low']
    close15 = m15_data['close']
    p = params

    ema_fast_15 = ema(close15, p['ema_fast'])
    ema_mid_15 = ema(close15, p['ema_mid'])
    ema_slow_15 = ema(close15, p['ema_slow'])
    ema_fast_5 = ema(close5, p['ema_fast'])
    rsi_5 = rsi(close5, p['rsi_period'])
    atr_5 = atr(high5, low5, close5, p['atr_period'])
    m5_to_m15 = np.arange(len(close5)) // 3

    trades = []
    equity = 10000.0
    peak_equity = equity
    cooldown = 0
    consec_loss = 0
    paused = False
    daily_pnl = 0.0
    day_start_bar = 0
    atr_hist = []
    in_position = False
    pos_dir = 0
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_orig_risk = 0.0
    pos_stake = 0.0
    pos_bars = 0
    pos_regime = ''
    pos_sig = ''

    for i in range(start_idx, len(close5)):
        if np.isnan(atr_5[i]) or np.isnan(ema_fast_5[i]) or np.isnan(rsi_5[i]):
            continue
        m15_idx = min(m5_to_m15[i], len(close15) - 1)
        if m15_idx < 1 or np.isnan(ema_fast_15[m15_idx]):
            continue

        bars_per_day = 288
        if (i - day_start_bar) >= bars_per_day:
            daily_pnl = 0.0
            day_start_bar = i

        if cooldown > 0:
            cooldown -= 1

        atr_hist.append(atr_5[i])
        if len(atr_hist) > p['atr_lookback'] + 50:
            atr_hist = atr_hist[-(p['atr_lookback'] + 50):]
        atr_pct = calc_atr_percentile(atr_5[i], np.array(atr_hist), p['atr_lookback'])

        if in_position:
            pos_bars += 1
            bid = close5[i]
            closed = False
            exit_price = 0.0

            if pos_dir > 0:
                if bid <= pos_sl: closed, exit_price = True, pos_sl
                elif bid >= pos_tp: closed, exit_price = True, pos_tp
            else:
                if bid >= pos_sl: closed, exit_price = True, pos_sl
                elif bid <= pos_tp: closed, exit_price = True, pos_tp

            if not closed and pos_bars >= p['hold_bars']:
                closed, exit_price = True, close5[i]

            if not closed and p['use_be']:
                be = p['be_trigger'] * atr_5[i]
                if pos_dir > 0 and bid >= pos_entry + be and pos_sl < pos_entry:
                    pos_sl = pos_entry + 2 * specs['point']
                elif pos_dir < 0 and bid <= pos_entry - be and pos_sl > pos_entry:
                    pos_sl = pos_entry - 2 * specs['point']

            if not closed and p['use_trailing']:
                ts = p['trail_start'] * atr_5[i]
                td = p['trail_dist'] * atr_5[i]
                if pos_dir > 0 and bid >= pos_entry + ts:
                    ns = bid - td
                    if ns > pos_sl and ns > pos_entry: pos_sl = ns
                elif pos_dir < 0 and bid <= pos_entry - ts:
                    ns = bid + td
                    if ns < pos_sl and ns < pos_entry: pos_sl = ns

            if closed:
                r = (exit_price - pos_entry) / pos_orig_risk if pos_dir > 0 else (pos_entry - exit_price) / pos_orig_risk
                pnl = pos_stake * r
                equity += pnl
                daily_pnl += pnl
                if equity > peak_equity: peak_equity = equity
                trades.append({
                    'entry': pos_entry, 'exit': exit_price, 'dir': pos_dir,
                    'reason': 'STOP' if r < 0 else 'TARGET' if abs(r) > 1.5 else 'TIME',
                    'r_mult': r, 'pnl': pnl, 'bars': pos_bars, 'equity': equity,
                    'atr_pct': atr_pct, 'regime': pos_regime, 'signal_type': pos_sig,
                })
                if r < 0:
                    consec_loss += 1
                    cooldown = p['cooldown']
                else:
                    consec_loss = 0
                if consec_loss >= p['max_consec_loss']: paused = True
                if daily_pnl < -equity * 0.025: paused = True
                if (peak_equity - equity) > peak_equity * 0.12: paused = True
                in_position = False
            continue

        if paused or cooldown > 0: continue
        if atr_pct < p['atr_low_pct'] or atr_pct > p['atr_high_pct']: continue
        if np.isnan(ema_mid_15[m15_idx]) or np.isnan(ema_slow_15[m15_idx]): continue

        regime = 'RANGING'
        m15_close = close15[m15_idx]
        ef, em, es = ema_fast_15[m15_idx], ema_mid_15[m15_idx], ema_slow_15[m15_idx]
        if ef > em > es and m15_close > ef: regime = 'BULLISH'
        elif ef < em < es and m15_close < ef: regime = 'BEARISH'

        direction = 0
        sig_type = ''

        if regime in ('BULLISH', 'BEARISH'):
            direction = 1 if regime == 'BULLISH' else -1
            pb = abs(close5[i] - ema_fast_5[i])
            if pb < p['pullback_min'] * atr_5[i] or pb > p['pullback_max'] * atr_5[i]: continue
            if direction > 0 and close5[i] > ema_fast_5[i] + 0.6 * atr_5[i]: continue
            if direction < 0 and close5[i] < ema_fast_5[i] - 0.6 * atr_5[i]: continue
            if direction > 0 and rsi_5[i] > p['rsi_buy_max']: continue
            if direction < 0 and rsi_5[i] < p['rsi_sell_min']: continue
            body = close5[i] - close5[i - 1]
            if direction > 0 and body <= 0: continue
            if direction < 0 and body >= 0: continue
            if abs(body) > atr_5[i] * 0.7: continue
            sig_type = 'PULLBACK_LONG' if direction > 0 else 'PULLBACK_SHORT'

        elif regime == 'RANGING':
            atr_now = atr_5[i]
            start_a = max(0, i - 100)
            avg_atr = np.mean(atr_5[start_a:i])
            if atr_now > avg_atr * p['compress_atr_mult']: continue
            cs = max(0, i - p['compress_bars'])
            rh = np.max(high5[cs:i + 1])
            rng = rh - np.min(low5[cs:i + 1])
            if rng < atr_now * 0.4: continue
            cl = close5[i]
            rl = np.min(low5[cs:i + 1])
            if cl > rh + p['breakout_min'] * atr_now: direction = 1
            elif cl < rl - p['breakout_min'] * atr_now: direction = -1
            else: continue
            if high5[i] - low5[i] > atr_now * 2.2: continue
            if direction > 0 and rsi_5[i] < 52: continue
            if direction < 0 and rsi_5[i] > 48: continue
            sig_type = 'BREAKOUT_UP' if direction > 0 else 'BREAKOUT_DOWN'
        else:
            continue

        entry = close5[i]
        stop_dist = p['atr_stop'] * atr_5[i]
        tp_dist = p['atr_target'] * atr_5[i]
        max_stop = entry * 0.025
        if stop_dist > max_stop: stop_dist = max_stop
        if stop_dist < atr_5[i] * 0.5: stop_dist = atr_5[i] * 0.5
        risk_money = equity * p['risk_pct']
        risk_points = stop_dist / specs['point']
        vol = risk_money / (risk_points * (specs['tick_val'] / (specs['tick_size'] / specs['point'])))
        vol = max(specs['min_lot'], round(vol / specs['step']) * specs['step'])

        in_position = True
        pos_dir = direction
        pos_entry = entry
        pos_sl = entry - stop_dist if direction > 0 else entry + stop_dist
        pos_tp = entry + tp_dist if direction > 0 else entry - tp_dist
        pos_orig_risk = stop_dist
        pos_stake = risk_money
        pos_bars = 0
        pos_regime = regime
        pos_sig = sig_type

    return trades


def analyze(trades, name):
    if not trades:
        return {'name': name, 'trades': 0, 'error': 'No trades'}
    wins = [t for t in trades if t['r_mult'] > 0]
    losses = [t for t in trades if t['r_mult'] <= 0]
    pnl = sum(t['pnl'] for t in trades)
    gross_win = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0
    equities = [10000] + [t['equity'] for t in trades]
    peaks = np.maximum.accumulate(equities)
    dd = (peaks - equities) / peaks * 100
    max_dd = float(np.max(dd))

    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = {'count': 0, 'wins': 0, 'pnl': 0}
        reasons[r]['count'] += 1
        if t['r_mult'] > 0: reasons[r]['wins'] += 1
        reasons[r]['pnl'] += t['pnl']

    regimes = {}
    for t in trades:
        r = t.get('regime', '?')
        if r not in regimes: regimes[r] = {'count': 0, 'wins': 0, 'pnl': 0}
        regimes[r]['count'] += 1
        if t['r_mult'] > 0: regimes[r]['wins'] += 1
        regimes[r]['pnl'] += t['pnl']

    signals = {}
    for t in trades:
        s = t.get('signal_type', '?')
        if s not in signals: signals[s] = {'count': 0, 'wins': 0, 'pnl': 0}
        signals[s]['count'] += 1
        if t['r_mult'] > 0: signals[s]['wins'] += 1
        signals[s]['pnl'] += t['pnl']

    return {
        'name': name,
        'trades': len(trades),
        'wins': len(wins),
        'win_rate': len(wins) / len(trades) * 100,
        'pnl': pnl,
        'pnl_pct': pnl / 10000 * 100,
        'profit_factor': pf,
        'avg_win_r': float(np.mean([t['r_mult'] for t in wins])) if wins else 0,
        'avg_loss_r': float(np.mean([t['r_mult'] for t in losses])) if losses else 0,
        'expectancy_r': float(np.mean([t['r_mult'] for t in trades])),
        'max_drawdown': max_dd,
        'avg_bars_held': float(np.mean([t['bars'] for t in trades])),
        'reasons': reasons,
        'regimes': regimes,
        'signals': signals,
    }


def print_report(r):
    if 'error' in r:
        print(f"  {r['name']}: {r['error']}")
        return
    print(f"  Trades: {r['trades']}")
    print(f"  Win Rate: {r['win_rate']:.1f}%")
    print(f"  P&L: ${r['pnl']:.2f} ({r['pnl_pct']:.1f}%)")
    print(f"  Profit Factor: {r['profit_factor']:.2f}")
    print(f"  Expectancy: {r['expectancy_r']:.3f}R")
    print(f"  Avg Win: {r['avg_win_r']:.3f}R | Avg Loss: {r['avg_loss_r']:.3f}R")
    print(f"  Max Drawdown: {r['max_drawdown']:.1f}%")
    print(f"  Avg Bars Held: {r['avg_bars_held']:.1f}")

    print(f"\n  By Exit Reason:")
    for reason, data in r['reasons'].items():
        wr = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
        print(f"    {reason:8s}: {data['count']:3d} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}")

    print(f"\n  By Regime:")
    for regime, data in r['regimes'].items():
        wr = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
        print(f"    {regime:10s}: {data['count']:3d} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}")

    print(f"\n  By Signal Type:")
    for sig, data in r['signals'].items():
        wr = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
        print(f"    {sig:16s}: {data['count']:3d} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}")


def main():
    mt5.initialize()
    now = datetime.now()

    # Full available history: Jan 12 – Aug 23
    full_start = datetime(2026, 1, 12)
    full_end = now

    # Walk-forward split: train on first ~190 days, validate last 45 days
    oos_start = now - timedelta(days=45)
    train_end = oos_start

    print("=" * 70)
    print("  v15 LONG-PERIOD VALIDATION")
    print(f"  Full Period: {full_start.strftime('%b %d')} – {full_end.strftime('%b %d, %Y')} (~224 days)")
    print(f"  OOS Period:  {oos_start.strftime('%b %d')} – {full_end.strftime('%b %d, %Y')} (45 days, pure forward)")
    print(f"  Train Period: {full_start.strftime('%b %d')} – {train_end.strftime('%b %d, %Y')} (~179 days)")
    print("=" * 70)

    results = {}

    for sym_name, specs in SYMBOLS.items():
        params = OPT_V75 if '75' in sym_name else OPT_V100
        sym_short = 'V75' if '75' in sym_name else 'V100'

        print(f"\n{'━' * 60}")
        print(f"  {sym_name}")
        print(f"  Optimized: ATR Stop={params['atr_stop']}, Target={params['atr_target']}, Trail={params['trail_start']}/{params['trail_dist']}")
        print(f"{'━' * 60}")

        # ─── FULL PERIOD ───
        m5_full = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M5, full_start, full_end)
        m15_full = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M15, full_start, full_end)
        if m5_full is None or m15_full is None:
            print("  No data"); continue

        trades_full = run_backtest(m5_full, m15_full, specs, params, start_idx=250)
        full = analyze(trades_full, 'FULL 7-MONTH')
        print(f"\n  ─── FULL PERIOD ({full_start.strftime('%b %d')} – {full_end.strftime('%b %d')}) ───")
        print_report(full)
        results[f'{sym_short}_full'] = full

        # ─── TRAIN PERIOD ───
        m5_train = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M5, full_start, train_end)
        m15_train = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M15, full_start, train_end)
        if m5_train is not None and m15_train is not None:
            trades_train = run_backtest(m5_train, m15_train, specs, params, start_idx=250)
            train = analyze(trades_train, 'TRAIN')
            print(f"\n  ─── TRAIN PERIOD ({full_start.strftime('%b %d')} – {train_end.strftime('%b %d')}) ───")
            print_report(train)
            results[f'{sym_short}_train'] = train

        # ─── OOS PERIOD (45 days, no parameter changes) ───
        m5_oos = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M5, oos_start, full_end)
        m15_oos = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M15, oos_start, full_end)
        if m5_oos is not None and m15_oos is not None:
            trades_oos = run_backtest(m5_oos, m15_oos, specs, params, start_idx=0)
            oos = analyze(trades_oos, 'OOS 45-DAY FORWARD')
            print(f"\n  ─── OUT-OF-SAMPLE ({oos_start.strftime('%b %d')} – {full_end.strftime('%b %d')}) ───")
            print_report(oos)
            results[f'{sym_short}_oos'] = oos

        # ─── ROBUSTNESS CHECK ───
        if 'error' not in full and 'error' not in oos:
            pf_full = full['profit_factor']
            pf_train = results.get(f'{sym_short}_train', {}).get('profit_factor', 0)
            pf_oos = oos['profit_factor']
            wr_full = full['win_rate']
            wr_oos = oos['win_rate']
            dd_full = full['max_drawdown']
            dd_oos = oos['max_drawdown']

            print(f"\n  ─── ROBUSTNESS SUMMARY ───")
            print(f"  {'Metric':<20} {'Full 7M':<12} {'Train':<12} {'OOS 45d':<12}")
            print(f"  {'─'*20} {'─'*11} {'─'*11} {'─'*11}")
            print(f"  {'Trades':<20} {full['trades']:<12} {results.get(f'{sym_short}_train', {}).get('trades', 0):<12} {oos['trades']:<12}")
            print(f"  {'Win Rate':<20} {wr_full:<11.1f}% {results.get(f'{sym_short}_train', {}).get('win_rate', 0):<11.1f}% {wr_oos:<11.1f}%")
            print(f"  {'P&L ($)':<20} ${full['pnl']:<10.2f} ${results.get(f'{sym_short}_train', {}).get('pnl', 0):<10.2f} ${oos['pnl']:<10.2f}")
            print(f"  {'P&L (%)':<20} {full['pnl_pct']:<11.1f}% {results.get(f'{sym_short}_train', {}).get('pnl_pct', 0):<11.1f}% {oos['pnl_pct']:<11.1f}%")
            print(f"  {'Profit Factor':<20} {pf_full:<12.2f} {pf_train:<12.2f} {pf_oos:<12.2f}")
            print(f"  {'Max Drawdown':<20} {dd_full:<11.1f}% {results.get(f'{sym_short}_train', {}).get('max_drawdown', 0):<11.1f}% {dd_oos:<11.1f}%")
            print(f"  {'Expectancy (R)':<20} {full['expectancy_r']:<12.3f} {results.get(f'{sym_short}_train', {}).get('expectancy_r', 0):<12.3f} {oos['expectancy_r']:<12.3f}")

            # Degradation check
            pf_degradation = (pf_full - pf_oos) / pf_full * 100 if pf_full > 0 else 0
            wr_degradation = wr_full - wr_oos

            if pf_oos > 1.5 and pf_degradation < 20:
                verdict = "✅ ROBUST — OOS maintains >1.5 PF with <20% degradation"
            elif pf_oos > 1.2 and pf_degradation < 30:
                verdict = "⚠️ ACCEPTABLE — OOS profitable but some degradation"
            elif pf_oos > 1.0:
                verdict = "⚠️ WEAK — OOS barely profitable, needs monitoring"
            else:
                verdict = "❌ OVERFIT — OOS unprofitable, strategy fails forward test"

            print(f"\n  VERDICT: {verdict}")
            print(f"  PF degradation: {pf_degradation:.1f}% | WR degradation: {wr_degradation:.1f}pp")

    mt5.shutdown()
    print(f"\n{'=' * 70}")
    print("  LONG-PERIOD VALIDATION COMPLETE")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
