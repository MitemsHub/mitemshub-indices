from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.config import Mt5Config
from synthetic_trader.domain import Direction


@dataclass(frozen=True)
class Mt5Credentials:
    server: str | None
    login: str | None
    password: str | None
    terminal_path: str | None
    symbol_map: dict[str, str]


@dataclass(frozen=True)
class Mt5OrderRequest:
    symbol: str
    venue_symbol: str
    volume: float
    order_type: str
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str | None = None


@dataclass(frozen=True)
class Mt5OrderResult:
    accepted: bool
    order_ticket: int | None
    deal_ticket: int | None
    retcode: int | None
    message: str
    venue_symbol: str


@dataclass(frozen=True)
class Mt5CloseRequest:
    symbol: str
    venue_symbol: str
    ticket: int
    volume: float
    direction: Direction


@dataclass(frozen=True)
class Mt5ModifyRequest:
    symbol: str
    venue_symbol: str
    ticket: int
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True)
class Mt5RuntimeStatus:
    ready: bool
    failures: tuple[str, ...]
    venue_symbol: str | None = None


@dataclass(frozen=True)
class Mt5PositionSnapshot:
    symbol: str
    venue_symbol: str
    ticket: int
    direction: Direction
    volume: float
    open_price: float
    current_price: float | None
    broker_time: int | None


@dataclass(frozen=True)
class Mt5SyncResult:
    ready: bool
    failures: tuple[str, ...]
    venue_symbol: str | None
    positions: tuple[Mt5PositionSnapshot, ...]


@dataclass(frozen=True)
class Mt5ReconcileResult:
    ready: bool
    actionable: bool
    failures: tuple[str, ...]
    target_ticket: int | None
    sync_result: Mt5SyncResult


def build_mt5_credentials(config: Mt5Config) -> Mt5Credentials:
    return Mt5Credentials(
        server=config.server,
        login=config.login,
        password=config.password,
        terminal_path=config.terminal_path,
        symbol_map=dict(config.symbol_map),
    )


def mt5_dependency_available() -> bool:
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        return False
    return True


def evaluate_mt5_runtime(
    *,
    config: Mt5Config,
    symbol: str,
    mt5_module=None,
) -> Mt5RuntimeStatus:
    failures: list[str] = []
    module = mt5_module
    if module is None:
        try:
            import MetaTrader5 as module
        except ImportError:
            return Mt5RuntimeStatus(
                ready=False,
                failures=("missing_mt5_runtime",),
                venue_symbol=None,
            )

    venue_symbol = config.resolve_symbol(symbol)
    if not venue_symbol:
        failures.append("missing_mt5_symbol_mapping")
        return Mt5RuntimeStatus(
            ready=False,
            failures=tuple(failures),
            venue_symbol=None,
        )

    if not module.initialize(path=config.terminal_path):
        failures.append("mt5_initialize_failed")
        return Mt5RuntimeStatus(
            ready=False,
            failures=tuple(failures),
            venue_symbol=venue_symbol,
        )

    try:
        if config.login is None or config.login == "":
            failures.append("mt5_login_empty")
        elif not module.login(int(config.login), password=config.password or "", server=config.server or ""):
            failures.append("mt5_login_failed")
        if module.symbol_info(venue_symbol) is None:
            failures.append("mt5_symbol_unavailable")
    finally:
        module.shutdown()

    return Mt5RuntimeStatus(
        ready=not failures,
        failures=tuple(failures),
        venue_symbol=venue_symbol,
    )


def synchronize_mt5_positions(
    *,
    config: Mt5Config,
    symbol: str,
    mt5_module,
) -> Mt5SyncResult:
    venue_symbol = config.resolve_symbol(symbol)
    if not venue_symbol:
        return Mt5SyncResult(
            ready=False,
            failures=("missing_mt5_symbol_mapping",),
            venue_symbol=None,
            positions=(),
        )

    if not hasattr(mt5_module, "terminal_info") or mt5_module.terminal_info() is None:
        try:
            if config.terminal_path:
                if not mt5_module.initialize(path=config.terminal_path):
                    return Mt5SyncResult(ready=False, failures=("mt5_init_failed",), venue_symbol=venue_symbol, positions=())
            elif not mt5_module.initialize():
                return Mt5SyncResult(ready=False, failures=("mt5_init_failed",), venue_symbol=venue_symbol, positions=())
        except Exception:
            return Mt5SyncResult(ready=False, failures=("mt5_init_failed",), venue_symbol=venue_symbol, positions=())

    positions = mt5_module.positions_get(symbol=venue_symbol) or []
    snapshots = tuple(
        Mt5PositionSnapshot(
            symbol=symbol,
            venue_symbol=venue_symbol,
            ticket=int(position.ticket),
            direction=(
                Direction.LONG
                if position.type == mt5_module.POSITION_TYPE_BUY
                else Direction.SHORT
            ),
            volume=float(position.volume),
            open_price=float(position.price_open),
            current_price=(
                float(position.price_current)
                if getattr(position, "price_current", None) is not None
                else None
            ),
            broker_time=(
                int(position.time)
                if getattr(position, "time", None) is not None
                else None
            ),
        )
        for position in positions
    )
    return Mt5SyncResult(
        ready=True,
        failures=(),
        venue_symbol=venue_symbol,
        positions=snapshots,
    )


def reconcile_mt5_positions(
    *,
    config: Mt5Config,
    symbol: str,
    ticket: int | None,
    mt5_module,
) -> Mt5ReconcileResult:
    sync_result = synchronize_mt5_positions(
        config=config,
        symbol=symbol,
        mt5_module=mt5_module,
    )
    failures = list(sync_result.failures)
    target_ticket: int | None = None

    if not sync_result.positions:
        failures.append("no_synchronized_mt5_positions")
    elif ticket is None:
        if len(sync_result.positions) == 1:
            target_ticket = sync_result.positions[0].ticket
        else:
            failures.append("ambiguous_mt5_positions")
    else:
        matches = [
            position for position in sync_result.positions if position.ticket == ticket
        ]
        if len(matches) != 1:
            failures.append("missing_mt5_target_ticket")
        else:
            target_ticket = matches[0].ticket

    return Mt5ReconcileResult(
        ready=sync_result.ready and not failures,
        actionable=not failures and target_ticket is not None,
        failures=tuple(failures),
        target_ticket=target_ticket,
        sync_result=sync_result,
    )


def place_mt5_order(
    *,
    request: Mt5OrderRequest,
    mt5_module,
) -> Mt5OrderResult:
    payload = {
        "action": mt5_module.TRADE_ACTION_DEAL,
        "symbol": request.venue_symbol,
        "volume": request.volume,
        "type": mt5_module.ORDER_TYPE_BUY
        if request.order_type == "BUY"
        else mt5_module.ORDER_TYPE_SELL,
        "sl": request.stop_loss,
        "tp": request.take_profit,
        "comment": request.comment or "synthetic-trader",
        "type_time": mt5_module.ORDER_TIME_GTC,
        "type_filling": mt5_module.ORDER_FILLING_FOK,
    }
    result = mt5_module.order_send(payload)
    accepted = getattr(result, "retcode", None) == 10009
    return Mt5OrderResult(
        accepted=accepted,
        order_ticket=getattr(result, "order", None),
        deal_ticket=getattr(result, "deal", None),
        retcode=getattr(result, "retcode", None),
        message=str(getattr(result, "comment", "")),
        venue_symbol=request.venue_symbol,
    )


def close_mt5_position(
    *,
    request: Mt5CloseRequest,
    mt5_module,
) -> Mt5OrderResult:
    close_type = (
        mt5_module.ORDER_TYPE_SELL
        if request.direction is Direction.LONG
        else mt5_module.ORDER_TYPE_BUY
    )
    payload = {
        "action": mt5_module.TRADE_ACTION_DEAL,
        "symbol": request.venue_symbol,
        "position": request.ticket,
        "volume": request.volume,
        "type": close_type,
        "comment": "synthetic-trader-mt5-close",
        "type_time": mt5_module.ORDER_TIME_GTC,
        "type_filling": mt5_module.ORDER_FILLING_FOK,
    }
    result = mt5_module.order_send(payload)
    accepted = getattr(result, "retcode", None) == 10009
    return Mt5OrderResult(
        accepted=accepted,
        order_ticket=getattr(result, "order", None),
        deal_ticket=getattr(result, "deal", None),
        retcode=getattr(result, "retcode", None),
        message=str(getattr(result, "comment", "")),
        venue_symbol=request.venue_symbol,
    )


def modify_mt5_position(
    *,
    request: Mt5ModifyRequest,
    mt5_module,
) -> Mt5OrderResult:
    payload = {
        "action": mt5_module.TRADE_ACTION_SLTP,
        "symbol": request.venue_symbol,
        "position": request.ticket,
        "sl": request.stop_loss,
        "tp": request.take_profit,
    }
    result = mt5_module.order_send(payload)
    accepted = getattr(result, "retcode", None) == 10009
    return Mt5OrderResult(
        accepted=accepted,
        order_ticket=getattr(result, "order", None),
        deal_ticket=getattr(result, "deal", None),
        retcode=getattr(result, "retcode", None),
        message=str(getattr(result, "comment", "")),
        venue_symbol=request.venue_symbol,
    )
