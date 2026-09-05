#!/usr/bin/env python3
"""Verify repository-side go-live artifacts without touching MT5 or the broker.

Usage:
    python scripts/verify_go_live_artifacts.py
    python scripts/verify_go_live_artifacts.py --deployed-live C:\\path\\VOL75_LIVE.set

The repository can prove the checked-in preset and source markers. A deployed
preset is only byte-identity verified when its path is supplied explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI.mq5"
LIVE = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_LIVE.set"
FINAL = ROOT / "mql5" / "MITEMSHUB_AI" / "MitemshubAI_VOL75_FINAL.set"
EXPECTED_VERSION = "26.35"
EXPECTED_FLEET = {"7788075", "7788100"}


class VerificationError(Exception):
    """A go-live artifact failed a repository invariant."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_set(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith(("#", ";", "[")):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def verify_source(source: Path = SOURCE) -> list[str]:
    text = source.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    version = re.search(r'#define\s+APP_VERSION\s+"([\d.]+)"', text)
    if not version or version.group(1) != EXPECTED_VERSION:
        problems.append(f"APP_VERSION is {version.group(1) if version else 'missing'}, expected {EXPECTED_VERSION}")
    markers = (
        f'MITEMSHUB AI v"+APP_VERSION+" started',
        "Standard Mode",
        "PAPER MODE:",
        "FIT ROUTER:",
        "RiskCap=",
        "WARNING: risk cap > 10%",
        "[SELFTEST]",
        "GARCH",
        "Telemetry ->",
        "State    ->",
        "Executing ",
        "ORDER FAILED retcode=",
    )
    for marker in markers:
        if marker not in text:
            problems.append(f"missing source marker: {marker}")
    if "#define APP_VERSION \"26.35\"" not in text:
        problems.append("source version definition is not the expected single source")
    return problems


def verify_preset(path: Path, *, live: bool) -> list[str]:
    values = read_set(path)
    problems: list[str] = []
    expected = {
        "InpMagic": "7788075",
        "InpTpMult": "1.8",
        "InpPaperEquity": "50.0",
    }
    if live:
        expected["InpLiveExecution"] = "true"
    else:
        expected["InpLiveExecution"] = "false"
    for key, value in expected.items():
        if values.get(key) != value:
            problems.append(f"{path.name}: {key}={values.get(key)!r}, expected {value!r}")
    fleet = {x.strip() for x in values.get("InpFleetMagicsCSV", "").split(",") if x.strip()}
    missing_fleet = EXPECTED_FLEET - fleet
    if missing_fleet:
        problems.append(f"{path.name}: fleet CSV missing {sorted(missing_fleet)}")
    return problems


def verify(deployed_live: Path | None = None) -> dict:
    problems = []
    for path in (SOURCE, LIVE, FINAL):
        if not path.exists():
            problems.append(f"missing artifact: {path}")
    if not problems:
        problems.extend(verify_source())
        problems.extend(verify_preset(LIVE, live=True))
        problems.extend(verify_preset(FINAL, live=False))
        live_values = read_set(LIVE)
        final_values = read_set(FINAL)
        for key in sorted(set(live_values) & set(final_values)):
            if key != "InpLiveExecution" and live_values[key] != final_values[key]:
                problems.append(f"LIVE/FINAL drift in {key}: {live_values[key]!r} != {final_values[key]!r}")
    result = {
        "version": EXPECTED_VERSION,
        "source": str(SOURCE.relative_to(ROOT)),
        "repo_live_preset": str(LIVE.relative_to(ROOT)),
        "repo_live_sha256": sha256(LIVE) if LIVE.exists() else None,
        "repo_final_sha256": sha256(FINAL) if FINAL.exists() else None,
        "deployed_live": str(deployed_live) if deployed_live else None,
        "deployed_live_sha256": sha256(deployed_live) if deployed_live and deployed_live.exists() else None,
        "deployed_byte_identical": (sha256(deployed_live) == sha256(LIVE)
                                    if deployed_live and deployed_live.exists() and LIVE.exists() else None),
        "problems": problems,
        "ok": not problems and not (deployed_live and not deployed_live.exists()),
    }
    if deployed_live and not deployed_live.exists():
        result["problems"].append(f"deployed preset not found: {deployed_live}")
        result["ok"] = False
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deployed-live", type=Path,
                    help="optional explicitly supplied deployed .set to hash-compare with repo")
    args = ap.parse_args(argv)
    result = verify(args.deployed_live)
    print(f"GO-LIVE ARTIFACTS: {'PASS' if result['ok'] else 'FAIL'}")
    print(f"  source/preset version: v{result['version']}")
    print(f"  repo LIVE sha256: {result['repo_live_sha256']}")
    if result["deployed_live"]:
        print(f"  deployed LIVE sha256: {result['deployed_live_sha256']}")
        print(f"  deployed byte-identical: {result['deployed_byte_identical']}")
    if result["problems"]:
        for problem in result["problems"]:
            print(f"  FAIL: {problem}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
