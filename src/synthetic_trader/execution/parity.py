"""Paper->live execution parity: one execution contract, two backends.

The Python engine can execute an approved call two ways:

1. **Simulated** (``SimulatedExecutionBackend`` / ``PaperBroker``) — the
   forward-demo path; fills are simulated from signal levels.
2. **Live MT5** (``Mt5LiveExecutionBackend`` via the MetaTrader5 python API,
   the Python CTrade-equivalent) — places real FOK market orders with broker
   SL/TP.
3. **EA** (``SynthCallExecutor.mq5``, MQL5 ``CTrade``) — reads the call file
   ``ea_emitter`` writes and executes the identical levels natively.

These must be ONE execution layer: for the same approved call and the same
market path, all three must produce the same trade — same direction, entry,
exit, R, and open-position count.  This module proves that for the paper and
live-MT5 backends by replaying identical ``OrderIntent`` streams and candle
streams through both, comparing every decision; ``check_ea_contract`` proves
the EA's call file carries exactly the levels the Python backends executed,
so the MQL5 path shares the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from synthetic_trader.config import Mt5Config, PaperExecutionConfig
from synthetic_trader.domain import Candle, Direction, OrderIntent
from synthetic_trader.execution.ea_emitter import build_call_record
from synthetic_trader.execution.mt5_simulator import FakeMetaTrader5
from synthetic_trader.live.execution_backends import (
    Mt5LiveExecutionBackend,
    SimulatedExecutionBackend,
)

# return_r comparison tolerance (float drift across the two PnL paths).
R_TOLERANCE = 1e-9


class _NoopJournal:
    """Minimal journal stand-in for the live backend's record_event calls."""

    def record_event(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None

    def record_outcome(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None


@dataclass(frozen=True)
class ParityItem:
    step: str          # "submit:0" | "candle:3" | "shutdown"
    aspect: str        # "accept" | "open_positions" | "outcome_count" | "outcome:i:field"
    paper: object
    live: object
    ok: bool
    detail: str = ""


@dataclass
class ParityReport:
    items: list[ParityItem] = field(default_factory=list)
    compared: int = 0
    agreed: int = 0

    @property
    def mismatches(self) -> list[ParityItem]:
        return [item for item in self.items if not item.ok]

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def add(self, item: ParityItem) -> None:
        self.items.append(item)
        self.compared += 1
        if item.ok:
            self.agreed += 1

    def summary(self) -> str:
        return f"compared={self.compared} agreed={self.agreed} mismatches={len(self.mismatches)}"


def _as_bool(value: object) -> bool:
    return bool(value)


def _close_to(a: float, b: float, tol: float = R_TOLERANCE) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def run_parity_replay(
    *,
    symbol: str,
    intents: list[OrderIntent],
    candles: list[Candle],
    mt5_simulator: FakeMetaTrader5,
    mt5_config: Mt5Config,
    paper_config: PaperExecutionConfig | None = None,
    journal=None,
    fill_price: Mapping[int, float] | None = None,
) -> ParityReport:
    """Replay identical intents + candles through both backends and compare.

    ``fill_price`` maps intent index -> price the broker fills at (defaults to
    the intent's entry level).  The report FAILs on any disagreement: submit
    acceptance, open-position counts after every step, and per-outcome
    direction/entry/exit/return_r/won/close time.
    """
    report = ParityReport()
    paper_cfg = paper_config or PaperExecutionConfig()
    paper = SimulatedExecutionBackend(config=paper_cfg)
    live = Mt5LiveExecutionBackend(
        mt5_config=mt5_config,
        symbol=symbol,
        journal=journal or _NoopJournal(),
        mt5_module=mt5_simulator,
    )

    # ── submits ──────────────────────────────────────────────────────────
    for i, intent in enumerate(intents):
        if fill_price is not None and i in fill_price:
            price = fill_price[i]
            mt5_simulator.bid = price
            mt5_simulator.ask = price
        else:
            mt5_simulator.bid = intent.signal.entry
            mt5_simulator.ask = intent.signal.entry

        p_res = paper.submit(intent)
        l_res = live.submit(intent)
        report.add(
            ParityItem(
                step=f"submit:{i}",
                aspect="accept",
                paper=p_res.accepted,
                live=l_res.accepted,
                ok=(p_res.accepted == l_res.accepted),
                detail=f"paper={p_res.accepted} live={l_res.accepted}",
            )
        )
        report.add(
            ParityItem(
                step=f"submit:{i}",
                aspect="open_positions",
                paper=paper.open_positions_count(),
                live=live.open_positions_count(),
                ok=(paper.open_positions_count() == live.open_positions_count()),
                detail=(
                    f"paper={paper.open_positions_count()} live={live.open_positions_count()}"
                ),
            )
        )

    # ── candle stream ────────────────────────────────────────────────────
    for i, candle in enumerate(candles):
        p_outcomes = paper.on_candle(candle)
        l_outcomes = live.on_candle(candle)
        report.add(
            ParityItem(
                step=f"candle:{i}",
                aspect="outcome_count",
                paper=len(p_outcomes),
                live=len(l_outcomes),
                ok=(len(p_outcomes) == len(l_outcomes)),
                detail=f"paper={len(p_outcomes)} live={len(l_outcomes)}",
            )
        )
        for j in range(max(len(p_outcomes), len(l_outcomes))):
            if j >= len(p_outcomes) or j >= len(l_outcomes):
                break  # count mismatch already reported above
            p, l = p_outcomes[j], l_outcomes[j]
            for field_name in ("direction", "entry", "exit", "return_r", "won", "closed_at"):
                pv = getattr(p, field_name)
                lv = getattr(l, field_name)
                ok = pv == lv
                if isinstance(pv, float) and isinstance(lv, float):
                    ok = _close_to(pv, lv)
                report.add(
                    ParityItem(
                        step=f"candle:{i}",
                        aspect=f"outcome:{j}:{field_name}",
                        paper=pv,
                        live=lv,
                        ok=ok,
                        detail=f"paper={pv!r} live={lv!r}",
                    )
                )
        report.add(
            ParityItem(
                step=f"candle:{i}",
                aspect="open_positions",
                paper=paper.open_positions_count(),
                live=live.open_positions_count(),
                ok=(paper.open_positions_count() == live.open_positions_count()),
                detail=(
                    f"paper={paper.open_positions_count()} live={live.open_positions_count()}"
                ),
            )
        )

    # ── shutdown ─────────────────────────────────────────────────────────
    p_shut = paper.shutdown(candles[-1] if candles else None)
    l_shut = live.shutdown(candles[-1] if candles else None)
    report.add(
        ParityItem(
            step="shutdown",
            aspect="open_positions_before_shutdown",
            paper=p_shut.open_positions_before_shutdown,
            live=l_shut.open_positions_before_shutdown,
            ok=(p_shut.open_positions_before_shutdown == l_shut.open_positions_before_shutdown),
            detail=(
                f"paper={p_shut.open_positions_before_shutdown} "
                f"live={l_shut.open_positions_before_shutdown}"
            ),
        )
    )
    report.add(
        ParityItem(
            step="shutdown",
            aspect="unresolved_positions",
            paper=p_shut.unresolved_positions,
            live=l_shut.unresolved_positions,
            ok=(p_shut.unresolved_positions == l_shut.unresolved_positions),
            detail=f"paper={p_shut.unresolved_positions} live={l_shut.unresolved_positions}",
        )
    )
    return report


def run_rejection_probe(
    *,
    symbol: str,
    intent: OrderIntent,
    mt5_config: Mt5Config,
    reject_retcode: int = 10014,
) -> bool:
    """Live path must reject cleanly when the broker rejects (CTrade retcode
    != 10009): submit reports not-accepted and no position is tracked."""
    sim = FakeMetaTrader5(bid=intent.signal.entry, ask=intent.signal.entry, reject_retcode=reject_retcode)
    live = Mt5LiveExecutionBackend(
        mt5_config=mt5_config,
        symbol=symbol,
        journal=_NoopJournal(),
        mt5_module=sim,
    )
    res = live.submit(intent)
    if res.accepted:
        return False
    if live.open_positions_count() != 0:
        return False
    if sim.open_position_count != 0:
        return False
    return True


def check_ea_contract(
    *,
    intent: OrderIntent,
    symbol: str,
    venue_symbol: str,
    volume: float,
    magic: int,
    record: Mapping[str, object] | None = None,
) -> tuple[bool, str]:
    """The EA path must execute EXACTLY the levels the Python backends placed.

    ``record`` is the call file record the EA would consume.  When omitted it
    is built from the approved signal via ``build_call_record`` (validating
    the emitter contract end-to-end); when supplied it is compared against the
    intent directly — so a record that drifted from the executed levels (e.g.
    an alert whose ``execution_stop`` diverged from the signal) is caught.
    The MQL5 CTrade path and the Python MT5-API path must share one contract.
    """
    signal = intent.signal
    direction = "buy" if signal.direction is Direction.LONG else "sell"
    if record is None:
        alert: dict[str, object] = {
            "direction_bias": direction,
            "entry": signal.entry,
            "execution_stop": signal.stop_loss,
            "primary_target": signal.take_profit,
            "hold_horizon_minutes": signal.horizon_sec // 60,
            "generated_at": signal.snapshot.epoch,
            "evidence_status": "proven",
        }
        try:
            record = build_call_record(
                alert,
                symbol=symbol,
                venue_symbol=venue_symbol,
                volume=volume,
                magic=magic,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"build_call_record raised: {exc!r}"

    if record["direction"] != direction:
        return False, f"direction mismatch: record={record['direction']} intent={direction}"
    if record["venue_symbol"] != venue_symbol:
        return False, f"venue_symbol mismatch: record={record['venue_symbol']} expected={venue_symbol}"
    for key, (recorded, expected) in {
        "entry": (float(str(record["entry"])), float(signal.entry)),
        "stop_loss": (float(str(record["stop_loss"])), float(signal.stop_loss)),
        "take_profit": (float(str(record["take_profit"])), float(signal.take_profit)),
        "volume": (float(str(record["volume"])), float(volume)),
    }.items():
        if abs(recorded - expected) > R_TOLERANCE * max(1.0, abs(expected)):
            return False, f"{key} mismatch: record={recorded} intent={expected}"
    return True, (
        f"{direction} entry={signal.entry} sl={signal.stop_loss} tp={signal.take_profit} "
        f"vol={volume} -> call_id={record['call_id']}"
    )
