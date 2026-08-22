from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import time
from typing import Any

from synthetic_trader.config import LiveMode, Mt5Config, Venue
from synthetic_trader.execution.mt5 import (
    Mt5CloseRequest,
    Mt5ModifyRequest,
    Mt5OrderRequest,
    Mt5OrderResult,
    Mt5ReconcileResult,
    Mt5RuntimeStatus,
    Mt5SyncResult,
    close_mt5_position,
    modify_mt5_position,
    place_mt5_order,
)


@dataclass(frozen=True)
class LiveReadinessReport:
    mode: LiveMode
    ready: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class LatencyStage:
    name: str
    duration_ms: float
    category: str


@dataclass(frozen=True)
class LatencyProfile:
    stages: tuple[LatencyStage, ...] = field(default_factory=tuple)

    @property
    def total_duration_ms(self) -> float:
        return round(sum(stage.duration_ms for stage in self.stages), 6)


class LatencyRecorder:
    def __init__(self) -> None:
        self._stages: list[LatencyStage] = []

    def record_stage(self, name: str, *, duration_ms: float, category: str) -> None:
        self._stages.append(
            LatencyStage(
                name=name,
                duration_ms=round(duration_ms, 6),
                category=category,
            )
        )

    def build_profile(self) -> LatencyProfile:
        return LatencyProfile(stages=tuple(self._stages))


def build_live_readiness_report(
    *,
    venue: Venue = Venue.DERIV,
    mode: LiveMode,
    symbol: str,
    app_id: str | None,
    token: str | None,
    armed: bool,
    supported_symbols: set[str],
    mt5_config: Mt5Config | None = None,
    mt5_dependency_ready: bool = False,
    mt5_runtime_status: Mt5RuntimeStatus | None = None,
) -> LiveReadinessReport:
    failures: list[str] = []

    if symbol not in supported_symbols:
        failures.append("unsupported_symbol")
    if venue is Venue.DERIV and mode in {LiveMode.DRY_RUN_LIVE, LiveMode.ARMED_LIVE} and not app_id:
        failures.append("missing_app_id")
    if venue is Venue.DERIV and mode is LiveMode.ARMED_LIVE and not token:
        failures.append("missing_api_token")
    if venue is Venue.MT5:
        cfg = mt5_config or Mt5Config()
        if not cfg.server:
            failures.append("missing_mt5_server")
        if not cfg.login:
            failures.append("missing_mt5_login")
        if not cfg.password:
            failures.append("missing_mt5_password")
        if not cfg.resolve_symbol(symbol):
            failures.append("missing_mt5_symbol_mapping")
        if not mt5_dependency_ready:
            failures.append("missing_mt5_runtime")
        runtime_status = mt5_runtime_status
        if runtime_status is not None:
            failures.extend(runtime_status.failures)
    if mode is LiveMode.ARMED_LIVE and not armed:
        failures.append("missing_armed_confirmation")

    return LiveReadinessReport(
        mode=mode,
        ready=not failures,
        failures=tuple(failures),
    )


async def execute_supervised_order(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    client: Any,
    proposal_id: str,
    price: float,
):
    if not readiness_ok:
        raise RuntimeError("live readiness failed")
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("live order placement is not allowed in this mode")
    return await client.buy(proposal_id, price)


async def run_supervised_live_session(
    *,
    venue: Venue = Venue.DERIV,
    mode: LiveMode,
    readiness_ok: bool,
    dry_run_runner: Callable[[], Awaitable[Any]],
    armed_runner: Callable[[], Awaitable[Any]],
    capture_latency: bool = False,
) -> Any:
    recorder = LatencyRecorder() if capture_latency else None

    readiness_start = time.perf_counter()
    if not readiness_ok:
        raise RuntimeError(f"{venue.value} readiness failed")
    if recorder is not None:
        recorder.record_stage(
            "readiness_gate",
            duration_ms=(time.perf_counter() - readiness_start) * 1000.0,
            category="critical",
        )

    route_start = time.perf_counter()
    if mode is LiveMode.DRY_RUN_LIVE:
        result = await dry_run_runner()
    elif mode is LiveMode.ARMED_LIVE:
        result = await armed_runner()
    else:
        raise RuntimeError("supervised live session is not used in paper mode")
    if recorder is not None:
        recorder.record_stage(
            "supervised_route",
            duration_ms=(time.perf_counter() - route_start) * 1000.0,
            category="critical",
        )
        return result, recorder.build_profile()
    return result


def execute_supervised_mt5_order(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    request: Mt5OrderRequest,
    mt5_module,
) -> Mt5OrderResult | str:
    if not readiness_ok:
        raise RuntimeError("mt5 readiness failed")
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("mt5 order placement is not allowed in this mode")
    return place_mt5_order(request=request, mt5_module=mt5_module)


def execute_supervised_mt5_close(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    sync_result: Mt5SyncResult,
    ticket: int | None,
    mt5_module,
) -> Mt5OrderResult | str:
    if not readiness_ok:
        raise RuntimeError("mt5 lifecycle readiness failed")
    if len(sync_result.positions) == 0:
        raise RuntimeError("no synchronized mt5 positions")
    if ticket is None and len(sync_result.positions) != 1:
        raise RuntimeError("ambiguous mt5 positions")

    target = next(
        (
            position
            for position in sync_result.positions
            if ticket is None or position.ticket == ticket
        ),
        None,
    )
    if target is None:
        raise RuntimeError("unknown mt5 ticket")
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("mt5 close is not allowed in this mode")
    return close_mt5_position(
        request=Mt5CloseRequest(
            symbol=target.symbol,
            venue_symbol=target.venue_symbol,
            ticket=target.ticket,
            volume=target.volume,
            direction=target.direction,
        ),
        mt5_module=mt5_module,
    )


def execute_supervised_mt5_modify(
    *,
    mode: LiveMode,
    readiness_ok: bool,
    reconcile_result: Mt5ReconcileResult,
    stop_loss: float | None,
    take_profit: float | None,
    mt5_module,
) -> Mt5OrderResult | str:
    if not readiness_ok:
        raise RuntimeError("mt5 refinement readiness failed")
    if not reconcile_result.actionable:
        raise RuntimeError("mt5 reconciliation is not actionable")

    target = next(
        position
        for position in reconcile_result.sync_result.positions
        if position.ticket == reconcile_result.target_ticket
    )
    if mode is LiveMode.DRY_RUN_LIVE:
        return "dry-run-only"
    if mode is not LiveMode.ARMED_LIVE:
        raise RuntimeError("mt5 modify is not allowed in this mode")
    return modify_mt5_position(
        request=Mt5ModifyRequest(
            symbol=target.symbol,
            venue_symbol=target.venue_symbol,
            ticket=target.ticket,
            stop_loss=stop_loss,
            take_profit=take_profit,
        ),
        mt5_module=mt5_module,
    )
