from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.config import LiveMode


@dataclass(frozen=True)
class LiveReadinessReport:
    mode: LiveMode
    ready: bool
    failures: tuple[str, ...]


def build_live_readiness_report(
    *,
    mode: LiveMode,
    symbol: str,
    app_id: str | None,
    token: str | None,
    armed: bool,
    supported_symbols: set[str],
) -> LiveReadinessReport:
    failures: list[str] = []

    if symbol not in supported_symbols:
        failures.append("unsupported_symbol")
    if mode in {LiveMode.DRY_RUN_LIVE, LiveMode.ARMED_LIVE} and not app_id:
        failures.append("missing_app_id")
    if mode is LiveMode.ARMED_LIVE and not token:
        failures.append("missing_api_token")
    if mode is LiveMode.ARMED_LIVE and not armed:
        failures.append("missing_armed_confirmation")

    return LiveReadinessReport(
        mode=mode,
        ready=not failures,
        failures=tuple(failures),
    )
