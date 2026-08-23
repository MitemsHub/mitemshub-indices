"""
Monte Carlo Stress Test — v16 Optimized Engine
Shuffles trade order 1000x per symbol to test robustness under worst-case sequencing.
Reports: ruin probability, drawdown distribution, equity confidence intervals.
Updated for v16.5: risk 0.4%, trailing 0.6/0.7, optimized stops.
"""
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import json, sys

sys.stdout.reconfigure(encoding='utf-8')
np.random.seed(42)

# ─── SPECS ──────────────────────────────────────────────────────────
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

# ─── v16.5 OPTIMIZED PARAMETERS (from backtest_v16.py) ─────────────
OPT_V75 = {
    'ema_fast': 20, 'ema_mid': 50, 'ema_slow': 100,
    'pullback_min': 0.25, 'pullback_max': 1.8,
    'rsi_period': 14, 'rsi_buy_max': 58, 'rsi_sell_min': 42,
    'atr_period': 14, 'atr_lookback': 200,
    'atr_low_pct': 12, 'atr_high_pct': 88,
    'compress_bars': 18, 'compress_atr_mult': 0.65, 'breakout_min': 0.12,
    'risk_pct': 0.004, 'atr_stop': 1.8, 'atr_target': 2.2,   # v16.5 optimized
    'hold_bars': 14, 'cooldown': 4, 'max_consec_loss': 3,
    'max_daily_loss_pct': 0.025,
    'use_trailing': True, 'trail_start': 0.6, 'trail_dist': 0.5,  # v16.5 optimized
    'use_be': True, 'be_trigger': 1.0,
    'max_spread_pts': 0,  # disabled in backtest
}

OPT_V100 = {
    'ema_fast': 20, 'ema_mid': 50, 'ema_slow': 100,
    'pullback_min': 0.25, 'pullback_max': 1.8,
    'rsi_period': 14, 'rsi_buy_max': 58, 'rsi_sell_min': 42,
    'atr_period': 14, 'atr_lookback': 200,
    'atr_low_pct': 12, 'atr_high_pct': 88,
    'compress_bars': 18, 'compress_atr_mult': 0.65, 'breakout_min': 0.12,
    'risk_pct': 0.004, 'atr_stop': 1.6, 'atr_target': 2.8,   # v16.5 optimized
    'hold_bars': 14, 'cooldown': 4, 'max_consec_loss': 3,
    'max_daily_loss_pct': 0.025,
    'use_trailing': True, 'trail_start': 0.6, 'trail_dist': 0.7,  # v16.5 optimized
    'use_be': True, 'be_trigger': 1.0,
    'max_spread_pts': 0,  # disabled in backtest
}


# ─── INDICATORS (same as backtest) ─────────────────────────────────
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


# ─── BACKTEST (returns list of R-multiples and PnL) ───────────────
def collect_trades(m5_data, m15_data, specs, params, start_idx=250):
    """Run v16 backtest and collect R-multiples for Monte Carlo."""
    close5 = m5_data['close']
    high5 = m5_data['high']
    low5 = m5_data['low']
    close15 = m15_data['close']
    p = {**{
        'max_daily_loss_pct': 0.025,
        'max_spread_pts': 0,
    }, **params}

    ema_fast_15 = ema(close15, p['ema_fast'])
    ema_mid_15 = ema(close15, p['ema_mid'])
    ema_slow_15 = ema(close15, p['ema_slow'])
    ema_fast_5 = ema(close5, p['ema_fast'])
    rsi_5 = rsi(close5, p['rsi_period'])
    atr_5 = atr(high5, low5, close5, p['atr_period'])
    m5_to_m15 = np.arange(len(close5)) // 3

    r_multiples = []
    pnl_list = []
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

    for i in range(start_idx, len(close5)):
        if np.isnan(atr_5[i]) or np.isnan(ema_fast_5[i]) or np.isnan(rsi_5[i]):
            continue
        m15_idx = min(m5_to_m15[i], len(close15) - 1)
        if m15_idx < 1 or np.isnan(ema_fast_15[m15_idx]):
            continue

        # Daily reset
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

        # Spread filter (disabled in backtest)
        if p.get('max_spread_pts', 0) > 0:
            if specs['spread_pts'] > p['max_spread_pts']:
                continue

        if in_position:
            pos_bars += 1
            bid = close5[i]
            ask = close5[i]
            closed = False
            exit_price = 0.0

            # Time exit
            if pos_bars >= p['hold_bars']:
                closed, exit_price = True, close5[i]

            # SL / TP
            if not closed:
                if pos_dir > 0:
                    if bid <= pos_sl: closed, exit_price = True, pos_sl
                    elif bid >= pos_tp: closed, exit_price = True, pos_tp
                else:
                    if ask >= pos_sl: closed, exit_price = True, pos_sl
                    elif ask <= pos_tp: closed, exit_price = True, pos_tp

            # Breakeven
            if not closed and p['use_be']:
                be = p['be_trigger'] * atr_5[i]
                if pos_dir > 0 and bid >= pos_entry + be and pos_sl < pos_entry:
                    pos_sl = pos_entry + 2 * specs['point']
                elif pos_dir < 0 and ask <= pos_entry - be and pos_sl > pos_entry:
                    pos_sl = pos_entry - 2 * specs['point']

            # Trailing
            if not closed and p['use_trailing']:
                ts = p['trail_start'] * atr_5[i]
                td = p['trail_dist'] * atr_5[i]
                if pos_dir > 0 and bid >= pos_entry + ts:
                    ns = bid - td
                    if ns > pos_sl and ns > pos_entry: pos_sl = ns
                elif pos_dir < 0 and ask <= pos_entry - ts:
                    ns = ask + td
                    if ns < pos_sl and ns > pos_entry: pos_sl = ns

            if closed:
                r = (exit_price - pos_entry) / pos_orig_risk if pos_dir > 0 else (pos_entry - exit_price) / pos_orig_risk
                pnl = pos_stake * r
                r_multiples.append(r)
                pnl_list.append(pnl)
                equity += pnl
                daily_pnl += pnl
                if equity > peak_equity: peak_equity = equity

                if r < 0:
                    consec_loss += 1
                    cooldown = p['cooldown']
                else:
                    consec_loss = 0

                # v16.5 3-circuit-breaker
                if consec_loss >= p['max_consec_loss']: paused = True
                if daily_pnl < -equity * p['max_daily_loss_pct']: paused = True
                if (peak_equity - equity) > peak_equity * 0.12: paused = True

                in_position = False
            continue

        if paused or cooldown > 0:
            continue
        if atr_pct < p['atr_low_pct'] or atr_pct > p['atr_high_pct']:
            continue

        if np.isnan(ema_mid_15[m15_idx]) or np.isnan(ema_slow_15[m15_idx]):
            continue
        regime = 'RANGING'
        m15_close = close15[m15_idx]
        ef, em, es = ema_fast_15[m15_idx], ema_mid_15[m15_idx], ema_slow_15[m15_idx]
        if ef > em > es and m15_close > ef: regime = 'BULLISH'
        elif ef < em < es and m15_close < ef: regime = 'BEARISH'

        direction = 0
        sig_type = ''

        # Pullback
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

        # Compression breakout
        elif regime == 'RANGING':
            atr_now = atr_5[i]
            start_a = max(1, i - 100)
            avg_atr = np.mean(atr_5[start_a:i]) if i > start_a else atr_now
            if atr_now > avg_atr * p['compress_atr_mult']: continue
            compress_start = max(0, i - p['compress_bars'])
            rh = np.max(high5[compress_start:i + 1])
            rl = np.min(low5[compress_start:i + 1])
            if (rh - rl) < atr_now * 0.4: continue
            cl = close5[i]
            if cl > rh + p['breakout_min'] * atr_now: direction = 1
            elif cl < rl - p['breakout_min'] * atr_now: direction = -1
            else: continue
            if (high5[i] - low5[i]) > atr_now * 2.2: continue
            if direction > 0 and rsi_5[i] < 52: continue
            if direction < 0 and rsi_5[i] > 48: continue
            sig_type = 'BREAKOUT_UP' if direction > 0 else 'BREAKOUT_DOWN'
        else:
            continue

        # Open trade
        entry = close5[i]
        stop_dist = p['atr_stop'] * atr_5[i]
        tp_dist = p['atr_target'] * atr_5[i]
        max_stop = entry * 0.025
        if stop_dist > max_stop: stop_dist = max_stop
        if stop_dist < atr_5[i] * 0.5: stop_dist = atr_5[i] * 0.5
        sl = entry - stop_dist if direction > 0 else entry + stop_dist
        tp = entry + tp_dist if direction > 0 else entry - tp_dist
        spread_cost = specs['spread_pts'] * specs['point']
        risk_money = equity * p['risk_pct']
        risk_points = stop_dist / specs['point']
        vol = risk_money / (risk_points * (specs['tick_val'] / (specs['tick_size'] / specs['point'])))
        vol = max(specs['min_lot'], round(vol / specs['step']) * specs['step'])
        entry_adj = entry + (spread_cost / 2) * direction

        in_position = True
        pos_dir = direction
        pos_entry = entry_adj
        pos_sl = sl
        pos_tp = tp
        pos_orig_risk = stop_dist
        pos_stake = risk_money
        pos_bars = 0

    return r_multiples, pnl_list


# ─── MONTE CARLO SIMULATION ────────────────────────────────────────
def monte_carlo(r_multiples, pnls, n_sims=1000, initial_equity=10000.0):
    """Shuffle trade order and simulate equity curves."""
    n_trades = len(r_multiples)
    if n_trades < 5:
        return None

    final_equities = []
    max_drawdowns = []
    peak_equities = []
    min_equity_seen = []
    ruin_count = 0

    for _ in range(n_sims):
        # Shuffle trade order
        idx = np.random.permutation(n_trades)
        shuffled_r = [r_multiples[i] for i in idx]
        shuffled_pnl = [pnls[i] for i in idx]

        equity = initial_equity
        peak = equity
        max_dd = 0.0
        min_eq = equity

        for r, pnl in zip(shuffled_r, shuffled_pnl):
            equity += pnl
            if equity > peak: peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd: max_dd = dd
            if equity < min_eq: min_eq = equity

            # Ruin: equity drops below 50% of starting capital
            if equity < initial_equity * 0.5:
                ruin_count += 1
                break

        final_equities.append(equity)
        max_drawdowns.append(max_dd)
        peak_equities.append(peak)
        min_equity_seen.append(min_eq)

    final_arr = np.array(final_equities)
    dd_arr = np.array(max_drawdowns)

    return {
        'n_trades': n_trades,
        'n_sims': n_sims,
        'final_equity_median': float(np.median(final_arr)),
        'final_equity_mean': float(np.mean(final_arr)),
        'final_equity_5pct': float(np.percentile(final_arr, 5)),
        'final_equity_25pct': float(np.percentile(final_arr, 25)),
        'final_equity_75pct': float(np.percentile(final_arr, 75)),
        'final_equity_95pct': float(np.percentile(final_arr, 95)),
        'final_equity_worst': float(np.min(final_arr)),
        'final_equity_best': float(np.max(final_arr)),
        'max_dd_median': float(np.median(dd_arr)),
        'max_dd_mean': float(np.mean(dd_arr)),
        'max_dd_95pct': float(np.percentile(dd_arr, 95)),
        'max_dd_worst': float(np.max(dd_arr)),
        'ruin_probability': ruin_count / n_sims * 100,
        'profitable_pct': float(np.sum(final_arr > initial_equity) / n_sims * 100),
        'min_equity_median': float(np.median(min_equity_seen)),
        'min_equity_5pct': float(np.percentile(min_equity_seen, 5)),
    }


def print_mc(result, name, initial):
    if result is None:
        print(f"\n  {name}: Not enough trades for Monte Carlo")
        return
    print(f"\n  {'=' * 60}")
    print(f"  {name} — Monte Carlo ({result['n_sims']} simulations, {result['n_trades']} trades)")
    print(f"  {'=' * 60}")
    print(f"  Starting Equity:     ${initial:,.2f}")
    print(f"  ")
    print(f"  Final Equity Distribution:")
    print(f"    Best case:         ${result['final_equity_best']:,.2f}")
    print(f"    95th percentile:   ${result['final_equity_95pct']:,.2f}")
    print(f"    75th percentile:   ${result['final_equity_75pct']:,.2f}")
    print(f"    Median:            ${result['final_equity_median']:,.2f}")
    print(f"    25th percentile:   ${result['final_equity_25pct']:,.2f}")
    print(f"    5th percentile:    ${result['final_equity_5pct']:,.2f}")
    print(f"    Worst case:        ${result['final_equity_worst']:,.2f}")
    print(f"  ")
    print(f"  Max Drawdown Distribution:")
    print(f"    Median:            {result['max_dd_median']:.1f}%")
    print(f"    Mean:              {result['max_dd_mean']:.1f}%")
    print(f"    95th percentile:   {result['max_dd_95pct']:.1f}%")
    print(f"    Worst case:        {result['max_dd_worst']:.1f}%")
    print(f"  ")
    print(f"  Risk Metrics:")
    print(f"    Ruin probability:  {result['ruin_probability']:.1f}% (equity < 50%)")
    print(f"    Profitable:        {result['profitable_pct']:.1f}% of simulations")
    print(f"    Min equity (med):  ${result['min_equity_median']:,.2f}")
    print(f"    Min equity (5%):   ${result['min_equity_5pct']:,.2f}")

    # Verdict
    if result['ruin_probability'] < 1:
        verdict = "✅ EXCELLENT — near-zero ruin risk"
    elif result['ruin_probability'] < 5:
        verdict = "✅ GOOD — very low ruin risk"
    elif result['ruin_probability'] < 15:
        verdict = "⚠️ MODERATE — some sequences cause significant drawdown"
    else:
        verdict = "❌ FRAGILE — high ruin risk in bad sequences"
    print(f"\n  VERDICT: {verdict}")
    print(f"  {'=' * 60}")


def main():
    mt5.initialize()
    now = datetime.now()
    start = now - timedelta(days=90)
    N_SIMS = 1000

    print("=" * 70)
    print(f"  MONTE CARLO STRESS TEST — v16.5 Optimized Engine")
    print(f"  {N_SIMS} shuffled simulations per symbol")
    print(f"  Period: {start.strftime('%b %d')} – {now.strftime('%b %d, %Y')}")
    print("=" * 70)

    for sym_name, specs in SYMBOLS.items():
        params = OPT_V75 if '75' in sym_name else OPT_V100
        sym_short = 'V75' if '75' in sym_name else 'V100'
        initial = 10000.0

        m5 = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M5, start, now)
        m15 = mt5.copy_rates_range(sym_name, mt5.TIMEFRAME_M15, start, now)
        if m5 is None or m15 is None:
            print(f"\n  {sym_name}: No data")
            continue

        r_mults, pnls = collect_trades(m5, m15, specs, params, start_idx=250)
        print(f"\n  {sym_name}: Collected {len(r_mults)} trades")

        if len(r_mults) < 10:
            print("  Not enough trades for Monte Carlo (need ≥10)")
            # Still show what we have
            if len(r_mults) > 0:
                wins = sum(1 for r in r_mults if r > 0)
                print(f"  Partial stats: WR={wins/len(r_mults)*100:.1f}%, "
                      f"AvgR={np.mean(r_mults):.3f}, TotalR={sum(r_mults):.2f}")
            continue

        # Original trade stats
        wins = sum(1 for r in r_mults if r > 0)
        print(f"  Original: WR={wins/len(r_mults)*100:.1f}%, "
              f"AvgR={np.mean(r_mults):.3f}, "
              f"MedianR={np.median(r_mults):.3f}")

        result = monte_carlo(r_mults, pnls, n_sims=N_SIMS, initial_equity=initial)
        print_mc(result, sym_name, initial)

        # Streak analysis
        max_consec_loss = 0
        cur_loss = 0
        for r in r_mults:
            if r <= 0:
                cur_loss += 1
                max_consec_loss = max(max_consec_loss, cur_loss)
            else:
                cur_loss = 0
        print(f"\n  Streak Analysis (original order):")
        print(f"    Max consecutive losses: {max_consec_loss}")
        max_consec_win = 0
        cur_win = 0
        for r in r_mults:
            if r > 0:
                cur_win += 1
                max_consec_win = max(max_consec_win, cur_win)
            else:
                cur_win = 0
        print(f"    Max consecutive wins:   {max_consec_win}")

        # R-multiple distribution
        sorted_r = sorted(r_mults)
        print(f"\n  R-Multiple Distribution:")
        print(f"    Best trade:  {max(r_mults):.3f}R")
        print(f"    75th pct:    {np.percentile(r_mults, 75):.3f}R")
        print(f"    Median:      {np.median(r_mults):.3f}R")
        print(f"    25th pct:    {np.percentile(r_mults, 25):.3f}R")
        print(f"    Worst trade: {min(r_mults):.3f}R")

    mt5.shutdown()
    print(f"\n{'=' * 70}")
    print(f"  MONTE CARLO COMPLETE (v16.5)")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
