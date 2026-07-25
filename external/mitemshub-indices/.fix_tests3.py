"""Fix test 1: mock isMt5ProcessRunning so the warmup doesn't wait for real tasklist I/O."""
import re

with open('tests/engine-bridge.test.ts', 'r', encoding='utf-8') as f:
    content = f.read()

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

assert old1 in content, 'Fix 1: block not found'
content = content.replace(old1, new1, 1)

with open('tests/engine-bridge.test.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: test 1 fixed with isMt5ProcessRunning mock')
