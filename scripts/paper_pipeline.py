"""Run the full paper-research pipeline and report which verdicts changed.

    python scripts/paper_pipeline.py            # run everything + diff vs last run
    python scripts/paper_pipeline.py --no-run   # re-print last state + diff only

Dynamic tools (re-executed; they are all read-only and gate themselves when
data is missing):
  ab       scripts/ab_adjudicate.py          TP 1.8 vs TP 2.4 adjudication
  recon    scripts/reconcile_paper_ticks.py  paper-vs-tick drift check
  regime3  scripts/regime_gate_study_v3.py   z/hour gate replication
  weekly   scripts/paper_weekly.py           ledger + watchdog + preset drift

Registered verdicts (read from artifacts, never re-executed — they are
one-look contracts):
  zgate     artifacts/z_gate/phaseA_result.json
  wf_v75    artifacts/v75_replay/walkforward_210d_r4_gate.json
  wf_v100   artifacts/v100_replay/walkforward_v100_210d.json
  regime3i  artifacts/v75_replay/regime_gate_study_v3.json (interim info)

State: artifacts/v75_replay/pipeline_state.json (last verdict per tool).
A verdict that differs from the previous state is reported as CHANGED.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "artifacts", "v75_replay")
STATE = os.path.join(DATA, "pipeline_state.json")
LEDGER = "MitemshubAI_paper_Volatility_75_Index.csv"
TERM_ROOT = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
PY = sys.executable


def verdict_line(text: str, tool: str) -> str | None:
    if tool == "weekly":
        m = re.findall(r"(CERTIFIED|VIOLATIONS PRESENT)\s*\([^\n]*", text)
        if m:
            return m[-1].strip()
    m = re.findall(r"verdict:\s*(.+)", text, re.I)   # matches VERDICT/Verdict
    return m[-1].strip() if m else None


def discover_arm_dirs() -> tuple[str | None, str | None]:
    """Arm A/B Files dirs by chart magic (fall back to ledger presence order)."""
    a = b = None
    for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
        led = os.path.join(td, "MQL5", "Files", LEDGER)
        if not os.path.exists(led):
            continue
        magic = ""
        for chr_f in glob.glob(os.path.join(td, "MQL5", "Profiles", "Charts", "*", "*.chr")):
            try:
                txt = open(chr_f, encoding="utf-16", errors="replace").read()
            except OSError:
                continue
            if "Volatility 75" in txt:
                m = re.search(r"^InpMagic=(7788075|7788100)$", txt, re.M)
                if m:
                    magic = m.group(1)
                    break
        if magic == "7788075" and a is None:
            a = os.path.join(td, "MQL5", "Files")
        elif magic == "7788100" and b is None:
            b = os.path.join(td, "MQL5", "Files")
    if a is None:  # fallback: first ledger-bearing terminal
        for td in sorted(glob.glob(os.path.join(TERM_ROOT, "*"))):
            if os.path.exists(os.path.join(td, "MQL5", "Files", LEDGER)):
                a = os.path.join(td, "MQL5", "Files")
                break
    return a, b


def run_tool(name: str, cmd: list[str]) -> dict:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=1800)
        out = (p.stdout + p.stderr).strip()
        v = verdict_line(out, name)
        return {"tool": name, "exit": p.returncode,
                "verdict": v or f"(no verdict line; exit {p.returncode})",
                "tail": out[-2000:]}
    except Exception as e:
        return {"tool": name, "exit": -1, "verdict": f"ERROR {e}", "tail": ""}


def registered() -> dict:
    out = {}
    checks = {
        "zgate [registered one-look]": os.path.join(ROOT, "artifacts", "z_gate", "phaseA_result.json"),
        "wf_v75 [registered V1-V6]": os.path.join(DATA, "walkforward_210d_r4_gate.json"),
        "wf_v100 [registered V1-V6]": os.path.join(ROOT, "artifacts", "v100_replay", "walkforward_v100_210d.json"),
        "regime3_interim [descriptive]": os.path.join(DATA, "regime_gate_study_v3.json"),
    }
    for name, path in checks.items():
        try:
            j = json.load(open(path))
            if "verdicts" in j:  # walkforward artifacts: per-config verdicts
                vs = {c: ("VALIDATED" if v.get("ok") else "NOT VALIDATED") for c, v in j["verdicts"].items()}
                out[name] = " | ".join(f"{c}:{v}" for c, v in vs.items())
            else:
                out[name] = str(j.get("verdict", "(no verdict field)"))
        except (OSError, KeyError, json.JSONDecodeError) as e:
            out[name] = f"(artifact missing: {e})"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", action="store_true", help="re-diff stored state only")
    args = ap.parse_args()

    prev = {}
    if os.path.exists(STATE):
        prev = json.load(open(STATE)).get("verdicts", {})

    now = datetime.now()
    print(f"=== PAPER PIPELINE {now:%Y-%m-%d %H:%M} ===\n")
    current: dict[str, str] = {}
    rows: dict[str, dict] = {}

    if not args.no_run:
        a, b = discover_arm_dirs()
        print(f"arm dirs: A={a or '(none)'} B={b or '(none)'}\n")
        tools = []
        if a or b:
            cmd = [PY, os.path.join("scripts", "ab_adjudicate.py"),
                   "--a-dir", a or os.path.join(TERM_ROOT, "_none_"),
                   "--b-dir", b or os.path.join(TERM_ROOT, "_none_")]
            tools.append(("ab", cmd))
            tools.append(("recon", [PY, os.path.join("scripts", "reconcile_paper_ticks.py"),
                                    "--a-dir", a or os.path.join(TERM_ROOT, "_none_")]
                          + (["--b-dir", b] if b else [])))
        tools.append(("regime3", [PY, os.path.join("scripts", "regime_gate_study_v3.py")]))
        for name, cmd in tools:
            r = run_tool(name, cmd)
            rows[name] = r
            current[name] = r["verdict"]
            print(f"[{name:8s}] {r['verdict']}")

    weekly = run_tool("weekly", [PY, os.path.join("scripts", "paper_weekly.py")])
    rows["weekly"] = weekly
    current["weekly"] = weekly["verdict"]
    wd = re.search(r"(CERTIFIED|VIOLATIONS PRESENT)[^\n]*", weekly["tail"] + weekly["verdict"])
    print(f"[weekly  ] {current['weekly']}")

    print("\n-- registered verdicts (one-look contracts, read-only) --")
    for name, v in registered().items():
        current[name] = v
        print(f"[{name}] {v}")

    print("\n-- changes vs previous run --")
    changes = 0
    for name in sorted(set(current) | set(prev)):
        old, new = prev.get(name), current.get(name)
        if old is None:
            print(f"  NEW      {name}: {new}")
            changes += 1
        elif old != new:
            print(f"  CHANGED  {name}:")
            print(f"     was: {old}")
            print(f"     now: {new}")
            changes += 1
        else:
            print(f"  unchanged {name}")
    if changes == 0:
        print("  (none)")

    with open(STATE, "w") as f:
        json.dump({"generated": now.isoformat(timespec="seconds"),
                   "verdicts": current, "details": rows}, f, indent=1)
    print(f"\nstate: {STATE}")


if __name__ == "__main__":
    main()
