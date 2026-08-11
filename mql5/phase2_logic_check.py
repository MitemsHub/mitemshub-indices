#!/usr/bin/env python3
"""Phase-2 logic mirror — verifies the exact algorithms in MITEMSHUB_AI.

Replicates line-for-line:
  Market/TimeframeManager.mqh      (seconds mapping, stack validation)
  Market/CandleEngine.mqh          (ring-buffer semantics)
  Regime/HurstAnalyzer.mqh         (R/S Hurst)
  Regime/TrendDetector.mqh         (efficiency + MA slope)
  Regime/RangeDetector.mqh         (chop score)
  Regime/CompressionDetector.mqh   (squeeze score)
  Regime/ExpansionDetector.mqh     (burst score)
  Regime/TransitionDetector.mqh    (vol-of-vol + efficiency change)
  Regime/RegimeEngine.mqh          (argmax + disagreement penalty)

and runs the SAME assertions as Tests/Phase2Tests.mq5.  This is the fast
CI loop for the math; the MetaEditor compile + tester run verify the MQL5
side.  Keep the two files in lockstep.
"""

import math
import random

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PHASE2] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PHASE2] FAIL  {name}  -> {detail}")


def close(a, b, tol):
    return abs(a - b) <= tol


# --- TimeframeManager mirror -------------------------------------------------
PERIODS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN1": 2592000,
}
VALID_TFS = set(PERIODS)


def tf_seconds(tf):
    return PERIODS.get(tf, 0)


# --- CandleEngine mirror -----------------------------------------------------
class CandleEngine:
    CAP = 500

    def __init__(self):
        self.tfs = []
        self.bars = {}
        self.head = {}
        self.counts = {}

    def register(self, tf):
        if tf not in self.tfs:
            self.tfs.append(tf)
            self.bars[tf] = [None] * self.CAP
            self.head[tf] = 0
            self.counts[tf] = 0

    def push(self, tf, open_, high, low, close, time_):
        if tf not in self.bars:
            return
        self.bars[tf][self.head[tf]] = (open_, high, low, close, time_)
        self.head[tf] = (self.head[tf] + 1) % self.CAP
        if self.counts[tf] < self.CAP:
            self.counts[tf] += 1

    def count(self, tf):
        return self.counts.get(tf, 0)

    def get_bar(self, tf, shift):
        if tf not in self.bars or shift < 0 or shift >= self.counts[tf]:
            return None
        idx = (self.head[tf] - 1 - shift) % self.CAP
        return self.bars[tf][idx]

    def get_closes(self, tf, count):
        if tf not in self.bars or count <= 0 or count > self.counts[tf]:
            return None
        out = []
        for k in range(count):
            idx = (self.head[tf] - 1 - k) % self.CAP
            out.insert(0, self.bars[tf][idx][3])
        return out


# --- NormalizationEngine mirror (subset used by detectors) -------------------
def efficiency_ratio(closes):
    n = len(closes)
    if n < 2:
        return 0.0
    net = abs(closes[n - 1] - closes[0])
    gross = sum(abs(closes[i] - closes[i - 1]) for i in range(1, n))
    return 0.0 if gross <= 0.0 else net / gross


# --- HurstAnalyzer mirror ----------------------------------------------------
def hurst(returns):
    count = len(returns)
    if count < 32:
        return -1.0
    xs, ys = [], []
    maxL = count // 2
    L = 8
    while L <= maxL:
        L = max(8, L)
        if L + 1 > count or L >= count:
            break
        ns = count // L
        rs_sum = 0.0
        rs_n = 0
        for s in range(ns):
            base = s * L
            sub = returns[base:base + L]
            mean = sum(sub) / L
            var = sum((x - mean) ** 2 for x in sub) / (L - 1)
            sdev = math.sqrt(var)
            if sdev <= 0.0:
                continue
            cum = 0.0
            mn = mx = 0.0
            for i, x in enumerate(sub):
                cum += (x - mean)
                if i == 0:
                    mn = mx = cum
                else:
                    mn = min(mn, cum)
                    mx = max(mx, cum)
            rng = mx - mn
            if rng > 0.0:
                rs_sum += rng / sdev
                rs_n += 1
        if rs_n > 0 and len(xs) < 16:
            xs.append(math.log(L))
            ys.append(math.log(rs_sum / rs_n))
        L = (L * 3) // 2
    if len(xs) < 3:
        return -1.0
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0.0:
        return -1.0
    h = (n * sxy - sx * sy) / denom
    return max(0.0, min(1.0, h))


def hurst_on_closes(closes):
    if len(closes) < 33:
        return -1.0
    rets = [math.log(closes[i + 1] / closes[i])
            if closes[i] > 0.0 and closes[i + 1] > 0.0 else 0.0
            for i in range(len(closes) - 1)]
    return hurst(rets)


# --- TrendDetector mirror ----------------------------------------------------
def sma(closes, start, period):
    return sum(closes[start:start + period]) / period


def trend_strength(closes, ma_period=20):
    count = len(closes)
    if count < 2 * ma_period + 2:
        return 0.0
    er = efficiency_ratio(closes)
    ma_now = sma(closes, count - ma_period, ma_period)
    ma_prev = sma(closes, count - 2 * ma_period, ma_period)
    mean = sum(abs(c) for c in closes) / count
    slope = (ma_now - ma_prev) / mean if mean > 0.0 else 0.0
    slope_score = min(1.0, abs(slope) * 50.0)
    return min(1.0, 0.5 * er + 0.5 * slope_score)


def trend_direction(closes, ma_period=20):
    count = len(closes)
    if count < 2 * ma_period + 2:
        return 0
    ma_now = sma(closes, count - ma_period, ma_period)
    ma_prev = sma(closes, count - 2 * ma_period, ma_period)
    mean = sum(abs(c) for c in closes) / count
    diff = ma_now - ma_prev
    if mean > 0.0 and abs(diff) < mean * 0.0005:
        return 0
    return 1 if diff > 0.0 else -1


# --- RangeDetector mirror ----------------------------------------------------
def range_score(closes):
    count = len(closes)
    if count < 8:
        return 0.0
    er = efficiency_ratio(closes)
    flips = 0.0
    n = 0
    for i in range(2, count):
        d1 = closes[i - 1] - closes[i - 2]
        d2 = closes[i] - closes[i - 1]
        if (d1 > 0.0 and d2 < 0.0) or (d1 < 0.0 and d2 > 0.0):
            flips += 1.0
        n += 1
    flip_ratio = flips / n if n > 0 else 0.0
    er_score = 1.0 - min(1.0, er * 4.0)
    flip_score = min(1.0, flip_ratio * 2.0)
    return min(1.0, 0.6 * er_score + 0.4 * flip_score)


# --- Compression / Expansion mirrors -----------------------------------------
def compression_score(atr_percentile, atr_ratio):
    if atr_percentile < 0.0 or atr_percentile > 1.0:
        return 0.0
    p = 1.0 - atr_percentile
    r = max(0.0, 1.0 - atr_ratio)
    return min(1.0, 0.6 * p + 0.4 * min(1.0, r))


def expansion_score(atr_percentile, atr_ratio):
    if atr_percentile < 0.0 or atr_percentile > 1.0:
        return 0.0
    p = atr_percentile
    r = max(0.0, atr_ratio - 1.0)
    return min(1.0, 0.6 * p + 0.4 * min(1.0, r))


# --- TransitionDetector mirror ------------------------------------------------
def _slice_er(closes, start, n):
    if n < 2:
        return 0.0
    net = abs(closes[start + n - 1] - closes[start])
    gross = sum(abs(closes[start + i] - closes[start + i - 1]) for i in range(1, n))
    return 0.0 if gross <= 0.0 else net / gross


def _slice_realized_vol(closes, start, n):
    if n < 3:
        return 0.0
    rets = [math.log(closes[start + i + 1] / closes[start + i])
            if closes[start + i] > 0.0 else 0.0
            for i in range(n - 1)]
    m = len(rets)
    mean = sum(rets) / m
    var = sum((r - mean) ** 2 for r in rets) / (m - 1)
    return math.sqrt(var)


def transition_score(closes, window=10):
    count = len(closes)
    if count < 2 * window + 4:
        return 0.0
    start1 = count - 2 * window
    start2 = count - window
    v1 = _slice_realized_vol(closes, start1, window)
    v2 = _slice_realized_vol(closes, start2, window)
    vv = abs(v2 - v1) / (v1 + v2) if (v1 + v2) > 0.0 else 0.0
    e1 = _slice_er(closes, start1, window)
    e2 = _slice_er(closes, start2, window)
    ed = abs(e2 - e1)
    return min(1.0, 0.6 * min(1.0, vv * 3.0) + 0.4 * min(1.0, ed * 3.0))


# --- RegimeEngine mirror ------------------------------------------------------
REGIME_TRANSITION_THRESHOLD = 0.70   # real-corpus calibration (was 0.55)
R_TREND_UP, R_TREND_DOWN, R_RANGE, R_COMPRESSION, R_EXPANSION, R_TRANSITION = range(6)
R_NAME = ["TREND_UP", "TREND_DOWN", "RANGE", "COMPRESSION", "EXPANSION", "TRANSITION"]


def classify(closes, atr_percentile, atr_ratio):
    trend_strength = trend_strength_fn(closes)
    trend_direction = trend_direction_fn(closes)
    mr_score = range_score(closes)
    transition_prob = transition_score(closes)
    compression = compression_score(atr_percentile, atr_ratio)
    expansion = expansion_score(atr_percentile, atr_ratio)

    s_trend_up = trend_strength if trend_direction > 0 else 0.0
    s_trend_down = trend_strength if trend_direction < 0 else 0.0
    s_range = mr_score
    s_compress = compression * (1.0 - trend_strength)
    # EXPANSION must be a REAL ATR lift, not a high relative percentile alone:
    # on real R_75 data the percentile can sit near 1.0 during a merely
    # volatile-but-stable stretch (ratio ~1.0), which is not an expansion.
    s_expand = expansion if atr_ratio > 1.15 else expansion * 0.4
    s_transition = transition_prob if transition_prob >= REGIME_TRANSITION_THRESHOLD else 0.0

    scores = [s_trend_up, s_trend_down, s_range, s_compress, s_expand, s_transition]
    top = max(scores)
    regime = scores.index(top)

    disagreement = abs(trend_strength - mr_score)
    conf = min(1.0, max(0.0, top * (1.0 - 0.5 * disagreement)))
    return R_NAME[regime], conf, trend_strength, trend_direction, mr_score, transition_prob


# names for the classify closure
trend_strength_fn = trend_strength
trend_direction_fn = trend_direction


# --- Synthetic series builders ------------------------------------------------
def ramp(n, step=0.5, start=100.0):
    return [start + i * step for i in range(n)]


def zigzag(n, amp=1.0, start=100.0):
    out = []
    for i in range(n):
        out.append(start + amp if i % 2 == 0 else start - amp)
    return out


def oscillation(n, amp=1.0, period=8, start=100.0):
    import math as _m
    return [start + amp * _m.sin(2 * _m.pi * i / period) for i in range(n)]


def random_walk(n, seed=42):
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] + rng.gauss(0.0, 1.0))
    return closes


def persistent(n, seed=42):
    """Strongly persistent: integrated increments with drift dominating noise
    (R/S Hurst measured ~0.9 for this generator)."""
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] + 0.2 + rng.gauss(0.0, 0.02))
    return closes


def mean_reverting(n, seed=42):
    """Anti-persistent: alternation around a fixed mean."""
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        prev = closes[-1]
        nxt = prev + (0.6 * (100.0 - prev)) + rng.gauss(0.0, 0.15)
        closes.append(nxt)
    return closes


# ============================ TESTS ==========================================
print("[PHASE2] --- TimeframeManager ---")
check("M1=60s", tf_seconds("M1") == 60)
check("H1=3600s", tf_seconds("H1") == 3600)
check("H4=14400s", tf_seconds("H4") == 14400)
check("D1=86400s", tf_seconds("D1") == 86400)
check("MN1=2592000s", tf_seconds("MN1") == 2592000)

print("[PHASE2] --- CandleEngine ---")
ce = CandleEngine()
ce.register("M5")
for i in range(10):
    ce.push("M5", 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1000 + i)
check("count=10", ce.count("M5") == 10)
check("newest = last pushed", ce.get_bar("M5", 0)[3] == 109.5)
check("shift1 = second newest", ce.get_bar("M5", 1)[3] == 108.5)
closes = ce.get_closes("M5", 5)
check("closes oldest-first", closes == [105.5, 106.5, 107.5, 108.5, 109.5], f"{closes}")
check("unregistered tf count 0", ce.count("H1") == 0)
ce2 = CandleEngine()
ce2.register("M5")
for i in range(600):
    ce2.push("M5", 0, 0, 0, float(i), i)
check("ring wraps at 500", ce2.count("M5") == 500)
check("ring newest preserved", ce2.get_bar("M5", 0)[3] == 599.0)
check("ring oldest evicted", ce2.get_bar("M5", 499)[3] == 100.0)

print("[PHASE2] --- TrendDetector ---")
r = ramp(120, 0.5)
ts = trend_strength(r)
check("ramp strength high", ts > 0.6, f"ts={ts:.3f}")
check("ramp direction +1", trend_direction(r) == 1)
zg = zigzag(120, 1.0)
check("zigzag strength low", trend_strength(zg) < 0.4, f"ts={trend_strength(zg):.3f}")
check("zigzag direction 0", trend_direction(zg) == 0)

print("[PHASE2] --- RangeDetector ---")
osc = oscillation(120, 1.0, 8)
rs = range_score(osc)
check("oscillation range score high", rs > 0.5, f"rs={rs:.3f}")
check("ramp range score low", range_score(r) < 0.3, f"rs={range_score(r):.3f}")

print("[PHASE2] --- Compression / Expansion ---")
check("compression at p=0.05 r=0.3 high", compression_score(0.05, 0.3) > 0.6,
      f"c={compression_score(0.05, 0.3):.3f}")
check("expansion at p=0.95 r=3.0 high", expansion_score(0.95, 3.0) > 0.6,
      f"e={expansion_score(0.95, 3.0):.3f}")

print("[PHASE2] --- TransitionDetector ---")
# Vol change must sit INSIDE the detector's 2*window view (the last 20 pts
# with window=10): 30 low-vol pts, then 10 low-vol, then 10 high-vol.
low = [100.0 + 0.1 * i for i in range(30)]
mid = [low[-1] + 0.1 * i for i in range(10)]
hi = [mid[-1] + 0.5 * i for i in range(10)]
trans_series = low + mid + hi
tv = transition_score(trans_series, 10)
check("vol-doubling transition high", tv > 0.4, f"trans={tv:.3f}")

print("[PHASE2] --- HurstAnalyzer ---")
rw = random_walk(512, 42)
h_rw = hurst_on_closes(rw)
check("random walk H ~ 0.5", 0.35 < h_rw < 0.65, f"H={h_rw:.3f}")
pr = persistent(512, 42)
h_pr = hurst_on_closes(pr)
check("persistent H > 0.6", h_pr > 0.6, f"H={h_pr:.3f}")
mr = mean_reverting(512, 42)
h_mr = hurst_on_closes(mr)
check("mean-reverting H < 0.4", h_mr < 0.4, f"H={h_mr:.3f}")

print("[PHASE2] --- RegimeEngine ---")
reg, conf, _, _, _, _ = classify(r, 0.4, 1.0)
check("ramp -> TREND_UP", reg == "TREND_UP", f"got {reg}")
check("trend confidence > 0", conf > 0.0, f"conf={conf:.3f}")

reg, conf, _, _, _, _ = classify(osc, 0.5, 1.0)
check("oscillation -> RANGE", reg == "RANGE", f"got {reg}")

flat = [100.0] * 120
reg, conf, _, _, _, _ = classify(flat, 0.05, 0.3)
check("squeeze inputs -> COMPRESSION", reg == "COMPRESSION", f"got {reg}")

# A monotonic ramp + burst correctly resolves to TREND_UP (expansion WITH a
# trend is a trend); EXPANSION wins only when vol bursts without a strong
# trend — use oscillation closes.
reg, conf, _, _, _, _ = classify(osc, 0.95, 3.0)
check("burst + no trend -> EXPANSION", reg == "EXPANSION", f"got {reg}")

print(f"[PHASE2] === {PASS} passed, {FAIL} failed ===")
raise SystemExit(1 if FAIL > 0 else 0)
