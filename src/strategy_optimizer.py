import MetaTrader5 as mt5
import math
import numpy as np
import json
from datetime import datetime

def analyze_strategy_optimization():
    mt5.initialize()
    
    results = {}
    
    for symbol in ['Volatility 100 Index', 'Volatility 75 Index']:
        print(f"\n{'='*60}")
        print(f"ANALYZING: {symbol}")
        print(f"{'='*60}")
        
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 25000)
        if rates is None or len(rates) == 0:
            print(f"No data for {symbol}")
            continue
        
        closes = np.array([r['close'] for r in rates])
        times = np.array([r['time'] for r in rates])
        
        # Calculate indicators
        log_ret = np.log(closes[1:] / closes[:-1])
        
        # EMA-20
        ema = np.zeros(len(closes))
        ema[0] = closes[0]
        alpha = 2.0 / 21.0
        for i in range(1, len(closes)):
            ema[i] = ema[i-1] * (1 - alpha) + closes[i] * alpha
        
        # Rolling sigma (30-bar EMA)
        sigma = np.zeros(len(closes))
        sigma[0] = abs(log_ret[0]) if len(log_ret) > 0 else 0.001
        sigma_alpha = 2.0 / 31.0
        for i in range(1, len(log_ret)):
            sigma[i] = sigma[i-1] * (1 - sigma_alpha) + abs(log_ret[i]) * sigma_alpha
            if sigma[i] < 1e-6:
                sigma[i] = 1e-6
        
        # Calculate z-scores
        z_scores = []
        for i in range(60, len(closes)):
            s = sigma[i-1] if i > 0 else 0.001
            if s < 1e-6:
                s = 1e-6
            z = math.log(closes[i] / ema[i]) / s
            z_scores.append(z)
        
        z_arr = np.array(z_scores)
        
        # === BACKTEST DIFFERENT PARAMETERS ===
        print(f"\nBacktesting {len(z_arr)} bars...")
        
        # Test different z-entry thresholds
        print("\n--- Z-Entry Threshold Analysis ---")
        for z_entry in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5]:
            trades = []
            in_trade = False
            entry_price = 0
            direction = 0
            entry_idx = 0
            
            for i in range(1, len(z_arr)):
                z = z_arr[i]
                
                if not in_trade:
                    # Entry condition
                    if abs(z) >= z_entry:
                        in_trade = True
                        entry_price = closes[i + 60]
                        direction = 1 if z > 0 else -1  # Fade the extension
                        entry_idx = i
                
                else:
                    # Exit condition: z returns to 0 (mean reversion)
                    current_price = closes[i + 60]
                    
                    # Calculate P&L in R units
                    risk = abs(entry_price - closes[entry_idx + 60 + (0 if direction > 0 else 1)])
                    if risk < 1e-12:
                        risk = 1e-12
                    
                    if direction > 0:  # Short entry (fading upward extension)
                        pnl_r = (entry_price - current_price) / risk
                    else:  # Long entry (fading downward extension)
                        pnl_r = (current_price - entry_price) / risk
                    
                    # Exit when z returns to 0 or hits stop
                    if abs(z) < 0.5 or pnl_r < -2 or pnl_r > 4:
                        trades.append({
                            'entry_z': z_arr[entry_idx],
                            'exit_z': z,
                            'pnl_r': pnl_r,
                            'bars_held': i - entry_idx
                        })
                        in_trade = False
            
            if trades:
                wins = [t for t in trades if t['pnl_r'] > 0]
                losses = [t for t in trades if t['pnl_r'] <= 0]
                total_pnl = sum(t['pnl_r'] for t in trades)
                win_rate = len(wins) / len(trades) * 100
                avg_win = np.mean([t['pnl_r'] for t in wins]) if wins else 0
                avg_loss = np.mean([t['pnl_r'] for t in losses]) if losses else 0
                profit_factor = abs(sum(t['pnl_r'] for t in wins) / sum(t['pnl_r'] for t in losses)) if losses and sum(t['pnl_r'] for t in losses) != 0 else float('inf')
                avg_bars = np.mean([t['bars_held'] for t in trades])
                
                print(f"  z_entry={z_entry:.1f}: {len(trades)} trades, "
                      f"WR={win_rate:.1f}%, "
                      f"Total R={total_pnl:+.2f}, "
                      f"PF={profit_factor:.2f}, "
                      f"Avg Win={avg_win:+.2f}R, "
                      f"Avg Loss={avg_loss:+.2f}R, "
                      f"Avg Hold={avg_bars:.0f} bars")
        
        # === ANALYZE OPTIMAL EXIT ===
        print("\n--- Optimal Exit Analysis (using z_entry=1.8) ---")
        
        for exit_z in [0.0, 0.2, 0.5, 0.8, 1.0]:
            trades = []
            in_trade = False
            entry_price = 0
            direction = 0
            entry_idx = 0
            
            for i in range(1, len(z_arr)):
                z = z_arr[i]
                
                if not in_trade:
                    if abs(z) >= 1.8:
                        in_trade = True
                        entry_price = closes[i + 60]
                        direction = 1 if z > 0 else -1
                        entry_idx = i
                else:
                    current_price = closes[i + 60]
                    risk = abs(entry_price - closes[entry_idx + 60 + (0 if direction > 0 else 1)])
                    if risk < 1e-12:
                        risk = 1e-12
                    
                    if direction > 0:
                        pnl_r = (entry_price - current_price) / risk
                    else:
                        pnl_r = (current_price - entry_price) / risk
                    
                    # Exit when z returns to exit_z
                    if (direction > 0 and z <= exit_z) or (direction < 0 and z >= -exit_z) or pnl_r < -2:
                        trades.append({
                            'pnl_r': pnl_r,
                            'bars_held': i - entry_idx
                        })
                        in_trade = False
            
            if trades:
                wins = [t for t in trades if t['pnl_r'] > 0]
                total_pnl = sum(t['pnl_r'] for t in trades)
                win_rate = len(wins) / len(trades) * 100
                avg_bars = np.mean([t['bars_held'] for t in trades])
                
                print(f"  exit_z={exit_z:.1f}: {len(trades)} trades, "
                      f"WR={win_rate:.1f}%, "
                      f"Total R={total_pnl:+.2f}, "
                      f"Avg Hold={avg_bars:.0f} bars")
        
        # === ANALYZE STOP LOSS ===
        print("\n--- Stop Loss Analysis (z_entry=1.8, exit_z=0.5) ---")
        
        for stop_r in [1.0, 1.5, 2.0, 2.5, 3.0]:
            trades = []
            in_trade = False
            entry_price = 0
            direction = 0
            entry_idx = 0
            
            for i in range(1, len(z_arr)):
                z = z_arr[i]
                
                if not in_trade:
                    if abs(z) >= 1.8:
                        in_trade = True
                        entry_price = closes[i + 60]
                        direction = 1 if z > 0 else -1
                        entry_idx = i
                else:
                    current_price = closes[i + 60]
                    risk = abs(entry_price - closes[entry_idx + 60 + (0 if direction > 0 else 1)])
                    if risk < 1e-12:
                        risk = 1e-12
                    
                    if direction > 0:
                        pnl_r = (entry_price - current_price) / risk
                    else:
                        pnl_r = (current_price - entry_price) / risk
                    
                    # Exit conditions
                    if pnl_r < -stop_r or ((direction > 0 and z <= 0.5) or (direction < 0 and z >= -0.5)):
                        trades.append({
                            'pnl_r': pnl_r,
                            'exit_type': 'STOP' if pnl_r < -stop_r else 'TARGET'
                        })
                        in_trade = False
            
            if trades:
                wins = [t for t in trades if t['pnl_r'] > 0]
                losses = [t for t in trades if t['pnl_r'] <= 0]
                total_pnl = sum(t['pnl_r'] for t in trades)
                win_rate = len(wins) / len(trades) * 100
                stop_exits = len([t for t in trades if t['exit_type'] == 'STOP'])
                
                print(f"  stop={stop_r:.1f}R: {len(trades)} trades, "
                      f"WR={win_rate:.1f}%, "
                      f"Total R={total_pnl:+.2f}, "
                      f"Stop Exits={stop_exits}")
        
        # === FIND OPTIMAL PARAMETERS ===
        print("\n--- OPTIMAL PARAMETERS ---")
        
        best_pnl = -float('inf')
        best_params = {}
        
        for z_entry in [1.2, 1.5, 1.8, 2.0]:
            for exit_z in [0.0, 0.3, 0.5, 0.8]:
                for stop_r in [1.5, 2.0, 2.5]:
                    trades = []
                    in_trade = False
                    entry_price = 0
                    direction = 0
                    entry_idx = 0
                    
                    for i in range(1, len(z_arr)):
                        z = z_arr[i]
                        
                        if not in_trade:
                            if abs(z) >= z_entry:
                                in_trade = True
                                entry_price = closes[i + 60]
                                direction = 1 if z > 0 else -1
                                entry_idx = i
                        else:
                            current_price = closes[i + 60]
                            risk = abs(entry_price - closes[entry_idx + 60 + (0 if direction > 0 else 1)])
                            if risk < 1e-12:
                                risk = 1e-12
                            
                            if direction > 0:
                                pnl_r = (entry_price - current_price) / risk
                            else:
                                pnl_r = (current_price - entry_price) / risk
                            
                            if pnl_r < -stop_r or ((direction > 0 and z <= exit_z) or (direction < 0 and z >= -exit_z)):
                                trades.append({'pnl_r': pnl_r})
                                in_trade = False
                    
                    if trades and len(trades) >= 10:
                        total_pnl = sum(t['pnl_r'] for t in trades)
                        win_rate = len([t for t in trades if t['pnl_r'] > 0]) / len(trades) * 100
                        
                        # Score: prioritize total P&L with win rate bonus
                        score = total_pnl + (win_rate - 50) * 0.5
                        
                        if score > best_pnl:
                            best_pnl = score
                            best_params = {
                                'z_entry': z_entry,
                                'exit_z': exit_z,
                                'stop_r': stop_r,
                                'trades': len(trades),
                                'win_rate': win_rate,
                                'total_pnl': total_pnl
                            }
        
        if best_params:
            print(f"  Best: z_entry={best_params['z_entry']}, "
                  f"exit_z={best_params['exit_z']}, "
                  f"stop={best_params['stop_r']}R")
            print(f"  Result: {best_params['trades']} trades, "
                  f"WR={best_params['win_rate']:.1f}%, "
                  f"Total R={best_params['total_pnl']:+.2f}")
        
        results[symbol] = best_params
    
    mt5.shutdown()
    return results

if __name__ == '__main__':
    results = analyze_strategy_optimization()
    print("\n" + "="*60)
    print("SUMMARY OF OPTIMAL PARAMETERS")
    print("="*60)
    for symbol, params in results.items():
        print(f"\n{symbol}:")
        if params:
            print(f"  Z-Entry: {params['z_entry']}")
            print(f"  Exit Z: {params['exit_z']}")
            print(f"  Stop: {params['stop_r']}R")
            print(f"  Trades: {params['trades']}")
            print(f"  Win Rate: {params['win_rate']:.1f}%")
            print(f"  Total P&L: {params['total_pnl']:+.2f}R")
