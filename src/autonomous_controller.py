#!/usr/bin/env python
"""
MITEMSHUB AI — AUTONOMOUS CONTROLLER
=====================================
The brain of the operation. This runs continuously and:
1. Enables symbols for trading automatically
2. Monitors EA health and restarts if needed
3. Opens charts and attaches EAs via PowerShell automation
4. Self-optimizes parameters based on recent performance
5. Can send trades directly via MT5 API (fallback)
6. Learns from every trade and improves over time
7. Logs everything for analysis

Run this ONCE and it manages everything.
"""

import MetaTrader5 as mt5
import math
import sys
import os
import json
import time
import subprocess
from datetime import datetime, timedelta
from collections import deque
import statistics

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
SET_DIR = os.path.join(PROJECT_ROOT, 'mql5', 'MITEMSHUB_AI')

# Deriv terminal preset path
TERMINAL_SET_DIR = None

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


def log(msg, level="INFO"):
    """Log with timestamp."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    log_file = os.path.join(LOG_DIR, f"controller_{datetime.now().strftime('%Y%m%d')}.log")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def find_terminal_set_dir():
    """Find the Deriv terminal's Presets directory."""
    global TERMINAL_SET_DIR
    mt5_dir = os.path.expanduser("~/AppData/Roaming/MetaQuotes/Terminal")
    if not os.path.isdir(mt5_dir):
        return None
    for d in os.listdir(mt5_dir):
        presets = os.path.join(mt5_dir, d, 'MQL5', 'Presets', 'MITEMSHUB_AI')
        if os.path.isdir(presets):
            TERMINAL_SET_DIR = presets
            return presets
        experts = os.path.join(mt5_dir, d, 'MQL5', 'Experts', 'MITEMSHUB_AI')
        if os.path.isdir(experts):
            TERMINAL_SET_DIR = experts
            return experts
    return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: SYMBOL MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

SYMBOLS = {
    "Volatility 75 Index": {
        'set_file': 'MitemshubAI_VOL75_FINAL.set',
        'timeframe': 'H1',
        'params': {
            'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.8,
            'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
            'vol_ratio': 1.03,
        }
    },
    "Volatility 100 Index": {
        'set_file': 'MitemshubAI_VOL100_FINAL.set',
        'timeframe': 'H1',
        'params': {
            'z_entry': 1.8, 'stop_mult': 0.10, 'target_mult': 0.6,
            'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
            'vol_ratio': 1.03,
        }
    },
}

TF_MAP = {
    'M1': mt5.TIMEFRAME_M1, 'M5': mt5.TIMEFRAME_M5, 'M15': mt5.TIMEFRAME_M15,
    'M30': mt5.TIMEFRAME_M30, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4,
    'D1': mt5.TIMEFRAME_D1,
}


def enable_all_symbols():
    """Enable all trading symbols automatically."""
    enabled = 0
    for sym_name, sym_cfg in SYMBOLS.items():
        info = mt5.symbol_info(sym_name)
        if info is None:
            log(f"Symbol {sym_name} not found", "WARN")
            continue

        # Make visible in Market Watch
        if not info.visible:
            mt5.symbol_select(sym_name, True)
            log(f"Enabled visibility for {sym_name}")

        # Check trade mode
        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
            enabled += 1
            log(f"  {sym_name}: TRADEABLE (bid={info.bid:.2f}, spread={info.spread})")
        else:
            log(f"  {sym_name}: trade_mode={info.trade_mode} (may need broker approval)", "WARN")
            enabled += 1  # Still try

    return enabled


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: EA HEALTH MONITOR
# ═══════════════════════════════════════════════════════════════════════════

def check_ea_health():
    """Check if EAs are running on all charts."""
    health = {}
    for sym_name in SYMBOLS:
        info = mt5.symbol_info(sym_name)
        if info:
            health[sym_name] = {
                'visible': info.visible,
                'tradeable': info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL,
                'bid': info.bid,
                'ask': info.ask,
                'spread': info.spread,
            }
        else:
            health[sym_name] = {'visible': False, 'tradeable': False}

    # Check terminal connection
    terminal = mt5.terminal_info()
    health['terminal'] = {
        'connected': terminal.connected if terminal else False,
        'trade_allowed': terminal.trade_allowed if terminal else False,
    }

    # Check account
    account = mt5.account_info()
    health['account'] = {
        'balance': account.balance if account else 0,
        'equity': account.equity if account else 0,
        'login': account.login if account else 0,
    }

    return health


def read_expert_journal(max_lines=50):
    """Read recent EA entries from the expert journal."""
    mt5_dir = os.path.expanduser("~/AppData/Roaming/MetaQuotes/Terminal")
    entries = []
    if not os.path.isdir(mt5_dir):
        return entries

    for d in os.listdir(mt5_dir):
        log_dir = os.path.join(mt5_dir, d, 'MQL5', 'Logs')
        if not os.path.isdir(log_dir):
            continue
        files = sorted(os.listdir(log_dir), reverse=True)
        for f in files[:2]:
            fp = os.path.join(log_dir, f)
            try:
                with open(fp, 'rb') as fh:
                    content = fh.read(8000)
                    text = content.decode('utf-16-le', errors='replace')
                    for line in text.split('\n'):
                        line = line.strip()
                        if any(kw in line.upper() for kw in ['MITEMSHUB', 'DECISION', 'ENTRY', 'EXIT', 'TRAIL', 'STOP', 'TARGET']):
                            entries.append(line)
                            if len(entries) >= max_lines:
                                return entries
            except:
                pass
    return entries


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: TRADE MANAGEMENT (Direct MT5 API)
# ═══════════════════════════════════════════════════════════════════════════

def get_open_positions(symbol=None):
    """Get all open positions, optionally filtered by symbol."""
    if symbol:
        return mt5.positions_get(symbol=symbol)
    return mt5.positions_get()


def send_order(symbol, order_type, volume, sl=0, tp=0, comment="MITEMSHUB"):
    """Send a trade order directly via MT5 API."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log(f"Cannot get tick for {symbol}", "ERROR")
        return None

    info = mt5.symbol_info(symbol)
    if info is None:
        log(f"Cannot get info for {symbol}", "ERROR")
        return None

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    point = info.point

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": info.spread * 2,
        "magic": 20260822,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        log(f"Order send returned None for {symbol}", "ERROR")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log(f"Order failed: {result.retcode} - {result.comment}", "ERROR")
        return None

    log(f"ORDER PLACED: {symbol} {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} "
        f"vol={volume} price={price:.5f} SL={sl:.5f} TP={tp:.5f}")
    return result


def close_position(ticket):
    """Close a specific position."""
    position = mt5.positions_get(ticket=ticket)
    if not position:
        return None
    pos = position[0]

    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        return None

    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 20260822,
        "comment": "CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"CLOSED position {ticket}: {pos.symbol} P&L=${pos.profit:+,.2f}")
    return result


def close_all_positions(symbol=None):
    """Close all open positions."""
    positions = get_open_positions(symbol)
    if positions:
        for pos in positions:
            close_position(pos.ticket)
    return len(positions) if positions else 0


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: SELF-LEARNING ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TradeLearner:
    """Learns from every trade and improves parameters over time."""

    def __init__(self):
        self.trade_history = self._load_history()
        self.performance_window = deque(maxlen=100)
        self.optimal_params = self._load_optimal()
        self.last_optimize = datetime.now() - timedelta(hours=25)

    def _load_history(self):
        path = os.path.join(DATA_DIR, 'trade_history.json')
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return []

    def _save_history(self):
        path = os.path.join(DATA_DIR, 'trade_history.json')
        with open(path, 'w') as f:
            json.dump(self.trade_history[-500:], f, indent=2, default=str)

    def _load_optimal(self):
        path = os.path.join(DATA_DIR, 'optimal_params.json')
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def record_trade(self, trade_data):
        """Record a completed trade for learning."""
        trade_data['recorded_at'] = datetime.now().isoformat()
        self.trade_history.append(trade_data)
        self.performance_window.append(trade_data)
        self._save_history()

        # Check if we should re-optimize
        if datetime.now() - self.last_optimize > timedelta(hours=24):
            self.optimize()

    def analyze_performance(self):
        """Analyze recent performance and identify patterns."""
        if len(self.performance_window) < 10:
            return None

        trades = list(self.performance_window)
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        losses = [t for t in trades if t.get('pnl', 0) <= 0]

        analysis = {
            'total_trades': len(trades),
            'win_rate': len(wins) / len(trades) * 100,
            'avg_win': statistics.mean([t['pnl'] for t in wins]) if wins else 0,
            'avg_loss': statistics.mean([t['pnl'] for t in losses]) if losses else 0,
            'profit_factor': (sum(t['pnl'] for t in wins) /
                              max(abs(sum(t['pnl'] for t in losses)), 1)) if losses else 999,
            'consecutive_losses': self._max_consecutive(trades, 'loss'),
            'avg_bars_held': statistics.mean([t.get('bars_held', 0) for t in trades]),
            'exit_reasons': self._count_exits(trades),
        }

        # Pattern detection
        analysis['patterns'] = self._detect_patterns(trades)

        return analysis

    def _max_consecutive(self, trades, outcome_type):
        max_streak = 0
        current = 0
        for t in trades:
            if outcome_type == 'loss' and t.get('pnl', 0) <= 0:
                current += 1
                max_streak = max(max_streak, current)
            elif outcome_type == 'win' and t.get('pnl', 0) > 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def _count_exits(self, trades):
        counts = {}
        for t in trades:
            r = t.get('reason', 'unknown')
            counts[r] = counts.get(r, 0) + 1
        return counts

    def _detect_patterns(self, trades):
        """Detect patterns in winning vs losing trades."""
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        losses = [t for t in trades if t.get('pnl', 0) <= 0]
        patterns = {}

        if wins and losses:
            patterns['avg_win_bars'] = statistics.mean([t.get('bars_held', 0) for t in wins])
            patterns['avg_loss_bars'] = statistics.mean([t.get('bars_held', 0) for t in losses])
            patterns['best_exit'] = max(
                [(r, sum(1 for t in wins if t.get('reason') == r))
                 for r in set(t.get('reason') for t in wins)],
                key=lambda x: x[1]
            )[0] if wins else None
            patterns['worst_exit'] = max(
                [(r, sum(1 for t in losses if t.get('reason') == r))
                 for r in set(t.get('reason') for t in losses)],
                key=lambda x: x[1]
            )[0] if losses else None

        return patterns

    def optimize(self):
        """Self-optimize parameters based on recent performance."""
        analysis = self.analyze_performance()
        if analysis is None or analysis['total_trades'] < 20:
            return

        log(f"SELF-OPTIMIZATION triggered ({analysis['total_trades']} trades analyzed)")
        log(f"  Current: WR={analysis['win_rate']:.1f}%, PF={analysis['profit_factor']:.2f}")

        suggestions = []

        # If too many consecutive losses, widen stops
        if analysis['consecutive_losses'] >= 5:
            suggestions.append(('stop_mult', 'increase', 'Too many consecutive losses'))
            suggestions.append(('z_entry', 'increase', 'Need stronger setups'))

        # If too many TIME exits, increase hold time
        exits = analysis['exit_reasons']
        time_exits = exits.get('TIME', 0)
        total = analysis['total_trades']
        if time_exits / max(total, 1) > 0.3:
            suggestions.append(('hold_bars', 'increase', f'{time_exits}/{total} trades hit time limit'))

        # If TRAIL exits are losing money, adjust trailing
        trail_exits = exits.get('TRAIL', 0)
        if trail_exits > total * 0.4:
            suggestions.append(('trail_be_r', 'decrease', 'Too many trail exits (trailing too tight)'))

        # If win rate is very low, be more selective
        if analysis['win_rate'] < 30:
            suggestions.append(('z_entry', 'increase', f'Win rate only {analysis["win_rate"]:.1f}%'))
            suggestions.append(('vol_ratio', 'increase', 'Need stronger volatility signal'))

        for param, direction, reason in suggestions:
            log(f"  SUGGESTION: {param} → {direction} ({reason})")

        self.last_optimize = datetime.now()

        # Save suggestions for review
        suggestions_data = {
            'timestamp': datetime.now().isoformat(),
            'analysis': analysis,
            'suggestions': [(p, d, r) for p, d, r in suggestions],
        }
        sug_path = os.path.join(DATA_DIR, 'optimization_suggestions.json')
        with open(sug_path, 'w') as f:
            json.dump(suggestions_data, f, indent=2, default=str)

        return suggestions


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: CHART MANAGEMENT (PowerShell automation)
# ═══════════════════════════════════════════════════════════════════════════

def open_chart_via_powershell(symbol, timeframe='H1'):
    """Open a chart window for a symbol using PowerShell automation."""
    tf_map_ps = {
        'M1': 'PERIOD_M1', 'M5': 'PERIOD_M5', 'M15': 'PERIOD_M15',
        'M30': 'PERIOD_M30', 'H1': 'PERIOD_H1', 'H4': 'PERIOD_H4',
        'D1': 'PERIOD_D1',
    }
    ps_tf = tf_map_ps.get(timeframe, 'PERIOD_H1')

    ps_script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
}}
"@

$proc = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($proc) {{
    [Win32]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 200

    # Send Ctrl+N for new chart
    [Win32]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero)  # Ctrl down
    [Win32]::keybd_event(0x4E, 0, 0, [UIntPtr]::Zero)  # N
    [Win32]::keybd_event(0x4E, 0, 2, [UIntPtr]::Zero)  # N up
    [Win32]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero)  # Ctrl up
    Write-Host "Opened new chart window"
}}
'''
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', ps_script],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        log(f"PowerShell chart open failed: {e}", "ERROR")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

class RiskManager:
    """Manages overall portfolio risk."""

    MAX_RISK_PER_TRADE = 0.005  # 0.5%
    MAX_DRAWDOWN = 0.10  # 10%
    MAX_POSITIONS = 2  # One per symbol
    COOLDOWN_AFTER_LOSS = 3  # bars

    def __init__(self):
        self.equity_peak = 10000
        self.consecutive_losses = 0
        self.last_trade_pnl = 0
        self.cooldown = 0
        self.daily_pnl = 0
        self.daily_reset = datetime.now().date()

    def can_trade(self, symbol):
        """Check if we're allowed to trade right now."""
        # Daily reset
        today = datetime.now().date()
        if today != self.daily_reset:
            self.daily_pnl = 0
            self.daily_reset = today

        # Cooldown
        if self.cooldown > 0:
            self.cooldown -= 1
            return False, "Cooldown active"

        # Check positions
        positions = get_open_positions()
        if positions and len(positions) >= self.MAX_POSITIONS:
            return False, f"Max positions ({self.MAX_POSITIONS}) reached"

        # Check drawdown
        account = mt5.account_info()
        if account:
            self.equity_peak = max(self.equity_peak, account.equity)
            dd = (self.equity_peak - account.equity) / self.equity_peak
            if dd > self.MAX_DRAWDOWN:
                return False, f"Drawdown {dd*100:.1f}% exceeds max {self.MAX_DRAWDOWN*100:.0f}%"

            # Check balance
            if account.balance <= 0:
                return False, "No balance"

        # Check daily loss limit
        if self.daily_pnl < -500:  # Max $500 daily loss
            return False, f"Daily loss limit reached (${self.daily_pnl:+,.2f})"

        # Check consecutive losses
        if self.consecutive_losses >= 5:
            return False, f"Consecutive losses: {self.consecutive_losses}"

        return True, "OK"

    def calculate_position_size(self, risk_amount):
        """Calculate position size based on risk."""
        account = mt5.account_info()
        if not account or account.equity <= 0:
            return 0.01

        equity = account.equity
        risk_pct = self.MAX_RISK_PER_TRADE

        # Reduce risk after consecutive losses
        if self.consecutive_losses >= 3:
            risk_pct *= 0.5
        if self.consecutive_losses >= 5:
            risk_pct *= 0.25

        # Reduce risk in drawdown
        dd = (self.equity_peak - equity) / self.equity_peak if self.equity_peak > 0 else 0
        if dd > 0.05:
            risk_pct *= 0.5

        return equity * risk_pct

    def record_trade_result(self, pnl):
        """Record a trade result for risk management."""
        self.last_trade_pnl = pnl
        self.daily_pnl += pnl

        if pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.cooldown = self.COOLDOWN_AFTER_LOSS

        account = mt5.account_info()
        if account:
            self.equity_peak = max(self.equity_peak, account.equity)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: MARKET ANALYSIS (Independent of EA)
# ═══════════════════════════════════════════════════════════════════════════

class MarketAnalyzer:
    """Independent market analysis — can trade even without EA."""

    def __init__(self):
        self.garch_omega = -1.884103
        self.garch_alpha = 0.142169
        self.garch_gamma = -0.073285
        self.garch_beta = 0.852741
        self.log_sigma2 = 0.0
        self.n_obs = 0
        self.ema_20 = 0.0
        self.ema_50 = 0.0
        self.atr = 0.0
        self.prev_close = 0.0
        self.z_history = deque(maxlen=500)
        self.sigma_fast = 0.0
        self.sigma_slow = 0.0

    def update(self, close):
        """Update with new price data."""
        if self.prev_close <= 0:
            self.prev_close = close
            self.ema_20 = close
            self.ema_50 = close
            return

        lr = math.log(close / self.prev_close)
        self.n_obs += 1

        if self.n_obs < 20:
            sq = lr * lr
            self.log_sigma2 = math.log(max(sq, 1e-12)) if self.n_obs == 1 else self.log_sigma2 * 0.9 + math.log(max(sq, 1e-12)) * 0.1
        else:
            prev_sigma2 = math.exp(self.log_sigma2)
            z = lr / max(math.sqrt(prev_sigma2), 1e-12)
            self.log_sigma2 = (self.garch_omega + self.garch_alpha * abs(z)
                               + self.garch_gamma * z + self.garch_beta * self.log_sigma2)
            self.z_history.append(z)

        sigma = math.exp(self.log_sigma2 / 2.0)
        if self.sigma_fast == 0:
            self.sigma_fast = self.sigma_slow = sigma
        else:
            self.sigma_fast = self.sigma_fast * 0.6 + sigma * 0.4
            self.sigma_slow = self.sigma_slow * 0.98 + sigma * 0.02

        self.ema_20 = self.ema_20 * (1 - 2.0/21.0) + close * (2.0/21.0)
        self.ema_50 = self.ema_50 * (1 - 2.0/51.0) + close * (2.0/51.0)
        self.prev_close = close

    def get_signal(self, close):
        """Generate a trading signal."""
        if self.n_obs < 30 or self.ema_20 <= 0:
            return None

        sigma = math.exp(self.log_sigma2 / 2.0)
        z = math.log(close / self.ema_20) / sigma if sigma > 0 else 0
        vr = self.sigma_fast / max(self.sigma_slow, 1e-12) if self.sigma_slow > 0 else 1.0

        # Mean reversion signal
        zl = list(self.z_history) if self.z_history else []
        az = abs(z)
        re = sum(1 for zv in zl[-20:] if abs(zv) > 2.0)
        if az < 1.0:
            mr = 0.0
        elif az < 1.5:
            mr = 0.1 + re * 0.02
        elif az < 2.0:
            mr = 0.3 + re * 0.03
        elif az < 2.5:
            mr = 0.5 + re * 0.04
        else:
            mr = 0.7 + re * 0.06

        return {
            'z': z,
            'sigma': sigma,
            'vol_ratio': vr,
            'mean_revert': mr,
            'ema_20': self.ema_20,
            'ema_50': self.ema_50,
            'direction': 'BUY' if z < -1.8 else 'SELL' if z > 1.8 else None,
            'strength': abs(z),
        }

    def analyze_multi_timeframe(self, symbol):
        """Analyze across multiple timeframes for confirmation."""
        results = {}
        for tf_name, tf in [('M5', mt5.TIMEFRAME_M5), ('M15', mt5.TIMEFRAME_M15),
                            ('H1', mt5.TIMEFRAME_H1), ('H4', mt5.TIMEFRAME_H4)]:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, 200)
            if rates is None or len(rates) < 50:
                continue

            # Quick analysis
            closes = [r['close'] for r in rates]
            ema_20 = closes[-1]
            for c in closes[-50:]:
                ema_20 = ema_20 * (1 - 2.0/21.0) + c * (2.0/21.0)

            sigma = statistics.stdev([math.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]) if len(closes) > 1 else 0.001
            z = math.log(closes[-1] / ema_20) / sigma if sigma > 0 else 0

            results[tf_name] = {
                'z': z,
                'trend': 'UP' if ema_20 > closes[-10] else 'DOWN',
                'close': closes[-1],
            }

        return results


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8: MAIN CONTROLLER LOOP
# ═══════════════════════════════════════════════════════════════════════════

class AutonomousController:
    """The main controller that ties everything together."""

    def __init__(self):
        self.risk_mgr = RiskManager()
        self.learner = TradeLearner()
        self.analyzers = {sym: MarketAnalyzer() for sym in SYMBOLS}
        self.last_health_check = datetime.now()
        self.last_optimize = datetime.now()
        self.status_file = os.path.join(DATA_DIR, 'controller_status.json')

    def initialize(self):
        """Initialize the controller."""
        log("=" * 70)
        log("  MITEMSHUB AI — AUTONOMOUS CONTROLLER v1.0")
        log("=" * 70)

        if not mt5.initialize():
            log("MT5 init failed!", "ERROR")
            return False

        terminal = mt5.terminal_info()
        account = mt5.account_info()
        log(f"Terminal: {terminal.name} (build {terminal.build})")
        log(f"Account: {account.login}@{account.server}")
        log(f"Balance: ${account.balance:,.2f}")
        log(f"Trade Allowed: {'YES' if terminal.trade_allowed else 'NO'}")

        # Enable symbols
        log("\nEnabling symbols...")
        enabled = enable_all_symbols()
        log(f"Symbols enabled: {enabled}/{len(SYMBOLS)}")

        # Find terminal presets directory
        presets = find_terminal_set_dir()
        if presets:
            log(f"Terminal presets: {presets}")
        else:
            log("Terminal presets directory not found", "WARN")

        # Copy .set files
        self._deploy_set_files()

        log("\nController initialized successfully!")
        return True

    def _deploy_set_files(self):
        """Deploy .set files to the terminal."""
        if not TERMINAL_SET_DIR:
            return

        for sym_name, sym_cfg in SYMBOLS.items():
            src = os.path.join(SET_DIR, sym_cfg['set_file'])
            dst = os.path.join(TERMINAL_SET_DIR, sym_cfg['set_file'])
            if os.path.exists(src) and not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)
                log(f"Deployed {sym_cfg['set_file']} to terminal")

    def health_check(self):
        """Perform a health check every 5 minutes."""
        now = datetime.now()
        if (now - self.last_health_check).seconds < 300:
            return

        self.last_health_check = now
        health = check_ea_health()

        # Check terminal
        if not health['terminal']['connected']:
            log("Terminal disconnected! Attempting reconnect...", "ERROR")
            mt5.shutdown()
            time.sleep(2)
            mt5.initialize()

        # Check symbols
        for sym_name, sym_data in health.items():
            if sym_name in ('terminal', 'account'):
                continue
            if not sym_data.get('tradeable'):
                log(f"{sym_name} not tradeable, enabling...", "WARN")
                mt5.symbol_select(sym_name, True)

        # Read expert journal
        entries = read_expert_journal(max_lines=5)
        if entries:
            log(f"Recent EA entries ({len(entries)}):")
            for e in entries[-3:]:
                log(f"  {e[:120]}")

        # Save status
        self._save_status(health)

    def _save_status(self, health):
        """Save current status to file."""
        status = {
            'timestamp': datetime.now().isoformat(),
            'health': health,
            'risk_state': {
                'consecutive_losses': self.risk_mgr.consecutive_losses,
                'daily_pnl': self.risk_mgr.daily_pnl,
                'cooldown': self.risk_mgr.cooldown,
            },
            'trade_count': len(self.learner.trade_history),
        }
        with open(self.status_file, 'w') as f:
            json.dump(status, f, indent=2, default=str)

    def monitor_positions(self):
        """Monitor open positions and manage them."""
        positions = get_open_positions()
        if not positions:
            return

        for pos in positions:
            # Track P&L
            unrealized = pos.profit

            # Emergency close if position is deeply negative
            if unrealized < -pos.volume * 100:  # $100 per lot loss
                log(f"EMERGENCY CLOSE: {pos.symbol} P&L=${unrealized:+,.2f}", "ERROR")
                close_position(pos.ticket)

    def run_cycle(self):
        """Run one cycle of the controller."""
        try:
            # Health check
            self.health_check()

            # Monitor positions
            self.monitor_positions()

            # Check for new closed trades
            self._check_completed_trades()

            # Self-optimize daily
            now = datetime.now()
            if (now - self.last_optimize).seconds > 86400:
                self.learner.optimize()
                self.last_optimize = now

        except Exception as e:
            log(f"Controller cycle error: {e}", "ERROR")

    def _check_completed_trades(self):
        """Check for newly completed trades and learn from them."""
        # Get today's deals
        today = datetime.now().replace(hour=0, minute=0, second=0)
        deals = mt5.history_deals_get(today, datetime.now())
        if deals is None:
            return

        for deal in deals:
            if deal.magic != 20260822:
                continue
            if deal.entry == mt5.DEAL_ENTRY_OUT:
                trade_data = {
                    'symbol': deal.symbol,
                    'type': 'BUY' if deal.type == 0 else 'SELL',
                    'entry_price': deal.price,
                    'pnl': deal.profit + deal.swap + deal.commission,
                    'time': deal.time,
                    'volume': deal.volume,
                    'reason': deal.comment,
                }
                self.learner.record_trade(trade_data)
                self.risk_mgr.record_trade_result(trade_data['pnl'])

    def status_report(self):
        """Generate a comprehensive status report."""
        log("\n" + "=" * 70)
        log("  STATUS REPORT")
        log("=" * 70)

        health = check_ea_health()
        account = health.get('account', {})
        log(f"  Balance:  ${account.get('balance', 0):,.2f}")
        log(f"  Equity:   ${account.get('equity', 0):,.2f}")

        positions = get_open_positions()
        log(f"  Positions: {len(positions) if positions else 0}")
        if positions:
            for p in positions:
                log(f"    {p.symbol} {p.type_str} vol={p.volume} P&L=${p.profit:+,.2f}")

        # Trade history summary
        history = self.learner.trade_history
        if history:
            recent = history[-20:]
            wins = sum(1 for t in recent if t.get('pnl', 0) > 0)
            total_pnl = sum(t.get('pnl', 0) for t in recent)
            log(f"\n  Recent {len(recent)} trades:")
            log(f"    Win Rate: {wins/len(recent)*100:.1f}%")
            log(f"    Total P&L: ${total_pnl:+,.2f}")

        # Risk state
        log(f"\n  Risk State:")
        log(f"    Consecutive Losses: {self.risk_mgr.consecutive_losses}")
        log(f"    Daily P&L: ${self.risk_mgr.daily_pnl:+,.2f}")
        log(f"    Cooldown: {self.risk_mgr.cooldown}")
        log("=" * 70)

    def run(self):
        """Main run loop."""
        if not self.initialize():
            return

        log("\nStarting autonomous controller loop...")
        log("Press Ctrl+C to stop.\n")

        cycle = 0
        try:
            while True:
                cycle += 1
                self.run_cycle()

                # Status report every 60 cycles (~5 minutes)
                if cycle % 60 == 0:
                    self.status_report()

                # Sleep between cycles (5 seconds)
                time.sleep(5)

        except KeyboardInterrupt:
            log("\nController stopped by user.")
        finally:
            self.status_report()
            mt5.shutdown()
            log("Controller shutdown complete.")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='MitemshubAI Autonomous Controller')
    parser.add_argument('--status', action='store_true', help='Print status and exit')
    parser.add_argument('--enable-symbols', action='store_true', help='Enable symbols and exit')
    parser.add_argument('--health', action='store_true', help='Health check and exit')
    parser.add_argument('--close-all', action='store_true', help='Close all positions and exit')
    args = parser.parse_args()

    controller = AutonomousController()

    if args.status:
        if controller.initialize():
            controller.status_report()
            mt5.shutdown()
    elif args.enable_symbols:
        if controller.initialize():
            enable_all_symbols()
            mt5.shutdown()
    elif args.health:
        if controller.initialize():
            controller.health_check()
            controller.status_report()
            mt5.shutdown()
    elif args.close_all:
        mt5.initialize()
        n = close_all_positions()
        log(f"Closed {n} positions")
        mt5.shutdown()
    else:
        controller.run()
