#!/usr/bin/env python3
"""Verify that MT5 .set files only reference input names that exist in the EA source.

MT5 silently DROPS unknown keys when loading a .set file, so any rename between
EA versions means the chart trades with code defaults while the operator believes
the validated config is active. This script makes that mismatch loud.

Usage:
    python scripts/verify_set_inputs.py <ea_source.mq5> <config.set> [<more.set> ...]

Exit code 0 = all keys match; 1 = mismatches found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

INPUT_RE = re.compile(r"^\s*input\s+\S+\s+(\w+)\s*=", re.MULTILINE)
SET_KEY_RE = re.compile(r"^([^#;\r\n]+?)=", re.MULTILINE)


def strip_mql_comments_and_strings(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', "", text)
    text = re.sub(r"'(?:[^'\\]|\\.)*'", "", text)
    return text


def brace_balance(mq5_path: Path) -> list[str]:
    src = strip_mql_comments_and_strings(mq5_path.read_text(encoding="utf-8", errors="replace"))
    problems = []
    for opn, cls in (("{", "}"), ("(", ")")):
        if src.count(opn) != src.count(cls):
            problems.append(f"  unbalanced {opn}{cls}: {src.count(opn)} vs {src.count(cls)}")
    return problems


def ea_inputs(mq5_path: Path) -> set[str]:
    text = mq5_path.read_text(encoding="utf-8", errors="replace")
    return set(INPUT_RE.findall(text))


def set_keys(set_path: Path) -> set[str]:
    text = set_path.read_text(encoding="utf-8", errors="replace")
    return {k.strip() for k in SET_KEY_RE.findall(text) if k.strip()}


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    mq5 = Path(argv[1])
    inputs = ea_inputs(mq5)
    if not inputs:
        print(f"ERROR: no 'input' declarations found in {mq5}")
        return 2

    failed = False

    balance = brace_balance(mq5)
    if balance:
        failed = True
        print(f"== {mq5.name} source sanity ==")
        print("\n".join(balance))
    else:
        print(f"== {mq5.name} source sanity ==")
        print("  braces/parens balanced")
    for arg in argv[2:]:
        sp = Path(arg)
        keys = set_keys(sp)
        unknown = sorted(keys - inputs)
        # Inputs absent from the .set fall back to code defaults: warn, don't fail,
        # unless they look risk-critical.
        missing = inputs - keys
        critical = {"InpRiskPerTrade", "InpMaxEffectiveRiskPct", "InpMaxDailyLossPct",
                    "InpMaxConsecLoss", "InpTpMult", "InpBandZEntry",
                    "InpBandStopSigmaMult", "InpBandTargetSigmaMult"}
        missing_critical = missing & critical

        print(f"\n== {sp.name} vs {mq5.name} ==")
        if unknown:
            failed = True
            print(f"  UNKNOWN KEYS (silently dropped by MT5 -> defaults!): {unknown}")
        else:
            print("  all .set keys exist in EA source")
        if missing_critical:
            failed = True
            print(f"  CRITICAL INPUTS MISSING from .set (defaults would be used!): {sorted(missing_critical)}")
        elif missing:
            print(f"  note: {len(missing)} non-critical input(s) not in .set, using code defaults: {sorted(missing)}")

    print("\nRESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
