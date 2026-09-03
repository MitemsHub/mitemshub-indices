"""Check today's deals + open positions on the logged-in MT5 account.

Any deal with magic != 0 was placed by an EA; with local algo-trading disabled
(VPS sync), an EA-magic trade can only have executed on the virtual hosting.

Usage: python scripts/check_today_trades.py
"""
from __future__ import annotations

import datetime as dt

import MetaTrader5 as mt5

if not mt5.initialize():
    raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")

try:
    acct = mt5.account_info()
    if acct is None:
        raise SystemExit(f"account_info failed: {mt5.last_error()}")
    print(f"account: {acct.login} | server: {acct.server} | equity: {acct.equity:.2f} "
          f"| balance: {acct.balance:.2f}")

    now = dt.datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    positions = mt5.positions_get()
    print(f"\n=== OPEN POSITIONS: {0 if positions is None else len(positions)} ===")
    for p in positions or []:
        print(f"  ticket={p.ticket} {p.symbol} {'BUY' if p.type == 0 else 'SELL'} "
              f"vol={p.volume} open={p.price_open} cur={p.price_current} "
              f"sl={p.sl} tp={p.tp} profit={p.profit:.2f} magic={p.magic} "
              f"comment='{p.comment}' time={dt.datetime.fromtimestamp(p.time)}")

    deals = mt5.history_deals_get(start, now + dt.timedelta(minutes=5))
    print(f"\n=== TODAY'S DEALS: {0 if deals is None else len(deals)} ===")
    for d in deals or []:
        side = "BUY" if d.type == mt5.DEAL_TYPE_BUY else (
            "SELL" if d.type == mt5.DEAL_TYPE_SELL else d.type)
        entry = {0: "in", 1: "out", 2: "in/out", 3: "out-ish"}.get(d.entry, d.entry)
        print(f"  ticket={d.ticket} {d.symbol} {side} {entry} vol={d.volume} "
              f"price={d.price} profit={d.profit:.2f} magic={d.magic} "
              f"comment='{d.comment}' time={dt.datetime.fromtimestamp(d.time)}")
finally:
    mt5.shutdown()
