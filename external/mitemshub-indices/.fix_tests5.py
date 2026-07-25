"""Fix test 2: use individual nthCalledWith checks instead of mock.calls.toEqual (Promise.all order varies)."""
import re

with open('tests/engine-bridge.test.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# The old block — just replace the mock.calls.toEqual with individual checks
old = r"""    // Call warmPreparedCalls a second time directly instead of relying
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
    ]);"""

new = r"""    // Call warmPreparedCalls a second time directly instead of relying
    // on timer advancement (which mixes real I/O with fake timers poorly).
    await reloadedBridge.warmPreparedCalls();
    expect(liveSnapshotSpy).toHaveBeenCalledTimes(8);

    // Verify each expected call happened (order may vary between runs
    // because warmPreparedCalls uses Promise.all internally).
    for (const symbol of ["R_75", "R_100"] as const) {
      for (const tradingMode of ["sniper", "active_trader"] as const) {
        expect(liveSnapshotSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            engineRoot: "c:\\engine-root",
            mode: "prepared",
            symbol,
            tradingMode,
            skipApi: true,
          }),
        );
      }
    }"""

assert old in content, 'Fix 2: block not found'
content = content.replace(old, new, 1)

with open('tests/engine-bridge.test.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: test 2 fixed with individual toHaveBeenCalledWith checks')
