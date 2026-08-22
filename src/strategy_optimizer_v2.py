import MetaTrader5 as mt5
import math
import numpy as np

def analyze_strategy():
    mt5.initialize()
    
    for symbol in ['Volatility 100 Index', 'Volatility 75 Index']:
        print(f"\n{'='*60}")
        print(f"ANALYZING: {symbol}")
        print(f"{'='*60}")
        
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 25000)
        if rates is None or len(rates) == 0:
            continue
        
        closes = np.array([r['close'] for r in rates])
        
        # Calculate indicators
        log_ret = np.log(closes[1:] / closes[:-1])
        
        # EMA-20
        ema = np.zeros(len(closes))
        ema[0] = closes[0]
        alpha = 2.0 / 21.0
        for i in range(1, len(closes)):
            ema[i] = ema[i-1] * (1 - alpha) + closes[i] * alpha
        
        # Rolling sigma
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
        
        print(f"Data: {len(closes)} bars, {len(z_arr)} z-scores")
        print(f"Z-Score range: [{np.min(z_arr):.2f}, {np.max(z_arr):.2f}]")
        
        # === BACKTEST WITH SIMPLE P&L ===
        print("\n--- Backtesting Different Parameters ---")
        
        best_score = -float('inf')
        best_params = None
        
        for z_entry in [1.2, 1.5, 1.8, 2.0, 2.5]:
            for exit_z in [0.0, 0.3, 0.5, 0.8]:
                for stop_pct in [0.5, 1.0, 1.5, 2.0]:
                    trades = []
                    in_trade = False
                    entry_price = 0
                    direction = 0
                    entry_idx = 0
                    entry_sigma = 0
                    
                    for i in range(1, len(z_arr)):
                        z = z_arr[i]
                        price = closes[i + 60]
                        
                        if not in_trade:
                            # Entry: z crosses threshold
                            if abs(z) >= z_entry:
                                in_trade = True
                                entry_price = price
                                direction = 1 if z > 0 else -1  # Fade
                                entry_idx = i
                                entry_sigma = sigma[i + 60] if i + 60 < len(sigma) else 0.001
                        else:
                            # Calculate P&L as % of entry price
                            if direction > 0:  # Short
                                pnl_pct = (entry_price - price) / entry_price * 100
                            else:  # Long
                                pnl_pct = (price - entry_price) / entry_price * 100
                            
                            # Stop loss: if loss exceeds stop_pct%
                            if pnl_pct < -stop_pct:
                                trades.append({'pnl_pct': pnl_pct, 'exit': 'STOP'})
                                in_trade = False
                            # Take profit: z returns to exit_z
                            elif (direction > 0 and z <= exit_z) or (direction < 0 and z >= -exit_z):
                                trades.append({'pnl_pct': pnl_pct, 'exit': 'TARGET'})
                                in_trade = False
                    
                    if trades and len(trades) >= 20:
                        total_pnl = sum(t['pnl_pct'] for t in trades)
                        wins = [t for t in trades if t['pnl_pct'] > 0]
                        win_rate = len(wins) / len(trades) * 100
                        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
                        losses = [t for t in trades if t['pnl_pct'] <= 0]
                        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
                        
                        # Score: total P&L with risk adjustment
                        score = total_pnl - abs(avg_loss) * 0.5
                        
                        if score > best_score:
                            best_score = score
                            best_params = {
                                'z_entry': z_entry,
                                'exit_z': exit_z,
                                'stop_pct': stop_pct,
                                'trades': len(trades),
                                'win_rate': win_rate,
                                'total_pnl': total_pnl,
                                'avg_win': avg_win,
                                'avg_loss': avg_loss,
                                'trades_per_day': len(trades) / (len(closes) * 5 / 1440)
                            }
        
        if best_params:
            print(f"\n{'='*40}")
            print(f"OPTIMAL PARAMETERS FOR {symbol}")
            print(f"{'='*40}")
            print(f"Z-Entry:      {best_params['z_entry']}")
            print(f"Exit Z:       {best_params['exit_z']}")
            print(f"Stop Loss:    {best_params['stop_pct']}%")
            print(f"Trades:       {best_params['trades']}")
            print(f"Trades/Day:   {best_params['trades_per_day']:.1f}")
            print(f"Win Rate:     {best_params['win_rate']:.1f}%")
            print(f"Total P&L:    {best_params['total_pnl']:+.4f}%")
            print(f"Avg Win:      {best_params['avg_win']:+.4f}%")
            print(f"Avg Loss:     {best_params['avg_loss']:+.4f}%")
            
            # Calculate expectancy
            expectancy = (best_params['win_rate']/100 * best_params['avg_win'] + 
                         (1 - best_params['win_rate']/100) * best_params['avg_loss'])
            print(f"Expectancy:   {expectancy:+.4f}% per trade")
            
            # Project $30 growth
            print(f"\n--- Growth Projection ($30, 0.5% risk) ---")
            equity = 30.0
            for day in [7, 14, 30, 60, 90]:
                trades_per_day = best_params['trades_per_day']
                for _ in range(int(trades_per_day)):
                    risk = equity * 0.005  # 0.5% risk
                    pnl = risk * expectancy / best_params['avg_win'] * 100
                    equity += pnl
                print(f"  Day {day:3d}: ${equity:.2f}")
    
    mt5.shutdown()

if __name__ == '__main__':
    analyze_strategy()
