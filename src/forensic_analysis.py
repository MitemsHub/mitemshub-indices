import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta
import json

mt5.initialize()

# ═══════════════════════════════════════════════════════════════
# PHASE 1: Discover ALL synthetic indices available
# ═══════════════════════════════════════════════════════════════
print("=" * 80)
print("PHASE 1: DISCOVERING ALL SYNTHETIC INDICES")
print("=" * 80)

# Get all symbols
all_symbols = mt5.symbols_get(group="Synthetics")
if not all_symbols:
    # Try alternate approach
    all_symbols = mt5.symbols_get()

synthetics = []
for sym in all_symbols:
    name = sym.name
    # Filter for synthetic indices we care about
    if any(kw in name.lower() for kw in ['volatility', 'boom', 'crash', 'step', 'jump', 'drift']):
        # Try to get tick data
        tick = mt5.symbol_info_tick(name)
        if tick and tick.ask > 0 and tick.bid > 0:
            info = mt5.symbol_info(name)
            if info and info.visible:
                synthetics.append({
                    'name': name,
                    'point': info.point,
                    'digits': info.digits,
                    'tick_value': info.trade_tick_value,
                    'tick_size': info.trade_tick_size,
                    'volume_min': info.volume_min,
                    'volume_max': info.volume_max,
                    'volume_step': info.volume_step,
                    'margin_initial': info.margin_initial,
                    'spread': info.spread,
                    'bid': tick.bid,
                    'ask': tick.ask,
                    'contract_size': info.trade_contract_size,
                })

print(f"\nFound {len(synthetics)} tradeable synthetic indices:\n")
for s in synthetics:
    dollar_per_lot = s['tick_value'] / s['tick_size'] * s['point'] if s['tick_size'] > 0 else 0
    spread_cost = s['spread'] * s['point'] * dollar_per_lot
    print(f"  {s['name']:<30} Point={s['point']:<10} TickVal={s['tick_value']:<12} "
          f"Margin=${s['margin_initial']:<8.2f} Spread={s['spread']:<6} "
          f"$1/lot={dollar_per_lot:.4f} SpreadCost=${spread_cost:.4f}")

# ═══════════════════════════════════════════════════════════════
# PHASE 2: Analyze EACH symbol's trading characteristics
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("PHASE 2: ANALYZING EACH SYMBOL (90-day M5 data)")
print("=" * 80)

results = []

for s in synthetics:
    name = s['name']
    point = s['point']
    tick_val = s['tick_value']
    tick_size = s['tick_size']
    margin = s['margin_initial']
    spread = s['spread']
    
    dollar_per_lot = tick_val / tick_size * point if tick_size > 0 else 0
    spread_cost_per_lot = spread * point * dollar_per_lot
    
    # How many lots can we buy with $22.75 (using 70% margin)?
    margin_budget = 22.75 * 0.70
    max_lots = int(margin_budget / margin) if margin > 0 else 0
    max_lots = min(max_lots, int(s['volume_max']))
    
    if max_lots < s['volume_min']:
        max_lots = 0
    
    # Get 90 days of M5 data
    rates = mt5.copy_rates_from(name, mt5.TIMEFRAME_M5, datetime.now() - timedelta(days=90), 25000)
    if rates is None or len(rates) < 1000:
        print(f"\n  {name}: insufficient data ({len(rates) if rates else 0} bars)")
        continue
    
    closes = np.array([r['close'] for r in rates])
    highs = np.array([r['high'] for r in rates])
    lows = np.array([r['low'] for r in rates])
    times_arr = np.array([r['time'] for r in rates])
    n = len(closes)
    
    # Basic stats
    price_range = np.max(closes) - np.min(closes)
    avg_price = np.mean(closes)
    
    # ATR (14-period)
    tr = np.maximum(highs[1:] - lows[1:], 
         np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    atr_14 = np.zeros(len(tr))
    atr_14[13] = np.mean(tr[:14])
    for i in range(14, len(tr)):
        atr_14[i] = (atr_14[i-1] * 13 + tr[i]) / 14
    avg_atr = np.mean(atr_14[-500:])  # Last 500 bars
    
    # Convert to points
    atr_points = avg_atr / point if point > 0 else 0
    
    # Dollar value of ATR move at max lots
    atr_dollar = atr_points * max_lots * dollar_per_lot
    
    # Daily range (in points)
    daily_ranges = []
    current_day = None
    day_high = day_low = closes[0]
    for i in range(n):
        day = times_arr[i] // 86400
        if day != current_day:
            if current_day is not None:
                daily_ranges.append((day_high - day_low) / point)
            current_day = day
            day_high = highs[i]
            day_low = lows[i]
        else:
            day_high = max(day_high, highs[i])
            day_low = min(day_low, lows[i])
    avg_daily_range = np.mean(daily_ranges) if daily_ranges else 0
    
    # Trend analysis using EMAs
    def ema(data, period):
        result = np.zeros(len(data))
        result[:period-1] = np.nan
        result[period-1] = np.mean(data[:period])
        multiplier = 2 / (period + 1)
        for i in range(period, len(data)):
            result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]
        return result
    
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    
    # Trending percentage
    valid = ~np.isnan(ema20) & ~np.isnan(ema50)
    trending = np.sum((ema20[valid] > ema50[valid]) | (ema20[valid] < ema50[valid]))
    trend_pct = trending / np.sum(valid) * 100 if np.sum(valid) > 0 else 0
    
    # Profit factor simulation: simple EMA crossover backtest
    trades = []
    pos = 0
    entry_price = 0
    sl_dist = 0
    
    for i in range(51, n-1):
        if np.isnan(ema20[i]) or np.isnan(ema50[i]) or atr_14[i] <= 0:
            continue
        
        if pos != 0:
            # Check SL
            if pos > 0 and lows[i] <= entry_price - sl_dist:
                trades.append(-sl_dist / point)
                pos = 0
                continue
            if pos < 0 and highs[i] >= entry_price + sl_dist:
                trades.append(-sl_dist / point)
                pos = 0
                continue
            
            # Check TP (2x SL)
            if pos > 0 and highs[i] >= entry_price + sl_dist * 2:
                trades.append(sl_dist * 2 / point)
                pos = 0
                continue
            if pos < 0 and lows[i] <= entry_price - sl_dist * 2:
                trades.append(sl_dist * 2 / point)
                pos = 0
                continue
            
            # Time exit (20 bars)
            continue
        
        # Entry signals
        if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]:
            pos = 1
            entry_price = closes[i]
            sl_dist = atr_14[i] * 1.5
        elif ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]:
            pos = -1
            entry_price = closes[i]
            sl_dist = atr_14[i] * 1.5
    
    n_trades = len(trades)
    if n_trades > 0:
        wins = sum(1 for t in trades if t > 0)
        win_rate = wins / n_trades * 100
        total_pts = sum(trades)
        avg_trade = total_pts / n_trades
    else:
        win_rate = 0
        total_pts = 0
        avg_trade = 0
    
    # Dollar P&L at max lots
    dollar_per_trade = avg_trade * max_lots * dollar_per_lot
    total_dollar_pnl = total_pts * max_lots * dollar_per_lot
    
    # Spread analysis
    spread_pct_of_atr = (spread * point) / avg_atr * 100 if avg_atr > 0 else 100
    trades_per_spread = atr_points / spread if spread > 0 else 0
    
    result = {
        'name': name,
        'point': point,
        'dollar_per_lot': dollar_per_lot,
        'margin': margin,
        'spread': spread,
        'spread_cost': spread_cost_per_lot,
        'max_lots': max_lots,
        'avg_atr_pts': atr_points,
        'avg_daily_range_pts': avg_daily_range,
        'trend_pct': trend_pct,
        'n_trades': n_trades,
        'win_rate': win_rate,
        'total_pts': total_pts,
        'avg_trade_pts': avg_trade,
        'dollar_per_trade': dollar_per_trade,
        'total_dollar_pnl': total_dollar_pnl,
        'spread_pct_of_atr': spread_pct_of_atr,
        'trades_per_spread': trades_per_spread,
        'atr_dollar': atr_dollar,
    }
    results.append(result)
    
    print(f"\n  {name}:")
    print(f"    Point: {point} | $1/lot: ${dollar_per_lot:.4f} | Max lots: {max_lots}")
    print(f"    Avg ATR: {atr_points:.1f} pts (${atr_dollar:.2f} at {max_lots} lots)")
    print(f"    Daily range: {avg_daily_range:.0f} pts | Trend%: {trend_pct:.1f}%")
    print(f"    Spread: {spread} pts ({spread_pct_of_atr:.1f}% of ATR) | Trades/spread: {trades_per_spread:.1f}")
    print(f"    Backtest: {n_trades} trades | WR: {win_rate:.1f}% | Avg: {avg_trade:.1f} pts")
    print(f"    Dollar P&L: ${total_dollar_pnl:.2f} | Per trade: ${dollar_per_trade:.4f}")

# ═══════════════════════════════════════════════════════════════
# PHASE 3: Rank and recommend
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("PHASE 3: RANKING & RECOMMENDATION")
print("=" * 80)

# Score each symbol
for r in results:
    # Composite score: consider profit, spread cost, trend, and dollar value
    r['score'] = 0
    if r['max_lots'] > 0 and r['spread_pct_of_atr'] < 50:
        r['score'] = r['total_dollar_pnl'] / max(abs(r['total_dollar_pnl']), 1) * 100
        r['score'] += r['trend_pct'] / 10
        r['score'] -= r['spread_pct_of_atr']
        r['score'] += min(r['trades_per_spread'], 10)

results.sort(key=lambda x: x['score'], reverse=True)

print(f"\n{'Rank':<5} {'Symbol':<30} {'$/10pts':<12} {'Max Lots':<10} {'Spread%':<10} {'Trend%':<10} {'WR%':<8} {'P&L':<12} {'Score':<8}")
print("-" * 105)
for i, r in enumerate(results[:10]):
    dollar_10pts = 10 * r['max_lots'] * r['dollar_per_lot']
    print(f"#{i+1:<4} {r['name']:<30} ${dollar_10pts:<11.2f} {r['max_lots']:<10} {r['spread_pct_of_atr']:<10.1f} "
          f"{r['trend_pct']:<10.1f} {r['win_rate']:<8.1f} ${r['total_dollar_pnl']:<+11.2f} {r['score']:<8.1f}")

# Best recommendation
best = results[0] if results else None
if best:
    print(f"\n{'='*80}")
    print(f"RECOMMENDATION: {best['name']}")
    print(f"{'='*80}")
    print(f"  Why: Best composite score considering profitability,")
    print(f"  spread efficiency, trend strength, and dollar potential.")
    print(f"  Point: {best['point']} | $1/lot: ${best['dollar_per_lot']:.4f}")
    print(f"  Max lots on $22.75: {best['max_lots']}")
    print(f"  ATR: {best['avg_atr_pts']:.1f} pts | Daily range: {best['avg_daily_range_pts']:.0f} pts")
    print(f"  Spread: {best['spread']} pts ({best['spread_pct_of_atr']:.1f}% of ATR)")
    print(f"  Trend%: {best['trend_pct']:.1f}% | Win rate: {best['win_rate']:.1f}%")
    print(f"  Estimated P&L (90d): ${best['total_dollar_pnl']:.2f}")

mt5.shutdown()
