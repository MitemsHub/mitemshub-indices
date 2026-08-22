#!/usr/bin/env python
"""
MITEMSHUB AI — PRODUCTION ENGINE (v6+ ensemble)
Uses the PROVEN v6 grid-searched parameters + v7's ensemble signal filtering.
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
from datetime import datetime
from collections import deque

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


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


class ProductionEngine:
    def __init__(self, symbol_name=""):
        self.garch = GARCH()
        self.symbol = symbol_name
        self.ema_20 = 0.0; self.ema_50 = 0.0; self.atr = 0.0; self.prev_close = 0.0
        self.bars_seen = 0; self.in_pos = False; self.pos_dir = 0
        self.pos_entry = 0.0; self.pos_sl = 0.0; self.pos_tp = 0.0
        self.pos_bar = 0; self.pos_stake = 0.0; self.pos_risk = 0.0
        self.pos_best_r = 0.0; self.pos_trail = -1
        self.pending = 0; self.pending_z = 0.0; self.pending_conf = 0.0
        self.cooldown = 0; self.equity = 10000.0; self.peak = 10000.0
        self.consec_loss = 0; self.total = 0; self.trades = []
        self.rsi_gain = 0.0; self.rsi_loss = 0.0

        # v6 optimal parameters
        self.z_entry = 1.8
        self.stop_mult = 0.10
        self.target_mult = 0.8
        self.hold_bars = 12
        self.trail_be_r = 1.0
        self.trail_behind_r = 0.3
        self.vol_ratio = 1.03

    def process_bar(self, rate):
        c, h, l, o = rate['close'], rate['high'], rate['low'], rate['open']
        t = rate['time']; ts = datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
        self.bars_seen += 1

        if self.prev_close <= 0:
            self.prev_close = c; self.ema_20 = c; self.ema_50 = c; return None

        lr = math.log(c / self.prev_close) if self.prev_close > 0 else 0
        sigma = self.garch.update(lr)
        z = self.garch.get_z_from_price(c, self.ema_20)
        vr = self.garch.sigma_fast / max(self.garch.sigma_slow, 1e-12) if self.garch.sigma_slow > 0 else 1.0
        mr = self.garch.mean_revert_signal()

        # EMAs + ATR
        self.ema_20 = self.ema_20 * (1 - 2.0/21.0) + c * (2.0/21.0)
        self.ema_50 = self.ema_50 * (1 - 2.0/51.0) + c * (2.0/51.0)
        tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.atr = self.atr * (1 - 2.0/15.0) + tr * (2.0/15.0) if self.atr > 0 else tr

        # RSI
        gain = max(c - self.prev_close, 0); loss = max(self.prev_close - c, 0)
        self.rsi_gain = self.rsi_gain * 13/14 + gain/14; self.rsi_loss = self.rsi_loss * 13/14 + loss/14
        rsi = 100 - 100 / (1 + self.rsi_gain / max(self.rsi_loss, 1e-10))

        # ─── MANAGE POSITION ─────────────────────────────────────
        if self.in_pos:
            bh = self.bars_seen - self.pos_bar; rd = self.pos_risk
            cr = (c - self.pos_entry) * self.pos_dir / rd if rd > 0 else 0
            self.pos_best_r = max(self.pos_best_r, cr)

            # Multi-level trailing
            if self.pos_best_r >= self.trail_be_r and self.pos_trail < 0:
                self.pos_trail = 0
            if self.pos_best_r >= 2.0 and self.pos_trail < 1: self.pos_trail = 1
            if self.pos_best_r >= 3.0 and self.pos_trail < 2: self.pos_trail = 2

            if self.pos_trail >= 0:
                trail_cfgs = [(1.0, 0.3), (2.0, 0.25), (3.0, 0.2)]
                td = self.atr * trail_cfgs[min(self.pos_trail, 2)][1]
                if self.pos_dir > 0: self.pos_sl = max(self.pos_sl, c - td)
                else: self.pos_sl = min(self.pos_sl, c + td)

            ep, reason = 0, ""
            if self.pos_dir > 0:
                if l <= self.pos_sl: ep, reason = self.pos_sl, "TRAIL" if self.pos_trail >= 0 else "STOP"
                elif h >= self.pos_tp: ep, reason = self.pos_tp, "TARGET"
            else:
                if h >= self.pos_sl: ep, reason = self.pos_sl, "TRAIL" if self.pos_trail >= 0 else "STOP"
                elif l <= self.pos_tp: ep, reason = self.pos_tp, "TARGET"

            if not reason and bh >= self.hold_bars: ep, reason = c, "TIME"

            if reason:
                slipped = ep - 0.05 if self.pos_dir > 0 else ep + 0.05
                rr = (slipped - self.pos_entry) * self.pos_dir / rd if rd > 0 else 0
                pnl = self.pos_stake * rr
                self.equity += pnl; self.peak = max(self.peak, self.equity)
                self.total += 1
                if rr > 0: self.consec_loss = 0
                else: self.consec_loss += 1; self.cooldown = 3
                self.trades.append({'num': self.total, 'time': ts, 'side': 'BUY' if self.pos_dir > 0 else 'SELL',
                    'entry': self.pos_entry, 'exit': slipped, 'reason': reason, 'rr': rr, 'pnl': pnl,
                    'equity': self.equity, 'bars_held': bh, 'trail_level': self.pos_trail})
                self.in_pos = False; self.pos_dir = 0; self.pos_trail = -1
                self.prev_close = c; return self.trades[-1]
            self.prev_close = c; return None

        if self.cooldown > 0: self.cooldown -= 1; self.prev_close = c; return None

        # ─── ENTRY ───────────────────────────────────────────────
        if self.in_pos or self.bars_seen < 60 or self.garch.observations() < 30:
            self.prev_close = c; return None

        if self.pending != 0:
            confirmed = (self.pending > 0 and c > o) or (self.pending < 0 and c < o)
            if confirmed:
                result = self._enter(c, ts, self.pending, self.pending_conf)
                self.prev_close = c; return result
            else: self.pending = 0; self.prev_close = c; return None

        # v6 entry conditions
        if abs(z) < self.z_entry: self.prev_close = c; return None
        if vr < self.vol_ratio: self.prev_close = c; return None
        if mr < 0.02: self.prev_close = c; return None

        direction = -1 if z > 0 else 1

        # Ensemble filter: check RSI doesn't contradict
        if direction > 0 and rsi > 80: self.prev_close = c; return None
        if direction < 0 and rsi < 20: self.prev_close = c; return None

        # Confidence from mean reversion signal
        conf = mr
        if conf < 0.3: self.prev_close = c; return None

        self.pending = direction; self.pending_z = z; self.pending_conf = conf
        self.prev_close = c; return None

    def _enter(self, c, ts, direction, conf):
        # v6 proven stop/target (price-based, not ATR-based)
        sd = c * self.stop_mult * self.garch.get_sigma()
        td = c * self.target_mult * self.garch.get_sigma()
        sl = (c - sd) if direction > 0 else (c + sd)
        tp = (c + td) if direction > 0 else (c - td)
        rd = abs(c - sl)
        if rd <= 0: self.pending = 0; return None
        rr = abs(tp - c) / rd
        if rr < 1.8: self.pending = 0; return None

        # Position sizing with caps
        risk_pct = 0.005
        if self.consec_loss >= 5: risk_pct *= 0.5
        dd = (self.peak - self.equity) / self.peak if self.peak > 0 else 0
        if dd > 0.08: risk_pct *= 0.5
        stake = self.equity * risk_pct

        self.in_pos = True; self.pos_dir = direction; self.pos_entry = c
        self.pos_sl = sl; self.pos_tp = tp; self.pos_bar = self.bars_seen
        self.pos_stake = stake; self.pos_risk = rd; self.pos_best_r = 0; self.pos_trail = -1
        self.pending = 0

        side = "BUY" if direction > 0 else "SELL"
        return {'type': 'ENTRY', 'time': ts, 'side': side, 'entry': c, 'sl': sl, 'tp': tp, 'z': self.pending_z}


def run(symbol, rates, params=None):
    e = ProductionEngine(symbol)
    if params:
        e.z_entry = params.get('z_entry', 1.8)
        e.stop_mult = params.get('stop_mult', 0.10)
        e.target_mult = params.get('target_mult', 0.8)
        e.hold_bars = params.get('hold_bars', 12)
        e.trail_be_r = params.get('trail_be_r', 1.0)
        e.trail_behind_r = params.get('trail_behind_r', 0.3)
        e.vol_ratio = params.get('vol_ratio', 1.03)
    for rate in rates: e.process_bar(rate)
    return e


def report(engine, symbol):
    t = engine.trades
    if not t: return None
    w = [x for x in t if x['pnl'] > 0]; l = [x for x in t if x['pnl'] <= 0]
    wr = len(w)/len(t)*100; pnl = sum(x['pnl'] for x in t)
    gp = sum(x['pnl'] for x in w) if w else 0; gl = abs(sum(x['pnl'] for x in l)) if l else 0
    pf = gp/gl if gl > 0 else 999
    eq = 10000; pk = 10000; mdd = 0
    for x in t: eq += x['pnl']; pk = max(pk, eq); dd = (pk-eq)/pk; mdd = max(mdd, dd)
    mc = 0; s = 0
    for x in t:
        if x['pnl'] <= 0: s += 1; mc = max(mc, s)
        else: s = 0

    reasons = {}
    for x in t:
        r = x['reason']
        if r not in reasons: reasons[r] = {'c': 0, 'p': 0, 'r': 0}
        reasons[r]['c'] += 1; reasons[r]['p'] += x['pnl']; reasons[r]['r'] += x['rr']

    print(f"\n{'='*100}")
    print(f"  PRODUCTION ENGINE — {symbol}")
    print(f"{'='*100}")
    print(f"  Trades: {len(t)} | Wins: {len(w)} ({wr:.1f}%) | Losses: {len(l)}")
    print(f"  P&L: ${pnl:+,.2f} ({pnl/100:.1f}%) | PF: {pf:.2f} | MaxDD: {mdd*100:.2f}% | MaxConsec: {mc}")
    print(f"  AvgWin: ${gp/len(w):+,.2f} | AvgLoss: ${-gl/len(l):+,.2f}" if w and l else "")
    print(f"\n  EXIT REASONS:")
    for r, d in sorted(reasons.items()):
        print(f"    {r:10s}: {d['c']:3d} trades, ${d['p']:+10,.2f}, avg R={d['r']/d['c']:+.3f}")
    print(f"\n  TRADE LOG:")
    print(f"  {'#':>3} | {'TIME':16} | {'SIDE':4} | {'ENTRY':>10} | {'EXIT':>10} | {'REASON':5} | {'R':>6} | {'P&L':>10} | {'EQUITY':>10} | LVL")
    print("  " + "-"*95)
    for x in t:
        cc = "\033[92m" if x['pnl'] > 0 else "\033[91m"
        lv = f"L{x['trail_level']}" if x['trail_level'] >= 0 else "---"
        print(f"  {cc}{x['num']:3d} | {x['time']:16} | {x['side']:4s} | {x['entry']:10.2f} | {x['exit']:10.2f} | {x['reason']:5s} | {x['rr']:+6.3f} | {x['pnl']:+10.2f} | ${x['equity']:>8.2f} | {lv}\033[0m")
    print(f"\n  EQUITY CURVE:")
    eqs = [10000] + [x['equity'] for x in t]; mn=min(eqs); mx=max(eqs)
    for i, e in enumerate(eqs):
        bl = int((e-mn)/max(mx-mn,1)*50) if mx>mn else 25
        mk = "---" if i==0 else f"#{i:3d}"
        print(f"  {mk} | {'#'*bl}${e:>9.2f}")
    print(f"{'='*100}")
    return {'symbol': symbol, 'trades': len(t), 'wr': wr, 'pnl': pnl, 'pf': pf, 'mdd': mdd, 'mc': mc}


def main():
    if not mt5.initialize(): return

    # Run on both symbols
    symbols = ["Volatility 75 Index", "Volatility 100 Index"]
    # Best params per symbol from grid search
    params = {
        "Volatility 75 Index": {'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.8, 'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3, 'vol_ratio': 1.03},
        "Volatility 100 Index": {'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.6, 'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3, 'vol_ratio': 1.03},
    }

    results = {}
    for sym in symbols:
        print(f"\n  Loading {sym}...")
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 8640)
        if rates is None or len(rates) < 200: print(f"  [SKIP]"); continue
        print(f"  {len(rates)} bars")
        engine = run(sym, rates, params.get(sym))
        r = report(engine, sym)
        if r: results[sym] = r

    if len(results) == 2:
        s75 = results["Volatility 75 Index"]; s100 = results["Volatility 100 Index"]
        print(f"\n{'='*100}")
        print(f"  FINAL COMPARISON")
        print(f"{'='*100}")
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
        print(f"\n{'='*100}")
    mt5.shutdown()

if __name__ == "__main__": main()
