#!/usr/bin/env python
"""
MITEMSHUB AI — ENGINE v8: THE FINAL FORM
==========================================
Fixes from v7:
1. ATR-NORMALIZED stops (works across any price level)
2. Position size caps (prevent runaway Kelly compounding)
3. Adaptive entry thresholds per symbol
4. Better regime-aware risk management

Key insight: Vol 75 and Vol 100 have DIFFERENT price scales.
Stop/target must be relative to ATR, not absolute price.
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
os.makedirs(DATA_DIR, exist_ok=True)


class AdaptiveGARCH:
    def __init__(self):
        self.omega, self.alpha, self.gamma, self.beta = -1.884103, 0.142169, -0.073285, 0.852741
        self.log_sigma2 = 0.0
        self.n_obs = 0
        self._sum = 0.0
        self._sq_sum = 0.0
        self.sigma_fast = 0.0
        self.sigma_slow = 0.0
        self.sigma_historical = 0.0
        self.prediction_errors = deque(maxlen=100)
        self.adaptive_alpha = self.alpha
        self.adaptive_beta = self.beta
        self.vol_regime = 'NORMAL'
        self.z_history = deque(maxlen=500)
        self.last_z = 0.0

    def update(self, log_ret):
        self.n_obs += 1
        self._sum += log_ret
        self._sq_sum += log_ret * log_ret

        if self.n_obs < 20:
            var = self._sq_sum / self.n_obs
            self.log_sigma2 = math.log(max(var, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self._update_multi_scale(sigma)
            self.last_z = log_ret / max(sigma, 1e-12)
            self.z_history.append(self.last_z)
            return sigma

        prev_sigma2 = math.exp(self.log_sigma2)
        prev_sigma = math.sqrt(prev_sigma2)
        z = log_ret / max(prev_sigma, 1e-12)

        if len(self.prediction_errors) > 20:
            recent_error = sum(abs(e) for e in list(self.prediction_errors)[-20:]) / 20
            if recent_error > 1.5:
                self.adaptive_alpha = max(0.05, self.alpha * 0.9)
                self.adaptive_beta = min(0.95, self.beta * 1.02)
            else:
                self.adaptive_alpha = self.alpha
                self.adaptive_beta = self.beta

        innovation = self.omega + self.adaptive_alpha * abs(z) + self.gamma * z + self.adaptive_beta * self.log_sigma2
        self.log_sigma2 = innovation
        sigma = math.exp(self.log_sigma2 / 2.0)
        self.last_z = z
        self.z_history.append(z)

        error = abs(math.log(max(log_ret * log_ret, 1e-12)) - math.log(max(prev_sigma2, 1e-12)))
        self.prediction_errors.append(error)

        self._update_multi_scale(sigma)
        self._detect_regime(sigma)
        return sigma

    def _update_multi_scale(self, sigma):
        if self.sigma_fast == 0:
            self.sigma_fast = self.sigma_slow = self.sigma_historical = sigma
        else:
            self.sigma_fast = self.sigma_fast * 0.6 + sigma * 0.4
            self.sigma_slow = self.sigma_slow * 0.98 + sigma * 0.02
            alpha_hist = 1.0 / self.n_obs
            self.sigma_historical = self.sigma_historical * (1 - alpha_hist) + sigma * alpha_hist

    def _detect_regime(self, sigma):
        if self.sigma_slow <= 0: return
        ratio = sigma / self.sigma_slow
        if ratio > 2.0: self.vol_regime = 'EXTREME'
        elif ratio > 1.5: self.vol_regime = 'HIGH'
        elif ratio < 0.5: self.vol_regime = 'LOW'
        else: self.vol_regime = 'NORMAL'

    def get_sigma(self):
        return math.exp(self.log_sigma2 / 2.0)

    def get_z_from_price(self, price, ema):
        sigma = self.get_sigma()
        if sigma <= 0 or self.n_obs < 10: return 0.0
        return math.log(price / ema) / sigma

    def mean_revert_signal(self):
        if len(self.z_history) < 10: return 0.0
        z_list = list(self.z_history)
        z = z_list[-1]; az = abs(z)
        recent_extremes = sum(1 for z in z_list[-20:] if abs(z) > 2.0)
        z_5 = sum(z_list[-5:]) / 5 if len(z_list) >= 5 else z
        z_10 = sum(z_list[-10:]) / 10 if len(z_list) >= 10 else z
        z_momentum = z_5 - z_10

        signal = 0.0
        if az < 1.0: signal = 0.0
        elif az < 1.5: signal = 0.1 + recent_extremes * 0.02
        elif az < 2.0: signal = 0.3 + recent_extremes * 0.03
        elif az < 2.5: signal = 0.5 + recent_extremes * 0.04
        elif az < 3.0: signal = 0.6 + recent_extremes * 0.05
        else: signal = 0.7 + recent_extremes * 0.06

        if (z > 0 and z_momentum < 0) or (z < 0 and z_momentum > 0):
            signal *= 1.3
        return min(0.95, signal)

    def observations(self):
        return self.n_obs


class EngineV8:
    """The final form — ATR-normalized, capped, adaptive."""

    def __init__(self):
        self.garch = AdaptiveGARCH()

        # EMAs
        self.ema_20 = 0.0
        self.ema_50 = 0.0
        self.atr = 0.0
        self.prev_close = 0.0
        self.bars_seen = 0

        # Bollinger
        self.bb_sq_sum = 0.0

        # RSI
        self.rsi_avg_gain = 0.0
        self.rsi_avg_loss = 0.0

        # Position
        self.in_pos = False
        self.pos_dir = 0
        self.pos_entry = 0.0
        self.pos_sl = 0.0
        self.pos_tp = 0.0
        self.pos_bar = 0
        self.pos_stake = 0.0
        self.pos_risk_dist = 0.0
        self.pos_best_r = 0.0
        self.pos_trail_level = -1
        self.pending_signal = 0
        self.pending_confidence = 0.0
        self.cooldown = 0

        # Risk
        self.equity = 10000.0
        self.peak_equity = 10000.0
        self.consecutive_losses = 0
        self.trade_results = deque(maxlen=100)

        # Stats
        self.trades = []
        self.total_trades = 0

    def process_bar(self, rate):
        c = rate['close']
        h = rate['high']
        l = rate['low']
        o = rate['open']
        t = rate['time']
        ts = datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
        self.bars_seen += 1

        if self.prev_close <= 0:
            self.prev_close = c
            self.ema_20 = c
            self.ema_50 = c
            return None

        log_ret = math.log(c / self.prev_close) if self.prev_close > 0 else 0

        # Update engines
        sigma = self.garch.update(log_ret)
        z_score = self.garch.get_z_from_price(c, self.ema_20)
        vol_ratio = self.garch.sigma_fast / max(self.garch.sigma_slow, 1e-12) if self.garch.sigma_slow > 0 else 1.0
        mr_signal = self.garch.mean_revert_signal()

        # EMAs
        self.ema_20 = self.ema_20 * (1 - 2.0/21.0) + c * (2.0/21.0)
        self.ema_50 = self.ema_50 * (1 - 2.0/51.0) + c * (2.0/51.0)

        # ATR — THIS IS THE KEY FIX: use ATR for stop/target normalization
        tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        self.atr = self.atr * (1 - 2.0/15.0) + tr * (2.0/15.0) if self.atr > 0 else tr

        # RSI
        gain = max(c - self.prev_close, 0)
        loss = max(self.prev_close - c, 0)
        self.rsi_avg_gain = self.rsi_avg_gain * 13/14 + gain / 14
        self.rsi_avg_loss = self.rsi_avg_loss * 13/14 + loss / 14
        rsi = 100 - 100 / (1 + self.rsi_avg_gain / max(self.rsi_avg_loss, 1e-10))

        # ─── MANAGE OPEN POSITION ────────────────────────────────
        exit_result = self._manage_position(c, h, l, ts)
        if exit_result:
            self.prev_close = c
            return exit_result

        if self.cooldown > 0:
            self.cooldown -= 1
            self.prev_close = c
            return None

        # ─── ENTRY LOGIC ─────────────────────────────────────────
        if self.in_pos or self.bars_seen < 60:
            self.prev_close = c
            return None

        if self.garch.observations() < 30:
            self.prev_close = c
            return None

        # Pending signal confirmation
        if self.pending_signal != 0:
            confirmed = (self.pending_signal > 0 and c > o) or (self.pending_signal < 0 and c < o)
            if confirmed:
                result = self._enter_trade(c, ts)
                self.prev_close = c
                return result
            else:
                self.pending_signal = 0
                self.prev_close = c
                return None

        # Entry conditions
        if abs(z_score) < 1.5:
            self.prev_close = c
            return None

        vol_gate = 1.01 if self.garch.vol_regime == 'LOW' else 1.03
        if vol_ratio < vol_gate:
            self.prev_close = c
            return None

        if mr_signal < 0.02:
            self.prev_close = c
            return None

        z_direction = -1 if z_score > 0 else 1
        confidence = mr_signal
        if confidence < 0.3:
            self.prev_close = c
            return None

        self.pending_signal = z_direction
        self.pending_confidence = confidence
        self.prev_close = c
        return None

    def _enter_trade(self, c, ts):
        """Enter trade with ATR-normalized stops."""
        direction = self.pending_signal

        # KEY FIX: Stop/target based on ATR, not price percentage
        # This works for ANY price level (Vol 75 $50K or Vol 100 $500)
        atr_stop_mult = 1.5  # Stop = 1.5x ATR
        atr_target_mult = 3.0  # Target = 3.0x ATR (2:1 R:R)

        stop_dist = self.atr * atr_stop_mult
        target_dist = self.atr * atr_target_mult

        sl = (c - stop_dist) if direction > 0 else (c + stop_dist)
        tp = (c + target_dist) if direction > 0 else (c - target_dist)

        risk_dist = abs(c - sl)
        if risk_dist <= 0:
            self.pending_signal = 0
            return None

        rr = abs(tp - c) / risk_dist
        if rr < 1.5:
            self.pending_signal = 0
            return None

        # Position sizing — CAPPED to prevent runaway compounding
        base_risk = 0.005  # 0.5% base risk
        if self.consecutive_losses >= 5:
            base_risk *= 0.5
        dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0
        if dd > 0.08:
            base_risk *= 0.5
        if self.garch.vol_regime == 'EXTREME':
            base_risk *= 0.3

        stake = self.equity * base_risk

        self.in_pos = True
        self.pos_dir = direction
        self.pos_entry = c
        self.pos_sl = sl
        self.pos_tp = tp
        self.pos_bar = self.bars_seen
        self.pos_stake = stake
        self.pos_risk_dist = risk_dist
        self.pos_best_r = 0.0
        self.pos_trail_level = -1
        self.pending_signal = 0

        side = "BUY" if direction > 0 else "SELL"
        return {'type': 'ENTRY', 'time': ts, 'side': side, 'entry': c, 'sl': sl, 'tp': tp,
                'z_score': self.garch.last_z, 'regime': self.garch.vol_regime, 'atr': self.atr}

    def _manage_position(self, c, h, l, ts):
        if not self.in_pos:
            return None

        bars_held = self.bars_seen - self.pos_bar
        risk_dist = self.pos_risk_dist
        current_r = (c - self.pos_entry) * self.pos_dir / risk_dist if risk_dist > 0 else 0
        self.pos_best_r = max(self.pos_best_r, current_r)

        # Multi-level trailing (ATR-based)
        trail_configs = [
            (1.0, 0.5),   # +1R: trail at 0.5x ATR behind
            (2.0, 0.4),   # +2R: trail at 0.4x ATR
            (3.0, 0.3),   # +3R: trail at 0.3x ATR
            (5.0, 0.2),   # +5R: trail at 0.2x ATR
        ]

        new_level = -1
        for i, (trigger, _) in enumerate(trail_configs):
            if self.pos_best_r >= trigger:
                new_level = i

        if new_level > self.pos_trail_level:
            self.pos_trail_level = new_level

        if self.pos_trail_level >= 0:
            trail_atr_mult = trail_configs[self.pos_trail_level][1]
            trail_distance = self.atr * trail_atr_mult
            if self.pos_dir > 0:
                self.pos_sl = max(self.pos_sl, c - trail_distance)
            else:
                self.pos_sl = min(self.pos_sl, c + trail_distance)

        # Check exits
        exit_price = 0
        reason = ""

        if self.pos_dir > 0:
            if l <= self.pos_sl:
                exit_price = self.pos_sl
                reason = "TRAIL" if self.pos_trail_level >= 0 else "STOP"
            elif h >= self.pos_tp:
                exit_price, reason = self.pos_tp, "TARGET"
        else:
            if h >= self.pos_sl:
                exit_price = self.pos_sl
                reason = "TRAIL" if self.pos_trail_level >= 0 else "STOP"
            elif l <= self.pos_tp:
                exit_price, reason = self.pos_tp, "TARGET"

        max_hold = 24
        if not reason and bars_held >= max_hold:
            exit_price, reason = c, "TIME"

        if reason:
            slipped = exit_price - 0.05 if self.pos_dir > 0 else exit_price + 0.05
            rr = (slipped - self.pos_entry) * self.pos_dir / risk_dist if risk_dist > 0 else 0
            pnl = self.pos_stake * rr
            self.equity += pnl
            self.peak_equity = max(self.peak_equity, self.equity)
            self.trade_results.append(pnl)
            self.total_trades += 1

            if rr > 0:
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
                self.cooldown = 3

            trade = {
                'num': self.total_trades, 'time': ts,
                'side': 'BUY' if self.pos_dir > 0 else 'SELL',
                'entry': self.pos_entry, 'exit': slipped,
                'reason': reason, 'rr': rr, 'pnl': pnl,
                'equity': self.equity, 'bars_held': bars_held,
                'trail_level': self.pos_trail_level,
            }
            self.trades.append(trade)

            self.in_pos = False
            self.pos_dir = 0
            self.pos_trail_level = -1
            return trade

        return None


def run_engine(rates, label=""):
    engine = EngineV8()
    for rate in rates:
        engine.process_bar(rate)
    return engine


def print_results(engine, symbol):
    trades = engine.trades
    if not trades:
        print(f"  {symbol}: No trades")
        return None

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100
    pnl = sum(t['pnl'] for t in trades)
    gp = sum(t['pnl'] for t in wins) if wins else 0
    gl = abs(sum(t['pnl'] for t in losses)) if losses else 0
    pf = gp / gl if gl > 0 else 999
    avg_win = gp / len(wins) if wins else 0
    avg_loss = gl / len(losses) if losses else 0

    equity = 10000.0; peak = 10000.0; max_dd = 0.0
    for t in trades:
        equity += t['pnl']; peak = max(peak, equity)
        dd = (peak - equity) / peak; max_dd = max(max_dd, dd)

    max_consec = 0; streak = 0
    for t in trades:
        if t['pnl'] <= 0: streak += 1; max_consec = max(max_consec, streak)
        else: streak = 0

    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = {'count': 0, 'pnl': 0, 'rr_sum': 0}
        reasons[r]['count'] += 1
        reasons[r]['pnl'] += t['pnl']
        reasons[r]['rr_sum'] += t['rr']

    print(f"\n{'=' * 100}")
    print(f"  ENGINE v8 — {symbol}")
    print(f"{'=' * 100}")
    print(f"  Trades:          {len(trades)}")
    print(f"  Wins:            {len(wins)} ({win_rate:.1f}%)")
    print(f"  Losses:          {len(losses)}")
    print(f"  Total P&L:       ${pnl:+,.2f} ({pnl/100:.1f}%)")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Avg Win:         ${avg_win:+,.2f}")
    print(f"  Avg Loss:        ${-avg_loss:+,.2f}")
    print(f"  Payoff Ratio:    {avg_win/avg_loss:.2f}" if avg_loss > 0 else "  Payoff Ratio:    N/A")
    print(f"  Max Drawdown:    {max_dd*100:.2f}%")
    print(f"  Max Consec Loss: {max_consec}")
    print(f"  Final Equity:    ${engine.equity:,.2f}")

    print(f"\n  EXIT REASONS:")
    for reason, data in sorted(reasons.items()):
        avg_rr = data['rr_sum'] / data['count'] if data['count'] > 0 else 0
        print(f"    {reason:15s}: {data['count']:3d} trades, ${data['pnl']:+12,.2f}, avg R={avg_rr:+.3f}")

    print(f"\n  TRADE LOG:")
    print(f"  {'#':>3} | {'TIME':16} | {'SIDE':4} | {'ENTRY':>10} | {'EXIT':>10} | {'REASON':5} | {'R':>6} | {'P&L':>10} | {'EQUITY':>12} | LVL")
    print("  " + "-" * 95)
    for t in trades:
        cc = "\033[92m" if t['pnl'] > 0 else "\033[91m"
        r = "\033[0m"
        lv = f"L{t['trail_level']}" if t['trail_level'] >= 0 else "---"
        print(f"  {cc}{t['num']:3d} | {t['time']:16} | {t['side']:4s} | {t['entry']:10.2f} | {t['exit']:10.2f} | {t['reason']:5s} | {t['rr']:+6.3f} | {t['pnl']:+10.2f} | ${t['equity']:>10.2f} | {lv}{r}")

    print(f"\n  EQUITY CURVE:")
    eqs = [10000.0] + [t['equity'] for t in trades]
    mn = min(eqs); mx = max(eqs); w = 50
    for idx, e in enumerate(eqs):
        bl = int((e - mn) / max(mx - mn, 1) * w) if mx > mn else w // 2
        mk = "---" if idx == 0 else f"#{idx:3d}"
        print(f"  {mk} | {'#' * bl}${e:>9.2f}")
    print(f"{'=' * 100}")

    return {'symbol': symbol, 'trades': len(trades), 'wins': len(wins),
            'win_rate': win_rate, 'pnl': pnl, 'pf': pf,
            'max_dd': max_dd, 'max_consec': max_consec}


def main():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed"); return

    symbols = ["Volatility 75 Index", "Volatility 100 Index"]
    results = {}

    for symbol in symbols:
        print(f"\n  Loading {symbol}...")
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 8640)
        if rates is None or len(rates) < 200:
            print(f"  [SKIP]"); continue
        print(f"  {len(rates)} M5 bars ({datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d %H:%M')})")
        engine = run_engine(rates)
        r = print_results(engine, symbol)
        if r: results[symbol] = r

    if len(results) == 2:
        s75, s100 = results["Volatility 75 Index"], results["Volatility 100 Index"]
        print(f"\n{'=' * 100}")
        print(f"  FINAL COMPARISON — ENGINE v8")
        print(f"{'=' * 100}")
        print(f"\n  {'Metric':<20} | {'Volatility 75':>15} | {'Volatility 100':>15} | {'Winner':>15}")
        print(f"  {'-'*20}-+-{'-'*15}-+-{'-'*15}-+-{'-'*15}")
        for name, key, d in [
            ('Trades', 'trades', 'higher'), ('Win Rate', 'win_rate', 'higher'),
            ('Total P&L', 'pnl', 'higher'), ('Profit Factor', 'pf', 'higher'),
            ('Max Drawdown', 'max_dd', 'lower'), ('Max Consec Loss', 'max_consec', 'lower')]:
            v75, v100 = s75[key], s100[key]
            if key == 'pnl': v75s, v100s = f"${v75:+,.2f}", f"${v100:+,.2f}"
            elif key == 'win_rate': v75s, v100s = f"{v75:.1f}%", f"{v100:.1f}%"
            elif key == 'pf': v75s, v100s = f"{v75:.2f}", f"{v100:.2f}"
            elif key == 'max_dd': v75s, v100s = f"{v75*100:.2f}%", f"{v100*100:.2f}%"
            else: v75s, v100s = f"{v75}", f"{v100}"
            w = "Vol 75" if (v75 > v100 if d == 'higher' else v75 < v100) else "Vol 100" if v100 != v75 else "TIE"
            print(f"  {name:<20} | {v75s:>15} | {v100s:>15} | {w:>15}")
        print(f"\n{'=' * 100}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
