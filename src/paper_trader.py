#!/usr/bin/env python
"""
MITEMSHUB AI — Paper Trading Simulator
Runs the exact same GARCH band strategy as the MQL5 EA,
using live Deriv MT5 tick data. No warmup delay — preloads
historical bars to start immediately.
"""

import MetaTrader5 as mt5
import math
import time
import sys
import os
from datetime import datetime, timedelta

LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'paper_trades.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Tee print to file too
class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()
    def flush(self):
        for s in self.streams:
            s.flush()

_log = open(LOG_FILE, 'a', encoding='utf-8')
sys.stdout = Tee(sys.__stdout__, _log)
sys.stderr = Tee(sys.__stderr__, _log)

# ─── GARCH Forecaster (matches CGarchForecaster in MQL5) ──────────
class GarchForecaster:
    def __init__(self, omega=-1.884103, alpha=0.142169, gamma=-0.073285, beta=0.852741):
        self.omega = omega
        self.alpha = alpha
        self.gamma = gamma
        self.beta = beta
        self.log_sigma2 = 0.0
        self.last_z = 0.0
        self.n_obs = 0
        self._log_ret_sum = 0.0
        self._log_ret_sq_sum = 0.0

    def update(self, log_ret):
        """Update GARCH and return current sigma."""
        self.n_obs += 1
        self._log_ret_sum += log_ret
        self._log_ret_sq_sum += log_ret * log_ret

        if self.n_obs < 10:
            # Seed with sample variance
            if self.n_obs == 1:
                self.log_sigma2 = math.log(max(log_ret * log_ret, 1e-12))
            else:
                var = self._log_ret_sq_sum / self.n_obs
                self.log_sigma2 = math.log(max(var, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self.last_z = log_ret / max(sigma, 1e-12)
            return sigma

        # EGARCH-style update
        prev_sigma2 = math.exp(self.log_sigma2)
        prev_sigma = math.sqrt(prev_sigma2)
        z = log_ret / max(prev_sigma, 1e-12)

        # Log-variance update: ln(sigma_t^2) = omega + alpha*|z| + gamma*z + beta*ln(sigma_{t-1}^2)
        innovation = self.omega + self.alpha * abs(z) + self.gamma * z + self.beta * self.log_sigma2
        self.log_sigma2 = innovation
        sigma = math.exp(self.log_sigma2 / 2.0)
        self.last_z = z
        return sigma

    def observations(self):
        return self.n_obs


# ─── Strategy Parameters (matching EA defaults) ──────────────────
BAR_SEC = 300          # M5 bars from ticks
Z_ENTRY = 1.8          # z-score threshold for entry (paper relaxed from 2.2)
VOL_GATE_RATIO = 1.15  # volatility must be elevated (paper relaxed from 1.3)
MIN_REVERT_SIGNAL = 0.01
EMA_PERIOD = 20
SIGMA_EMA_PERIOD = 30
WARMUP_CANDLES = 60    # only needed for first-time init
STOP_SIGMA_MULT = 0.12
TARGET_SIGMA_MULT = 1.0
HOLD_SEC = 3600
MIN_TARGET_RR = 1.5
MAX_STOP_PCT = 0.015
EXIT_SLIPPAGE = 0.05
RISK_PER_TRADE = 0.005


# ─── Paper Position Tracker ───────────────────────────────────────
class PaperPosition:
    def __init__(self):
        self.clear()

    def clear(self):
        self.direction = 0   # +1 = BUY, -1 = SELL
        self.entry = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.entry_time = None
        self.stake = 0.0

    def open(self, direction, entry, sl, tp, stake):
        self.direction = direction
        self.entry = entry
        self.stop_loss = sl
        self.take_profit = tp
        self.entry_time = datetime.now()
        self.stake = stake

    def is_open(self):
        return self.direction != 0

    def check_exit(self, high, low, close):
        """Check if position should be closed. Returns (exit_price, reason) or (0, None)."""
        if not self.is_open():
            return 0, None

        # BUY position
        if self.direction > 0:
            if low <= self.stop_loss:
                return self.stop_loss, "STOP"
            if high >= self.take_profit:
                return self.take_profit, "TARGET"
        # SELL position
        else:
            if high >= self.stop_loss:
                return self.stop_loss, "STOP"
            if low <= self.take_profit:
                return self.take_profit, "TARGET"

        # Time exit
        elapsed = (datetime.now() - self.entry_time).total_seconds()
        if elapsed >= HOLD_SEC:
            return close, "TIME"

        return 0, None


# ─── Mean Revert Signal (matches EA) ──────────────────────────────
class ZRingBuffer:
    def __init__(self, size=50):
        self.ring = [0.0] * size
        self.head = 0
        self.count = 0

    def push(self, z):
        self.ring[self.head] = z
        self.head = (self.head + 1) % len(self.ring)
        if self.count < len(self.ring):
            self.count += 1

    def mean_revert_signal(self, z_t):
        if self.count < 5:
            return 0.0
        recent = 0
        take = min(10, self.count)
        for k in range(take):
            idx = (self.head - 1 - k) % len(self.ring)
            if abs(self.ring[idx]) > 2.0:
                recent += 1
        az = abs(z_t)
        if az < 1.0:
            return 0.0
        if az < 2.0:
            return min(0.3, recent * 0.05)
        if az < 3.0:
            return min(0.6, 0.3 + recent * 0.05)
        return min(0.9, 0.5 + recent * 0.07)


# ─── Bar Aggregator (matches CBarAggregator) ──────────────────────
class BarAggregator:
    def __init__(self, bar_sec):
        self.bar_sec = bar_sec
        self.reset()

    def reset(self):
        self.open_price = 0.0
        self.high = 0.0
        self.low = 0.0
        self.close = 0.0
        self.bar_time = 0
        self.bar_start = 0

    def on_tick(self, bid, tick_time):
        """Feed tick, returns True if a bar closed."""
        if bid <= 0:
            return False

        bar_idx = tick_time // self.bar_sec
        bar_start = bar_idx * self.bar_sec

        if self.bar_start == 0:
            # First tick
            self.open_price = bid
            self.high = bid
            self.low = bid
            self.close = bid
            self.bar_start = bar_start
            self.bar_time = bar_start
            return False

        if bar_start > self.bar_start:
            # New bar — close the previous one
            closed = True
            # Start new bar
            self.open_price = bid
            self.high = bid
            self.low = bid
            self.close = bid
            self.bar_start = bar_start
            self.bar_time = bar_start
            return True

        # Same bar
        self.high = max(self.high, bid)
        self.low = min(self.low, bid)
        self.close = bid
        return False

    def get_closed_bar(self):
        """Returns (open, high, low, close, time) of last closed bar."""
        return (self.open_price, self.high, self.low, self.close, self.bar_time)


# ─── Main Paper Trader ────────────────────────────────────────────
def run_paper_trader():
    if not mt5.initialize():
        print("[ERROR] MT5 initialize failed:", mt5.last_error())
        return

    symbol = "Volatility 75 Index"
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"[ERROR] Symbol '{symbol}' not found")
        mt5.shutdown()
        return

    # Enable symbol if needed
    if not info.visible:
        mt5.symbol_select(symbol, True)

    acct = mt5.account_info()
    print("=" * 70)
    print("  MITEMSHUB AI — Paper Trading Simulator")
    print("  Same GARCH Band Strategy as the MQL5 EA")
    print("=" * 70)
    print(f"  Account:   {acct.login}@{acct.server}")
    print(f"  Symbol:    {symbol}")
    print(f"  Balance:   ${acct.balance:.2f} (paper)")
    print(f"  Bar Sec:   {BAR_SEC} ({BAR_SEC // 60}min bars)")
    print(f"  Z Entry:   {Z_ENTRY}")
    print(f"  Warmup:    {WARMUP_CANDLES} candles")
    print(f"  Risk:      {RISK_PER_TRADE * 100:.1f}% per trade")
    print(f"  Hold:      {HOLD_SEC // 60} minutes")
    print(f"  Stop:      {STOP_SIGMA_MULT} x sigma")
    print(f"  Target:    {TARGET_SIGMA_MULT} x sigma")
    print("=" * 70)
    print()

    # Preload historical data for warmup
    print("[INIT] Loading historical M5 bars for warmup...")
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 200)
    if rates is None or len(rates) < WARMUP_CANDLES:
        print(f"[ERROR] Not enough historical data: {len(rates) if rates is not None else 0} bars")
        mt5.shutdown()
        return

    print(f"[INIT] Loaded {len(rates)} historical M5 bars")

    # Initialize engines
    garch = GarchForecaster()
    zbuf = ZRingBuffer()
    agg = BarAggregator(BAR_SEC)
    pos = PaperPosition()

    # State variables
    prev_close = 0.0
    ema = 0.0
    sigma = 0.0
    sigma_ema = 0.0
    prev_sigma = 0.0
    bars_seen = 0
    atr_ema = 0.0
    equity = 10000.0
    initial_equity = 10000.0

    # Trading stats
    trades = []
    total_r = 0.0
    wins = 0
    losses = 0
    total_trades = 0

    # Feed historical bars for warmup
    print("[INIT] Feeding historical bars for GARCH warmup...")
    for i, rate in enumerate(rates):
        o, h, l, c = rate['open'], rate['high'], rate['low'], rate['close']
        t = int(rate['time'])

        if prev_close <= 0:
            prev_close = c
            ema = c
            continue

        log_ret = math.log(c / prev_close) if prev_close > 0 else 0
        prev_close = c

        prev_sigma = sigma
        sigma = garch.update(log_ret)
        if garch.observations() >= 10:
            zbuf.push(garch.last_z)

        # Update EMAs
        sigma_alpha = 2.0 / (SIGMA_EMA_PERIOD + 1.0)
        if sigma_ema <= 0:
            sigma_ema = sigma
        else:
            sigma_ema = sigma_ema * (1.0 - sigma_alpha) + sigma * sigma_alpha

        ema_alpha = 2.0 / (EMA_PERIOD + 1.0)
        ema = ema * (1.0 - ema_alpha) + c * ema_alpha

        bars_seen += 1

        # Check exit on historical bars (just for warmup)
        if pos.is_open():
            ep, reason = pos.check_exit(h, l, c)
            if ep > 0:
                slipped = ep - EXIT_SLIPPAGE if pos.direction > 0 else ep + EXIT_SLIPPAGE
                rr = 0.0
                pnl = pos.stake * rr
                equity += pnl
                trades.append({
                    'dir': 'BUY' if pos.direction > 0 else 'SELL',
                    'entry': pos.entry,
                    'exit': slipped,
                    'reason': reason,
                    'rr': rr,
                    'pnl': pnl,
                    'bars': bars_seen
                })
                pos.clear()

    print(f"[INIT] Warmup complete: {bars_seen} bars, GARCH observations: {garch.observations()}")
    print(f"[INIT] Starting live paper trading on {symbol}...")
    print()
    print("-" * 70)
    print("  TIME       | SIGNAL  | ENTRY     | SL        | TP        | Z     | STATUS")
    print("-" * 70)

    # ─── Live tick loop ───────────────────────────────────────────
    last_print = time.time()
    try:
        while True:
            tick = mt5.copy_ticks_from(symbol, mt5.symbol_info_tick(symbol).time, 1, mt5.COPY_TICKS_ALL)
            if tick is None or len(tick) == 0:
                time.sleep(0.1)
                continue

            bid = tick[0]['bid']
            ask = tick[0]['ask']
            tick_time = int(tick[0]['time'])
            now_str = datetime.now().strftime("%H:%M:%S")

            if bid <= 0:
                continue

            bar_closed = agg.on_tick(bid, tick_time)

            # ─── Check exits on every tick ──────────────────────
            if pos.is_open():
                ep, reason = pos.check_exit(agg.high, agg.low, agg.close)
                if ep > 0:
                    slipped = ep - EXIT_SLIPPAGE if pos.direction > 0 else ep + EXIT_SLIPPAGE
                    # Calculate R-multiple
                    risk_dist = abs(pos.entry - pos.stop_loss)
                    if risk_dist > 0:
                        rr = (slipped - pos.entry) * pos.direction / risk_dist
                    else:
                        rr = 0.0
                    pnl = pos.stake * rr
                    equity += pnl
                    total_r += rr
                    total_trades += 1
                    if rr > 0:
                        wins += 1
                    else:
                        losses += 1
                    trades.append({
                        'dir': 'BUY' if pos.direction > 0 else 'SELL',
                        'entry': pos.entry,
                        'exit': slipped,
                        'reason': reason,
                        'rr': rr,
                        'pnl': pnl,
                        'bars': bars_seen,
                        'time': now_str
                    })
                    color = "\033[92m" if rr > 0 else "\033[91m"
                    reset = "\033[0m"
                    wr = f"{wins}/{total_trades}" if total_trades > 0 else "0/0"
                    print(f"  {now_str} | {color}EXIT {reason:5s}{reset} | {pos.entry:.2f} | {slipped:.2f} | --- | ---   | R={rr:+.3f} | Equity=${equity:.2f} | W/L={wr}")
                    pos.clear()
                    # Update dashboard
                    if time.time() - last_print >= 5:
                        _print_dashboard(now_str, equity, initial_equity, total_trades, wins, losses, total_r, sigma, garch.last_z, bars_seen, pos)
                        last_print = time.time()
                    continue

            # ─── Process closed bar → signals ───────────────────
            if bar_closed:
                closed_bar = agg.get_closed_bar()
                _, h, l, c, bt = closed_bar

                if prev_close <= 0:
                    prev_close = c
                    ema = c
                    bars_seen += 1
                    continue

                log_ret = math.log(c / prev_close) if prev_close > 0 else 0
                prev_close = c

                prev_sigma = sigma
                sigma = garch.update(log_ret)
                if garch.observations() >= 10:
                    zbuf.push(garch.last_z)

                sigma_alpha = 2.0 / (SIGMA_EMA_PERIOD + 1.0)
                if sigma_ema <= 0:
                    sigma_ema = sigma
                else:
                    sigma_ema = sigma_ema * (1.0 - sigma_alpha) + sigma * sigma_alpha

                ema_alpha = 2.0 / (EMA_PERIOD + 1.0)
                ema = ema * (1.0 - ema_alpha) + c * ema_alpha

                bars_seen += 1

                # ─── Entry Logic (matches EA ProcessOneBar) ──────
                if pos.is_open():
                    continue  # already in a position

                if bars_seen < WARMUP_CANDLES:
                    continue

                if garch.observations() < 30:
                    continue

                if sigma_ema <= 0 or prev_sigma <= 0:
                    continue

                # Volatility gate
                if not (prev_sigma > VOL_GATE_RATIO * sigma_ema):
                    continue

                # Mean revert signal
                if MIN_REVERT_SIGNAL > 0:
                    revert = zbuf.mean_revert_signal(garch.last_z)
                    if revert < MIN_REVERT_SIGNAL:
                        continue

                # Z-score deviation
                z_dev = math.log(c / ema) / max(prev_sigma, 1e-12)
                if abs(z_dev) < Z_ENTRY:
                    continue

                direction = -1 if z_dev > 0 else 1  # fade the extension
                depth = abs(z_dev) / Z_ENTRY

                # Calculate stop and target (sigma in log-return space -> price space)
                stop_dist = c * STOP_SIGMA_MULT * sigma
                target_dist = c * TARGET_SIGMA_MULT * sigma

                if direction > 0:  # BUY
                    sl = c - stop_dist
                    tp = c + target_dist
                else:  # SELL
                    sl = c + stop_dist
                    tp = c - target_dist

                # Risk check
                risk_dist = abs(c - sl)
                if risk_dist <= 0:
                    continue
                rr = abs(tp - c) / risk_dist

                if rr < MIN_TARGET_RR:
                    continue

                if abs(c - sl) / c > MAX_STOP_PCT:
                    continue

                # Calculate stake
                risk_amount = equity * RISK_PER_TRADE
                stake = risk_amount

                # Open paper position
                pos.open(direction, c, sl, tp, stake)
                side = "BUY" if direction > 0 else "SELL"
                print(f"  {now_str} | ENTRY   | {side:4s} @ {c:.2f} | SL={sl:.2f} | TP={tp:.2f} | z={z_dev:.2f} | depth={depth:.2f} | RR={rr:.1f}")

            # Periodic dashboard update
            if time.time() - last_print >= 5:
                _print_dashboard(now_str, equity, initial_equity, total_trades, wins, losses, total_r, sigma, garch.last_z, bars_seen, pos)
                last_print = time.time()

            time.sleep(0.05)  # 50ms tick rate

    except KeyboardInterrupt:
        print("\n\n[STOPPED] Paper trading stopped by user.")

    # Final summary
    print()
    print("=" * 70)
    print("  PAPER TRADING SESSION SUMMARY")
    print("=" * 70)
    print(f"  Total Trades:  {total_trades}")
    print(f"  Wins:          {wins}")
    print(f"  Losses:        {losses}")
    wr = (wins / total_trades * 100) if total_trades > 0 else 0
    print(f"  Win Rate:      {wr:.1f}%")
    print(f"  Total R:       {total_r:+.3f}")
    avg_r = (total_r / total_trades) if total_trades > 0 else 0
    print(f"  Avg R/Trade:   {avg_r:+.3f}")
    print(f"  Starting $:    ${initial_equity:.2f}")
    print(f"  Final $:       ${equity:.2f}")
    pnl = equity - initial_equity
    print(f"  Paper P&L:     ${pnl:+.2f} ({pnl / initial_equity * 100:+.2f}%)")
    print("=" * 70)

    if total_trades > 0:
        print()
        print("  TRADE LOG:")
        print(f"  {'#':>3} | {'TIME':>8} | {'SIDE':4} | {'ENTRY':>8} | {'EXIT':>8} | {'REASON':5} | {'R':>6} | {'P&L':>8}")
        print("  " + "-" * 65)
        for i, t in enumerate(trades):
            time_str = t.get('time', '--:--:--')
            print(f"  {i+1:3d} | {time_str:>8} | {t['dir']:4s} | {t['entry']:8.2f} | {t['exit']:8.2f} | {t['reason']:5s} | {t['rr']:+6.3f} | {t['pnl']:+8.2f}")

    mt5.shutdown()


def _print_dashboard(now_str, equity, initial_equity, total_trades, wins, losses, total_r, sigma, z, bars_seen, pos):
    """Print a compact dashboard line."""
    wr = f"{wins}/{total_trades}" if total_trades > 0 else "0/0"
    pnl = equity - initial_equity
    pnl_pct = pnl / initial_equity * 100

    if pos.is_open():
        side = "BUY" if pos.direction > 0 else "SELL"
        status = f"OPEN {side}@{pos.entry:.2f} SL={pos.stop_loss:.2f} TP={pos.take_profit:.2f}"
    else:
        status = "SCANNING..."

    print(f"\033[90m  [{now_str}] Bars={bars_seen} sigma={sigma:.4f} z={z:.2f} | "
          f"Trades={wr} R={total_r:+.3f} | ${equity:.2f} ({pnl_pct:+.2f}%) | {status}\033[0m")


if __name__ == "__main__":
    run_paper_trader()
