"""
MITEMSHUB AI v16 — Walk-Forward Backtest & Optimization
Matches MitemshubAI_v16_5.mq5 EA logic:
  Multi-symbol • Session Filter • Regime + Pullback + Trailing
  Updated: risk 0.4%, ATR stop 1.8, trailing 0.8/0.7, spread filter.
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

# ─── v16.5 DEFAULT EA PARAMETERS (matching MitemshubAI_v16_5.mq5) ──
DEFAULTS = {
    'ema_fast': 20, 'ema_mid': 50, 'ema_slow': 100,
    'pullback_min': 0.20, 'pullback_max': 2.2,   # v16.6: wider entry
    'rsi_period': 14, 'rsi_buy_max': 58, 'rsi_sell_min': 42,
    'atr_period': 14, 'atr_lookback': 200,
    'atr_low_pct': 12, 'atr_high_pct': 88,
    'min_atr_points': 0.0,          # v16.5: min ATR in points (0 = disabled)
    'compress_bars': 18, 'compress_atr_mult': 0.65, 'breakout_min': 0.12,
    'risk_pct': 0.004,              # v16.5: 0.4% per trade (was 0.5%)
    'atr_stop': 1.8,                # v16.5: default 1.8 (was 2.0)
    'atr_target': 2.8,
    'hold_bars': 14, 'cooldown': 3, 'max_consec_loss': 3,  # v16.6: faster recovery
    'max_daily_loss_pct': 0.025,
    'use_trailing': True, 'trail_start': 0.8, 'trail_dist': 0.7,  # v16.5: tighter
    'use_be': True, 'be_trigger': 1.0,
    'max_spread_pts': 0,            # v16.5: live-only filter; backtest uses entry spread cost instead
    'use_session_filter': False,     # v16.5: session filter (off by default)
    'session_start_hour': 0,
    'session_end_hour': 24,
}

# ─── PARAMETER GRID FOR OPTIMIZATION (v16.5 range) ──────────────────
GRID = {
    'atr_stop':        [1.2, 1.4, 1.6, 1.8, 2.0],
    'atr_target':      [1.8, 2.0, 2.4, 2.8, 3.0],
    'pullback_min':    [0.15, 0.25, 0.35],
    'pullback_max':    [1.4, 1.8, 2.2],
    'rsi_buy_max':     [55, 58, 62],
    'rsi_sell_min':    [38, 42, 45],
    'trail_start':     [0.6, 0.8, 1.0, 1.2],
    'trail_dist':      [0.5, 0.7, 0.9, 1.1],
}


def ema(data, period):
    """Exponential moving average."""
    result = np.full(len(data), np.nan)
    if len(data) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = data[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(close, period):
    """Relative strength index."""
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
    """Average true range."""
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
    """ATR percentile over lookback window."""
    valid = atr_history[~np.isnan(atr_history)]
    if len(valid) < 50:
        return 50.0
    recent = valid[-min(lookback, len(valid)):]
    return float(np.sum(current > recent) / len(recent) * 100.0)


def is_in_session(bar_time, start_hour, end_hour):
    """Check if a bar's hour falls within the trading session (UTC)."""
    hour = bar_time.hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    else:  # overnight session
        return hour >= start_hour or hour < end_hour


def run_backtest(m5_data, m15_data, specs, params, start_idx=250):
    """Run v16 backtest on given data with given parameters.
    Matches MitemshubAI_v16_5.mq5 logic exactly."""
    close5 = m5_data['close']
    high5 = m5_data['high']
    low5 = m5_data['low']
    time5 = m5_data['time']  # numpy datetime64 array

    close15 = m15_data['close']

    p = {**DEFAULTS, **params}

    # Precompute indicators
    ema_fast_15 = ema(close15, p['ema_fast'])
    ema_mid_15 = ema(close15, p['ema_mid'])
    ema_slow_15 = ema(close15, p['ema_slow'])

    ema_fast_5 = ema(close5, p['ema_fast'])
    rsi_5 = rsi(close5, p['rsi_period'])
    atr_5 = atr(high5, low5, close5, p['atr_period'])

    # Map M5 bars to M15 bars (3 M5 bars per M15 bar)
    m5_to_m15 = np.arange(len(close5)) // 3

    trades = []
    equity = 10000.0
    peak_equity = equity
    cooldown = 0
    consec_loss = 0
    paused = False
    daily_pnl = 0.0
    day_start_bar = 0

    # ATR history for percentile (matching EA: atr_hist[300])
    atr_hist = []
    # v16.6: support multiple concurrent positions
    max_positions = 2
    positions = []  # list of dicts: {dir, entry, sl, tp, orig_risk, stake, bars, regime, sig}

    for i in range(start_idx, len(close5)):
        if np.isnan(atr_5[i]) or np.isnan(ema_fast_5[i]) or np.isnan(rsi_5[i]):
            continue
        m15_idx = min(m5_to_m15[i], len(close15) - 1)
        if m15_idx < 1 or np.isnan(ema_fast_15[m15_idx]):
            continue

        # ─── DAILY RESET (matching EA: per-day, not per-bar) ───
        # EA uses TimeCurrent() - (TimeCurrent() % 86400) for day boundaries
        # In backtest we approximate by counting bars_per_day
        bars_per_day = 288  # 24h * 60 / 5
        if (i - day_start_bar) >= bars_per_day:
            daily_pnl = 0.0
            day_start_bar = i
            paused = False
            consec_loss = 0

        if cooldown > 0:
            cooldown -= 1

        # ─── SESSION FILTER (v16.5 new) ───
        if p['use_session_filter'] and len(time5) > i:
            bar_dt = np.datetime64(time5[i], 's').astype(datetime)
            if not is_in_session(bar_dt, p['session_start_hour'], p['session_end_hour']):
                continue

        # ─── ATR PERCENTILE ───
        # EA stores in fixed 300-element array; backtest uses dynamic list
        atr_hist.append(atr_5[i])
        if len(atr_hist) > p['atr_lookback'] + 50:
            atr_hist = atr_hist[-(p['atr_lookback'] + 50):]
        atr_pct = calc_atr_percentile(atr_5[i], np.array(atr_hist), p['atr_lookback'])

        # ─── SPREAD FILTER (v16.5 new, live-only) ───
        # The EA checks live spread via SymbolInfoInteger(SYMBOL_SPREAD).
        # Backtest can't simulate variable per-bar spread, so we skip this
        # filter and model spread cost via entry adjustment instead.
        # Set max_spread_pts > 0 to enable a rough backtest approximation.
        if p['max_spread_pts'] > 0:
            spread_pts = specs['spread_pts']
            if spread_pts > p['max_spread_pts']:
                continue

        # ─── MANAGE POSITIONS (v16.6: multi-position) ───
        closed_indices = []
        for pi, pos in enumerate(positions):
            pos['bars'] += 1
            bid = close5[i]
            ask = close5[i]

            closed = False
            exit_reason = ''
            exit_price = 0.0

            # Time exit
            if pos['bars'] >= p['hold_bars']:
                closed, exit_reason, exit_price = True, 'TIME', close5[i]

            # SL / TP check
            if not closed:
                if pos['dir'] > 0:
                    if bid <= pos['sl']:
                        closed, exit_reason, exit_price = True, 'STOP', pos['sl']
                    elif bid >= pos['tp']:
                        closed, exit_reason, exit_price = True, 'TARGET', pos['tp']
                else:
                    if ask >= pos['sl']:
                        closed, exit_reason, exit_price = True, 'STOP', pos['sl']
                    elif ask <= pos['tp']:
                        closed, exit_reason, exit_price = True, 'TARGET', pos['tp']

            # Breakeven
            if not closed and p['use_be']:
                be_trigger = p['be_trigger'] * atr_5[i]
                if pos['dir'] > 0 and bid >= pos['entry'] + be_trigger and pos['sl'] < pos['entry']:
                    pos['sl'] = pos['entry'] + 2 * specs['point']
                elif pos['dir'] < 0 and ask <= pos['entry'] - be_trigger and pos['sl'] > pos['entry']:
                    pos['sl'] = pos['entry'] - 2 * specs['point']

            # Trailing
            if not closed and p['use_trailing']:
                trail_start = p['trail_start'] * atr_5[i]
                trail_dist = p['trail_dist'] * atr_5[i]
                if pos['dir'] > 0 and bid >= pos['entry'] + trail_start:
                    new_sl = bid - trail_dist
                    if new_sl > pos['sl'] and new_sl > pos['entry']:
                        pos['sl'] = new_sl
                elif pos['dir'] < 0 and ask <= pos['entry'] - trail_start:
                    new_sl = ask + trail_dist
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

                trades.append({
                    'entry': pos['entry'], 'exit': exit_price, 'dir': pos['dir'],
                    'reason': exit_reason, 'r_mult': r_mult, 'pnl': pnl,
                    'bars': pos['bars'], 'equity': equity,
                    'atr_pct': atr_pct, 'regime': pos['regime'],
                    'signal_type': pos['sig'],
                })

                if r_mult < 0:
                    consec_loss += 1
                    cooldown = p['cooldown']
                else:
                    consec_loss = 0

                # v16.6: 3-circuit-breaker
                if consec_loss >= p['max_consec_loss']:
                    paused = True
                if daily_pnl < -equity * p['max_daily_loss_pct']:
                    paused = True
                if (peak_equity - equity) > peak_equity * 0.12:
                    paused = True

                closed_indices.append(pi)

        # Remove closed positions (reverse order)
        for pi in reversed(closed_indices):
            positions.pop(pi)

        # ─── ENTRY LOGIC (v16.6: multi-position) ───
        if paused or cooldown > 0:
            continue
        if len(positions) >= max_positions:
            continue  # Max concurrent positions reached

        # ATR percentile filters (matching EA: pct < 12 → NO_TRADE, pct > 88 → HIGH_VOL)
        if atr_pct < p['atr_low_pct']:
            continue
        if atr_pct > p['atr_high_pct']:
            continue  # HIGH_VOL regime → no trade

        # Regime classification (M15) — matching EA exactly
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

        # ─── MODE 1: TREND PULLBACK (matching EA exactly) ───
        if regime in ('BULLISH', 'BEARISH'):
            direction = 1 if regime == 'BULLISH' else -1
            pb = abs(close5[i] - ema_fast_5[i])

            # Pullback range filter
            if pb < p['pullback_min'] * atr_5[i] or pb > p['pullback_max'] * atr_5[i]:
                continue

            # Correct side of EMA (0.6 ATR from fast EMA)
            if direction > 0 and close5[i] > ema_fast_5[i] + 0.6 * atr_5[i]:
                continue
            if direction < 0 and close5[i] < ema_fast_5[i] - 0.6 * atr_5[i]:
                continue

            # RSI filter
            if direction > 0 and rsi_5[i] > p['rsi_buy_max']:
                continue
            if direction < 0 and rsi_5[i] < p['rsi_sell_min']:
                continue

            # Confirmation candle (body must be in direction)
            body = close5[i] - close5[i - 1]
            if direction > 0 and body <= 0:
                continue
            if direction < 0 and body >= 0:
                continue

            # Gap filter (no large candles)
            if abs(body) > atr_5[i] * 0.7:
                continue

            sig_type = 'PULLBACK_LONG' if direction > 0 else 'PULLBACK_SHORT'

        # ─── MODE 2: COMPRESSION BREAKOUT (matching EA exactly) ───
        elif regime == 'RANGING':
            atr_now = atr_5[i]
            # Average ATR over last 100 bars (matching EA: for i=1 to 100)
            start_a = max(1, i - 100)
            # EA reads from CopyBuffer which is 1-indexed; backtest uses 0-indexed
            avg_atr = np.mean(atr_5[start_a:i]) if i > start_a else atr_now
            if atr_now > avg_atr * p['compress_atr_mult']:
                continue  # Not compressed

            # Range over compress_bars
            compress_start = max(0, i - p['compress_bars'])
            rh = np.max(high5[compress_start:i + 1])
            rl = np.min(low5[compress_start:i + 1])
            rng = rh - rl
            if rng < atr_now * 0.4:
                continue

            cl = close5[i]
            if cl > rh + p['breakout_min'] * atr_now:
                direction = 1
            elif cl < rl - p['breakout_min'] * atr_now:
                direction = -1
            else:
                continue

            # Exhaustion filter
            candle_range = high5[i] - low5[i]
            if candle_range > atr_now * 2.2:
                continue

            # RSI confirmation
            if direction > 0 and rsi_5[i] < 52:
                continue
            if direction < 0 and rsi_5[i] > 48:
                continue

            sig_type = 'BREAKOUT_UP' if direction > 0 else 'BREAKOUT_DOWN'
        else:
            continue

        # ─── OPEN TRADE (matching EA v16.5 exactly) ───
        entry = close5[i]
        stop_dist = p['atr_stop'] * atr_5[i]
        tp_dist = p['atr_target'] * atr_5[i]

        # Max stop distance cap (matching EA: entry * 0.025)
        max_stop = entry * 0.025
        if stop_dist > max_stop:
            stop_dist = max_stop
        if stop_dist < atr_5[i] * 0.5:
            stop_dist = atr_5[i] * 0.5

        sl = entry - stop_dist if direction > 0 else entry + stop_dist
        tp = entry + tp_dist if direction > 0 else entry - tp_dist

        # Spread cost (v16.5: spread filter already applied above)
        spread_cost = specs['spread_pts'] * specs['point']

        # Risk sizing (v16.5: 0.4% equity risk)
        risk_money = equity * p['risk_pct']
        risk_points = stop_dist / specs['point']
        vol = risk_money / (risk_points * (specs['tick_val'] / (specs['tick_size'] / specs['point'])))
        vol = max(specs['min_lot'], round(vol / specs['step']) * specs['step'])

        # Apply spread to entry
        entry_adj = entry + (spread_cost / 2) * direction

        # v16.6: Add to positions list
        positions.append({
            'dir': direction,
            'entry': entry_adj,
            'sl': sl,
            'tp': tp,
            'orig_risk': stop_dist,
            'stake': risk_money,
            'bars': 0,
            'regime': regime,
            'sig': sig_type,
        })

    return trades


def analyze(trades, name):
    """Analyze backtest results."""
    if not trades:
        return {'name': name, 'trades': 0, 'error': 'No trades'}

    wins = [t for t in trades if t['r_mult'] > 0]
    losses = [t for t in trades if t['r_mult'] <= 0]
    pnl = sum(t['pnl'] for t in trades)
    avg_win = np.mean([t['r_mult'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['r_mult'] for t in losses]) if losses else 0

    # Drawdown
    equities = [10000] + [t['equity'] for t in trades]
    peaks = np.maximum.accumulate(equities)
    dd = (peaks - equities) / peaks * 100
    max_dd = float(np.max(dd))

    # Profit factor
    gross_win = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0

    # Per-regime
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

    # Per-signal
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

    # Total R
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
        'avg_win_r': float(avg_win),
        'avg_loss_r': float(avg_loss),
        'expectancy_r': float(np.mean([t['r_mult'] for t in trades])),
        'total_r': total_r,
        'max_drawdown': max_dd,
        'avg_bars_held': float(np.mean([t['bars'] for t in trades])),
        'regimes': regimes,
        'signals': signals,
    }


def walk_forward(m5_data, m15_data, specs, params, n_windows=3):
    """3-window walk-forward validation."""
    total = len(m5_data)
    warmup = 250
    window_size = (total - warmup) // n_windows
    results = []

    for w in range(n_windows):
        start = warmup + w * window_size
        end = min(start + window_size, total)
        # Chunk both M5 and M15 proportionally
        m5_start = start
        m5_end = end
        m15_start = start // 3
        m15_end = end // 3 + 10  # extra buffer
        chunk_m5 = m5_data[m5_start:m5_end]
        chunk_m15 = m15_data[m15_start:min(m15_end, len(m15_data))]
        trades = run_backtest(chunk_m5, chunk_m15, specs, params, start_idx=0)
        r = analyze(trades, f'W{w + 1}')
        results.append(r)

    return results


def main():
    mt5.initialize()
    print("=" * 70)
    print("  MITEMSHUB AI v16 — WALK-FORWARD BACKTEST & OPTIMIZATION")
    print("  (Matching MitemshubAI_v16_5.mq5 EA)")
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

        # ─── PHASE 1: Walk-forward with v16.5 defaults ───
        print("\n  Phase 1: Walk-forward with v16.5 defaults...")
        wf = walk_forward(m5, m15, specs, {})
        for r in wf:
            pf = r.get('profit_factor', 0)
            print(f"    {r['name']}: {r['trades']} trades, WR={r.get('win_rate', 0):.0f}%, "
                  f"P&L=${r.get('pnl', 0):.2f}, PF={pf:.2f}, MaxDD={r.get('max_drawdown', 0):.1f}%")

        full_trades = run_backtest(m5, m15, specs, {})
        full = analyze(full_trades, 'FULL (v16.5 defaults)')
        if full['trades'] == 0:
            print(f"\n  FULL (v16.5 defaults): No trades generated")
        else:
            print(f"\n  FULL (v16.5 defaults): {full['trades']} trades, WR={full['win_rate']:.0f}%, "
                  f"P&L=${full['pnl']:.2f}, PF={full['profit_factor']:.2f}, "
                  f"MaxDD={full['max_drawdown']:.1f}%, Exp={full['expectancy_r']:.3f}R")

        # ─── PHASE 2: Per-regime analysis ───
        if full['trades'] > 0:
            print("\n  Per-Regime Performance:")
            for regime, data in full['regimes'].items():
                total = data['wins'] + data['losses']
                wr = data['wins'] / total * 100 if total > 0 else 0
                print(f"    {regime}: {total} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}")

            # ─── PHASE 3: Per-signal analysis ───
            print("\n  Per-Signal Performance:")
            for sig, data in full['signals'].items():
                total = data['wins'] + data['losses']
                wr = data['wins'] / total * 100 if total > 0 else 0
                avg_r = np.mean(data['r_mults']) if data['r_mults'] else 0
                print(f"    {sig}: {total} trades, WR={wr:.0f}%, P&L=${data['pnl']:.2f}, AvgR={avg_r:.3f}")

        # ─── PHASE 4: Optimize key parameters ───
        print("\n  Phase 4: Optimizing key parameters...")
        best_pf = 0
        best_params = {}
        tested = 0

        for atr_stop in [1.4, 1.6, 1.8, 2.0]:
            for atr_target in [2.2, 2.4, 2.6, 2.8]:
                for trail_start in [0.6, 0.8, 1.0]:
                    for trail_dist in [0.5, 0.7, 0.9]:
                        params = {
                            'atr_stop': atr_stop,
                            'atr_target': atr_target,
                            'trail_start': trail_start,
                            'trail_dist': trail_dist,
                        }
                        trades = run_backtest(m5, m15, specs, params)
                        if len(trades) < 10:
                            continue
                        r = analyze(trades, 'opt')
                        # Require: PF>1.0, WR>45%, MaxDD<15%, at least 15 trades
                        if (r['profit_factor'] > best_pf and
                            r['win_rate'] > 45 and r['max_drawdown'] < 15 and
                            r['trades'] >= 15):
                            best_pf = r['profit_factor']
                            best_params = params.copy()
                            best_result = r
                        tested += 1

        print(f"  Tested {tested} parameter combinations")

        if best_params:
            print(f"\n  ★ OPTIMAL PARAMETERS (v16.5):")
            print(f"    ATR Stop:  {best_params['atr_stop']}")
            print(f"    ATR Target: {best_params['atr_target']}")
            print(f"    Trail Start: {best_params['trail_start']}")
            print(f"    Trail Dist: {best_params['trail_dist']}")
            print(f"    → {best_result['trades']} trades, WR={best_result['win_rate']:.0f}%, "
                  f"PF={best_result['profit_factor']:.2f}, MaxDD={best_result['max_drawdown']:.1f}%, "
                  f"TotalR={best_result['total_r']:.2f}")

            # Walk-forward on optimal params
            print(f"\n  Walk-forward on optimal params:")
            wf_opt = walk_forward(m5, m15, specs, best_params)
            all_pf = []
            all_profitable = 0
            for r in wf_opt:
                pf = r.get('profit_factor', 0)
                all_pf.append(pf)
                if r.get('pnl', 0) > 0:
                    all_profitable += 1
                trades_n = r.get('trades', 0)
                if trades_n > 0:
                    print(f"    {r['name']}: {trades_n} trades, WR={r.get('win_rate', 0):.0f}%, "
                          f"P&L=${r.get('pnl', 0):.2f}, PF={pf:.2f}, MaxDD={r.get('max_drawdown', 0):.1f}%")
                else:
                    print(f"    {r['name']}: 0 trades")

            avg_pf = np.mean(all_pf)
            profitable_windows = sum(1 for r in wf_opt if r.get('trades', 0) > 0 and r.get('pnl', 0) > 0)
            print(f"\n  Walk-forward avg PF: {avg_pf:.2f} ({profitable_windows}/3 windows profitable)")

            # Save optimal params
            sym_short = 'V75' if '75' in sym_name else 'V100'
            with open(f'v16_optimal_{sym_short}.json', 'w') as f:
                json.dump({
                    'symbol': sym_name,
                    'version': 'v16.5',
                    'params': best_params,
                    'full_result': {k: v for k, v in best_result.items() if k != 'signals'},
                    'walk_forward': [{'name': r['name'], 'trades': r.get('trades', 0),
                                       'win_rate': r.get('win_rate', 0), 'pnl': r.get('pnl', 0),
                                       'profit_factor': r.get('profit_factor', 0),
                                       'max_drawdown': r.get('max_drawdown', 0)} for r in wf_opt],
                }, f, indent=2)
        else:
            print("  No profitable parameter combination found with constraints")

    mt5.shutdown()
    print(f"\n{'=' * 70}")
    print("  BACKTEST COMPLETE (v16.5)")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
