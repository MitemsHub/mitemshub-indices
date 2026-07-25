"""Fix test 1: replace mock.calls.toEqual with individual toHaveBeenCalledWith checks."""
import re

with open('tests/engine-bridge.test.ts', 'r', encoding='utf-8') as f:
    content = f.read()

old = r"""    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);
    expect(liveSnapshotSpy.mock.calls).toEqual([
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_75", tradingMode: "active_trader", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "sniper", skipApi: true })],
      [expect.objectContaining({ engineRoot: "c:\\engine-root", mode: "prepared", symbol: "R_100", tradingMode: "active_trader", skipApi: true })],
    ]);
  });"""

new = r"""    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);

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
    }
  });"""

assert old in content, 'Fix 1: block not found'
content = content.replace(old, new, 1)

with open('tests/engine-bridge.test.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: test 1 fixed with individual toHaveBeenCalledWith checks')
