#!/usr/bin/env python
"""
MITEMSHUB AI — Reinforcement Learning Engine
Analyzes past trades, identifies patterns in wins vs losses,
and auto-optimizes parameters for the next iteration.
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DATA_DIR, exist_ok=True)


# ─── GARCH Forecaster ──────────────────────────────────────────────
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
    """Run a single backtest with given parameters. Returns trade list."""
    z_entry = params['z_entry']
    vol_ratio = params['vol_ratio']
    min_revert = params['min_revert']
    stop_mult = params['stop_mult']
    target_mult = params['target_mult']
    min_rr = params['min_rr']
    hold_bars = params['hold_bars']
    trail_be_r = params.get('trail_be_r', 2.0)
    trail_behind_r = params.get('trail_behind_r', 0.5)
    cooldown_bars = params.get('cooldown_bars', 5)
    confirm = params.get('confirm', True)

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

        # ─── MANAGE OPEN POSITION ────────────────────────────────
        if in_pos:
            bars_held = bars_seen - pos_bar
            risk_dist = abs(pos_entry - pos_sl)
            current_r = (c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0

            if not pos_trail_active and current_r >= trail_be_r:
                pos_trail_active = True
                new_sl = pos_entry + pos_dir * risk_dist * 0.1
                if pos_dir > 0:
                    pos_sl = max(pos_sl, new_sl)
                else:
                    pos_sl = min(pos_sl, new_sl)

            if pos_trail_active:
                trail_distance = risk_dist * trail_behind_r
                if pos_dir > 0:
                    pos_sl = max(pos_sl, c - trail_distance)
                else:
                    pos_sl = min(pos_sl, c + trail_distance)

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
                    'num': len(trades) + 1,
                    'time': ts,
                    'side': 'BUY' if pos_dir > 0 else 'SELL',
                    'entry': pos_entry,
                    'exit': slipped,
                    'reason': reason,
                    'rr': rr,
                    'pnl': pnl,
                    'equity': equity,
                    'bars_held': bars_held,
                    'z_score': pending_z,
                })

                if pnl < -1.0:
                    cooldown = cooldown_bars

                in_pos = False
                pos_dir = 0
                pos_trail_active = False
                continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # Confirmation
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
                if risk_dist <= 0:
                    pending_signal = 0
                    continue
                rr = abs(tp - c) / risk_dist
                if rr < min_rr:
                    pending_signal = 0
                    continue
                in_pos = True
                pos_dir = direction
                pos_entry = c
                pos_sl = sl
                pos_tp = tp
                pos_bar = bars_seen
                pos_stake = equity * 0.005
                pos_trail_active = False
                pending_signal = 0
                continue
            else:
                pending_signal = 0
                continue

        # Entry
        if in_pos or bars_seen < 60 or garch.observations() < 30:
            continue
        if sigma_ema <= 0 or prev_sigma <= 0:
            continue
        if not (prev_sigma > vol_ratio * sigma_ema):
            continue
        if min_revert > 0:
            rev = zbuf.mean_revert_signal(garch.last_z)
            if rev < min_revert:
                continue
        z_dev = math.log(c / ema) / max(prev_sigma, 1e-12)
        if abs(z_dev) < z_entry:
            continue
        pending_signal = -1 if z_dev > 0 else 1
        pending_z = z_dev

    # Close open
    if in_pos:
        last_c = rates[-1]['close']
        risk_dist = abs(pos_entry - pos_sl)
        rr = (last_c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
        pnl = pos_stake * rr
        equity += pnl
        trades.append({
            'num': len(trades) + 1, 'time': 'FORCE', 'side': 'BUY' if pos_dir > 0 else 'SELL',
            'entry': pos_entry, 'exit': last_c, 'reason': 'FORCE', 'rr': rr, 'pnl': pnl,
            'equity': equity, 'bars_held': 0, 'z_score': 0,
        })

    return trades


def score_trades(trades):
    """Score a set of trades. Higher = better."""
    if len(trades) < 5:
        return -999

    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades)

    # Equity curve metrics
    equity = 10000.0
    peak = 10000.0
    max_dd = 0.0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    # Composite score: penalize drawdowns, reward consistency
    score = 0
    score += total_pnl / 100  # P&L component
    score += win_rate * 20     # Win rate bonus
    score -= max_dd * 100      # Drawdown penalty
    score -= len(losses) * 0.5 # Loss count penalty

    # Streak penalty
    max_consec = 0
    streak = 0
    for t in trades:
        if t['pnl'] <= 0:
            streak += 1
            max_consec = max(max_consec, streak)
        else:
            streak = 0
    score -= max_consec * 1.0

    return score


def main():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed:", mt5.last_error())
        return

    symbol = "Volatility 75 Index"
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 8640)
    mt5.shutdown()

    if rates is None or len(rates) < 200:
        print("[ERROR] Not enough data")
        return

    print("=" * 100)
    print("  MITEMSHUB AI — REINFORCEMENT LEARNING ENGINE")
    print("  Iterative optimization: analyze trades, learn patterns, improve")
    print("=" * 100)
    print()

    # ─── ITERATION 1: Current v4 baseline ────────────────────────
    v4_params = {
        'z_entry': 2.0, 'vol_ratio': 1.03, 'min_revert': 0.02,
        'stop_mult': 0.15, 'target_mult': 1.2, 'min_rr': 1.8,
        'hold_bars': 24, 'trail_be_r': 2.0, 'trail_behind_r': 0.5,
        'cooldown_bars': 5, 'confirm': True,
    }

    print("  ITERATION 1: v4 Baseline")
    trades_v4 = run_backtest(rates, v4_params)
    score_v4 = score_trades(trades_v4)
    wins_v4 = len([t for t in trades_v4 if t['pnl'] > 0])
    losses_v4 = len([t for t in trades_v4 if t['pnl'] <= 0])
    pnl_v4 = sum(t['pnl'] for t in trades_v4)
    wr_v4 = wins_v4 / len(trades_v4) * 100 if trades_v4 else 0

    print(f"    Trades: {len(trades_v4)} | Wins: {wins_v4} | Losses: {losses_v4}")
    print(f"    Win Rate: {wr_v4:.1f}% | Total P&L: ${pnl_v4:+,.2f} | Score: {score_v4:.1f}")
    print()

    # ─── Analyze losses to find patterns ──────────────────────────
    print("  LOSS ANALYSIS:")
    losing_trades = [t for t in trades_v4 if t['pnl'] <= 0]

    # Group by z-score at entry
    z_buckets = {'2.0-2.5': [], '2.5-3.0': [], '3.0-4.0': [], '4.0+': []}
    for t in losing_trades:
        z = abs(t.get('z_score', 0))
        if z < 2.5: z_buckets['2.0-2.5'].append(t)
        elif z < 3.0: z_buckets['2.5-3.0'].append(t)
        elif z < 4.0: z_buckets['3.0-4.0'].append(t)
        else: z_buckets['4.0+'].append(t)

    print("    Losses by Z-Score at Entry:")
    for bucket, trades_list in z_buckets.items():
        if trades_list:
            avg_loss = sum(t['pnl'] for t in trades_list) / len(trades_list)
            print(f"      z={bucket}: {len(trades_list)} trades, avg loss ${avg_loss:+.2f}")

    # Group by duration
    dur_buckets = {'0-10min': [], '10-30min': [], '30-60min': [], '60min+': []}
    for t in losing_trades:
        d = t['bars_held'] * 5
        if d < 10: dur_buckets['0-10min'].append(t)
        elif d < 30: dur_buckets['10-30min'].append(t)
        elif d < 60: dur_buckets['30-60min'].append(t)
        else: dur_buckets['60min+'].append(t)

    print("    Losses by Duration:")
    for bucket, trades_list in dur_buckets.items():
        if trades_list:
            avg_loss = sum(t['pnl'] for t in trades_list) / len(trades_list)
            print(f"      {bucket}: {len(trades_list)} trades, avg loss ${avg_loss:+.2f}")

    # Wins analysis
    winning_trades = [t for t in trades_v4 if t['pnl'] > 0]
    print("\n  WIN ANALYSIS:")
    win_reasons = {}
    for t in winning_trades:
        r = t['reason']
        if r not in win_reasons:
            win_reasons[r] = {'count': 0, 'total_pnl': 0, 'total_rr': 0}
        win_reasons[r]['count'] += 1
        win_reasons[r]['total_pnl'] += t['pnl']
        win_reasons[r]['total_rr'] += t['rr']

    for reason, data in win_reasons.items():
        avg_pnl = data['total_pnl'] / data['count']
        avg_rr = data['total_rr'] / data['count']
        print(f"    {reason}: {data['count']} trades, avg P&L=${avg_pnl:+.2f}, avg R={avg_rr:+.3f}")

    print()

    # ─── ITERATION 2: Optimize based on analysis ──────────────────
    print("  ITERATION 2: Optimized (learning from losses)")
    print("    Changes:")
    print("    - Higher z-entry (2.3 vs 2.0): filter weak signals")
    print("    - Wider stop (0.18 vs 0.15): avoid premature stops")
    print("    - Tighter trail (0.3 vs 0.5): lock profits faster")
    print("    - Longer hold (30 vs 24): more time for reversal")
    print("    - Higher min RR (2.0 vs 1.8): only take quality setups")
    print()

    v5_params = {
        'z_entry': 2.3, 'vol_ratio': 1.03, 'min_revert': 0.02,
        'stop_mult': 0.18, 'target_mult': 1.3, 'min_rr': 2.0,
        'hold_bars': 30, 'trail_be_r': 1.5, 'trail_behind_r': 0.3,
        'cooldown_bars': 5, 'confirm': True,
    }

    trades_v5 = run_backtest(rates, v5_params)
    score_v5 = score_trades(trades_v5)
    wins_v5 = len([t for t in trades_v5 if t['pnl'] > 0])
    losses_v5 = len([t for t in trades_v5 if t['pnl'] <= 0])
    pnl_v5 = sum(t['pnl'] for t in trades_v5)
    wr_v5 = wins_v5 / len(trades_v5) * 100 if trades_v5 else 0

    print(f"    Trades: {len(trades_v5)} | Wins: {wins_v5} | Losses: {losses_v5}")
    print(f"    Win Rate: {wr_v5:.1f}% | Total P&L: ${pnl_v5:+,.2f} | Score: {score_v5:.1f}")
    print()

    # ─── ITERATION 3: Grid search for best parameters ─────────────
    print("  ITERATION 3: Grid Search (100+ configurations)")
    print("    Searching optimal z_entry x stop_mult x hold_bars x trail...")
    print()

    best_score = -999
    best_params = None
    best_trades = None
    configs_tested = 0

    for z_entry in [1.8, 2.0, 2.2, 2.5]:
        for stop_mult in [0.12, 0.15, 0.18, 0.20, 0.25]:
            for hold_bars in [12, 18, 24, 30, 36]:
                for trail_be_r in [1.0, 1.5, 2.0, 2.5]:
                    for target_mult in [0.8, 1.0, 1.2, 1.5]:
                        params = {
                            'z_entry': z_entry, 'vol_ratio': 1.03, 'min_revert': 0.02,
                            'stop_mult': stop_mult, 'target_mult': target_mult, 'min_rr': 1.8,
                            'hold_bars': hold_bars, 'trail_be_r': trail_be_r, 'trail_behind_r': 0.3,
                            'cooldown_bars': 5, 'confirm': True,
                        }
                        trades = run_backtest(rates, params)
                        score = score_trades(trades)
                        configs_tested += 1

                        if score > best_score:
                            best_score = score
                            best_params = params.copy()
                            best_trades = trades
                            wins = len([t for t in trades if t['pnl'] > 0])
                            pnl = sum(t['pnl'] for t in trades)
                            wr = wins / len(trades) * 100 if trades else 0
                            print(f"      NEW BEST: z={z_entry} stop={stop_mult} hold={hold_bars} trail={trail_be_r} tgt={target_mult} "
                                  f"| {len(trades)} trades {wr:.0f}% WR ${pnl:+,.0f} score={score:.1f}")

    print(f"\n    Tested {configs_tested} configurations")

    # ─── FINAL RESULTS ────────────────────────────────────────────
    print()
    print("=" * 100)
    print("  REINFORCEMENT LEARNING RESULTS")
    print("=" * 100)
    print()
    print("  ITERATION COMPARISON:")
    print(f"    v4 Baseline:  {len(trades_v4):3d} trades | {wr_v4:5.1f}% WR | ${pnl_v4:+8,.2f} P&L | score={score_v4:.1f}")
    print(f"    v5 Tuned:     {len(trades_v5):3d} trades | {wr_v5:5.1f}% WR | ${pnl_v5:+8,.2f} P&L | score={score_v5:.1f}")

    if best_trades:
        wins_b = len([t for t in best_trades if t['pnl'] > 0])
        pnl_b = sum(t['pnl'] for t in best_trades)
        wr_b = wins_b / len(best_trades) * 100 if best_trades else 0
        print(f"    v6 OPTIMAL:   {len(best_trades):3d} trades | {wr_b:5.1f}% WR | ${pnl_b:+8,.2f} P&L | score={best_score:.1f}")

        # Drawdown
        equity = 10000.0
        peak = 10000.0
        max_dd = 0.0
        for t in best_trades:
            equity += t['pnl']
            peak = max(peak, equity)
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)

        print()
        print("  OPTIMAL PARAMETERS (v6):")
        for k, v in best_params.items():
            print(f"    {k}: {v}")

        print()
        print(f"  FINAL STATISTICS:")
        print(f"    Net Return:      ${pnl_b:+,.2f} ({pnl_b/100:.1f}%)")
        print(f"    Max Drawdown:    {max_dd*100:.2f}%")
        print(f"    Profit Factor:   ", end="")
        gp = sum(t['pnl'] for t in best_trades if t['pnl'] > 0)
        gl = abs(sum(t['pnl'] for t in best_trades if t['pnl'] < 0))
        print(f"{gp/gl:.2f}" if gl > 0 else "N/A")

        # Improvement
        if pnl_b > pnl_v4:
            improvement = (pnl_b - pnl_v4) / abs(pnl_v4) * 100 if pnl_v4 != 0 else 999
            print(f"    vs v4:          +{improvement:.1f}% improvement")

        print()

        # Show all v6 trades
        print("  v6 TRADE LOG:")
        print(f"  {'#':>3} | {'TIME':16} | {'SIDE':4} | {'ENTRY':>8} | {'EXIT':>8} | {'REASON':5} | {'R':>6} | {'P&L':>8} | {'EQUITY':>10}")
        print("  " + "-" * 82)
        for t in best_trades:
            c_color = "\033[92m" if t['pnl'] > 0 else "\033[91m"
            reset = "\033[0m"
            print(f"  {c_color}{t['num']:3d} | {t['time']:16} | {t['side']:4s} | {t['entry']:8.2f} | {t['exit']:8.2f} | {t['reason']:5s} | {t['rr']:+6.3f} | {t['pnl']:+8.2f} | ${t['equity']:>8.2f}{reset}")

    print()
    print("=" * 100)

    # Save optimal params
    if best_params:
        with open(os.path.join(DATA_DIR, 'optimal_params.json'), 'w') as f:
            json.dump({
                'version': 'v6',
                'params': best_params,
                'stats': {
                    'trades': len(best_trades),
                    'wins': wins_b if best_trades else 0,
                    'win_rate': wr_b if best_trades else 0,
                    'total_pnl': pnl_b if best_trades else 0,
                    'max_dd': max_dd if best_trades else 0,
                    'score': best_score,
                },
                'timestamp': datetime.now().isoformat(),
            }, f, indent=2)
        print(f"\n  Optimal parameters saved to data/optimal_params.json")


if __name__ == "__main__":
    main()
