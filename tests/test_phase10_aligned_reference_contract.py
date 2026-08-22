"""Locks the P10-A aligned reference contract (2026-08-16 matrix basis).

The Phase-10 P10-A gate pairs the EA's [PHASE10] machine line against the CLI
`backtest-vol --mode band` reference run on the R_75 tick corpus with the
ALIGNED risk basis (--max-consecutive-losses 9999 --max-daily-loss-frac 1.0,
matching InpMaxConsecLosses=9999 / InpMaxDailyLossPct=1.0 so both approve
every signal like the anchored fit does).  The documented pair on the
full-window matrix corpus (Jul 30 -> Aug 16) is EA 98 vs CLI ~102 (Δ4 <= 10)
with a negative CLI expectancy.

This test replays that exact invocation against the WINDOWED parity corpus
(data/backfill/R_75_ticks.windowed.csv — union of the pre-repair head and the
live backfill, repaired from the terminal's M1 history, clipped exactly to the
tester window Jul 30 00:00 -> Aug 16 00:00; rebuilt 2026-08-18) and asserts
the two contract legs:

  * |trades - 98| <= 10   (the STRICT trade-count tolerance)
  * expectancy_r < 0      (the sign-lock)

If the windowed corpus is not present (archived/deleted), the test SKIPS with
a clear reason instead of false-redding the suite — the live CSV spans a
different window and the strict count pair does not apply to it (the gate
itself is data-aware about this).  Runs the real CLI in a subprocess exactly
as verify_all.ps1 does; slow by nature (~1-3 min) so it is a genuine
integration lock, not a unit stub.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO_ROOT, "data", "backfill", "R_75_ticks.windowed.csv")
DOCUMENTED_EA_TRADES = 98
STRICT_TOLERANCE = 10


@pytest.fixture(scope="module")
def cli_reference() -> dict[str, float]:
    """Run the exact P10-A CLI reference against the matrix corpus."""
    if not os.path.exists(CORPUS):
        pytest.skip(f"matrix corpus not found at {CORPUS} (pre-repair basis archived?) - strict pair not applicable")

    cmd = [
        sys.executable,
        "-m",
        "synthetic_trader.cli",
        "backtest-vol",
        "--csv",
        CORPUS,
        "--symbol",
        "R_75",
        "--timeframe",
        "300",
        "--mode",
        "band",
        "--max-consecutive-losses",
        "9999",
        "--max-daily-loss-frac",
        "1.0",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=900,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, (
        f"backtest-vol failed (exit {proc.returncode}): "
        f"{proc.stderr[-2000:]}"
    )
    trades = re.search(r"^trades=(\d+)", proc.stdout, re.MULTILINE)
    exp = re.search(r"^expectancy_r=(-?[\d.]+)", proc.stdout, re.MULTILINE)
    assert trades, f"no trades= line in CLI output:\n{proc.stdout[-3000:]}"
    assert exp, f"no expectancy_r= line in CLI output:\n{proc.stdout[-3000:]}"
    return {"trades": int(trades.group(1)), "expectancy_r": float(exp.group(1))}


def test_aligned_trade_count_within_delta10(cli_reference: dict[str, float]) -> None:
    """STRICT leg: CLI trades within Δ10 of the documented EA count 98."""
    delta = abs(cli_reference["trades"] - DOCUMENTED_EA_TRADES)
    assert delta <= STRICT_TOLERANCE, (
        f"P10-A STRICT breach: CLI {cli_reference['trades']} vs documented EA "
        f"{DOCUMENTED_EA_TRADES} differ by {delta} > {STRICT_TOLERANCE}"
    )


def test_aligned_expectancy_negative(cli_reference: dict[str, float]) -> None:
    """Sign-lock leg: the aligned band reference stays negative on R_75."""
    assert cli_reference["expectancy_r"] < 0.0, (
        f"P10 sign flip: CLI expectancy {cli_reference['expectancy_r']} is "
        "non-negative on the calibrated real-tick basis"
    )
