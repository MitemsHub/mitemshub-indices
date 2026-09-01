#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MITEMSHUB_AI — P1 Meta-Labeling Prototype (v0.1)
=================================================
 López de Prado 式 meta-labeling:
  主信号（tick-fade / CB spike）负责"方向"，本模型只回答一个问题：
  "在这个上下文里，这笔信号值不值得下、下多大？"

 输入: data/calibration_outcomes.jsonl  (prediction, label, r_multiple, outcome...)
 输出: data/meta_label_multipliers.json (P(win) 分桶 → 分数 Kelly 仓位倍率)

 使用方法:
   python scripts/meta_labeling_prototype.py                # 训练 + 输出乘率表
   python scripts/meta_labeling_prototype.py --report       # 打印详细校准报告
"""

import json
import argparse
import statistics
import sys
import io
from pathlib import Path
from collections import defaultdict

import numpy as np

# Windows cp1252 console fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---------------- config ----------------
DATA_PATH = Path("data/calibration_outcomes.jsonl")
OUT_PATH = Path("data/meta_label_multipliers.json")

# 账户安全参数（与 EA 0.30% base risk 对齐）
BASE_RISK = 0.003          # 单笔基础风险
KELLY_FRACTION = 0.25      # 分数 Kelly（保守）
MIN_TRADES_PER_BUCKET = 15 # 低于此样本量的桶回退到默认倍率
MIN_PREDICTION = 0.52      # 低于此 P(win) 的信号直接跳过（不交易）
N_BINS = 5

# ---------------- data ----------------
def load_records(path: Path) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


# ---------------- core math ----------------
def kelly_multiplier(win_rate: float, avg_win_r: float, avg_loss_r: float) -> float:
    """
    分数 Kelly 仓位倍率:
      f* = (p * b - q) / b,  b = avg_win_r / |avg_loss_r|
      multiplier = clip(f* / f*_baseline, 0.0, 1.5)
    f*_baseline 用全样本 Kelly 作为归一化基准，保证乘率围绕 1.0 波动。
    """
    q = 1.0 - win_rate
    if avg_loss_r == 0 or avg_win_r == 0:
        return 0.5
    b = avg_win_r / abs(avg_loss_r)
    kelly = (win_rate * b - q) / b
    # 全样本基准
    all_p = sum(1 for _ in range(0))  # placeholder; baseline computed outside
    return kelly  # raw, normalized later


def compute_baseline_kelly(recs: list[dict]) -> float:
    wins = [d for d in recs if d.get("label") == 1]
    losses = [d for d in recs if d.get("label") == 0]
    if not wins or not losses:
        return 0.10
    p = len(wins) / len(recs)
    avg_w = statistics.mean(d["r_multiple"] for d in wins if d.get("r_multiple") is not None)
    avg_l = statistics.mean(d["r_multiple"] for d in losses if d.get("r_multiple") is not None)
    if avg_l == 0:
        return 0.10
    b = avg_w / abs(avg_l)
    q = 1.0 - p
    k = (p * b - q) / b
    return max(k, 0.02)


# ---------------- pipeline ----------------
def build_buckets(recs: list[dict]):
    """按 prediction 分桶，计算每桶的 P(win) 与 Kelly 乘率。"""
    buckets = defaultdict(list)
    edges = np.linspace(0.5, 1.0, N_BINS + 1)

    for d in recs:
        pred = d.get("prediction")
        label = d.get("label")
        r = d.get("r_multiple")
        if pred is None or label is None or r is None:
            continue
        for i in range(N_BINS):
            if edges[i] <= pred < edges[i + 1] or (i == N_BINS - 1 and pred == edges[i + 1]):
                buckets[i].append(d)
                break

    baseline = compute_baseline_kelly(recs)
    table = {}
    details = []

    for i in range(N_BINS):
        grp = buckets.get(i, [])
        lo, hi = edges[i], edges[i + 1]
        if len(grp) < MIN_TRADES_PER_BUCKET:
            # 样本不足 → 保守回退
            table[f"{lo:.2f}-{hi:.2f}"] = {
                "multiplier": 0.5,
                "n": len(grp),
                "note": "insufficient_data_fallback"
            }
            details.append((lo, hi, len(grp), None, None, 0.5))
            continue

        wins = [d for d in grp if d["label"] == 1]
        losses = [d for d in grp if d["label"] == 0]
        p = len(wins) / len(grp)
        avg_w = statistics.mean(d["r_multiple"] for d in wins)
        avg_l = statistics.mean(d["r_multiple"] for d in losses)

        raw_kelly = kelly_multiplier(p, avg_w, avg_l)
        mult = raw_kelly / baseline if baseline > 0 else 0.5
        mult = float(np.clip(mult, 0.0, 1.5))

        table[f"{lo:.2f}-{hi:.2f}"] = {
            "multiplier": round(mult, 3),
            "p_win": round(p, 3),
            "n": len(grp),
            "avg_win_r": round(avg_w, 3),
            "avg_loss_r": round(avg_l, 3),
        }
        details.append((lo, hi, len(grp), p, raw_kelly, mult))

    return table, details, baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"[ERROR] 找不到数据文件: {DATA_PATH}")
        return

    recs = load_records(DATA_PATH)
    print(f"[INFO] 加载 {len(recs)} 条校准记录")

    # 过滤：只取有结果的记录
    valid = [d for d in recs if d.get("label") is not None and d.get("r_multiple") is not None]
    print(f"[INFO] 有效样本: {len(valid)} (label + r_multiple 完整)")

    table, details, baseline = build_buckets(valid)

    # 输出乘率表
    output = {
        "version": "0.1",
        "generated_from": str(DATA_PATH),
        "n_total": len(recs),
        "n_valid": len(valid),
        "baseline_kelly": round(baseline, 4),
        "kelly_fraction": KELLY_FRACTION,
        "min_prediction": MIN_PREDICTION,
        "buckets": table,
        "ea_integration": {
            "usage": "EA 在入场前查 prediction → 桶 → multiplier",
            "formula": "actual_risk = base_risk * multiplier",
            "skip_rule": "prediction < min_prediction → 放弃信号",
        }
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
    print(f"[DONE] 乘率表已写入 {OUT_PATH}")

    if args.report:
        print("\n========== 校准报告 ==========")
        print(f"全样本基准 Kelly: {baseline:.4f}")
        print(f"{'桶':<14} {'n':>5} {'P(win)':>8} {'rawKelly':>9} {'乘率':>6}")
        for lo, hi, n, p, rk, mult in details:
            p_str = f"{p:.3f}" if p is not None else "  -  "
            rk_str = f"{rk:.4f}" if rk is not None else "  -  "
            print(f"[{lo:.2f},{hi:.2f}) {n:>5} {p_str:>8} {rk_str:>9} {mult:>6.3f}")


if __name__ == "__main__":
    main()
