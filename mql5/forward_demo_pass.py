#!/usr/bin/env python3
"""Forward-demo paper pass: UTC 18-24h & |range_z_50| < 1.5 on the sniper leg.

Runs the LIVE DecisionEngine (sniper mode; entry gate UTC [18,24) &
|range_z_50| < 1.5, the strongest measured cell) on REAL Blueberry MT5
ticks (venue=MT5 — the MT5-first rule; paper fills via
SimulatedExecutionBackend, no orders are ever sent to the terminal),
journaling every signal/rejection/outcome to
journals/forward_demo_18_24.jsonl.

The pass records the FIRST N CLOSED TRADES (default 30) on fresh,
out-of-sample forward data, then prints the summary.  The backtest cell
measured n=67 / hit 58.2% / +0.242R@RR1.2 (+0.304R@RR1.5) and the harness
measured +0.141R net@0.05 on the 12.99-day corpus — this pass confirms or
refutes that on data the model has never seen.

The loop restarts run_live_paper in chunks (default 3h) so a crash or an
MT5 disconnect just sleeps and retries; the journal is the source of truth
for progress.  Hard cap 7 days (30 trades at the measured ~5/day ≈ 6 days).

Usage:  python mql5/forward_demo_pass.py [--max-trades 30] [--chunk-sec 10800]
"""
import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

# ── MT5 venue env: the mt5_data discovery caches on a fingerprint, so set
# these BEFORE importing anything that touches MT5.  Load .env.local if it
# exists (plain KEY=VALUE), then default the Blueberry terminal path.
_env_local = os.path.join(_ROOT, ".env.local")
if os.path.exists(_env_local):
    with open(_env_local, encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('\"').strip("'"))
if not os.getenv("SYNTHETIC_MT5_TERMINAL_PATH"):
    os.environ["SYNTHETIC_MT5_TERMINAL_PATH"] = (
        r"C:\Program Files\Blueberry Markets MetaTrader 5\terminal64.exe"
    )

from synthetic_trader.config import LiveMode, TraderConfig, Venue  # noqa: E402
from synthetic_trader.execution.mt5_data import Mt5TickClient  # noqa: E402
from synthetic_trader.live.paper_runner import run_live_paper  # noqa: E402

JOURNAL = Path(_HERE) / ".." / "journals" / "forward_demo_18_24.jsonl"


def count_outcomes(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("type") == "outcome":
                n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-trades", type=int, default=30)
    ap.add_argument("--chunk-sec", type=int, default=10800)  # 3h chunks
    ap.add_argument("--hard-cap-sec", type=int, default=7 * 86400)
    args = ap.parse_args()

    # Override the R_75 SymbolProfile entry gate to UTC [18,24) & |range_z_50|<1.5
    cfg = TraderConfig.default()
    prof = cfg.symbols["R_75"]
    prof = replace(
        prof,
        entry_gate_enabled=True,
        entry_gate_hour_utc_start=18,
        entry_gate_hour_utc_end=24,
        entry_gate_max_range_z=1.5,
    )
    cfg = replace(cfg, symbols={**cfg.symbols, "R_75": prof})

    journal = JOURNAL.resolve()
    journal.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    n_before = count_outcomes(journal)
    print(
        f"[FWD] UTC18-24h/rz<1.5 forward-demo pass starting "
        f"(target {args.max_trades} closed trades, already {n_before})",
        flush=True,
    )
    print(
        f"[FWD] venue=MT5 (Blueberry) live ticks, paper fills, "
        f"chunk={args.chunk_sec}s hard_cap={args.hard_cap_sec}s journal={journal}",
        flush=True,
    )

    while count_outcomes(journal) < args.max_trades:
        if time.time() - start >= args.hard_cap_sec:
            print(f"[FWD] hard cap {args.hard_cap_sec}s reached; stopping", flush=True)
            break
        try:
            import asyncio

            summary = asyncio.run(run_live_paper(
                symbol="R_75",
                venue=Venue.MT5,
                live_mode=LiveMode.PAPER,
                client_factory=Mt5TickClient,
                config=cfg,
                duration_sec=args.chunk_sec,
                warmup_count=5000,
                timeframe_sec=60,
                higher_timeframe_sec=300,
                journal_path=journal,
            ))
            print(
                f"[FWD] chunk done: closed={summary.closed_trades} "
                f"signals={summary.signals} approved={summary.approved_signals} "
                f"rejected={summary.rejected_signals} "
                f"equity={summary.final_equity:.2f} "
                f"total_outcomes={count_outcomes(journal)}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 — the pass must survive venue hiccups
            print(f"[FWD] chunk failed: {exc!r} — sleeping 30s and retrying", flush=True)
            time.sleep(30)

    n = count_outcomes(journal)
    print(f"[FWD] PASS COMPLETE: {n} closed trades recorded at {journal}", flush=True)


if __name__ == "__main__":
    main()
