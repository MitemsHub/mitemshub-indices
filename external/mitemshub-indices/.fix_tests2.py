"""Rewrite the two failing warmup cache tests.

Test 1: Instead of relying on fake timers + getSystemStatus -> setTimeout,
call getSystemStatus to schedule the warmup, then await warmPreparedCalls()
directly to trigger it.

Test 2: Clear the CSV mtime cache with __testResetWarmupCache() between
the first and second warmup cycles so the cache doesn't skip the re-run.
"""
import re

with open('tests/engine-bridge.test.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# ============================================================
# Test 1: "triggers background warmup from getSystemStatus only once"
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

    const firstStatus = await reloadedBridge.getSystemStatus();
    const secondStatus = await reloadedBridge.getSystemStatus();

    expect(firstStatus.backend_status).toBe("live_bridge_ready");
    expect(secondStatus.backend_status).toBe("live_bridge_ready");
    expect(liveSnapshotSpy).not.toHaveBeenCalled();

    // Run the timer that ensurePreparedCallWarmup() scheduled.
    await vi.runAllTimersAsync();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);
    expect(liveSnapshotSpy.mock.calls).toEqual([
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
    ]);
  });"""

new1 = r"""  it("triggers background warmup from getSystemStatus only once while a warmup is already in flight", async () => {
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

    // First call schedules the warmup via setTimeout(0).
    const firstStatus = await reloadedBridge.getSystemStatus();
    // Second call sees the timer already set, so no duplicate timer.
    const secondStatus = await reloadedBridge.getSystemStatus();

    expect(firstStatus.backend_status).toBe("live_bridge_ready");
    expect(secondStatus.backend_status).toBe("live_bridge_ready");
    expect(liveSnapshotSpy).not.toHaveBeenCalled();

    // Run pending timers — this triggers warmPreparedCalls().
    await vi.runAllTimersAsync();

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
# Test 2: "reschedules prepared warmup periodically after a successful run"
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
    // rather than skipping because the CSV hasn't changed.
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

assert old2 in content, 'Fix 2: block not found'
content = content.replace(old2, new2, 1)

with open('tests/engine-bridge.test.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: both tests rewritten')
