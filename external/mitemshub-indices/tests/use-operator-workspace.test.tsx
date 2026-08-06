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
      <button type="button" onClick={() => workspace.setExecutionMode("live_mt5")}>
        Set live mode
      </button>
      <button type="button" onClick={() => void workspace.executeTradeOrder()}>
        Execute order
      </button>
      <pre data-testid="current-call">
        {JSON.stringify(workspace.currentCall)}
      </pre>
      <span data-testid="execution-error">{workspace.executionError ?? ""}</span>
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

  if (url.includes("/api/calls/latest")) {
    // No usable cached call on mount — a stand_aside forces the auto-run
    // path so the plan populates without a manual click.
    return Promise.resolve(
      new Response(
        JSON.stringify({
          symbol: "R_100",
          call: "stand_aside",
          alert_type: "context_update",
          trade_status: "not_valid",
          confidence: null,
          regime: "range",
          direction_bias: "none",
          why: "current movement is active but not a clean setup yet",
          current_close: 352.1,
          guardian_state: "forming",
          guardian_reason: "Setup still forming",
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

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
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

  it("auto-runs a fresh read on mount when there is no usable cached call", async () => {
    const runCalls: string[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const support = buildSupportResponse(url);
      if (support) {
        return support;
      }

      if (url.includes("/api/calls/run")) {
        runCalls.push(url);
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
              why: "buyers control the short-term move",
              wait_for: "wait for confirmation",
              decision_summary: "buy setup ready",
              entry: 475.1,
              stop_loss: 474.8,
              take_profit: 488.8,
              reward_risk: 1.9,
              current_close: 476,
              guardian_state: "actionable",
              guardian_reason: "The setup is actionable.",
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

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    // No click: the plan must populate on its own because the cached call
    // is a stand_aside (not usable), so the hook auto-runs a fresh read.
    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.call).toBe("buy_candidate");
      expect(currentCall?.entry).toBe(475.1);
    });
    expect(runCalls.length).toBeGreaterThanOrEqual(1);
  });

  it("blocks live MT5 submits for paper-only calls (no empirical verdict)", async () => {
    const user = userEvent.setup();
    const submitCalls: Array<{ url: string; body?: unknown }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
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
              decision_summary: "4H bullish bias; 1H pullback held",
              entry_area: "around 475.1",
              stop_area: "below 474.8",
              target_area: "toward 488.8",
              entry: 475.1,
              stop_loss: 474.8,
              take_profit: 488.8,
              reward_risk: 1.9,
              current_close: 476,
              guardian_state: "actionable",
              guardian_reason: "The setup is actionable.",
              invalidates_if: "price closes back below the defended 1H shelf",
              generated_at: "2026-07-12T11:00:00Z",
              account_mode: "own_account",
              prop_compliance: null,
              prop_adjusted_risk: null,
              prop_block_reason: null,
              prop_remaining_daily_buffer: null,
              prop_remaining_overall_buffer: null,
              size_multiplier: 0,
              position_sizing_empirical: "paper_only",
              stage3: {
                state: "insufficient_data",
                evidence_status: "still_learning",
                trigger_type: "continuation_close",
                empirical_target_hit_rate: 0.6,
                empirical_sample_count: 4,
                empirical_stop_hit_rate: 0.25,
                horizon_verdict: "calibrated",
                horizon_verdict_4h: "calibrated",
                horizon_verdict_6h: "calibrated",
                model_confidence: 0.71,
                display_confidence: 0.71,
                min_samples: 10,
                hit_rate_floor: 0.5,
                suppression_mode: "suppress",
                below_floor: false,
                sizing: {
                  level: "paper_only",
                  multiplier: 0,
                  basis: "still_learning",
                  reason: "60% hit rate on fewer than the minimum samples — paper only until verified",
                },
                suppressed_call: null,
                note: "only 4/10 scored outcomes — the raw model confidence is shown.",
              },
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
              guardian_reason: "The setup is actionable.",
              current_close: 476,
              generated_at: "2026-07-12T11:00:00Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url.includes("/api/execution/submit")) {
        submitCalls.push({ url, body: JSON.parse(String((init as RequestInit)?.body ?? "{}")) });
        return Promise.resolve(
          new Response(
            JSON.stringify({ accepted: true, position_id: "999", message: "placed" }),
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
      const stage3 = (currentCall?.stage3 ?? {}) as { sizing?: { level?: string } };
      expect(currentCall?.size_multiplier).toBe(0);
      expect(stage3.sizing?.level).toBe("paper_only");
    });

    await user.click(screen.getByRole("button", { name: /set live mode/i }));
    await user.click(screen.getByRole("button", { name: /execute order/i }));

    await waitFor(() => {
      expect(screen.getByTestId("execution-error").textContent).toMatch(/paper-only/i);
    });
    // The paper-only call must never reach the submit endpoint.
    expect(submitCalls).toHaveLength(0);
  });

  it("blocks live MT5 submits for still_learning calls when proven-only mode is on", async () => {
    // Proven-only mode is persisted in localStorage and read at hook init.
    localStorage.setItem("synth-gate-proven-only", "1");
    const user = userEvent.setup();
    const submitCalls: Array<{ url: string; body?: unknown }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const support = buildSupportResponse(url);
      if (support) {
        return support;
      }

      if (url.includes("/api/calls/run")) {
        // A candidate that is still_learning (above-floor rate, too few
        // samples) but carries FULL size — the exact case proven-only mode
        // is designed to hold back even though the sizing ladder allows it.
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_100",
              call: "buy_candidate",
              alert_type: "setup_candidate",
              trade_status: "valid",
              confidence: 0.71,
              regime: "trend_up",
              direction_bias: "buy",
              why: "buyers still control the short-term move",
              wait_for: "wait for a clean bullish continuation close",
              decision_summary: "4H bullish bias; 1H pullback held",
              entry: 475.1,
              stop_loss: 474.8,
              take_profit: 488.8,
              reward_risk: 1.9,
              current_close: 476,
              guardian_state: "actionable",
              guardian_reason: "The setup is actionable.",
              generated_at: "2026-07-12T11:00:00Z",
              account_mode: "own_account",
              prop_compliance: null,
              prop_adjusted_risk: null,
              prop_block_reason: null,
              prop_remaining_daily_buffer: null,
              prop_remaining_overall_buffer: null,
              size_multiplier: 1,
              position_sizing_empirical: "full",
              stage3: {
                state: "gated",
                evidence_status: "still_learning",
                trigger_type: "continuation_close",
                empirical_target_hit_rate: 0.6,
                empirical_sample_count: 7,
                empirical_stop_hit_rate: 0.25,
                horizon_verdict: "calibrated",
                model_confidence: 0.71,
                display_confidence: 0.71,
                min_samples: 10,
                hit_rate_floor: 0.5,
                suppression_mode: "suppress",
                below_floor: false,
                sizing: {
                  level: "full",
                  multiplier: 1,
                  basis: "above_floor",
                  reason: "hit rate clears the floor but samples are still accruing",
                },
                suppressed_call: null,
                note: "still learning — 7/10 scored outcomes.",
              },
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
              guardian_reason: "The setup is actionable.",
              current_close: 476,
              generated_at: "2026-07-12T11:00:00Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url.includes("/api/execution/submit")) {
        submitCalls.push({ url, body: JSON.parse(String((init as RequestInit)?.body ?? "{}")) });
        return Promise.resolve(
          new Response(
            JSON.stringify({ accepted: true, position_id: "999", message: "placed" }),
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
      const stage3 = (currentCall?.stage3 ?? {}) as {
        evidence_status?: string;
        sizing?: { level?: string };
      };
      expect(currentCall?.size_multiplier).toBe(1);
      expect(stage3.evidence_status).toBe("still_learning");
      expect(stage3.sizing?.level).toBe("full");
    });

    await user.click(screen.getByRole("button", { name: /set live mode/i }));
    await user.click(screen.getByRole("button", { name: /execute order/i }));

    await waitFor(() => {
      expect(screen.getByTestId("execution-error").textContent).toMatch(
        /proven-only execution is on/i,
      );
    });
    // Full-sized but unproven must still never reach the submit endpoint.
    expect(submitCalls).toHaveLength(0);
    localStorage.removeItem("synth-gate-proven-only");
  });

  it("allows live MT5 in annotate mode and scales the lot by the multiplier", async () => {
    const user = userEvent.setup();
    const submitCalls: Array<{ url: string; body?: unknown }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
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
              decision_summary: "4H bullish bias; 1H pullback held",
              entry_area: "around 475.1",
              stop_area: "below 474.8",
              target_area: "toward 488.8",
              entry: 475.1,
              stop_loss: 474.8,
              take_profit: 488.8,
              reward_risk: 1.9,
              current_close: 476,
              guardian_state: "actionable",
              guardian_reason: "The setup is actionable.",
              invalidates_if: "price closes back below the defended 1H shelf",
              generated_at: "2026-07-12T11:00:00Z",
              account_mode: "own_account",
              prop_compliance: null,
              prop_adjusted_risk: null,
              prop_block_reason: null,
              prop_remaining_daily_buffer: null,
              prop_remaining_overall_buffer: null,
              size_multiplier: 0,
              position_sizing_empirical: "paper_only",
              stage3: {
                state: "annotated",
                evidence_status: "suppressed",
                trigger_type: "continuation_close",
                empirical_target_hit_rate: 0.3,
                empirical_sample_count: 14,
                empirical_stop_hit_rate: 0.6,
                horizon_verdict: "calibrated",
                horizon_verdict_4h: "calibrated",
                horizon_verdict_6h: "calibrated",
                model_confidence: 0.71,
                display_confidence: 0.3,
                min_samples: 10,
                hit_rate_floor: 0.5,
                suppression_mode: "annotate",
                below_floor: true,
                sizing: {
                  level: "paper_only",
                  multiplier: 0,
                  basis: "below_floor",
                  reason: "below the 50% verified floor (30%) — paper only even in annotate mode",
                },
                suppressed_call: null,
                note: "14 scored outcomes; target-hit rate 30% is BELOW the 50% floor — suppression mode is 'annotate'.",
              },
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
              guardian_reason: "The setup is actionable.",
              current_close: 476,
              generated_at: "2026-07-12T11:00:00Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url.includes("/api/execution/submit")) {
        submitCalls.push({ url, body: JSON.parse(String((init as RequestInit)?.body ?? "{}")) });
        return Promise.resolve(
          new Response(
            JSON.stringify({ accepted: true, position_id: "999", message: "placed" }),
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
      const stage3 = (currentCall?.stage3 ?? {}) as { suppression_mode?: string };
      expect(stage3.suppression_mode).toBe("annotate");
    });

    await user.click(screen.getByRole("button", { name: /set live mode/i }));
    await user.click(screen.getByRole("button", { name: /execute order/i }));

    // Annotate mode lifts the paper-only block; the lot is scaled by the
    // multiplier and floored at the broker minimum 0.01.
    await waitFor(() => {
      expect(submitCalls).toHaveLength(1);
    });
    const body = submitCalls[0].body as { execution_mode?: string; mt5_volume?: number };
    expect(body.execution_mode).toBe("live_mt5");
    expect(body.mt5_volume).toBe(0.01);
  });
});
