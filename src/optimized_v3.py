#!/usr/bin/env python
"""
MITEMSHUB AI — Optimized Strategy v3
Uses the ACTUAL GARCH parameters from the EA's runtime log:
  omega=-1.1150 alpha=0.0770 gamma=0.0110 beta=0.9180
"""

import MetaTrader5 as mt5
import math
import sys
from datetime import datetime

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
                var = self._sq_sum / self.n_obs
                self.log_sigma2 = math.log(max(var, 1e-12))
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


def run():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed:", mt5.last_error())
        return

    symbol = "Volatility 75 Index"
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 8640)
    if rates is None or len(rates) < 200:
        print("[ERROR] Not enough data")
        mt5.shutdown()
        return

    # First: calibrate the vol gate ratio from the data
    # The EA's vol gate is: prev_sigma > ratio * sigma_ema
    # We need to find what ratio gives ~3-5 signals per week
    print("=" * 78)
    print("  MITEMSHUB AI — CALIBRATED STRATEGY (v3)")
    print("  Volatility 75 Index | M5 | 30 Days")
    print("=" * 78)
    print()
    print("  ACTUAL EA GARCH PARAMETERS (from runtime log):")
    print("  omega=-1.1150 alpha=0.0770 gamma=0.0110 beta=0.9180")
    print()

    # Calibrate: find what vol gate ratio produces reasonable signal count
    print("  CALIBRATING VOL GATE RATIO...")
    for test_ratio in [1.01, 1.02, 1.03, 1.05, 1.08, 1.10, 1.15, 1.20]:
        garch = GarchForecaster(-1.1150, 0.0770, 0.0110, 0.9180)
        sigma_ema = 0.0
        ema = 0.0
        prev_close = 0.0
        bars_seen = 0
        vol_passes = 0
        z_passes = 0
        for rate in rates:
            c = rate['close']
            bars_seen += 1
            if prev_close <= 0:
                prev_close = c; ema = c; continue
            lr = math.log(c / prev_close)
            prev_close = c
            ps = math.exp(garch.log_sigma2 / 2.0)
            z = lr / max(ps, 1e-12)
            sig = garch.update(lr)
            sa = 2.0 / 31.0
            sigma_ema = sig if sigma_ema <= 0 else sigma_ema * (1 - sa) + sig * sa
            ea = 2.0 / 21.0
            ema = ema * (1 - ea) + c * ea
            if bars_seen < 60: continue
            if ps > test_ratio * sigma_ema:
                vol_passes += 1
                z_dev = math.log(c / ema) / max(ps, 1e-12)
                if abs(z_dev) > 2.0:
                    z_passes += 1
        print(f"    ratio={test_ratio:.2f}: vol_pass={vol_passes:4d} z_pass={z_passes:4d} (est ~{z_passes*2:.0f} trades/month)")

    print()

    # Run backtest with best ratio
    # From calibration, find the ratio that gives 60-100 trades/month (2-3/day)
    # Typically ratio ~1.02-1.05 for this GARCH model

    # ─── Run with multiple configurations ────────────────────────
    configs = [
        {"name": "TIGHT: z=2.0, stop=0.15, hold=12, ratio=1.03",
         "z_entry": 2.0, "stop_mult": 0.15, "target_mult": 0.8,
         "hold": 12, "min_rr": 1.5, "vol_ratio": 1.03, "min_revert": 0.02,
         "trend_filter": False},
        {"name": "BALANCED: z=2.2, stop=0.12, hold=12, ratio=1.03",
         "z_entry": 2.2, "stop_mult": 0.12, "target_mult": 1.0,
         "hold": 12, "min_rr": 2.0, "vol_ratio": 1.03, "min_revert": 0.02,
         "trend_filter": False},
        {"name": "WIDE: z=2.5, stop=0.20, hold=18, ratio=1.03",
         "z_entry": 2.5, "stop_mult": 0.20, "target_mult": 1.2,
         "hold": 18, "min_rr": 2.0, "vol_ratio": 1.03, "min_revert": 0.02,
         "trend_filter": True},
    ]

    best_result = None
    best_config = None

    for cfg in configs:
        print(f"\n  --- {cfg['name']} ---")

        garch = GarchForecaster(-1.1150, 0.0770, 0.0110, 0.9180)
        zbuf = ZRingBuffer()
        equity = 10000.0
        peak_equity = 10000.0
        bars_seen = 0
        prev_close = 0.0
        ema = 0.0
        sigma = 0.0
        sigma_ema = 0.0
        ema_history = []

        in_pos = False
        pos_dir = 0
        pos_entry = 0.0
        pos_sl = 0.0
        pos_tp = 0.0
        pos_bar = 0
        pos_stake = 0.0

        trades = []
        total_trades = 0
        wins = 0
        losses = 0
        total_r = 0.0
        max_dd = 0.0
        consec_losses = 0
        max_consec = 0

        for i, rate in enumerate(rates):
            c = rate['close']
            h = rate['high']
            l = rate['low']
            t = rate['time']
            ts = datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
            bars_seen += 1

            if prev_close <= 0:
                prev_close = c; ema = c; ema_history.append(c)
                continue

            log_ret = math.log(c / prev_close) if prev_close > 0 else 0
            prev_close = c

            prev_sigma = sigma
            sigma = garch.update(log_ret)
            if garch.observations() >= 10:
                zbuf.push(garch.last_z)

            sa = 2.0 / (SIGMA_EMA_PERIOD := 30) / 1.0 if False else 2.0 / 31.0
            sigma_ema = sigma if sigma_ema <= 0 else sigma_ema * (1 - sa) + sigma * sa
            ea = 2.0 / 21.0
            ema = ema * (1 - ea) + c * ea
            ema_history.append(ema)
            if len(ema_history) > 50:
                ema_history.pop(0)

            # Check exit
            if in_pos:
                bars_held = bars_seen - pos_bar
                exit_price = 0
                reason = ""

                if pos_dir > 0:
                    if l <= pos_sl: exit_price, reason = pos_sl, "STOP"
                    elif h >= pos_tp: exit_price, reason = pos_tp, "TARGET"
                else:
                    if h >= pos_sl: exit_price, reason = pos_sl, "STOP"
                    elif l <= pos_tp: exit_price, reason = pos_tp, "TARGET"

                if not reason and bars_held >= cfg['hold']:
                    exit_price, reason = c, "TIME"

                if reason:
                    risk_dist = abs(pos_entry - pos_sl)
                    slipped = exit_price - 0.05 if pos_dir > 0 else exit_price + 0.05
                    rr = (slipped - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
                    pnl = pos_stake * rr
                    equity += pnl
                    total_r += rr
                    total_trades += 1
                    if rr > 0:
                        wins += 1
                        consec_losses = 0
                    else:
                        losses += 1
                        consec_losses += 1
                        max_consec = max(max_consec, consec_losses)

                    peak_equity = max(peak_equity, equity)
                    dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
                    max_dd = max(max_dd, dd)

                    trades.append({
                        'num': total_trades, 'time': ts,
                        'dir': 'BUY' if pos_dir > 0 else 'SELL',
                        'entry': pos_entry, 'exit': slipped, 'reason': reason,
                        'rr': rr, 'pnl': pnl, 'equity': equity, 'bars_held': bars_held
                    })
                    in_pos = False
                    pos_dir = 0
                    continue

            # Entry logic
            if in_pos or bars_seen < 60 or garch.observations() < 30:
                continue
            if sigma_ema <= 0 or prev_sigma <= 0:
                continue
            if not (prev_sigma > cfg['vol_ratio'] * sigma_ema):
                continue
            if cfg['min_revert'] > 0:
                rev = zbuf.mean_revert_signal(garch.last_z)
                if rev < cfg['min_revert']:
                    continue
            z_dev = math.log(c / ema) / max(prev_sigma, 1e-12)
            if abs(z_dev) < cfg['z_entry']:
                continue

            # Trend filter
            if cfg['trend_filter'] and len(ema_history) >= 10:
                slope = ema_history[-1] - ema_history[-10]
                slope_pct = slope / ema_history[-1] * 100 if ema_history[-1] > 0 else 0
                if z_dev < 0 and slope_pct < -0.05: continue  # Don't buy in downtrend
                if z_dev > 0 and slope_pct > 0.05: continue   # Don't sell in uptrend

            direction = -1 if z_dev > 0 else 1
            stop_dist = c * cfg['stop_mult'] * sigma
            target_dist = c * cfg['target_mult'] * sigma

            sl = (c - stop_dist) if direction > 0 else (c + stop_dist)
            tp = (c + target_dist) if direction > 0 else (c - target_dist)

            risk_dist = abs(c - sl)
            if risk_dist <= 0: continue
            rr = abs(tp - c) / risk_dist
            if rr < cfg['min_rr']: continue
            if risk_dist / c > 0.015: continue

            stake = equity * 0.005

            in_pos = True
            pos_dir = direction
            pos_entry = c
            pos_sl = sl
            pos_tp = tp
            pos_bar = bars_seen
            pos_stake = stake

            side = "BUY" if direction > 0 else "SELL"
            print(f"  {ts} ENTRY {side:4s} @ {c:8.2f} SL={sl:.2f} TP={tp:.2f} z={z_dev:.2f}")

        # Close open
        if in_pos:
            last_c = rates[-1]['close']
            risk_dist = abs(pos_entry - pos_sl)
            rr = (last_c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
            pnl = pos_stake * rr
            equity += pnl
            total_r += rr
            total_trades += 1
            if rr > 0: wins += 1
            else: losses += 1

        wr = (wins / total_trades * 100) if total_trades > 0 else 0
        avg_r = (total_r / total_trades) if total_trades > 0 else 0
        net_pnl = equity - 10000.0
        monthly_ret = net_pnl / 10000.0 * 100
        gp = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        gl = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
        pf = gp / gl if gl > 0 else 999

        print(f"\n  RESULTS:")
        print(f"  Trades: {total_trades} | Wins: {wins} | Losses: {losses}")
        print(f"  Win Rate: {wr:.1f}% | Profit Factor: {pf:.2f}")
        print(f"  Total R: {total_r:+.3f} | Avg R: {avg_r:+.3f}")
        print(f"  Max DD: {max_dd*100:.2f}% | Max Consec: {max_consec}")
        print(f"  P&L: ${net_pnl:+,.2f} ({monthly_ret:+.2f}%)")

        # Show trade log
        if trades:
            print(f"\n  TRADE LOG:")
            for t in trades:
                c_color = "\033[92m" if t['rr'] > 0 else "\033[91m"
                reset = "\033[0m"
                print(f"  {c_color}#{t['num']:3d} {t['time']} {t['dir']:4s} @ {t['entry']:8.2f} -> {t['exit']:8.2f} {t['reason']:5s} R={t['rr']:+.3f} ${t['pnl']:+.2f}{reset}")

        # Track best
        if total_trades >= 5 and (best_result is None or avg_r > best_result['avg_r']):
            best_result = {'avg_r': avg_r, 'wr': wr, 'pf': pf, 'trades': total_trades, 'pnl': net_pnl, 'max_dd': max_dd, 'config': cfg['name'], 'max_consec': max_consec, 'total_r': total_r}
            best_config = cfg

    print()
    print("=" * 78)
    print("  OPTIMIZATION SUMMARY")
    print("=" * 78)
    if best_result:
        print(f"  BEST CONFIG: {best_result['config']}")
        print(f"  Trades: {best_result['trades']} | Win Rate: {best_result['wr']:.1f}%")
        print(f"  Profit Factor: {best_result['pf']:.2f} | Avg R: {best_result['avg_r']:+.3f}")
        print(f"  Total R: {best_result['total_r']:+.3f} | Max DD: {best_result['max_dd']*100:.2f}%")
        print(f"  Max Consec Loss: {best_result['max_consec']}")
        print(f"  Net P&L: ${best_result['pnl']:+,.2f} ({best_result['pnl']/100:+.2f}%)")
    else:
        print("  No configuration produced 5+ trades. Need to relax filters further.")
    print("=" * 78)

    mt5.shutdown()

if __name__ == "__main__":
    run()
