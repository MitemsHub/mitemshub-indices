#!/usr/bin/env python
"""
MITEMSHUB AI — Trade Analyzer & Self-Improvement Engine
Extracts all trades from Strategy Tester, analyzes patterns,
identifies weaknesses, and auto-optimizes parameters.
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
from datetime import datetime, timedelta
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DATA_DIR, exist_ok=True)


def extract_trades():
    """Pull all Strategy Tester deals from MT5."""
    mt5.initialize()
    start = datetime(2026, 1, 1)
    end = datetime(2026, 8, 21)
    deals = mt5.history_deals_get(start, end)
    mt5.shutdown()

    if deals is None or len(deals) == 0:
        return []

    entries_map = {}  # position_id -> entry deal
    exits = []
    for d in deals:
        if d.entry == mt5.DEAL_ENTRY_IN:
            entries_map[d.position_id] = d
        elif d.entry == mt5.DEAL_ENTRY_OUT:
            exits.append(d)

    trades = []
    for e in exits:
        ent = entries_map.get(e.position_id)
        if ent is None:
            continue

        open_time = datetime.fromtimestamp(ent.time)
        close_time = datetime.fromtimestamp(e.time)
        entry_price = ent.price
        exit_price = e.price
        profit = e.profit
        volume = ent.volume
        comment = e.comment if e.comment else ""
        duration_min = (close_time - open_time).total_seconds() / 60

        # Determine original side: closing BUY = deal type SELL
        if e.type == mt5.DEAL_TYPE_BUY:
            side = "SELL"  # closing a short
        else:
            side = "BUY"  # closing a long

        trades.append({
            'num': len(trades) + 1,
            'side': side,
            'open_time': open_time,
            'close_time': close_time,
            'entry': entry_price,
            'exit': exit_price,
            'profit': profit,
            'volume': volume,
            'comment': comment,
            'duration_min': duration_min,
            'sl': ent.sl,
            'tp': ent.tp,
        })

    return trades


def analyze_trades(trades):
    """Deep analysis of all trades."""
    if not trades:
        print("No trades to analyze")
        return

    wins = [t for t in trades if t['profit'] > 0]
    losses = [t for t in trades if t['profit'] <= 0]
    breakevens = [t for t in trades if abs(t['profit']) < 1.0]

    print("=" * 100)
    print("  COMPLETE TRADE LOG FROM STRATEGY TESTER (EA)")
    print("=" * 100)
    print(f"  {'#':>3} | {'OPEN_TIME':16} | {'SIDE':4} | {'ENTRY':>10} | {'EXIT':>10} | {'PROFIT':>10} | {'DURATION':>8} | COMMENT")
    print("  " + "-" * 98)

    for t in trades:
        color = "\033[92m" if t['profit'] > 0 else "\033[91m" if t['profit'] < 0 else "\033[93m"
        reset = "\033[0m"
        print(f"  {color}{t['num']:3d} | {t['open_time'].strftime('%m-%d %H:%M'):16} | {t['side']:4s} | {t['entry']:10.2f} | {t['exit']:10.2f} | {t['profit']:+10.2f} | {t['duration_min']:6.0f}min | {t['comment']}{reset}")

    print()
    print("=" * 100)
    print("  TRADE ANALYSIS")
    print("=" * 100)

    total_profit = sum(t['profit'] for t in trades)
    total_wins = sum(t['profit'] for t in wins)
    total_losses = sum(t['profit'] for t in losses)
    avg_win = total_wins / len(wins) if wins else 0
    avg_loss = total_losses / len(losses) if losses else 0
    win_rate = len(wins) / len(trades) * 100
    profit_factor = total_wins / abs(total_losses) if total_losses else 999

    print(f"  Total Trades:    {len(trades)}")
    print(f"  Wins:            {len(wins)} ({win_rate:.1f}%)")
    print(f"  Losses:          {len(losses)}")
    print(f"  Breakevens:      {len(breakevens)}")
    print(f"  Total Profit:    ${total_profit:+,.2f}")
    print(f"  Avg Win:         ${avg_win:+,.2f}")
    print(f"  Avg Loss:        ${avg_loss:+,.2f}")
    print(f"  Profit Factor:   {profit_factor:.2f}")
    print(f"  Payoff Ratio:    {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "  Payoff Ratio:    N/A")

    # Duration analysis
    avg_dur = sum(t['duration_min'] for t in trades) / len(trades)
    win_dur = sum(t['duration_min'] for t in wins) / len(wins) if wins else 0
    loss_dur = sum(t['duration_min'] for t in losses) / len(losses) if losses else 0
    print(f"  Avg Duration:    {avg_dur:.0f} min")
    print(f"  Win Duration:    {win_dur:.0f} min")
    print(f"  Loss Duration:   {loss_dur:.0f} min")

    # Time analysis
    hourly = {}
    for t in trades:
        h = t['open_time'].hour
        if h not in hourly:
            hourly[h] = {'wins': 0, 'losses': 0, 'profit': 0}
        if t['profit'] > 0:
            hourly[h]['wins'] += 1
        else:
            hourly[h]['losses'] += 1
        hourly[h]['profit'] += t['profit']

    print()
    print("  PERFORMANCE BY HOUR (UTC):")
    print(f"  {'HOUR':>4} | {'TRADES':>7} | {'WINS':>5} | {'WIN%':>6} | {'PROFIT':>10}")
    print("  " + "-" * 45)
    for h in sorted(hourly.keys()):
        d = hourly[h]
        total = d['wins'] + d['losses']
        wr = d['wins'] / total * 100 if total else 0
        color = "\033[92m" if d['profit'] > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"  {color}{h:4d} | {total:7d} | {d['wins']:5d} | {wr:5.1f}% | {d['profit']:+10.2f}{reset}")

    # Day analysis
    daily = {}
    for t in trades:
        d = t['open_time'].strftime('%Y-%m-%d')
        if d not in daily:
            daily[d] = {'trades': 0, 'wins': 0, 'profit': 0}
        daily[d]['trades'] += 1
        if t['profit'] > 0:
            daily[d]['wins'] += 1
        daily[d]['profit'] += t['profit']

    # Streak analysis
    max_consec_loss = 0
    current_streak = 0
    max_consec_win = 0
    current_win_streak = 0
    for t in trades:
        if t['profit'] <= 0:
            current_streak += 1
            current_win_streak = 0
            max_consec_loss = max(max_consec_loss, current_streak)
        else:
            current_win_streak += 1
            current_streak = 0
            max_consec_win = max(max_consec_win, current_win_streak)

    print()
    print(f"  Max Consecutive Losses: {max_consec_loss}")
    print(f"  Max Consecutive Wins:   {max_consec_win}")

    # Drawdown
    equity = 10000.0
    peak = 10000.0
    max_dd = 0.0
    for t in trades:
        equity += t['profit']
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    print(f"  Max Drawdown:     {max_dd * 100:.2f}%")
    print(f"  Final Equity:     ${equity:,.2f}")
    print(f"  Net Return:       ${(equity - 10000):+,.2f} ({(equity - 10000)/100:.1f}%)")
    print("=" * 100)

    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_profit': total_profit,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'max_dd': max_dd,
        'max_consec_loss': max_consec_loss,
        'equity': equity,
    }


if __name__ == "__main__":
    trades = extract_trades()
    result = analyze_trades(trades)

    # Save results
    if trades:
        save_data = []
        for t in trades:
            save_data.append({
                'num': t['num'],
                'side': t['side'],
                'open_time': t['open_time'].isoformat(),
                'close_time': t['close_time'].isoformat(),
                'entry': t['entry'],
                'exit': t['exit'],
                'profit': t['profit'],
                'duration_min': t['duration_min'],
                'comment': t['comment'],
            })
        with open(os.path.join(DATA_DIR, 'ea_trades.json'), 'w') as f:
            json.dump(save_data, f, indent=2)
        print(f"\n  Trades saved to data/ea_trades.json")
