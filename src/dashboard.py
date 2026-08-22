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

    # Trade history (from MT5 + EA log)
    _fetch_trade_history()
    _parse_ea_log_trades()

    # Metrics
    _compute_metrics()


def _read_journal():
    """Read recent EA journal entries — only latest session."""
    mt5_dir = os.path.expanduser("~/AppData/Roaming/MetaQuotes/Terminal")
    entries = []
    if not os.path.isdir(mt5_dir):
        return entries
    for d in os.listdir(mt5_dir):
        log_dir = os.path.join(mt5_dir, d, 'MQL5', 'Logs')
        if not os.path.isdir(log_dir):
            continue
        files = sorted(os.listdir(log_dir), reverse=True)
        for f in files[:1]:  # only latest log file
            fp = os.path.join(log_dir, f)
            try:
                with open(fp, 'rb') as fh:
                    content = fh.read(50000)
                    text = content.decode('utf-16-le', errors='replace')
                    for line in text.split('\n'):
                        line = line.strip()
                        if '[MITEM]' in line or 'ORDER FAIL' in line:
                            # Skip old session entries
                            if '$10000' in line:
                                continue
                            # Extract just the [MITEM] part for cleaner display
                            if '[MITEM]' in line:
                                idx = line.index('[MITEM]')
                                clean = line[idx:idx+120]
                            else:
                                clean = line[:120]
                            entries.append({'text': clean, 'time': ''})
                            if len(entries) >= 30:
                                return entries
            except:
                pass
    return entries


def _fetch_trade_history():
    """Fetch recent trade history from MT5 deals — pair IN/OUT into completed trades."""
    now = datetime.now()
    from_date = now - timedelta(days=7)
    deals = mt5.history_deals_get(from_date, now)
    completed = []
    if deals:
        # Filter MITEM deals only
        mitem_deals = [d for d in deals if d.magic == 7788123 or d.comment.startswith('MITEM')]
        # Group by symbol and pair IN/OUT
        pending_in = {}  # symbol -> IN deal
        for deal in mitem_deals:
            sym = deal.symbol
            if deal.entry == mt5.DEAL_ENTRY_IN:
                pending_in[sym] = deal
            elif deal.entry == mt5.DEAL_ENTRY_OUT and sym in pending_in:
                in_deal = pending_in.pop(sym)
                direction = 'BUY' if in_deal.type == mt5.ORDER_TYPE_BUY else 'SELL'
                entry_price = in_deal.price
                exit_price = deal.price
                pnl = deal.profit + deal.swap + deal.commission
                # Parse SL/TP from comment
                sl = 0
                tp = 0
                comment = deal.comment or ''
                if '[sl ' in comment:
                    try:
                        sl = float(comment.split('[sl ')[1].split(']')[0])
                    except:
                        pass
                if '[tp ' in comment:
                    try:
                        tp = float(comment.split('[tp ')[1].split(']')[0])
                    except:
                        pass
                status = 'STOP' if '[sl ' in comment else 'TARGET' if '[tp ' in comment else 'TIME'
                completed.append({
                    'time': datetime.fromtimestamp(in_deal.time).strftime('%Y-%m-%d %H:%M'),
                    'exit_time': datetime.fromtimestamp(deal.time).strftime('%H:%M'),
                    'symbol': sym,
                    'direction': direction,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'sl': sl,
                    'tp': tp,
                    'status': status,
                    'pnl': round(pnl, 2),
                    'volume': in_deal.volume,
                    'comment': 'MITEM',
                    'source': 'MT5',
                })
    with lock:
        cache['trades'] = completed[-200:]


def _parse_ea_log_trades():
    """Parse MITEM trades from EA logs, merge with MT5 deals for accurate P&L.
    EA_LOG is PRIMARY source (has z-score, SL, TP, R-multiple).
    MT5 deals provide accurate broker P&L when available."""
    mt5_dir = os.path.expanduser("~/AppData/Roaming/MetaQuotes/Terminal")
    if not os.path.isdir(mt5_dir):
        return

    log_trades = []
    for d in os.listdir(mt5_dir):
        log_path = os.path.join(mt5_dir, d, 'MQL5', 'logs')
        if not os.path.isdir(log_path):
            continue
        for fname in sorted(os.listdir(log_path), reverse=True)[:2]:
            if not fname.endswith('.log'):
                continue
            fp = os.path.join(log_path, fname)
            try:
                with open(fp, 'rb') as fh:
                    text = fh.read(200000).decode('utf-16-le', errors='replace')
                    for line in text.split('\n'):
                        if '[MITEM]' not in line:
                            continue
                        if '$10000' in line:
                            continue
                        # Parse SELL/BUY entries
                        if any(kw in line for kw in ['SELL @', 'BUY @']):
                            try:
                                parts = line.split('\t')
                                time_str = parts[2].strip() if len(parts) > 2 else ''
                                msg = line.split('[MITEM]')[1].strip()
                                direction = 'BUY' if 'BUY @' in msg else 'SELL'
                                entry_price = float(msg.split('@')[1].split()[0])
                                sl = float(msg.split('SL=')[1].split()[0]) if 'SL=' in msg else 0
                                tp = float(msg.split('TP=')[1].split()[0]) if 'TP=' in msg else 0
                                rr = float(msg.split('RR=')[1].split()[0]) if 'RR=' in msg else 0
                                z = float(msg.split('z=')[1].split()[0]) if 'z=' in msg else 0
                                risk = float(msg.split('$')[1].split()[0]) if '$' in msg else 0
                                log_trades.append({
                                    'time': time_str,
                                    'symbol': 'Volatility 100 Index' if '100' in line else 'Volatility 75 Index',
                                    'direction': direction,
                                    'entry_price': entry_price,
                                    'sl': sl,
                                    'tp': tp,
                                    'rr': rr,
                                    'z_score': z,
                                    'risk': risk,
                                    'status': 'OPEN',
                                    'source': 'EA_LOG',
                                })
                            except Exception:
                                pass

                        # Parse STOP/TARGET/TIME/ZDECAY exit entries
                        elif any(kw in line for kw in ['STOP @', 'TARGET @', 'TIME @', 'ZDECAY @']):
                            try:
                                parts = line.split('\t')
                                time_str = parts[2].strip() if len(parts) > 2 else ''
                                msg = line.split('[MITEM]')[1].strip()
                                exit_price = float(msg.split('@')[1].split()[0])
                                r_mult = float(msg.split('R=')[1].split()[0]) if 'R=' in msg else 0
                                pnl = float(msg.split('$')[1].split()[0]) if '$' in msg else 0
                                reason = 'STOP' if 'STOP @' in msg else 'TARGET' if 'TARGET @' in msg else 'ZDECAY' if 'ZDECAY @' in msg else 'TIME'
                                for ot in reversed(log_trades):
                                    if ot['status'] == 'OPEN':
                                        ot['status'] = reason
                                        ot['exit_price'] = exit_price
                                        ot['exit_time'] = time_str
                                        ot['r_multiple'] = r_mult
                                        ot['pnl'] = pnl
                                        break
                            except Exception:
                                pass
            except Exception:
                pass

    # Build final trade list: EA_LOG is primary, MT5 fills gaps
    with lock:
        mt5_trades = cache.get('trades', [])  # from _fetch_trade_history

        # Completed EA_LOG trades
        completed_ea = [lt for lt in log_trades if lt['status'] != 'OPEN']

        # Match each EA_LOG trade to closest MT5 trade by (symbol, direction, time within 2min)
        used_mt5 = set()
        merged = []
        for ea_t in completed_ea:
            t = dict(ea_t)
            # Parse EA_LOG time HH:MM:SS
            ea_hhmm = ea_t.get('time', '')[:5]  # '16:40'
            best_mt = None
            best_dist = 999
            for i, mt in enumerate(mt5_trades):
                if i in used_mt5:
                    continue
                if mt['symbol'] != ea_t['symbol']:
                    continue
                if mt['direction'] != ea_t['direction']:
                    continue
                # Parse MT5 time HH:MM
                mt_hhmm = mt['time'][-5:]  # '16:40' from '2026-08-22 16:40'
                if ea_hhmm == mt_hhmm:
                    best_mt = mt
                    best_dist = 0
                    break
                # Approximate distance
                try:
                    eh, em = map(int, ea_hhmm.split(':'))
                    mh, mm = map(int, mt_hhmm.split(':'))
                    dist = abs((eh * 60 + em) - (mh * 60 + mm))
                    if dist < best_dist and dist <= 2:
                        best_dist = dist
                        best_mt = mt
                except:
                    pass
            if best_mt:
                t['pnl'] = best_mt.get('pnl', ea_t.get('pnl', 0))
                t['exit_price'] = best_mt.get('exit_price', ea_t.get('exit_price', 0))
                t['status'] = best_mt.get('status', ea_t.get('status', ''))
                if not t.get('sl') and best_mt.get('sl'):
                    t['sl'] = best_mt['sl']
                if not t.get('tp') and best_mt.get('tp'):
                    t['tp'] = best_mt['tp']
                used_mt5.add(i)
            merged.append(t)

        # Add any unmatched MT5 trades as fallback
        for i, mt in enumerate(mt5_trades):
            if i not in used_mt5:
                merged.append(mt)

        # Sort by time descending
        merged.sort(key=lambda x: x.get('time', ''), reverse=True)
        cache['trades'] = merged[-200:]


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
            cache['equity_curve'] = [{'equity': 30.04, 'trade': 0}]
        return

    # All trades now have 'pnl' field (completed trades only)
    completed = [t for t in trades if t.get('pnl', 0) != 0]
    if not completed:
        with lock:
            cache['metrics'] = {
                'total_trades': 0, 'win_rate': 0, 'profit_factor': 0,
                'total_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                'max_drawdown': 0, 'sharpe': 0, 'expectancy': 0,
            }
            cache['equity_curve'] = [{'equity': 30.04, 'trade': 0}]
        return

    wins = [t for t in completed if t.get('pnl', 0) > 0]
    losses = [t for t in completed if t.get('pnl', 0) <= 0]

    total_pnl = sum(t.get('pnl', 0) for t in completed)
    gp = sum(t.get('pnl', 0) for t in wins) if wins else 0
    gl = abs(sum(t.get('pnl', 0) for t in losses)) if losses else 0
    pf = gp / gl if gl > 0 else 999
    wr = len(wins) / len(completed) * 100 if completed else 0

    # Drawdown — start from actual account balance
    acct = cache.get('account', {})
    starting_eq = acct.get('balance', 30.04)
    eq = starting_eq
    pk = starting_eq
    mdd = 0
    eq_curve = [{'equity': round(starting_eq, 2), 'trade': 0}]
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
