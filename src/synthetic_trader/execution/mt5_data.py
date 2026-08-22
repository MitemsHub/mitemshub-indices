from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from synthetic_trader.domain import Tick
from synthetic_trader import __version__ as _engine_version
from synthetic_trader.execution.mt5_guard import Mt5SingleFlightLock


# ── Engine version ────────────────────────────────────────────────────

def get_engine_version() -> str:
    """Return the synthetic-trader Python package version."""
    return _engine_version


# ── MT5 last-error persistence ────────────────────────────────────────
# Written by Mt5TickClient on login/init failure so the TS-side
# connection-status endpoint can read why MT5 is disconnected.
_MT5_ERROR_PATH = Path("data/mt5_last_error.json")


def _store_mt5_error(error_msg: str) -> None:
    """Write the most recent MT5 error to a shared JSON file."""
    try:
        _MT5_ERROR_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MT5_ERROR_PATH.write_text(
            json.dumps({"error": error_msg, "timestamp": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass  # Best-effort; failure to write should not crash the snapshot.


def _clear_mt5_error() -> None:
    """Remove the error file after a successful connection."""
    try:
        if _MT5_ERROR_PATH.exists():
            _MT5_ERROR_PATH.unlink()
    except Exception:
        pass


def get_last_mt5_error() -> str | None:
    """Read the last persisted MT5 error, if any."""
    try:
        if _MT5_ERROR_PATH.exists():
            data = json.loads(_MT5_ERROR_PATH.read_text(encoding="utf-8"))
            return data.get("error") or None
    except Exception:
        pass
    return None


# ── MT5 timing persistence ───────────────────────────────────────────
# Written by Mt5TickClient on successful connection so the TS-side
# health dashboard can show init/login latency breakdown.
_MT5_TIMING_PATH = Path("data/mt5_timing.json")


def _store_mt5_timing(init_ms: float, login_ms: float) -> None:
    """Write the most recent MT5 connection timing to a shared file."""
    try:
        _MT5_TIMING_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MT5_TIMING_PATH.write_text(
            json.dumps({
                "init_ms": round(init_ms, 1),
                "login_ms": round(login_ms, 1),
                "total_ms": round(init_ms + login_ms, 1),
                "timestamp": time.time(),
            }),
            encoding="utf-8",
        )
    except Exception:
        pass


def get_mt5_timing() -> dict[str, Any] | None:
    """Read the last persisted MT5 timing data, if any."""
    try:
        if _MT5_TIMING_PATH.exists():
            return dict(json.loads(_MT5_TIMING_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return None


def get_health_metrics(symbol: str = "R_100") -> dict:
    """Return a snapshot of connection health metrics for the dashboard."""
    timing = get_mt5_timing()
    error = get_last_mt5_error()
    cfg = mt5_config_from_env()
    
    # Count CSV lines for tick velocity estimation
    csv_candidates = [
        Path(f"data/{symbol}_ticks.csv"),
        Path(f"data/{symbol.lower().replace('_', '')}_ticks.csv"),
    ]
    csv_size = 0
    csv_lines = 0
    for p in csv_candidates:
        if p.exists():
            csv_size = p.stat().st_size
            try:
                text = p.read_text(encoding="utf-8")
                csv_lines = sum(1 for line in text.splitlines() if line.strip() and not line.startswith("epoch"))
            except Exception:
                pass
            break
    
    return {
        "mt5_configured": is_mt5_configured(),
        "mt5_server": cfg.get("server") or None,
        "mt5_error": error,
        "mt5_timing": timing,
        "csv_size_bytes": csv_size,
        "csv_tick_count": csv_lines,
        "engine_version": get_engine_version(),
        "timestamp": time.time(),
    }


# ── Shared connection cache (per-process) ──────────────────────────────
# Since each snapshot runs in a separate Python subprocess, caching only
# persists within that subprocess lifetime. The main benefit is avoiding
# redundant directory/registry scanning when the terminal path is unknown.
_cached_terminal_path: str | None = None
_cached_terminal_path_attempted: bool = False
_cached_terminal_env: str = ""


def _mt5_available() -> bool:
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        return False
    return True


# Cache for resolved symbols — avoids repeated MT5 queries and log spam
# in the tight polling loop of the tick collector.
_SYMBOL_RESOLUTION_CACHE: dict[str, str] = {}


def clear_symbol_resolution_cache() -> None:
    """Clear the symbol resolution cache. Call on reconnect/MT5 shutdown."""
    _SYMBOL_RESOLUTION_CACHE.clear()


def _resolve_mt5_symbol(symbol: str, mt5_module=None) -> str:
    # Return cached resolution if available (avoids log spam in tight loops)
    if symbol in _SYMBOL_RESOLUTION_CACHE:
        return _SYMBOL_RESOLUTION_CACHE[symbol]

    configured = os.getenv("SYNTHETIC_MT5_SYMBOL_MAP")
    if configured:
        try:
            mapping = dict(item.split(":", 1) for item in configured.split(","))
            if symbol in mapping:
                _SYMBOL_RESOLUTION_CACHE[symbol] = mapping[symbol]
                return mapping[symbol]
        except Exception:
            pass

    vol_num = "75" if symbol == "R_75" else "100"
    candidates = [
        # Deriv' actual broker symbols (verified live on the
        # Deriv MT5 terminal) — try these first.
        f"SYN{vol_num}",
        f"Deriv Volatility {vol_num}",
        f"Volatility {vol_num} Index",
        f"Volatility {vol_num}",
        f"Vol {vol_num} Index",
        f"Vol {vol_num}",
        f"Volatility {vol_num} (1s)",
        f"R_{vol_num}",
        symbol,
    ]

    if mt5_module is not None:
        import MetaTrader5 as mt5
        for name in candidates:
            try:
                info = mt5.symbol_info(name)
                if info is not None:
                    _diag(f"resolved {symbol} -> {name}")
                    _SYMBOL_RESOLUTION_CACHE[symbol] = name
                    return name
                if mt5.symbol_select(name, True):
                    _diag(f"resolved {symbol} -> {name} (via symbol_select)")
                    _SYMBOL_RESOLUTION_CACHE[symbol] = name
                    return name
            except Exception:
                continue
        _diag(f"symbol {symbol} not found on broker, tried: {candidates}")

    _diag(f"using default symbol name: {candidates[0]} (no MT5 module to verify)")
    _SYMBOL_RESOLUTION_CACHE[symbol] = candidates[0]
    return candidates[0]


def mt5_config_from_env() -> dict[str, str | None]:
    return {
        "server": os.getenv("SYNTHETIC_MT5_SERVER", "").strip() or None,
        "login": os.getenv("SYNTHETIC_MT5_LOGIN", "").strip() or None,
        "password": os.getenv("SYNTHETIC_MT5_PASSWORD", "").strip() or None,
        "terminal_path": os.getenv("SYNTHETIC_MT5_TERMINAL_PATH", "").strip() or None,
    }


def is_mt5_configured() -> bool:
    cfg = mt5_config_from_env()
    return bool(cfg["server"] and cfg["login"] and cfg["password"])


def _diag(msg: str) -> None:
    print(f"[mt5_data] {msg}", file=sys.stderr, flush=True)


# ── Terminal path resolution helpers ──────────────────────────────────

def _extract_broker_keywords(server: str) -> list[str]:
    cleaned = server.lower().strip()
    if not cleaned:
        return []
    parts = cleaned.replace("-", " ").replace("_", " ").replace(".", " ").split()
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        word = "".join(c for c in part if c.isalpha())
        if len(word) >= 3 and word not in seen:
            seen.add(word)
            ordered.append(word)
    if len(ordered) > 1 and len(ordered[0]) > 4:
        ordered = ordered[:1] + ordered[-2:]
    return ordered


def _find_best_terminal(broker_keywords: list[str]) -> str | None:
    search_roots: list[Path] = []
    for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
        val = os.getenv(env_var)
        if val:
            p = Path(val)
            if p.exists():
                search_roots.append(p)

    candidates: list[tuple[int, str]] = []

    for root in search_roots:
        _diag(f"scanning {root}")
        try:
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                for candidate_name in ("terminal64.exe", "terminal.exe"):
                    exe_path = entry / candidate_name
                    if not exe_path.is_file():
                        for sub in entry.iterdir():
                            if not sub.is_dir():
                                continue
                            exe_path = sub / candidate_name
                            if exe_path.is_file():
                                break
                        else:
                            continue
                    parent_name = entry.name.lower()
                    score = sum(1 for kw in broker_keywords if kw in parent_name)
                    if score > 0:
                        _diag(f"candidate (score={score}): {exe_path}")
                        candidates.append((score, str(exe_path)))
        except PermissionError:
            continue

    candidates.sort(key=lambda x: -x[0])
    if candidates:
        _diag(f"best match (score={candidates[0][0]}): {candidates[0][1]}")
        return candidates[0][1]

    # Fallback: scan Windows registry for MetaQuotes terminal installations
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\MetaQuotes\Terminal\Installations") as key:
            index = 0
            reg_candidates: list[tuple[int, str]] = []
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, index)
                    subkey_lower = subkey_name.lower()
                    score = sum(1 for kw in broker_keywords if kw in subkey_lower)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        path_value, _ = winreg.QueryValueEx(subkey, "Path")
                        for name in ("terminal64.exe", "terminal.exe"):
                            candidate = Path(path_value) / name
                            if candidate.is_file():
                                _diag(f"registry (score={score}): {candidate}")
                                reg_candidates.append((score, str(candidate)))
                except OSError:
                    break
                index += 1
            reg_candidates.sort(key=lambda x: -x[0])
            if reg_candidates:
                _diag(f"best registry match: {reg_candidates[0][1]}")
                return reg_candidates[0][1]
    except Exception:
        pass

    return None


def _terminal_env_fingerprint() -> str:
    """Env values the resolution depends on — cache is only valid for the
    same fingerprint, so a changed SYNTHETIC_MT5_* env (e.g. between tests)
    invalidates the module-global cache."""
    return "|".join(
        [
            os.getenv("SYNTHETIC_MT5_TERMINAL_PATH", "").strip(),
            os.getenv("SYNTHETIC_MT5_SERVER", "").strip(),
        ]
    )


def _resolve_mt5_terminal_path() -> str | None:
    global _cached_terminal_path, _cached_terminal_path_attempted, _cached_terminal_env

    # Return cached result only when the resolving env is unchanged (the
    # cache must not leak a resolution from a previous env, e.g. a test that
    # resolved with no server and cached None).
    if (
        _cached_terminal_path_attempted
        and _cached_terminal_env == _terminal_env_fingerprint()
    ):
        return _cached_terminal_path
    fingerprint = _terminal_env_fingerprint()

    # 1. Use explicit env var if set — this is the fast path
    configured = os.getenv("SYNTHETIC_MT5_TERMINAL_PATH", "").strip()
    if configured:
        expanded = os.path.expandvars(os.path.expanduser(configured))
        candidate = Path(expanded)
        if candidate.is_dir():
            for name in ("terminal64.exe", "terminal.exe"):
                exe = candidate / name
                if exe.is_file():
                    _diag(f"using configured dir: {exe}")
                    _cached_terminal_env = fingerprint
                    _cached_terminal_path = str(exe)
                    _cached_terminal_path_attempted = True
                    return _cached_terminal_path
        _diag(f"using configured path: {candidate}")
        _cached_terminal_env = fingerprint
        _cached_terminal_path = str(candidate)
        _cached_terminal_path_attempted = True
        return _cached_terminal_path

    # 2. Heuristic: scan Program Files for terminal matching the broker name
    server = (os.getenv("SYNTHETIC_MT5_SERVER", "") or "").strip()
    broker_keywords = _extract_broker_keywords(server) if server else []
    _diag(f"looking for terminal matching server={server!r} keywords={broker_keywords}")

    result = _find_best_terminal(broker_keywords)
    if result:
        _cached_terminal_env = fingerprint
        _cached_terminal_path = result
        _cached_terminal_path_attempted = True
        return _cached_terminal_path

    _diag("no matching terminal found — set SYNTHETIC_MT5_TERMINAL_PATH in .env.local")
    _cached_terminal_env = fingerprint
    _cached_terminal_path = None
    _cached_terminal_path_attempted = True
    return None


# ── Tick pacing: separate per-connection timeout and retry budget ─────
# Retries happen fast (0.5s gaps) so we stay within the asyncio timeout.
_INIT_RETRY_SLEEP = 0.5
_INIT_RETRY_COUNT = 1          # was 3 — one retry is plenty for a local terminal
_LOGIN_RETRY_SLEEP = 0.5
_LOGIN_RETRY_COUNT = 1         # was 3
_SELECT_RETRY_SLEEP = 0.5
_SELECT_RETRY_COUNT = 1        # was 3

# IPC-timeout hardening: mt5.initialize() can return (-10005, 'IPC timeout')
# when the terminal is busy or a previous process left a half-open IPC
# channel (a timed-out initialize keeps running in the executor thread even
# after asyncio.wait_for gives up — the MetaTrader5 Python package allows
# one connection per process and a zombie initialize wedges the terminal for
# every later subprocess).  The fix: retry the whole portable(False→True)
# pass a few times, calling mt5.shutdown() before each retry so the
# half-open state is cleared, with a small backoff between full passes.
_INIT_FULL_RETRY_COUNT = 3     # full portable(False→True) passes
_INIT_FULL_RETRY_SLEEP = 1.0   # backoff between full passes (seconds)


async def _safe_mt5_shutdown(mt5, loop) -> None:
    """Best-effort mt5.shutdown from the executor; never raises.

    Clears any half-open IPC state left by a timed-out initialize so the
    next attempt starts from a clean slate.  Also the documented way to
    unstick a hung initialize in the same process.
    """
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, mt5.shutdown),
            timeout=3.0,
        )
    except Exception:
        pass


class Mt5TickClient:
    """Async MT5 tick client with fast retry and connection reuse.

    Each instance connects on enter and **does not disconnect on exit** —
    the Python subprocess itself cleans up on exit. This avoids the
    expensive ``shutdown()`` call and allows the MT5 API to keep a
    warm local connection for the subprocess duration.
    """

    def __init__(self, connect_timeout: float = 20.0) -> None:
        self._connect_timeout = connect_timeout
        self._mt5_module: Any | None = None

    async def __aenter__(self) -> "Mt5TickClient":
        if not _mt5_available():
            raise RuntimeError("MetaTrader5 Python package not installed")
        import MetaTrader5 as mt5

        self._mt5_module = mt5
        cfg = mt5_config_from_env()
        loop = asyncio.get_running_loop()

        # Resolve terminal path (cached after first call in this subprocess)
        terminal_path = _resolve_mt5_terminal_path()
        if terminal_path is None:
            raise RuntimeError(
                f"No MT5 terminal found for server {cfg['server']!r}. "
                "Set SYNTHETIC_MT5_TERMINAL_PATH=path/to/terminal64.exe in .env.local"
            )

        # Fast initialize with fallback:
        # 1. Try portable=False FIRST (connects to an already-running terminal).
        #    The terminal IS running on the user's machine — `portable=False` will
        #    connect to it via IPC without starting a new process.
        # 2. If that fails, try portable=True (starts a new terminal instance).
        # 3. Each attempt passes `timeout=8000` (8 seconds) to mt5.initialize().
        #    Without a timeout parameter, the C-level initialize() can hang
        #    indefinitely (known issue with MetaTrader5 Python package). With
        #    the timeout, it returns cleanly with error code `(-10005, 'IPC timeout')`
        #    when the existing terminal cannot be reached.
        # 4. IPC-timeout hardening: the whole pass is retried up to
        #    _INIT_FULL_RETRY_COUNT times with mt5.shutdown() + backoff between
        #    passes — a timed-out initialize keeps running in the executor
        #    thread, and shutdown is the only way to release that half-open IPC
        #    channel so the next subprocess doesn't inherit the timeout.
        # Cross-process single-flight guard: the scheduled collector, the
        # dashboard warmup cycle, and manual CLI runs are separate processes,
        # and two simultaneous mt5.initialize() calls race the terminal's
        # startup handshake (one gets (-10005, 'IPC timeout')).  Acquire the
        # shared named mutex for the init+login sequence ONLY, then release
        # so concurrent sessions (the terminal supports multiple IPC
        # clients) and long-lived collectors are never blocked afterwards.
        guard = Mt5SingleFlightLock(timeout_sec=self._connect_timeout)
        acquired = await loop.run_in_executor(None, guard.acquire)
        if not acquired:
            raise RuntimeError(
                "MT5 terminal busy: another process is initializing "
                "(single-flight guard timed out)"
            )
        try:
            await self._connect(mt5, loop, cfg, terminal_path)
        finally:
            guard.release()
        return self

    async def _connect(self, mt5, loop, cfg, terminal_path) -> None:
        """Initialize + login under the single-flight guard."""
        _diag(f"initializing: {terminal_path}")
        _t0 = time.perf_counter()
        initialized = False
        init_error = None
        for full_attempt in range(_INIT_FULL_RETRY_COUNT):
            if full_attempt > 0:
                # Clear any half-open IPC state left by the timed-out attempt.
                await _safe_mt5_shutdown(mt5, loop)
                await asyncio.sleep(_INIT_FULL_RETRY_SLEEP * full_attempt)
            for portable in (False, True):  # portable=False FIRST (connect to running terminal)
                if portable is False and not terminal_path:
                    _diag("skipping portable=False — no terminal path resolved")
                    continue
                try:
                    initialized = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda p=portable: mt5.initialize(path=terminal_path, portable=p, timeout=8000),
                        ),
                        timeout=10.0,  # Slightly longer than C-level timeout
                    )
                    if initialized:
                        _diag(f"initialized (portable={portable}, full_attempt={full_attempt})")
                        break
                except (asyncio.TimeoutError, Exception) as ex:
                    init_error = ex
                    _diag(f"initialize (portable={portable}) full_attempt {full_attempt}: {ex}")
                else:
                    if not initialized:
                        err = mt5.last_error()
                        init_error = err
                        _diag(f"initialize (portable={portable}) full_attempt {full_attempt}: returned False ({err})")
            if initialized:
                break
        _init_ms = (time.perf_counter() - _t0) * 1000
        if not initialized:
            err = mt5.last_error() if mt5.last_error() != (0,) else str(init_error or "unknown")
            _store_mt5_error(f"initialize failed: {err}")
            raise RuntimeError(f"MT5 initialize failed: {err} (path: {terminal_path})")

        # Verify connection
        term_info = await loop.run_in_executor(None, mt5.terminal_info)
        if term_info is not None:
            _diag(f"connected terminal: {getattr(term_info, 'path', '')}")
        else:
            _diag("terminal_info returned None — cannot verify terminal identity")

        # Fast login (1 retry, 0.5s gap).  When NO credentials are configured
        # but the running terminal already holds a session (account_info is
        # populated), REUSE that session instead of forcing a credentialed
        # re-login — the terminal is the source of truth for what it's
        # connected to (MT5-first; no credential dependency).  When
        # credentials ARE configured the behavior is byte-identical to before.
        existing = None
        _account_info = getattr(mt5, "account_info", None)
        if callable(_account_info):
            existing = await loop.run_in_executor(None, _account_info)
        reuse_session = (cfg["login"] is None and existing is not None)
        if reuse_session:
            login = int(getattr(existing, "login", 0))
            server = getattr(existing, "server", "") or ""
            _diag(f"reusing running terminal session ({login}@{server})")
        else:
            login = int(cfg["login"])
            server = cfg["server"] or ""
        password = cfg["password"] or ""
        _t1 = time.perf_counter()
        logged_in = reuse_session
        if not reuse_session:
            for attempt in range(1 + _LOGIN_RETRY_COUNT):
                logged_in = await loop.run_in_executor(
                    None,
                    lambda: mt5.login(login, password=password, server=server),
                )
                if logged_in:
                    break
                err = mt5.last_error()
                if attempt < _LOGIN_RETRY_COUNT:
                    _diag(f"login attempt {attempt + 1} failed: {err}, retrying in {_LOGIN_RETRY_SLEEP}s")
                    await asyncio.sleep(_LOGIN_RETRY_SLEEP)
        _login_ms = (time.perf_counter() - _t1) * 1000
        if not logged_in:
            err = mt5.last_error()
            _store_mt5_error(f"login failed: {err}")
            raise RuntimeError(f"MT5 login failed: {err}")

        # Clear any previous error on successful connection
        _clear_mt5_error()

        # Persist timing for the health dashboard
        _store_mt5_timing(_init_ms, _login_ms)

        _diag(f"connected as {login}@{server} (init={_init_ms:.0f}ms, login={_login_ms:.0f}ms)")

    async def __aexit__(self, *_: object) -> None:
        # Intentionally DO NOT call mt5.shutdown() here.
        # The Python subprocess will clean up the MT5 connection on exit,
        # saving ~0.5s of unnecessary shutdown + reconnect overhead.
        self._mt5_module = None

    async def ticks_history(
        self,
        symbol: str,
        count: int = 5000,
        end: str | int = "latest",
        start: int | None = None,
    ) -> list[Tick]:
        if self._mt5_module is None:
            raise RuntimeError("MT5 client not connected")

        mt5 = self._mt5_module
        mt5_symbol = _resolve_mt5_symbol(symbol, mt5)
        loop = asyncio.get_running_loop()

        # Symbol availability check (1 retry, 0.5s gap)
        symbol_info = await loop.run_in_executor(None, mt5.symbol_info, mt5_symbol)
        if symbol_info is None:
            selected = False
            for attempt in range(1 + _SELECT_RETRY_COUNT):
                selected = await loop.run_in_executor(None, mt5.symbol_select, mt5_symbol, True)
                if selected:
                    break
                if attempt < _SELECT_RETRY_COUNT:
                    _diag(f"symbol_select({mt5_symbol}) attempt {attempt + 1} failed, retrying in {_SELECT_RETRY_SLEEP}s")
                    await asyncio.sleep(_SELECT_RETRY_SLEEP)
            if not selected:
                raise RuntimeError(
                    f"MT5 symbol not available: {mt5_symbol}. "
                    "Set SYNTHETIC_MT5_SYMBOL_MAP in .env.local"
                )
            symbol_info = await loop.run_in_executor(None, mt5.symbol_info, mt5_symbol)
            if symbol_info is None:
                raise RuntimeError(f"MT5 symbol not available after select: {mt5_symbol}")

        if start is not None:
            date_from = datetime.fromtimestamp(start, tz=timezone.utc)
            ticks = await loop.run_in_executor(
                None,
                lambda: mt5.copy_ticks_range(
                    mt5_symbol, date_from, datetime.now(timezone.utc), mt5.COPY_TICKS_ALL
                ),
            )
            if ticks is None:
                ticks = ()
        elif end == "latest":
            ticks = await loop.run_in_executor(
                None,
                lambda: mt5.copy_ticks_from(mt5_symbol, datetime.now(timezone.utc), count, mt5.COPY_TICKS_ALL),
            )
            if ticks is None:
                ticks = ()
        elif isinstance(end, int):
            date_to = datetime.fromtimestamp(end, tz=timezone.utc)
            ticks = await loop.run_in_executor(
                None,
                lambda: mt5.copy_ticks_from(mt5_symbol, date_to, count, mt5.COPY_TICKS_ALL),
            )
            if ticks is None:
                ticks = ()
        else:
            ticks = await loop.run_in_executor(
                None,
                lambda: mt5.copy_ticks_from(mt5_symbol, datetime.now(timezone.utc), count, mt5.COPY_TICKS_ALL),
            )
            if ticks is None:
                ticks = ()

        # Root-cause hardening: a real MqlTick from MT5 ALWAYS carries
        # time_msc (millisecond precision).  A struct with time_msc == 0 is a
        # partially-initialized / garbage read — the fallback to the
        # whole-second ``time`` field silently turns it into a plausible
        # Deriv-style tick (whole-second epoch) and masks the corruption.
        # Reject those structs at the API boundary instead of letting garbage
        # flow downstream.
        clean: list[Tick] = []
        for tick in ticks:
            if tick["time_msc"] <= 0:
                continue
            price = float(tick["bid"]) if tick["bid"] > 0 else float(tick["ask"])
            if price <= 0:
                continue
            clean.append(
                Tick(
                    symbol=symbol,
                    epoch=float(tick["time_msc"]) / 1000.0,
                    price=price,
                )
            )
        return clean

    async def subscribe_ticks(
        self, symbol: str, timeout: float = 20.0,
    ) -> AsyncIterator[Tick]:
        if self._mt5_module is None:
            raise RuntimeError("MT5 client not connected")

        mt5 = self._mt5_module
        mt5_symbol = _resolve_mt5_symbol(symbol, mt5)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last_price: float | None = None

        # Poll interval was 0.5s — a hard ~2 ticks/sec cap that made the
        # snapshot's live phase take 5s for a handful of fresh ticks.  At
        # 0.05s the snapshot collects 20x more ticks per second (SYN75/SYN100
        # tick several times per second), so the same freshness budget
        # bridges to "now" in a fraction of the time.
        POLL_INTERVAL = 0.05
        while loop.time() < deadline:
            tick_info = await loop.run_in_executor(
                None, mt5.symbol_info_tick, mt5_symbol
            )
            if tick_info is not None:
                price = float(tick_info.bid) if tick_info.bid > 0 else float(tick_info.ask)
                if price > 0 and price != last_price:
                    last_price = price
                    # SAME clock as ticks_history/latest_tick: the terminal's
                    # time_msc (broker server time), NOT the local machine
                    # clock.  The research corpus and its "UTC 18-24h" hour
                    # edge are stamped in server time (Deriv server =
                    # local UTC+3h), and the warmup candles are built from
                    # time_msc ticks — the old time.time() stamp put live
                    # candles 3h BEHIND the warmup, so the journal epochs
                    # went non-monotonic and the entry gate fired 3h late
                    # vs the backtest.  Fall back to the local clock only
                    # when the terminal reports no timestamp.
                    epoch = (
                        float(tick_info.time_msc) / 1000.0
                        if tick_info.time_msc > 0
                        else time.time()
                    )
                    yield Tick(
                        symbol=symbol,
                        epoch=epoch,
                        price=price,
                    )
            await asyncio.sleep(POLL_INTERVAL)

    def mt5_symbol(self, symbol: str) -> str:
        return _resolve_mt5_symbol(symbol)

    async def latest_tick(self, symbol: str) -> Tick | None:
        """Return the most recent real tick for ``symbol``, or None.

        Uses the terminal's actual tick timestamp (``time_msc``) rather than
        the local poll time so downstream tick stores can deduplicate across
        process restarts and sessions.
        """
        if self._mt5_module is None:
            raise RuntimeError("MT5 client not connected")
        mt5 = self._mt5_module
        mt5_symbol = _resolve_mt5_symbol(symbol, mt5)
        loop = asyncio.get_running_loop()
        tick = await loop.run_in_executor(None, mt5.symbol_info_tick, mt5_symbol)
        if tick is None:
            return None
        price = float(tick.bid) if tick.bid > 0 else float(tick.ask)
        if price <= 0:
            return None
        epoch = float(tick.time_msc) / 1000.0 if tick.time_msc > 0 else time.time()
        return Tick(symbol=symbol, epoch=epoch, price=price)
