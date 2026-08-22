#!/usr/bin/env python
"""
MITEMSHUB AI — 90-Day Walk-Forward Validation
Runs the final engine on the longest available data to check:
1. Does the strategy hold up over 90 days?
2. Is there performance degradation over time?
3. What's the monthly breakdown?
4. Are there regime-dependent failures?

This is the REAL test — if it works on 90 days, it's robust.
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
from datetime import datetime, timedelta
from collections import deque

sys.stdout.reconfigure(encoding='utf-8')


class GARCH:
    def __init__(self):
        self.omega, self.alpha, self.gamma, self.beta = -1.884103, 0.142169, -0.073285, 0.852741
        self.log_sigma2 = 0.0; self.n_obs = 0; self._sum = 0.0; self._sq_sum = 0.0
        self.sigma_fast = 0.0; self.sigma_slow = 0.0; self.sigma_historical = 0.0
        self.vol_regime = 'NORMAL'; self.z_history = deque(maxlen=500); self.last_z = 0.0

    def update(self, log_ret):
        self.n_obs += 1; self._sum += log_ret; self._sq_sum += log_ret * log_ret
        if self.n_obs < 20:
            self.log_sigma2 = math.log(max(self._sq_sum / self.n_obs, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self._update_scales(sigma); self.last_z = log_ret / max(sigma, 1e-12)
            self.z_history.append(self.last_z); return sigma
        prev_sigma2 = math.exp(self.log_sigma2)
        z = log_ret / max(math.sqrt(prev_sigma2), 1e-12)
        self.log_sigma2 = self.omega + self.alpha * abs(z) + self.gamma * z + self.beta * self.log_sigma2
        sigma = math.exp(self.log_sigma2 / 2.0); self.last_z = z; self.z_history.append(z)
        self._update_scales(sigma); self._detect_regime(sigma); return sigma

    def _update_scales(self, sigma):
        if self.sigma_fast == 0:
            self.sigma_fast = self.sigma_slow = self.sigma_historical = sigma
        else:
            self.sigma_fast = self.sigma_fast * 0.6 + sigma * 0.4
            self.sigma_slow = self.sigma_slow * 0.98 + sigma * 0.02
            self.sigma_historical = self.sigma_historical * (1 - 1.0/self.n_obs) + sigma / self.n_obs

    def _detect_regime(self, sigma):
        if self.sigma_slow <= 0: return
        r = sigma / self.sigma_slow
        self.vol_regime = 'EXTREME' if r > 2.0 else 'HIGH' if r > 1.5 else 'LOW' if r < 0.5 else 'NORMAL'

    def get_sigma(self): return math.exp(self.log_sigma2 / 2.0)
    def get_z_from_price(self, price, ema):
        s = self.get_sigma(); return math.log(price / ema) / s if s > 0 and self.n_obs >= 10 else 0.0
    def mean_revert_signal(self):
        if len(self.z_history) < 10: return 0.0
        zl = list(self.z_history); z = zl[-1]; az = abs(z)
        re = sum(1 for z in zl[-20:] if abs(z) > 2.0)
        s = 0.0 if az < 1.0 else (0.1 + re*0.02) if az < 1.5 else (0.3 + re*0.03) if az < 2.0 else (0.5 + re*0.04) if az < 2.5 else (0.6 + re*0.05) if az < 3.0 else (0.7 + re*0.06)
        z5 = sum(zl[-5:])/5 if len(zl) >= 5 else z; z10 = sum(zl[-10:])/10 if len(zl) >= 10 else z
        if (z > 0 and z5 < z10) or (z < 0 and z5 > z10): s *= 1.3
        return min(0.95, s)
    def observations(self): return self.n_obs


class Engine:
    def __init__(self, params):
        self.garch = GARCH()
        self.p = params
        self.ema_20 = 0.0; self.ema_50 = 0.0; self.atr = 0.0; self.prev_close = 0.0
        self.bars_seen = 0; self.in_pos = False; self.pos_dir = 0
        self.pos_entry = 0.0; self.pos_sl = 0.0; self.pos_tp = 0.0
        self.pos_bar = 0; self.pos_stake = 0.0; self.pos_risk = 0.0
        self.pos_best_r = 0.0; self.pos_trail = -1
        self.pending = 0; self.cooldown = 0; self.equity = 10000.0; self.peak = 10000.0
        self.consec_loss = 0; self.total = 0; self.trades = []
        self.rsi_gain = 0.0; self.rsi_loss = 0.0; self.bar_time = None

    def process_bar(self, rate):
        c, h, l, o = rate['close'], rate['high'], rate['low'], rate['open']
        t = rate['time']; ts = datetime.fromtimestamp(t)
        self.bar_time = ts
        self.bars_seen += 1

        if self.prev_close <= 0:
            self.prev_close = c; self.ema_20 = c; self.ema_50 = c; return None

        lr = math.log(c / self.prev_close) if self.prev_close > 0 else 0
        sigma = self.garch.update(lr)
        z = self.garch.get_z_from_price(c, self.ema_20)
        vr = self.garch.sigma_fast / max(self.garch.sigma_slow, 1e-12) if self.garch.sigma_slow > 0 else 1.0
        mr = self.garch.mean_revert_signal()

        self.ema_20 = self.ema_20 * (1 - 2.0/21.0) + c * (2.0/21.0)
        self.ema_50 = self.ema_50 * (1 - 2.0/51.0) + c * (2.0/51.0)
        tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.atr = self.atr * (1 - 2.0/15.0) + tr * (2.0/15.0) if self.atr > 0 else tr

        gain = max(c - self.prev_close, 0); loss = max(self.prev_close - c, 0)
        self.rsi_gain = self.rsi_gain * 13/14 + gain/14; self.rsi_loss = self.rsi_loss * 13/14 + loss/14
        rsi = 100 - 100 / (1 + self.rsi_gain / max(self.rsi_loss, 1e-10))

        # Manage position
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
                self.trades.append({'num': self.total, 'time': ts, 'entry': self.pos_entry,
                    'exit': slipped, 'reason': reason, 'rr': rr, 'pnl': pnl,
                    'equity': self.equity, 'bars_held': bh, 'trail': self.pos_trail})
                self.in_pos = False; self.pos_dir = 0; self.pos_trail = -1
                self.prev_close = c; return self.trades[-1]
            self.prev_close = c; return None

        if self.cooldown > 0: self.cooldown -= 1; self.prev_close = c; return None
        if self.in_pos or self.bars_seen < 60 or self.garch.observations() < 30:
            self.prev_close = c; return None

        if self.pending != 0:
            confirmed = (self.pending > 0 and c > o) or (self.pending < 0 and c < o)
            if confirmed:
                result = self._enter(c, ts, self.pending)
                self.prev_close = c; return result
            else: self.pending = 0; self.prev_close = c; return None

        if abs(z) < self.p['z_entry']: self.prev_close = c; return None
        if vr < self.p['vol_ratio']: self.prev_close = c; return None
        if mr < 0.02: self.prev_close = c; return None
        direction = -1 if z > 0 else 1
        if direction > 0 and rsi > 80: self.prev_close = c; return None
        if direction < 0 and rsi < 20: self.prev_close = c; return None
        if mr < 0.3: self.prev_close = c; return None

        self.pending = direction
        self.prev_close = c; return None

    def _enter(self, c, ts, direction):
        sd = c * self.p['stop_mult'] * self.garch.get_sigma()
        td = c * self.p['target_mult'] * self.garch.get_sigma()
        sl = (c - sd) if direction > 0 else (c + sd)
        tp = (c + td) if direction > 0 else (c - td)
        rd = abs(c - sl)
        if rd <= 0: self.pending = 0; return None
        rr = abs(tp - c) / rd
        if rr < 1.8: self.pending = 0; return None

        risk_pct = 0.005
        if self.consec_loss >= 5: risk_pct *= 0.5
        dd = (self.peak - self.equity) / self.peak if self.peak > 0 else 0
        if dd > 0.08: risk_pct *= 0.5
        stake = self.equity * risk_pct

        self.in_pos = True; self.pos_dir = direction; self.pos_entry = c
        self.pos_sl = sl; self.pos_tp = tp; self.pos_bar = self.bars_seen
        self.pos_stake = stake; self.pos_risk = rd; self.pos_best_r = 0; self.pos_trail = -1
        self.pending = 0
        return None


def monthly_breakdown(trades):
    """Group trades by month and compute monthly stats."""
    monthly = {}
    for t in trades:
        month = t['time'].strftime('%Y-%m')
        if month not in monthly:
            monthly[month] = {'trades': 0, 'wins': 0, 'pnl': 0}
        monthly[month]['trades'] += 1
        monthly[month]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            monthly[month]['wins'] += 1
    return monthly


def run_90day(symbol, rates, params):
    """Run engine on full dataset and analyze."""
    print(f"\n{'=' * 100}")
    print(f"  90-DAY VALIDATION — {symbol}")
    print(f"  Data: {len(rates)} M5 bars ({datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d %H:%M')})")
    print(f"{'=' * 100}")

    engine = Engine(params)
    for rate in rates:
        engine.process_bar(rate)

    trades = engine.trades
    if not trades:
        print("  No trades generated")
        return None

    # Overall stats
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins)/len(trades)*100
    pnl = sum(t['pnl'] for t in trades)
    gp = sum(t['pnl'] for t in wins) if wins else 0
    gl = abs(sum(t['pnl'] for t in losses)) if losses else 0
    pf = gp/gl if gl > 0 else 999

    eq = 10000; pk = 10000; mdd = 0
    for t in trades: eq += t['pnl']; pk = max(pk, eq); dd = (pk-eq)/pk; mdd = max(mdd, dd)
    mc = 0; s = 0
    for t in trades:
        if t['pnl'] <= 0: s += 1; mc = max(mc, s)
        else: s = 0

    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = {'c': 0, 'p': 0, 'r': 0}
        reasons[r]['c'] += 1; reasons[r]['p'] += t['pnl']; reasons[r]['r'] += t['rr']

    print(f"\n  OVERALL PERFORMANCE:")
    print(f"  Trades:          {len(trades)}")
    print(f"  Wins:            {len(wins)} ({wr:.1f}%)")
    print(f"  Losses:          {len(losses)}")
    print(f"  Total P&L:       ${pnl:+,.2f} ({pnl/100:.1f}%)")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Avg Win:         ${gp/len(wins):+,.2f}" if wins else "")
    print(f"  Avg Loss:        ${-gl/len(losses):+,.2f}" if losses else "")
    print(f"  Max Drawdown:    {mdd*100:.2f}%")
    print(f"  Max Consec Loss: {mc}")
    print(f"  Final Equity:    ${engine.equity:,.2f}")

    print(f"\n  EXIT REASONS:")
    for r, d in sorted(reasons.items()):
        avg_rr = d['r']/d['c'] if d['c'] > 0 else 0
        print(f"    {r:10s}: {d['c']:3d} trades, ${d['p']:+12,.2f}, avg R={avg_rr:+.3f}")

    # Monthly breakdown
    monthly = monthly_breakdown(trades)
    print(f"\n  MONTHLY BREAKDOWN:")
    print(f"  {'Month':>10} | {'Trades':>6} | {'Wins':>5} | {'WinRate':>7} | {'P&L':>12} | {'Equity End':>12}")
    print("  " + "-" * 60)
    cum_pnl = 0
    for month in sorted(monthly.keys()):
        d = monthly[month]
        wr_m = d['wins']/d['trades']*100 if d['trades'] > 0 else 0
        cum_pnl += d['pnl']
        eq_end = 10000 + cum_pnl
        color = "\033[92m" if d['pnl'] > 0 else "\033[91m"
        print(f"  {color}{month:>10} | {d['trades']:6d} | {d['wins']:5d} | {wr_m:6.1f}% | ${d['pnl']:+10,.2f} | ${eq_end:>10,.2f}\033[0m")

    # Walk-forward: first half vs second half
    mid = len(trades) // 2
    if mid > 10:
        first = trades[:mid]
        second = trades[mid:]
        fw_wr = len([t for t in first if t['pnl'] > 0])/len(first)*100
        sw_wr = len([t for t in second if t['pnl'] > 0])/len(second)*100
        fw_pnl = sum(t['pnl'] for t in first)
        sw_pnl = sum(t['pnl'] for t in second)
        fw_pf = sum(t['pnl'] for t in first if t['pnl'] > 0) / max(abs(sum(t['pnl'] for t in first if t['pnl'] <= 0)), 1)
        sw_pf = sum(t['pnl'] for t in second if t['pnl'] > 0) / max(abs(sum(t['pnl'] for t in second if t['pnl'] <= 0)), 1)
        print(f"\n  WALK-FORWARD ANALYSIS (first half vs second half):")
        print(f"  {'Period':>12} | {'Trades':>6} | {'WinRate':>7} | {'P&L':>12} | {'PF':>6}")
        print(f"  {'First Half':>12} | {len(first):6d} | {fw_wr:6.1f}% | ${fw_pnl:+10,.2f} | {fw_pf:.2f}")
        print(f"  {'Second Half':>12} | {len(second):6d} | {sw_wr:6.1f}% | ${sw_pnl:+10,.2f} | {sw_pf:.2f}")
        degradation = fw_wr - sw_wr
        print(f"\n  Win Rate Change: {degradation:+.1f}% ({'DEGRADED' if degradation > 5 else 'STABLE' if abs(degradation) < 3 else 'IMPROVED'})")
        pnl_change = sw_pnl - fw_pnl
        print(f"  P&L Change:      ${pnl_change:+,.2f} ({'DEGRADED' if pnl_change < -1000 else 'STABLE' if abs(pnl_change) < 500 else 'IMPROVED'})")

    # Regime analysis
    regimes = {}
    for t in trades:
        # Determine regime from the entry bar
        r = 'NORMAL'  # default
        if t['rr'] > 3: r = 'STRONG_MOVE'
        elif t['rr'] > 1: r = 'MODERATE'
        else: r = 'WEAK'
        if r not in regimes: regimes[r] = {'c': 0, 'p': 0, 'w': 0}
        regimes[r]['c'] += 1; regimes[r]['p'] += t['pnl']
        if t['pnl'] > 0: regimes[r]['w'] += 1

    print(f"\n  TRADE STRENGTH ANALYSIS:")
    for r, d in sorted(regimes.items()):
        wr_r = d['w']/d['c']*100 if d['c'] > 0 else 0
        print(f"    {r:15s}: {d['c']:3d} trades, {wr_r:.1f}% WR, ${d['p']:+10,.2f}")

    print(f"\n{'=' * 100}")

    return {
        'symbol': symbol, 'trades': len(trades), 'wr': wr, 'pnl': pnl,
        'pf': pf, 'mdd': mdd, 'mc': mc, 'monthly': monthly,
    }


def main():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed"); return

    params = {
        'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.6,
        'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
        'vol_ratio': 1.03, 'min_revert': 0.02, 'min_rr': 1.8,
    }

    symbols = ["Volatility 75 Index", "Volatility 100 Index"]
    results = {}

    for sym in symbols:
        print(f"\n  Loading maximum available data for {sym}...")
        # Try to get as much data as possible
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 26000)  # ~90 days
        if rates is None or len(rates) < 500:
            print(f"  [SKIP] Only {len(rates) if rates else 0} bars")
            continue

        days = (datetime.fromtimestamp(rates[-1]['time']) - datetime.fromtimestamp(rates[0]['time'])).days
        print(f"  Got {len(rates)} M5 bars = {days} days of data")

        r = run_90day(sym, rates, params)
        if r: results[sym] = r

    # Final comparison
    if len(results) == 2:
        s75 = results["Volatility 75 Index"]
        s100 = results["Volatility 100 Index"]
        print(f"\n{'=' * 100}")
        print(f"  90-DAY VALIDATION SUMMARY")
        print(f"{'=' * 100}")
        print(f"\n  {'Metric':<20} | {'Volatility 75':>15} | {'Volatility 100':>15} | {'Winner':>15}")
        print(f"  {'-'*20}-+-{'-'*15}-+-{'-'*15}-+-{'-'*15}")
        for name, k, d in [('Trades','trades','>'),('Win Rate','wr','>'),('Total P&L','pnl','>'),('Profit Factor','pf','>'),('Max Drawdown','mdd','<'),('Max Consec','mc','<')]:
            v75, v100 = s75[k], s100[k]
            if k=='pnl': v75s,v100s = f"${v75:+,.2f}",f"${v100:+,.2f}"
            elif k=='wr': v75s,v100s = f"{v75:.1f}%",f"{v100:.1f}%"
            elif k=='pf': v75s,v100s = f"{v75:.2f}",f"{v100:.2f}"
            elif k=='mdd': v75s,v100s = f"{v75*100:.2f}%",f"{v100*100:.2f}%"
            else: v75s,v100s = f"{v75}",f"{v100}"
            if d=='>': w = "Vol 75" if v75>v100 else "Vol 100" if v100>v75 else "TIE"
            else: w = "Vol 75" if v75<v100 else "Vol 100" if v100<v75 else "TIE"
            print(f"  {name:<20} | {v75s:>15} | {v100s:>15} | {w:>15}")

        # Robustness verdict
        print(f"\n  ROBUSTNESS VERDICT:")
        for sym, r in results.items():
            status = "ROBUST" if r['pf'] > 2.0 and r['mdd'] < 0.10 else "MARGINAL" if r['pf'] > 1.5 else "WEAK"
            monthly_avg = r['pnl'] / 3 if r['pnl'] > 0 else 0
            print(f"    {sym}: {status} (PF={r['pf']:.2f}, MDD={r['mdd']*100:.1f}%, ~${monthly_avg:+,.0f}/month)")

        print(f"\n{'=' * 100}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
