from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from synthetic_trader.domain import TradeOutcome, TradeSignal
from synthetic_trader.models.online import OnlineLogisticModel


@dataclass(frozen=True)
class JournalMetrics:
    trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    net_pnl: float


class TradeJournal:
    """Append-only trade journal with automatic line-count pruning.

    Keeps at most MAX_LINES entries in the JSONL file. When the file exceeds
    this limit, the oldest entries are trimmed after each append. Set
    max_lines=0 to disable pruning (unbounded growth).
    """

    # Default: keep the most recent 10,000 journal entries. This preserves
    # roughly 10-20 MB of history, which is enough for months of trading.
    # Override via the constructor or by subclassing.
    MAX_LINES: int = 10_000

    def __init__(self, path: str | Path, max_lines: int | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._max_lines = max_lines if max_lines is not None else self.MAX_LINES

    def record_signal(self, signal: TradeSignal) -> None:
        self._append(
            {
                "type": "signal",
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "confidence": signal.confidence,
                "entry": signal.entry,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "reward_risk": signal.reward_risk,
                "epoch": signal.snapshot.epoch,
                "regime": signal.snapshot.regime.value,
                "rationale": list(signal.rationale),
                "model_version": signal.model_version,
            }
        )

    def record_outcome(self, outcome: TradeOutcome) -> None:
        payload = asdict(outcome)
        payload["direction"] = outcome.direction.value
        payload["type"] = "outcome"
        self._append(payload)

    def record_rejection(
        self,
        *,
        symbol: str,
        epoch: float,
        reasons: tuple[str, ...],
        model_version: str,
        confidence: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self._append(
            {
                "type": "rejection",
                "symbol": symbol,
                "epoch": epoch,
                "reasons": list(reasons),
                "model_version": model_version,
                "confidence": confidence,
                "metadata": metadata or {},
            }
        )

    def record_event(self, event_type: str, payload: dict[str, object]) -> None:
        self._append({"type": event_type, **payload})

    def record_mt5_sync_summary(
        self,
        *,
        symbol: str,
        venue_symbol: str | None,
        positions: int,
        failures: tuple[str, ...],
    ) -> None:
        self.record_event(
            "mt5_sync_summary",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "positions": positions,
                "failures": list(failures),
            },
        )

    def record_mt5_runtime_summary(
        self,
        *,
        symbol: str,
        venue_symbol: str | None,
        ready: bool,
        failures: tuple[str, ...],
    ) -> None:
        self.record_event(
            "mt5_runtime_summary",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "ready": ready,
                "failures": list(failures),
            },
        )

    def record_mt5_reconcile_summary(
        self,
        *,
        symbol: str,
        target_ticket: int | None,
        actionable: bool,
        failures: tuple[str, ...],
    ) -> None:
        self.record_event(
            "mt5_reconcile_summary",
            {
                "symbol": symbol,
                "target_ticket": target_ticket,
                "actionable": actionable,
                "failures": list(failures),
            },
        )

    def record_mt5_close_result(
        self,
        *,
        symbol: str,
        venue_symbol: str,
        ticket: int,
        accepted: bool,
        retcode: int | None,
        message: str,
    ) -> None:
        self.record_event(
            "mt5_close_result",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "ticket": ticket,
                "accepted": accepted,
                "retcode": retcode,
                "message": message,
            },
        )

    def record_mt5_modify_result(
        self,
        *,
        symbol: str,
        venue_symbol: str,
        ticket: int,
        accepted: bool,
        retcode: int | None,
        message: str,
    ) -> None:
        self.record_event(
            "mt5_modify_result",
            {
                "symbol": symbol,
                "venue_symbol": venue_symbol,
                "ticket": ticket,
                "accepted": accepted,
                "retcode": retcode,
                "message": message,
            },
        )

    def outcomes(self) -> list[TradeOutcome]:
        outcomes: list[TradeOutcome] = []
        if not self.path.exists():
            return outcomes
        for line in self.path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if payload.get("type") != "outcome":
                continue
            from synthetic_trader.domain import Direction

            payload = dict(payload)
            payload.pop("type", None)
            payload["direction"] = Direction(payload["direction"])
            outcomes.append(TradeOutcome(**payload))
        return outcomes

    def metrics(self) -> JournalMetrics:
        outcomes = self.outcomes()
        return metrics_from_outcomes(outcomes)

    def teach(self, model: OnlineLogisticModel, outcome: TradeOutcome) -> float:
        label = 1 if outcome.won else 0
        return model.update(dict(outcome.features), label=label, sample_weight=min(2.0, max(0.25, abs(outcome.return_r))))

    def _append(self, payload: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        # ── Prune to max_lines after each append ──
        # If the file has grown beyond MAX_LINES entries, rewrite it with
        # only the most recent MAX_LINES lines. This prevents journal files
        # from growing unbounded over months of trading.
        if self._max_lines > 0 and self.path.stat().st_size > 50_000:
            self._prune(self._max_lines)

    def _prune(self, max_lines: int) -> None:
        """Keep only the most recent `max_lines` entries in the journal file."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= max_lines:
                return
            # Keep the last max_lines lines (most recent)
            with self.path.open("w", encoding="utf-8") as f:
                f.write("\n".join(lines[-max_lines:]) + "\n")
        except Exception:
            pass  # Best-effort; pruning should never crash the trading system.


def metrics_from_outcomes(outcomes: list[TradeOutcome]) -> JournalMetrics:
    if not outcomes:
        return JournalMetrics(trades=0, win_rate=0.0, profit_factor=0.0, expectancy_r=0.0, net_pnl=0.0)

    wins = [outcome for outcome in outcomes if outcome.pnl > 0]
    gross_profit = sum(outcome.pnl for outcome in outcomes if outcome.pnl > 0)
    gross_loss = abs(sum(outcome.pnl for outcome in outcomes if outcome.pnl < 0))
    expectancy_r = sum(outcome.return_r for outcome in outcomes) / len(outcomes)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    return JournalMetrics(
        trades=len(outcomes),
        win_rate=len(wins) / len(outcomes),
        profit_factor=profit_factor,
        expectancy_r=expectancy_r,
        net_pnl=sum(outcome.pnl for outcome in outcomes),
    )


def summarize_run_diagnostics(
    *,
    metrics: JournalMetrics,
    signals: int,
    rejected_signals: int,
    shutdown_closed_trades: int,
    session_resets: int,
) -> dict[str, float | int]:
    approved_signals = max(0, signals - rejected_signals)
    total_signals = max(signals, 1)
    return {
        "signals": signals,
        "approved_signals": approved_signals,
        "rejected_signals": rejected_signals,
        "trades": metrics.trades,
        "approval_rate": approved_signals / total_signals,
        "rejection_rate": rejected_signals / total_signals,
        "shutdown_closed_trades": shutdown_closed_trades,
        "session_resets": session_resets,
        "net_pnl": metrics.net_pnl,
        "expectancy_r": metrics.expectancy_r,
    }
