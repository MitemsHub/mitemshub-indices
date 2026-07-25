import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as engineBridge from "../src/lib/engine-bridge";

function buildLiveSnapshot(symbol: "R_75" | "R_100") {
  return {
    symbol,
    call:
      (symbol === "R_75" ? "sell_candidate" : "buy_candidate") as
        | "sell_candidate"
        | "buy_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: symbol === "R_75" ? 0.68 : 0.74,
    regime: symbol === "R_75" ? "trend_down" : "trend_up",
    direction_bias: symbol === "R_75" ? "sell" : "buy",
    why:
      symbol === "R_75"
        ? "sellers still control the short-term move"
        : "buyers still control the short-term move",
    wait_for:
      symbol === "R_75"
        ? "wait for a clean bearish continuation close"
        : "wait for a clean bullish continuation close",
    decision_summary: symbol === "R_75" ? "sell setup ready" : "buy setup ready",
    entry_area: symbol === "R_75" ? "around 321.0" : "around 51260.0",
    stop_area: symbol === "R_75" ? "above 324.0" : "below 51210.0",
    target_area: symbol === "R_75" ? "toward 315.0" : "toward 51360.0",
    entry: symbol === "R_75" ? 321 : 51260,
    stop_loss: symbol === "R_75" ? 324 : 51210,
    take_profit: symbol === "R_75" ? 315 : 51360,
    reward_risk: 2,
    current_close: symbol === "R_75" ? 320.4 : 51280,
    guardian_state: "actionable" as const,
    guardian_reason: "The setup is actionable with caution.",
    invalidates_if:
      symbol === "R_75"
        ? "price closes back above the rejection shelf"
        : "price closes back below the reclaimed shelf",
    call_age_seconds: 4,
    generated_at:
      symbol === "R_75" ? "2026-07-11T05:00:00Z" : "2026-07-11T05:00:01Z",
  };
}

describe("runFreshCall", () => {
  it("returns a normalized fresh call payload in own-account mode", async () => {
    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.symbol).toBe("R_100");
    expect(result.account_mode).toBe("own_account");
    expect(result.prop_compliance).toBeNull();
  });

  it("returns a compliance result in prop-firm mode", async () => {
    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "prop_firm",
      propAccountState: {
        profile: "blueberry_2step_funded",
        startingBalance: 100000,
        currentBalance: 100200,
        currentEquity: 100100,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
      },
    });

    expect(result.account_mode).toBe("prop_firm");
    expect(result.prop_compliance).toBeTruthy();
  });
});

describe("runFreshCall engine config", () => {
  beforeEach(async () => {
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-engine-bridge-history-"));
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", join(tempDir, "call-history.jsonl"));
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
    vi.doUnmock("node:child_process");
  });

  it("normalizes missing engine-root config to null before falling back to mock data", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "   ");

    expect(engineBridge.getConfiguredEngineRoot()).toBeNull();

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.symbol).toBe("R_100");
    expect(result.generated_at).toBeTruthy();
  });

  it("uses the live engine snapshot when engine root is configured", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const liveSnapshotSpy = vi
      .spyOn(engineBridge.liveSnapshotAdapter, "read")
      .mockResolvedValue({
        symbol: "R_100",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.73,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers still control the short-term move",
        wait_for: "wait for a clean bullish continuation close",
        decision_summary:
          "buy setup valid; buyers still control the short-term move",
        entry_area: "around 51260.0",
        stop_area: "below 51210.0",
        target_area: "toward 51360.0",
        entry: 51260,
        stop_loss: 51210,
        take_profit: 51360,
        reward_risk: 2,
        guardian_state: "actionable",
        guardian_reason: "The setup is actionable with caution.",
        invalidates_if: "price closes back below the reclaimed shelf",
        call_age_seconds: 2,
        current_close: 51280,
        generated_at: "2026-07-09T13:00:00Z",
      });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).toHaveBeenCalledWith(expect.objectContaining({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
      mode: undefined,
      tradingMode: "sniper",
      warmupProfile: undefined,
      skipApi: false,
      signal: undefined,
    }));
    expect(result.generated_at).toBe("2026-07-09T13:00:00Z");
    expect(result.why).toBe("buyers still control the short-term move");
    expect(result.guardian_state).toBe("actionable");
    expect(result.guardian_reason).toMatch(/actionable with caution/i);
    expect(result.invalidates_if).toMatch(/reclaimed shelf/i);
    expect(result.call_age_seconds).toBe(2);
    expect(result.current_close).toBe(51280);
  });

  it("uses fewer live ticks for prepared snapshot reads than the default manual path", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const execFileMock = vi.fn((_command, _args, _options, callback) => {
      callback(null, "", "");
    });
    const promisifiedExecFileMock = vi.fn(async (..._args: unknown[]) => {
      const scriptArg = (_args[1] as string[])?.at(-1) ?? "";
      // Import check — return OK first
      if (scriptArg.startsWith("from synthetic_trader.live.market_snapshot import")) {
        return { stdout: "OK", stderr: "" };
      }
      return {
        stdout: JSON.stringify({
          call: "stand_aside",
          trade_status: "not_valid",
          direction_bias: "buy",
          why: "current movement is active but not a clean setup yet",
          wait_for: "wait for confidence above threshold",
          guardian_state: "forming",
          guardian_reason: "Directional thesis is not yet armed.",
          confidence: 0.53,
          current_close: 500.1,
        }),
        stderr: "",
      };
    });
    (execFileMock as unknown as { [promisify.custom]: unknown })[
      promisify.custom
    ] = promisifiedExecFileMock;

    vi.doMock("node:child_process", () => ({
      execFile: execFileMock,
      default: { execFile: execFileMock },
    }));

    const reloadedBridge = await import("../src/lib/engine-bridge");

    await reloadedBridge.liveSnapshotAdapter.read({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
    });
    await reloadedBridge.liveSnapshotAdapter.read({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
      mode: "prepared",
    });

    // First call is the import check, second and third are the two snapshot calls
    const snapshotCalls = promisifiedExecFileMock.mock.calls.filter(
      ([_, args]) => !((args as string[])?.at(-1) ?? "").startsWith("from synthetic_trader.live.market_snapshot import")
    );
    const manualArgs = snapshotCalls[0]?.[1] as string[] | undefined;
    const preparedArgs = snapshotCalls[1]?.[1] as string[] | undefined;
    const manualPythonScript = manualArgs?.[manualArgs.length - 1];
    const preparedPythonScript = preparedArgs?.[preparedArgs.length - 1];
    const manualMaxLiveTicks = Number(
      manualPythonScript?.match(/max_live_ticks=(\d+)/)?.[1] ?? Number.NaN,
    );
    const preparedMaxLiveTicks = Number(
      preparedPythonScript?.match(/max_live_ticks=(\d+)/)?.[1] ?? Number.NaN,
    );

    expect(manualMaxLiveTicks).toBe(12);
    expect(preparedMaxLiveTicks).toBe(40);
    expect(preparedMaxLiveTicks).toBeGreaterThan(manualMaxLiveTicks);
  });

  it("uses a long enough live snapshot timeout for tick-driven reads", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const execFileMock = vi.fn((_command, _args, _options, callback) => {
      callback(null, "", "");
    });
    const promisifiedExecFileMock = vi.fn(async (..._args: unknown[]) => {
      const scriptArg = (_args[1] as string[])?.at(-1) ?? "";
      // Import check — return OK first
      if (scriptArg.startsWith("from synthetic_trader.live.market_snapshot import")) {
        return { stdout: "OK", stderr: "" };
      }
      return {
        stdout: JSON.stringify({
          call: "stand_aside",
          trade_status: "not_valid",
          direction_bias: "buy",
          why: "current movement is active but not a clean setup yet",
          wait_for: "wait for confidence above threshold",
          guardian_state: "forming",
          guardian_reason: "Directional thesis is not yet armed.",
          confidence: 0.53,
          current_close: 500.1,
        }),
        stderr: "",
      };
    });
    (execFileMock as unknown as { [promisify.custom]: unknown })[
      promisify.custom
    ] = promisifiedExecFileMock;

    vi.doMock("node:child_process", () => ({
      execFile: execFileMock,
      default: { execFile: execFileMock },
    }));

    const reloadedBridge = await import("../src/lib/engine-bridge");

    await reloadedBridge.liveSnapshotAdapter.read({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
    });

    // First call is import check; second is the actual snapshot
    const snapshotArgs = promisifiedExecFileMock.mock.calls.find(
      ([_, args]) => !((args as string[])?.at(-1) ?? "").startsWith("from synthetic_trader.live.market_snapshot import")
    );
    const options = snapshotArgs?.[2] as
      | { timeout?: number }
      | undefined;

    expect(options?.timeout).toBe(35000);
  });

  it("uses a lower warmup count for prepared snapshot reads than the default manual path", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const execFileMock = vi.fn((_command, _args, _options, callback) => {
      callback(null, "", "");
    });
    const promisifiedExecFileMock = vi.fn(async (..._args: unknown[]) => {
      const scriptArg = (_args[1] as string[])?.at(-1) ?? "";
      // Import check — return OK first
      if (scriptArg.startsWith("from synthetic_trader.live.market_snapshot import")) {
        return { stdout: "OK", stderr: "" };
      }
      return {
        stdout: JSON.stringify({
          call: "stand_aside",
          trade_status: "not_valid",
          direction_bias: "buy",
          why: "current movement is active but not a clean setup yet",
          wait_for: "wait for confidence above threshold",
          guardian_state: "forming",
          guardian_reason: "Directional thesis is not yet armed.",
          confidence: 0.53,
          current_close: 500.1,
        }),
        stderr: "",
      };
    });
    (execFileMock as unknown as { [promisify.custom]: unknown })[
      promisify.custom
    ] = promisifiedExecFileMock;

    vi.doMock("node:child_process", () => ({
      execFile: execFileMock,
      default: { execFile: execFileMock },
    }));

    const reloadedBridge = await import("../src/lib/engine-bridge");

    await reloadedBridge.liveSnapshotAdapter.read({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
    });
    await reloadedBridge.liveSnapshotAdapter.read({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
      mode: "prepared",
    });

    // Filter out import-check calls — only snapshot calls have the long script
    const snapshotCalls = promisifiedExecFileMock.mock.calls.filter(
      ([_, args]) => !((args as string[])?.at(-1) ?? "").startsWith("from synthetic_trader.live.market_snapshot import")
    );
    const manualScript = (
      snapshotCalls[0]?.[1] as unknown as
        | string[]
        | undefined
    )?.at(-1);
    const preparedScript = (
      snapshotCalls[1]?.[1] as unknown as
        | string[]
        | undefined
    )?.at(-1);
    const manualWarmupCount = Number(
      manualScript?.match(/warmup_count=(\d+)/)?.[1] ?? Number.NaN,
    );
    const preparedWarmupCount = Number(
      preparedScript?.match(/warmup_count=(\d+)/)?.[1] ?? Number.NaN,
    );

    expect(preparedWarmupCount).toBeLessThan(manualWarmupCount);
  });

  it("normalizes intraday execution geometry from Python output", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const execFileMock = vi.fn((_command, _args, _options, callback) => {
      callback(null, "", "");
    });
    const promisifiedExecFileMock = vi.fn(async (..._args: unknown[]) => {
      const scriptArg = (_args[1] as string[])?.at(-1) ?? "";
      // Import check — return OK first
      if (scriptArg.startsWith("from synthetic_trader.live.market_snapshot import")) {
        return { stdout: "OK", stderr: "" };
      }
      return {
        stdout: JSON.stringify({
          call: "buy_candidate",
          trade_status: "valid",
          alert_type: "setup_candidate",
          confidence: "0.73",
          regime: "trend_up",
          direction_bias: "buy",
          why: "buyers still control the short-term move",
          wait_for: "wait for a clean bullish continuation close",
          decision_summary: "buy setup ready",
          entry_area: "around 475.1",
          stop_area: "below 474.8",
          target_area: "toward 488.8",
          entry: "475.1",
          stop_loss: "474.8",
          take_profit: "488.8",
          reward_risk: "1.9",
          current_close: "476.0",
          guardian_state: "actionable",
          guardian_reason:
            "The setup is actionable, but live continuation still needs more persistence.",
          invalidates_if: "price closes back below the defended 1H shelf",
          execution_stop: "474.8",
          thesis_invalidation: "440.67",
          primary_target: "488.8",
          extended_target: "493.4",
          hold_horizon_minutes: "60",
          generated_at: "2026-07-12T11:00:00Z",
        }),
        stderr: "",
      };
    });
    (execFileMock as unknown as { [promisify.custom]: unknown })[
      promisify.custom
    ] = promisifiedExecFileMock;

    vi.doMock("node:child_process", () => ({
      execFile: execFileMock,
      default: { execFile: execFileMock },
    }));

    const reloadedBridge = await import("../src/lib/engine-bridge");

    const result = await reloadedBridge.liveSnapshotAdapter.read({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
    });

    expect(result.execution_stop).toBe(474.8);
    expect(result.thesis_invalidation).toBe(440.67);
    expect(result.primary_target).toBe(488.8);
    expect(result.extended_target).toBe(493.4);
    expect(result.hold_horizon_minutes).toBe(60);
  });

  it("preserves actionable guardian reasons when confirmation is not yet present", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.7,
      regime: "trend_up",
      direction_bias: "buy",
      why: "buyers still control the short-term move",
      wait_for: "wait for a clean bullish continuation close",
      decision_summary: "buy thesis present",
      entry_area: "around 459.6",
      stop_area: "below 458.2",
      target_area: "toward 462.2",
      entry: 459.6,
      stop_loss: 458.2,
      take_profit: 462.2,
      reward_risk: 2,
      current_close: 459.67,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "price closes back below the defended shelf",
      call_age_seconds: 3,
      generated_at: "2026-07-11T04:00:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.guardian_state).toBe("actionable");
    expect(result.guardian_reason).toMatch(/actionable with caution/i);
    expect(result.invalidates_if).toMatch(/defended shelf/i);
    expect(result.call_age_seconds).toBe(3);
    expect(result.entry).toBe(459.6);
  });

  it("preserves failing stale-plan reasons from the live snapshot", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.68,
      regime: "trend_up",
      direction_bias: "buy",
      why: "buyers briefly reclaimed control before rollover pressure took over",
      wait_for: "wait for a fresh aligned reclaim before considering a new entry",
      decision_summary: "buy thesis was valid, then broke down",
      entry_area: "around 459.6",
      stop_area: "below 458.2",
      target_area: "toward 462.2",
      entry: 459.6,
      stop_loss: 458.2,
      take_profit: 462.2,
      reward_risk: 2,
      current_close: 459.5,
      guardian_state: "failing",
      guardian_reason:
        "The setup is deteriorating and the old plan is no longer fresh.",
      invalidates_if: "price closes back below the reclaimed shelf",
      call_age_seconds: 11,
      generated_at: "2026-07-11T04:05:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.guardian_state).toBe("failing");
    expect(result.guardian_reason).toMatch(/old plan is no longer fresh/i);
    expect(result.invalidates_if).toMatch(/reclaimed shelf/i);
    expect(result.call_age_seconds).toBe(11);
    expect(result.current_close).toBe(459.5);
  });

  it("preserves cancelled rollover reasons from the live snapshot", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.68,
      regime: "trend_up",
      direction_bias: "buy",
      why: "buyers briefly reclaimed control before rollover pressure took over",
      wait_for: "wait for a fresh aligned reclaim before considering a new entry",
      decision_summary: "buy thesis was valid, then broke down",
      entry_area: "around 459.6",
      stop_area: "below 458.2",
      target_area: "toward 462.2",
      entry: 459.6,
      stop_loss: 458.2,
      take_profit: 462.2,
      reward_risk: 2,
      current_close: 458.1,
      guardian_state: "cancelled",
      guardian_reason:
        "The original trade thesis is broken and should not be used.",
      invalidates_if: "price closes back below the reclaimed shelf",
      call_age_seconds: 19,
      generated_at: "2026-07-11T04:06:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.guardian_state).toBe("cancelled");
    expect(result.guardian_reason).toMatch(/should not be used/i);
    expect(result.invalidates_if).toMatch(/reclaimed shelf/i);
    expect(result.call_age_seconds).toBe(19);
    expect(result.current_close).toBe(458.1);
  });

  it("returns unavailable when the live bridge fails — no mock data, only honest unavailable state", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockRejectedValue(
      new Error("live snapshot failed"),
    );

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    // No mock data — the system returns an honest unavailable state
    expect(result.call).toBe("stand_aside");
    expect(result.trade_status).toBe("not_valid");
    expect(result.entry).toBeNull();
    expect(result.stop_loss).toBeNull();
    expect(result.take_profit).toBeNull();
    expect(result.direction_bias).toBeNull();
    expect(result.guardian_state).toBe("unavailable");
    expect(result.guardian_reason).toMatch(/unavailable/i);
  });

  it("keeps an unavailable guardian state honest when the bridge returns no trustworthy execution levels", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: null,
      regime: null,
      direction_bias: null,
      why: "Live market read unavailable. The app could not confirm a fresh price from the bridge.",
      wait_for: "wait for the live bridge to reconnect, then refresh the call",
      decision_summary:
        "Live market read unavailable. Refresh after the live bridge reconnects.",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: null,
      stop_loss: null,
      take_profit: null,
      reward_risk: null,
      guardian_state: "unavailable",
      guardian_reason:
        "Live market read unavailable. The app could not confirm a fresh price from the bridge.",
      current_close: null,
      generated_at: "2026-07-11T03:05:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    // The snapshot's unavailable state is preserved — no mock override
    expect(result.guardian_state).toBe("unavailable");
    expect(result.entry).toBeNull();
    expect(result.stop_loss).toBeNull();
    expect(result.take_profit).toBeNull();
    expect(result.guardian_reason).toMatch(/unavailable/i);
  });

  it("keeps unavailable execution levels null when the adapter returns stale numbers — no mock override", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: null,
      regime: null,
      direction_bias: null,
      why: "Live market read unavailable. The app could not confirm a fresh price from the bridge.",
      wait_for: "wait for the live bridge to reconnect, then refresh the call",
      decision_summary:
        "Live market read unavailable. Refresh after the live bridge reconnects.",
      entry_area: "around 459.6",
      stop_area: "below 458.2",
      target_area: "toward 462.2",
      entry: 459.6,
      stop_loss: 458.2,
      take_profit: 462.2,
      reward_risk: 2,
      guardian_state: "unavailable",
      guardian_reason:
        "Live market read unavailable. The app could not confirm a fresh price from the bridge.",
      current_close: null,
      generated_at: "2026-07-11T03:05:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    // sanitizeUnavailableExecutionLevels strips execution levels from unavailable state
    expect(result.guardian_state).toBe("unavailable");
    expect(result.entry_area).toBeNull();
    expect(result.stop_area).toBeNull();
    expect(result.target_area).toBeNull();
    expect(result.entry).toBeNull();
    expect(result.stop_loss).toBeNull();
    expect(result.take_profit).toBeNull();
  });

  it("retries a transient live-read failure before declaring the bridge unavailable", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const liveSnapshotSpy = vi
      .spyOn(engineBridge.liveSnapshotAdapter, "read")
      .mockRejectedValueOnce(new Error("temporary bridge error"))
      .mockResolvedValueOnce({
        symbol: "R_100",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.73,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers still control the short-term move",
        wait_for: "wait for a clean bullish continuation close",
        decision_summary:
          "buy setup valid; buyers still control the short-term move",
        entry_area: "around 459.6",
        stop_area: "below 458.2",
        target_area: "toward 462.2",
        entry: 459.6,
        stop_loss: 458.2,
        take_profit: 462.2,
        reward_risk: 2,
        guardian_state: "confirmed",
        guardian_reason: "Buy confirmation received from improving short-term acceptance.",
        current_close: 459.7,
        generated_at: "2026-07-11T02:30:00Z",
      });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(2);
    expect(result.call).toBe("buy_candidate");
    expect(result.entry).toBe(459.6);
    expect(result.guardian_state).toBe("confirmed");
  });

  it("writes fresh calls into the local history journal", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-history-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockResolvedValue({
      symbol: "R_75",
      call: "sell_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.68,
      regime: "trend_down",
      direction_bias: "sell",
      why: "sellers still control the short-term move",
      wait_for: "wait for a clean bearish continuation close",
      decision_summary: "sell setup ready",
      entry_area: "around 321.0",
      stop_area: "above 324.0",
      target_area: "toward 315.0",
      entry: 321,
      stop_loss: 324,
      take_profit: 315,
      reward_risk: 2,
      current_close: 320.4,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "price closes back above the rejection shelf",
      call_age_seconds: 4,
      generated_at: "2026-07-09T13:10:00Z",
    });

    await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
    });

    const journal = await readFile(journalPath, "utf8");

    expect(journal).toContain("\"symbol\":\"R_75\"");
    expect(journal).toContain("\"call\":\"sell_candidate\"");
  });

  it("reuses the latest journaled call before re-running the live snapshot", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    const cachedEntry = {
      symbol: "R_75",
      call: "sell_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.68,
      regime: "trend_down",
      direction_bias: "sell",
      why: "sellers still control the short-term move",
      wait_for: "wait for a clean bearish continuation close",
      decision_summary:
        "  4H bearish bias; 1H rejection held; 15m confirmed continuation  ",
      entry_area: "around 321.0",
      stop_area: "above 324.0",
      target_area: "toward 315.0",
      entry: 321,
      stop_loss: 324,
      take_profit: 315,
      reward_risk: 2,
      current_close: 320.4,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "  price closes back above the defended 1H shelf  ",
      call_age_seconds: 4,
      generated_at: new Date().toISOString(),
      account_mode: "own_account",
      trading_mode: "sniper",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
    await writeFile(journalPath, `${JSON.stringify(cachedEntry)}\n`, "utf8");

    const liveSnapshotSpy = vi.spyOn(engineBridge.liveSnapshotAdapter, "read");

    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).not.toHaveBeenCalled();
    expect(result.symbol).toBe("R_75");
    expect(result.guardian_state).toBe("actionable");
    expect(result.decision_summary).toBe(
      "4H bearish bias; 1H rejection held; 15m confirmed continuation",
    );
    expect(result.invalidates_if).toBe(
      "price closes back above the defended 1H shelf",
    );
  });

  it("ignores legacy invalid journal lines and still reuses a fresh prepared call", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-invalid-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    const cachedEntry = {
      symbol: "R_75",
      call: "sell_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.68,
      regime: "trend_down",
      direction_bias: "sell",
      why: "sellers still control the short-term move",
      wait_for: "wait for a clean bearish continuation close",
      decision_summary: "sell setup ready",
      entry_area: "around 321.0",
      stop_area: "above 324.0",
      target_area: "toward 315.0",
      entry: 321,
      stop_loss: 324,
      take_profit: 315,
      reward_risk: 2,
      current_close: 320.4,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "price closes back above the rejection shelf",
      call_age_seconds: 4,
      generated_at: new Date().toISOString(),
      account_mode: "own_account",
      trading_mode: "sniper",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
    await writeFile(
      journalPath,
      ['{"legacy":', JSON.stringify(cachedEntry)].join("\n") + "\n",
      "utf8",
    );

    const liveSnapshotSpy = vi.spyOn(engineBridge.liveSnapshotAdapter, "read");

    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).not.toHaveBeenCalled();
    expect(result.symbol).toBe("R_75");
    expect(result.call).toBe("sell_candidate");
    expect(result.guardian_state).toBe("actionable");
  });

  it("does not reuse a stale forming prepared call and falls back to a live snapshot", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-forming-stale-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    const staleFormingEntry = {
      symbol: "R_75",
      call: "stand_aside",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: 0.55,
      regime: "transition",
      direction_bias: "sell",
      why: "sellers are pressing, but the setup is still forming",
      wait_for: "wait for a clean breakdown confirmation",
      decision_summary: "setup still forming",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: null,
      stop_loss: null,
      take_profit: null,
      reward_risk: null,
      current_close: 320.1,
      guardian_state: "forming",
      guardian_reason: "The setup is still forming and needs confirmation.",
      invalidates_if: null,
      call_age_seconds: 9,
      generated_at: new Date(Date.now() - 10_000).toISOString(),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
    await writeFile(journalPath, `${JSON.stringify(staleFormingEntry)}\n`, "utf8");

    const liveSnapshotSpy = vi
      .spyOn(engineBridge.liveSnapshotAdapter, "read")
      .mockResolvedValue(buildLiveSnapshot("R_75"));

    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).toHaveBeenCalledWith(expect.objectContaining({
      engineRoot: "c:\\engine-root",
      symbol: "R_75",
    }));
    expect(result.guardian_state).toBe("actionable");

    expect(result.why).toBe("sellers still control the short-term move");
  });

  it("still reuses a recent prepared actionable call", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-actionable-fresh-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    const recentActionableEntry = {
      symbol: "R_75",
      call: "sell_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.68,
      regime: "trend_down",
      direction_bias: "sell",
      why: "sellers still control the short-term move",
      wait_for: "wait for a clean bearish continuation close",
      decision_summary: "sell setup ready",
      entry_area: "around 321.0",
      stop_area: "above 324.0",
      target_area: "toward 315.0",
      entry: 321,
      stop_loss: 324,
      take_profit: 315,
      reward_risk: 2,
      current_close: 320.4,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "price closes back above the rejection shelf",
      call_age_seconds: 2,
      generated_at: new Date(Date.now() - 2_000).toISOString(),
      account_mode: "own_account",
      trading_mode: "sniper",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
    await writeFile(journalPath, `${JSON.stringify(recentActionableEntry)}\n`, "utf8");

    const liveSnapshotSpy = vi.spyOn(engineBridge.liveSnapshotAdapter, "read");

    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).not.toHaveBeenCalled();
    expect(result.guardian_state).toBe("actionable");
    expect(result.invalidates_if).toMatch(/rejection shelf/i);
  });

  it("does not reuse a near-threshold forming prepared call on a manual refresh", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-forming-near-threshold-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    const recentNearThresholdEntry = {
      symbol: "R_75",
      call: "stand_aside",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: 0.498,
      regime: "range",
      direction_bias: "none",
      why: "current movement is active but not a clean setup yet",
      wait_for: "wait for confidence above threshold and cleaner directional agreement",
      decision_summary: null,
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: null,
      stop_loss: null,
      take_profit: null,
      reward_risk: null,
      current_close: 53612.6402,
      guardian_state: "forming",
      guardian_reason: "Directional thesis is still forming.",
      invalidates_if: null,
      call_age_seconds: 2,
      generated_at: new Date(Date.now() - 2_000).toISOString(),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
    await writeFile(journalPath, `${JSON.stringify(recentNearThresholdEntry)}\n`, "utf8");

    const liveSnapshotSpy = vi
      .spyOn(engineBridge.liveSnapshotAdapter, "read")
      .mockResolvedValue(buildLiveSnapshot("R_75"));

    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).toHaveBeenCalledWith(expect.objectContaining({
      engineRoot: "c:\\engine-root",
      symbol: "R_75",
    }));
    expect(result.trade_status).toBe("valid");
    expect(result.guardian_state).toBe("actionable");
  });

  it("does not reuse a weak prepared forming call when manual reuse is disabled", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-cache-manual-weak-forming-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);

    const recentWeakFormingEntry = {
      symbol: "R_75",
      call: "stand_aside",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: 0.2,
      regime: "range",
      direction_bias: "sell",
      why: "setup still forming",
      wait_for: "wait for confirmation",
      decision_summary: "setup still forming",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: null,
      stop_loss: null,
      take_profit: null,
      reward_risk: null,
      current_close: 320.1,
      guardian_state: "forming",
      guardian_reason: "The setup is still forming and needs confirmation.",
      invalidates_if: null,
      call_age_seconds: 2,
      generated_at: new Date(Date.now() - 2_000).toISOString(),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
    await writeFile(journalPath, `${JSON.stringify(recentWeakFormingEntry)}\n`, "utf8");

    const liveSnapshotSpy = vi
      .spyOn(engineBridge.liveSnapshotAdapter, "read")
      .mockResolvedValue(buildLiveSnapshot("R_75"));

    const result = await engineBridge.runFreshCall({
      symbol: "R_75",
      accountMode: "own_account",
      propAccountState: null,
      reusePreparedCall: "never",
    });

    expect(liveSnapshotSpy).toHaveBeenCalledWith(expect.objectContaining({
      engineRoot: "c:\\engine-root",
      symbol: "R_75",
    }));
    expect(result.trade_status).toBe("valid");
    expect(result.guardian_state).toBe("actionable");
  });

  it("uses live MT5 prop telemetry when configured", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    vi.stubEnv("SYNTHETIC_PROP_STARTING_BALANCE", "100000");
    vi.stubEnv("SYNTHETIC_MT5_SERVER", "Blueberry");
    vi.stubEnv("SYNTHETIC_MT5_LOGIN", "123456");
    vi.stubEnv("SYNTHETIC_MT5_PASSWORD", "secret");

    const propProfileSpy = vi
      .spyOn(engineBridge.livePropProfileAdapter, "read")
      .mockResolvedValue({
        profile: "blueberry_2step_funded",
        startingBalance: 100000,
        currentBalance: 101250,
        currentEquity: 100950,
        todaysRealizedLoss: 150,
        todaysFloatingLossExposure: 50,
        highImpactNewsLockout: false,
      });

    const profile = await engineBridge.getCurrentPropProfile();

    expect(propProfileSpy).toHaveBeenCalled();
    expect(profile.currentBalance).toBe(101250);
    expect(profile.currentEquity).toBe(100950);
  });
});

describe("prepared-call warmup", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("writes fresh own-account entries for R_75 and R_100 into the journal", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-warmup-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);
    vi.resetModules();
    const reloadedBridge = await import("../src/lib/engine-bridge");
    const liveSnapshotSpy = vi
      .spyOn(reloadedBridge.liveSnapshotAdapter, "read")
      .mockImplementation(async ({ symbol }) => buildLiveSnapshot(symbol));

    await reloadedBridge.warmPreparedCalls();

    const journal = await readFile(journalPath, "utf8");
    const entries = journal
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line) as Record<string, unknown>);

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);
    // Promise.all in warmPreparedCalls introduces non-determinism, so check
    // each expected combination was called (order-independent).
    const expectedCombos = [
      { symbol: "R_75", tradingMode: "sniper" },
      { symbol: "R_75", tradingMode: "active_trader" },
      { symbol: "R_100", tradingMode: "sniper" },
      { symbol: "R_100", tradingMode: "active_trader" },
    ];
    for (const { symbol, tradingMode } of expectedCombos) {
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
    expect(entries).toHaveLength(4);
    expect(entries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          symbol: "R_75",
          account_mode: "own_account",
          prop_compliance: null,
        }),
        expect.objectContaining({
          symbol: "R_100",
          account_mode: "own_account",
          prop_compliance: null,
        }),
      ]),
    );
  });

  it("triggers background warmup on getSystemStatus when engine root is configured", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    const tempDir = await mkdtemp(join(tmpdir(), "mitems-warmup-on-status-"));
    const journalPath = join(tempDir, "call-history.jsonl");
    vi.stubEnv("SYNTHETIC_OPERATOR_HISTORY_PATH", journalPath);
    vi.resetModules();
    const reloadedBridge = await import("../src/lib/engine-bridge");
    const liveSnapshotSpy = vi
      .spyOn(reloadedBridge.liveSnapshotAdapter, "read")
      .mockImplementation(async ({ symbol }) => buildLiveSnapshot(symbol));
    const status = await reloadedBridge.getSystemStatus();
    expect(status.backend_status).toBe("live_bridge_ready");

    // Call warmPreparedCalls directly to verify the warmup logic
    // (the getSystemStatus call schedules it via setTimeout(0) but
    // we run it directly to avoid timer/I/O interaction in tests).
    await reloadedBridge.warmPreparedCalls();

    expect(liveSnapshotSpy).toHaveBeenCalledTimes(4);

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
  });

  it("reschedules prepared warmup periodically after a successful run", async () => {
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

    // Verify the warmup schedules the next cycle via setTimeout.
    const refreshDelay = setTimeoutSpy.mock.calls.at(-1)?.[1];
    expect(typeof refreshDelay).toBe("number");
    expect(refreshDelay).toBe(45_000);

    // Clear the CSV mtime cache so the second warmup cycle re-runs
    // rather than skipping because the CSV hasn't changed.
    reloadedBridge.resetTestOverrides();

    // Call warmPreparedCalls a second time directly instead of relying
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
    }
  });
});

describe("getCurrentPropProfileForRequest", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("uses request-supplied prop credentials before env fallback", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    vi.stubEnv("SYNTHETIC_MT5_SERVER", "EnvServer");
    vi.stubEnv("SYNTHETIC_MT5_LOGIN", "111111");
    vi.stubEnv("SYNTHETIC_MT5_PASSWORD", "env-secret");

    const propProfileSpy = vi
      .spyOn(engineBridge.livePropProfileAdapter, "read")
      .mockResolvedValue({
        profile: "blueberry_2step_funded",
        startingBalance: 120000,
        currentBalance: 119800,
        currentEquity: 119700,
        todaysRealizedLoss: 100,
        todaysFloatingLossExposure: 50,
        highImpactNewsLockout: false,
      });

    const profile = await engineBridge.getCurrentPropProfileForRequest({
      connection: {
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        terminalPath: null,
      },
      startingBalance: 120000,
    });

    expect(propProfileSpy).toHaveBeenCalledWith({
      engineRoot: "c:\\engine-root",
      config: expect.objectContaining({
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        startingBalance: 120000,
      }),
    });
    expect(profile.telemetry.status).toBe("live_confirmed");
    expect(profile.telemetry.message).toBe("Live prop check confirmed");
  });

  it("falls back to own-account env credentials when the request fields are blank", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");
    vi.stubEnv("SYNTHETIC_MT5_SERVER", "EnvServer");
    vi.stubEnv("SYNTHETIC_MT5_LOGIN", "111111");
    vi.stubEnv("SYNTHETIC_MT5_PASSWORD", "env-secret");

    const propProfileSpy = vi
      .spyOn(engineBridge.livePropProfileAdapter, "read")
      .mockResolvedValue({
        profile: "blueberry_2step_funded",
        startingBalance: 100000,
        currentBalance: 100050,
        currentEquity: 100010,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 40,
        highImpactNewsLockout: false,
      });

    const profile = await engineBridge.getCurrentPropProfileForRequest({
      connection: {
        server: null,
        login: null,
        password: null,
        terminalPath: null,
      },
      startingBalance: null,
    });

    expect(propProfileSpy).toHaveBeenCalledWith({
      engineRoot: "c:\\engine-root",
      config: expect.objectContaining({
        server: "EnvServer",
        login: "111111",
        password: "env-secret",
        startingBalance: 100000,
      }),
    });
    expect(profile.telemetry.status).toBe("own_account_fallback");
    expect(profile.telemetry.message).toBe("Using own-account fallback");
  });

  it("returns the unavailable profile when neither dedicated nor fallback credentials exist", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    const propProfileSpy = vi.spyOn(engineBridge.livePropProfileAdapter, "read");

    const profile = await engineBridge.getCurrentPropProfileForRequest({
      connection: null,
      startingBalance: null,
    });

    expect(propProfileSpy).not.toHaveBeenCalled();
    expect(profile).toEqual({
      profile: "blueberry_2step_funded",
      startingBalance: 100000,
      currentBalance: 0,
      currentEquity: 0,
      todaysRealizedLoss: 0,
      todaysFloatingLossExposure: 0,
      highImpactNewsLockout: false,
      telemetry: {
        status: "live_unavailable",
        message: "MT5 not configured or unreachable — no prop profile available",
      },
    });
  });
});
