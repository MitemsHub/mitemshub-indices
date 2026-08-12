#!/usr/bin/env python3
"""Re-check the UTC 12-24h & |range_z|<1.0 sniper entry cell as the corpus
compounds past ~15 days.

The entry-filter sweep (2026-08-11, ~9.5-day corpus) found:
  UTC 12-24h & |range_z|<1.0 : n=34, medMFE +1.10R, hit 58.8% at RR 1.2 AND
  RR 1.5 (vs floors 50%/45%), exp +0.246R / +0.267R.
This script re-runs the SAME methodology on the CURRENT corpus: one real
`run_ticks` capture (production broker, fixed 1.9R target, fresh model),
then replays every captured trade's intrabar path under production-legal
targets (RR 1.2 / 1.5, stop fixed at 1R, stop-first semantics) for the
filtered cells.  Fidelity is verified first: replay at RR 1.9 must
reproduce the realized hit exactly.

Watch target: does hit 58% / exp +0.25R hold at n >= 60 (≈ 16.5+ days at
~3.6 cell-trades/day)?

Usage:  python mql5/utc_cell_recheck.py [--timeframe 300]
"""
import argparse
import os
import sys
import time
from statistics import mean

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from tradequality_real_corpus_check import (  # noqa: E402
    CapturePaperBroker,
    clear_assembler_caches,
    dedupe_ticks,
    load_ticks_csv,
    run_sniper_ticks_captured,
    CORPUS_PATHS,
)


class FeatureCaptureBroker(CapturePaperBroker):
    """Records each position's entry-time features (hour + |range_z_50| +
    the GARCH vol features) at submit, so the filtered replay and the
    deep-vs-shallow / vol-regime profile use ONLY entry-time information.
    Also records the CLOSE of every path bar so the replay's time/close
    exit matches the real broker's close-price exit exactly (approximating
    with low/high biased wins down and broke the fidelity check)."""

    def __init__(self, config):
        super().__init__(config)
        self.features_by_pid = {}
        self.closes = {}

    def submit(self, intent):
        pos = super().submit(intent)
        s = intent.signal
        feats = s.snapshot.features
        self.features_by_pid[pos.id] = {
            "epoch": s.snapshot.epoch,
            "range_z_50": feats.get("range_z_50", 0.0),
            "garch_z_score": feats.get("garch_z_score", 0.0),
            "garch_vol_ratio": feats.get("garch_vol_ratio", 1.0),
            "garch_vol_regime": feats.get("garch_vol_regime", 1.0),
        }
        self.closes[pos.id] = []
        return pos

    def _maybe_close(self, position, candle):
        self.closes[position.id].append(candle.close)
        return super()._maybe_close(position, candle)


def replay(entry, stop, direction, target, path, closes):
    """Stop-first replay of a captured intrabar path under a different target.
    Returns the realized R (stop -1R, target +RR, else exit at the bar's
    CLOSE — the same close-price exit the real broker uses)."""
    risk = abs(entry - stop) or entry * 0.001
    for i, (high, low) in enumerate(path):
        if direction > 0:
            if low <= stop:
                return -1.0
            if high >= target:
                return abs(target - entry) / risk
        else:
            if high >= stop:
                return -1.0
            if low <= target:
                return abs(target - entry) / risk
    close = closes[-1]
    return (close - entry) / risk if direction > 0 else (entry - close) / risk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", type=int, default=300)
    args = ap.parse_args()

    ticks = dedupe_ticks([
        t for p in CORPUS_PATHS if os.path.exists(p)
        for t in load_ticks_csv(p, default_symbol="R_75")
    ])
    span = (max(t.epoch for t in ticks) - min(t.epoch for t in ticks)) / 86400
    print(f"[UTC] loaded {len(ticks)} R_75 ticks ({span:.2f} days)")

    # Patch the broker class used by run_sniper_ticks_captured so entry
    # features are captured per position during the real run.
    import tradequality_real_corpus_check as tqc

    tqc.CapturePaperBroker = FeatureCaptureBroker
    clear_assembler_caches()
    outcomes, broker, signals, rejected, model = run_sniper_ticks_captured(
        ticks, args.timeframe)
    print(f"[UTC] capture: signals={signals} rejected={rejected} "
          f"closed={len(outcomes)} model={model.version}")

    rows = []
    for o in outcomes:
        pid = o.position_id
        entry, stop, target, d = broker.geometry[pid]
        path = broker.paths[pid]
        feat = broker.features_by_pid[pid]
        closes = broker.closes[pid]
        risk = abs(entry - stop) or entry * 0.001
        rr_planned = abs(target - entry) / risk
        mfe = 0.0
        for high, low in path:
            mfe = max(mfe, (high - entry) / risk if d > 0 else (entry - low) / risk)
        rows.append({
            "hour": time.gmtime(feat["epoch"]).tm_hour,
            "rz": abs(feat["range_z_50"]),
            "gz": abs(feat["garch_z_score"]),
            "vr": feat["garch_vol_ratio"],
            "rr_planned": rr_planned,
            "realized_r": o.return_r,
            "realized_win": o.won,
            "mfe": mfe,
            "entry": entry, "stop": stop, "d": d, "path": path,
            "closes": closes,
        })
    del broker  # closed positions no longer live on the broker; rows hold all

    def cell_stats(cell_rows, target_rr):
        n = len(cell_rows)
        hits = 0
        rs = []
        for r in cell_rows:
            target = r["entry"] + target_rr * abs(r["entry"] - r["stop"]) \
                if r["d"] > 0 else r["entry"] - target_rr * abs(r["entry"] - r["stop"])
            rr = replay(r["entry"], r["stop"], r["d"], target, r["path"], r["closes"])
            rs.append(rr)
            if rr > 0:
                hits += 1
        hit = hits / n if n else 0.0
        exp = mean(rs) if rs else 0.0
        med_mfe = sorted(r["mfe"] for r in cell_rows)[n // 2] if n else 0.0
        return n, hit, exp, med_mfe

    # Fidelity: replay at the production 1.9R target must reproduce the
    # realized hit exactly (the capture already traded that geometry).
    fid_n, fid_hit, fid_exp, _ = cell_stats(rows, 1.9)
    real_hit = sum(1 for r in rows if r["realized_win"]) / len(rows) if rows else 0.0
    print(f"[UTC] fidelity: replay@RR1.9 hit={fid_hit*100:.1f}% vs realized "
          f"{real_hit*100:.1f}% (n={fid_n}) — "
          f"{'MATCH' if abs(fid_hit - real_hit) < 1e-9 else 'MISMATCH'}")

    cells = [
        ("UTC 12-24h & |range_z|<1.0", lambda r: 12 <= r["hour"] < 24 and r["rz"] < 1.0),
        ("UTC 12-24h & |range_z|<0.8", lambda r: 12 <= r["hour"] < 24 and r["rz"] < 0.8),
        ("UTC 12-24h & |range_z|<0.7", lambda r: 12 <= r["hour"] < 24 and r["rz"] < 0.7),
        ("UTC 12-24h & |range_z|<0.6", lambda r: 12 <= r["hour"] < 24 and r["rz"] < 0.6),
        ("UTC 18-24h & |range_z|<0.7", lambda r: 18 <= r["hour"] < 24 and r["rz"] < 0.7),
        ("UTC 18-24h & |range_z|<1.5", lambda r: 18 <= r["hour"] < 24 and r["rz"] < 1.5),
        ("baseline (all)", lambda r: True),
    ]
    print(f"\n[UTC] filtered-cell re-check (original sweep: n=34 hit 58.8% "
          f"exp +0.246R@RR1.2 / +0.267R@RR1.5; rz-tightening ladder added 2026-08-12):")
    print(f"[UTC]   {'cell':26} {'n':>4} {'hit@1.2':>8} {'exp@1.2':>9} {'net@0.05':>9} "
          f"{'hit@1.5':>8} {'exp@1.5':>9} {'net@0.05':>9} {'medMFE':>8}")
    for name, pred in cells:
        cell = [r for r in rows if pred(r)]
        n12, h12, e12, mm12 = cell_stats(cell, 1.2)
        n15, h15, e15, mm15 = cell_stats(cell, 1.5)
        print(f"[UTC]   {name:26} {len(cell):>4} {h12*100:>7.1f}% {e12:>+9.3f} {e12-0.05:>+9.3f} "
              f"{h15*100:>7.1f}% {e15:>+9.3f} {e15-0.05:>+9.3f} {mm12:>+8.2f}")
        if name.startswith("UTC 12-24h"):
            trades_per_day = len(cell) / span
            days_to_60 = (60 - len(cell)) / trades_per_day if trades_per_day > 0 else float("inf")
            print(f"[UTC]     -> {trades_per_day:.1f} cell-trades/day; n>=60 at "
                  f"~{span + days_to_60:.1f} corpus days")

    # --- deep-vs-shallow profile (mirrors the band's BandBackTests split) ---
    # Axes: depth = |range_z_50| at entry (the sniper's band-edge z; the entry
    # gate caps it at 1.0, so thirds of [0,1) — near-center / mid / band-edge)
    # and vol-regime = garch_vol_ratio at entry (current conditional vol vs
    # long-run vol, split at 1.25 like the band's prev_sigma/sigma_ema).
    def bucket_stats(bucket_rows):
        n = len(bucket_rows)
        if n == 0:
            return 0, 0.0, 0.0, 0.0, 0.0, 0.0
        hits = sum(1 for r in bucket_rows if r["realized_win"])
        rs = [r["realized_r"] for r in bucket_rows]
        exp = mean(rs)
        # maxDD in close order (rows are in outcome order ~ chronological)
        peak = 0.0
        cum = 0.0
        max_dd = 0.0
        for r in bucket_rows:
            cum += r["realized_r"]
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
        med_mfe = sorted(r["mfe"] for r in bucket_rows)[n // 2]
        return n, hits / n, exp, sum(rs), max_dd, med_mfe

    print("\n[UTC] deep-vs-shallow profile (realized production geometry, "
          "fixed 1.9R target / 1R stop) — does the sniper edge concentrate?")
    print(f"[UTC]   {'bucket':18} {'n':>4} {'hit':>7} {'exp':>8} {'sumR':>8} "
          f"{'maxDD':>7} {'medMFE':>7} {'mean|gz|':>8}")
    depth_buckets = [
        ("rz<0.33 center", lambda r: r["rz"] < 0.33),
        ("rz 0.33-0.66", lambda r: 0.33 <= r["rz"] < 0.66),
        ("rz>=0.66 edge", lambda r: r["rz"] >= 0.66),
    ]
    for name, pred in depth_buckets:
        cell = [r for r in rows if pred(r)]
        n, hit, exp, s, dd, mm = bucket_stats(cell)
        mgz = mean(r["gz"] for r in cell) if cell else 0.0
        print(f"[UTC]   depth {name:14} {n:>4} {hit*100:>6.1f}% {exp:>+8.3f} "
              f"{s:>+8.1f} {dd:>7.1f} {mm:>+7.2f} {mgz:>8.2f}")
    vol_buckets = [
        ("vol<=1.25", lambda r: r["vr"] <= 1.25),
        ("vol>1.25", lambda r: r["vr"] > 1.25),
    ]
    print(f"[UTC]   {'vol-regime':17} {'n':>4} {'hit':>7} {'exp':>8} {'sumR':>8} "
          f"{'maxDD':>7} {'medMFE':>7} {'mean rz':>8}")
    for name, pred in vol_buckets:
        cell = [r for r in rows if pred(r)]
        n, hit, exp, s, dd, mm = bucket_stats(cell)
        mrz = mean(r["rz"] for r in cell) if cell else 0.0
        print(f"[UTC]   {name:17} {n:>4} {hit*100:>6.1f}% {exp:>+8.3f} "
              f"{s:>+8.1f} {dd:>7.1f} {mm:>+7.2f} {mrz:>8.3f}")

    # --- direction + hour split of the FORWARD-PASS cell (18-24h & rz<1.5) ---
    # Does the edge concentrate further by side or hour, or is it balanced?
    fwd = [r for r in rows if 18 <= r["hour"] < 24 and r["rz"] < 1.5]
    print("\n[UTC] direction + hour split of the forward-pass cell "
          "(UTC 18-24h & |range_z|<1.5):")

    def line(label, cell):
        n12, h12, e12, mm12 = cell_stats(cell, 1.2)
        n15, h15, e15, _ = cell_stats(cell, 1.5)
        rh = sum(1 for r in cell if r["realized_win"]) / n12 if n12 else 0.0
        rexp = mean([r["realized_r"] for r in cell]) if cell else 0.0
        print(f"[UTC]   {label:12} n={n12:>3} hit@1.2={h12*100:>5.1f}% "
              f"exp@1.2={e12:>+7.3f} hit@1.5={h15*100:>5.1f}% exp@1.5={e15:>+7.3f} "
              f"realized(1.9R)={rh*100:>5.1f}%/{rexp:>+7.3f} medMFE={mm12:>+6.2f}")

    print(f"[UTC]   {'side':12}   (replay at RR 1.2/1.5; realized = production 1.9R geometry)")
    line("LONG", [r for r in fwd if r["d"] > 0])
    line("SHORT", [r for r in fwd if r["d"] < 0])
    line("ALL", fwd)
    print("\n[UTC]   hour buckets (same cell):")
    for h in range(18, 24):
        line(f"{h:02d}-{h+1:02d}", [r for r in fwd if r["hour"] == h])
    line("18-21", [r for r in fwd if 18 <= r["hour"] < 21])
    line("21-24", [r for r in fwd if 21 <= r["hour"] < 24])

    # --- full 12-24h hour ladder + rolling sub-windows -----------------------
    # Which hours inside the PRODUCTION gate (12-24h & |range_z|<1.0) carry the
    # edge?  Per-hour buckets plus rolling contiguous 4/5/6h sub-windows show
    # whether a tighter window raises expectancy with acceptable trade count.
    gated = [r for r in rows if 12 <= r["hour"] < 24 and r["rz"] < 1.0]
    print("\n[UTC] full 12-24h hour ladder (gated population, replay at RR 1.2):")
    print(f"[UTC]   {'hour':6} {'n':>4} {'hit@1.2':>8} {'exp@1.2':>9} "
          f"{'net@0.05':>9} {'trades/day':>10} {'medMFE':>8}")
    for h in range(12, 24):
        cell = [r for r in gated if r["hour"] == h]
        n, hit, exp, mm = cell_stats(cell, 1.2)
        tpd = n / span
        print(f"[UTC]   {h:02d}-{h+1:02d}   {n:>4} {hit*100:>7.1f}% {exp:>+9.3f} "
              f"{exp-0.05:>+9.3f} {tpd:>10.1f} {mm:>+8.2f}")
    print("\n[UTC]   rolling contiguous sub-windows (replay at RR 1.2):")
    print(f"[UTC]   {'window':6} {'n':>4} {'hit@1.2':>8} {'exp@1.2':>9} "
          f"{'net@0.05':>9} {'trades/day':>10} {'medMFE':>8}")
    best = {}
    for w in (4, 5, 6):
        best[w] = None
        for start in range(12, 24 - w + 1):
            cell = [r for r in gated if start <= r["hour"] < start + w]
            n, hit, exp, mm = cell_stats(cell, 1.2)
            tpd = n / span
            flag = ""
            if best[w] is None or (n >= 15 and exp > best[w][1]):
                if n >= 15:
                    best[w] = (f"{start:02d}-{start+w:02d}", exp)
            print(f"[UTC]   {start:02d}-{start+w:02d} {n:>4} {hit*100:>7.1f}% "
                  f"{exp:>+9.3f} {exp-0.05:>+9.3f} {tpd:>10.1f} {mm:>+8.2f}")
    print("\n[UTC]   best contiguous windows by exp@1.2 (n>=15): " +
          ", ".join(f"{k}h={v[0]} ({v[1]:+.3f}R)" for k, v in
                  sorted(best.items()) if v is not None))


if __name__ == "__main__":
    main()
