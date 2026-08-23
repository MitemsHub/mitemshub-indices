"""
MITEMSHUB AI v16.7 — Walk-Forward Backtest & Optimization
Matches MitemshubAI.mq5 EA logic (v16.7):
  Auto-TF • Wide Pullback • Momentum • Regime + Trailing
  v16.7: wider entry (0.10-3.5 ATR), momentum mode, removed body filter.
"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import json, sys

sys.stdout.reconfigure(encoding='utf-8')

# ─── SYMBOL SPECS ────────────────────────────────────────────────────
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

# ─── v16.7 DEFAULT EA PARAMETERS (matching MitemshubAI.mq5) ────────
DEFAULTS = {
    'ema_fast': 20, 'ema_mid': 50, 'ema_slow': 100,
    'pullback_min': 0.10, 'pullback_max': 3.5,     # v16.7: wider range
    'rsi_period': 14, 'rsi_buy_max': 62, 'rsi_sell_min': 38,  # v16.7: wider RSI
    'atr_period': 14, 'atr_lookback': 200,
    'atr_low_pct': 8, 'atr_high_pct': 92,           # v16.7: wider ATR band
    'compress_bars': 18, 'compress_atr_mult': 0.70, 'breakout_min': 0.10,  # v16.7: easier
    'risk_pct': 0.004,              # 0.4% per trade
    'atr_stop': 1.6,                # optimized for V100
    'atr_target': 2.8,
    'hold_bars': 14, 'cooldown': 3, 'max_consec_loss': 3,
    'max_daily_loss_pct': 0.025,
    'use_trailing': True, 'trail_start': 0.6, 'trail_dist': 0.7,
    'use_be': True, 'be_trigger': 1.0,
    # v16.7: momentum params
    'use_momentum': True,
    'mom_lookback': 20,
    'mom_min_move': 1.5,
    'mom_rsi_thresh': 40,
    'mom_rsi_thresh_sell': 60,
}


def ema(data, period):
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
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
    if len(close) < period + 1:
        return avg_gain
    avg_gain[period] = np.mean(gain[1:period + 1])
    avg_loss[period] = np.mean(loss[1:period + 1])
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    result = 100.0 - 100.0 / (1.0 + rs)
    return result


def atr(high, low, close, period):
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    result = np.full(len(close), np.nan)
    if len(close) < period:
        return result
    result[period - 1] = np.mean(tr[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(close)):
        result[i] = tr[i] * k + result[i - 1] * (1 - k)
    return result


def calc_atr_percentile(current, atr_history, lookback=200):
    valid = atr_history[~np.isnan(atr_history)]
    if len(valid) < 50:
        return 50.0
    recent = valid[-min(lookback, len(valid)):]
    return float(np.sum(current > recent) / len(recent) * 100.0)


def run_backtest(m5_data, m15_data, specs, params, start_idx=250):
    """Run v16.7 backtest. Matches MitemshubAI.mq5 v16.7 exactly."""
    close5 = m5_data['close']
    high5 = m5_data['high']
    low5 = m5_data['low']

    close15 = m15_data['close']

    p = {**DEFAULTS, **params}

    # Precompute indicators
    ema_fast_15 = ema(close15, p['ema_fast'])
    ema_mid_15 = ema(close15, p['ema_mid'])
    ema_slow_15 = ema(close15, p['ema_slow'])

    ema_fast_5 = ema(close5, p['ema_fast'])
    rsi_5 = rsi(close5, p['rsi_period'])
    atr_5 = atr(high5, low5, close5, p['atr_period'])

    # Map M5 bars to M15 bars
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

    for i in range(start_idx, len(close5)):
        if np.isnan(atr_5[i]) or np.isnan(ema_fast_5[i]) or np.isnan(rsi_5[i]):
            continue
        m15_idx = min(m5_to_m15[i], len(close15) - 1)
        if m15_idx < 1 or np.isnan(ema_fast_15[m15_idx]):
            continue

        # ─── DAILY RESET ───
        bars_per_day = 288
        if (i - day_start_bar) >= bars_per_day:
            daily_pnl = 0.0
            day_start_bar = i
            paused = False
            consec_loss = 0

        if cooldown > 0:
            cooldown -= 1

        # ─── ATR PERCENTILE ───
        atr_hist.append(atr_5[i])
        if len(atr_hist) > p['atr_lookback'] + 50:
            atr_hist = atr_hist[-(p['atr_lookback'] + 50):]
        atr_pct = calc_atr_percentile(atr_5[i], np.array(atr_hist), p['atr_lookback'])

        # ─── MANAGE POSITIONS ───
        # (Single position matching EA v16.7)
        # Check for open position exit
        if trades and trades[-1].get('exit') is None:
            pos = trades[-1]
            pos['bars'] += 1
            bid = close5[i]
            closed = False
            exit_reason = ''
            exit_price = 0.0

            if pos['bars'] >= p['hold_bars']:
                closed, exit_reason, exit_price = True, 'TIME', close5[i]

            if not closed:
                if pos['dir'] > 0:
                    if bid <= pos['sl']:
                        closed, exit_reason, exit_price = True, 'STOP', pos['sl']
                    elif bid >= pos['tp']:
                        closed, exit_reason, exit_price = True, 'TARGET', pos['tp']
                else:
                    if bid >= pos['sl']:
                        closed, exit_reason, exit_price = True, 'STOP', pos['sl']
                    elif bid <= pos['tp']:
                        closed, exit_reason, exit_price = True, 'TARGET', pos['tp']

            if not closed and p['use_be']:
                be_trigger = p['be_trigger'] * atr_5[i]
                if pos['dir'] > 0 and bid >= pos['entry'] + be_trigger and pos['sl'] < pos['entry']:
                    pos['sl'] = pos['entry'] + 2 * specs['point']
                elif pos['dir'] < 0 and bid <= pos['entry'] - be_trigger and pos['sl'] > pos['entry']:
                    pos['sl'] = pos['entry'] - 2 * specs['point']

            if not closed and p['use_trailing']:
                trail_start = p['trail_start'] * atr_5[i]
                trail_dist = p['trail_dist'] * atr_5[i]
                if pos['dir'] > 0 and bid >= pos['entry'] + trail_start:
                    new_sl = bid - trail_dist
                    if new_sl > pos['sl'] and new_sl > pos['entry']:
                        pos['sl'] = new_sl
                elif pos['dir'] < 0 and bid <= pos['entry'] - trail_start:
                    new_sl = bid + trail_dist
                    if new_sl < pos['sl'] and new_sl > pos['entry']:
                        pos['sl'] = new_sl

            if closed:
                if pos['dir'] > 0:
                    r_mult = (exit_price - pos['entry']) / pos['orig_risk']
                else:
                    r_mult = (pos['entry'] - exit_price) / pos['orig_risk']
                pnl = pos['stake'] * r_mult

                equity += pnl
                daily_pnl += pnl
                if equity > peak_equity:
                    peak_equity = equity

                pos['exit'] = exit_price
                pos['reason'] = exit_reason
                pos['r_mult'] = r_mult
                pos['pnl'] = pnl
                pos['equity'] = equity

                if r_mult < 0:
                    consec_loss += 1
                    cooldown = p['cooldown']
                else:
                    consec_loss = 0

                if consec_loss >= p['max_consec_loss']:
                    paused = True
                if daily_pnl < -equity * p['max_daily_loss_pct']:
                    paused = True
                if (peak_equity - equity) > peak_equity * 0.12:
                    paused = True

        # ─── ENTRY LOGIC (v16.7) ───
        has_open = trades and trades[-1].get('exit') is None
        if has_open or paused or cooldown > 0:
            continue

        # ATR percentile filters (v16.7: 8-92%)
        if atr_pct < p['atr_low_pct']:
            continue
        if atr_pct > p['atr_high_pct']:
            continue

        # Regime classification (M15)
        if np.isnan(ema_mid_15[m15_idx]) or np.isnan(ema_slow_15[m15_idx]):
            continue

        regime = 'RANGING'
        m15_close = close15[m15_idx]
        ef = ema_fast_15[m15_idx]
        em = ema_mid_15[m15_idx]
        es = ema_slow_15[m15_idx]

        if ef > em > es and m15_close > ef:
            regime = 'BULLISH'
        elif ef < em < es and m15_close < ef:
            regime = 'BEARISH'

        direction = 0
        sig_type = ''

        # ─── MODE 1: TREND PULLBACK (v16.7: wider, no body filter) ───
        if regime in ('BULLISH', 'BEARISH'):
            direction = 1 if regime == 'BULLISH' else -1
            pb = abs(close5[i] - ema_fast_5[i])

            # v16.7: wider pullback range (0.10-3.5 ATR)
            if pb < p['pullback_min'] * atr_5[i] or pb > p['pullback_max'] * atr_5[i]:
                direction = 0  # reject

            # v16.7: RSI filter only (removed 0.6 ATR cap)
            if direction != 0 and direction > 0 and rsi_5[i] > p['rsi_buy_max']:
                direction = 0
            if direction != 0 and direction < 0 and rsi_5[i] < p['rsi_sell_min']:
                direction = 0

            # v16.7: REMOVED body direction filter
            # v16.7: REMOVED body size filter

            if direction != 0:
                sig_type = 'PULLBACK_LONG' if direction > 0 else 'PULLBACK_SHORT'

        # ─── MODE 2: MOMENTUM (v16.7 NEW) ───
        if direction == 0 and p['use_momentum'] and regime in ('BULLISH', 'BEARISH'):
            mom_dir = 1 if regime == 'BULLISH' else -1

            # Session high/low over lookback
            lb = min(p['mom_lookback'], i)
            session_high = np.max(high5[i - lb:i + 1])
            session_low = np.min(low5[i - lb:i + 1])

            move_up = close5[i] - session_low
            move_down = session_high - close5[i]

            body = close5[i] - close5[i - 1]

            if mom_dir > 0 and move_up > p['mom_min_move'] * atr_5[i]:
                if rsi_5[i] > p['mom_rsi_thresh'] and rsi_5[i] < 68 and body > 0:
                    direction = 1
                    sig_type = 'MOMENTUM_LONG'

            if mom_dir < 0 and move_down > p['mom_min_move'] * atr_5[i]:
                if rsi_5[i] < p['mom_rsi_thresh_sell'] and rsi_5[i] > 32 and body < 0:
                    direction = -1
                    sig_type = 'MOMENTUM_SHORT'

        # ─── MODE 3: COMPRESSION BREAKOUT (v16.7: easier) ───
        if direction == 0 and regime == 'RANGING':
            atr_now = atr_5[i]
            start_a = max(1, i - 100)
            avg_atr = np.mean(atr_5[start_a:i]) if i > start_a else atr_now

            # v16.7: easier compression (0.70x)
            if atr_now > avg_atr * p['compress_atr_mult']:
                continue

            compress_start = max(0, i - p['compress_bars'])
            rh = np.max(high5[compress_start:i + 1])
            rl = np.min(low5[compress_start:i + 1])
            rng = rh - rl

            # v16.7: easier range filter (0.3x)
            if rng < atr_now * 0.3:
                continue

            cl = close5[i]
            if cl > rh + p['breakout_min'] * atr_now:
                direction = 1
            elif cl < rl - p['breakout_min'] * atr_now:
                direction = -1

            if direction == 0:
                continue

            # v16.7: easier RSI filter (48/52)
            if direction > 0 and rsi_5[i] < 48:
                continue
            if direction < 0 and rsi_5[i] > 52:
                continue

            sig_type = 'BREAKOUT_UP' if direction > 0 else 'BREAKOUT_DOWN'

        if direction == 0:
            continue

        # ─── OPEN TRADE ───
        entry = close5[i]
        stop_dist = p['atr_stop'] * atr_5[i]
        tp_dist = p['atr_target'] * atr_5[i]

        max_stop = entry * 0.025
        if stop_dist > max_stop:
            stop_dist = max_stop
        if stop_dist < atr_5[i] * 0.5:
            stop_dist = atr_5[i] * 0.5

        sl = entry - stop_dist if direction > 0 else entry + stop_dist
        tp = entry + tp_dist if direction > 0 else entry - tp_dist

        spread_cost = specs['spread_pts'] * specs['point']
        risk_money = equity * p['risk_pct']
        risk_points = stop_dist / specs['point']
        vol = risk_money / (risk_points * (specs['tick_val'] / (specs['tick_size'] / specs['point'])))
        vol = max(specs['min_lot'], round(vol / specs['step']) * specs['step'])

        entry_adj = entry + (spread_cost / 2) * direction

        trades.append({
            'dir': direction,
            'entry': entry_adj,
            'sl': sl,
            'tp': tp,
            'orig_risk': stop_dist,
            'stake': risk_money,
            'bars': 0,
            'regime': regime,
            'sig': sig_type,
            'exit': None,
            'reason': None,
            'r_mult': None,
            'pnl': None,
            'equity': None,
            'atr_pct': atr_pct,
        })

    # Finalize any open trades
    for t in trades:
        if t.get('exit') is None:
            t['exit'] = close5[-1]
            t['reason'] = 'EOD'
            t['bars'] = t.get('bars', 0)
            if t['dir'] > 0:
                t['r_mult'] = (t['exit'] - t['entry']) / t['orig_risk']
            else:
                t['r_mult'] = (t['entry'] - t['exit']) / t['orig_risk']
            t['pnl'] = t['stake'] * t['r_mult']
            t['equity'] = equity + t['pnl']

    # Convert to flat list of completed trades
    completed = []
    for t in trades:
        if t.get('r_mult') is not None:
            completed.append({
                'entry': t['entry'], 'exit': t['exit'], 'dir': t['dir'],
                'reason': t['reason'], 'r_mult': t['r_mult'], 'pnl': t['pnl'],
                'bars': t['bars'], 'equity': t['equity'],
                'atr_pct': t['atr_pct'], 'regime': t['regime'],
                'signal_type': t['sig'],
            })

    return completed


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

    regimes = {}
    for t in trades:
        r = t.get('regime', 'UNKNOWN')
        if r not in regimes:
            regimes[r] = {'wins': 0, 'losses': 0, 'pnl': 0}
        if t['r_mult'] > 0:
            regimes[r]['wins'] += 1
        else:
            regimes[r]['losses'] += 1
        regimes[r]['pnl'] += t['pnl']

    signals = {}
    for t in trades:
        s = t.get('signal_type', 'UNKNOWN')
        if s not in signals:
            signals[s] = {'wins': 0, 'losses': 0, 'pnl': 0, 'r_mults': []}
        if t['r_mult'] > 0:
            signals[s]['wins'] += 1
        else:
            signals[s]['losses'] += 1
        signals[s]['pnl'] += t['pnl']
        signals[s]['r_mults'].append(t['r_mult'])

    total_r = sum(t['r_mult'] for t in trades)

    return {
        'name': name,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100,
        'pnl': pnl,
        'pnl_pct': pnl / 10000 * 100,
        'profit_factor': pf,
        'avg_win_r': float(np.mean([t['r_mult'] for t in wins])) if wins else 0,
        'avg_loss_r': float(np.mean([t['r_mult'] for t in losses])) if losses else 0,
        'expectancy_r': float(np.mean([t['r_mult'] for t in trades])),
        'total_r': total_r,
        'max_drawdown': max_dd,
        'avg_bars_held': float(np.mean([t['bars'] for t in trades])),
        'regimes': regimes,
        'signals': signals,
    }


def walk_forward(m5_data, m15_data, specs, params, n_windows=3):
    total = len(m5_data)
    warmup = 250
    window_size = (total - warmup) // n_windows
    results = []

    for w in range(n_windows):
        start = warmup + w * window_size
        end = min(start + window_size, total)
        m5_start = start
        m5_end = end
        m15_start = start // 3
        m15_end = end // 3 + 10
        chunk_m5 = m5_data[m5_start:m5_end]
        chunk_m15 = m15_data[m15_start:min(m15_end, len(m15_data))]
        trades = run_backtest(chunk_m5, chunk_m15, specs, params, start_idx=0)
        r = analyze(trades, f'W{w + 1}')
        results.append(r)

    return results


def main():
    mt5.initialize()
    print("=" * 70)
    print("  MITEMSHUB AI v16.7 — WALK-FORWARD BACKTEST & OPTIMIZATION")
    print("  Auto-TF + Momentum + Wide Pullback + Daily Reset")
    print("=" * 70)

    end = datetime.now()
    start = end - timedelta(days=90)

    for sym_name, specs in SYMBOLS.items():
        print(f"\n{'─' * 60}")
        print(f"  {sym_name}")
        print(f"{'─' * 60}")

        m5 = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M5, start, end)
        m15 = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M15, start, end)
        if m5 is None or m15 is None:
            print("  No data available")
            continue

        print(f"  M5 bars: {len(m5)}, M15 bars: {len(m15)}")

        # ─── PHASE 1: Walk-forward with v16.7 defaults ───
        print("\n  Phase 1: Walk-forward with v16.7 defaults...")
        wf = walk_forward(m5, m15, specs, {})
        for r in wf:
            pf = r.get('profit_factor', 0)
            print(f"    {r['name']}: {r['trades']} trades, WR={r.get('win_rate', 0):.0f}%, "
                  f"P&L=${r.get('pnl', 0):.2f}, PF={pf:.2f}, MaxDD={r.get('max_drawdown', 0):.1f}%")

        full_trades = run_backtest(m5, m15, specs, {})
        full = analyze(full_trades, 'FULL (v16.7 defaults)')
        if full['trades'] == 0:
            print(f"\n  FULL (v16.7 defaults): No trades generated")
        else:
            print(f"\n  FULL (v16.7 defaults): {full['trades']} trades, WR={full['win_rate']:.0f}%, "
                  f"P&L=${full['pnl']:.2f}, PF={full['profit_factor']:.2f}, "
                  f"MaxDD={full['max_drawdown']:.1f}%, Exp={full['expectancy_r']:.3f}R")

        # ─── PHASE 2: Per-regime & per-signal ───
        if full['trades'] > 0:
            print("\n  Per-Regime Performance:")
            for regime, data in full['regimes'].items():
                total = data['wins'] + data['losses']
                wr = data['wins'] / total * 100 if total > 0 else 0
                print(f"    {regime}: {total} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}")

            print("\n  Per-Signal Performance:")
            for sig, data in full['signals'].items():
                total = data['wins'] + data['losses']
                wr = data['wins'] / total * 100 if total > 0 else 0
                avg_r = np.mean(data['r_mults']) if data['r_mults'] else 0
                print(f"    {sig}: {total} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}, AvgR={avg_r:.3f}")

        # ─── PHASE 3: Optimize ───
        print("\n  Phase 3: Optimizing key parameters...")
        best_pf = 0
        best_params = {}
        tested = 0

        for atr_stop in [1.2, 1.4, 1.6, 1.8, 2.0]:
            for atr_target in [2.2, 2.4, 2.6, 2.8, 3.0]:
                for trail_start in [0.5, 0.6, 0.8, 1.0]:
                    for trail_dist in [0.5, 0.7, 0.9]:
                        for pb_max in [2.5, 3.0, 3.5]:
                            params = {
                                'atr_stop': atr_stop,
                                'atr_target': atr_target,
                                'trail_start': trail_start,
                                'trail_dist': trail_dist,
                                'pullback_max': pb_max,
                            }
                            trades = run_backtest(m5, m15, specs, params)
                            if len(trades) < 10:
                                continue
                            r = analyze(trades, 'opt')
                            if (r['profit_factor'] > best_pf and
                                r['win_rate'] > 45 and r['max_drawdown'] < 15 and
                                r['trades'] >= 15):
                                best_pf = r['profit_factor']
                                best_params = params.copy()
                                best_result = r
                            tested += 1

        print(f"  Tested {tested} parameter combinations")

        if best_params:
            print(f"\n  ★ OPTIMAL PARAMETERS (v16.7):")
            print(f"    ATR Stop:    {best_params['atr_stop']}")
            print(f"    ATR Target:  {best_params['atr_target']}")
            print(f"    Trail Start: {best_params['trail_start']}")
            print(f"    Trail Dist:  {best_params['trail_dist']}")
            print(f"    Pullback Max:{best_params['pullback_max']}")
            print(f"    → {best_result['trades']} trades, WR={best_result['win_rate']:.0f}%, "
                  f"PF={best_result['profit_factor']:.2f}, MaxDD={best_result['max_drawdown']:.1f}%, "
                  f"TotalR={best_result['total_r']:.2f}")

            # Walk-forward on optimal params
            print(f"\n  Walk-forward on optimal params:")
            wf_opt = walk_forward(m5, m15, specs, best_params)
            all_pf = []
            for r in wf_opt:
                pf = r.get('profit_factor', 0)
                all_pf.append(pf)
                trades_n = r.get('trades', 0)
                if trades_n > 0:
                    print(f"    {r['name']}: {trades_n} trades, WR={r.get('win_rate', 0):.0f}%, "
                          f"P&L=${r.get('pnl', 0):.2f}, PF={pf:.2f}, MaxDD={r.get('max_drawdown', 0):.1f}%")
                else:
                    print(f"    {r['name']}: 0 trades")

            avg_pf = np.mean(all_pf)
            profitable_windows = sum(1 for r in wf_opt if r.get('trades', 0) > 0 and r.get('pnl', 0) > 0)
            print(f"\n  Walk-forward avg PF: {avg_pf:.2f} ({profitable_windows}/3 windows profitable)")

            sym_short = 'V75' if '75' in sym_name else 'V100'
            with open(f'v16_optimal_{sym_short}.json', 'w') as f:
                json.dump({
                    'symbol': sym_name,
                    'version': 'v16.7',
                    'params': best_params,
                    'full_result': {k: v for k, v in best_result.items() if k != 'signals'},
                    'walk_forward': [{'name': r['name'], 'trades': r.get('trades', 0),
                                       'win_rate': r.get('win_rate', 0), 'pnl': r.get('pnl', 0),
                                       'profit_factor': r.get('profit_factor', 0),
                                       'max_drawdown': r.get('max_drawdown', 0)} for r in wf_opt],
                }, f, indent=2)
        else:
            print("  No profitable parameter combination found")

    mt5.shutdown()
    print(f"\n{'=' * 70}")
    print("  BACKTEST COMPLETE (v16.7)")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
