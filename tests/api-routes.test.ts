import { describe, expect, it, vi } from "vitest";
import { GET as getGuardian } from "../app/api/calls/guardian/route";
import { GET as getLatest } from "../app/api/calls/latest/route";
import { POST as postRun } from "../app/api/calls/run/route";
import { GET as getHistory } from "../app/api/history/route";
import {
  GET as getCurrentPropProfile,
  POST as postCurrentPropProfile,
} from "../app/api/prop-profiles/current/route";
import { GET as getSystemStatus } from "../app/api/system/status/route";
import * as engineBridge from "../src/lib/engine-bridge";

describe("API routes", () => {
  it("POST /api/calls/run returns a fresh call payload", async () => {
    const request = new Request("http://localhost/api/calls/run", {
      method: "POST",
      body: JSON.stringify({
        symbol: "R_100",
        account_mode: "own_account",
      }),
    });

    const response = await postRun(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.symbol).toBe("R_100");
    expect(payload.account_mode).toBe("own_account");
  });

  it("GET /api/calls/latest returns the latest call for the requested symbol", async () => {
    const response = await getLatest(
      new Request("http://localhost/api/calls/latest?symbol=R_75"),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.symbol).toBe("R_75");
  });

  it("GET /api/calls/guardian returns a guardian status payload", async () => {
    const response = await getGuardian(
      new Request("http://localhost/api/calls/guardian?symbol=R_100"),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.symbol).toBe("R_100");
    expect(payload.guardian_state).toBeTruthy();
    expect(payload.guardian_reason).toBeTruthy();
  });

  it("GET /api/history returns recent calls", async () => {
    vi.spyOn(engineBridge, "getRecentHistory").mockResolvedValue({
      history: [
        {
          symbol: "R_100",
          call: "stand_aside",
          alert_type: "context_update",
          trade_status: "not_valid",
          confidence: null,
          regime: null,
          direction_bias: null,
          why: "Live market read unavailable. Refresh after the live bridge reconnects.",
          wait_for: "wait for the live bridge to reconnect, then refresh the call",
          decision_summary: "Live market read unavailable. Refresh after the live bridge reconnects.",
          entry_area: null,
          stop_area: null,
          target_area: null,
          entry: null,
          stop_loss: null,
          take_profit: null,
          reward_risk: null,
          generated_at: "2026-07-11T02:45:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        },
      ],
    });

    const response = await getHistory(
      new Request("http://localhost/api/history?symbol=R_100"),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.history.length).toBe(1);
    expect(payload.history[0].symbol).toBe("R_100");
  });

  it("GET /api/system/status returns backend health data", async () => {
    const response = await getSystemStatus(
      new Request("http://localhost/api/system/status"),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.backend_status).toBe("engine_not_configured");
  });

  it("GET /api/prop-profiles/current returns the current prop profile", async () => {
    const response = await getCurrentPropProfile(
      new Request("http://localhost/api/prop-profiles/current"),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.profile).toBe("deriv_2step_funded");
    expect(payload.telemetry.status).toBe("live_unavailable");
  });

  it("POST /api/prop-profiles/current uses the request connection", async () => {
    const profileSpy = vi
      .spyOn(engineBridge, "getCurrentPropProfileForRequest")
      .mockResolvedValue({
        profile: "deriv_2step_funded",
        startingBalance: 100000,
        currentBalance: 100000,
        currentEquity: 100100,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
        telemetry: {
          status: "own_account_fallback",
          message: "Using own-account fallback",
        },
      });

    const response = await postCurrentPropProfile(
      new Request("http://localhost/api/prop-profiles/current", {
        method: "POST",
        body: JSON.stringify({
          connection: {
            server: "PropServer",
            login: "222222",
            password: "prop-secret",
            terminalPath: null,
          },
          startingBalance: 120000,
        }),
      }),
    );

    expect(response.status).toBe(200);
    expect((await response.json()).telemetry.status).toBe("own_account_fallback");
    expect(profileSpy).toHaveBeenCalledWith({
      connection: {
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        terminalPath: null,
      },
      startingBalance: 120000,
    });
  });

  it("POST /api/calls/run forwards prop_connection when prop mode is active", async () => {
    const runFreshCallSpy = vi
      .spyOn(engineBridge, "runFreshCall")
      .mockResolvedValue({
        symbol: "R_100",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.71,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers still control the short-term move",
        wait_for: "wait for a clean bullish continuation close",
        decision_summary: "buy setup ready",
        entry_area: "around 500.0",
        stop_area: "below 496.0",
        target_area: "toward 510.0",
        entry: 500,
        stop_loss: 496,
        take_profit: 510,
        reward_risk: 2.5,
        generated_at: "2026-07-10T11:00:00.000Z",
        account_mode: "prop_firm",
        prop_compliance: "allowed",
        prop_adjusted_risk: 1,
        prop_block_reason: null,
        prop_remaining_daily_buffer: 4800,
        prop_remaining_overall_buffer: 9800,
      });

    const response = await postRun(
      new Request("http://localhost/api/calls/run", {
        method: "POST",
        body: JSON.stringify({
          symbol: "R_100",
          account_mode: "prop_firm",
          prop_account_state: {
            profile: "deriv_2step_funded",
            startingBalance: 100000,
            currentBalance: 100000,
            currentEquity: 100100,
            todaysRealizedLoss: 0,
            todaysFloatingLossExposure: 0,
            highImpactNewsLockout: false,
          },
          prop_connection: {
            server: "PropServer",
            login: "222222",
            password: "prop-secret",
            terminalPath: null,
            startingBalance: 120000,
          },
        }),
      }),
    );

    expect(response.status).toBe(200);
    expect(runFreshCallSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        accountMode: "prop_firm",
        propConnection: {
          server: "PropServer",
          login: "222222",
          password: "prop-secret",
          terminalPath: null,
          startingBalance: 120000,
        },
      }),
    );
  });
});
