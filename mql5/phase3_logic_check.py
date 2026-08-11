#!/usr/bin/env python3
"""Phase-3 logic mirror — verifies the exact algorithms in MITEMSHUB_AI.

Replicates line-for-line:
  Structure/SwingDetector.mqh        (fractal swings + ATR prominence)
  Structure/BOSDetector.mqh          (break of structure, confirmed swings)
  Structure/CHOCHDetector.mqh        (change of character, HH+HL / LH+LL)
  Structure/LiquidityEngine.mqh      (sweep = wick beyond + close back)
  Structure/SupportResistance.mqh    (level clustering with touch counts)
  Structure/DisplacementDetector.mqh (normalized impulse bars)
  Structure/StructureEngine.mqh      (aggregator over CandleEngine)

and runs the SAME assertions as Tests/Phase3Tests.mq5.  This is the fast
CI loop for the math; the MetaEditor compile + tester run verify the MQL5
side.  Keep the two files in lockstep.
"""

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PHASE3] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PHASE3] FAIL  {name}  -> {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


# --- SwingDetector mirror ----------------------------------------------------
def is_swing_high(highs, i, left, right):
    if i - left < 0 or i + right >= len(highs):
        return False
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        if highs[i] <= highs[j]:
            return False
    return True


def is_swing_low(lows, i, left, right):
    if i - left < 0 or i + right >= len(lows):
        return False
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        if lows[i] >= lows[j]:
            return False
    return True


def swing_strength(highs, lows, i, direction, atr):
    if atr <= 0.0 or i < 1 or i >= len(highs) - 1:
        return 0.0
    if direction > 0:
        clear = min(highs[i] - highs[i - 1], highs[i] - highs[i + 1])
    else:
        clear = min(lows[i - 1] - lows[i], lows[i + 1] - lows[i])
    if clear <= 0.0:
        return 0.0
    return min(1.0, clear / atr)


def find_swing(highs, lows, times, count, left, right, atr, max_out=128):
    out = []
    # Python-parity window-edge convention: the CURRENT (last) bar is never a
    # right guard — swings are confirmed only by bars strictly before it, i.e.
    # i + right < count - 1 (Python detect_swings over candles[:-1] iterates
    # range(left, len-1-right)).  This removed the 25 window-edge B2b BOS
    # disagreements in the real-corpus gate.
    for i in range(left, count - right - 1):
        if len(out) >= max_out:
            break
        if is_swing_high(highs, i, left, right):
            out.append(dict(time=times[i], price=highs[i], bar=i,
                            direction=1, strength=swing_strength(highs, lows, i, 1, atr)))
        elif is_swing_low(lows, i, left, right):
            out.append(dict(time=times[i], price=lows[i], bar=i,
                            direction=-1, strength=swing_strength(highs, lows, i, -1, atr)))
    return out


# --- BOSDetector mirror ------------------------------------------------------
def bos_detect(highs, lows, closes, times, count, left, right, atr, max_out=16):
    out = []
    if count < left + right + 3 or atr <= 0.0:
        return out
    swings = find_swing(highs, lows, times, count, left, right, atr)
    next_swing = 0
    last_sh_price = 0.0
    last_sl_price = 0.0
    for i in range(count):
        while next_swing < len(swings) and swings[next_swing]["bar"] + right <= i:
            if swings[next_swing]["direction"] > 0:
                last_sh_price = swings[next_swing]["price"]
            else:
                last_sl_price = swings[next_swing]["price"]
            next_swing += 1
        if (last_sh_price > 0.0 and closes[i] > last_sh_price
                and (i == 0 or closes[i - 1] <= last_sh_price)):
            if len(out) >= max_out:
                break
            out.append(dict(time=times[i], price=closes[i], level=last_sh_price,
                            direction=1, strength=min(1.0, max(0.0, (closes[i] - last_sh_price) / atr))))
        elif (last_sl_price > 0.0 and closes[i] < last_sl_price
              and (i == 0 or closes[i - 1] >= last_sl_price)):
            if len(out) >= max_out:
                break
            out.append(dict(time=times[i], price=closes[i], level=last_sl_price,
                            direction=-1, strength=min(1.0, max(0.0, (last_sl_price - closes[i]) / atr))))
    return out


# --- CHOCHDetector mirror ----------------------------------------------------
def choch_detect(highs, lows, closes, times, count, left, right, atr, max_out=16):
    out = []
    if count < left + right + 5 or atr <= 0.0:
        return out
    swings = find_swing(highs, lows, times, count, left, right, atr)
    next_swing = 0
    sh1 = sh0 = 0.0
    sl1 = sl0 = 0.0
    for i in range(count):
        while next_swing < len(swings) and swings[next_swing]["bar"] + right <= i:
            if swings[next_swing]["direction"] > 0:
                sh1, sh0 = sh0, swings[next_swing]["price"]
            else:
                sl1, sl0 = sl0, swings[next_swing]["price"]
            next_swing += 1
        uptrend = (sh0 > 0.0 and sh1 > 0.0 and sl0 > 0.0 and sl1 > 0.0) and sh0 > sh1 and sl0 > sl1
        downtrend = (sh0 > 0.0 and sh1 > 0.0 and sl0 > 0.0 and sl1 > 0.0) and sh0 < sh1 and sl0 < sl1
        if uptrend and closes[i] < sl0 and (i == 0 or closes[i - 1] >= sl0):
            if len(out) >= max_out:
                break
            out.append(dict(time=times[i], price=closes[i], level=sl0,
                            direction=-1, strength=min(1.0, max(0.0, (sl0 - closes[i]) / atr))))
        elif downtrend and closes[i] > sh0 and (i == 0 or closes[i - 1] <= sh0):
            if len(out) >= max_out:
                break
            out.append(dict(time=times[i], price=closes[i], level=sh0,
                            direction=1, strength=min(1.0, max(0.0, (closes[i] - sh0) / atr))))
    return out


# --- LiquidityEngine mirror --------------------------------------------------
def is_sweep(bar_high, bar_low, close, level, atr, min_exceed_atr, above):
    if atr <= 0.0:
        return False
    if above:
        return bar_high > level + min_exceed_atr * atr and close < level
    return bar_low < level - min_exceed_atr * atr and close > level


def detect_sweeps(highs, lows, closes, times, count, left, right, atr, min_exceed_atr=0.1, max_out=16):
    # Only the most recent swing of each polarity is the live liquidity
    # reference (Python recent_high/recent_low semantics) — the Phase-3
    # real-corpus reconciliation.  Scanning every historical level fired a
    # sweep in every 100-bar window on the real corpus (448/448).
    out = []
    if count < left + right + 3 or atr <= 0.0:
        return out
    swings = find_swing(highs, lows, times, count, left, right, atr)
    last_high = last_low = 0.0
    last_high_bar = last_low_bar = -1
    for s in swings:
        if s["direction"] > 0:
            last_high, last_high_bar = s["price"], s["bar"]
        else:
            last_low, last_low_bar = s["price"], s["bar"]
    for level, level_bar, above in ((last_high, last_high_bar, True),
                                    (last_low, last_low_bar, False)):
        if level_bar < 0 or len(out) >= max_out:
            continue
        for i in range(level_bar + right + 1, count):
            if is_sweep(highs[i], lows[i], closes[i], level, atr, min_exceed_atr, above):
                out.append(dict(time=times[i], level=level,
                                extreme=highs[i] if above else lows[i],
                                close=closes[i], direction=-1 if above else 1,
                                confirmed=True))
                break
    return out


# --- SupportResistance mirror ------------------------------------------------
def sr_cluster(prices, kinds, times, atr, tol_atr, min_touches=2, max_out=32):
    out = []
    if atr <= 0.0 or len(prices) <= 0:
        return out
    for i in range(len(prices)):
        found = -1
        for j in range(len(out)):
            if abs(out[j]["level"] - prices[i]) <= tol_atr * atr:
                found = j
                break
        if found >= 0:
            out[found]["touches"] += 1
            out[found]["kind"] |= kinds[i]
            out[found]["last_time"] = times[i]
        else:
            if len(out) >= max_out:
                continue
            out.append(dict(level=prices[i], touches=1, kind=kinds[i],
                            first_time=times[i], last_time=times[i]))
    return [lv for lv in out if lv["touches"] >= min_touches]


def sr_query_near(levels, price, atr, tol_atr):
    best = -1
    best_dist = 0.0
    for i in range(len(levels)):
        d = abs(levels[i]["level"] - price)
        if best < 0 or d < best_dist:
            best = i
            best_dist = d
    if best < 0 or best_dist > tol_atr * atr:
        return None
    return (levels[best]["level"], levels[best]["touches"])


# --- DisplacementDetector mirror ---------------------------------------------
def disp_score(open_, high, low, close, atr, body_mult=2.0, range_mult=3.0):
    if atr <= 0.0:
        return 0.0
    rng = high - low
    if rng <= 0.0:
        return 0.0
    body_part = min(1.0, abs(close - open_) / atr / body_mult)
    range_part = min(1.0, rng / atr / range_mult)
    return 0.7 * body_part + 0.3 * range_part


def is_displacement(open_, high, low, close, atr, body_mult=2.0, range_mult=3.0):
    if atr <= 0.0:
        return False
    rng = high - low
    if rng <= 0.0:
        return False
    body = abs(close - open_)
    if body / atr < body_mult or rng / atr < range_mult:
        return False
    loc = (close - low) / rng
    if body > 0.0 and close > open_:
        return loc >= 0.7
    if body > 0.0 and close < open_:
        return loc <= 0.3
    return False


def disp_detect(opens, highs, lows, closes, times, count, atr,
                body_mult=2.0, range_mult=3.0, max_out=16):
    out = []
    if atr <= 0.0:
        return out
    for i in range(count):
        if len(out) >= max_out:
            break
        if not is_displacement(opens[i], highs[i], lows[i], closes[i], atr, body_mult, range_mult):
            continue
        rng = highs[i] - lows[i]
        out.append(dict(bar=i, direction=1 if closes[i] > opens[i] else -1,
                        body_atr=abs(closes[i] - opens[i]) / atr if rng > 0 else 0.0,
                        range_atr=rng / atr if rng > 0 else 0.0,
                        close_loc=(closes[i] - lows[i]) / rng if rng > 0 else 0.5,
                        score=disp_score(opens[i], highs[i], lows[i], closes[i], atr,
                                         body_mult, range_mult)))
    return out


# --- StructureEngine mirror (aggregator over a CandleEngine-like buffer) -----
class CandleEngine:
    """Minimal mirror of Market/CandleEngine.mqh ring buffer (Phase 2)."""

    def __init__(self, cap=500):
        self.cap = cap
        self.tfs = {}
        self.head = {}
        self.counts = {}

    def register(self, tf):
        if tf not in self.tfs:
            self.tfs[tf] = [None] * self.cap
            self.head[tf] = 0
            self.counts[tf] = 0

    def push(self, tf, o, h, l, c, t):
        self.tfs[tf][self.head[tf]] = (o, h, l, c, t)
        self.head[tf] = (self.head[tf] + 1) % self.cap
        if self.counts[tf] < self.cap:
            self.counts[tf] += 1

    def count(self, tf):
        return self.counts.get(tf, 0)

    def get_bar(self, tf, shift):
        if tf not in self.tfs or shift < 0 or shift >= self.counts[tf]:
            return None
        idx = (self.head[tf] - 1 - shift) % self.cap
        return self.tfs[tf][idx]


class StructureEngine:
    """Mirror of Structure/StructureEngine.mqh."""

    def __init__(self, swing_left=3, swing_right=3, window=100):
        self.sl = swing_left
        self.sr = swing_right
        self.window = window
        self.atr = 0.0
        self.swings = []
        self.bos = []
        self.choch = []
        self.sweeps = []
        self.sr_levels = []
        self.disp = []
        self.bias = 0
        self.last_event = 0
        self.last_direction = 0
        self.last_event_price = 0.0
        self.last_event_time = 0

    def update(self, ce, tf, atr):
        have = ce.count(tf)
        take = min(have, self.window)
        if take < self.sl + self.sr + 3:
            return False
        self.atr = atr
        bars = []
        for i in range(take):
            b = ce.get_bar(tf, take - 1 - i)
            if b is None:
                return False
            bars.append(b)
        opens = [b[0] for b in bars]
        highs = [b[1] for b in bars]
        lows = [b[2] for b in bars]
        closes = [b[3] for b in bars]
        times = [b[4] for b in bars]

        self.swings = find_swing(highs, lows, times, take, self.sl, self.sr, atr)
        self.bos = bos_detect(highs, lows, closes, times, take, self.sl, self.sr, atr)
        self.choch = choch_detect(highs, lows, closes, times, take, self.sl, self.sr, atr)
        self.sweeps = detect_sweeps(highs, lows, closes, times, take, self.sl, self.sr, atr)
        self.disp = disp_detect(opens, highs, lows, closes, times, take, atr)

        kinds = [s["direction"] for s in self.swings]
        prices = [s["price"] for s in self.swings]
        stimes = [s["time"] for s in self.swings]
        self.sr_levels = sr_cluster(prices, kinds, stimes, atr, 0.5, min_touches=2)

        # last event = max time across lists; CHOCH > BOS > SWEEP > DISP ties.
        # Event codes mirror ENUM_STRUCTURE_EVENT in Core/Constants.mqh:
        # NONE=0, BOS=1, CHOCH=2, SWEEP=3, DISPLACEMENT=4.
        t, type_, dir_, price = 0, 0, 0, 0.0
        if self.choch:
            c = self.choch[-1]
            t, type_, dir_, price = c["time"], 2, c["direction"], c["price"]
        if self.bos and self.bos[-1]["time"] > t:
            b = self.bos[-1]
            t, type_, dir_, price = b["time"], 1, b["direction"], b["price"]
        if self.sweeps and self.sweeps[-1]["time"] > t:
            s = self.sweeps[-1]
            t, type_, dir_, price = s["time"], 3, s["direction"], s["level"]
        if self.disp and self.disp[-1]["bar"] < len(times) and times[self.disp[-1]["bar"]] > t:
            d = self.disp[-1]
            t, type_, dir_, price = times[d["bar"]], 4, d["direction"], closes[d["bar"]]
        self.last_event = type_
        self.last_direction = dir_
        self.last_event_price = price
        self.last_event_time = t

        if type_ == 2 or type_ == 1:
            self.bias = 1 if dir_ > 0 else -1
        else:
            self.bias = 0
            sh1 = sh0 = sl1 = sl0 = 0.0
            for s in self.swings:
                if s["direction"] > 0:
                    sh1, sh0 = sh0, s["price"]
                else:
                    sl1, sl0 = sl0, s["price"]
            if sh0 > 0 and sh1 > 0 and sl0 > 0 and sl1 > 0:
                if sh0 > sh1 and sl0 > sl1:
                    self.bias = 1
                elif sh0 < sh1 and sl0 < sl1:
                    self.bias = -1
        return True


# --- Crafted series builders -------------------------------------------------
def series_from_closes(closes, off=0.5):
    """Build OHLC arrays from closes: high=close+off, low=close-off, open=prev close."""
    highs = [c + off for c in closes]
    lows = [c - off for c in closes]
    opens = [closes[0]] + closes[:-1]
    times = list(range(1000, 1000 + len(closes)))
    return opens, highs, lows, closes, times


# ============================ TESTS ==========================================
print("[PHASE3] --- SwingDetector ---")
v_highs = [100, 101, 102, 103, 104, 103, 102, 101, 100]
v_lows = [104, 103, 102, 101, 100, 101, 102, 103, 104]
check("peak is swing high", is_swing_high(v_highs, 4, 2, 2))
check("slope not swing high", not is_swing_high(v_highs, 2, 2, 2))
check("edge guard left", not is_swing_high(v_highs, 0, 2, 2))
check("valley is swing low", is_swing_low(v_lows, 4, 2, 2))
check("slope not swing low", not is_swing_low(v_lows, 2, 2, 2))
check("deep peak strength 1.0", close(swing_strength(v_highs, v_lows, 4, 1, 1.0), 1.0))
shallow_h = [100, 100.5, 101, 100.5, 100]
shallow_l = [c - 0.5 for c in shallow_h]
check("shallow peak strength 0.5", close(swing_strength(shallow_h, shallow_l, 2, 1, 1.0), 0.5))

saw = [100, 101, 102, 103, 102, 101, 100, 101, 102, 103, 102, 101, 100]
o_saw, h_saw, l_saw, c_saw, t_saw = series_from_closes(saw)
sw = find_swing(h_saw, l_saw, t_saw, len(saw), 2, 2, 2.0)
check("sawtooth swing count 3", len(sw) == 3, f"got {len(sw)}")
check("swing directions alternate", [s["direction"] for s in sw] == [1, -1, 1],
      f"{[s['direction'] for s in sw]}")
check("sawtooth swing strength 0.5", close(sw[0]["strength"], 0.5), f"{sw[0]['strength']}")
check("swing bar indices", [s["bar"] for s in sw] == [3, 6, 9], f"{[s['bar'] for s in sw]}")

print("[PHASE3] --- BOSDetector ---")
bos_closes = [100, 101, 102, 103, 104, 103, 102, 106]
o_b, h_b, l_b, c_b, t_b = series_from_closes(bos_closes)
bos = bos_detect(h_b, l_b, c_b, t_b, len(bos_closes), 2, 2, 1.0)
check("bullish BOS count 1", len(bos) == 1, f"got {len(bos)}")
check("bullish BOS direction +1", bos[0]["direction"] == 1)
check("bullish BOS at break bar", bos[0]["time"] == 1007, f"{bos[0]['time']}")
check("bullish BOS level 104.5", close(bos[0]["level"], 104.5))
check("bullish BOS strength clamped 1.0", close(bos[0]["strength"], 1.0))

no_break = [100, 101, 102, 103, 104, 103, 102, 103]
o_n, h_n, l_n, c_n, t_n = series_from_closes(no_break)
check("no BOS without break", len(bos_detect(h_n, l_n, c_n, t_n, len(no_break), 2, 2, 1.0)) == 0)

bear_closes = [100, 99, 98, 97, 96, 97, 98, 94]
o_br, h_br, l_br, c_br, t_br = series_from_closes(bear_closes)
bos_b = bos_detect(h_br, l_br, c_br, t_br, len(bear_closes), 2, 2, 1.0)
check("bearish BOS direction -1", len(bos_b) == 1 and bos_b[0]["direction"] == -1,
      f"got {len(bos_b)} {[e['direction'] for e in bos_b]}")

print("[PHASE3] --- CHOCHDetector ---")
choch_down = [100, 103, 106, 104, 102, 104, 106, 108, 106.5, 105, 106.5, 107.5, 104]
o_c, h_c, l_c, c_c, t_c = series_from_closes(choch_down)
cd = choch_detect(h_c, l_c, c_c, t_c, len(choch_down), 2, 2, 1.0)
check("CHOCH down count 1", len(cd) == 1, f"got {len(cd)}")
check("CHOCH down direction -1", cd[0]["direction"] == -1)
check("CHOCH down at bar 12", cd[0]["time"] == 1012, f"{cd[0]['time']}")
check("CHOCH down level = last HL 104.5", close(cd[0]["level"], 104.5))
check("CHOCH down strength 0.5", close(cd[0]["strength"], 0.5))

ramp = list(range(100, 114))
o_r, h_r, l_r, c_r, t_r = series_from_closes(ramp)
check("no CHOCH on monotonic ramp", len(choch_detect(h_r, l_r, c_r, t_r, len(ramp), 2, 2, 1.0)) == 0)

choch_up = [100, 97, 94, 96, 98, 96, 94, 92, 93.5, 95, 93.5, 92.5, 96]
o_u, h_u, l_u, c_u, t_u = series_from_closes(choch_up)
cu = choch_detect(h_u, l_u, c_u, t_u, len(choch_up), 2, 2, 1.0)
check("CHOCH up count 1", len(cu) == 1, f"got {len(cu)}")
check("CHOCH up direction +1", cu[0]["direction"] == 1)
check("CHOCH up level = last LH 95.5", close(cu[0]["level"], 95.5))

print("[PHASE3] --- LiquidityEngine ---")
# Stale-level sweep must NOT fire (only the most recent swing of each
# polarity is the live liquidity reference): H1=110.5 (bar 2) is swept by
# bar 10's wick to 111.5, but H2=113.5 (bar 7) is the newest high and is
# NOT swept, so the detector must report nothing.
stale_bars = [(100, 105.5, 104.5, 105), (105, 107.5, 106.5, 107), (107, 110.5, 109.5, 110),
              (110, 109.9, 107.5, 108), (108, 108.5, 105.5, 106), (106, 109.5, 108.5, 109),
              (109, 111.5, 110.5, 111), (111, 113.5, 112.5, 113), (113, 112.5, 111.0, 111.5),
              (111.5, 111.5, 110.0, 110.5), (110.5, 111.5, 108.5, 109.2), (109.2, 110.5, 109.5, 110)]
h_st = [b[1] for b in stale_bars]
l_st = [b[2] for b in stale_bars]
c_st = [b[3] for b in stale_bars]
t_st = list(range(1000, 1012))
check("stale-level sweep ignored",
      len(detect_sweeps(h_st, l_st, c_st, t_st, 12, 2, 2, 1.0)) == 0,
      f"{len(detect_sweeps(h_st, l_st, c_st, t_st, 12, 2, 2, 1.0))}")
# Control: the same setup but bar 10 wicks ABOVE the newest high (114.5) and
# closes back inside -> one sweep of H2=113.5.
ctrl_bars = list(stale_bars)
ctrl_bars[10] = (110.5, 114.5, 109.0, 112.8)
h_ct = [b[1] for b in ctrl_bars]
l_ct = [b[2] for b in ctrl_bars]
c_ct = [b[3] for b in ctrl_bars]
sw_ctrl = detect_sweeps(h_ct, l_ct, c_ct, t_st, 12, 2, 2, 1.0)
check("newest-level sweep fires", len(sw_ctrl) == 1 and close(sw_ctrl[0]["level"], 113.5)
      and sw_ctrl[0]["direction"] == -1 and close(sw_ctrl[0]["extreme"], 114.5),
      f"{sw_ctrl}")
check("buy-side sweep true", is_sweep(111.5, 108.0, 109.2, 110.5, 1.0, 0.1, True))
check("breakout close not a sweep", not is_sweep(111.5, 108.0, 111.2, 110.5, 1.0, 0.1, True))
check("no-exceed not a sweep", not is_sweep(109.8, 108.0, 109.2, 110.5, 1.0, 0.1, True))
check("wick must exceed min ATR", not is_sweep(110.55, 108.0, 109.2, 110.5, 1.0, 0.1, True))
check("sell-side sweep true", is_sweep(102.5, 98.2, 100.5, 99.5, 1.0, 0.1, False))

buy_sweep = [(100, 105.5, 99.5, 105), (105, 107.5, 104.5, 107), (107, 110.5, 106.5, 110),
             (110, 109.9, 107.5, 108), (108, 108.5, 105.5, 106), (106, 109.5, 105.5, 109),
             (109, 109.5, 106.5, 107), (107, 108.5, 106.5, 108), (108.5, 111.5, 108.0, 109.2),
             (109.2, 110.0, 108.5, 109.5)]
o_s1 = [b[0] for b in buy_sweep]
h_s1 = [b[1] for b in buy_sweep]
l_s1 = [b[2] for b in buy_sweep]
c_s1 = [b[3] for b in buy_sweep]
t_s1 = list(range(1000, 1010))
swp = detect_sweeps(h_s1, l_s1, c_s1, t_s1, 10, 2, 2, 1.0)
check("buy-side sweep detected", len(swp) == 1, f"got {len(swp)}")
check("buy-side sweep direction -1", swp[0]["direction"] == -1)
check("buy-side sweep level 110.5", close(swp[0]["level"], 110.5))
check("buy-side sweep extreme 111.5", close(swp[0]["extreme"], 111.5))
check("buy-side sweep at bar 8", swp[0]["time"] == 1008, f"{swp[0]['time']}")

sell_sweep = [(105, 105.5, 104.5, 105), (105, 103.5, 102.5, 103), (103, 100.5, 99.5, 100),
              (100, 101.5, 100.5, 101), (101, 103.0, 102.0, 102.5), (102.5, 101.0, 100.0, 100.5),
              (100.5, 102.5, 101.5, 102), (102, 102.5, 98.2, 100.5), (100.5, 101.0, 99.5, 100.8)]
o_s2 = [b[0] for b in sell_sweep]
h_s2 = [b[1] for b in sell_sweep]
l_s2 = [b[2] for b in sell_sweep]
c_s2 = [b[3] for b in sell_sweep]
t_s2 = list(range(1000, 1009))
swp2 = detect_sweeps(h_s2, l_s2, c_s2, t_s2, 9, 2, 2, 1.0)
check("sell-side sweep detected", len(swp2) == 1, f"got {len(swp2)}")
check("sell-side sweep direction +1", swp2[0]["direction"] == 1)
check("sell-side sweep extreme 98.2", close(swp2[0]["extreme"], 98.2))

print("[PHASE3] --- SupportResistance ---")
prices = [100, 100.1, 101, 99.9]
kinds = [1, -1, 1, -1]
times4 = list(range(0, 4))
lvl = sr_cluster(prices, kinds, times4, 1.0, 0.25, min_touches=2)
check("cluster keeps 1 level", len(lvl) == 1, f"got {len(lvl)}")
check("cluster level ~100", close(lvl[0]["level"], 100.0), f"{lvl[0]['level']}")
check("cluster touches 3", lvl[0]["touches"] == 3, f"{lvl[0]['touches']}")
check("cluster kind mixed -> -1", lvl[0]["kind"] == -1, f"{lvl[0]['kind']}")
q = sr_query_near(lvl, 100.2, 1.0, 0.25)
check("query near finds level", q is not None and close(q[0], 100.0) and q[1] == 3, f"{q}")
check("query outside tolerance misses", sr_query_near(lvl, 102.0, 1.0, 0.25) is None)

print("[PHASE3] --- DisplacementDetector ---")
check("big up bar is displacement", is_displacement(100, 104, 99, 103.8, 0.5))
check("big up direction +1", disp_detect([100], [104], [99], [103.8], [0], 1, 0.5)[0]["direction"] == 1)
check("big up score 1.0", close(disp_score(100, 104, 99, 103.8, 0.5), 1.0))
check("small bar not displacement", not is_displacement(100, 100.6, 99.4, 100.5, 0.5))
# 0.7*min(1, body_atr/2) + 0.3*min(1, range_atr/3) with body_atr=1.0, range_atr=2.4
check("small bar score 0.59", close(disp_score(100, 100.6, 99.4, 100.5, 0.5), 0.59, 1e-9),
      f"{disp_score(100, 100.6, 99.4, 100.5, 0.5)}")
check("big down bar is displacement", is_displacement(100, 101, 95, 95.5, 0.5))
d_down = disp_detect([100], [101], [95], [95.5], [0], 1, 0.5)
check("big down direction -1", d_down[0]["direction"] == -1)
check("mid-close not displacement", not is_displacement(100, 104, 99, 101.5, 0.5))

print("[PHASE3] --- StructureEngine (CandleEngine consumer) ---")
M5 = "M5"
eng = StructureEngine(swing_left=2, swing_right=2, window=32)

# BOS series -> bullish bias
ce2 = CandleEngine()
ce2.register(M5)
for i, c in enumerate([100, 101, 102, 103, 104, 103, 102, 106, 105, 106.5]):
    ce2.push(M5, c - 0.5, c + 0.5, c - 0.5, c, 2000 + i)
check("engine min-bars guard", not eng.update(CandleEngine(), M5, 1.0))
check("engine BOS update ok", eng.update(ce2, M5, 1.0))
check("engine BOS bias BULLISH", eng.bias == 1, f"bias={eng.bias}")
check("engine BOS last event BOS", eng.last_event == 1, f"ev={eng.last_event}")
check("engine BOS direction +1", eng.last_direction == 1)
check("engine swings detected", len(eng.swings) >= 1, f"{len(eng.swings)}")

# sweep series -> sweep event, neutral-ish bias (no BOS/CHOCH)
ce3 = CandleEngine()
ce3.register(M5)
for i, (o, h, l, c) in enumerate(buy_sweep):
    ce3.push(M5, o, h, l, c, 3000 + i)
check("engine sweep update ok", eng.update(ce3, M5, 1.0))
check("engine sweep count >= 1", len(eng.sweeps) >= 1, f"{len(eng.sweeps)}")
check("engine sweep last event", eng.last_event == 3, f"ev={eng.last_event}")
check("engine sweep direction -1", eng.last_direction == -1)

# CHOCH series -> bearish bias (CHOCH beats the earlier BOS by time)
ce4 = CandleEngine()
ce4.register(M5)
for i, c in enumerate(choch_down):
    ce4.push(M5, c - 0.5, c + 0.5, c - 0.5, c, 4000 + i)
check("engine CHOCH update ok", eng.update(ce4, M5, 1.0))
check("engine CHOCH bias BEARISH", eng.bias == -1, f"bias={eng.bias}")
check("engine CHOCH last event CHOCH", eng.last_event == 2, f"ev={eng.last_event}")
check("engine CHOCH direction -1", eng.last_direction == -1)

print(f"[PHASE3] === {PASS} passed, {FAIL} failed ===")
raise SystemExit(1 if FAIL > 0 else 0)
