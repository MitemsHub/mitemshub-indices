/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useOperatorWorkspace } from "../src/hooks/use-operator-workspace";

function WorkspaceHarness() {
  const workspace = useOperatorWorkspace();

  return (
    <div>
      <button type="button" onClick={() => void workspace.runSymbol("R_100")}>
        Run R_100
      </button>
      <pre data-testid="current-call">
        {JSON.stringify(workspace.currentCall)}
      </pre>
    </div>
  );
}

function buildSupportResponse(url: string): Promise<Response> | null {
  if (url.includes("/api/history")) {
    return Promise.resolve(
      new Response(JSON.stringify({ history: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  }

  if (url.includes("/api/system/status")) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          latest_call: "R_100 stand_aside",
          alert_count: 0,
          suppressed_context_count: 0,
          transport_event_count: 0,
          latest_transport_event: "steady",
          latest_transport_reason: "test route",
          backend_status: "live_bridge_ready",
          journal_status: "fresh",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
  }

  if (url.includes("/api/prop-profiles/current")) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
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
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
  }

  return null;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useOperatorWorkspace", () => {
  it("keeps intraday execution geometry fields in current call state", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      const support = buildSupportResponse(url);
      if (support) {
        return support;
      }

      if (url.includes("/api/calls/run")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
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
                "4H bullish bias; 1H pullback held; 15m confirmed continuation",
              entry_area: "around 475.1",
              stop_area: "below 474.8",
              target_area: "toward 488.8",
              entry: 475.1,
              stop_loss: 474.8,
              take_profit: 488.8,
              reward_risk: 1.9,
              current_close: 476,
              guardian_state: "actionable",
              guardian_reason:
                "The setup is actionable, but live continuation still needs more persistence.",
              invalidates_if: "price closes back below the defended 1H shelf",
              execution_stop: 474.8,
              thesis_invalidation: 440.67,
              primary_target: 488.8,
              extended_target: 493.4,
              hold_horizon_minutes: 60,
              generated_at: "2026-07-12T11:00:00Z",
              account_mode: "own_account",
              prop_compliance: null,
              prop_adjusted_risk: null,
              prop_block_reason: null,
              prop_remaining_daily_buffer: null,
              prop_remaining_overall_buffer: null,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url.includes("/api/calls/guardian")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_100",
              guardian_state: "actionable",
              guardian_reason:
                "The setup is actionable, but live continuation still needs more persistence.",
              current_close: 476,
              generated_at: "2026-07-12T11:00:00Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    await user.click(screen.getByRole("button", { name: /run r_100/i }));

    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;

      expect(currentCall?.execution_stop).toBe(474.8);
      expect(currentCall?.thesis_invalidation).toBe(440.67);
      expect(currentCall?.primary_target).toBe(488.8);
      expect(currentCall?.extended_target).toBe(493.4);
      expect(currentCall?.hold_horizon_minutes).toBe(60);
    });
  });
});
