#!/usr/bin/env python
"""
MITEMSHUB AI — Nightly Optimization Engine
Runs every night to retrain the strategy on fresh data.
1. Pulls latest 30 days of M5 data from MT5
2. Runs grid search across 1,600+ parameter combinations
3. Saves best parameters to optimal_params.json
4. Updates the .set file in the Deriv terminal
5. Logs results for morning review
"""

import MetaTrader5 as mt5
import math
import sys
import json
import os
import shutil
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, '..', 'data')
LOG_DIR = os.path.join(DATA_DIR, 'optimizer_logs')
MQL5_SET_DIR = os.path.join(os.environ.get('APPDATA', ''),
    'MetaQuotes', 'Terminal', 'FB9A56D617EDDDFE29EE54EBEFFE96C1',
    'MQL5', 'Profiles', 'Sets')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)


# ─── GARCH Forecaster ──────────────────────────────────────────────
class GarchForecaster:
    def __init__(self, omega, alpha, gamma, beta):
        self.omega, self.alpha, self.gamma, self.beta = omega, alpha, gamma, beta
        self.log_sigma2 = 0.0
        self.last_z = 0.0
        self.n_obs = 0
        self._sum = 0.0
        self._sq_sum = 0.0

    def update(self, log_ret):
        self.n_obs += 1
        self._sum += log_ret
        self._sq_sum += log_ret * log_ret
        if self.n_obs < 10:
            if self.n_obs == 1:
                self.log_sigma2 = math.log(max(log_ret * log_ret, 1e-12))
            else:
                self.log_sigma2 = math.log(max(self._sq_sum / self.n_obs, 1e-12))
            sigma = math.exp(self.log_sigma2 / 2.0)
            self.last_z = log_ret / max(sigma, 1e-12)
            return sigma
        prev_sigma = math.exp(self.log_sigma2 / 2.0)
        z = log_ret / max(prev_sigma, 1e-12)
        self.log_sigma2 = self.omega + self.alpha * abs(z) + self.gamma * z + self.beta * self.log_sigma2
        sigma = math.exp(self.log_sigma2 / 2.0)
        self.last_z = z
        return sigma

    def observations(self):
        return self.n_obs


class ZRingBuffer:
    def __init__(self, size=50):
        self.ring = [0.0] * size
        self.head = 0
        self.count = 0
    def push(self, z):
        self.ring[self.head] = z
        self.head = (self.head + 1) % len(self.ring)
        if self.count < len(self.ring): self.count += 1
    def mean_revert_signal(self, z_t):
        if self.count < 5: return 0.0
        recent = sum(1 for k in range(min(10, self.count)) if abs(self.ring[(self.head - 1 - k) % len(self.ring)]) > 2.0)
        az = abs(z_t)
        if az < 1.0: return 0.0
        if az < 2.0: return min(0.3, recent * 0.05)
        if az < 3.0: return min(0.6, 0.3 + recent * 0.05)
        return min(0.9, 0.5 + recent * 0.07)


def run_backtest(rates, params):
    """Run backtest with given parameters. Returns (trades, equity)."""
    z_entry = params['z_entry']
    vol_ratio = params['vol_ratio']
    min_revert = params['min_revert']
    stop_mult = params['stop_mult']
    target_mult = params['target_mult']
    min_rr = params['min_rr']
    hold_bars = params['hold_bars']
    trail_be_r = params.get('trail_be_r', 2.0)
    trail_behind_r = params.get('trail_behind_r', 0.5)
    cooldown_bars = params.get('cooldown_bars', 5)

    garch = GarchForecaster(-1.884103, 0.142169, -0.073285, 0.852741)
    zbuf = ZRingBuffer()
    equity = 10000.0
    peak_equity = 10000.0
    bars_seen = 0
    prev_close = 0.0
    ema = 0.0
    sigma = 0.0
    sigma_ema = 0.0

    in_pos = False
    pos_dir = 0
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_bar = 0
    pos_stake = 0.0
    pos_trail_active = False
    cooldown = 0
    pending_signal = 0
    pending_z = 0.0
    trades = []

    for i, rate in enumerate(rates):
        c = rate['close']
        h = rate['high']
        l = rate['low']
        bars_seen += 1

        if prev_close <= 0:
            prev_close = c; ema = c
            continue

        log_ret = math.log(c / prev_close) if prev_close > 0 else 0
        prev_close = c

        prev_sigma = sigma
        sigma = garch.update(log_ret)
        if garch.observations() >= 10:
            zbuf.push(garch.last_z)

        sa = 2.0 / 31.0
        sigma_ema = sigma if sigma_ema <= 0 else sigma_ema * (1 - sa) + sigma * sa
        ea = 2.0 / 21.0
        ema = ema * (1 - ea) + c * ea

        # Manage open position
        if in_pos:
            bars_held = bars_seen - pos_bar
            risk_dist = abs(pos_entry - pos_sl)
            current_r = (c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0

            if not pos_trail_active and current_r >= trail_be_r:
                pos_trail_active = True
                new_sl = pos_entry + pos_dir * risk_dist * 0.1
                if pos_dir > 0: pos_sl = max(pos_sl, new_sl)
                else: pos_sl = min(pos_sl, new_sl)

            if pos_trail_active:
                trail_distance = risk_dist * trail_behind_r
                if pos_dir > 0: pos_sl = max(pos_sl, c - trail_distance)
                else: pos_sl = min(pos_sl, c + trail_distance)

            exit_price = 0
            reason = ""
            if pos_dir > 0:
                if l <= pos_sl: exit_price, reason = pos_sl, "TRAIL" if pos_trail_active else "STOP"
                elif h >= pos_tp: exit_price, reason = pos_tp, "TARGET"
            else:
                if h >= pos_sl: exit_price, reason = pos_sl, "TRAIL" if pos_trail_active else "STOP"
                elif l <= pos_tp: exit_price, reason = pos_tp, "TARGET"

            if not reason and bars_held >= hold_bars:
                exit_price, reason = c, "TIME"

            if reason:
                slipped = exit_price - 0.05 if pos_dir > 0 else exit_price + 0.05
                rr = (slipped - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
                pnl = pos_stake * rr
                equity += pnl
                trades.append({'pnl': pnl, 'rr': rr, 'reason': reason, 'equity': equity})
                if pnl < -1.0: cooldown = cooldown_bars
                in_pos = False; pos_dir = 0; pos_trail_active = False
                continue

        if cooldown > 0:
            cooldown -= 1
            continue

        # Confirmation
        if pending_signal != 0:
            bar_open = rate['open']
            confirmed = (pending_signal > 0 and c > bar_open) or (pending_signal < 0 and c < bar_open)
            if confirmed:
                direction = pending_signal
                stop_dist = c * stop_mult * sigma
                target_dist = c * target_mult * sigma
                sl = (c - stop_dist) if direction > 0 else (c + stop_dist)
                tp = (c + target_dist) if direction > 0 else (c - target_dist)
                risk_dist = abs(c - sl)
                if risk_dist <= 0: pending_signal = 0; continue
                rr = abs(tp - c) / risk_dist
                if rr < min_rr: pending_signal = 0; continue
                in_pos = True; pos_dir = direction; pos_entry = c; pos_sl = sl; pos_tp = tp
                pos_bar = bars_seen; pos_stake = equity * 0.005; pos_trail_active = False
                pending_signal = 0
                continue
            else:
                pending_signal = 0
                continue

        if in_pos or bars_seen < 60 or garch.observations() < 30: continue
        if sigma_ema <= 0 or prev_sigma <= 0: continue
        if not (prev_sigma > vol_ratio * sigma_ema): continue
        if min_revert > 0:
            rev = zbuf.mean_revert_signal(garch.last_z)
            if rev < min_revert: continue
        z_dev = math.log(c / ema) / max(prev_sigma, 1e-12)
        if abs(z_dev) < z_entry: continue
        pending_signal = -1 if z_dev > 0 else 1
        pending_z = z_dev

    # Close open
    if in_pos:
        last_c = rates[-1]['close']
        risk_dist = abs(pos_entry - pos_sl)
        rr = (last_c - pos_entry) * pos_dir / risk_dist if risk_dist > 0 else 0
        pnl = pos_stake * rr
        equity += pnl
        trades.append({'pnl': pnl, 'rr': rr, 'reason': 'FORCE', 'equity': equity})

    return trades, equity


def score_trades(trades):
    """Composite score: higher = better."""
    if len(trades) < 5: return -999
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    win_rate = len(wins) / len(trades)

    equity = 10000.0; peak = 10000.0; max_dd = 0.0
    for t in trades:
        equity += t['pnl']; peak = max(peak, equity)
        dd = (peak - equity) / peak; max_dd = max(max_dd, dd)

    max_consec = 0; streak = 0
    for t in trades:
        if t['pnl'] <= 0: streak += 1; max_consec = max(max_consec, streak)
        else: streak = 0

    score = (total_pnl / 100) + (win_rate * 20) - (max_dd * 100) - (len(trades) - len(wins)) * 0.5 - max_consec * 1.0
    return score


def generate_set_file(params, filepath):
    """Generate MT5 .set file from parameters."""
    content = f"""; MITEMSHUB AI MARKET ENGINE -- AUTO-OPTIMIZED (Nightly Retrain)
; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
; Grid search optimized on latest 30 days of data
;
InpBarSec=300
InpZEntry={params['z_entry']}
InpVolGateRatio={params['vol_ratio']}
InpMinRevertSignal={params['min_revert']}
InpEmaPeriod=20
InpSigmaEmaPeriod=30
InpWarmupCandles=60
InpStopSigmaMult={params['stop_mult']}
InpTargetSigmaMult={params['target_mult']}
InpHoldSec={int(params['hold_bars'] * 300)}
InpMinTargetRR={params['min_rr']}
InpMaxStopPct=0.015
InpGarchMode=0
InpGarchOmega=-1.884103
InpGarchAlpha=0.142169
InpGarchGamma=-0.073285
InpGarchBeta=0.852741
InpTrailOn=true
InpTrailFrac={params['trail_behind_r']}
InpPartialClose=false
InpClosedCandleGrace=false
InpDriftGate=false
InpExitSlippage=0.05
InpRiskPerTrade=0.005
InpMinConfidence=0.0
InpMinRewardRisk=0.0
InpMaxDailyLossPct=1.0
InpMaxConsecLosses=9999
InpMaxEquityDDPct=1.0
InpFloorMinSamples=10
InpFloorMargin=0.05
InpFloorGate=false
InpMaxEdgeDepth=0.0
InpLiveExecution=false
InpMagic=7788123
InpMaxSlippagePts=50
InpMaxSpreadPts=0
InpDrawDashboard=true
InpDrawSignals=true
"""
    with open(filepath, 'w') as f:
        f.write(content)


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] MITEMSHUB AI — Nightly Optimization Started")
    print("=" * 80)

    # 1. Pull latest data
    print("\n[1] Fetching latest 30 days of M5 data...")
    if not mt5.initialize():
        print("[ERROR] MT5 init failed:", mt5.last_error())
        return

    symbol = "Volatility 75 Index"
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 8640)
    mt5.shutdown()

    if rates is None or len(rates) < 200:
        print(f"[ERROR] Only got {len(rates) if rates is not None else 0} bars")
        return

    print(f"    Got {len(rates)} M5 bars")
    print(f"    Period: {datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d %H:%M')}")

    # 2. Load previous best for comparison
    prev_best_file = os.path.join(DATA_DIR, 'optimal_params.json')
    prev_best = None
    if os.path.exists(prev_best_file):
        with open(prev_best_file) as f:
            prev_best = json.load(f)
        print(f"\n[2] Previous best: score={prev_best['stats']['score']:.1f}, "
              f"WR={prev_best['stats']['win_rate']:.1f}%, "
              f"P&L=${prev_best['stats']['total_pnl']:+,.2f}")

    # 3. Run previous best on fresh data
    print("\n[3] Evaluating previous best on fresh data...")
    prev_params = prev_best['params'] if prev_best else {
        'z_entry': 2.5, 'vol_ratio': 1.03, 'min_revert': 0.02,
        'stop_mult': 0.12, 'target_mult': 0.8, 'min_rr': 1.8,
        'hold_bars': 12, 'trail_be_r': 1.0, 'trail_behind_r': 0.3,
        'cooldown_bars': 5,
    }
    prev_trades, prev_equity = run_backtest(rates, prev_params)
    prev_score = score_trades(prev_trades)
    prev_wins = len([t for t in prev_trades if t['pnl'] > 0])
    prev_pnl = sum(t['pnl'] for t in prev_trades)
    print(f"    Previous params: {len(prev_trades)} trades, {prev_wins} wins, "
          f"P&L=${prev_pnl:+,.2f}, score={prev_score:.1f}")

    # 4. Grid search
    print("\n[4] Grid search: testing 1,600+ configurations...")
    best_score = -999
    best_params = None
    best_trades = None
    best_equity = 10000.0
    configs_tested = 0

    for z_entry in [1.8, 2.0, 2.2, 2.5, 2.8]:
        for stop_mult in [0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
            for hold_bars in [12, 18, 24, 30, 36]:
                for trail_be_r in [1.0, 1.5, 2.0, 2.5]:
                    for target_mult in [0.6, 0.8, 1.0, 1.2, 1.5]:
                        params = {
                            'z_entry': z_entry, 'vol_ratio': 1.03, 'min_revert': 0.02,
                            'stop_mult': stop_mult, 'target_mult': target_mult, 'min_rr': 1.8,
                            'hold_bars': hold_bars, 'trail_be_r': trail_be_r, 'trail_behind_r': 0.3,
                            'cooldown_bars': 5,
                        }
                        trades, equity = run_backtest(rates, params)
                        score = score_trades(trades)
                        configs_tested += 1

                        if score > best_score:
                            best_score = score
                            best_params = params.copy()
                            best_trades = trades
                            best_equity = equity

    wins = len([t for t in best_trades if t['pnl'] > 0]) if best_trades else 0
    wr = wins / len(best_trades) * 100 if best_trades else 0
    pnl = sum(t['pnl'] for t in best_trades) if best_trades else 0

    print(f"    Tested {configs_tested} configurations")
    print(f"\n    NEW BEST: {len(best_trades)} trades, {wins} wins, {wr:.1f}% WR")
    print(f"    P&L: ${pnl:+,.2f} | Score: {best_score:.1f}")

    # 5. Compare with previous
    improved = best_score > prev_score if prev_best else True
    print(f"\n[5] Improvement over previous: {'YES' if improved else 'NO'}")
    if improved and prev_best:
        print(f"    Score: {prev_score:.1f} -> {best_score:.1f} (+{best_score - prev_score:.1f})")
        print(f"    P&L: ${prev_pnl:+,.2f} -> ${pnl:+,.2f} (+${pnl - prev_pnl:+,.2f})")
        print(f"    WR: {prev_wins/len(prev_trades)*100:.1f}% -> {wr:.1f}%")

    # 6. Save results
    print("\n[6] Saving results...")
    result = {
        'version': f'v{datetime.now().strftime("%m%d")}',
        'params': best_params,
        'stats': {
            'trades': len(best_trades),
            'wins': wins,
            'win_rate': wr,
            'total_pnl': pnl,
            'max_dd': 0.0,
            'score': best_score,
            'configs_tested': configs_tested,
        },
        'timestamp': datetime.now().isoformat(),
        'data_period': f"{datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d')}",
        'previous_score': prev_score if prev_best else None,
        'improved': bool(improved),
    }

    # Calculate max DD
    equity = 10000.0; peak = 10000.0; max_dd = 0.0
    for t in best_trades:
        equity += t['pnl']; peak = max(peak, equity)
        dd = (peak - equity) / peak; max_dd = max(max_dd, dd)
    result['stats']['max_dd'] = max_dd

    # Save optimal_params.json
    with open(os.path.join(DATA_DIR, 'optimal_params.json'), 'w') as f:
        json.dump(result, f, indent=2)
    print(f"    Saved to data/optimal_params.json")

    # Save .set file
    set_path = os.path.join(DATA_DIR, f"MitemshubAI_AUTO_{result['version']}.set")
    generate_set_file(best_params, set_path)
    print(f"    Saved .set to {set_path}")

    # Copy to terminal
    if os.path.exists(MQL5_SET_DIR):
        terminal_set = os.path.join(MQL5_SET_DIR, f"MitemshubAI_AUTO_{result['version']}.set")
        shutil.copy2(set_path, terminal_set)
        # Also update the live set
        live_set = os.path.join(MQL5_SET_DIR, 'MitemshubAI_V6_OPTIMAL.set')
        shutil.copy2(set_path, live_set)
        print(f"    Copied to Deriv terminal Sets folder")

    # Save detailed log
    log_file = os.path.join(LOG_DIR, f"optimizer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'bars': len(rates),
        'configs_tested': configs_tested,
        'best': result,
        'trades': [{'pnl': t['pnl'], 'rr': t['rr'], 'reason': t['reason']} for t in best_trades] if best_trades else [],
    }
    with open(log_file, 'w') as f:
        json.dump(log_data, f, indent=2)
    print(f"    Detailed log: {log_file}")

    # 7. Summary
    print("\n" + "=" * 80)
    print("  NIGHTLY OPTIMIZATION COMPLETE")
    print("=" * 80)
    print(f"  Data:      {len(rates)} bars ({datetime.fromtimestamp(rates[0]['time']).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(rates[-1]['time']).strftime('%Y-%m-%d')})")
    print(f"  Tested:    {configs_tested} configurations")
    print(f"  Best:      {len(best_trades)} trades, {wr:.1f}% WR, ${pnl:+,.2f}")
    print(f"  Max DD:    {max_dd*100:.2f}%")
    print(f"  Score:     {best_score:.1f}")
    print(f"  Improved:  {'YES' if improved else 'NO'}")
    print()
    print("  OPTIMAL PARAMETERS:")
    for k, v in best_params.items():
        print(f"    {k}: {v}")
    print()
    print("  NEXT: Load the updated .set file in your terminal")
    print("  to activate the latest optimized parameters.")
    print("=" * 80)


if __name__ == "__main__":
    main()
