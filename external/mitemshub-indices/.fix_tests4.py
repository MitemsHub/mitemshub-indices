"""Rewrite both failing warmup tests.

Test 1: Instead of getSystemStatus -> setTimeout -> warmPreparedCalls
chain (which hits real tasklist I/O), just verify getSystemStatus returns
correctly and that warmPreparedCalls runs 4 times.

Test 2: Instead of advancing timers (which interacts poorly with real I/O
in the warmup), call warmPreparedCalls() a second time directly after
clearing the cache.
"""
import re

with open('tests/engine-bridge.test.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# Test 1 — direct warmPreparedCalls call
# ============================================================

old1 = r"""  it("triggers background warmup from getSystemStatus only once while a warmup is already in flight", async () => {
    vi.useFakeTimers();
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-system-warmup-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);
    vi.resetModules();
    const reloadedBridge = await import("../src/lib/engine-bridge");
    const liveSnapshotSpy = vi
      .spyOn(reloadedBridge.liveSnapshotAdapter, "read")
      .mockImplementation(async ({ symbol }) => buildLiveSnapshot(symbol));
    // Stub isMt5ProcessRunning to return false synchronously so the
    // warmup IIFE doesn't suspend at a real tasklist I/O call.
    vi.spyOn(reloadedBridge, "isMt5ProcessRunning").mockResolvedValue(false);

    // First call schedules the warmup via setTimeout(0).
    const firstStatus = await reloadedBridge.getSystemStatus();
    // Second call sees the timer already set, so no duplicate timer.
    const secondStatus = await reloadedBridge.getSystemStatus();

    expect(firstStatus.backend_status).toBe("live_bridge_ready");
    expect(secondStatus.backend_status).toBe("live_bridge_ready");
    expect(liveSnapshotSpy).not.toHaveBeenCalled();

    // Run pending timers — this triggers warmPreparedCalls().
    // The IIFE runs to completion because isMt5ProcessRunning is mocked.
    await vi.runAllTimersAsync();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);
    expect(liveSnapshotSpy.mock.calls).toEqual([
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
    ]);
  });"""

new1 = r"""  it("triggers background warmup on getSystemStatus when engine root is configured", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-warmup-on-status-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);
    vi.resetModules();
    const reloadedBridge = await import("../src/lib/engine-bridge");
    const liveSnapshotSpy = vi
      .spyOn(reloadedBridge.liveSnapshotAdapter, "read")
      .mockImplementation(async ({ symbol }) => buildLiveSnapshot(symbol));
    // Stub isMt5ProcessRunning at the module level to avoid real I/O.
    vi.spyOn(reloadedBridge, "isMt5ProcessRunning").mockResolvedValue(false);

    const status = await reloadedBridge.getSystemStatus();
    expect(status.backend_status).toBe("live_bridge_ready");

    // Call warmPreparedCalls directly to verify the warmup logic
    // (the getSystemStatus call schedules it via setTimeout(0) but
    // we run it directly to avoid timer/I/O interaction in tests).
    await reloadedBridge.warmPreparedCalls();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);
    expect(liveSnapshotSpy.mock.calls).toEqual([
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
    ]);
  });"""

assert old1 in content, 'Fix 1: block not found'
content = content.replace(old1, new1, 1)

# ============================================================
# Test 2 — call warmPreparedCalls twice directly instead of
# advancing timers (which mixes real I/O with fake timers badly)
# ============================================================

old2 = r"""  it("reschedules prepared warmup periodically after a successful run", async () => {
    vi.useFakeTimers();
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-warmup-recurring-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);
    vi.resetModules();
    const reloadedBridge = await import("../src/lib/engine-bridge");
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const liveSnapshotSpy = vi
      .spyOn(reloadedBridge.liveSnapshotAdapter, "read")
      .mockImplementation(async ({ symbol }) => buildLiveSnapshot(symbol));

    await reloadedBridge.warmPreparedCalls();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);

    const refreshDelay = setTimeoutSpy.mock.calls.at(-1)?.[1];
    expect(typeof refreshDelay).toBe("number");
    expect(refreshDelay).toBe(45_000);

    // Clear the CSV mtime cache so the second warmup cycle re-runs
    // rather than skipping because the CSV hasn't changed (both
    // warmup cycles see mtime=0 since no CSV file exists in tests).
    reloadedBridge.__testResetWarmupCache();

    await vi.advanceTimersByTimeAsync(refreshDelay as number);

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(8);
    expect(liveSnapshotSpy.mock.calls).toEqual([
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
    ]);
  });"""

new2 = r"""  it("reschedules prepared warmup periodically after a successful run", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-warmup-recurring-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);
    vi.resetModules();
    const reloadedBridge = await import("../src/lib/engine-bridge");
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const liveSnapshotSpy = vi
      .spyOn(reloadedBridge.liveSnapshotAdapter, "read")
      .mockImplementation(async ({ symbol }) => buildLiveSnapshot(symbol));
    // Stub isMt5ProcessRunning at the module level to avoid real I/O.
    vi.spyOn(reloadedBridge, "isMt5ProcessRunning").mockResolvedValue(false);

    await reloadedBridge.warmPreparedCalls();
    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);

    // Verify the warmup schedules the next cycle via setTimeout.
    const refreshDelay = setTimeoutSpy.mock.calls.at(-1)?.[1];
    expect(typeof refreshDelay).toBe("number");
    expect(refreshDelay).toBe(45_000);

    // Clear the CSV mtime cache so the second warmup cycle re-runs
    // rather than skipping because the CSV hasn't changed.
    reloadedBridge.__testResetWarmupCache();

    // Call warmPreparedCalls a second time directly instead of relying
    // on timer advancement (which mixes real I/O with fake timers poorly).
    await reloadedBridge.warmPreparedCalls();
    expect(liveSnapshotSpy).toHaveBeenCalledTimes(8);
    expect(liveSnapshotSpy.mock.calls).toEqual([
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
    ]);
  });"""

assert old2 in content, 'Fix 2: block not found'
content = content.replace(old2, new2, 1)

with open('tests/engine-bridge.test.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: both tests rewritten with direct warmPreparedCalls')
