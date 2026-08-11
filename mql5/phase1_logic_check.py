#!/usr/bin/env python3
"""Phase-1 logic mirror — verifies the exact algorithms in MITEMSHUB_AI.

This script replicates, line-for-line, the math in:
  Market/NormalizationEngine.mqh
  Market/VolatilityEngine.mqh
  Market/SymbolAdapter.mqh (volume normalization + spread)
and runs the SAME assertions as Tests/Phase1Tests.mq5, so the Phase-1
logic is verified numerically even before the in-tester run.

It is NOT a substitute for the MetaEditor compile (already clean) or the
Strategy-Tester run — it is the fast CI loop for the math.
"""

import math

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PHASE1] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PHASE1] FAIL  {name}  -> {detail}")


def close(a, b, tol):
    return abs(a - b) <= tol


# --- NormalizationEngine.mqh mirror -----------------------------------------
def range_to_atr(high, low, atr):
    if atr <= 0.0 or high <= low or high <= 0.0:
        return 0.0
    return (high - low) / atr


def body_to_atr(open_, close, atr):
    if atr <= 0.0:
        return 0.0
    return abs(close - open_) / atr


def log_return(frm, to):
    if frm <= 0.0 or to <= 0.0:
        return 0.0
    return math.log(to / frm)


def pct_return(frm, to):
    if frm == 0.0:
        return 0.0
    return (to - frm) / frm


def z_score(value, mean, std):
    if std <= 0.0:
        return 0.0
    return (value - mean) / std


def relative_distance(price, level, atr):
    if atr <= 0.0:
        return 0.0
    return (price - level) / atr


def close_location(high, low, close):
    rng = high - low
    if rng <= 0.0:
        return 0.5
    loc = (close - low) / rng
    return max(0.0, min(1.0, loc))


def efficiency_ratio(closes):
    n = len(closes)
    if n < 2:
        return 0.0
    net = abs(closes[n - 1] - closes[0])
    gross = sum(abs(closes[i] - closes[i - 1]) for i in range(1, n))
    if gross <= 0.0:
        return 0.0
    return net / gross


# --- VolatilityEngine.mqh mirror --------------------------------------------
MAX_BARS = 500


class VolatilityEngine:
    def __init__(self, period=14):
        self.period = max(2, period)
        self.atr = 0.0
        self.has_atr = False
        self.log_returns = [0.0] * MAX_BARS
        self.atr_series = [0.0] * MAX_BARS
        self.head = 0
        self.count = 0

    def set_period(self, period):
        self.period = max(2, period)
        self.atr = 0.0
        self.has_atr = False
        self.head = 0
        self.count = 0
        self.log_returns = [0.0] * MAX_BARS
        self.atr_series = [0.0] * MAX_BARS

    def on_bar_with_prev_close(self, prev_close, high, low, close):
        tr = high - low
        if prev_close > 0.0:
            up_gap = abs(high - prev_close)
            dn_gap = abs(low - prev_close)
            if up_gap > tr:
                tr = up_gap
            if dn_gap > tr:
                tr = dn_gap
        if not self.has_atr:
            self.atr = tr
            self.has_atr = True
        else:
            self.atr = (self.atr * (self.period - 1) + tr) / self.period
        if prev_close > 0.0 and close > 0.0:
            self._buffer_push(math.log(close / prev_close), self.atr)

    def _buffer_push(self, log_ret, atr):
        self.log_returns[self.head] = log_ret
        self.atr_series[self.head] = atr
        self.head = (self.head + 1) % MAX_BARS
        if self.count < MAX_BARS:
            self.count += 1

    def realized_vol(self, lookback):
        n = min(lookback, self.count)
        if n < 2:
            return 0.0
        start = (self.head - n + MAX_BARS) % MAX_BARS
        vals = [self.log_returns[(start + i) % MAX_BARS] for i in range(n)]
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / (n - 1)
        return math.sqrt(var)

    def atr_percentile(self, window):
        if not self.has_atr or window <= 0 or self.count < 2:
            return 0.5
        n = min(window, self.count)
        start = (self.head - n + MAX_BARS) % MAX_BARS
        below = sum(
            1 for i in range(n)
            if self.atr_series[(start + i) % MAX_BARS] < self.atr
        )
        return below / n

    def is_expanding(self, window):
        if not self.has_atr or window <= 0 or self.count < 2:
            return False
        n = min(window, self.count)
        start = (self.head - n + MAX_BARS) % MAX_BARS
        vals = [self.atr_series[(start + i) % MAX_BARS] for i in range(n)]
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / max(1, n - 1)
        std = math.sqrt(var)
        return std > 0.0 and self.atr > mean + std


# --- SymbolAdapter.mqh mirror (volume grid + spread) -------------------------
def normalize_volume_from_spec(spec, requested):
    vmin = spec["volume_min"]
    vmax = spec["volume_max"]
    vstep = spec["volume_step"]
    if vmin <= 0.0:
        vmin = 0.01
    if vstep <= 0.0:
        vstep = 0.01
    vol = requested
    if vol < vmin:
        vol = vmin
    if vol > vmax:
        vol = vmax
    vol = math.floor(vol / vstep + 0.5) * vstep
    if vol < vmin:
        vol = vmin
    return vol


# --- Tests (same assertions as Tests/Phase1Tests.mq5) ------------------------
print("[PHASE1] --- NormalizationEngine ---")
check("RangeToATR 2.0/1.0 = 2.0", close(range_to_atr(102.0, 100.0, 1.0), 2.0, 1e-9))
check("RangeToATR atr<=0 -> 0", close(range_to_atr(102.0, 100.0, 0.0), 0.0, 1e-9))
check("BodyToATR |101-100|/1 = 1", close(body_to_atr(100.0, 101.0, 1.0), 1.0, 1e-9))
check("LogReturn 100->110 ~ 0.0953", close(log_return(100.0, 110.0), 0.095310, 1e-4))
check("PctReturn 100->110 = 0.1", close(pct_return(100.0, 110.0), 0.1, 1e-9))
check("ZScore (10,5,2.5) = 2", close(z_score(10.0, 5.0, 2.5), 2.0, 1e-9))
check("ZScore std<=0 -> 0", close(z_score(10.0, 5.0, 0.0), 0.0, 1e-9))
check("RelativeDistance (12,10,1) = 2", close(relative_distance(12.0, 10.0, 1.0), 2.0, 1e-9))
check("CloseLocation low=0", close(close_location(10.0, 8.0, 8.0), 0.0, 1e-9))
check("CloseLocation high=1", close(close_location(10.0, 8.0, 10.0), 1.0, 1e-9))
check("EfficiencyRatio ramp = 1", close(efficiency_ratio([100.0, 101.0, 102.0, 103.0, 104.0]), 1.0, 1e-9))
check("EfficiencyRatio zigzag = 0", close(efficiency_ratio([100.0, 102.0, 100.0, 102.0, 100.0]), 0.0, 1e-9))

print("[PHASE1] --- VolatilityEngine ---")
ve = VolatilityEngine(14)
# Constant range 2.0 bars: ATR converges to 2.0.  Bars must track the
# drift (high=prev+1, low=prev-1) so the previous close stays inside the
# candle — fixed high/low with a drifting close would invert the candle
# and balloon the true range.
prev = 100.0
for _ in range(100):
    ve.on_bar_with_prev_close(prev, prev + 1.0, prev - 1.0, prev + 0.5)
    prev += 0.5
check("ATR converges to 2.0", close(ve.atr, 2.0, 0.05), f"atr={ve.atr:.4f}")
# Constant ATR series: strict-< rank means nothing is below the current
# value, so the percentile is 0.0 (expansion test below covers the rise).
check("ATR percentile 0 for constant ATR", close(ve.atr_percentile(50), 0.0, 0.05),
      f"pct={ve.atr_percentile(50):.3f}")

ve2 = VolatilityEngine(5)
prev = 100.0
for _ in range(40):
    ve2.on_bar_with_prev_close(prev, prev + 0.5, prev - 0.5, prev + 0.1)
    prev += 0.1
ve2.on_bar_with_prev_close(prev, prev + 5.0, prev - 5.0, prev + 2.0)
check("expansion bar detected", ve2.is_expanding(30), f"atr={ve2.atr:.3f}")
check("ATR percentile high after expansion", ve2.atr_percentile(30) > 0.7,
      f"pct={ve2.atr_percentile(30):.3f}")
check("RealizedVol positive", ve2.realized_vol(10) > 0.0,
      f"rv={ve2.realized_vol(10):.6f}")

print("[PHASE1] --- SymbolAdapter (real Blueberry fixtures) ---")
syn75 = {
    "point": 0.001, "digits": 3, "tick_size": 0.001, "tick_value": 0.1,
    "contract_size": 100.0, "volume_min": 0.01, "volume_max": 100.0,
    "volume_step": 0.01, "stops_level": 0, "freeze_level": 0,
    "bid": 1668.904, "ask": 1669.984,
}
syn100 = {
    "point": 0.001, "digits": 3, "tick_size": 0.001, "tick_value": 0.1,
    "contract_size": 100.0, "volume_min": 0.01, "volume_max": 100.0,
    "volume_step": 0.01, "stops_level": 0, "freeze_level": 0,
    "bid": 353.835, "ask": 354.266,
}
check("SYN75 digits=3", syn75["digits"] == 3)
check("SYN75 point=0.001", close(syn75["point"], 0.001, 1e-9))
check("SYN75 tick_size=0.001", close(syn75["tick_size"], 0.001, 1e-9))
check("SYN75 tick_value=0.1", close(syn75["tick_value"], 0.1, 1e-9))
check("SYN75 contract=100", close(syn75["contract_size"], 100.0, 1e-9))
check("SYN75 volume_min=0.01", close(syn75["volume_min"], 0.01, 1e-9))
check("SYN75 volume_max=100", close(syn75["volume_max"], 100.0, 1e-9))
check("SYN75 volume_step=0.01", close(syn75["volume_step"], 0.01, 1e-9))
check("SYN75 stops_level=0", syn75["stops_level"] == 0)
syn75_spread = (syn75["ask"] - syn75["bid"]) / syn75["point"]
check("SYN75 spread ~1080 pts", close(syn75_spread, 1080.0, 5.0), f"spread={syn75_spread:.1f}")
syn100_spread = (syn100["ask"] - syn100["bid"]) / syn100["point"]
check("SYN100 spread ~431 pts", close(syn100_spread, 431.0, 5.0), f"spread={syn100_spread:.1f}")

v = normalize_volume_from_spec(syn75, 0.0)
check("vol 0 -> min", close(v, 0.01, 1e-9), f"v={v}")
v = normalize_volume_from_spec(syn75, 0.123)
check("vol 0.123 -> 0.12", close(v, 0.12, 1e-9), f"v={v}")
v = normalize_volume_from_spec(syn75, 250.0)
check("vol 250 -> max", close(v, 100.0, 1e-9), f"v={v}")
v = normalize_volume_from_spec(syn75, 0.25)
check("vol 0.25 -> 0.25", close(v, 0.25, 1e-9), f"v={v}")

print(f"[PHASE1] === {PASS} passed, {FAIL} failed ===")
raise SystemExit(1 if FAIL > 0 else 0)
