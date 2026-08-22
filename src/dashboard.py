#!/usr/bin/env python
"""
MITEMSHUB AI — MONITORING DASHBOARD
====================================
Real-time web dashboard showing:
- Account status (balance, equity, margin)
- Open positions with live P&L
- Trade history with entry/exit visualization
- Performance metrics (win rate, profit factor, Sharpe, drawdown)
- Equity curve chart
- Market data (live bid/ask for Vol 75 & Vol 100)
- EA health status
- Risk management state

Run: python dashboard.py
Open: http://localhost:5000
"""

import MetaTrader5 as mt5
import math
import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta
from collections import deque
import statistics

from flask import Flask, render_template, jsonify

sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')


# ═══════════════════════════════════════════════════════════════════════════
# DATA CACHE (refreshed every 2 seconds in background)
# ═══════════════════════════════════════════════════════════════════════════

cache = {
    'account': {},
    'positions': [],
    'market': {},
    'health': {},
    'trades': [],
    'equity_curve': [],
    'metrics': {},
    'last_update': None,
}

lock = threading.Lock()


def refresh_data():
    """Background thread that refreshes MT5 data every 2 seconds."""
    while True:
        try:
            _fetch_all_data()
        except Exception as e:
            print(f"Refresh error: {e}")
        time.sleep(2)


def _fetch_all_data():
    """Fetch all data from MT5."""
    if not mt5.terminal_info():
        mt5.initialize()

    # Account
    account = mt5.account_info()
    if account:
        with lock:
            cache['account'] = {
                'login': account.login,
                'server': account.server,
                'name': account.name,
                'balance': account.balance,
                'equity': account.equity,
                'margin': account.margin,
                'free_margin': account.margin_free,
                'margin_level': account.margin_level,
                'profit': account.profit,
                'leverage': account.leverage,
                'currency': account.currency,
            }

    # Positions
    positions = mt5.positions_get()
    pos_list = []
    if positions:
        for p in positions:
            tick = mt5.symbol_info_tick(p.symbol)
            current_price = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
            pos_list.append({
                'ticket': p.ticket,
                'symbol': p.symbol,
                'type': 'BUY' if p.type == mt5.ORDER_TYPE_BUY else 'SELL',
                'volume': p.volume,
                'price_open': p.price_open,
                'price_current': current_price,
                'sl': p.sl,
                'tp': p.tp,
                'profit': p.profit,
                'swap': p.swap,
                'commission': p.commission,
                'time': datetime.fromtimestamp(p.time).strftime('%Y-%m-%d %H:%M'),
                'magic': p.magic,
                'comment': p.comment,
            })
    with lock:
        cache['positions'] = pos_list

    # Market data for both symbols
    market = {}
    for sym in ['Volatility 75 Index', 'Volatility 100 Index']:
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if info and tick:
            # Get recent rates for mini chart
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 100)
            sparkline = []
            if rates is not None:
                sparkline = [{'time': int(r['time']), 'close': r['close']} for r in rates]

            market[sym] = {
                'bid': tick.bid,
                'ask': tick.ask,
                'spread': info.spread,
                'point': info.point,
                'digits': info.digits,
                'trade_mode': info.trade_mode,
                'volume': info.volume_real if hasattr(info, 'volume_real') else 0,
                'sparkline': sparkline,
            }
    with lock:
        cache['market'] = market

    # Expert journal entries
    entries = _read_journal()
    with lock:
        cache['health'] = {
            'terminal_connected': mt5.terminal_info().connected if mt5.terminal_info() else False,
            'trade_allowed': mt5.terminal_info().trade_allowed if mt5.terminal_info() else False,
            'expert_entries': entries[-20:],
            'last_update': datetime.now().strftime('%H:%M:%S'),
        }

    # Trade history (today)
    _fetch_trade_history()

    # Metrics
    _compute_metrics()


def _read_journal():
    """Read recent EA journal entries."""
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
                    content = fh.read(16000)
                    text = content.decode('utf-16-le', errors='replace')
                    for line in text.split('\n'):
                        line = line.strip()
                        if any(kw in line.upper() for kw in ['MITEMSHUB', 'DECISION', 'ENTRY', 'EXIT', 'TRAIL', 'STOP', 'TARGET']):
                            entries.append({'text': line[:150], 'time': line[:19] if len(line) > 19 else ''})
                            if len(entries) >= 50:
                                return entries
            except:
                pass
    return entries


def _fetch_trade_history():
    """Fetch recent trade history."""
    # Last 7 days
    now = datetime.now()
    from_date = now - timedelta(days=7)
    deals = mt5.history_deals_get(from_date, now)
    trades = []
    if deals:
        for deal in deals:
            if deal.magic == 20260822 or deal.comment == 'MITEMSHUB':
                trades.append({
                    'ticket': deal.ticket,
                    'order': deal.order,
                    'time': datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M'),
                    'symbol': deal.symbol,
                    'type': 'BUY' if deal.type == mt5.ORDER_TYPE_BUY else 'SELL',
                    'entry': 'IN' if deal.entry == mt5.DEAL_ENTRY_IN else 'OUT',
                    'volume': deal.volume,
                    'price': deal.price,
                    'profit': deal.profit,
                    'swap': deal.swap,
                    'commission': deal.commission,
                    'comment': deal.comment,
                })
    # Also load from file
    history_file = os.path.join(DATA_DIR, 'trade_history.json')
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                file_trades = json.load(f)
                # Merge with MT5 deals
                existing_tickets = {t['ticket'] for t in trades}
                for ft in file_trades:
                    if ft.get('ticket') not in existing_tickets:
                        trades.append(ft)
        except:
            pass

    with lock:
        cache['trades'] = trades[-100:]  # Keep last 100


def _compute_metrics():
    """Compute performance metrics from trade history."""
    trades = cache.get('trades', [])
    if not trades:
        with lock:
            cache['metrics'] = {
                'total_trades': 0, 'win_rate': 0, 'profit_factor': 0,
                'total_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                'max_drawdown': 0, 'sharpe': 0, 'expectancy': 0,
            }
        return

    # Filter to completed trades (have pnl)
    completed = [t for t in trades if 'pnl' in t and t.get('entry') in ('OUT', None)]
    if not completed:
        completed = [t for t in trades if 'pnl' in t]

    wins = [t for t in completed if t.get('pnl', 0) > 0]
    losses = [t for t in completed if t.get('pnl', 0) <= 0]

    total_pnl = sum(t.get('pnl', 0) for t in completed)
    gp = sum(t.get('pnl', 0) for t in wins) if wins else 0
    gl = abs(sum(t.get('pnl', 0) for t in losses)) if losses else 0
    pf = gp / gl if gl > 0 else 999
    wr = len(wins) / len(completed) * 100 if completed else 0

    # Drawdown
    eq = 10000
    pk = 10000
    mdd = 0
    eq_curve = [{'equity': 10000, 'trade': 0}]
    for i, t in enumerate(completed):
        eq += t.get('pnl', 0)
        pk = max(pk, eq)
        dd = (pk - eq) / pk if pk > 0 else 0
        mdd = max(mdd, dd)
        eq_curve.append({'equity': eq, 'trade': i + 1})

    # Sharpe
    returns = [t.get('pnl', 0) for t in completed]
    sharpe = 0
    if len(returns) > 1 and statistics.stdev(returns) > 0:
        sharpe = statistics.mean(returns) / statistics.stdev(returns) * math.sqrt(252)

    # Consecutive losses
    mc = 0
    s = 0
    for t in completed:
        if t.get('pnl', 0) <= 0:
            s += 1
            mc = max(mc, s)
        else:
            s = 0

    # Expectancy
    avg_win = gp / len(wins) if wins else 0
    avg_loss = -gl / len(losses) if losses else 0
    expectancy = (wr / 100 * avg_win) - ((100 - wr) / 100 * avg_loss)

    with lock:
        cache['metrics'] = {
            'total_trades': len(completed),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(wr, 1),
            'profit_factor': round(pf, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'max_drawdown': round(mdd * 100, 2),
            'sharpe': round(sharpe, 2),
            'expectancy': round(expectancy, 2),
            'max_consecutive_losses': mc,
            'final_equity': round(eq, 2),
        }
        cache['equity_curve'] = eq_curve


# ═══════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    with lock:
        return jsonify({
            'account': cache.get('account', {}),
            'positions': cache.get('positions', []),
            'market': cache.get('market', {}),
            'health': cache.get('health', {}),
            'metrics': cache.get('metrics', {}),
            'last_update': cache.get('last_update'),
        })


@app.route('/api/trades')
def api_trades():
    with lock:
        return jsonify(cache.get('trades', []))


@app.route('/api/equity_curve')
def api_equity_curve():
    with lock:
        return jsonify(cache.get('equity_curve', []))


@app.route('/api/market')
def api_market():
    with lock:
        return jsonify(cache.get('market', {}))


@app.route('/api/positions')
def api_positions():
    with lock:
        return jsonify(cache.get('positions', []))


@app.route('/api/journal')
def api_journal():
    with lock:
        return jsonify(cache.get('health', {}).get('expert_entries', []))


@app.route('/api/replay/summary')
def api_replay_summary():
    """Return just the summary + signals (lightweight)."""
    replay_file = os.path.join(DATA_DIR, 'backtest_replay.json')
    if not os.path.exists(replay_file):
        return jsonify({'error': 'No replay data. Run backtest_replay.py first.'})
    try:
        with open(replay_file, 'r') as f:
            data = json.load(f)
        return jsonify({
            'summary': data.get('summary', {}),
            'signals': data.get('signals', []),
            'trades': data.get('trades', []),
            'symbol': data.get('symbol', ''),
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/replay/prices')
def api_replay_prices():
    """Return price data in chunks for the replay chart."""
    replay_file = os.path.join(DATA_DIR, 'backtest_replay.json')
    if not os.path.exists(replay_file):
        return jsonify({'error': 'No replay data'})
    try:
        start = int(request.args.get('start', 0))
        end = int(request.args.get('end', 500))
        with open(replay_file, 'r') as f:
            data = json.load(f)
        prices = data.get('price_data', [])[start:end]
        return jsonify({
            'prices': prices,
            'total': len(data.get('price_data', [])),
            'start': start,
            'end': end,
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/replay/trade/<int:trade_id>')
def api_replay_trade(trade_id):
    """Return a specific trade with surrounding context."""
    replay_file = os.path.join(DATA_DIR, 'backtest_replay.json')
    if not os.path.exists(replay_file):
        return jsonify({'error': 'No replay data'})
    try:
        with open(replay_file, 'r') as f:
            data = json.load(f)
        trades = data.get('trades', [])
        if trade_id < 1 or trade_id > len(trades):
            return jsonify({'error': 'Trade not found'})
        trade = trades[trade_id - 1]
        # Get price context (200 bars around the trade)
        prices = data.get('price_data', [])
        entry_bar = trade.get('bar', 0)
        ctx_start = max(0, entry_bar - 100)
        ctx_end = min(len(prices), entry_bar + 200)
        context_prices = prices[ctx_start:ctx_end]
        return jsonify({
            'trade': trade,
            'context_prices': context_prices,
            'ctx_start': ctx_start,
        })
    except Exception as e:
        return jsonify({'error': str(e)})


from flask import request


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════

def start_background_refresh():
    t = threading.Thread(target=refresh_data, daemon=True)
    t.start()


if __name__ == '__main__':
    if not mt5.initialize():
        print("MT5 init failed!")
        sys.exit(1)

    print("=" * 60)
    print("  MITEMSHUB AI — MONITORING DASHBOARD")
    print("  http://localhost:5000")
    print("=" * 60)

    start_background_refresh()
    time.sleep(1)  # Let first data load

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
