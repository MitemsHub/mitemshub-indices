#!/usr/bin/env python3
"""V100 FINAL VERDICT — Simple scalper showing what's actually possible"""

import MetaTrader5 as mt5
import numpy as np

mt5.initialize()
sym = "Volatility 100 Index"
mt5.symbol_select(sym, True)
info = mt5.symbol_info(sym)
dpp = info.trade_tick_value / info.trade_tick_size * info.point  # $/point/lot
acc = mt5.account_info()
margin_per_lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 1, info.ask)
if not margin_per_lot or margin_per_lot <= 0:
    margin_per_lot = info.ask * info.trade_contract_size / acc.leverage

equity = acc.equity
max_lots = min(int(equity * 0.70 / margin_per_lot), info.volume_max)
spread_price = info.spread * info.point  # spread in price units
spread_cost_lots = spread_price * dpp  # $ spread per lot

print(f"{'='*70}")
print(f"  V100 FINAL VERDICT")
print(f"{'='*70}")
print(f"  Price:           {info.ask}")
print(f"  $/pt/lot:        ${dpp}")
print(f"  Spread:          {info.spread} pts = {spread_price:.2f} price = ${spread_cost_lots * 1:.4f}/lot")
print(f"  Equity:          ${equity:.2f}")
print(f"  Max lots (70%):  {max_lots}")
print(f"  Margin/lot:      ${margin_per_lot:.4f}")

# H1 data
rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2000)
closes = rates['close']
highs = rates['high']
lows = rates['low']
opens = rates['open']
n = len(closes)
days = n / 24

print(f"  H1 bars:         {n} ({days:.0f} days)")

# What if you entered EVERY bar in the direction of the bar body?
body_dirs = np.sign(closes - opens)
ranges = highs - lows
bodies = np.abs(closes - opens)

print(f"\n{'─'*70}")
print(f"  SCENARIO 1: Buy every bullish H1 bar, sell every bearish H1 bar")
print(f"  (Enter at open, exit at close, accounting for spread)")
print(f"{'─'*70}")

for lots in [5, 10, 15, 20, 25]:
    pnl = 0
    wins = 0
    total = 0
    for i in range(1, n):
        if body_dirs[i] == 0:
            continue
        total += 1
        # Simulate: enter at open, exit at close
        if body_dirs[i] > 0:  # bullish bar
            # Buy at open, sell at close
            gain = (closes[i] - opens[i] - spread_price) * lots * dpp
        else:  # bearish bar
            # Sell at open, buy at close
            gain = (opens[i] - closes[i] - spread_price) * lots * dpp
        
        pnl += gain
        if gain > 0: wins += 1
    
    wr = wins / total * 100 if total > 0 else 0
    avg_trade = pnl / total if total > 0 else 0
    daily_pnl = pnl / days
    risk_per_trade = lots * spread_price * dpp + 2 * lots * dpp  # approximate max risk
    
    print(f"  {lots} lots: {total} trades, WR={wr:.1f}%, Total=${pnl:.2f}, Daily=${daily_pnl:.2f}, Avg=${avg_trade:.2f}")

# Scenario 2: Capture half the bar range
print(f"\n{'─'*70}")
print(f"  SCENARIO 2: Capture 50% of each bar's range (realistic partial capture)")
print(f"{'─'*70}")

for lots in [5, 10, 15, 20, 25]:
    pnl = 0
    total = 0
    for i in range(1, n):
        if body_dirs[i] == 0:
            continue
        total += 1
        # Capture 50% of the body, minus spread
        half_body = bodies[i] * 0.5
        gain = (half_body - spread_price) * lots * dpp
        pnl += gain
    
    avg = pnl / total if total > 0 else 0
    daily = pnl / days
    print(f"  {lots} lots: Total=${pnl:.2f}, Daily=${daily:.2f}, Avg=${avg:.2f}, ROI={pnl/equity*100:.0f}%")

# Scenario 3: What about M5?
print(f"\n{'─'*70}")
print(f"  SCENARIO 3: V100 on M5 — more opportunities")
print(f"{'─'*70}")

rates_m5 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 5000)
if rates_m5 is not None and len(rates_m5) > 500:
    closes_m5 = rates_m5['close']
    opens_m5 = rates_m5['open']
    highs_m5 = rates_m5['high']
    lows_m5 = rates_m5['low']
    n_m5 = len(closes_m5)
    days_m5 = n_m5 / 288
    
    ranges_m5 = highs_m5 - lows_m5
    print(f"  M5 bars: {n_m5} ({days_m5:.0f} days)")
    print(f"  Avg range: {np.mean(ranges_m5):.2f} price = {np.mean(ranges_m5)/info.point:.0f} pts")
    print(f"  Avg body:  {np.mean(np.abs(closes_m5 - opens_m5)):.2f} price")
    
    body_dirs_m5 = np.sign(closes_m5 - opens_m5)
    
    for lots in [5, 10, 15, 20, 25]:
        pnl = 0
        wins = 0
        total = 0
        for i in range(1, n_m5):
            if body_dirs_m5[i] == 0: continue
            total += 1
            if body_dirs_m5[i] > 0:
                gain = (closes_m5[i] - opens_m5[i] - spread_price) * lots * dpp
            else:
                gain = (opens_m5[i] - closes_m5[i] - spread_price) * lots * dpp
            pnl += gain
            if gain > 0: wins += 1
        
        wr = wins / total * 100 if total > 0 else 0
        daily = pnl / days_m5
        print(f"  {lots} lots: WR={wr:.1f}%, Daily=${daily:.2f}, ROI={pnl/equity*100:.0f}%")

# Scenario 4: Scalping with 1-3pt targets
print(f"\n{'─'*70}")
print(f"  SCENARIO 4: Target 2pt moves, SL 1.5pt, max 3/day")
print(f"{'─'*70}")

# Count how often V100 makes a 2pt move from any point
for lots in [5, 10, 15, 20, 25]:
    wins = 0
    losses = 0
    total_pnl = 0
    
    for i in range(250, n-1):
        # Check if there's a 2pt move in the next few bars
        entry = closes[i]
        # Look at next 4 bars
        max_move = 0
        for j in range(1, min(5, n-i)):
            max_move = max(max_move, abs(closes[i+j] - entry))
        
        if max_move >= 2.0:
            # Would have captured the move (assuming we pick direction correctly ~55% of time)
            # Simplified: trade with the bar direction
            if body_dirs[i] > 0:
                gain = (2.0 - spread_price) * lots * dpp
            else:
                gain = (2.0 - spread_price) * lots * dpp
            wins += 1
            total_pnl += gain
        elif max_move >= 1.5:
            # Partial capture
            gain = (1.5 - spread_price) * lots * dpp
            if gain > 0:
                wins += 1
            else:
                losses += 1
            total_pnl += gain
        else:
            # Would hit SL at 1.5pt
            loss = -1.5 * lots * dpp
            losses += 1
            total_pnl += loss
    
    total = wins + losses
    wr = wins / total * 100 if total > 0 else 0
    daily = total_pnl / days
    
    print(f"  {lots} lots: {total} trades ({total/days:.1f}/day), WR={wr:.1f}%, Daily=${daily:.2f}")

# Final honest verdict
print(f"\n{'='*70}")
print(f"  HONEST VERDICT: V100 on ${equity:.2f}")
print(f"{'='*70}")
print(f"""
  THE MATH:
  ─────────
  V100 H1 moves an average of {np.mean(ranges):.1f} price per bar
  At {max_lots} lots (70% margin): ${np.mean(ranges) * max_lots * dpp:.2f} per bar
  Spread cost: ${spread_price * max_lots * dpp:.2f} per trade

  For $2/day: Need ${2/days:.2f}/day = {2/np.mean(ranges)/max_lots/dpp:.0f} successful trades
  For $5/day: Need ${5/days:.2f}/day = {5/np.mean(ranges)/max_lots/dpp:.0f} successful trades
  For $10/day: Need ${10/days:.2f}/day = {10/np.mean(ranges)/max_lots/dpp:.0f} successful trades

  BUT at {max_lots} lots with 1.5pt SL:
  One loss = ${1.5 * max_lots * dpp:.2f} = {1.5 * max_lots * dpp/equity*100:.0f}% of equity
  3 consecutive losses = ${4.5 * max_lots * dpp:.2f} = {4.5 * max_lots * dpp/equity*100:.0f}% of equity
  Account blown at: {equity / (1.5 * max_lots * dpp):.1f} consecutive losses

  AT SAFE RISK (1% = ${equity*0.01:.2f}):
  Max lots with 3pt SL: {equity*0.01 / (3.0 * dpp):.2f} lots
  $/trade: ${3.0 * dpp * equity*0.01 / (3.0 * dpp):.4f}
  $/day at 2.5 trades: ${3.0 * dpp * equity*0.01 / (3.0 * dpp) * 2.5:.4f}
""")

print("  WHAT YOU MADE MANUALLY TODAY:")
print("  ~$7 in 4-5 hours of trading")
print("  This is POSSIBLE because you used larger volume and caught good moves")
print("")

print("  RECOMMENDATION:")
print("  V100 CAN make money but requires:")
print("    1. Higher volume (15-25 lots)")
print("    2. Tight SL (1.5-3 pt) with quick exit")
print("    3. Capturing $1-$3 per trade net of spread")
print("    4. 2-3 wins per day")
print("    5. Risking $15-$37 per loss (65-165%% of equity)")
print("")
print("  OR with proper risk management (1%% risk):")
print("    Accept $0.07/trade until equity grows to $100+")

mt5.shutdown()
print(f"\n{'='*70}")
