"""Cross-process single-flight guard for MT5 terminal initialization.

The Blueberry MT5 terminal accepts IPC clients, but two processes calling
``mt5.initialize()`` at the SAME instant race the terminal's startup
handshake — one of them gets ``(-10005, 'IPC timeout')`` (see §41).  The
scheduled collector, the dashboard warmup cycle, and manual CLI runs are all
separate processes, so a plain ``threading.Lock`` cannot serialize them.

This module provides a **Windows named mutex** (ctypes ``CreateMutexW`` /
``WaitForSingleObject`` / ``ReleaseMutex``):

- **Cross-process** — every process contends on the same kernel object, so
  the collector and the dashboard can never initialize at the same instant.
- **Abandoned-safe** — if the holder crashes mid-init, ``WaitForSingleObject``
  returns ``WAIT_ABANDONED`` and the next process takes over; no stale lock
  file to clean up (the kernel object dies with its last handle).
- **Timeout** — a process that cannot acquire within ``timeout_sec`` fails
  fast with a clear error instead of wedging its own IPC attempt.
- **Thread-consistent ownership** — kernel mutex ownership is per-THREAD and
  ``ReleaseMutex`` must be called by the owning thread.  Every lock owns a
  dedicated single worker thread and runs *both* acquire and release on it,
  so callers (event-loop threads, executor threads, the TS bridge's sync
  snippets) can acquire and release from any thread without tripping
  ``ERROR_NOT_OWNER``.

Scope is deliberately the **init + login sequence only**: once a connection
is up, the lock is released so concurrent sessions (the terminal supports
multiple IPC clients) and long-lived collectors never block each other.  The
§41 shutdown-before-retry hardening remains the backstop for a half-open
channel.

Non-Windows platforms degrade to a no-op (the project is Windows-only, but
this keeps tests portable).
"""

from __future__ import annotations

import ctypes
import os
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

# Session-namespace named mutex (no "Global\\" prefix — that requires the
# SeCreateGlobalPrivilege and is unnecessary: the collector task and the
# dashboard run in the same interactive session).
DEFAULT_MUTEX_NAME = "SyntheticTraderMT5Init"
# How long a waiter is willing to wait for the current holder to finish
# initializing.  A normal init+login completes in 1-8s; the hardened retry
# path can take longer, so 30s is generous without hanging the dashboard.
DEFAULT_TIMEOUT_SEC = 30.0

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102


def _kernel32():
    if os.name != "nt":
        return None
    return ctypes.WinDLL("kernel32", use_last_error=True)


class Mt5SingleFlightLock:
    """One-at-a-time cross-process lock around MT5 initialize/login."""

    def __init__(
        self,
        name: str = DEFAULT_MUTEX_NAME,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._name = name
        self._timeout_sec = timeout_sec
        self._handle = None
        self._acquired = False
        # Dedicated single thread: kernel mutex ownership is per-thread, and
        # ReleaseMutex must run on the owning thread.  Routing both acquire
        # and release through this one thread keeps ownership consistent no
        # matter which caller thread invokes them.
        self._owner = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mt5-single-flight"
        )

    def _acquire_sync(self) -> bool:
        k32 = _kernel32()
        if k32 is None:
            self._acquired = True  # non-Windows no-op
            return True
        k32.CreateMutexW.restype = wintypes.HANDLE
        handle = k32.CreateMutexW(None, False, self._name)
        if not handle:
            return False
        wait_ms = max(0, int(self._timeout_sec * 1000))
        result = k32.WaitForSingleObject(handle, wait_ms)
        if result in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            self._handle = handle
            self._acquired = True
            return True
        # Timeout or error: close the handle and report failure so the caller
        # can fail fast instead of racing the terminal's init handshake.
        k32.CloseHandle(handle)
        return False

    def _release_sync(self) -> None:
        k32 = _kernel32()
        if k32 is not None and self._handle:
            if self._acquired:
                k32.ReleaseMutex(self._handle)
            k32.CloseHandle(self._handle)
        self._handle = None
        self._acquired = False

    def acquire(self) -> bool:
        """Block (up to ``timeout_sec``) until the MT5 init slot is free.

        Returns True when the lock is held (including WAIT_ABANDONED — the
        previous holder crashed mid-init, so the slot is ours), False on
        timeout or error.  Non-Windows always returns True (no-op).
        """
        return self._owner.submit(self._acquire_sync).result()

    def release(self) -> None:
        """Release the mutex (safe when not held)."""
        self._owner.submit(self._release_sync).result()

    def __enter__(self) -> "Mt5SingleFlightLock":
        if not self.acquire():
            raise TimeoutError(
                f"MT5 terminal busy: another process is initializing "
                f"(single-flight '{self._name}' not free within {self._timeout_sec:.0f}s)"
            )
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def mt5_single_flight(
    name: str = DEFAULT_MUTEX_NAME,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> Mt5SingleFlightLock:
    """Context manager: ``with mt5_single_flight(): ...`` around init/login."""
    return Mt5SingleFlightLock(name=name, timeout_sec=timeout_sec)
