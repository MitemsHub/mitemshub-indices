#!/usr/bin/env python
"""
MITEMSHUB AI — Cross-Symbol Comparison
Runs the v6 optimal strategy on both Volatility 75 and Volatility 100
to find which symbol performs better.
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


class GarchForecaster:
    def __init__(self, omega, alpha, gamma, beta):
        self.omega, self.alpha, self.gamma, self.beta = omega, alpha, gamma, beta
        self.log_sigma2 = 0.0
        self.last_z = 0.0
        self.n_obs = 0
        self._sum = 0.0
        self._sq_sum = 0.0

    def update(self, log_ret):
        self.n_obs += 1
        self._sum += log_ret
        self._sq_sum += log_ret * log_ret
        if self.n_obs < 10:
            if self.n_obs == 1:
                self.log_sigma2 = math.log(max(log_ret * log_ret, 1e-12))
            else:
                self.log_sigma2 = math.log(max(self._sq_sum / self.n_obs, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self.last_z = log_ret / max(sigma, 1e-12)
            return sigma
        prev_sigma = math.exp(self.log_sigma2 / 2.0)
        z = log_ret / max(prev_sigma, 1e-12)
        self.log_sigma2 = self.omega + self.alpha * abs(z) + self.gamma * z + self.beta * self.log_sigma2
        sigma = math.exp(self.log_sigma2 / 2.0)
        self.last_z = z
        return sigma

    def observations(self):
        return self.n_obs


class ZRingBuffer:
    def __init__(self, size=50):
        self.ring = [0.0] * size
        self.head = 0
        self.count = 0
    def push(self, z):
        self.ring[self.head] = z
        self.head = (self.head + 1) % len(self.ring)
        if self.count < len(self.ring): self.count += 1
    def mean_revert_signal(self, z_t):
        if self.count < 5: return 0.0
        recent = sum(1 for k in range(min(10, self.count)) if abs(self.ring[(self.head - 1 - k) % len(self.ring)]) > 2.0)
        az = abs(z_t)
        if az < 1.0: return 0.0
        if az < 2.0: return min(0.3, recent * 0.05)
        if az < 3.0: return min(0.6, 0.3 + recent * 0.05)
        return min(0.9, 0.5 + recent * 0.07)


def run_backtest(rates, params):
    z_entry = params['z_entry']
    vol_ratio = params['vol_ratio']
    min_revert = params['min_revert']
    stop_mult = params['stop_mult']
    target_mult = params['target_mult']
    min_rr = params['min_rr']
    hold_bars = params['hold_bars']
    trail_be_r = params.get('trail_be_r', 1.0)
    trail_behind_r = params.get('trail_behind_r', 0.3)
    cooldown_bars = params.get('cooldown_bars', 5)

    garch = GarchForecaster(-1.884103, 0.142169, -0.073285, 0.852741)
    zbuf = ZRingBuffer()
    equity = 10000.0
    peak_equity = 10000.0
    bars_seen = 0
    prev_close = 0.0
    ema = 0.0
    sigma = 0.0
    sigma_ema = 0.0

    in_pos = False
    pos_dir = 0
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_bar = 0
    pos_stake = 0.0
    pos_trail_active = False
    cooldown = 0
    pending_signal = 0
    pending_z = 0.0
    trades = []

    for i, rate in enumerate(rates):
        c = rate['close']
        h = rate['high']
        l = rate['low']
        t = rate['time']
        ts = datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
        bars_seen += 1

        if prev_close <= 0:
            prev_close = c; ema = c
            continue

        log_ret = math.log(c / prev_close) if prev_close > 0 else 0
        prev_close = c

        prev_sigma = sigma
        sigma = garch.update(log_ret)
        if garch.observations() >= 10:
            zbuf.push(garch.last_z)

        sa = 2.0 / 31.0
        sigma_ema = sigma if sigma_ema <= 0 else sigma_ema * (1 - sa) + sigma * sa
        ea = 2.0 / 21.0
        ema = ema * (1 - ea) + c * ea

        if in_pos:
            bars_held = bars_seen - pos_bar
            risk_dist = abs(pos_entry - pos_sl)
            current_r = (c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0

            if not pos_trail_active and current_r >= trail_be_r:
                pos_trail_active = True
                new_sl = pos_entry + pos_dir * risk_dist * 0.1
                if pos_dir > 0: pos_sl = max(pos_sl, new_sl)
                else: pos_sl = min(pos_sl, new_sl)

            if pos_trail_active:
                trail_distance = risk_dist * trail_behind_r
                if pos_dir > 0: pos_sl = max(pos_sl, c - trail_distance)
                else: pos_sl = min(pos_sl, c + trail_distance)

            exit_price = 0
            reason = ""
            if pos_dir > 0:
                if l <= pos_sl: exit_price, reason = pos_sl, "TRAIL" if pos_trail_active else "STOP"
                elif h >= pos_tp: exit_price, reason = pos_tp, "TARGET"
            else:
                if h >= pos_sl: exit_price, reason = pos_sl, "TRAIL" if pos_trail_active else "STOP"
                elif l <= pos_tp: exit_price, reason = pos_tp, "TARGET"

            if not reason and bars_held >= hold_bars:
                exit_price, reason = c, "TIME"

            if reason:
                slipped = exit_price - 0.05 if pos_dir > 0 else exit_price + 0.05
                rr = (slipped - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
                pnl = pos_stake * rr
                equity += pnl
                trades.append({
                    'num': len(trades) + 1, 'time': ts,
                    'side': 'BUY' if pos_dir > 0 else 'SELL',
                    'entry': pos_entry, 'exit': slipped,
                    'reason': reason, 'rr': rr, 'pnl': pnl,
                    'equity': equity, 'bars_held': bars_held,
                })
                if pnl < -1.0: cooldown = cooldown_bars
                in_pos = False; pos_dir = 0; pos_trail_active = False
                continue

        if cooldown > 0:
            cooldown -= 1
            continue

        if pending_signal != 0:
            bar_open = rate['open']
            confirmed = (pending_signal > 0 and c > bar_open) or (pending_signal < 0 and c < bar_open)
            if confirmed:
                direction = pending_signal
                stop_dist = c * stop_mult * sigma
                target_dist = c * target_mult * sigma
                sl = (c - stop_dist) if direction > 0 else (c + stop_dist)
                tp = (c + target_dist) if direction > 0 else (c - target_dist)
                risk_dist = abs(c - sl)
                if risk_dist <= 0: pending_signal = 0; continue
                rr = abs(tp - c) / risk_dist
                if rr < min_rr: pending_signal = 0; continue
                in_pos = True; pos_dir = direction; pos_entry = c; pos_sl = sl; pos_tp = tp
                pos_bar = bars_seen; pos_stake = equity * 0.005; pos_trail_active = False
                pending_signal = 0
                continue
            else:
                pending_signal = 0
                continue

        if in_pos or bars_seen < 60 or garch.observations() < 30: continue
        if sigma_ema <= 0 or prev_sigma <= 0: continue
        if not (prev_sigma > vol_ratio * sigma_ema): continue
        if min_revert > 0:
            rev = zbuf.mean_revert_signal(garch.last_z)
            if rev < min_revert: continue
        z_dev = math.log(c / ema) / max(prev_sigma, 1e-12)
        if abs(z_dev) < z_entry: continue
        pending_signal = -1 if z_dev > 0 else 1
        pending_z = z_dev

    if in_pos:
        last_c = rates[-1]['close']
        risk_dist = abs(pos_entry - pos_sl)
        rr = (last_c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
        pnl = pos_stake * rr
        equity += pnl
        trades.append({'num': len(trades)+1, 'time': 'FORCE', 'side': 'BUY' if pos_dir > 0 else 'SELL',
            'entry': pos_entry, 'exit': last_c, 'reason': 'FORCE', 'rr': rr, 'pnl': pnl,
            'equity': equity, 'bars_held': 0})

    return trades, equity


def score_trades(trades):
    if len(trades) < 5: return -999
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    win_rate = len(wins) / len(trades)
    equity = 10000.0; peak = 10000.0; max_dd = 0.0
    for t in trades:
        equity += t['pnl']; peak = max(peak, equity)
        dd = (peak - equity) / peak; max_dd = max(max_dd, dd)
    max_consec = 0; streak = 0
    for t in trades:
        if t['pnl'] <= 0: streak += 1; max_consec = max(max_consec, streak)
        else: streak = 0
    return (total_pnl / 100) + (win_rate * 20) - (max_dd * 100) - (len(trades) - len(wins)) * 0.5 - max_consec * 1.0


def optimize_and_test(symbol, rates):
    """Grid search on this symbol and return best result."""
    best_score = -999
    best_params = None
    best_trades = None
    best_equity = 10000.0
    configs = 0

    for z_entry in [1.8, 2.0, 2.2, 2.5, 2.8]:
        for stop_mult in [0.10, 0.12, 0.15, 0.18, 0.20]:
            for hold_bars in [12, 18, 24, 30]:
                for trail_be_r in [1.0, 1.5, 2.0]:
                    for target_mult in [0.6, 0.8, 1.0, 1.2]:
                        params = {
                            'z_entry': z_entry, 'vol_ratio': 1.03, 'min_revert': 0.02,
                            'stop_mult': stop_mult, 'target_mult': target_mult, 'min_rr': 1.8,
                            'hold_bars': hold_bars, 'trail_be_r': trail_be_r, 'trail_behind_r': 0.3,
                            'cooldown_bars': 5,
                        }
                        trades, equity = run_backtest(rates, params)
                        score = score_trades(trades)
                        configs += 1
                        if score > best_score:
                            best_score = score
                            best_params = params.copy()
                            best_trades = trades
                            best_equity = equity

    return best_params, best_trades, best_equity, best_score, configs


def print_results(symbol, trades, params, score, equity, configs):
    if not trades:
        print(f"  {symbol}: No trades")
        return

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100
    pnl = sum(t['pnl'] for t in trades)
    gp = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses))
    pf = gp / gl if gl > 0 else 999
    avg_win = gp / len(wins) if wins else 0
    avg_loss = gl / len(losses) if losses else 0

    equity = 10000.0; peak = 10000.0; max_dd = 0.0
    for t in trades:
        equity += t['pnl']; peak = max(peak, equity)
        dd = (peak - equity) / peak; max_dd = max(max_dd, dd)

    # Max consecutive
    max_consec = 0; streak = 0
    for t in trades:
        if t['pnl'] <= 0: streak += 1; max_consec = max(max_consec, streak)
        else: streak = 0

    # Win reasons
    win_reasons = {}
    for t in wins:
        r = t['reason']
        if r not in win_reasons: win_reasons[r] = 0
        win_reasons[r] += 1

    # Exit reasons
    exit_reasons = {}
    for t in trades:
        r = t['reason']
        if r not in exit_reasons: exit_reasons[r] = {'count': 0, 'pnl': 0}
        exit_reasons[r]['count'] += 1
        exit_reasons[r]['pnl'] += t['pnl']

    print(f"\n  {symbol}")
    print(f"  {'=' * 60}")
    print(f"  Trades:       {len(trades)}")
    print(f"  Wins:         {len(wins)} ({win_rate:.1f}%)")
    print(f"  Losses:       {len(losses)}")
    print(f"  Total P&L:    ${pnl:+,.2f} ({pnl/100:.1f}%)")
    print(f"  Profit Factor:{pf:.2f}")
    print(f"  Avg Win:      ${avg_win:+,.2f}")
    print(f"  Avg Loss:     ${-avg_loss:+,.2f}")
    print(f"  Payoff Ratio: {avg_win/avg_loss:.2f}" if avg_loss > 0 else "  Payoff Ratio: N/A")
    print(f"  Max Drawdown: {max_dd*100:.2f}%")
    print(f"  Max Consec L: {max_consec}")
    print(f"  Score:        {score:.1f}")
    print(f"  Configs:      {configs}")
    print(f"\n  Exit Reasons:")
    for reason, data in sorted(exit_reasons.items()):
        print(f"    {reason:15s}: {data['count']:3d} trades, ${data['pnl']:+10,.2f}")
    print(f"\n  OPTIMAL PARAMETERS:")
    for k, v in params.items():
        print(f"    {k}: {v}")

    # Print trade log
    print(f"\n  TRADE LOG:")
    print(f"  {'#':>3} | {'TIME':16} | {'SIDE':4} | {'ENTRY':>8} | {'EXIT':>8} | {'REASON':5} | {'R':>6} | {'P&L':>8} | {'EQUITY':>10}")
    print("  " + "-" * 82)
    for t in trades:
        c_color = "\033[92m" if t['pnl'] > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"  {c_color}{t['num']:3d} | {t['time']:16} | {t['side']:4s} | {t['entry']:8.2f} | {t['exit']:8.2f} | {t['reason']:5s} | {t['rr']:+6.3f} | {t['pnl']:+8.2f} | ${t['equity']:>8.2f}{reset}")

    return {
        'symbol': symbol, 'trades': len(trades), 'wins': len(wins),
        'win_rate': win_rate, 'pnl': pnl, 'pf': pf,
        'max_dd': max_dd, 'max_consec': max_consec, 'score': score,
    }


def main():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed:", mt5.last_error())
        return

    symbols = ["Volatility 75 Index", "Volatility 100 Index"]
    results = {}

    for symbol in symbols:
        print(f"\n{'=' * 80}")
        print(f"  Fetching data for {symbol}...")
        print(f"{'=' * 80}")

        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 8640)
        if rates is None or len(rates) < 200:
            print(f"  [SKIP] Only {len(rates) if rates else 0} bars available")
            continue

        print(f"  Got {len(rates)} M5 bars ({datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d')})")
        print(f"  Price range: {min(r['close'] for r in rates):.2f} - {max(r['close'] for r in rates):.2f}")
        print(f"  Running grid search (2,400 configs)...")

        params, trades, equity, score, configs = optimize_and_test(symbol, rates)
        result = print_results(symbol, trades, params, score, equity, configs)
        if result:
            results[symbol] = result

    # Comparison
    print(f"\n{'=' * 80}")
    print(f"  CROSS-SYMBOL COMPARISON")
    print(f"{'=' * 80}")
    print(f"\n  {'Metric':<20} | {'Volatility 75':>15} | {'Volatility 100':>15} | {'Winner':>15}")
    print(f"  {'-'*20}-+-{'-'*15}-+-{'-'*15}-+-{'-'*15}")

    for symbol in symbols:
        if symbol not in results:
            print(f"  {symbol}: Not enough data")
            continue

    if len(results) == 2:
        s75 = results["Volatility 75 Index"]
        s100 = results["Volatility 100 Index"]

        metrics = [
            ('Trades', 'trades', 'higher'),
            ('Win Rate', 'win_rate', 'higher'),
            ('Total P&L', 'pnl', 'higher'),
            ('Profit Factor', 'pf', 'higher'),
            ('Max Drawdown', 'max_dd', 'lower'),
            ('Max Consec Loss', 'max_consec', 'lower'),
            ('Score', 'score', 'higher'),
        ]

        for name, key, direction in metrics:
            v75 = s75[key]
            v100 = s100[key]

            if key == 'pnl':
                v75_str = f"${v75:+,.2f}"
                v100_str = f"${v100:+,.2f}"
            elif key in ('win_rate', 'max_dd'):
                v75_str = f"{v75:.1f}%"
                v100_str = f"{v100:.1f}%"
            elif key == 'pf':
                v75_str = f"{v75:.2f}"
                v100_str = f"{v100:.2f}"
            elif key == 'score':
                v75_str = f"{v75:.1f}"
                v100_str = f"{v100:.1f}"
            else:
                v75_str = f"{v75}"
                v100_str = f"{v100}"

            if direction == 'higher':
                winner = "Vol 75" if v75 > v100 else "Vol 100" if v100 > v75 else "TIE"
            else:
                winner = "Vol 75" if v75 < v100 else "Vol 100" if v100 < v75 else "TIE"

            print(f"  {name:<20} | {v75_str:>15} | {v100_str:>15} | {winner:>15}")

        # Overall winner
        if s75['score'] > s100['score']:
            overall = "Volatility 75 Index"
        elif s100['score'] > s75['score']:
            overall = "Volatility 100 Index"
        else:
            overall = "TIE"

        print(f"\n  OVERALL WINNER: {overall}")
        print(f"  (by composite score: Vol75={s75['score']:.1f} vs Vol100={s100['score']:.1f})")

    print(f"\n{'=' * 80}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
