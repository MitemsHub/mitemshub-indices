#!/usr/bin/env python3
"""Calibration-sanity gate for verify_all.ps1.

Loads the on-disk EGARCH calibration JSONs (data/garch_calibration/*.json —
the exact files the live engine and the band reference load on startup) and
verifies each fit would actually be accepted:

  - the file exists and parses,
  - convergence is True (a degenerate / all-basins-rejected fit reports
    False and the loader falls back to default priors),
  - _params_at_bounds(result) is False (bound-pinned, no-clustering,
    absurd-NLL, or absurd long-run-ratio fits are never usable), and
  - vol_ratio is inside the healthy band [0.02, 50] (criterion-3 semantics,
    checked first-class so a regeneration that drifts the ratio fails the
    loop with a specific message even if the predicate itself were to change).

Emits [CALIB] machine lines (one per symbol + a summary) so the PowerShell
verifier can parse and gate on them.  Exit code 0 = all healthy, 1 = any
problem, 2 = the calibration directory or dependencies are missing.

This gate deliberately validates the JSONs the engine WILL load rather than
re-fitting (a full calibrate-egarch run takes minutes per symbol) — the
purpose is to fail loudly the moment a regenerated fit becomes unusable,
not to re-derive it.
"""

import sys
from pathlib import Path

from synthetic_trader.models.garch_calibration import (
    _params_at_bounds,
    load_calibration_result,
)

# Same healthy band as _params_at_bounds criterion 3 (per-bar scale).
VOL_RATIO_MIN = 0.02
VOL_RATIO_MAX = 50.0

# mql5/calibration_sanity_check.py -> repo root -> data/garch_calibration.
CALIB_DIR = Path(__file__).resolve().parents[1] / "data" / "garch_calibration"

SYMBOLS = ("R_75", "R_100")


def main() -> int:
    if not CALIB_DIR.is_dir():
        print(f"[CALIB] summary ok=0 n_problems=1 problem=calibration_dir_missing:{CALIB_DIR}")
        return 2

    problems: list[str] = []
    for sym in SYMBOLS:
        path = CALIB_DIR / f"{sym.lower()}.json"
        if not path.exists():
            problems.append(f"{sym}: calibration file missing at {path}")
            print(f"[CALIB] symbol={sym} ok=0 reason=missing_file")
            continue
        try:
            result = load_calibration_result(path)
        except Exception as exc:  # json decode / KeyError / OSError
            problems.append(f"{sym}: unparseable calibration: {exc}")
            print(f"[CALIB] symbol={sym} ok=0 reason=unparseable")
            continue

        reason: str | None = None
        if not result.convergence:
            reason = f"convergence=False ({result.message})"
        elif _params_at_bounds(result):
            reason = "rejected by _params_at_bounds"
        elif not (VOL_RATIO_MIN <= result.vol_ratio <= VOL_RATIO_MAX):
            reason = (
                f"vol_ratio={result.vol_ratio:.4f} outside "
                f"[{VOL_RATIO_MIN}, {VOL_RATIO_MAX}]"
            )
        ok = 1 if reason is None else 0
        if reason:
            problems.append(f"{sym}: {reason}")
        print(
            f"[CALIB] symbol={sym} ok={ok} omega={result.omega:.4f} "
            f"alpha={result.alpha:.4f} beta={result.beta:.4f} "
            f"gamma={result.gamma:.4f} persistence={result.persistence:.4f} "
            f"vol_ratio={result.vol_ratio:.4f} "
            f"n={result.n_observations} reason={reason or 'ok'}"
        )

    all_ok = len(problems) == 0
    print(f"[CALIB] summary ok={1 if all_ok else 0} n_problems={len(problems)}")
    for p in problems:
        print(f"[CALIB] problem {p}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
