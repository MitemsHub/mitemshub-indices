#!/usr/bin/env python3
"""Cross-validate the MQL5 Phase-3 StructureEngine against the Python SMC
structure on REAL R_75 M5 bars from the tick corpus.

The two engines measure structure differently:
  - MQL5 StructureEngine (mql5/MITEMSHUB_AI/Structure/): window-scan detector.
    Fractal swings are STRICT (high strictly greater / low strictly lesser over
    left+right closed bars) and usable only after the right guard confirms
    them.  Bias comes from the most recent BOS/CHOCH event, with the HH+HL /
    LH+LL swing sequence as fallback — there is no momentum fallback.
  - Python SMC (src/synthetic_trader/features/market_structure.py): per-LAST-
    bar flags over a window.  detect_swings is NON-strict (high == window max
    counts as a swing, so flat tops are swings).  bos_up/down and
    liquidity_sweep_up/down test only the final bar against the most recent
    swing.  structure_bias is HH+HL (+0.7) / LH+LL (-0.7) with a normalized
    price-momentum fallback when the swing sequence is inconclusive; the
    decision engine consumes it via structural_direction() -> LONG/SHORT/FLAT.

This harness maps both onto a common structure axis per 100-bar window,
measures agreement, and classifies the disagreements with context so they can
be reconciled before Phase 4 builds on the structure layer.  The MQL5-side
math comes from the phase3_logic_check.py mirror (exec'd from its definitions
section, so it stays in lockstep with the MQL5 code).

The BOS axis is measured on the SAME recency footing as the sweep axis
(last 8 bars + most-recent swing level) so the two event axes are comparable:
B2a = the last MQL5 BOS event in the last 8 bars against the still-live level
(sweep-style event view); B2b = the question-identical view (last-bar close vs
the most-recent strict swing level — Python's exact bos_up/bos_down question),
which isolates swing detection.  B2b's residual is then attributed to strict-
vs-flat-top swing counting (level-shift / fallback / no-swing) to answer
whether the fractal difference is the dominant cause of BOS disagreement.

It ALSO reports an event census of the MQL5 mirror over the whole corpus:
swing/BOS/CHOCH/sweep/displacement counts (deduped across the overlapping
windows so each event counts once), the per-day breakdown, and BIAS COVERAGE —
how often the engine commits to a direction and how long those bias regimes
persist before flipping.  That is the "is this structure layer actually giving
the strategy something to act on" measurement.
"""

import csv
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))

# --- load the mirror's definitions WITHOUT running its test block ------------
_MIRROR_SRC = open(os.path.join(_HERE, "phase3_logic_check.py"), encoding="utf-8").read()
_MIRROR_NS: dict = {}
exec(_MIRROR_SRC.split("# ============================ TESTS")[0], _MIRROR_NS)
MqlEngine = _MIRROR_NS["StructureEngine"]
MqlCandleEngine = _MIRROR_NS["CandleEngine"]

# --- Python side (the real production SMC feature code) -----------------------
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
from synthetic_trader.domain import Candle, Direction  # noqa: E402
from synthetic_trader.features.market_structure import (  # noqa: E402
    detect_swings,
    market_structure_features,
    structural_direction,
)

# --- config (mirrors MITEMSHUB_AI Core/Config.mqh defaults) ------------------
ATR_PERIOD = 14
STRUCTURE_LOOKBACK = 100   # DEFAULT_STRUCTURE_LOOKBACK
TF = 300                   # M5 — the execution timeframe the engine runs on
STEP = 5                   # window slide (bars)
SWING_LR = 2               # Python detect_swings default (left=2, right=2)

CORPUS_PATHS = [
    os.path.join(_HERE, "..", "data", "backfill", "R_75_ticks.csv"),
    os.path.join(_HERE, "..", "data", "R_75_ticks.csv"),
]


def wilder_atr_series(hlc):
    """Replicate Market/VolatilityEngine.mqh Wilder ATR(14)."""
    atrs = []
    atr = None
    prev_close = 0.0
    for high, low, close in hlc:
        tr = high - low
        if prev_close > 0.0:
            tr = max(tr, abs(high - prev_close), abs(low - prev_close))
        atr = tr if atr is None else (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        atrs.append(atr)
        prev_close = close
    return atrs


def load_m5_bars(paths):
    ticks = []
    seen = set()
    for p in paths:
        if not os.path.exists(p):
            print(f"  (missing corpus: {p})", file=sys.stderr)
            continue
        with open(p, newline="", encoding="utf-8") as f:
            next(f, None)  # header
            prev = None
            for row in csv.reader(f):
                try:
                    epoch = float(row[0])
                    price = float(row[2])
                except (ValueError, IndexError):
                    continue
                if not (100.0 <= price <= 5000.0):
                    continue
                if prev is not None and abs(price - prev) / prev > 0.30:
                    continue  # single-tick jump ~3.7x is corrupted data
                k = round(epoch, 6)
                if k in seen:
                    continue
                seen.add(k)
                ticks.append((epoch, price))
                prev = price
    ticks.sort(key=lambda t: t[0])
    bars = []
    for epoch, price in ticks:
        bucket = int(epoch // TF)
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            bars[-1] = (bucket, b[1], max(b[2], price), min(b[3], price), price)
        else:
            bars.append((bucket, price, price, price, price))
    return bars


def py_bias_sign(struct_bias, dead=0.05):
    if struct_bias > dead:
        return 1
    if struct_bias < -dead:
        return -1
    return 0


def main():
    print("loading ticks -> M5 bars ...")
    bars = load_m5_bars(CORPUS_PATHS)
    if len(bars) < STRUCTURE_LOOKBACK + 20:
        print(f"not enough bars ({len(bars)})", file=sys.stderr)
        return 1
    closes = [b[4] for b in bars]
    hlc = [(b[2], b[3], b[4]) for b in bars]
    atrs = wilder_atr_series(hlc)
    span_h = len(bars) * TF / 3600.0
    print(f"bars={len(bars)}  ({span_h:.1f} hours of M5)  "
          f"close range {min(closes):.2f}..{max(closes):.2f}")

    # --- classify every window with both engines ------------------------------
    # rows carry one entry per window for every axis:
    #   mb    MQL5 bias (+1/0/-1)
    #   pb    Python structure_bias sign
    #   pbraw Python structure_bias raw value (|0.7| = swing-sequence derived)
    #   pdir  Python structural_direction (1/-1/0)
    #   mbo   MQL5 last BOS direction (1/-1/0)
    #   pbo   Python bos_up/bos_down on the last bar (1/-1/0)
    #   msw   MQL5 last sweep direction (1/-1/0) — anywhere in the window
    #   msw_r MQL5 last sweep direction when it is within the last 8 bars (0 else)
    #   psw   Python sweep flags (1=below-low bullish, -1=above-high bearish, 0)
    #   mdp   MQL5 displacement present in window (1/0)
    #   pdp   Python displacement_atr >= 2.0 on last bar (1/0)
    #   mbev  MQL5 bias driver: 1 = BOS/CHOCH event, 0 = swing sequence
    #   nsw_m / nsw_p  swing counts
    rows = []
    for i in range(STRUCTURE_LOOKBACK, len(closes), STEP):
        win_bars = bars[i - STRUCTURE_LOOKBACK + 1: i + 1]
        candles = [
            Candle(symbol="R_75", timeframe_sec=TF, open_time=int(b[0]),
                   open=b[1], high=b[2], low=b[3], close=b[4])
            for b in win_bars
        ]
        end_bucket = int(bars[i][0])
        recent8_bucket = int(bars[max(0, i - 7)][0])   # Python scans candles[-8:]

        # Python side — the real production functions
        feats = market_structure_features(candles)
        pdir_raw = structural_direction(feats)
        pdir = {Direction.LONG: 1, Direction.SHORT: -1, Direction.FLAT: 0}[pdir_raw]
        pbraw = feats.get("structure_bias", 0.0)
        pb = py_bias_sign(pbraw)
        pbo = 1 if feats.get("bos_up", 0.0) else (-1 if feats.get("bos_down", 0.0) else 0)
        psw = 1 if feats.get("liquidity_sweep_down", 0.0) else (
            -1 if feats.get("liquidity_sweep_up", 0.0) else 0)
        pdp = 1 if feats.get("displacement_atr", 0.0) >= 2.0 else 0
        nsw_p = len(detect_swings(candles[:-1], left=SWING_LR, right=SWING_LR))

        # MQL5 side — mirror of StructureEngine over the same window
        ce = MqlCandleEngine()
        ce.register("M5")
        for b in win_bars:
            ce.push("M5", b[1], b[2], b[3], b[4], int(b[0]))
        eng = MqlEngine(swing_left=SWING_LR, swing_right=SWING_LR, window=STRUCTURE_LOOKBACK)
        if not eng.update(ce, "M5", atrs[i]):
            continue
        mb = eng.bias
        mbev = 1 if eng.last_event in (1, 2) else 0     # BOS or CHOCH drives bias
        mbo = eng.last_direction if eng.last_event == 1 else 0   # 1 = BOS
        mbo_r = mbo if (eng.last_event == 1 and eng.last_event_time >= recent8_bucket) else 0
        msw = eng.sweeps[-1]["direction"] if eng.sweeps else 0
        msw_r = 0
        for s in reversed(eng.sweeps):
            if s["time"] >= recent8_bucket:
                msw_r = s["direction"]
                break
        mdp = 1 if len(eng.disp) > 0 else 0
        nsw_m = len(eng.swings)

        # --- BOS on the same recency footing as sweeps -------------------------
        # The sweep reconciliation aligned MQL5 sweeps to Python's exact
        # semantics: most-recent swing level of each polarity + last 8 bars.
        # Mirror it for BOS.  Two views:
        #   m_bo_r8_lvl — sweep-style EVENT view: the last MQL5 BOS event inside
        #                 the last 8 bars whose broken level is still the live
        #                 most-recent swing level (an event against a level that
        #                 a newer swing replaced is stale, exactly like a sweep
        #                 of an old level).
        #   m_bo_lvl    — question-IDENTICAL view: last-bar close vs the most-
        #                 recent strict swing level, i.e. Python's bos_up/down
        #                 question answered with MQL5 swings.  This isolates
        #                 swing DETECTION (strict vs non-strict fractal) as the
        #                 only remaining difference.
        last_close = win_bars[-1][4]   # the window's last close — not corpus-wide!
        m_rh = m_rl = 0.0
        m_rh_bar = m_rl_bar = -1
        for s in eng.swings:
            if s["direction"] > 0:
                m_rh, m_rh_bar = s["price"], s["bar"]
            else:
                m_rl, m_rl_bar = s["price"], s["bar"]
        m_bo_lvl = (1 if (m_rh > 0.0 and last_close > m_rh)
                    else (-1 if (m_rl > 0.0 and last_close < m_rl) else 0))
        m_bo_r8_lvl = 0
        for b in reversed(eng.bos):
            if b["time"] >= recent8_bucket:
                live_lvl = m_rh if b["direction"] > 0 else m_rl
                if live_lvl > 0.0 and abs(b["level"] - live_lvl) <= 1e-9 * max(live_lvl, 1.0):
                    m_bo_r8_lvl = b["direction"]
                break
        # Python swing detail: whether its recent level came from a real swing
        # or the max/min-of-last-20 fallback, and the level prices themselves.
        py_swings = detect_swings(candles[:-1], left=SWING_LR, right=SWING_LR)
        nsw_p = len(py_swings)
        p_has_sh = any(s.kind == "high" for s in py_swings)
        p_has_sl = any(s.kind == "low" for s in py_swings)
        prh = feats.get("recent_swing_high", 0.0)
        prl = feats.get("recent_swing_low", 0.0)

        rows.append(dict(i=i, close=closes[i], atr=atrs[i], mb=mb, pb=pb, pbraw=pbraw, pdir=pdir,
                         mbo=mbo, mbo_r=mbo_r, pbo=pbo, msw=msw, msw_r=msw_r, psw=psw,
                         mdp=mdp, pdp=pdp, mbev=mbev, nsw_m=nsw_m, nsw_p=nsw_p,
                         m_bo_lvl=m_bo_lvl, m_bo_r8_lvl=m_bo_r8_lvl,
                         m_rh=m_rh, m_rl=m_rl, m_rh_bar=m_rh_bar, m_rl_bar=m_rl_bar,
                         prh=prh, prl=prl, p_has_sh=p_has_sh, p_has_sl=p_has_sl,
                         swings=eng.swings, bos=eng.bos, choch=eng.choch,
                         sweeps=eng.sweeps, disp=eng.disp,
                         win0=bars[i - STRUCTURE_LOOKBACK + 1][0]))

    n = len(rows)
    print(f"\nwindows compared: {n}   "
          f"(100-bar M5 window, slide {STEP} bars, swing left=right={SWING_LR})")

    # --- Axis A1: bias (MQL5 Bias vs Python structure_bias sign) --------------
    agree_b = sum(1 for r in rows if r["mb"] == r["pb"])
    print(f"\n=== AXIS A1 — structure bias: MQL5 Bias() vs Python structure_bias sign ===")
    print(f"agreement: {agree_b} / {n} ({100.0 * agree_b / n:.1f}%)")
    print("\ncontingency (MQL5 rows x Python cols):")
    print("MQL5 \\ py    bearish  neutral  bullish   total")
    conf_b = Counter((r["mb"], r["pb"]) for r in rows)
    tot_m = Counter(r["mb"] for r in rows)
    for m in (1, 0, -1):
        c = conf_b.get((m, -1), 0), conf_b.get((m, 0), 0), conf_b.get((m, 1), 0)
        print(f"{m:>11}  {c[0]:>7}  {c[1]:>7}  {c[2]:>7}   {tot_m[m]:>5}")

    # --- Axis A2: MQL5 bias vs Python structural_direction --------------------
    agree_d = sum(1 for r in rows if r["mb"] == r["pdir"])
    print(f"\n=== AXIS A2 — bias vs Python structural_direction (LONG/SHORT/FLAT) ===")
    print(f"agreement: {agree_d} / {n} ({100.0 * agree_d / n:.1f}%)")

    # --- Axis B: BOS -----------------------------------------------------------
    agree_bos = sum(1 for r in rows if r["mbo"] == r["pbo"])
    agree_bos_r = sum(1 for r in rows if r["mbo_r"] == r["pbo"])
    print(f"\n=== AXIS B — BOS: MQL5 last-event BOS vs Python bos_up/bos_down ===")
    print(f"agreement (MQL5 scans whole window): {agree_bos} / {n} ({100.0 * agree_bos / n:.1f}%)")
    print(f"agreement (MQL5 BOS within last 8 bars): {agree_bos_r} / {n} ({100.0 * agree_bos_r / n:.1f}%)")
    conf_bos = Counter((r["mbo_r"], r["pbo"]) for r in rows)
    print("MQL5(recent) \\ py    down  none  up   total")
    for m in (-1, 0, 1):
        c = conf_bos.get((m, -1), 0), conf_bos.get((m, 0), 0), conf_bos.get((m, 1), 0)
        print(f"{m:>13}  {c[0]:>4}  {c[1]:>4}  {c[2]:>4}   {sum(c):>5}")

    # --- Axis B2: BOS aligned to the same footing as sweeps --------------------
    # The sweep reconciliation (Axis C) aligned MQL5 sweeps to Python's exact
    # semantics: most-recent swing level of each polarity + the last 8 bars.
    # Do the same for BOS on two levels of strictness:
    #   B2a — sweep-style EVENT view: last MQL5 BOS event within the last 8 bars
    #         whose broken level is still the live most-recent swing level.
    #   B2b — question-IDENTICAL view: last-bar close vs the most-recent strict
    #         swing level — exactly Python's bos_up/bos_down question, answered
    #         with MQL5 swings.  Only swing detection (strict vs non-strict)
    #         differs, so B2b isolates it.
    agree_b2a = sum(1 for r in rows if r["m_bo_r8_lvl"] == r["pbo"])
    agree_b2b = sum(1 for r in rows if r["m_bo_lvl"] == r["pbo"])
    n_b2a_fire = sum(1 for r in rows if r["m_bo_r8_lvl"] != 0)
    n_b2b_fire = sum(1 for r in rows if r["m_bo_lvl"] != 0)
    print(f"\n=== AXIS B2 — BOS on the sweep footing (last 8 bars + most-recent swing level) ===")
    print(f"B2a (event view, live level, last 8 bars): "
          f"{agree_b2a} / {n} ({100.0 * agree_b2a / n:.1f}%)   "
          f"MQL5 fires: {n_b2a_fire} / {n}")
    print(f"B2b (same question as Python: last close vs most-recent swing level): "
          f"{agree_b2b} / {n} ({100.0 * agree_b2b / n:.1f}%)   "
          f"MQL5 fires: {n_b2b_fire} / {n}")
    conf_b2b = Counter((r["m_bo_lvl"], r["pbo"]) for r in rows)
    print("B2b contingency  MQL5 \\ py    down  none  up   total")
    for m in (-1, 0, 1):
        c = conf_b2b.get((m, -1), 0), conf_b2b.get((m, 0), 0), conf_b2b.get((m, 1), 0)
        print(f"{m:>18}  {c[0]:>4}  {c[1]:>4}  {c[2]:>4}   {sum(c):>5}")

    # recent-level agreement: how often strict and non-strict swing counting
    # pick the same most-recent reference level (the thing BOS actually tests)
    def _lvl_same(a, b, atr):
        return a > 0.0 and b > 0.0 and abs(a - b) <= max(0.1 * atr, 1e-9 * max(a, b))

    def _lvl_bucket(m_lvl, p_lvl, p_have):
        if m_lvl > 0.0 and p_have:
            return "same" if _lvl_same(m_lvl, p_lvl, 0.0) else "differs"
        if m_lvl > 0.0 and not p_have:
            return "m-only"
        if m_lvl <= 0.0 and p_have:
            return "p-only"
        return "neither"

    lvl_buckets = Counter(
        (_lvl_bucket(r["m_rh"], r["prh"], r["p_has_sh"]),
         _lvl_bucket(r["m_rl"], r["prl"], r["p_has_sl"])) for r in rows)
    print("\nrecent-level agreement (strict vs non-strict swing counting):")
    print("  (high-level bucket, low-level bucket)  count")
    for k in sorted(lvl_buckets):
        print(f"  {k}  {lvl_buckets[k]:>5}")
    same_hl = sum(c for (h, l), c in lvl_buckets.items() if h == "same" and l == "same")
    gap_hl = [abs(r["m_rh"] - r["prh"]) / r["atr"] for r in rows
              if r["m_rh"] > 0.0 and r["p_has_sh"]
              and not _lvl_same(r["m_rh"], r["prh"], r["atr"])]
    gap_ll = [abs(r["m_rl"] - r["prl"]) / r["atr"] for r in rows
              if r["m_rl"] > 0.0 and r["p_has_sl"]
              and not _lvl_same(r["m_rl"], r["prl"], r["atr"])]
    print(f"  both polarities pick the same recent level: {same_hl} / {n} "
          f"({100.0 * same_hl / n:.1f}%)")
    if gap_hl:
        print(f"  high-level gap when differing: mean {sum(gap_hl) / len(gap_hl):.2f} ATR "
              f"(max {max(gap_hl):.2f}, {len(gap_hl)} windows)")
    if gap_ll:
        print(f"  low-level gap when differing:  mean {sum(gap_ll) / len(gap_ll):.2f} ATR "
              f"(max {max(gap_ll):.2f}, {len(gap_ll)} windows)")

    # --- B2b residual attribution: is strict-vs-flat-top the dominant cause? ---
    causes = Counter()
    cause_ex = {}
    for r in rows:
        if r["m_bo_lvl"] == r["pbo"]:
            continue
        if r["m_bo_lvl"] == 1 or r["pbo"] == 1:
            m_lvl, p_lvl, p_have, m_bar = r["m_rh"], r["prh"], r["p_has_sh"], r["m_rh_bar"]
        else:
            m_lvl, p_lvl, p_have, m_bar = r["m_rl"], r["prl"], r["p_has_sl"], r["m_rl_bar"]
        if m_lvl > 0.0 and p_have:
            # both sides have a real recent swing level: flags can differ only
            # when the close sits between the two levels (or on one) — i.e.
            # the two engines disagree about WHICH level is the live reference.
            # That is the strict-vs-flat-top swing-counting footprint.
            edge = m_bar >= STRUCTURE_LOOKBACK - SWING_LR - 2   # newest bar both engines can reach
            cause = ("level-shift: close between strict and non-strict recent levels"
                     + (" [window-edge recency]" if edge else " [flat-top recency]"))
        elif m_lvl > 0.0 and not p_have:
            cause = "Python fallback (no non-strict swings) vs MQL5 strict level"
        elif m_lvl <= 0.0 and p_have:
            cause = "MQL5 no swing (strict fractal misses it) vs Python level"
        else:
            cause = "neither found a swing of that polarity (quiet window)"
        causes[cause] += 1
        cause_ex.setdefault(cause, []).append(r)
    total_d = sum(causes.values())
    n_shift = sum(c for k, c in causes.items() if k.startswith("level-shift"))
    n_shift_flat = sum(c for k, c in causes.items() if k.startswith("level-shift") and "flat-top" in k)
    print("\nB2b residual attribution (windows where the same question gets different answers):")
    for cause, c in causes.most_common():
        ex = cause_ex[cause][:2]
        ex_s = ", ".join(f"bar {r['i']} @ {r['close']:.1f}" for r in ex)
        print(f"  {cause:<70} {c:>4}   e.g. {ex_s}")
    if total_d:
        pct = 100.0 * n_shift / total_d
        if n_shift == total_d and n_shift_flat == 0:
            verdict = (f"level-shift driven, and the level shift is 100% window-edge "
                       f"recency (MQL5's right guard uses the current bar; Python's "
                       f"candles[:-1] excludes it) — NOT flat-top swing counting")
        elif n_shift == total_d:
            verdict = f"level-shift driven ({n_shift_flat} flat-top recency, " \
                      f"{total_d - n_shift_flat} window-edge recency)"
        else:
            verdict = (f"level-shift driven ({pct:.1f}%); the rest are "
                       f"fallback/no-swing/quiet-window semantics")
        print(f"\nverdict: {n_shift} of {total_d} BOS residuals ({pct:.1f}%) are "
              f"{verdict}.")

    # --- Axis C: sweep -----------------------------------------------------------
    # Python only looks at the last 8 bars against the MOST RECENT swing; MQL5
    # scans the whole window per level.  Report both the raw comparison and the
    # recency-aligned one (MQL5 sweep within the last 8 bars) — the aligned
    # number is the honest apples-to-apples measurement.
    agree_sw = sum(1 for r in rows if r["msw"] == r["psw"])
    agree_sw_r = sum(1 for r in rows if r["msw_r"] == r["psw"])
    n_msw_recent = sum(1 for r in rows if r["msw_r"] != 0)
    print(f"\n=== AXIS C — sweep: MQL5 vs Python liquidity_sweep flags ===")
    print(f"raw agreement (MQL5 sweep anywhere in window): {agree_sw} / {n} ({100.0 * agree_sw / n:.1f}%)")
    print(f"windows with an MQL5 sweep anywhere in the window: {n - sum(1 for r in rows if r['msw'] == 0)} / {n} "
          f"(over-fire: window-scan almost always finds one)")
    print(f"windows with an MQL5 sweep in the last 8 bars: {n_msw_recent} / {n}")
    print(f"recency-aligned agreement (both engines look at the last 8 bars): "
          f"{agree_sw_r} / {n} ({100.0 * agree_sw_r / n:.1f}%)")
    conf_sw = Counter((r["msw_r"], r["psw"]) for r in rows)
    print("MQL5(recent) \\ py    down  none  up   total")
    for m in (-1, 0, 1):
        c = conf_sw.get((m, -1), 0), conf_sw.get((m, 0), 0), conf_sw.get((m, 1), 0)
        print(f"{m:>13}  {c[0]:>4}  {c[1]:>4}  {c[2]:>4}   {sum(c):>5}")

    # --- Axis D: displacement -----------------------------------------------------
    agree_dp = sum(1 for r in rows if r["mdp"] == r["pdp"])
    print(f"\n=== AXIS D — displacement: MQL5 window displacement vs Python displacement_atr>=2 ===")
    print(f"agreement: {agree_dp} / {n} ({100.0 * agree_dp / n:.1f}%)")

    # --- swing-count comparison (strict vs non-strict fractal) ---------------------
    diffs = [r["nsw_m"] - r["nsw_p"] for r in rows]
    n_same = sum(1 for d in diffs if d == 0)
    n_more = sum(1 for d in diffs if d > 0)
    n_less = sum(1 for d in diffs if d < 0)
    print(f"\n=== swing counts per window: MQL5 (strict) vs Python (non-strict) ===")
    print(f"same: {n_same}   MQL5 fewer: {n_less}   MQL5 more: {n_more}   "
          f"mean diff {sum(diffs) / len(diffs):+.2f} swings")

    # --- disagreement buckets with example windows --------------------------------
    print("\n=== disagreement buckets (examples: window-end bar, close) ===")
    flips = [r for r in rows if r["mb"] == -r["pb"] and r["pb"] != 0]
    flips_event = sum(1 for r in flips if r["mbev"] == 1)
    flips_py_mom = sum(1 for r in flips if abs(r["pbraw"]) < 0.69)   # momentum fallback
    buckets = {
        "A1 MQL5 0 / py +": [r for r in rows if r["mb"] == 0 and r["pb"] == 1],
        "A1 MQL5 0 / py -": [r for r in rows if r["mb"] == 0 and r["pb"] == -1],
        "A1 MQL5 + / py 0": [r for r in rows if r["mb"] == 1 and r["pb"] == 0],
        "A1 MQL5 - / py 0": [r for r in rows if r["mb"] == -1 and r["pb"] == 0],
        "A1 flipped (+/-)": flips,
        "  ..flip w/ MQL5 event driver": [r for r in flips if r["mbev"] == 1],
        "  ..flip w/ py momentum fallback": [r for r in flips if abs(r["pbraw"]) < 0.69],
        "B MQL5 BOS, py none": [r for r in rows if r["mbo"] != 0 and r["pbo"] == 0],
        "B py BOS, MQL5 none": [r for r in rows if r["mbo"] == 0 and r["pbo"] != 0],
        "C sweep MQL5 only (raw)": [r for r in rows if r["msw"] != 0 and r["psw"] == 0],
        "C sweep py only (raw)": [r for r in rows if r["msw"] == 0 and r["psw"] != 0],
        "C sweep MQL5 recent only": [r for r in rows if r["msw_r"] != 0 and r["psw"] == 0],
        "C sweep py only (recent)": [r for r in rows if r["msw_r"] == 0 and r["psw"] != 0],
    }
    for name, lst in buckets.items():
        if not lst:
            print(f"  {name:<28} 0")
            continue
        ex = lst[:2]
        ex_s = ", ".join(f"bar {r['i']} @ {r['close']:.1f} (mb={r['mb']} pb={r['pb']})"
                         for r in ex)
        print(f"  {name:<28} {len(lst):>4}   e.g. {ex_s}")
    print(f"\nflip diagnosis: {len(flips)} flips — {flips_event} driven by an MQL5 "
          f"BOS/CHOCH event, {flips_py_mom} driven by Python's momentum fallback "
          f"(|bias| != 0.7)")

    # --- event census (MQL5 mirror, deduped across overlapping windows) --------
    # Windows overlap (STEP=5), so a single event appears in many windows.  For
    # an honest corpus-wide count, dedupe by (type, bar-time).  Bias is a state,
    # not an event — coverage uses the raw window sequence.
    import datetime as _dt

    def _day(bucket):
        return _dt.datetime.utcfromtimestamp(bucket * TF).date().isoformat()

    events: dict = {}          # (type, time) -> direction  (dedupe key)
    per_day: dict = {}         # day -> Counter(type)

    def _add(kind, t, direction, detail_key):
        key = (kind, t)
        if key in events:
            return                     # same event seen via an overlapping window
        events[key] = direction
        per_day.setdefault(_day(t), Counter())[detail_key] += 1

    for r in rows:
        for ev in r["swings"]:
            _add("swing", ev["time"], ev["direction"],
                 "swing_high" if ev["direction"] > 0 else "swing_low")
        for ev in r["bos"]:
            _add("bos", ev["time"], ev["direction"],
                 "bos_up" if ev["direction"] > 0 else "bos_down")
        for ev in r["choch"]:
            _add("choch", ev["time"], ev["direction"],
                 "choch_up" if ev["direction"] > 0 else "choch_down")
        for ev in r["sweeps"]:
            _add("sweep", ev["time"], ev["direction"],
                 "sweep_buy_side" if ev["direction"] < 0 else "sweep_sell_side")
        for ev in r["disp"]:
            # displacement carries a window-relative bar; windows are contiguous
            t = r["win0"] + ev["bar"]
            _add("displacement", t, ev["direction"], "displacement")

    by_type = Counter(kind for kind, _ in events)
    by_dir = Counter((kind, d) for (kind, _), d in events.items())
    print("\n=== event census (MQL5 StructureEngine mirror, deduped across windows) ===")
    print(f"total events: {len(events)}  ("
          f"{by_type.get('swing', 0)} swings, {by_type.get('bos', 0)} BOS, "
          f"{by_type.get('choch', 0)} CHOCH, {by_type.get('sweep', 0)} sweeps, "
          f"{by_type.get('displacement', 0)} displacement bars)")
    print(f"  swings: {by_dir.get(('swing', 1), 0)} high / {by_dir.get(('swing', -1), 0)} low")
    print(f"  BOS:    {by_dir.get(('bos', 1), 0)} up / {by_dir.get(('bos', -1), 0)} down")
    print(f"  CHOCH:  {by_dir.get(('choch', 1), 0)} up / {by_dir.get(('choch', -1), 0)} down")
    print(f"  sweeps: {by_dir.get(('sweep', -1), 0)} buy-side (above high) / "
          f"{by_dir.get(('sweep', 1), 0)} sell-side (below low)")
    print("  per-day (deduped):")
    print(f"    {'day':<12} {'bars':>5} {'swH':>4} {'swL':>4} {'bosU':>4} {'bosD':>4} "
          f"{'chU':>4} {'chD':>4} {'swpB':>4} {'swpS':>4} {'disp':>5}")
    day_bars = Counter(_day(bars[i][0]) for i in range(STRUCTURE_LOOKBACK, len(closes), STEP))
    for day in sorted(per_day):
        c = per_day[day]
        print(f"    {day:<12} {day_bars.get(day, 0):>5} {c.get('swing_high', 0):>4} "
              f"{c.get('swing_low', 0):>4} {c.get('bos_up', 0):>4} {c.get('bos_down', 0):>4} "
              f"{c.get('choch_up', 0):>4} {c.get('choch_down', 0):>4} "
              f"{c.get('sweep_buy_side', 0):>4} {c.get('sweep_sell_side', 0):>4} "
              f"{c.get('displacement', 0):>5}")

    # --- bias coverage -----------------------------------------------------------
    biases = [r["mb"] for r in rows]
    nb = biases.count(1)
    ns = biases.count(-1)
    n0 = biases.count(0)
    # regime runs: consecutive windows with the same non-neutral bias
    runs = []
    cur_sign, cur_len = 0, 0
    flips = 0
    for b in biases:
        if b == 0:
            if cur_len > 0:
                runs.append(cur_len)
                cur_len = 0
            cur_sign = 0
            continue
        if cur_sign == 0:
            cur_sign = b
            cur_len = 1
        elif b == cur_sign:
            cur_len += 1
        else:
            runs.append(cur_len)
            flips += 1
            cur_sign = b
            cur_len = 1
    if cur_len > 0:
        runs.append(cur_len)
    mean_run = sum(runs) / len(runs) if runs else 0.0
    max_run = max(runs) if runs else 0
    print("\n=== bias coverage (MQL5 StructureEngine mirror) ===")
    print(f"windows: {len(biases)}  bullish {nb} ({100.0 * nb / len(biases):.1f}%)  "
          f"bearish {ns} ({100.0 * ns / len(biases):.1f}%)  "
          f"neutral {n0} ({100.0 * n0 / len(biases):.1f}%)")
    print(f"bias regime runs: {len(runs)}  mean {mean_run:.1f} windows (~{mean_run * STEP * TF / 3600.0:.1f}h)  "
          f"longest {max_run} windows (~{max_run * STEP * TF / 3600.0:.1f}h)")
    print(f"sign flips between consecutive windows: {flips}  "
          f"({100.0 * flips / max(1, len(biases) - 1):.1f}% of transitions)")
    if runs:
        buckets = {"1": sum(1 for x in runs if x == 1),
                   "2-3": sum(1 for x in runs if 2 <= x <= 3),
                   "4+": sum(1 for x in runs if x >= 4)}
        print(f"run-length distribution: {dict(buckets)}")

    print("\nDone. Reconcile the buckets above before Phase 4 (see README).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
