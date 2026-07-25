"""Fix warmup cache tests — add __testResetWarmupCache call between cycles."""
import re

with open('tests/engine-bridge.test.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: clarify comment in 'triggers background warmup' test
old1 = r"""    expect(liveSnapshotSpy).not.toHaveBeenCalled();

    await vi.runAllTimersAsync();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);"""

new1 = r"""    expect(liveSnapshotSpy).not.toHaveBeenCalled();

    // Run the timer that ensurePreparedCallWarmup() scheduled.
    await vi.runAllTimersAsync();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);"""

assert old1 in content, 'Fix 1: block not found'
content = content.replace(old1, new1, 1)

# Fix 2: add __testResetWarmupCache() before advancing timers for second warmup cycle
old2 = r"""    await reloadedBridge.warmPreparedCalls();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);

    const refreshDelay = setTimeoutSpy.mock.calls.at(-1)?.[1];
    expect(typeof refreshDelay).toBe("number");
    expect(refreshDelay).toBe(45_000);

    await vi.advanceTimersByTimeAsync(refreshDelay as number);

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(8);"""

new2 = r"""    await reloadedBridge.warmPreparedCalls();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);

    const refreshDelay = setTimeoutSpy.mock.calls.at(-1)?.[1];
    expect(typeof refreshDelay).toBe("number");
    expect(refreshDelay).toBe(45_000);

    // Clear the CSV mtime cache so the second warmup cycle re-runs
    // rather than skipping because the CSV hasn't changed.
    reloadedBridge.__testResetWarmupCache();

    await vi.advanceTimersByTimeAsync(refreshDelay as number);

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(8);"""

assert old2 in content, 'Fix 2: block not found'
content = content.replace(old2, new2, 1)

with open('tests/engine-bridge.test.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: both fixes applied')
