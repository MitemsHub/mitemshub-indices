import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as engineBridge from "../src/lib/engine-bridge";

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
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
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
        guardian_state: "armed",
        guardian_reason: "Directional thesis is armed, but confirmation has not arrived yet.",
        current_close: 51280,
        generated_at: "2026-07-09T13:00:00Z",
      });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(liveSnapshotSpy).toHaveBeenCalledWith({
      engineRoot: "c:\\engine-root",
      symbol: "R_100",
    });
    expect(result.generated_at).toBe("2026-07-09T13:00:00Z");
    expect(result.why).toBe("buyers still control the short-term move");
    expect(result.guardian_state).toBe("armed");
    expect(result.guardian_reason).toMatch(/confirmation has not arrived/i);
    expect(result.current_close).toBe(51280);
  });

  it("preserves armed guardian reasons when confirmation is blocked", async () => {
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
      guardian_state: "armed",
      guardian_reason:
        "Directional thesis is armed, but persistence is still too weak for confirmation.",
      generated_at: "2026-07-11T04:00:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.guardian_state).toBe("armed");
    expect(result.guardian_reason).toMatch(/persistence is still too weak/i);
    expect(result.entry).toBe(459.6);
  });

  it("preserves invalidated rollover reasons from the live snapshot", async () => {
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
      guardian_state: "invalidated",
      guardian_reason:
        "Setup invalidated after reversal pressure clustered too aggressively.",
      generated_at: "2026-07-11T04:05:00Z",
    });

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.guardian_state).toBe("invalidated");
    expect(result.guardian_reason).toMatch(/clustered too aggressively/i);
    expect(result.current_close).toBe(459.5);
  });

  it("returns an unavailable live-read response instead of mock trade levels when the bridge fails", async () => {
    vi.stubEnv("SYNTHETIC_ENGINE_ROOT", "c:\\engine-root");

    vi.spyOn(engineBridge.liveSnapshotAdapter, "read").mockRejectedValue(
      new Error("live snapshot failed"),
    );

    const result = await engineBridge.runFreshCall({
      symbol: "R_100",
      accountMode: "own_account",
      propAccountState: null,
    });

    expect(result.call).toBe("stand_aside");
    expect(result.trade_status).toBe("not_valid");
    expect(result.entry).toBeNull();
    expect(result.stop_loss).toBeNull();
    expect(result.take_profit).toBeNull();
    expect(result.decision_summary).toMatch(/live market read unavailable/i);
    expect(result.why).toMatch(/live market read unavailable/i);
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

    expect(result.guardian_state).toBe("unavailable");
    expect(result.entry).toBeNull();
    expect(result.stop_loss).toBeNull();
    expect(result.take_profit).toBeNull();
    expect(result.decision_summary).toMatch(/live market read unavailable/i);
  });

  it("keeps unavailable execution levels null when the adapter returns stale numbers", async () => {
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
      guardian_state: "armed",
      guardian_reason: "Directional thesis is armed, but confirmation has not arrived yet.",
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

  it("returns the mock profile when neither dedicated nor fallback credentials exist", async () => {
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
      currentBalance: 100200,
      currentEquity: 100100,
      todaysRealizedLoss: 0,
      todaysFloatingLossExposure: 0,
      highImpactNewsLockout: false,
      telemetry: {
        status: "live_unavailable",
        message: "Live prop check unavailable",
      },
    });
  });
});
