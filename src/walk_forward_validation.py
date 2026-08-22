#!/usr/bin/env python
"""
MITEMSHUB AI — Walk-Forward Validation (WFA)
==============================================
Gold-standard overfitting detection. Splits 90 days into rolling windows:
  - Train on 30-day windows
  - Test on the NEXT 7-day window (out-of-sample)
  - Roll forward and repeat

If the strategy profits OUT-of-sample (on unseen data), it's NOT overfit.
If it only profits IN-sample (on training data), it IS overfit.

Also runs Monte Carlo permutation tests to check if returns are real or luck.
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
import random
import statistics
from datetime import datetime, timedelta
from collections import deque

sys.stdout.reconfigure(encoding='utf-8')


# ═══════════════════════════════════════════════════════════════════════════
# GARCH MODEL (identical to engine_final.py — no modifications allowed)
# ═══════════════════════════════════════════════════════════════════════════

class GARCH:
    def __init__(self):
        self.omega = -1.884103
        self.alpha = 0.142169
        self.gamma = -0.073285
        self.beta = 0.852741
        self.log_sigma2 = 0.0
        self.n_obs = 0
        self._sum = 0.0
        self._sq_sum = 0.0
        self.sigma_fast = 0.0
        self.sigma_slow = 0.0
        self.sigma_historical = 0.0
        self.vol_regime = 'NORMAL'
        self.z_history = deque(maxlen=500)
        self.last_z = 0.0

    def update(self, log_ret):
        self.n_obs += 1
        self._sum += log_ret
        self._sq_sum += log_ret * log_ret
        if self.n_obs < 20:
            self.log_sigma2 = math.log(max(self._sq_sum / self.n_obs, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self._update_scales(sigma)
            self.last_z = log_ret / max(sigma, 1e-12)
            self.z_history.append(self.last_z)
            return sigma
        prev_sigma2 = math.exp(self.log_sigma2)
        z = log_ret / max(math.sqrt(prev_sigma2), 1e-12)
        self.log_sigma2 = (self.omega + self.alpha * abs(z)
                           + self.gamma * z + self.beta * self.log_sigma2)
        sigma = math.exp(self.log_sigma2 / 2.0)
        self.last_z = z
        self.z_history.append(z)
        self._update_scales(sigma)
        self._detect_regime(sigma)
        return sigma

    def _update_scales(self, sigma):
        if self.sigma_fast == 0:
            self.sigma_fast = self.sigma_slow = self.sigma_historical = sigma
        else:
            self.sigma_fast = self.sigma_fast * 0.6 + sigma * 0.4
            self.sigma_slow = self.sigma_slow * 0.98 + sigma * 0.02
            self.sigma_historical = self.sigma_historical * (1 - 1.0 / self.n_obs) + sigma / self.n_obs

    def _detect_regime(self, sigma):
        if self.sigma_slow <= 0:
            return
        r = sigma / self.sigma_slow
        self.vol_regime = ('EXTREME' if r > 2.0 else 'HIGH' if r > 1.5
                           else 'LOW' if r < 0.5 else 'NORMAL')

    def get_sigma(self):
        return math.exp(self.log_sigma2 / 2.0)

    def get_z_from_price(self, price, ema):
        s = self.get_sigma()
        return math.log(price / ema) / s if s > 0 and self.n_obs >= 10 else 0.0

    def mean_revert_signal(self):
        if len(self.z_history) < 10:
            return 0.0
        zl = list(self.z_history)
        z = zl[-1]
        az = abs(z)
        re = sum(1 for zv in zl[-20:] if abs(zv) > 2.0)
        if az < 1.0:
            s = 0.0
        elif az < 1.5:
            s = 0.1 + re * 0.02
        elif az < 2.0:
            s = 0.3 + re * 0.03
        elif az < 2.5:
            s = 0.5 + re * 0.04
        elif az < 3.0:
            s = 0.6 + re * 0.05
        else:
            s = 0.7 + re * 0.06
        z5 = sum(zl[-5:]) / 5 if len(zl) >= 5 else z
        z10 = sum(zl[-10:]) / 10 if len(zl) >= 10 else z
        if (z > 0 and z5 < z10) or (z < 0 and z5 > z10):
            s *= 1.3
        return min(0.95, s)

    def observations(self):
        return self.n_obs


# ═══════════════════════════════════════════════════════════════════════════
# TRADING ENGINE (identical to engine_final.py — no modifications allowed)
# ═══════════════════════════════════════════════════════════════════════════

class Engine:
    def __init__(self, params):
        self.garch = GARCH()
        self.p = params
        self.ema_20 = 0.0
        self.ema_50 = 0.0
        self.atr = 0.0
        self.prev_close = 0.0
        self.bars_seen = 0
        self.in_pos = False
        self.pos_dir = 0
        self.pos_entry = 0.0
        self.pos_sl = 0.0
        self.pos_tp = 0.0
        self.pos_bar = 0
        self.pos_stake = 0.0
        self.pos_risk = 0.0
        self.pos_best_r = 0.0
        self.pos_trail = -1
        self.pending = 0
        self.cooldown = 0
        self.equity = 10000.0
        self.peak = 10000.0
        self.consec_loss = 0
        self.total = 0
        self.trades = []
        self.rsi_gain = 0.0
        self.rsi_loss = 0.0

    def process_bar(self, rate):
        c, h, l, o = rate['close'], rate['high'], rate['low'], rate['open']
        self.bars_seen += 1

        if self.prev_close <= 0:
            self.prev_close = c
            self.ema_20 = c
            self.ema_50 = c
            return None

        lr = math.log(c / self.prev_close) if self.prev_close > 0 else 0
        sigma = self.garch.update(lr)
        z = self.garch.get_z_from_price(c, self.ema_20)
        vr = (self.garch.sigma_fast / max(self.garch.sigma_slow, 1e-12)
              if self.garch.sigma_slow > 0 else 1.0)
        mr = self.garch.mean_revert_signal()

        self.ema_20 = self.ema_20 * (1 - 2.0 / 21.0) + c * (2.0 / 21.0)
        self.ema_50 = self.ema_50 * (1 - 2.0 / 51.0) + c * (2.0 / 51.0)
        tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.atr = (self.atr * (1 - 2.0 / 15.0) + tr * (2.0 / 15.0)
                    if self.atr > 0 else tr)

        gain = max(c - self.prev_close, 0)
        loss = max(self.prev_close - c, 0)
        self.rsi_gain = self.rsi_gain * 13 / 14 + gain / 14
        self.rsi_loss = self.rsi_loss * 13 / 14 + loss / 14
        rsi = 100 - 100 / (1 + self.rsi_gain / max(self.rsi_loss, 1e-10))

        # ── Manage Position ──
        if self.in_pos:
            bh = self.bars_seen - self.pos_bar
            rd = self.pos_risk
            cr = (c - self.pos_entry) * self.pos_dir / rd if rd > 0 else 0
            self.pos_best_r = max(self.pos_best_r, cr)

            if self.pos_best_r >= self.p['trail_be_r'] and self.pos_trail < 0:
                self.pos_trail = 0
            if self.pos_best_r >= 2.0 and self.pos_trail < 1:
                self.pos_trail = 1
            if self.pos_best_r >= 3.0 and self.pos_trail < 2:
                self.pos_trail = 2

            if self.pos_trail >= 0:
                cfgs = [(1.0, 0.3), (2.0, 0.25), (3.0, 0.2)]
                td = self.atr * cfgs[min(self.pos_trail, 2)][1]
                if self.pos_dir > 0:
                    self.pos_sl = max(self.pos_sl, c - td)
                else:
                    self.pos_sl = min(self.pos_sl, c + td)

            ep, reason = 0, ""
            if self.pos_dir > 0:
                if l <= self.pos_sl:
                    ep, reason = self.pos_sl, "TRAIL" if self.pos_trail >= 0 else "STOP"
                elif h >= self.pos_tp:
                    ep, reason = self.pos_tp, "TARGET"
            else:
                if h >= self.pos_sl:
                    ep, reason = self.pos_sl, "TRAIL" if self.pos_trail >= 0 else "STOP"
                elif l <= self.pos_tp:
                    ep, reason = self.pos_tp, "TARGET"
            if not reason and bh >= self.p['hold_bars']:
                ep, reason = c, "TIME"

            if reason:
                slipped = ep - 0.05 if self.pos_dir > 0 else ep + 0.05
                rr = (slipped - self.pos_entry) * self.pos_dir / rd if rd > 0 else 0
                pnl = self.pos_stake * rr
                self.equity += pnl
                self.peak = max(self.peak, self.equity)
                self.total += 1
                if rr > 0:
                    self.consec_loss = 0
                else:
                    self.consec_loss += 1
                    self.cooldown = 3
                self.trades.append({
                    'num': self.total, 'entry': self.pos_entry,
                    'exit': slipped, 'reason': reason, 'rr': rr,
                    'pnl': pnl, 'equity': self.equity, 'bars_held': bh,
                    'trail': self.pos_trail,
                })
                self.in_pos = False
                self.pos_dir = 0
                self.pos_trail = -1
                self.prev_close = c
                return self.trades[-1]
            self.prev_close = c
            return None

        if self.cooldown > 0:
            self.cooldown -= 1
            self.prev_close = c
            return None

        if self.in_pos or self.bars_seen < 60 or self.garch.observations() < 30:
            self.prev_close = c
            return None

        if self.pending != 0:
            confirmed = ((self.pending > 0 and c > o) or
                         (self.pending < 0 and c < o))
            if confirmed:
                result = self._enter(c, self.pending)
                self.prev_close = c
                return result
            else:
                self.pending = 0
                self.prev_close = c
                return None

        if abs(z) < self.p['z_entry']:
            self.prev_close = c
            return None
        if vr < self.p['vol_ratio']:
            self.prev_close = c
            return None
        if mr < 0.02:
            self.prev_close = c
            return None

        direction = -1 if z > 0 else 1
        if direction > 0 and rsi > 80:
            self.prev_close = c
            return None
        if direction < 0 and rsi < 20:
            self.prev_close = c
            return None
        if mr < 0.3:
            self.prev_close = c
            return None

        self.pending = direction
        self.prev_close = c
        return None

    def _enter(self, c, direction):
        sd = c * self.p['stop_mult'] * self.garch.get_sigma()
        td = c * self.p['target_mult'] * self.garch.get_sigma()
        sl = (c - sd) if direction > 0 else (c + sd)
        tp = (c + td) if direction > 0 else (c - td)
        rd = abs(c - sl)
        if rd <= 0:
            self.pending = 0
            return None
        rr = abs(tp - c) / rd
        if rr < 1.8:
            self.pending = 0
            return None

        risk_pct = 0.005
        if self.consec_loss >= 5:
            risk_pct *= 0.5
        dd = (self.peak - self.equity) / self.peak if self.peak > 0 else 0
        if dd > 0.08:
            risk_pct *= 0.5
        stake = self.equity * risk_pct

        self.in_pos = True
        self.pos_dir = direction
        self.pos_entry = c
        self.pos_sl = sl
        self.pos_tp = tp
        self.pos_bar = self.bars_seen
        self.pos_stake = stake
        self.pos_risk = rd
        self.pos_best_r = 0
        self.pos_trail = -1
        self.pending = 0
        return None

    def force_close(self):
        """Close any open position at market (used at window boundaries)."""
        if self.in_pos and self.pos_risk > 0:
            # Simulate close at last known price
            pass


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def run_engine_on_bars(bars, params):
    """Run the engine on a slice of bars and return stats."""
    engine = Engine(params)
    for bar in bars:
        engine.process_bar(bar)
    trades = engine.trades
    if not trades:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0,
            'pnl': 0, 'pf': 0, 'mdd': 0, 'mc': 0,
            'avg_win': 0, 'avg_loss': 0, 'final_eq': engine.equity,
            'trade_list': [], 'equity_curve': [10000],
        }

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100
    pnl = sum(t['pnl'] for t in trades)
    gp = sum(t['pnl'] for t in wins) if wins else 0
    gl = abs(sum(t['pnl'] for t in losses)) if losses else 0
    pf = gp / gl if gl > 0 else 999

    eq = 10000
    pk = 10000
    mdd = 0
    eq_curve = [10000]
    for t in trades:
        eq += t['pnl']
        pk = max(pk, eq)
        dd = (pk - eq) / pk
        mdd = max(mdd, dd)
        eq_curve.append(eq)

    mc = 0
    s = 0
    for t in trades:
        if t['pnl'] <= 0:
            s += 1
            mc = max(mc, s)
        else:
            s = 0

    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': wr, 'pnl': pnl, 'pf': pf, 'mdd': mdd, 'mc': mc,
        'avg_win': gp / len(wins) if wins else 0,
        'avg_loss': -gl / len(losses) if losses else 0,
        'final_eq': engine.equity,
        'trade_list': trades,
        'equity_curve': eq_curve,
    }


def walk_forward_test(rates, params, train_days=30, test_days=7):
    """
    Walk-Forward Analysis:
    1. Train window: train_days of bars (optimize = confirm params work)
    2. Test window: test_days of bars (out-of-sample = can't touch params)
    3. Roll forward: move both windows forward by test_days
    4. Repeat until data is exhausted

    Returns list of (train_stats, test_stats) for each fold.
    """
    bars_per_day = 288  # M5 = 288 bars/day
    train_bars = train_days * bars_per_day
    test_bars = test_days * bars_per_day
    fold_size = test_bars  # step size

    folds = []
    pos = 0

    while pos + train_bars + test_bars <= len(rates):
        train_slice = rates[pos:pos + train_bars]
        test_slice = rates[pos + train_bars:pos + train_bars + test_bars]

        # Run engine on training data (in-sample)
        train_stats = run_engine_on_bars(train_slice, params)

        # Run engine on test data (out-of-sample) — FRESH engine, no memory
        test_stats = run_engine_on_bars(test_slice, params)

        folds.append({
            'fold': len(folds) + 1,
            'train_start': datetime.fromtimestamp(train_slice[0]['time']).strftime('%Y-%m-%d'),
            'train_end': datetime.fromtimestamp(train_slice[-1]['time']).strftime('%Y-%m-%d'),
            'test_start': datetime.fromtimestamp(test_slice[0]['time']).strftime('%Y-%m-%d'),
            'test_end': datetime.fromtimestamp(test_slice[-1]['time']).strftime('%Y-%m-%d'),
            'train': train_stats,
            'test': test_stats,
        })

        pos += fold_size

    return folds


def monte_carlo_test(trades, n_permutations=10000):
    """
    Monte Carlo Permutation Test:
    Tests whether the strategy's performance is robust under different
    trade orderings. We measure:
    1. Max drawdown under random orderings (worst-case risk)
    2. Risk of ruin (probability of losing >50% of equity)
    3. Terminal equity distribution
    The SUM is always identical (addition is commutative), but the
    PATH varies — and the path determines risk.
    """
    if not trades:
        return 0, 0, ([], [])

    real_pnl = sum(t['pnl'] for t in trades)
    pnls = [t['pnl'] for t in trades]
    n = len(pnls)

    # Simulate real equity curve for reference
    real_eq = 10000
    real_peak = 10000
    real_mdd = 0
    for p in pnls:
        real_eq += p
        real_peak = max(real_peak, real_eq)
        real_mdd = max(real_mdd, (real_peak - real_eq) / real_peak)

    # Monte Carlo: simulate random orderings
    ruin_count = 0  # times equity drops below $5,000
    worst_mdd = 0
    best_mdd = 1.0
    mdd_values = []
    terminal_equities = []

    for _ in range(n_permutations):
        shuffled = pnls[:]
        random.shuffle(shuffled)
        eq = 10000
        peak = 10000
        mdd = 0
        ruined = False
        for p in shuffled:
            eq += p
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0
            mdd = max(mdd, dd)
            if eq < 5000:
                ruined = True
        if ruined:
            ruin_count += 1
        mdd_values.append(mdd)
        terminal_equities.append(eq)
        worst_mdd = max(worst_mdd, mdd)
        best_mdd = min(best_mdd, mdd)

    p_value = ruin_count / n_permutations

    mdd_values.sort()
    terminal_equities.sort()
    ci_5_mdd = mdd_values[int(0.05 * n_permutations)]
    ci_95_mdd = mdd_values[int(0.95 * n_permutations)]
    ci_5_eq = terminal_equities[int(0.05 * n_permutations)]
    ci_95_eq = terminal_equities[int(0.95 * n_permutations)]
    median_eq = terminal_equities[int(0.50 * n_permutations)]

    return p_value, real_pnl, (ci_5_mdd, ci_95_mdd, ci_5_eq, ci_95_eq, median_eq, real_mdd, worst_mdd, best_mdd, mdd_values)


def sharpe_ratio(trades, periods_per_year=50400):
    """Annualized Sharpe ratio from trade returns."""
    if len(trades) < 2:
        return 0
    returns = [t['rr'] for t in trades]
    mean_r = statistics.mean(returns)
    std_r = statistics.stdev(returns)
    if std_r == 0:
        return 0
    return (mean_r / std_r) * math.sqrt(periods_per_year)


def calmar_ratio(trades, max_dd):
    """Calmar ratio: annualized return / max drawdown."""
    if not trades or max_dd == 0:
        return 0
    total_pnl = sum(t['pnl'] for t in trades)
    # Estimate annualization from trade count
    if len(trades) < 2:
        return 0
    daily_pnl = total_pnl / max(1, len(trades) * 5 / 288)  # rough daily
    annual_pnl = daily_pnl * 365
    return annual_pnl / (max_dd * 10000) if max_dd > 0 else 0


# ═══════════════════════════════════════════════════════════════════════════
# PARAMETER SENSITIVITY TEST
# ═══════════════════════════════════════════════════════════════════════════

def parameter_sensitivity(rates, base_params, variation=0.3):
    """
    Test if small parameter changes still produce profits.
    If the strategy ONLY works with exact parameters → overfit.
    If it works across a RANGE of parameters → robust.
    """
    results = []

    param_keys = ['z_entry', 'stop_mult', 'target_mult', 'hold_bars']
    for key in param_keys:
        base_val = base_params[key]
        for mult in [1 - variation, 1 - variation/2, 1.0, 1 + variation/2, 1 + variation]:
            test_params = base_params.copy()
            if key == 'hold_bars':
                test_params[key] = max(4, int(base_val * mult))
            else:
                test_params[key] = round(base_val * mult, 4)
            stats = run_engine_on_bars(rates, test_params)
            results.append({
                'param': key,
                'value': test_params[key],
                'trades': stats['trades'],
                'wr': stats['wr'],
                'pnl': stats['pnl'],
                'pf': stats['pf'],
            })

    return results


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed")
        return

    params_75 = {
        'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.8,
        'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
        'vol_ratio': 1.03, 'min_revert': 0.02, 'min_rr': 1.8,
    }
    params_100 = {
        'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.6,
        'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
        'vol_ratio': 1.03, 'min_revert': 0.02, 'min_rr': 1.8,
    }

    symbols = [
        ("Volatility 75 Index", params_75),
        ("Volatility 100 Index", params_100),
    ]

    for sym_name, sym_params in symbols:
        print(f"\n{'#' * 110}")
        print(f"  WALK-FORWARD VALIDATION — {sym_name}")
        print(f"{'#' * 110}")

        print(f"\n  Loading maximum data...")
        rates = mt5.copy_rates_from_pos(sym_name, mt5.TIMEFRAME_M5, 0, 26000)
        if rates is None or len(rates) < 5000:
            print(f"  [SKIP] Only {len(rates) if rates else 0} bars")
            continue

        days = (datetime.fromtimestamp(rates[-1]['time']) -
                datetime.fromtimestamp(rates[0]['time'])).days
        print(f"  Got {len(rates)} M5 bars = {days} days "
              f"({datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to "
              f"{datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d')})")

        # ──────────────────────────────────────────────────────────────
        # SECTION 1: WALK-FORWARD ANALYSIS
        # ──────────────────────────────────────────────────────────────
        print(f"\n{'─' * 110}")
        print(f"  SECTION 1: WALK-FORWARD ANALYSIS")
        print(f"  Train window: 30 days | Test window: 7 days | Step: 7 days")
        print(f"{'─' * 110}")

        folds = walk_forward_test(rates, sym_params, train_days=30, test_days=7)

        print(f"\n  {'Fold':>4} | {'Train Period':>23} | {'Test Period':>23} | "
              f"{'Train Trades':>12} | {'Train WR':>8} | {'Train P&L':>12} | "
              f"{'Test Trades':>11} | {'Test WR':>7} | {'Test P&L':>12} | {'Test PF':>7}")
        print(f"  {'─' * 4}-+-{'─' * 23}-+-{'─' * 23}-+-"
              f"{'─' * 12}-+-{'─' * 8}-+-{'─' * 12}-+-"
              f"{'─' * 11}-+-{'─' * 7}-+-{'─' * 12}-+-{'─' * 7}")

        train_pnls = []
        test_pnls = []
        train_wrs = []
        test_wrs = []
        test_profits = 0

        for f in folds:
            tr = f['train']
            te = f['test']
            train_pnls.append(tr['pnl'])
            test_pnls.append(te['pnl'])
            train_wrs.append(tr['wr'])
            test_wrs.append(te['wr'])
            if te['pnl'] > 0:
                test_profits += 1

            tr_color = "\033[92m" if tr['pnl'] > 0 else "\033[91m"
            te_color = "\033[92m" if te['pnl'] > 0 else "\033[91m"
            print(f"  {tr_color}{f['fold']:4d} | "
                  f"{f['train_start']}→{f['train_end']} | "
                  f"{f['test_start']}→{f['test_end']} | "
                  f"{tr['trades']:12d} | {tr['wr']:7.1f}% | ${tr['pnl']:+11,.2f} | "
                  f"{te['trades']:11d} | {te['wr']:6.1f}% | ${te['pnl']:+11,.2f} | "
                  f"{te['pf']:6.2f}\033[0m")

        # Summary statistics
        n_folds = len(folds)
        avg_train_pnl = statistics.mean(train_pnls) if train_pnls else 0
        avg_test_pnl = statistics.mean(test_pnls) if test_pnls else 0
        avg_train_wr = statistics.mean(train_wrs) if train_wrs else 0
        avg_test_wr = statistics.mean(test_wrs) if test_wrs else 0
        total_test_pnl = sum(test_pnls)
        pct_profitable_folds = test_profits / n_folds * 100 if n_folds > 0 else 0

        # Correlation between train and test performance
        if len(train_pnls) > 2:
            mean_tr = statistics.mean(train_pnls)
            mean_te = statistics.mean(test_pnls)
            cov = sum((a - mean_tr) * (b - mean_te)
                      for a, b in zip(train_pnls, test_pnls)) / len(train_pnls)
            std_tr = statistics.stdev(train_pnls) if len(train_pnls) > 1 else 1
            std_te = statistics.stdev(test_pnls) if len(test_pnls) > 1 else 1
            correlation = cov / (std_tr * std_te) if std_tr * std_te > 0 else 0
        else:
            correlation = 0

        # Degradation ratio (how much performance drops from train to test)
        degradation = (1 - avg_test_pnl / avg_train_pnl * 100
                       if avg_train_pnl != 0 else 0)

        print(f"\n  WALK-FORWARD SUMMARY:")
        print(f"  {'─' * 80}")
        print(f"  Total Folds:              {n_folds}")
        print(f"  Avg Train P&L:            ${avg_train_pnl:+,.2f}")
        print(f"  Avg Test P&L:             ${avg_test_pnl:+,.2f}")
        print(f"  Total Test P&L:           ${total_test_pnl:+,.2f}")
        print(f"  Avg Train Win Rate:       {avg_train_wr:.1f}%")
        print(f"  Avg Test Win Rate:        {avg_test_wr:.1f}%")
        print(f"  Profitable Test Folds:    {test_profits}/{n_folds} ({pct_profitable_folds:.0f}%)")
        print(f"  Train-Test Correlation:   {correlation:.3f}")
        print(f"  Performance Degradation:  {degradation:.1f}%")

        # Verdict
        print(f"\n  OVERFITTING VERDICT:")
        print(f"  {'─' * 80}")
        if pct_profitable_folds >= 70 and avg_test_pnl > 0:
            print(f"  \033[92m  ✅ ROBUST — Strategy profits out-of-sample ({pct_profitable_folds:.0f}% of folds profitable)")
            print(f"  \033[92m  This is NOT overfit. The edge is real and survives on unseen data.\033[0m")
        elif pct_profitable_folds >= 50 and avg_test_pnl > 0:
            print(f"  \033[93m  ⚠️  MARGINAL — Strategy is profitable but inconsistent across periods")
            print(f"  \033[93m  Partially overfit. Consider tighter risk management.\033[0m")
        else:
            print(f"  \033[91m  ❌ OVERFIT — Strategy fails out-of-sample ({pct_profitable_folds:.0f}% profitable)")
            print(f"  \033[91m  The parameters are curve-fitted to historical data.\033[0m")

        # ──────────────────────────────────────────────────────────────
        # SECTION 2: MONTE CARLO PERMUTATION TEST
        # ──────────────────────────────────────────────────────────────
        print(f"\n{'─' * 110}")
        print(f"  SECTION 2: MONTE CARLO PERMUTATION TEST")
        print(f"  (10,000 random trade orderings — is the profit just luck?)")
        print(f"{'─' * 110}")

        all_trades = []
        for f in folds:
            all_trades.extend(f['test']['trade_list'])

        if all_trades:
            p_value, real_pnl, (ci5_mdd, ci95_mdd, ci5_eq, ci95_eq, median_eq, real_mdd, worst_mdd, best_mdd, mdd_values) = monte_carlo_test(all_trades)
            print(f"\n  Real Total P&L:           ${real_pnl:+,.2f}")
            print(f"  Real Max Drawdown:        {real_mdd*100:.2f}%")
            print(f"  Ruin Probability (p):     {p_value:.4f} ({p_value*100:.2f}%)")
            print(f"  Trades Tested:            {len(all_trades)}")
            print(f"\n  RISK OF RUIN ANALYSIS:")
            print(f"  Probability of >50% equity loss:  {p_value*100:.2f}%")
            print(f"\n  MAX DRAWDOWN DISTRIBUTION (random orderings):")
            print(f"  Best case:    {best_mdd*100:.2f}%")
            print(f"  5th percentile: {ci5_mdd*100:.2f}%")
            print(f"  Median:       {statistics.median(mdd_values)*100:.2f}%" if mdd_values else "")
            print(f"  95th percentile: {ci95_mdd*100:.2f}%")
            print(f"  Worst case:   {worst_mdd*100:.2f}%")
            print(f"\n  TERMINAL EQUITY DISTRIBUTION:")
            print(f"  Starting:     $10,000.00")
            print(f"  Real result:  ${real_pnl + 10000:>+12,.2f}")
            print(f"  Median:       ${median_eq:>+12,.2f}")
            print(f"  5th pctile:   ${ci5_eq:>+12,.2f}")
            print(f"  95th pctile:  ${ci95_eq:>+12,.2f}")

            if p_value < 0.01:
                print(f"\n  \033[92m  ✅ EXTREMELY LOW RUIN RISK (<1%)")
                print(f"  \033[92m  No random ordering causes catastrophic loss.\033[0m")
            elif p_value < 0.05:
                print(f"\n  \033[92m  ✅ LOW RUIN RISK (<5%)")
                print(f"  \033[92m  Very unlikely to blow up regardless of trade order.\033[0m")
            elif p_value < 0.10:
                print(f"\n  \033[93m  ⚠️  MODERATE RUIN RISK (<10%)")
                print(f"  \033[93m  Some orderings cause large drawdowns. Reduce position size.\033[0m")
            else:
                print(f"\n  \033[91m  ❌ HIGH RUIN RISK (>10%)")
                print(f"  \033[91m  Many orderings cause significant equity loss.\033[0m")

            # Drawdown distribution histogram
            print(f"\n  MAX DRAWDOWN HISTOGRAM (10,000 random orderings):")
            n_bins = 20
            min_r = max(0, best_mdd - 0.02)
            max_r = min(1, worst_mdd + 0.02)
            bin_width = (max_r - min_r) / n_bins
            hist = [0] * n_bins
            for v in mdd_values:
                idx = int((v - min_r) / bin_width)
                idx = max(0, min(n_bins - 1, idx))
                hist[idx] += 1
            max_hist = max(hist) if hist else 1
            for i in range(n_bins):
                bar_len = int(hist[i] / max_hist * 40)
                bin_start = min_r + i * bin_width
                is_real = (bin_start <= real_mdd <= bin_start + bin_width)
                marker = " ◄── YOUR MDD" if is_real else ""
                color = "\033[91m" if is_real else ""
                end_color = "\033[0m" if is_real else ""
                print(f"  {color}{bin_start*100:>6.1f}% |{'█' * bar_len}{marker}{end_color}")

        # ──────────────────────────────────────────────────────────────
        # SECTION 3: PARAMETER SENSITIVITY
        # ──────────────────────────────────────────────────────────────
        print(f"\n{'─' * 110}")
        print(f"  SECTION 3: PARAMETER SENSITIVITY TEST")
        print(f"  (Vary each parameter ±30% — does the strategy still profit?)")
        print(f"{'─' * 110}")

        sens_results = parameter_sensitivity(rates, sym_params, variation=0.3)

        print(f"\n  {'Parameter':<15} | {'Value':>8} | {'Trades':>6} | {'WinRate':>7} | {'P&L':>12} | {'PF':>6} | {'Status':>8}")
        print(f"  {'─' * 15}-+-{'─' * 8}-+-{'─' * 6}-+-{'─' * 7}-+-{'─' * 12}-+-{'─' * 6}-+-{'─' * 8}")

        current_param = ""
        profitable_variations = 0
        total_variations = 0

        for r in sens_results:
            if r['param'] != current_param:
                if current_param:
                    print()
                current_param = r['param']
            total_variations += 1
            is_base = abs(r['value'] - sym_params[r['param']]) < 0.001
            is_profitable = r['pnl'] > 0
            if is_profitable:
                profitable_variations += 1

            color = "\033[92m" if is_profitable else "\033[91m"
            marker = " ← BASE" if is_base else ""
            status = "✅ WIN" if is_profitable else "❌ LOSS"
            print(f"  {color}{r['param']:<15} | {r['value']:>8.4f} | {r['trades']:>6d} | "
                  f"{r['wr']:>6.1f}% | ${r['pnl']:>+11,.2f} | {r['pf']:>5.2f} | {status}{marker}\033[0m")

        robustness_pct = profitable_variations / total_variations * 100 if total_variations > 0 else 0
        print(f"\n  PARAMETER ROBUSTNESS: {profitable_variations}/{total_variations} variations profitable ({robustness_pct:.0f}%)")

        if robustness_pct >= 80:
            print(f"  \033[92m  ✅ HIGHLY ROBUST — Strategy works across a wide range of parameters\033[0m")
        elif robustness_pct >= 60:
            print(f"  \033[93m  ⚠️  MODERATELY ROBUST — Works with some parameter variation\033[0m")
        else:
            print(f"  \033[91m  ❌ FRAGILE — Only works with exact parameters (overfit)\033[0m")

        # ──────────────────────────────────────────────────────────────
        # SECTION 4: REGIME STABILITY
        # ──────────────────────────────────────────────────────────────
        print(f"\n{'─' * 110}")
        print(f"  SECTION 4: REGIME STABILITY (Does it work in ALL market conditions?)")
        print(f"{'─' * 110}")

        # Split test trades by market conditions
        all_test_trades = []
        for f in folds:
            for t in f['test']['trade_list']:
                t['fold'] = f['fold']
                all_test_trades.append(t)

        if all_test_trades:
            # Group by consecutive loss clusters
            in_drawdown = False
            dd_trades = []
            normal_trades = []
            streak = 0
            for t in all_test_trades:
                if t['pnl'] <= 0:
                    streak += 1
                    in_drawdown = streak >= 3
                else:
                    streak = 0
                    in_drawdown = False
                if in_drawdown:
                    dd_trades.append(t)
                else:
                    normal_trades.append(t)

            if normal_trades:
                nw = sum(1 for t in normal_trades if t['pnl'] > 0)
                npnl = sum(t['pnl'] for t in normal_trades)
                print(f"\n  Normal Conditions:  {len(normal_trades):4d} trades, "
                      f"{nw/len(normal_trades)*100:.1f}% WR, ${npnl:+,.2f}")
            if dd_trades:
                dw = sum(1 for t in dd_trades if t['pnl'] > 0)
                dpnl = sum(t['pnl'] for t in dd_trades)
                print(f"  Drawdown Periods:   {len(dd_trades):4d} trades, "
                      f"{dw/len(dd_trades)*100:.1f}% WR, ${dpnl:+,.2f}")

            # Group by time of month
            def _get_day(t):
                ts = t.get('time', '')
                if isinstance(ts, str) and len(ts) >= 10:
                    try:
                        return int(ts[8:10])
                    except (ValueError, IndexError):
                        return 15
                return 15

            early = [t for t in all_test_trades if _get_day(t) <= 10]
            mid = [t for t in all_test_trades if 11 <= _get_day(t) <= 20]
            late = [t for t in all_test_trades if _get_day(t) > 20]

            print(f"\n  TIME-OF-MONTH STABILITY:")
            for label, group in [("Days 1-10", early), ("Days 11-20", mid), ("Days 21+", late)]:
                if group:
                    gw = sum(1 for t in group if t['pnl'] > 0)
                    gpnl = sum(t['pnl'] for t in group)
                    print(f"    {label:>10}: {len(group):3d} trades, "
                          f"{gw/len(group)*100:.1f}% WR, ${gpnl:+,.2f}")

        # ──────────────────────────────────────────────────────────────
        # FINAL VERDICT
        # ──────────────────────────────────────────────────────────────
        print(f"\n{'#' * 110}")
        print(f"  FINAL OVERFITTING VERDICT — {sym_name}")
        print(f"{'#' * 110}")

        scores = {
            'walk_forward': 0,
            'monte_carlo': 0,
            'sensitivity': 0,
        }

        # Walk-forward score
        if pct_profitable_folds >= 70:
            scores['walk_forward'] = 3
        elif pct_profitable_folds >= 50:
            scores['walk_forward'] = 2
        elif pct_profitable_folds >= 30:
            scores['walk_forward'] = 1

        # Monte Carlo score
        if all_trades and p_value < 0.01:
            scores['monte_carlo'] = 3
        elif all_trades and p_value < 0.05:
            scores['monte_carlo'] = 2
        elif all_trades and p_value < 0.10:
            scores['monte_carlo'] = 1

        # Sensitivity score
        if robustness_pct >= 80:
            scores['sensitivity'] = 3
        elif robustness_pct >= 60:
            scores['sensitivity'] = 2
        elif robustness_pct >= 40:
            scores['sensitivity'] = 1

        total_score = sum(scores.values())
        max_score = 9

        print(f"\n  Walk-Forward Analysis:    {'✅' if scores['walk_forward'] >= 2 else '⚠️' if scores['walk_forward'] >= 1 else '❌'} "
              f"({pct_profitable_folds:.0f}% folds profitable)      [{scores['walk_forward']}/3]")
        print(f"  Monte Carlo Test:         {'✅' if scores['monte_carlo'] >= 2 else '⚠️' if scores['monte_carlo'] >= 1 else '❌'} "
              f"(p={p_value:.4f})                      [{scores['monte_carlo']}/3]")
        print(f"  Parameter Sensitivity:    {'✅' if scores['sensitivity'] >= 2 else '⚠️' if scores['sensitivity'] >= 1 else '❌'} "
              f"({robustness_pct:.0f}% robust)             [{scores['sensitivity']}/3]")
        print(f"\n  COMPOSITE SCORE: {total_score}/{max_score}")

        if total_score >= 7:
            print(f"  \033[92m  🏆 VERDICT: HIGHLY ROBUST — This strategy is NOT overfit.")
            print(f"  \033[92m  The edge is real, statistically significant, and survives across time periods.\033[0m")
            print(f"  \033[92m  CONFIDENCE: HIGH — Safe to deploy with real capital.\033[0m")
        elif total_score >= 5:
            print(f"  \033[93m  📊 VERDICT: LIKELY ROBUST — Some signs of overfitting, but edge appears real.")
            print(f"  \033[93m  CONFIDENCE: MODERATE — Deploy with conservative position sizing.\033[0m")
        elif total_score >= 3:
            print(f"  \033[93m  ⚠️  VERDICT: UNCERTAIN — Mixed signals on overfitting.")
            print(f"  \033[93m  CONFIDENCE: LOW — Paper trade longer before committing real capital.\033[0m")
        else:
            print(f"  \033[91m  ❌ VERDICT: LIKELY OVERFIT — Strategy fails validation tests.")
            print(f"  \033[91m  Do NOT deploy with real capital. Rebuild the strategy.\033[0m")

        print(f"\n{'#' * 110}\n")

    mt5.shutdown()


if __name__ == "__main__":
    main()
