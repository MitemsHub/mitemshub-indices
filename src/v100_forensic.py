#!/usr/bin/env python3
"""V100 FORENSIC ANALYSIS — Is this instrument right for our EA?"""

import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import sys

mt5.initialize()
info = mt5.symbol_info("Volatility 100 Index")
if info is None:
    # Try common variants
    for name in ["Volatility 100 (1s) Index", "Volatility_100_Index", "Volatility100Index"]:
        info = mt5.symbol_info(name)
        if info:
            break

if info is None:
    print("❌ V100 not found. Listing available synthetic indices:")
    syms = mt5.symbols_get()
    for s in syms:
        if "volatil" in s.name.lower() or "step" in s.name.lower() or "boom" in s.name.lower() or "crash" in s.name.lower():
            print(f"  {s.name} | visible={s.visible}")
    mt5.shutdown()
    sys.exit(1)

sym = info.name
mt5.symbol_select(sym, True)
print(f"{'='*70}")
print(f"  V100 FORENSIC ANALYSIS: {sym}")
print(f"{'='*70}")

# === 1. SYMBOL SPECS ===
print(f"\n📊 SYMBOL SPECIFICATIONS")
print(f"{'─'*50}")
print(f"  $/point/lot:     {info.trade_tick_value / info.trade_tick_size * info.point:.6f}")
print(f"  Tick value:      ${info.trade_tick_value:.6f}")
print(f"  Tick size:       {info.trade_tick_size}")
print(f"  Point:           {info.point}")
print(f"  Digits:          {info.digits}")
print(f"  Spread (raw):    {info.spread} pts")
print(f"  Spread ($):      ${info.spread * info.trade_tick_value / info.trade_tick_size * info.point:.6f}")
print(f"  Contract size:   {info.trade_contract_size}")
print(f"  Min volume:      {info.volume_min}")
print(f"  Max volume:      {info.volume_max}")
print(f"  Volume step:     {info.volume_step}")
print(f"  Margin initial:  ${info.margin_initial:.4f}")
acc = mt5.account_info()
print(f"  Leverage:        1:{acc.leverage}")

dollar_per_point = info.trade_tick_value / info.trade_tick_size * info.point
print(f"\n  💰 $/point/lot = ${dollar_per_point:.6f}")

# Max volume calculation
equity = mt5.account_info().equity
# Calculate margin per lot using order_calc_margin
margin_per_lot_test = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 1, info.ask)
if margin_per_lot_test is None or margin_per_lot_test <= 0:
    # Use leverage-based calculation
    margin_per_lot_test = info.ask * info.trade_contract_size / acc.leverage if acc.leverage > 0 else info.ask * info.trade_contract_size
    
margin_70pct = equity * 0.70
max_lots_from_margin = int(margin_70pct / margin_per_lot_test) if margin_per_lot_test > 0 else 0
max_lots_safe = min(max_lots_from_margin, info.volume_max)
print(f"  Equity:          ${equity:.2f}")
print(f"  70% margin:      ${margin_70pct:.2f} → {max_lots_safe} lots max")
print(f"  $/pt at max vol: ${dollar_per_point * max_lots_safe:.4f}")

# === 2. MULTI-TIMEFRAME DATA ANALYSIS ===
print(f"\n\n📈 MULTI-TIMEFRAME ANALYSIS")
print(f"{'─'*50}")

for tf_name, tf, bars_needed in [("M5", mt5.TIMEFRAME_M5, 2000), ("M15", mt5.TIMEFRAME_M15, 2000), 
                                   ("H1", mt5.TIMEFRAME_H1, 2000), ("H4", mt5.TIMEFRAME_H4, 2000)]:
    rates = mt5.copy_rates_from_pos(sym, tf, 0, bars_needed)
    if rates is None or len(rates) < 100:
        print(f"  {tf_name}: insufficient data")
        continue
    
    closes = rates['close']
    highs = rates['high']
    lows = rates['low']
    opens = rates['open']
    bodies = np.abs(closes - opens)
    ranges = highs - lows
    
    # ATR
    atr_14 = np.mean(ranges[-14:])
    
    # Average range in points
    avg_range_pts = np.mean(ranges) / info.point
    avg_body_pts = np.mean(bodies) / info.point
    
    # Trend analysis using EMAs
    ema20 = np.convolve(closes, np.ones(20)/20, mode='valid')[-200:]
    ema50 = np.convolve(closes, np.ones(50)/50, mode='valid')[-200:]
    
    trend_up = np.sum(ema20 > ema50) / len(ema20) * 100
    trend_down = np.sum(ema20 < ema50) / len(ema20) * 100
    ranging = 100 - trend_up - trend_down
    
    # Consecutive directional bars
    directions = np.sign(closes - opens)
    max_consec = 1
    curr_consec = 1
    for i in range(1, len(directions)):
        if directions[i] == directions[i-1] and directions[i] != 0:
            curr_consec += 1
            max_consec = max(max_consec, curr_consec)
        else:
            curr_consec = 1
    
    # Active bars (had some movement)
    active_bars = np.sum(ranges > 0) / len(ranges) * 100
    
    # Volatility regime
    high_vol_bars = np.sum(ranges > 2 * np.mean(ranges)) / len(ranges) * 100
    low_vol_bars = np.sum(ranges < 0.5 * np.mean(ranges)) / len(ranges) * 100
    
    # Time span
    first_time = datetime.fromtimestamp(rates[0]['time'])
    last_time = datetime.fromtimestamp(rates[-1]['time'])
    days = (last_time - first_time).total_seconds() / 86400
    
    bars_per_day = len(rates) / max(days, 1)
    
    print(f"\n  {tf_name} ({len(rates)} bars, {days:.0f} days)")
    print(f"    Avg range:     {avg_range_pts:.1f} pts (${avg_range_pts * dollar_per_point * max_lots_safe:.4f} at max vol)")
    print(f"    Avg body:      {avg_body_pts:.1f} pts")
    print(f"    ATR(14):       {atr_14 / info.point:.1f} pts")
    print(f"    Trend up:      {trend_up:.1f}% | Down: {trend_down:.1f}% | Range: {ranging:.1f}%")
    print(f"    Max consec:    {max_consec} bars same direction")
    print(f"    Active bars:   {active_bars:.1f}%")
    print(f"    High vol:      {high_vol_bars:.1f}% | Low vol: {low_vol_bars:.1f}%")
    print(f"    Bars/day:      {bars_per_day:.0f}")

# === 3. TRADE OPPORTUNITY ANALYSIS ===
print(f"\n\n🎯 TRADE OPPORTUNITY ANALYSIS (H1, last 90 days)")
print(f"{'─'*50}")

rates_h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 2000)
if rates_h1 is not None and len(rates_h1) > 500:
    closes = rates_h1['close']
    highs = rates_h1['high']
    lows = rates_h1['low']
    opens = rates_h1['open']
    ranges = highs - lows
    bodies = closes - opens
    
    # How many points does V100 move per H1 bar?
    avg_range_h1 = np.mean(ranges[-500:]) / info.point
    
    # How many bars exceed X points?
    for pts in [10, 20, 50, 100, 200, 500]:
        count = np.sum(ranges[-500:] > pts * info.point)
        pct = count / 500 * 100
        dollars = pts * dollar_per_point * max_lots_safe
        print(f"    Bars > {pts:>4} pts: {count:>4} ({pct:>5.1f}%) → ${dollars:.2f} at max vol")
    
    # Best direction
    bullish_bars = np.sum(bodies[-500:] > 0)
    bearish_bars = np.sum(bodies[-500:] < 0)
    print(f"\n    Bullish H1 bars: {bullish_bars} ({bullish_bars/500*100:.1f}%)")
    print(f"    Bearish H1 bars: {bearish_bars} ({bearish_bars/500*100:.1f}%)")
    
    # Hourly distribution
    hours = rates_h1['time'] % 86400 // 3600
    print(f"\n    Hourly activity (avg range in pts):")
    for h in range(24):
        mask = hours == h
        if np.sum(mask) > 0:
            avg_r = np.mean(ranges[mask]) / info.point
            avg_b = np.mean(np.abs(bodies[mask])) / info.point
            print(f"      {h:02d}:00 → range={avg_r:.0f} pts | body={avg_b:.0f} pts | ${avg_r * dollar_per_point * max_lots_safe:.2f}")

# === 4. WHAT DOES OUR EA NEED? ===
print(f"\n\n🔍 EA COMPATIBILITY CHECK")
print(f"{'─'*50}")

atr_h1 = np.mean(ranges[-14:]) / info.point if len(ranges) > 14 else 0

# v19 SL = max(structure SL, 1.5 * ATR)
# v19 TP = 2 * SL
sl_distance = max(1.5 * atr_h1, 10)  # minimum 10 pts
tp_distance = 2.0 * sl_distance

sl_dollars = sl_distance * dollar_per_point * max_lots_safe
tp_dollars = tp_distance * dollar_per_point * max_lots_safe

print(f"  ATR(H1):          {atr_h1:.0f} pts")
print(f"  v19 SL distance:  {sl_distance:.0f} pts → ${sl_dollars:.2f} at {max_lots_safe} lots")
print(f"  v19 TP distance:  {tp_distance:.0f} pts → ${tp_dollars:.2f} at {max_lots_safe} lots")
print(f"  R:R ratio:        {tp_distance/sl_distance:.1f}:1")
print(f"  Spread cost:      ${info.spread * dollar_per_point * max_lots_safe:.4f}")

# Can V100 even reach our TP?
daily_moves = []
for i in range(0, min(len(closes)-24, 500), 24):
    daily_moves.append(np.max(highs[i:i+24]) - np.min(lows[i:i+24]))
avg_daily_move = np.mean(daily_moves) / info.point
print(f"  Avg daily range:  {avg_daily_move:.0f} pts")
print(f"  TP/ATR ratio:     {tp_distance/avg_daily_move*100:.1f}% of daily range")
print(f"  Days needed for TP: {tp_distance/avg_daily_move:.2f}")

# === 5. THE HONEST ASSESSMENT ===
print(f"\n\n{'='*70}")
print(f"  HONEST ASSESSMENT: V100 on $22.75 account")
print(f"{'='*70}")

risk_per_trade = equity * 0.01  # 1% risk
max_loss_at_risk = risk_per_trade
safe_lots_for_1pct_risk = max_loss_at_risk / (sl_distance * dollar_per_point) if sl_distance * dollar_per_point > 0 else 0
safe_lots_for_1pct_risk = min(safe_lots_for_1pct_risk, info.volume_max)

print(f"\n  With 1% risk (${risk_per_trade:.2f}):")
print(f"    Safe lot size:  {safe_lots_for_1pct_risk:.2f} lots")
print(f"    $/point:        ${dollar_per_point * safe_lots_for_1pct_risk:.4f}")
print(f"    TP ($):         ${tp_distance * dollar_per_point * safe_lots_for_1pct_risk:.4f}")
print(f"    SL ($):         ${sl_distance * dollar_per_point * safe_lots_for_1pct_risk:.4f}")

print(f"\n  With max volume ({max_lots_safe} lots, 70% margin):")
print(f"    $/point:        ${dollar_per_point * max_lots_safe:.4f}")
print(f"    TP ($):         ${tp_distance * dollar_per_point * max_lots_safe:.4f}")
print(f"    SL ($):         ${sl_distance * dollar_per_point * max_lots_safe:.4f}")
print(f"    Risk:           {sl_distance * dollar_per_point * max_lots_safe / equity * 100:.1f}% of equity")

# Compare to Step Index
print(f"\n\n  📊 COMPARISON WITH STEP INDEX:")
step_info = mt5.symbol_info("Step Index")
if step_info:
    mt5.symbol_select("Step Index", True)
    step_dollar_per_point = step_info.trade_tick_value / step_info.trade_tick_size * step_info.point
    step_margin_per_lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, "Step Index", 1, step_info.ask)
    if not step_margin_per_lot or step_margin_per_lot <= 0:
        step_margin_per_lot = step_info.ask * step_info.trade_contract_size / acc.leverage if acc.leverage > 0 else step_info.ask * step_info.trade_contract_size
    step_max_lots = int(margin_70pct / step_margin_per_lot) if step_margin_per_lot > 0 else 0
    step_max_lots = min(step_max_lots, step_info.volume_max)
    
    print(f"    {'':20s} {'V100':>12s} {'Step Index':>12s}")
    print(f"    {'$/point/lot':20s} ${dollar_per_point:>11.6f} ${step_dollar_per_point:>11.2f}")
    print(f"    {'Max lots (70%)':20s} {max_lots_safe:>12} {step_max_lots:>12}")
    print(f"    {'$/pt at max':20s} ${dollar_per_point*max_lots_safe:>11.4f} ${step_dollar_per_point*step_max_lots:>11.2f}")
    print(f"    {'Spread pts':20s} {info.spread:>12} {step_info.spread:>12}")
    print(f"    {'Spread $':20s} ${info.spread*dollar_per_point*max_lots_safe:>11.6f} ${step_info.spread*step_dollar_per_point*step_max_lots:>11.2f}")
    print(f"    {'TP at max ($)':20s} ${tp_distance*dollar_per_point*max_lots_safe:>11.4f} ${tp_distance*step_dollar_per_point*step_max_lots:>11.2f}")
    print(f"    {'Margin/lot':20s} ${margin_per_lot_test:>11.4f} ${step_margin_per_lot:>11.2f}")

mt5.shutdown()
print(f"\n{'='*70}")
