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

  it("POST /api/calls/run rejects malformed JSON instead of crashing the route", async () => {
    const request = new Request("http://localhost/api/calls/run", {
      method: "POST",
      body: "{bad json",
      headers: {
        "Content-Type": "application/json",
      },
    });

    const response = await postRun(request);
    const payload = await response.json();

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid JSON body.");
  });

  it("POST /api/calls/run returns actionable freshness metadata from the bridge", async () => {
    vi.spyOn(engineBridge, "runFreshCall").mockResolvedValue({
      symbol: "R_75",
      call: "sell_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.62,
      regime: "range",
      direction_bias: "sell",
      why: "sellers still control the upper rejection zone",
      wait_for: "a fresh bearish continuation close",
      decision_summary:
        "sell setup actionable; sellers still control the upper rejection zone",
      entry_area: "around 53074.2",
      stop_area: "above 53173.2",
      target_area: "toward 52886.2",
      entry: 53074.2,
      stop_loss: 53173.2,
      take_profit: 52886.2,
      reward_risk: 1.9,
      current_close: 53074.2,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "price closes back above the rejection shelf",
      call_age_seconds: 2,
      generated_at: "2026-07-11T22:00:00.000Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });

    const response = await postRun(
      new Request("http://localhost/api/calls/run", {
        method: "POST",
        body: JSON.stringify({
          symbol: "R_75",
          account_mode: "own_account",
        }),
      }),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.guardian_state).toBe("actionable");
    expect(payload.invalidates_if).toBe(
      "price closes back above the rejection shelf",
    );
    expect(payload.call_age_seconds).toBe(2);
  });

  it.each(["failing", "cancelled"] as const)(
    "POST /api/calls/run preserves %s live call states",
    async (guardianState) => {
      vi.spyOn(engineBridge, "runFreshCall").mockResolvedValue({
        symbol: "R_75",
        call: "sell_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.58,
        regime: "range",
        direction_bias: "sell",
        why: "sellers lost follow-through after the original rejection",
        wait_for: "refresh the live read before considering a new entry",
        decision_summary: "sell setup has deteriorated",
        entry_area: "around 53074.2",
        stop_area: "above 53173.2",
        target_area: "toward 52886.2",
        entry: 53074.2,
        stop_loss: 53173.2,
        take_profit: 52886.2,
        reward_risk: 1.9,
        current_close: guardianState === "cancelled" ? 53190.4 : 53110.8,
        guardian_state: guardianState,
        guardian_reason:
          guardianState === "cancelled"
            ? "The original trade thesis is broken and should not be used."
            : "The setup is deteriorating and the old plan is no longer fresh.",
        invalidates_if: "price closes back above the rejection shelf",
        call_age_seconds: guardianState === "cancelled" ? 18 : 9,
        generated_at: "2026-07-11T22:02:00.000Z",
        account_mode: "own_account",
        prop_compliance: null,
        prop_adjusted_risk: null,
        prop_block_reason: null,
        prop_remaining_daily_buffer: null,
        prop_remaining_overall_buffer: null,
      });

      const response = await postRun(
        new Request("http://localhost/api/calls/run", {
          method: "POST",
          body: JSON.stringify({
            symbol: "R_75",
            account_mode: "own_account",
          }),
        }),
      );
      const payload = await response.json();

      expect(response.status).toBe(200);
      expect(payload.guardian_state).toBe(guardianState);
      expect(payload.call_age_seconds).toBe(
        guardianState === "cancelled" ? 18 : 9,
      );
    },
  );

  it("POST /api/calls/run opts out of prepared reuse for user-triggered runs", async () => {
    const runFreshCallSpy = vi
      .spyOn(engineBridge, "runFreshCall")
      .mockResolvedValue({
        symbol: "R_75",
        call: "sell_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.62,
        regime: "range",
        direction_bias: "sell",
        why: "fresh live snapshot",
        wait_for: "wait for a clean bearish continuation close",
        decision_summary: "sell setup ready",
        entry_area: "around 53074.2",
        stop_area: "above 53173.2",
        target_area: "toward 52886.2",
        entry: 53074.2,
        stop_loss: 53173.2,
        take_profit: 52886.2,
        reward_risk: 1.9,
        current_close: 53074.2,
        guardian_state: "actionable",
        guardian_reason: "The setup is actionable with caution.",
        invalidates_if: "price closes back above the rejection shelf",
        call_age_seconds: 0,
        generated_at: "2026-07-12T10:00:00.000Z",
        account_mode: "own_account",
        prop_compliance: null,
        prop_adjusted_risk: null,
        prop_block_reason: null,
        prop_remaining_daily_buffer: null,
        prop_remaining_overall_buffer: null,
      });

    const response = await postRun(
      new Request("http://localhost/api/calls/run", {
        method: "POST",
        body: JSON.stringify({
          symbol: "R_75",
          account_mode: "own_account",
        }),
      }),
    );

    expect(response.status).toBe(200);
    expect(runFreshCallSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: "R_75",
        accountMode: "own_account",
        reusePreparedCall: "never",
      }),
    );
  });

  it("POST /api/calls/run preserves calibrated R_75 geometry", async () => {
    const runFreshCallSpy = vi
      .spyOn(engineBridge, "runFreshCall")
      .mockResolvedValue({
        symbol: "R_75",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.73,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers defended the intraday shelf and continuation remains intact",
        wait_for:
          "wait for the 5m continuation trigger to confirm, then manage toward the next hour objective",
        decision_summary:
          "buy setup ready; buyers defended the intraday shelf and continuation remains intact",
        entry_area: "around 55420.0",
        stop_area: "below 55280.0",
        target_area: "toward 56180.0",
        entry: 55420.0,
        stop_loss: 55280.0,
        take_profit: 56180.0,
        execution_stop: 55280.0,
        thesis_invalidation: 52541.0,
        primary_target: 56180.0,
        extended_target: 56640.0,
        hold_horizon_minutes: 60,
        reward_risk: 1.9,
        current_close: 55435.0,
        guardian_state: "actionable",
        guardian_reason: "The setup is actionable with caution.",
        invalidates_if:
          "5m continuation failure back through 55280.0 invalidates the execution attempt",
        call_age_seconds: 1,
        generated_at: "2026-07-12T11:05:00.000Z",
        account_mode: "own_account",
        prop_compliance: null,
        prop_adjusted_risk: null,
        prop_block_reason: null,
        prop_remaining_daily_buffer: null,
        prop_remaining_overall_buffer: null,
      });

    const response = await postRun(
      new Request("http://localhost/api/calls/run", {
        method: "POST",
        body: JSON.stringify({
          symbol: "R_75",
          account_mode: "own_account",
        }),
      }),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(runFreshCallSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: "R_75",
        accountMode: "own_account",
        reusePreparedCall: "never",
      }),
    );
    expect(payload.execution_stop).toBe(55280);
    expect(payload.thesis_invalidation).toBe(52541);
    expect(payload.primary_target).toBe(56180);
    expect(payload.extended_target).toBe(56640);
    expect(payload.wait_for).toMatch(/continuation/i);
    expect(payload.hold_horizon_minutes).toBe(60);
  });

  it("POST /api/calls/run preserves balanced intraday R_100 geometry", async () => {
    const runFreshCallSpy = vi
      .spyOn(engineBridge, "runFreshCall")
      .mockResolvedValue({
        symbol: "R_100",
        call: "buy_candidate",
        alert_type: "setup_candidate",
        trade_status: "valid",
        confidence: 0.74,
        regime: "trend_up",
        direction_bias: "buy",
        why: "buyers reclaimed the pullback shelf and still control continuation",
        wait_for:
          "wait for the 5m reclaim to confirm, then manage toward the next hour objective",
        decision_summary:
          "buy setup ready; buyers reclaimed the pullback shelf and still control continuation",
        entry_area: "around 476.1",
        stop_area: "below 474.9",
        target_area: "toward 488.4",
        entry: 476.1,
        stop_loss: 474.9,
        take_profit: 488.4,
        execution_stop: 474.9,
        thesis_invalidation: 440.67,
        primary_target: 488.4,
        extended_target: null,
        hold_horizon_minutes: 60,
        reward_risk: 1.9,
        current_close: 476.5,
        guardian_state: "actionable",
        guardian_reason: "The setup is actionable with caution.",
        invalidates_if:
          "5m close back below 474.8 invalidates the execution attempt",
        call_age_seconds: 1,
        generated_at: "2026-07-12T11:00:00.000Z",
        account_mode: "own_account",
        prop_compliance: null,
        prop_adjusted_risk: null,
        prop_block_reason: null,
        prop_remaining_daily_buffer: null,
        prop_remaining_overall_buffer: null,
      });

    const response = await postRun(
      new Request("http://localhost/api/calls/run", {
        method: "POST",
        body: JSON.stringify({
          symbol: "R_100",
          account_mode: "own_account",
        }),
      }),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(runFreshCallSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: "R_100",
        accountMode: "own_account",
        reusePreparedCall: "never",
      }),
    );
    expect(payload.execution_stop).toBe(474.9);
    expect(payload.thesis_invalidation).toBe(440.67);
    expect(payload.primary_target).toBe(488.4);
    expect(payload.wait_for).toMatch(/reclaim/i);
    expect(payload.extended_target).toBeNull();
    expect(payload.hold_horizon_minutes).toBe(60);
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
          current_close: null,
          guardian_state: "unavailable",
          guardian_reason: "no live read",
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

  it("POST /api/prop-profiles/current rejects malformed JSON instead of crashing the route", async () => {
    const response = await postCurrentPropProfile(
      new Request("http://localhost/api/prop-profiles/current", {
        method: "POST",
        body: "{bad json",
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    const payload = await response.json();

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid JSON body.");
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
        current_close: 500,
        guardian_state: "actionable",
        guardian_reason: "buy setup ready",
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
