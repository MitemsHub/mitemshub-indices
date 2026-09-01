#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MITEMSHUB_AI — P1 Meta-Labeling Trainer (v0.2)
==============================================
López de Prado-style meta-labeling:

  Primary signal (tick-fade / CB spike) decides DIRECTION.
  This meta-model answers: "given this context, should this signal be taken,
  and at what size?"  ->  P(win) bucket -> fractional-Kelly size multiplier.

Input : MitemshubAI_v23_telemetry_<Symbol>.jsonl  (sig/close events, per symbol)
Output: data/meta_label_multipliers_<Symbol>.json   (P(win) bucket table)
        data/meta_label_regime_table.csv            (regime|dir CSV for MQL5)
        data/meta_label_regime_table_<Symbol>.csv   (symbol-tagged copies matching
                                                     the EA's SymbolTaggedFile lookup;
                                                     --ea-files-dir copies them straight
                                                     into MQL5\\Files)

The EA consults the multiplier table before entry:
    actual_risk = InpBaseRisk * multiplier[P(win)_bucket]
    skip if P(win) < min_prediction

Usage:
    python scripts/meta_label_trainer.py                       # train on all telemetry found
    python scripts/meta_label_trainer.py --telemetry PATH      # explicit file
    python scripts/meta_label_trainer.py --report              # verbose calibration report
"""
from __future__ import annotations

import json
import math
import argparse
import os
import sys
import io
import statistics
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------- config ----------------
TELEMETRY_GLOBS = [
    "journals/MitemshubAI_v23_telemetry_*.jsonl",
    "data/MitemshubAI_v23_telemetry_*.jsonl",
    "artifacts/MitemshubAI_v23_telemetry_*.jsonl",
]
DEFAULT_OUT_DIR = Path("data")

KELLY_FRACTION = 0.25      # fractional Kelly (full Kelly too volatile on micro accounts)
MIN_TRADES_PER_BUCKET = 15 # buckets with thin evidence fall back to 0.5x
MIN_PREDICTION = 0.52      # signals below this P(win) are skipped entirely
MULT_CAP = (0.0, 1.5)      # hard clip: never exceed 1.5x base risk
SMOOTHING_ALPHA = 5.0      # Laplace-style prior weight per bucket


# ---------------- loading ----------------
def load_telemetry(paths: list[Path]) -> list[dict]:
    """Load all telemetry JSONL lines, tolerating corrupt lines."""
    recs = []
    for p in paths:
        if not p.exists():
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return recs


def find_telemetry_files(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit)]
    files = []
    for pattern in TELEMETRY_GLOBS:
        files.extend(sorted(Path().glob(pattern)))
    return files


# ---------------- joining sig -> close (trade outcomes) ----------------
def join_signals(events: list[dict]) -> list[dict]:
    """
    Pair 'sig' events with action=TAKE to their subsequent 'close' event.

    The EA is single-position-per-symbol, so the next close after a TAKE
    belongs to that signal. Returns one record per completed trade with
    context features + outcome label.
    """
    open_sig = None
    trades = []
    for ev in events:
        t = ev.get("type")
        if t == "sig" and ev.get("action") == "TAKE":
            open_sig = ev
        elif t == "close" and open_sig is not None:
            trades.append({
                "sym": open_sig.get("sym") or open_sig.get("symbol"),
                "dir": open_sig.get("dir"),
                "legs": open_sig.get("legs"),
                "regime": open_sig.get("regime"),
                "z": open_sig.get("z"),
                "exp": open_sig.get("exp"),
                "sigma": open_sig.get("sigma"),
                "sigma_base": open_sig.get("sigma_base"),
                "band_geom": open_sig.get("band_geom"),
                "score_b": open_sig.get("score_b"),
                "score_s": open_sig.get("score_s"),
                "r": ev.get("r"),
                "reason": ev.get("reason"),
            })
            open_sig = None
    return trades


# ---------------- feature engineering ----------------
def featurize(trade: dict) -> dict:
    """Engineer meta-model features from a joined trade record."""
    feats = {}
    feats["regime"] = trade.get("regime", "unknown")
    feats["dir"] = trade.get("dir", 0)
    feats["legs"] = trade.get("legs", "")
    feats["z"] = trade.get("z") or 0.0
    feats["exp"] = trade.get("exp") or 0.0
    feats["sigma_ratio"] = (
        trade["sigma"] / trade["sigma_base"]
        if trade.get("sigma") and trade.get("sigma_base")
        else 1.0
    )
    feats["band_geom"] = 1 if trade.get("band_geom") else 0
    feats["score_b"] = trade.get("score_b") or 0.0
    feats["score_s"] = trade.get("score_s") or 0.0
    # label: win if r > 0 (net-of-cost variant can use r > spread_cost)
    feats["label"] = 1 if (trade.get("r") or 0) > 0 else 0
    return feats


# ---------------- simple logistic regression (no sklearn dependency) ----------------
class LogisticModel:
    """Tiny L2-regularized logistic regression trained with gradient descent."""

    def __init__(self, lr: float = 0.1, epochs: int = 300, l2: float = 1e-3):
        self.lr, self.epochs, self.l2 = lr, epochs, l2
        self.w: dict[str, float] = {}
        self.bias = 0.0

    def _sigmoid(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))

    def predict(self, feats: dict) -> float:
        s = self.bias + sum(self.w.get(k, 0.0) * v for k, v in feats.items()
                            if isinstance(v, (int, float)))
        return self._sigmoid(s)

    def fit(self, rows: list[dict]):
        if not rows:
            return
        for _ in range(self.epochs):
            gw: dict[str, float] = defaultdict(float)
            gb = 0.0
            for feats in rows:
                p = self.predict(feats)
                err = p - feats["label"]
                for k, v in feats.items():
                    if isinstance(v, (int, float)):
                        gw[k] += err * v
                gb += err
            n = len(rows)
            for k in gw:
                self.w[k] = self.w.get(k, 0.0) - self.lr * (gw[k] / n + self.l2 * self.w.get(k, 0.0))
            self.bias -= self.lr * (gb / n)


# ---------------- P(win) -> multiplier table ----------------
def build_multiplier_table(trades: list[dict], model: LogisticModel) -> dict:
    """Bucket trades by predicted P(win); compute empirical win rate + Kelly multiplier per bucket."""
    buckets = defaultdict(list)
    for t in trades:
        feats = featurize(t)
        p = model.predict(feats)
        buckets[round(p, 2)].append(t)

    table = {}
    for p_bucket, group in sorted(buckets.items()):
        n = len(group)
        wins = sum(1 for t in group if (t.get("r") or 0) > 0)
        # Laplace smoothing so tiny buckets don't produce wild estimates
        p_emp = (wins + SMOOTHING_ALPHA / 2) / (n + SMOOTHING_ALPHA)
        rs = [t["r"] for t in group if t.get("r") is not None]
        avg_win = statistics.mean([x for x in rs if x > 0]) if any(x > 0 for x in rs) else 0.0
        avg_loss = statistics.mean([x for x in rs if x < 0]) if any(x < 0 for x in rs) else -1.0
        if n < MIN_TRADES_PER_BUCKET:
            mult = 0.5  # conservative fallback for thin evidence
            note = "insufficient_data_fallback"
        else:
            b = avg_win / abs(avg_loss) if avg_loss not in (0, 0.0) else 1.0
            if b == 0:
                b = 1.0
            q = 1.0 - p_emp
            kelly = (p_emp * b - q) / b if b else 0.0
            mult = max(MULT_CAP[0], min(MULT_CAP[1], KELLY_FRACTION * max(kelly, 0.0) / max(KELLY_FRACTION, 1e-9)))
            note = "kelly"
        table[str(p_bucket)] = {
            "p_win": round(p_emp, 3),
            "multiplier": round(mult, 3),
            "n": n,
            "avg_win_r": round(avg_win, 3),
            "avg_loss_r": round(avg_loss, 3),
            "note": note,
        }
    return table


def build_regime_table(trades: list[dict]) -> dict:
    """Regime+direction keyed lookup for direct MQL5 consumption.

    The live EA has no runtime P(win) model, so it cannot look up by prediction.
    Instead the EA looks up by (regime, direction) and gets a risk multiplier:
        multiplier = clip(mean_R_group / mean_R_overall, 0.0, 1.5)
    Groups with mean R <= 0 (no demonstrated edge) get 0 (never size up).
    Emitted as simple CSV so MQL5 can parse it without a JSON library.
    """
    groups = defaultdict(list)
    for t in trades:
        key = (str(t.get("regime", "unknown")).lower(),
               "long" if (t.get("dir") or 0) > 0 else "short")
        groups[key].append(t.get("r") or 0.0)

    all_r = [t.get("r") or 0.0 for t in trades]
    base_mean = statistics.mean(all_r) if all_r else 0.0

    table = {}
    for (regime, direction), rs in sorted(groups.items()):
        n = len(rs)
        mean_r = statistics.mean(rs)
        wins = sum(1 for x in rs if x > 0)
        if mean_r <= 0 or n < MIN_TRADES_PER_BUCKET:
            mult = 0.0  # never size up a context with no demonstrated edge
            note = "no_edge_or_thin_data"
        else:
            mult = max(MULT_CAP[0], min(MULT_CAP[1], mean_r / base_mean))
            note = "relative_expectancy"
        table[f"{regime}|{direction}"] = {
            "n": n,
            "win_rate": round(wins / n, 3) if n else 0.0,
            "avg_r": round(mean_r, 3),
            "multiplier": round(mult, 3),
            "note": note,
        }
    return table


# ---------------- main ----------------
def main():
    parser = argparse.ArgumentParser(description="MITEMSHUB meta-labeling trainer")
    parser.add_argument("--telemetry", help="explicit telemetry JSONL path (overrides globs)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--ea-files-dir", default=None,
                        help="MQL5\\Files dir (or its data/ mirror) to also drop "
                             "symbol-tagged meta_label_regime_table_<Symbol>.csv copies into")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    files = find_telemetry_files(args.telemetry)
    if not files:
        print("[WARN] No telemetry JSONL files found. Generate data by running the EA "
              "on demo, or pass --telemetry explicitly. Nothing to train on yet.")
        return

    events = load_telemetry(files)
    print(f"[INFO] Loaded {len(events)} telemetry events from {len(files)} file(s)")

    trades = join_signals(events)
    print(f"[INFO] Paired {len(trades)} completed trades (sig TAKE -> close)")

    if not trades:
        print("[WARN] No completed trades found — need both 'sig' (action=TAKE) "
              "and 'close' events. Nothing to train on yet.")
        return

    rows = [featurize(t) for t in trades]
    model = LogisticModel()
    model.fit(rows)

    # holdout check (simple temporal split: last 20% as validation)
    split = int(len(rows) * 0.8)
    train_rows, val_rows = rows[:split], rows[split:]
    if val_rows:
        correct = sum(1 for f in val_rows if (model.predict(f) > 0.5) == (f["label"] == 1))
        print(f"[VALID] Holdout accuracy: {correct}/{len(val_rows)} = {correct/len(val_rows):.1%}")

    table = build_multiplier_table(trades, model)

    out = {
        "version": "0.2",
        "generated_from": [str(f) for f in files],
        "n_trades": len(trades),
        "min_prediction": MIN_PREDICTION,
        "kelly_fraction": KELLY_FRACTION,
        "multiplier_table": table,
        "ea_integration": {
            "usage": "EA computes prediction -> look up bucket -> multiplier",
            "formula": "actual_risk = InpBaseRisk * multiplier",
            "skip_rule": "prediction < min_prediction -> skip signal",
        },
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # v0.3: regime+direction CSV table for direct MQL5 consumption
    regime_table = build_regime_table(trades)
    csv_lines = ["regime,direction,n,win_rate,avg_r,multiplier,note"]
    for key, info in regime_table.items():
        regime, direction = key.split("|")
        csv_lines.append(f"{regime},{direction},{info['n']},{info['win_rate']},"
                         f"{info['avg_r']},{info['multiplier']},{info['note']}")
    csv_body = "\n".join(csv_lines) + "\n"

    csv_path = out_dir / "meta_label_regime_table.csv"
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write(csv_body)
    print(f"[DONE] {csv_path}")

    # v0.4: symbol-tagged copies matching the EA's SymbolTaggedFile() lookup.
    # The EA opens meta_label_regime_table_<Symbol>.csv in MQL5\\Files
    # (spaces in _Symbol replaced with underscores, e.g.
    # meta_label_regime_table_Crash_1000_Index.csv), so emit one tagged copy
    # per symbol present in the telemetry. Real EA telemetry emits "sym";
    # accept "symbol" as a fallback so both journal formats work.
    symbols = sorted({(t.get("sym") or t.get("symbol") or "unknown") for t in trades})
    for sym in symbols:
        tagged_name = f"meta_label_regime_table_{sym.replace(' ', '_')}.csv"
        tagged_path = out_dir / tagged_name
        with open(tagged_path, "w", encoding="utf-8") as fh:
            fh.write(csv_body)
        print(f"[DONE] {tagged_path}")

    # v0.5: automatic delivery to the EA's SymbolTaggedFile() lookup target.
    # SymbolTaggedFile() resolves meta_label_regime_table_<Symbol>.csv inside
    # each MT5 terminal's MQL5\\Files directory, so copy every tagged CSV into
    # every installed terminal's Files dir. --ea-files-dir overrides/appends;
    # without it, terminals under %APPDATA%\\MetaQuotes\\Terminal are
    # discovered automatically (same pattern as replay_v22_bandfade.py).
    ea_targets: list[Path] = []
    if args.ea_files_dir:
        ea_targets.append(Path(args.ea_files_dir))
    else:
        appdata = os.environ.get("APPDATA")
        if appdata:
            ea_targets = sorted(Path(appdata).glob(
                "MetaQuotes/Terminal/*/MQL5/Files"))
            ea_targets.append(Path(appdata) / "MetaQuotes/Terminal/MQL5/Files")
    for target in ea_targets:
        try:
            target.mkdir(parents=True, exist_ok=True)
            for sym in symbols:
                tagged_name = f"meta_label_regime_table_{sym.replace(' ', '_')}.csv"
                ea_path = target / tagged_name
                with open(ea_path, "w", encoding="utf-8") as fh:
                    fh.write(csv_body)
                print(f"[DONE] {ea_path}  (EA SymbolTaggedFile target)")
        except OSError as exc:
            print(f"[WARN] Could not write EA files to {target}: {exc}")

    for sym in symbols:
        sym_trades = [t for t in trades if (t.get("sym") or t.get("symbol") or "unknown") == sym]
        sym_model = LogisticModel()
        sym_model.fit([featurize(t) for t in sym_trades])
        sym_table = build_multiplier_table(sym_trades, sym_model)
        out_path = out_dir / f"meta_label_multipliers_{sym.replace(' ', '_')}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(out | {"symbol": sym, "multiplier_table": sym_table}, fh, ensure_ascii=False, indent=2)
        print(f"[DONE] {out_path}")

    if args.report:
        print("\n========== Multiplier Table ==========")
        for bucket, info in table.items():
            print(f"  P(win)~{bucket}: mult={info['multiplier']} "
                  f"(n={info['n']}, p={info['p_win']}, {info['note']})")


if __name__ == "__main__":
    main()
