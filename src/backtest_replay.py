#!/usr/bin/env python
"""
MITEMSHUB AI — BACKTEST REPLAY ENGINE
======================================
Runs the strategy and saves EVERY bar's data plus every trade's details.
The dashboard reads this file to replay trades with animations.

Output: data/backtest_replay.json
"""

import MetaTrader5 as mt5
import math
import sys
import os
import json
from datetime import datetime
from collections import deque

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
os.makedirs(DATA_DIR, exist_ok=True)


class GARCH:
    def __init__(self):
        self.omega, self.alpha, self.gamma, self.beta = -1.884103, 0.142169, -0.073285, 0.852741
        self.log_sigma2 = 0.0; self.n_obs = 0; self._sum = 0.0; self._sq_sum = 0.0
        self.sigma_fast = 0.0; self.sigma_slow = 0.0
        self.z_history = deque(maxlen=500)

    def update(self, log_ret):
        self.n_obs += 1; self._sum += log_ret; self._sq_sum += log_ret * log_ret
        if self.n_obs < 20:
            self.log_sigma2 = math.log(max(self._sq_sum / self.n_obs, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self._update_scales(sigma)
            z = log_ret / max(sigma, 1e-12)
            self.z_history.append(z)
            return sigma
        prev_sigma2 = math.exp(self.log_sigma2)
        z = log_ret / max(math.sqrt(prev_sigma2), 1e-12)
        self.log_sigma2 = self.omega + self.alpha * abs(z) + self.gamma * z + self.beta * self.log_sigma2
        sigma = math.exp(self.log_sigma2 / 2.0)
        self.z_history.append(z)
        self._update_scales(sigma)
        return sigma

    def _update_scales(self, sigma):
        if self.sigma_fast == 0:
            self.sigma_fast = self.sigma_slow = sigma
        else:
            self.sigma_fast = self.sigma_fast * 0.6 + sigma * 0.4
            self.sigma_slow = self.sigma_slow * 0.98 + sigma * 0.02

    def get_sigma(self):
        return math.exp(self.log_sigma2 / 2.0)

    def get_z(self, price, ema):
        s = self.get_sigma()
        return math.log(price / ema) / s if s > 0 and self.n_obs >= 10 else 0.0

    def mean_revert_signal(self):
        if len(self.z_history) < 10: return 0.0
        zl = list(self.z_history); z = zl[-1]; az = abs(z)
        re = sum(1 for zv in zl[-20:] if abs(zv) > 2.0)
        if az < 1.0: s = 0.0
        elif az < 1.5: s = 0.1 + re * 0.02
        elif az < 2.0: s = 0.3 + re * 0.03
        elif az < 2.5: s = 0.5 + re * 0.04
        elif az < 3.0: s = 0.6 + re * 0.05
        else: s = 0.7 + re * 0.06
        z5 = sum(zl[-5:]) / 5 if len(zl) >= 5 else z
        z10 = sum(zl[-10:]) / 10 if len(zl) >= 10 else z
        if (z > 0 and z5 < z10) or (z < 0 and z5 > z10): s *= 1.3
        return min(0.95, s)

    def observations(self):
        return self.n_obs


class ReplayEngine:
    def __init__(self, params):
        self.garch = GARCH()
        self.p = params
        self.ema_20 = 0.0; self.ema_50 = 0.0; self.atr = 0.0; self.prev_close = 0.0
        self.bars_seen = 0; self.in_pos = False; self.pos_dir = 0
        self.pos_entry = 0.0; self.pos_sl = 0.0; self.pos_tp = 0.0
        self.pos_bar = 0; self.pos_stake = 0.0; self.pos_risk = 0.0
        self.pos_best_r = 0.0; self.pos_trail = -1
        self.pending = 0; self.cooldown = 0
        self.equity = 10000.0; self.peak = 10000.0
        self.consec_loss = 0; self.total = 0
        self.rsi_gain = 0.0; self.rsi_loss = 0.0

        # Replay data
        self.price_data = []    # Every bar's OHLC + indicators
        self.trades = []        # Every trade with full detail
        self.signals = []       # Every signal (entry/exit/pending)

    def process_bar(self, rate, bar_idx):
        c, h, l, o = rate['close'], rate['high'], rate['low'], rate['open']
        ts = datetime.fromtimestamp(rate['time']).strftime('%Y-%m-%d %H:%M')
        self.bars_seen += 1

        if self.prev_close <= 0:
            self.prev_close = c; self.ema_20 = c; self.ema_50 = c
            self._record_bar(ts, c, h, l, o, 0, 0, 0, 0)
            return

        lr = math.log(c / self.prev_close) if self.prev_close > 0 else 0
        sigma = self.garch.update(lr)
        z = self.garch.get_z(c, self.ema_20)
        vr = self.garch.sigma_fast / max(self.garch.sigma_slow, 1e-12) if self.garch.sigma_slow > 0 else 1.0
        mr = self.garch.mean_revert_signal()

        self.ema_20 = self.ema_20 * (1 - 2.0/21.0) + c * (2.0/21.0)
        self.ema_50 = self.ema_50 * (1 - 2.0/51.0) + c * (2.0/51.0)
        tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.atr = self.atr * (1 - 2.0/15.0) + tr * (2.0/15.0) if self.atr > 0 else tr

        gain = max(c - self.prev_close, 0); loss = max(self.prev_close - c, 0)
        self.rsi_gain = self.rsi_gain * 13/14 + gain/14; self.rsi_loss = self.rsi_loss * 13/14 + loss/14
        rsi = 100 - 100 / (1 + self.rsi_gain / max(self.rsi_loss, 1e-10))

        signal = None

        # ── Manage Position ──
        if self.in_pos:
            bh = self.bars_seen - self.pos_bar; rd = self.pos_risk
            cr = (c - self.pos_entry) * self.pos_dir / rd if rd > 0 else 0
            self.pos_best_r = max(self.pos_best_r, cr)

            if self.pos_best_r >= self.p['trail_be_r'] and self.pos_trail < 0: self.pos_trail = 0
            if self.pos_best_r >= 2.0 and self.pos_trail < 1: self.pos_trail = 1
            if self.pos_best_r >= 3.0 and self.pos_trail < 2: self.pos_trail = 2

            if self.pos_trail >= 0:
                cfgs = [(1.0, 0.3), (2.0, 0.25), (3.0, 0.2)]
                td = self.atr * cfgs[min(self.pos_trail, 2)][1]
                if self.pos_dir > 0: self.pos_sl = max(self.pos_sl, c - td)
                else: self.pos_sl = min(self.pos_sl, c + td)

            ep, reason = 0, ""
            if self.pos_dir > 0:
                if l <= self.pos_sl: ep, reason = self.pos_sl, "TRAIL" if self.pos_trail >= 0 else "STOP"
                elif h >= self.pos_tp: ep, reason = self.pos_tp, "TARGET"
            else:
                if h >= self.pos_sl: ep, reason = self.pos_sl, "TRAIL" if self.pos_trail >= 0 else "STOP"
                elif l <= self.pos_tp: ep, reason = self.pos_tp, "TARGET"
            if not reason and bh >= self.p['hold_bars']: ep, reason = c, "TIME"

            if reason:
                slipped = ep - 0.05 if self.pos_dir > 0 else ep + 0.05
                rr = (slipped - self.pos_entry) * self.pos_dir / rd if rd > 0 else 0
                pnl = self.pos_stake * rr
                self.equity += pnl; self.peak = max(self.peak, self.equity)
                self.total += 1
                if rr > 0: self.consec_loss = 0
                else: self.consec_loss += 1; self.cooldown = 3

                trade = {
                    'id': self.total, 'time': ts, 'bar': bar_idx,
                    'side': 'BUY' if self.pos_dir > 0 else 'SELL',
                    'entry': self.pos_entry, 'exit': slipped,
                    'sl': self.pos_sl, 'tp': self.pos_tp,
                    'reason': reason, 'rr': round(rr, 3), 'pnl': round(pnl, 2),
                    'equity': round(self.equity, 2), 'bars_held': bh,
                    'trail_level': self.pos_trail,
                }
                self.trades.append(trade)
                self.signals.append({'time': ts, 'bar': bar_idx, 'type': 'EXIT', 'side': trade['side'],
                                     'price': slipped, 'reason': reason, 'pnl': round(pnl, 2)})

                self.in_pos = False; self.pos_dir = 0; self.pos_trail = -1
                self.prev_close = c
                self._record_bar(ts, c, h, l, o, z, self.ema_20, rsi, self.equity)
                return

            self.prev_close = c
            self._record_bar(ts, c, h, l, o, z, self.ema_20, rsi, self.equity)
            return

        if self.cooldown > 0: self.cooldown -= 1
        if self.bars_seen < 60 or self.garch.observations() < 30:
            self.prev_close = c
            self._record_bar(ts, c, h, l, o, z, self.ema_20, rsi, self.equity)
            return

        if self.pending != 0:
            confirmed = (self.pending > 0 and c > o) or (self.pending < 0 and c < o)
            if confirmed:
                sd = c * self.p['stop_mult'] * self.garch.get_sigma()
                td = c * self.p['target_mult'] * self.garch.get_sigma()
                sl = (c - sd) if self.pending > 0 else (c + sd)
                tp = (c + td) if self.pending > 0 else (c - td)
                rd = abs(c - sl)
                if rd > 0 and abs(tp - c) / rd >= 1.8:
                    risk_pct = 0.005
                    if self.consec_loss >= 5: risk_pct *= 0.5
                    dd = (self.peak - self.equity) / self.peak if self.peak > 0 else 0
                    if dd > 0.08: risk_pct *= 0.5
                    stake = self.equity * risk_pct
                    self.in_pos = True; self.pos_dir = self.pending
                    self.pos_entry = c; self.pos_sl = sl; self.pos_tp = tp
                    self.pos_bar = self.bars_seen; self.pos_stake = stake
                    self.pos_risk = rd; self.pos_best_r = 0; self.pos_trail = -1
                    side = 'BUY' if self.pos_dir > 0 else 'SELL'
                    self.signals.append({'time': ts, 'bar': bar_idx, 'type': 'ENTRY', 'side': side,
                                         'price': c, 'sl': sl, 'tp': tp, 'z': round(z, 3)})
                self.pending = 0
                self.prev_close = c
                self._record_bar(ts, c, h, l, o, z, self.ema_20, rsi, self.equity)
                return
            else:
                self.pending = 0

        if abs(z) < self.p['z_entry'] or vr < self.p['vol_ratio'] or mr < 0.02:
            self.prev_close = c
            self._record_bar(ts, c, h, l, o, z, self.ema_20, rsi, self.equity)
            return

        direction = -1 if z > 0 else 1
        if direction > 0 and rsi > 80: self.prev_close = c; return
        if direction < 0 and rsi < 20: self.prev_close = c; return
        if mr < 0.3: self.prev_close = c; return

        self.pending = direction
        self._record_bar(ts, c, h, l, o, z, self.ema_20, rsi, self.equity)
        self.prev_close = c

    def _record_bar(self, ts, c, h, l, o, z, ema, rsi, eq):
        self.price_data.append({
            'time': ts, 'open': round(o, 2), 'high': round(h, 2),
            'low': round(l, 2), 'close': round(c, 2),
            'z': round(z, 3), 'ema': round(ema, 2), 'rsi': round(rsi, 1),
            'equity': round(eq, 2),
        })


def run_replay(symbol, params, num_bars=None):
    """Run backtest and return full replay data."""
    print(f"  Loading data for {symbol}...")
    if num_bars is None:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 26000)
    else:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, num_bars)

    if rates is None or len(rates) < 500:
        print(f"  [SKIP] Only {len(rates) if rates else 0} bars")
        return None

    days = (datetime.fromtimestamp(rates[-1]['time']) - datetime.fromtimestamp(rates[0]['time'])).days
    print(f"  {len(rates)} M5 bars = {days} days ({datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d')})")

    engine = ReplayEngine(params)
    for i, rate in enumerate(rates):
        engine.process_bar(rate, i)
        if i % 5000 == 0 and i > 0:
            print(f"  Progress: {i}/{len(rates)} bars ({i/len(rates)*100:.0f}%)...")

    # Summary
    trades = engine.trades
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    pnl = sum(t['pnl'] for t in trades)
    gp = sum(t['pnl'] for t in wins) if wins else 0
    gl = abs(sum(t['pnl'] for t in losses)) if losses else 0
    pf = gp / gl if gl > 0 else 0

    print(f"\n  Results: {len(trades)} trades, {wr:.1f}% WR, P&L=${pnl:+,.2f}, PF={pf:.2f}")

    return {
        'symbol': symbol,
        'params': params,
        'summary': {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(wr, 1),
            'total_pnl': round(float(pnl), 2),
            'profit_factor': round(float(pf), 2),
            'final_equity': round(float(engine.equity), 2),
            'start_date': int(rates[0]['time']),
            'end_date': int(rates[-1]['time']),
            'total_bars': int(len(rates)),
        },
        'price_data': engine.price_data,
        'trades': engine.trades,
        'signals': engine.signals,
    }


def main():
    if not mt5.initialize():
        print("MT5 init failed"); return

    params = {
        'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.6,
        'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
        'vol_ratio': 1.03,
    }

    # Run on Volatility 100 (best performer)
    result = run_replay("Volatility 100 Index", params)

    if result:
        output_path = os.path.join(DATA_DIR, 'backtest_replay.json')
        print(f"\n  Saving replay data to {output_path}...")
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=None, default=lambda o: int(o) if hasattr(o, 'item') else str(o))  # Compact
        print(f"  Saved! ({os.path.getsize(output_path) / 1024 / 1024:.1f} MB)")

    mt5.shutdown()


if __name__ == "__main__":
    main()
