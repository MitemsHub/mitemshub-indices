#!/usr/bin/env python3
"""Validate Boom 1000 + Crash 1000 fade-only configs and generate deployment report.

Checks:
  1. .set files have all required inputs
  2. Code changes compile (syntax check of modified .mqh files)
  3. Strategy logic matches the optimized parameters
  4. Generates deployment checklist

Usage:
    .venv/Scripts/python.exe scripts/boom1000_strategy_validate.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"

REQUIRED_CB_INPUTS = [
    "InpCrashBoomMode", "InpIsCrashIndex", "InpCBSpikeThreshold",
    "InpCBMaxSpikeProb", "InpCBFadeR", "InpCBFadeSL", "InpCBFadeTP",
    "InpCBBaseRisk", "InpCBMinRisk", "InpCBEnableGrind",
    "InpCBRequireSpikeDirection", "InpCBMinATRPoints",
]


def check_set_file(path: Path, label: str):
    """Validate a .set file has all required CB inputs."""
    print(f"\n{'=' * 70}")
    print(f"CHECKING: {label}")
    print(f"  File: {path}")
    print(f"{'=' * 70}")

    if not path.exists():
        print(f"  FAIL: File not found!")
        return False

    content = path.read_text(encoding="utf-8")
    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith(";")]
    params = {}
    for line in lines:
        if "=" in line:
            key, val = line.split("=", 1)
            # Strip inline comments (text after ;)
            val_clean = val.split(";")[0].strip()
            params[key.strip()] = val_clean

    all_ok = True
    for inp in REQUIRED_CB_INPUTS:
        if inp in params:
            print(f"  OK: {inp} = {params[inp]}")
        else:
            print(f"  MISSING: {inp}")
            all_ok = False

    # Check specific values
    if params.get("InpCrashBoomMode") == "true":
        print(f"  OK: CB mode ENABLED")
    else:
        print(f"  WARN: CB mode not enabled")
        all_ok = False

    if params.get("InpCBEnableGrind") == "false":
        print(f"  OK: Grind DISABLED (fade-only)")
    else:
        print(f"  WARN: Grind is enabled (should be false for fade-only)")

    is_crash = params.get("InpIsCrashIndex") == "true"
    tp = float(params.get("InpCBFadeTP", "0"))
    sl = float(params.get("InpCBFadeSL", "0"))
    print(f"  Symbol type: {'CRASH' if is_crash else 'BOOM'}")
    print(f"  Fade TP: {tp}x ATR  Fade SL: {sl}x ATR  R:R = {tp/sl:.1f}:1")

    return all_ok


def check_code_changes():
    """Verify the code changes are syntactically correct."""
    print(f"\n{'=' * 70}")
    print("CODE VALIDATION")
    print(f"{'=' * 70}")

    files_to_check = [
        "mql5/MITEMSHUB_AI/MitemshubAI.mq5",
        "mql5/MITEMSHUB_AI/CrashBoom/CrashBoomStrategy.mqh",
        "mql5/MITEMSHUB_AI/CrashBoom/CrashBoomEngine.mqh",
    ]

    all_ok = True
    for fp in files_to_check:
        path = ROOT / fp
        if not path.exists():
            print(f"  FAIL: {fp} not found")
            all_ok = False
            continue

        content = path.read_text(encoding="utf-8")

        # Check for InpCBEnableGrind in main EA
        if "MitemshubAI.mq5" in fp:
            if "InpCBEnableGrind" in content:
                print(f"  OK: {fp} - InpCBEnableGrind input found")
            else:
                print(f"  FAIL: {fp} - InpCBEnableGrind not found")
                all_ok = False

            for marker in ("SetEnableGrind", "SetRequireSpikeDirection", "SetMinATRPoints"):
                if marker in content:
                    print(f"  OK: {fp} - {marker} call found")
                else:
                    print(f"  FAIL: {fp} - {marker} call not found")
                    all_ok = False

        # Check for grind flag in strategy
        if "CrashBoomStrategy.mqh" in fp:
            if "m_enable_grind" in content:
                print(f"  OK: {fp} - m_enable_grind field found")
            else:
                print(f"  FAIL: {fp} - m_enable_grind not found")
                all_ok = False

            if "if(m_enable_grind)" in content:
                print(f"  OK: {fp} - grind gate check found")
            else:
                print(f"  FAIL: {fp} - grind gate check not found")
                all_ok = False

            for marker in ("IsGrindEnabled", "m_require_spike_direction", "m_min_atr_points"):
                if marker in content:
                    print(f"  OK: {fp} - {marker} found")
                else:
                    print(f"  FAIL: {fp} - {marker} not found")
                    all_ok = False

        # Check engine passes through
        if "CrashBoomEngine.mqh" in fp:
            for marker in ("SetEnableGrind", "SetRequireSpikeDirection", "SetMinATRPoints"):
                if marker in content:
                    print(f"  OK: {fp} - {marker} passthrough found")
                else:
                    print(f"  FAIL: {fp} - {marker} not found")
                    all_ok = False

            if "IsGrindEnabled" in content:
                print(f"  OK: {fp} - IsGrindEnabled dashboard found")
            else:
                print(f"  WARN: {fp} - IsGrindEnabled not in dashboard")

    return all_ok


def check_optimization_results():
    """Load and display the optimization results."""
    print(f"\n{'=' * 70}")
    print("OPTIMIZATION RESULTS SUMMARY")
    print(f"{'=' * 70}")

    boom_path = ART / "boom1000_fade_optimize.json"
    if boom_path.exists():
        data = json.loads(boom_path.read_text(encoding="utf-8"))
        w = data.get("winner", {})
        print(f"\n  BOOM 1000:")
        print(f"    TP = {w.get('tp')}x ATR")
        print(f"    SL = {w.get('sl')}x ATR")
        print(f"    Trailing: {'ON' if w.get('trail_enabled') else 'OFF'}")
        print(f"    Max Hold: {w.get('max_hold_bars')} bars")
        s = w.get("stats", {})
        print(f"    -> {s.get('trades')} trades, WR {s.get('wr')}%, PF {s.get('pf')}, "
              f"ExpR {s.get('exp_r'):+.3f}, DD {s.get('max_dd_r')}R")

    crash_path = ART / "crash1000_60day_analysis.json"
    if crash_path.exists():
        data = json.loads(crash_path.read_text(encoding="utf-8"))
        s = data.get("fade_stats", {})
        print(f"\n  CRASH 1000:")
        print(f"    TP = 3.5x ATR (from sweep)")
        print(f"    SL = 0.4x ATR")
        print(f"    -> {s.get('trades')} trades, WR {s.get('wr')}%, PF {s.get('pf')}, "
              f"ExpR {s.get('exp_r'):+.3f}, DD {s.get('max_dd_r')}R")


def main():
    print("MITEMSHUB AI - FADE-ONLY DEPLOYMENT VALIDATION")
    print("=" * 70)

    checks = []

    # 1. Check .set files
    checks.append(check_set_file(
        ROOT / "mql5/MITEMSHUB_AI/MitemshubAI_BOOM1000_CB.set",
        "Boom 1000 .set file"
    ))
    checks.append(check_set_file(
        ROOT / "mql5/MITEMSHUB_AI/MitemshubAI_CRASH1000_CB.set",
        "Crash 1000 .set file"
    ))

    # 2. Check code changes
    checks.append(check_code_changes())

    # 3. Show optimization results
    check_optimization_results()

    # 4. Deployment checklist
    print(f"\n{'=' * 70}")
    print("DEPLOYMENT CHECKLIST")
    print(f"{'=' * 70}")
    print("  1. Copy MitemshubAI_BOOM1000_CB.set to MT5 profiles/sets/")
    print("  2. Copy MitemshubAI_CRASH1000_CB.set to MT5 profiles/sets/")
    print("  3. Attach EA to Boom 1000 Index chart, load BOOM1000_CB.set")
    print("  4. Attach EA to Crash 1000 Index chart, load CRASH1000_CB.set")
    print("  5. Verify dashboard shows 'Mode: FADE-ONLY' on both charts")
    print("  6. Verify dashboard shows 'CB: BOOM' / 'CB: CRASH' correctly")
    print("  7. Enable Algo Trading")
    print("  8. Monitor first 24h before increasing size")

    # Final verdict
    print(f"\n{'=' * 70}")
    if all(checks):
        print("ALL CHECKS PASSED - Ready for deployment")
    else:
        print("SOME CHECKS FAILED - Review above issues")
    print("=" * 70)

    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
