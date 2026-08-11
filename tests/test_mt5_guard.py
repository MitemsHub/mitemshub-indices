"""Tests for the cross-process MT5 single-flight guard."""

from __future__ import annotations

import multiprocessing
import os
import time
import uuid

import pytest

from synthetic_trader.execution.mt5_guard import (
    Mt5SingleFlightLock,
    mt5_single_flight,
)

IS_WINDOWS = os.name == "nt"


def _uniq() -> str:
    return f"SyntheticTraderMT5Test_{uuid.uuid4().hex[:8]}"


# ── Multiprocessing worker targets (top-level for Windows spawn) ───────
def _hold_for(lock_name: str, ready, hold_sec: float) -> None:
    """Acquire the lock, signal ready, hold, then release cleanly."""
    lock = Mt5SingleFlightLock(name=lock_name, timeout_sec=2.0)
    assert lock.acquire()
    ready.set()
    time.sleep(hold_sec)
    lock.release()


def _crash_while_holding(lock_name: str, ready) -> None:
    """Acquire the lock, signal ready, then exit WITHOUT releasing."""
    lock = Mt5SingleFlightLock(name=lock_name, timeout_sec=2.0)
    assert lock.acquire()
    ready.set()
    time.sleep(0.3)
    os._exit(0)  # simulate a crash mid-init


@pytest.mark.skipif(not IS_WINDOWS, reason="named-mutex semantics are Windows-only")
class TestCrossProcess:
    def test_second_process_is_excluded_while_first_holds(self) -> None:
        name = _uniq()
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        holder = ctx.Process(target=_hold_for, args=(name, ready, 4.0))
        holder.start()
        try:
            assert ready.wait(timeout=10)
            # While the child holds the mutex, a short-timeout acquire must fail.
            lock = Mt5SingleFlightLock(name=name, timeout_sec=0.5)
            assert lock.acquire() is False
        finally:
            holder.join(timeout=10)
        # After the child released, the parent can acquire.
        lock = Mt5SingleFlightLock(name=name, timeout_sec=2.0)
        assert lock.acquire() is True
        lock.release()

    def test_abandoned_lock_is_recovered_after_crash(self) -> None:
        name = _uniq()
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        crasher = ctx.Process(target=_crash_while_holding, args=(name, ready))
        crasher.start()
        try:
            assert ready.wait(timeout=10)
            time.sleep(0.5)  # let the child actually hold + die
            # WAIT_ABANDONED must be treated as acquired — no stale lock.
            lock = Mt5SingleFlightLock(name=name, timeout_sec=3.0)
            assert lock.acquire() is True
            lock.release()
        finally:
            crasher.join(timeout=10)


class TestLockSemantics:
    def test_acquire_release_lifecycle(self) -> None:
        lock = Mt5SingleFlightLock(name=_uniq(), timeout_sec=1.0)
        assert lock.acquire() is True
        lock.release()
        assert lock.acquire() is True
        lock.release()

    def test_timeout_when_held_by_another_thread(self) -> None:
        name = _uniq()
        holder = Mt5SingleFlightLock(name=name, timeout_sec=1.0)
        assert holder.acquire() is True
        try:
            contender = Mt5SingleFlightLock(name=name, timeout_sec=0.2)
            assert contender.acquire() is False  # times out, does not block forever
        finally:
            holder.release()

    def test_context_manager_raises_on_busy(self) -> None:
        name = _uniq()
        holder = Mt5SingleFlightLock(name=name, timeout_sec=1.0)
        assert holder.acquire() is True
        try:
            with pytest.raises(TimeoutError):
                with mt5_single_flight(name=name, timeout_sec=0.2):
                    pass  # never reached
        finally:
            holder.release()

    def test_release_is_safe_when_not_held(self) -> None:
        lock = Mt5SingleFlightLock(name=_uniq(), timeout_sec=1.0)
        lock.release()  # must not raise
        assert lock.acquire() is True
        lock.release()
        lock.release()  # double release must not raise
