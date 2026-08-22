#!/usr/bin/env python3
"""Paper->live execution parity check — one execution layer, three paths.

The Python engine can execute an approved call via (1) the simulated backend
(forward-demo paper fills), (2) the MT5 python-API backend (the Python
CTrade-equivalent: FOK market order, broker SL/TP, modify/close by ticket),
and (3) the MQL5 ``SynthCallExecutor`` EA, which polls the call file
``ea_emitter`` writes and executes via ``CTrade``.  These must behave as ONE
execution layer: same approved call + same market path = same trade.

This harness (pure Python, no MT5 dependency — the live backend runs against
a CTrade-equivalent in-memory simulator) replays deterministic signals and
candle paths through the simulated and live backends and FAILS on ANY
disagreement: submit acceptance, open-position counts after every step, and
per-outcome direction/entry/exit/R/won/close-time.  It also verifies (a) the
live path rejects cleanly when the broker rejects (retcode != 10009), and
(b) the EA call record carries exactly the levels the Python backends
placed — so the MQL5 path shares the same execution contract.

Emits a strict machine line and exits nonzero on FAIL:

    [PARITY] PASS: compared=NNN agreed=NNN mismatches=0 trades=3 probe=ok ea=3/3
    [PARITY] FAIL: ... (mismatch detail)

Usage:  python mql5/execution_parity_check.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from synthetic_trader.config import Mt5Config, PaperExecutionConfig  # noqa: E402
from synthetic_trader.domain import (  # noqa: E402
    Candle,
    Direction,
    FeatureSnapshot,
    OrderIntent,
    Regime,
    TradeSignal,
)
from synthetic_trader.execution.mt5_simulator import FakeMetaTrader5  # noqa: E402
from synthetic_trader.execution.parity import (  # noqa: E402
    check_ea_contract,
    run_parity_replay,
    run_rejection_probe,
)

MT5_CONFIG = Mt5Config(symbol_map={"R_75": "SYN75"})
PAPER_CONFIG = PaperExecutionConfig()  # zero slippage / penalty -> exact parity

EA_MAGIC = 7788123  # mirrors SynthCallExecutor.mq5 InpMagic


def _signal(
    direction: Direction,
    entry: float,
    sl: float,
    tp: float,
    horizon_sec: int = 86400,
    epoch: float = 1_700_000_000.0,
) -> TradeSignal:
    return TradeSignal(
        symbol="R_75",
        direction=direction,
        confidence=0.7,
        min_confidence=0.5,
        entry=entry,
        stop_loss=sl,
        take_profit=tp,
        horizon_sec=horizon_sec,
        snapshot=FeatureSnapshot(
            symbol="R_75",
            epoch=epoch,
            timeframe_sec=300,
            features={"rz": 0.8, "z": 1.2},
            regime=Regime.TREND_UP,
            structure={},
        ),
        rationale=("parity-check",),
        model_version="parity",
    )


def _intent(signal: TradeSignal, volume: float = 0.1) -> OrderIntent:
    return OrderIntent(
        signal=signal,
        stake=50.0,
        max_loss=50.0,
        metadata={"volume": volume},
    )


def _candle(open_time: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        symbol="R_75",
        timeframe_sec=300,
        open_time=open_time,
        open=o,
        high=h,
        low=l,
        close=c,
    )


def _benign(open_time: int, base: float = 1700.0) -> Candle:
    return _candle(open_time, base + 1, base + 3, base, base + 2)


def main() -> int:
    failures: list[str] = []
    compared_total = 0
    agreed_total = 0
    trades = 0
    contract_ok = 0
    contract_total = 0

    # ── three deterministic trades exercising each exit class ────────────
    # Trade 1: BUY RR 1.2 -> target hit.  Trade 2: SELL RR 3.0 -> stop hit.
    # Trade 3: BUY RR 1.2 -> horizon expiry (exit at close).
    cases = [
        (
            _signal(Direction.LONG, 1700.0, 1690.0, 1712.0),
            [
                _benign(1_700_000_000),
                _candle(1_700_000_300, 1708.0, 1713.0, 1705.0, 1712.0),  # target
            ],
        ),
        (
            _signal(Direction.SHORT, 1700.0, 1710.0, 1695.0),
            [
                _benign(1_700_000_000),
                _candle(1_700_000_300, 1708.0, 1711.0, 1702.0, 1710.0),  # stop
            ],
        ),
        (
            _signal(Direction.LONG, 1700.0, 1690.0, 1712.0, horizon_sec=300, epoch=1_700_000_000.0),
            [
                _candle(1_700_000_000, 1701.0, 1702.0, 1699.0, 1701.0),  # expiry -> close
            ],
        ),
    ]

    for signal, candles in cases:
        intent = _intent(signal)
        trades += 1
        sim = FakeMetaTrader5(bid=signal.entry, ask=signal.entry)
        report = run_parity_replay(
            symbol="R_75",
            intents=[intent],
            candles=candles,
            mt5_simulator=sim,
            mt5_config=MT5_CONFIG,
            paper_config=PAPER_CONFIG,
        )
        compared_total += report.compared
        agreed_total += report.agreed
        for item in report.mismatches:
            failures.append(
                f"trade {trades} [{item.step}/{item.aspect}]: paper={item.paper!r} "
                f"live={item.live!r} ({item.detail})"
            )

        ok, detail = check_ea_contract(
            intent=intent,
            symbol="R_75",
            venue_symbol="SYN75",
            volume=0.1,
            magic=EA_MAGIC,
        )
        contract_total += 1
        if ok:
            contract_ok += 1
        else:
            failures.append(f"EA contract trade {trades}: {detail}")

    # ── broker rejection: live must reject cleanly (CTrade retcode != 10009)
    probe_ok = run_rejection_probe(
        symbol="R_75",
        intent=_intent(cases[0][0]),
        mt5_config=MT5_CONFIG,
    )
    if not probe_ok:
        failures.append("rejection probe: live backend accepted a rejected broker order")

    if failures:
        print("[PARITY] FAIL: " + "; ".join(failures), flush=True)
        for failure in failures:
            print(f"    - {failure}", flush=True)
        return 1

    print(
        f"[PARITY] PASS: compared={compared_total} agreed={agreed_total} "
        f"mismatches=0 trades={trades} probe=ok ea={contract_ok}/{contract_total}",
        flush=True,
    )
    print("[EACONTRACT] PASS: all call records match the executed levels", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
