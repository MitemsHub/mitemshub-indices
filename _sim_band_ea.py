"""Replicate mql5 Tests/BandBackTests.mq5 exactly (in Python) and compare with
the real Python VolBandStrategy on the same R_75 M5 corpus.  If the replica
matches the real Python strategy, the MQL5 port is faithful and the tester
result is a data-window artifact; if they diverge, the port has a bug."""

import csv
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "src"))
sys.path.insert(0, os.path.join(_HERE, "mql5"))

from phase3_real_corpus_check import CORPUS_PATHS, load_m5_bars  # noqa: E402

# === EA config (input defaults) ==============================================
Z_ENTRY = 1.0
VOL_GATE = 1.3
EMA_PERIOD = 20
SIGMA_EMA_PERIOD = 30
WARMUP = 60
DRIFT_COOLDOWN = 10
DRIFT_DELTA = 0.002
STOP_MULT = 0.20
TARGET_MULT = 0.80
HOLD_SEC = 3600
BAR_SEC = 300
TRAIL_FRAC = 0.3

LAM = 0.94


def sim_ea(bars):
    """Exact port of the EA's OnInit loop."""
    trades = []
    cum_r = 0.0
    peak_r = 0.0
    max_dd = 0.0

    sigma = 0.0
    prev_sigma = 0.0
    sigma_ema = 0.0
    ema = 0.0
    prev_close = 0.0
    bars_seen = 0
    cooldown = 0
    drift_win = []
    last_bar_end = 0.0

    in_pos = False
    direction = 0
    entry = stop = target = mfe_r = planned_rr = risk = 0.0
    opened_at = 0

    alpha = 2.0 / (EMA_PERIOD + 1.0)
    sigma_alpha = 2.0 / (SIGMA_EMA_PERIOD + 1.0)

    def gap(open_time):
        nonlocal prev_close, ema, last_bar_end, drift_win, cooldown
        if last_bar_end > 0 and open_time > last_bar_end + max(3 * BAR_SEC, 600):
            prev_close = ema = ema
            drift_win = []
            cooldown = 0
            last_bar_end = open_time + BAR_SEC
            return True
        last_bar_end = open_time + BAR_SEC
        return False

    def observe_drift(log_ret):
        nonlocal drift_win, cooldown
        v = abs(log_ret) * 100.0
        drift_win.append(v)
        if len(drift_win) < 20:
            return
        if len(drift_win) > 20:
            drift_win = drift_win[-20:]
        m0 = sum(drift_win[:10]) / 10.0
        m1 = sum(drift_win[10:]) / 10.0
        s = sum((x - (m0 if i < 10 else m1)) ** 2 for i, x in enumerate(drift_win))
        pooled = math.sqrt(s / 20.0)
        thr = math.sqrt(2.0 * math.log(2.0 / DRIFT_DELTA) / 10.0) * pooled
        if abs(m0 - m1) > thr:
            cooldown = 0
            drift_win = []

    def close_pos(bar_open, high, low, close, open_time):
        nonlocal trades, cum_r, peak_r, max_dd, in_pos, mfe_r
        risk_d = risk if risk > 0 else entry * 0.001
        mfe = (high - entry) / risk_d if direction > 0 else (entry - low) / risk_d
        mfe_r = max(mfe_r, mfe)
        trail = mfe_r >= TRAIL_FRAC * planned_rr
        eff_stop = entry if trail else stop
        expired = open_time + BAR_SEC >= opened_at + HOLD_SEC
        if direction > 0:
            stop_hit = low <= eff_stop
            target_hit = high >= target
        else:
            stop_hit = high >= eff_stop
            target_hit = low <= target
        if stop_hit and target_hit:
            exit_price = eff_stop
        elif stop_hit:
            exit_price = eff_stop
        elif target_hit:
            exit_price = target
        elif expired:
            exit_price = close
        else:
            return False
        rr = (exit_price - entry) / risk_d if direction > 0 else (entry - exit_price) / risk_d
        trades.append((direction, entry, exit_price, rr, mfe_r))
        cum_r += rr
        peak_r = max(peak_r, cum_r)
        max_dd = max(max_dd, peak_r - cum_r)
        in_pos = False
        mfe_r = 0.0
        return True

    for k, b in enumerate(bars):
        t = b[0]
        close = b[4]
        if prev_close <= 0.0:
            prev_close = close
            ema = close
            last_bar_end = t + BAR_SEC
            continue
        if gap(t):
            continue
        log_ret = math.log(close / prev_close)
        prev_close = close
        prev_sigma = sigma
        sigma = math.sqrt(LAM * sigma * sigma + 0.06 * log_ret * log_ret)
        sigma_ema = sigma if sigma_ema <= 0 else sigma_ema * (1 - sigma_alpha) + sigma * sigma_alpha
        ema = ema * (1 - alpha) + close * alpha
        bars_seen += 1
        observe_drift(log_ret)
        if cooldown < DRIFT_COOLDOWN:
            cooldown += 1

        if in_pos:
            if close_pos(b[1], b[2], b[3], close, t):
                pass
        if in_pos:
            continue
        if bars_seen < WARMUP:
            continue
        if sigma_ema <= 0 or prev_sigma <= 0:
            continue
        if cooldown < DRIFT_COOLDOWN:
            continue
        if not (prev_sigma > VOL_GATE * sigma_ema):
            continue
        z = math.log(close / ema) / prev_sigma
        if z >= Z_ENTRY:
            direction = -1
        elif z <= -Z_ENTRY:
            direction = 1
        else:
            continue
        sigma_h = prev_sigma * math.sqrt(max(1, round(HOLD_SEC / BAR_SEC)))
        stop_dist = STOP_MULT * sigma_h
        target_dist = TARGET_MULT * sigma_h
        if direction > 0:
            stop = close * (1 - stop_dist)
            target = close * (1 + target_dist)
        else:
            stop = close * (1 + stop_dist)
            target = close * (1 - target_dist)
        rr = target_dist / stop_dist
        if rr < 2.0:
            continue
        if abs(close - stop) / close > 0.015:
            continue
        entry = close
        risk = abs(entry - stop)
        planned_rr = abs(target - entry) / (risk if risk > 0 else entry * 0.001)
        mfe_r = 0.0
        opened_at = t + BAR_SEC
        in_pos = True

    return trades, cum_r, max_dd


def main():
    bars = load_m5_bars(CORPUS_PATHS)
    print(f"corpus: {len(bars)} M5 bars")
    trades, cum_r, max_dd = sim_ea(bars)
    n = len(trades)
    if n == 0:
        print("SIM: 0 trades")
        return
    wins = sum(1 for t in trades if t[3] > 0)
    exp = cum_r / n
    long_n = sum(1 for t in trades if t[0] > 0)
    print(f"SIM: trades={n} wins={wins} hit={100.0*wins/n:.1f}% "
          f"expectancy={exp:+.3f}R maxDD={max_dd:.2f}R long={long_n}")
    for t in trades[:5]:
        d = "BUY " if t[0] > 0 else "SELL"
        print(f"  {d} {t[1]:.1f} -> {t[2]:.1f} R={t[3]:+.2f} MFE={t[4]:.2f}")


if __name__ == "__main__":
    main()
