import MetaTrader5 as mt5
import numpy as np
from datetime import datetime, timedelta

mt5.initialize()

# ═══════════════════════════════════════════════════════════════
# STEP INDEX: MULTI-TIMEFRAME ANALYSIS
# ═══════════════════════════════════════════════════════════════
print("="*80)
print(" STEP INDEX: MULTI-TIMEFRAME BEHAVIORAL ANALYSIS")
print("="*80)

for tf_name, tf in [("M5", mt5.TIMEFRAME_M5), ("M15", mt5.TIMEFRAME_M15), 
                      ("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4)]:
    bars = mt5.copy_rates_from("Step Index", tf, datetime.now() - timedelta(days=90), 5000)
    if bars is None or len(bars) < 100:
        print(f"  {tf_name}: insufficient data")
        continue
    
    closes = np.array([b['close'] for b in bars])
    highs = np.array([b['high'] for b in bars])
    lows = np.array([b['low'] for b in bars])
    
    # Basic stats
    steps = np.abs(np.diff(closes)) / 0.1
    avg_steps = np.mean(steps)
    
    # ATR
    tr = np.maximum(highs[1:] - lows[1:], np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])))
    atr14 = np.mean(tr[-14:])
    
    # Trend analysis using EMA
    ema20 = np.full(len(closes), np.nan)
    ema50 = np.full(len(closes), np.nan)
    ema20[19] = np.mean(closes[:20])
    ema50[49] = np.mean(closes[:50])
    a20 = 2.0/21; a50 = 2.0/51
    for i in range(20, len(closes)): ema20[i] = a20*closes[i] + (1-a20)*ema20[i-1]
    for i in range(50, len(closes)): ema50[i] = a50*closes[i] + (1-a50)*ema50[i-1]
    
    # Trending vs ranging
    trending = 0; total = 0
    for i in range(50, len(closes)):
        if not np.isnan(ema20[i]) and not np.isnan(ema50[i]):
            total += 1
            if (ema20[i] > ema50[i] and closes[i] > ema20[i]) or (ema20[i] < ema50[i] and closes[i] < ema20[i]):
                trending += 1
    
    # Max consecutive same-direction bars
    dirs = np.sign(np.diff(closes))
    max_consec = 1; cur = 1
    for d in dirs[1:]:
        if d == dirs[cur-1] and d != 0: cur += 1
        else: max_consec = max(max_consec, cur); cur = 1
    max_consec = max(max_consec, cur)
    
    # Win rate of buying dips in uptrend
    buy_dips = 0; buy_dips_win = 0
    sell_rallies = 0; sell_rallies_win = 0
    for i in range(51, len(closes)):
        if np.isnan(ema20[i]) or np.isnan(ema50[i]): continue
        
        # Buy dip: uptrend + price pulled back to EMA20
        if ema20[i] > ema50[i]:
            if closes[i] < ema20[i] and closes[i] > ema50[i]:
                buy_dips += 1
                # Check if next bar goes up
                if i + 1 < len(closes) and closes[i+1] > closes[i]:
                    buy_dips_win += 1
        
        # Sell rally: downtrend + price rallied to EMA20
        if ema20[i] < ema50[i]:
            if closes[i] > ema20[i] and closes[i] < ema50[i]:
                sell_rallies += 1
                if i + 1 < len(closes) and closes[i+1] < closes[i]:
                    sell_rallies_win += 1
    
    # Breakout detection
    breakout_bars = 0; breakout_win = 0
    for i in range(21, len(closes)):
        hh = max(highs[i-20:i])
        ll = min(lows[i-20:i])
        rng = hh - ll
        if rng > 0:
            atr_t = np.mean(tr[max(0,i-14):i])
            if atr_t > 0 and rng < atr_t * 0.6:  # compression
                if i + 1 < len(closes):
                    if closes[i] > hh:  # breakout up
                        breakout_bars += 1
                        if closes[i+1] > closes[i]: breakout_win += 1
                    elif closes[i] < ll:  # breakout down
                        breakout_bars += 1
                        if closes[i+1] < closes[i]: breakout_win += 1
    
    buy_dip_wr = buy_dips_win/buy_dips*100 if buy_dips > 0 else 0
    sell_rally_wr = sell_rallies_win/sell_rallies*100 if sell_rallies > 0 else 0
    breakout_wr = breakout_win/breakout_bars*100 if breakout_bars > 0 else 0
    
    print(f"\n  {tf_name} ({len(bars)} bars):")
    print(f"    Avg steps/bar: {avg_steps:.1f} | ATR(14): {atr14:.1f}")
    print(f"    Trend%: {trending/total*100:.1f}% | Max consec same dir: {max_consec}")
    print(f"    Buy dip WR: {buy_dip_wr:.1f}% ({buy_dips} trades)")
    print(f"    Sell rally WR: {sell_rally_wr:.1f}% ({sell_rallies} trades)")
    print(f"    Breakout WR: {breakout_wr:.1f}% ({breakout_bars} trades)")

# ═══════════════════════════════════════════════════════════════
# STEP INDEX: QUICK BACKTEST — SIMPLE STRATEGIES
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*80)
print(" STEP INDEX: STRATEGY BACKTESTS (M15, 90 days)")
print("="*80)

bars = mt5.copy_rates_from("Step Index", mt5.TIMEFRAME_M15, datetime.now() - timedelta(days=90), 9000)
closes = np.array([b['close'] for b in bars])
highs = np.array([b['high'] for b in bars])
lows = np.array([b['low'] for b in bars])
opens = np.array([b['open'] for b in bars])
times = np.array([b['time'] for b in bars])

# Indicators
ema20 = np.full(len(closes), np.nan)
ema50 = np.full(len(closes), np.nan)
ema100 = np.full(len(closes), np.nan)
rsi = np.full(len(closes), 50.0)

ema20[19] = np.mean(closes[:20])
ema50[49] = np.mean(closes[:50])
ema100[99] = np.mean(closes[:100])
for i in range(20, len(closes)): ema20[i] = 2/21*closes[i] + 19/21*ema20[i-1]
for i in range(50, len(closes)): ema50[i] = 2/51*closes[i] + 49/51*ema50[i-1]
for i in range(100, len(closes)): ema100[i] = 2/101*closes[i] + 99/101*ema100[i-1]

for i in range(14, len(closes)):
    deltas = np.diff(closes[i-14:i+1])
    gains = np.sum(deltas[deltas > 0])
    losses = -np.sum(deltas[deltas < 0])
    rsi[i] = 100 if losses == 0 else 100 - 100/(1+gains/losses)

# ATR
tr = np.maximum(highs[1:]-lows[1:], np.maximum(np.abs(highs[1:]-closes[:-1]), np.abs(lows[1:]-closes[:-1])))
tr = np.insert(tr, 0, 0)
atr = np.zeros(len(tr)); atr[14] = np.mean(tr[1:15])
for i in range(15, len(tr)): atr[i] = (atr[i-1]*13 + tr[i])/14

equity = 22.75
margin_per_lot = 7.83  # Step Index

# ── Strategy 1: EMA Crossover ──
eq1 = equity; trades1 = []; wins1 = 0
pos = 0; entry = 0; sl_dist = 0; entry_bar = 0
for i in range(101, len(closes)-1):
    if atr[i] <= 0: continue
    if pos != 0:
        held = i - entry_bar
        bid = closes[i]; ask = closes[i]
        # SL/TP
        if pos > 0:
            if bid <= entry - sl_dist: pos = 0; trades1.append(-1); continue
            if bid >= entry + sl_dist * 2.5: pos = 0; trades1.append(2.5); wins1 += 1; continue
        else:
            if ask >= entry + sl_dist: pos = 0; trades1.append(-1); continue
            if ask <= entry - sl_dist * 2.5: pos = 0; trades1.append(2.5); wins1 += 1; continue
        if held >= 16:
            pnl = (closes[i] - entry) * pos
            trades1.append(pnl / sl_dist if sl_dist > 0 else 0)
            if pnl > 0: wins1 += 1
            pos = 0
        continue
    
    if ema20[i] > ema50[i] and ema20[i-1] <= ema50[i-1]:
        pos = 1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
    elif ema20[i] < ema50[i] and ema20[i-1] >= ema50[i-1]:
        pos = -1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i

n1 = len(trades1)
wr1 = wins1/n1*100 if n1 > 0 else 0
r1 = sum(trades1)

# ── Strategy 2: Pullback to EMA20 in Trend ──
eq2 = equity; trades2 = []; wins2 = 0
pos = 0; entry = 0; sl_dist = 0; entry_bar = 0
for i in range(101, len(closes)-1):
    if atr[i] <= 0: continue
    if pos != 0:
        held = i - entry_bar
        bid = closes[i]
        if pos > 0:
            if bid <= entry - sl_dist: pos = 0; trades2.append(-1); continue
            if bid >= entry + sl_dist * 2.5: pos = 0; trades2.append(2.5); wins2 += 1; continue
        else:
            if bid >= entry + sl_dist: pos = 0; trades2.append(-1); continue
            if bid <= entry - sl_dist * 2.5: pos = 0; trades2.append(2.5); wins2 += 1; continue
        if held >= 20:
            pnl = (closes[i] - entry) * pos
            trades2.append(pnl / sl_dist if sl_dist > 0 else 0)
            if pnl > 0: wins2 += 1
            pos = 0
        continue
    
    # Buy dip in uptrend
    if ema20[i] > ema50[i] and closes[i] < ema20[i] and closes[i] > ema50[i] and rsi[i] < 45:
        if closes[i] > closes[i-1]:  # bullish candle
            pos = 1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i
    # Sell rally in downtrend
    elif ema20[i] < ema50[i] and closes[i] > ema20[i] and closes[i] < ema50[i] and rsi[i] > 55:
        if closes[i] < closes[i-1]:  # bearish candle
            pos = -1; entry = closes[i]; sl_dist = atr[i] * 1.5; entry_bar = i

n2 = len(trades2)
wr2 = wins2/n2*100 if n2 > 0 else 0
r2 = sum(trades2)

# ── Strategy 3: Breakout from Compression ──
trades3 = []; wins3 = 0
pos = 0; entry = 0; sl_dist = 0; entry_bar = 0
for i in range(101, len(closes)-1):
    if atr[i] <= 0: continue
    if pos != 0:
        held = i - entry_bar
        if pos > 0:
            if closes[i] <= entry - sl_dist: pos = 0; trades3.append(-1); continue
            if closes[i] >= entry + sl_dist * 3.0: pos = 0; trades3.append(3.0); wins3 += 1; continue
        else:
            if closes[i] >= entry + sl_dist: pos = 0; trades3.append(-1); continue
            if closes[i] <= entry - sl_dist * 3.0: pos = 0; trades3.append(3.0); wins3 += 1; continue
        if held >= 12:
            pnl = (closes[i] - entry) * pos
            trades3.append(pnl / sl_dist if sl_dist > 0 else 0)
            if pnl > 0: wins3 += 1
            pos = 0
        continue
    
    # Detect compression
    hh = max(highs[i-20:i]); ll = min(lows[i-20:i])
    rng = hh - ll
    if rng < atr[i] * 0.5:  # compressed
        # Breakout up
        if closes[i] > hh and rsi[i] > 52:
            pos = 1; entry = closes[i]; sl_dist = atr[i] * 1.2; entry_bar = i
        # Breakout down
        elif closes[i] < ll and rsi[i] < 48:
            pos = -1; entry = closes[i]; sl_dist = atr[i] * 1.2; entry_bar = i

n3 = len(trades3)
wr3 = wins3/n3*100 if n3 > 0 else 0
r3 = sum(trades3)

# Dollar returns
pt_value = 1.0  # $1 per point per lot
lots = 2  # max at $22.75 / $7.83

print(f"\n  Account: $22.75 | Lots: {lots} | $/pt: ${pt_value}/lot | SL=1.5xATR | TP=2.5xSL")
print(f"  {'Strategy':<30} {'Trades':<8} {'T/Day':<7} {'WR%':<7} {'TotalR':<9} {'PnL':<10}")
print(f"  {'-'*71}")

for name, n, wr, total_r in [
    ("1. EMA Crossover M15", n1, wr1, r1),
    ("2. Pullback to EMA20 M15", n2, wr2, r2),
    ("3. Breakout from Compression M15", n3, wr3, r3)
]:
    # Approximate PnL
    avg_win = 2.5 * lots * pt_value if wr > 0 else 0
    avg_loss = 1.0 * lots * pt_value if wr < 100 else 0
    wins_count = int(n * wr / 100)
    losses_count = n - wins_count
    pnl = wins_count * avg_win - losses_count * avg_loss
    print(f"  {name:<30} {n:<8} {n/90:<7.1f} {wr:<7.1f} {total_r:<+9.2f} ${pnl:<+9.2f}")

# ═══════════════════════════════════════════════════════════════
# STEP INDEX: SESSION ANALYSIS
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*80)
print(" STEP INDEX: SESSION/UTC ANALYSIS")
print("="*80)

# Get hourly data and analyze by hour
bars_h = mt5.copy_rates_from("Step Index", mt5.TIMEFRAME_H1, datetime.now() - timedelta(days=30), 750)
if bars_h is not None:
    closes_h = np.array([b['close'] for b in bars_h])
    times_h = np.array([b['time'] for b in bars_h])
    
    hourly_vol = {}
    for j in range(1, len(bars_h)):
        h = datetime.fromtimestamp(times_h[j]).hour
        move = abs(closes_h[j] - closes_h[j-1])
        if h not in hourly_vol: hourly_vol[h] = []
        hourly_vol[h].append(move)
    
    print(f"\n  {'Hour(UTC)':<12} {'AvgMove':<10} {'MaxMove':<10} {'ActiveBars':<12} {'$Potential':<12}")
    print(f"  {'-'*56}")
    for h in range(24):
        if h in hourly_vol and hourly_vol[h]:
            avg = np.mean(hourly_vol[h])
            mx = np.max(hourly_vol[h])
            active = len([x for x in hourly_vol[h] if x > 0])
            dollar_pot = lots * avg * pt_value
            marker = " <-- BEST" if avg == max(np.mean(hourly_vol[hh]) for hh in hourly_vol if hourly_vol[hh]) else ""
            print(f"  {h:02d}:00 UTC    {avg:<10.1f} {mx:<10.1f} {active:<12} ${dollar_pot:<11.2f}{marker}")

mt5.shutdown()
