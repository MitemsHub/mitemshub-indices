#!/usr/bin/env python
"""
MITEMSHUB AI — Strategy Optimizer
Analyzes what went wrong, fixes the issues, and re-runs.
"""

import MetaTrader5 as mt5
import math
import sys
from datetime import datetime

# ─── GARCH Forecaster ──────────────────────────────────────────────
class GarchForecaster:
    def __init__(self, omega=-1.884103, alpha=0.142169, gamma=-0.073285, beta=0.852741):
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


def run_optimized_backtest():
    if not mt5.initialize():
        print("[ERROR] MT5 init failed:", mt5.last_error())
        return

    symbol = "Volatility 75 Index"
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 8640)
    if rates is None or len(rates) < 200:
        print(f"[ERROR] Not enough data")
        mt5.shutdown()
        return

    print("=" * 78)
    print("  MITEMSHUB AI — OPTIMIZED STRATEGY (v2)")
    print("  Volatility 75 Index | M5 | 30 Days")
    print("=" * 78)
    print()
    print("  CHANGES FROM v1:")
    print("  1. WIDER STOP: 0.20 sigma (was 0.12) -- gives room to breathe")
    print("  2. TREND FILTER: Only BUY when EMA slope > 0, SELL when < 0")
    print("  3. CONFIRMATION: Wait for price to move back toward EMA")
    print("  4. HIGHER Z-ENTRY: 2.5 (was 1.8) -- bigger extensions only")
    print("  5. VOL GATE: 1.2 (was 1.15) -- stricter volatility filter")
    print("  6. LONGER HOLD: 18 bars = 90 min (was 12 = 60 min)")
    print("=" * 78)
    print()

    # ─── Parameters (optimized v2) ────────────────────────────────
    Z_ENTRY = 2.5
    VOL_GATE_RATIO = 1.2
    MIN_REVERT = 0.02
    EMA_PERIOD = 20
    SIGMA_EMA_PERIOD = 30
    WARMUP = 60
    STOP_MULT = 0.20          # WIDER STOP — was 0.12
    TARGET_MULT = 1.2         # Slightly wider target
    MIN_RR = 2.0
    HOLD_BARS = 18            # 18 x 5min = 90min — was 12
    INITIAL_EQUITY = 10000.0
    RISK_PCT = 0.005
    EMA_SLOPE_PERIOD = 10     # Bars to measure EMA slope

    garch = GarchForecaster()
    zbuf = ZRingBuffer()
    equity = INITIAL_EQUITY
    peak_equity = INITIAL_EQUITY
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

    # Debug
    vol_blocked = 0
    revert_blocked = 0
    z_blocked = 0
    trend_blocked = 0
    rr_blocked = 0

    for i, rate in enumerate(rates):
        c = rate['close']
        h = rate['high']
        l = rate['low']
        t = rate['time']
        ts = datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
        bars_seen += 1

        if prev_close <= 0:
            prev_close = c
            ema = c
            ema_history.append(c)
            continue

        log_ret = math.log(c / prev_close) if prev_close > 0 else 0
        prev_close = c

        prev_sigma = sigma
        sigma = garch.update(log_ret)
        if garch.observations() >= 10:
            zbuf.push(garch.last_z)

        sa = 2.0 / (SIGMA_EMA_PERIOD + 1.0)
        sigma_ema = sigma if sigma_ema <= 0 else sigma_ema * (1 - sa) + sigma * sa
        ea = 2.0 / (EMA_PERIOD + 1.0)
        ema = ema * (1 - ea) + c * ea
        ema_history.append(ema)
        if len(ema_history) > 100:
            ema_history.pop(0)

        # ─── Check exit ──────────────────────────────────────────
        if in_pos:
            bars_held = bars_seen - pos_bar
            exit_price = 0
            reason = ""

            if pos_dir > 0:
                if l <= pos_sl:
                    exit_price, reason = pos_sl, "STOP"
                elif h >= pos_tp:
                    exit_price, reason = pos_tp, "TARGET"
            else:
                if h >= pos_sl:
                    exit_price, reason = pos_sl, "STOP"
                elif l <= pos_tp:
                    exit_price, reason = pos_tp, "TARGET"

            if not reason and bars_held >= HOLD_BARS:
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

                c_color = "\033[92m" if rr > 0 else "\033[91m"
                reset = "\033[0m"
                print(f"  {c_color}#{total_trades:3d} {ts} EXIT {reason:5s} @ {slipped:8.2f} R={rr:+.3f} P&L=${pnl:+.2f} Equity=${equity:,.2f}{reset}")
                in_pos = False
                pos_dir = 0
                continue

        # ─── Entry logic (v2 optimized) ──────────────────────────
        if in_pos:
            continue
        if bars_seen < WARMUP:
            continue
        if garch.observations() < 30:
            continue
        if sigma_ema <= 0 or prev_sigma <= 0:
            continue

        # 1. Volatility gate
        if not (prev_sigma > VOL_GATE_RATIO * sigma_ema):
            vol_blocked += 1
            continue

        # 2. Mean revert signal
        if MIN_REVERT > 0:
            rev = zbuf.mean_revert_signal(garch.last_z)
            if rev < MIN_REVERT:
                revert_blocked += 1
                continue

        # 3. Z-score deviation
        z_dev = math.log(c / ema) / max(prev_sigma, 1e-12)
        if abs(z_dev) < Z_ENTRY:
            z_blocked += 1
            continue

        # 4. TREND FILTER — NEW in v2
        # Measure EMA slope: positive = uptrend, negative = downtrend
        if len(ema_history) >= EMA_SLOPE_PERIOD:
            ema_slope = ema_history[-1] - ema_history[-EMA_SLOPE_PERIOD]
            ema_slope_pct = ema_slope / ema_history[-1] * 100 if ema_history[-1] > 0 else 0
        else:
            ema_slope_pct = 0

        # Only BUY when trend is up (or flat), only SELL when trend is down (or flat)
        # This filters out buying in strong downtrends and selling in strong uptrends
        if z_dev < 0:  # Want to BUY (price below EMA)
            if ema_slope_pct < -0.05:  # Strong downtrend — skip
                trend_blocked += 1
                continue
        else:  # Want to SELL (price above EMA)
            if ema_slope_pct > 0.05:  # Strong uptrend — skip
                trend_blocked += 1
                continue

        direction = -1 if z_dev > 0 else 1
        stop_dist = c * STOP_MULT * sigma
        target_dist = c * TARGET_MULT * sigma

        sl = (c - stop_dist) if direction > 0 else (c + stop_dist)
        tp = (c + target_dist) if direction > 0 else (c - target_dist)

        risk_dist = abs(c - sl)
        if risk_dist <= 0:
            continue
        rr = abs(tp - c) / risk_dist
        if rr < MIN_RR:
            rr_blocked += 1
            continue
        if risk_dist / c > 0.015:
            continue

        stake = equity * RISK_PCT

        in_pos = True
        pos_dir = direction
        pos_entry = c
        pos_sl = sl
        pos_tp = tp
        pos_bar = bars_seen
        pos_stake = stake

        side = "BUY" if direction > 0 else "SELL"
        print(f"  \033[96m#{total_trades+1:3d} {ts} ENTRY {side:4s} @ {c:8.2f} SL={sl:.2f} TP={tp:.2f} z={z_dev:.2f} trend={ema_slope_pct:+.4f}%\033[0m")

    # Close open position
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
        print(f"\n  [FORCE CLOSE] at {last_c:.2f} R={rr:+.3f}")

    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_r = (total_r / total_trades) if total_trades > 0 else 0
    net_pnl = equity - INITIAL_EQUITY
    monthly_ret = net_pnl / INITIAL_EQUITY * 100
    profit_factor = 0
    if losses > 0 and wins > 0:
        gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999

    print()
    print("=" * 78)
    print("  OPTIMIZED BACKTEST RESULTS (v2)")
    print("=" * 78)
    print(f"  Gate Analysis:")
    print(f"    Volatility blocked:  {vol_blocked}")
    print(f"    Revert blocked:      {revert_blocked}")
    print(f"    Z-score blocked:     {z_blocked}")
    print(f"    Trend blocked:       {trend_blocked}")
    print(f"    R:R blocked:         {rr_blocked}")
    print()
    print(f"  Total Trades:    {total_trades}")
    print(f"  Wins:            {wins}")
    print(f"  Losses:          {losses}")
    print(f"  Win Rate:        {wr:.1f}%")
    print(f"  Profit Factor:   {profit_factor:.2f}")
    print(f"  Total R:         {total_r:+.3f}")
    print(f"  Avg R/Trade:     {avg_r:+.3f}")
    print(f"  Max Consec Loss: {max_consec}")
    print(f"  Max Drawdown:    {max_dd * 100:.2f}%")
    print(f"  Starting Equity: ${INITIAL_EQUITY:,.2f}")
    print(f"  Final Equity:    ${equity:,.2f}")
    print(f"  Net P&L:         ${net_pnl:+,.2f} ({monthly_ret:+.2f}%)")
    if total_trades > 0:
        trades_per_day = total_trades / 30
        print(f"  Trades/Day:      {trades_per_day:.1f}")
        if avg_r > 0:
            annual_pct = avg_r * trades_per_day * 30 * 12 * RISK_PCT * 100
            print(f"  Est. Annual Ret: {annual_pct:+.1f}%")
    print("=" * 78)

    if trades:
        print()
        print("  TRADE LOG:")
        print(f"  {'#':>3} | {'DATE':16} | {'SIDE':4} | {'ENTRY':>8} | {'EXIT':>8} | {'REASON':5} | {'R':>6} | {'P&L':>8} | {'EQUITY':>10}")
        print("  " + "-" * 82)
        for t in trades:
            c_color = "\033[92m" if t['rr'] > 0 else "\033[91m"
            reset = "\033[0m"
            print(f"  {c_color}{t['num']:3d} | {t['time']:16} | {t['dir']:4s} | {t['entry']:8.2f} | {t['exit']:8.2f} | {t['reason']:5s} | {t['rr']:+6.3f} | {t['pnl']:+8.2f} | ${t['equity']:>8.2f}{reset}")

    if trades:
        print()
        print("  EQUITY CURVE:")
        eqs = [INITIAL_EQUITY] + [t['equity'] for t in trades]
        mn = min(eqs)
        mx = max(eqs)
        width = 40
        for idx, e in enumerate(eqs):
            bar_len = int((e - mn) / max(mx - mn, 1) * width) if mx > mn else width // 2
            label = f"${e:>9.2f}"
            marker = "---" if idx == 0 else f"#{idx:3d}"
            print(f"  {marker} | {'#' * bar_len}{label}")

    mt5.shutdown()

if __name__ == "__main__":
    run_optimized_backtest()
