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
      <button type="button" onClick={() => void workspace.runSymbol("R_75")}>
        Run R_75
      </button>
      <span data-testid="active-symbol">{workspace.activeSymbol}</span>
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
      <span data-testid="cached-call-error">
        {workspace.cachedCallError ?? ""}
      </span>
    </div>
  );
}

/**
 * Minimal EventSource stub so the tick-stream freshness effect (which opens
 * the shared /api/ticks feed) can be driven deterministically in jsdom.
 */
class MockEventSource {
  static instances: MockEventSource[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {
    // no-op
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  fail() {
    this.onerror?.();
  }
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
          profile: "deriv_2step_funded",
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
  vi.unstubAllGlobals();
  MockEventSource.instances = [];
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

  it("serves a journaled stand_aside instantly on mount without a fresh read", async () => {
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

    // The journal already holds a fresh stand_aside plan — the mount must
    // render it immediately and NOT spawn a slow fresh read just to
    // re-confirm "no setup yet" (the pre-fix behavior that made every page
    // load show the long "Pulling data…" state).
    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.call).toBe("stand_aside");
    });
    expect(runCalls.length).toBe(0);
  });

  it("auto-runs a fresh read on mount only when the journal is unavailable", async () => {
    const runCalls: string[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/history")) {
        return Promise.resolve(
          new Response(JSON.stringify({ history: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/calls/latest")) {
        // Empty journal — the mount has nothing to render, so the hook
        // must fall back to a fresh read automatically.
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_100",
              call: "unavailable",
              alert_type: "context_update",
              trade_status: "not_valid",
              confidence: null,
              regime: "unknown",
              direction_bias: "none",
              why: "no journaled plan",
              current_close: null,
              guardian_state: "unavailable",
              guardian_reason: "No plan yet",
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

  it("blocks live MT5 submits for unproven call types even when a stale payload claims full size", async () => {
    const user = userEvent.setup();
    const submitCalls: Array<{ url: string; body?: unknown }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const support = buildSupportResponse(url);
      if (support) {
        return support;
      }

      if (url.includes("/api/calls/run")) {
        // A stale/inconsistent payload: still_learning evidence but claims
        // FULL size with no execution_allowed authorization.  The collapsed
        // gate never emits this (still_learning always sizes 0.0), so the
        // submit path must fail closed rather than trust the claimed size.
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
                state: "insufficient_data",
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
                  level: "paper_only",
                  multiplier: 0,
                  basis: "still_learning",
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
      // The stale payload claims full size, but the gate's own sizing block
      // says paper_only — the submit path must honor the evidence, not the
      // claimed multiplier.
      expect(stage3.sizing?.level).toBe("paper_only");
    });

    await user.click(screen.getByRole("button", { name: /set live mode/i }));
    await user.click(screen.getByRole("button", { name: /execute order/i }));

    await waitFor(() => {
      expect(screen.getByTestId("execution-error").textContent).toMatch(
        /paper-only/i,
      );
    });
    // Full-sized but unproven must still never reach the submit endpoint.
    expect(submitCalls).toHaveLength(0);
  });

  it("blocks live MT5 submits for below-floor call types (no annotate escape)", async () => {
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
                state: "suppressed",
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
                suppression_mode: "suppress",
                execution_allowed: false,
                below_floor: true,
                sizing: {
                  level: "stand_aside",
                  multiplier: 0,
                  basis: "suppressed",
                  reason: "below the 50% verified floor (30%) — held back",
                },
                suppressed_call: "buy_candidate",
                note: "14 scored outcomes; target-hit rate 30% is BELOW the 50% floor — continuation_close calls are suppressed until the market-verified rate improves.",
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
      const stage3 = (currentCall?.stage3 ?? {}) as { state?: string; suppression_mode?: string };
      expect(stage3.state).toBe("suppressed");
      expect(stage3.suppression_mode).toBe("suppress");
    });

    await user.click(screen.getByRole("button", { name: /set live mode/i }));
    await user.click(screen.getByRole("button", { name: /execute order/i }));

    // The collapsed gate has no annotate escape: a below-floor call type is
    // always held back and never reaches the submit endpoint.
    await waitFor(() => {
      expect(screen.getByTestId("execution-error").textContent).toMatch(
        /paper-only/i,
      );
    });
    expect(submitCalls).toHaveLength(0);
  });

  it("places a live MT5 order for a market-proven call at full size", async () => {
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
              confidence: 0.62,
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
                evidence_status: "proven",
                trigger_type: "continuation_close",
                empirical_target_hit_rate: 0.62,
                empirical_sample_count: 24,
                empirical_stop_hit_rate: 0.29,
                horizon_verdict: "calibrated",
                horizon_verdict_4h: "calibrated",
                horizon_verdict_6h: "calibrated",
                model_confidence: 0.71,
                display_confidence: 0.62,
                min_samples: 10,
                hit_rate_floor: 0.5,
                suppression_mode: "suppress",
                below_floor: false,
                sizing: {
                  level: "full",
                  multiplier: 1,
                  basis: "gated",
                  reason: "calibrated horizon + 62% hit rate clears the floor",
                },
                suppressed_call: null,
                note: "24 scored outcomes; target-hit rate 62% clears 50% and the horizon verdict is calibrated.",
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
      ) as { size_multiplier?: number } | null;
      expect(currentCall?.size_multiplier).toBe(1);
    });

    await user.click(screen.getByRole("button", { name: /set live mode/i }));
    await user.click(screen.getByRole("button", { name: /execute order/i }));

    // Proven + full size: the collapsed gate authorizes the live order and
    // the lot is the base 0.01 scaled by the 1.0 multiplier.
    await waitFor(() => {
      expect(submitCalls).toHaveLength(1);
    });
    const body = submitCalls[0].body as { execution_mode?: string; mt5_volume?: number };
    expect(body.execution_mode).toBe("live_mt5");
    expect(body.mt5_volume).toBe(0.01);
  });

  it("defaults to R_75 and persists the symbol choice across reloads", async () => {
    localStorage.removeItem("synth-active-symbol");
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      const support = buildSupportResponse(url);
      if (support) return support;
      if (url.includes("/api/calls/run")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              call: "stand_aside",
              alert_type: "context_update",
              trade_status: "not_valid",
              confidence: null,
              regime: "range",
              direction_bias: "none",
              why: "no clean setup yet",
              current_close: 1920.5,
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              generated_at: "2026-07-12T11:00:00Z",
              account_mode: "own_account",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    // Fresh browser: no saved symbol -> the engine focus symbol R_75 wins.
    await waitFor(() =>
      expect(screen.getByTestId("active-symbol").textContent).toBe("R_75"),
    );

    // Selecting V75 persists it so a reload never snaps back to R_100.
    await user.click(screen.getByRole("button", { name: /run r_75/i }));
    await waitFor(() =>
      expect(localStorage.getItem("synth-active-symbol")).toBe("R_75"),
    );
  });

  it("restores a previously persisted symbol instead of the hard default", async () => {
    localStorage.setItem("synth-active-symbol", "R_100");

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      const support = buildSupportResponse(url);
      if (support) return support;
      if (url.includes("/api/calls/run")) {
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
              why: "no clean setup yet",
              current_close: 375.2,
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              generated_at: "2026-07-12T11:00:00Z",
              account_mode: "own_account",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    await waitFor(() =>
      expect(screen.getByTestId("active-symbol").textContent).toBe("R_100"),
    );
    localStorage.removeItem("synth-active-symbol");
  });

  it("keeps the last verified plan when a silent background refresh fails", async () => {
    const runCalls: string[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/history")) {
        return Promise.resolve(
          new Response(JSON.stringify({ history: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/calls/latest")) {
        // A confirmed, tradeable plan sits in the journal.
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              call: "buy_candidate",
              alert_type: "setup_candidate",
              trade_status: "valid",
              confidence: 0.73,
              regime: "trend_up",
              direction_bias: "buy",
              why: "buyers control the short-term move",
              decision_summary: "buy setup ready",
              entry: 1815.0,
              stop_loss: 1808.0,
              take_profit: 1845.0,
              reward_risk: 2.1,
              current_close: 1816.2,
              guardian_state: "confirmed",
              guardian_reason:
                "Buy confirmation is in place and the setup is ready to trade.",
              // Old enough that the mount auto-refresh silently re-reads.
              call_age_seconds: 9999,
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
      if (url.includes("/api/calls/run")) {
        runCalls.push(url);
        // The background read fails (e.g. a Python subprocess timeout) —
        // the confirmed plan must NOT be replaced by the unavailable fallback.
        return Promise.resolve(new Response("engine timeout", { status: 500 }));
      }
      if (url.includes("/api/calls/guardian")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              guardian_state: "confirmed",
              guardian_reason: "confirmed",
              current_close: 1816.2,
              generated_at: "2026-07-12T11:00:00Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/system/status")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              latest_call: "R_75 confirmed",
              alert_count: 0,
              suppressed_context_count: 0,
              transport_event_count: 0,
              latest_transport_event: "steady",
              latest_transport_reason: "test route",
              backend_status: "live_bridge_ready",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/prop-profiles/current")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              profile: "deriv_2step_funded",
              startingBalance: 5000,
              currentBalance: 5000,
              currentEquity: 5000,
              todaysRealizedLoss: 0,
              todaysFloatingLossExposure: 0,
              highImpactNewsLockout: false,
              telemetry: { status: "live_unavailable", message: "no" },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    // Mount renders the journaled confirmed plan immediately.
    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.guardian_state).toBe("confirmed");
    });

    // The stale plan triggers a silent background refresh, the refresh
    // fails — but the confirmed plan survives (keep-last-good) instead of
    // flipping to "Live read unavailable".
    expect(runCalls.length).toBeGreaterThanOrEqual(1);
    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.guardian_state).toBe("confirmed");
      expect(currentCall?.entry).toBe(1815.0);
    });
    await waitFor(() => {
      expect(screen.getByTestId("cached-call-error").textContent).toContain(
        "Background refresh failed",
      );
    });
  });

  it("updates the plan's live price from the shared tick stream", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    MockEventSource.instances = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/history")) {
        return Promise.resolve(
          new Response(JSON.stringify({ history: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/calls/latest")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              call: "stand_aside",
              alert_type: "context_update",
              trade_status: "not_valid",
              confidence: null,
              regime: "range",
              direction_bias: "none",
              why: "no clean setup yet",
              current_close: 1816.2,
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              generated_at: new Date().toISOString(),
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
              latest_call: "R_75 stand_aside",
              alert_count: 0,
              suppressed_context_count: 0,
              transport_event_count: 0,
              latest_transport_event: "steady",
              latest_transport_reason: "test route",
              backend_status: "live_bridge_ready",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/prop-profiles/current")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              profile: "deriv_2step_funded",
              startingBalance: 5000,
              currentBalance: 5000,
              currentEquity: 5000,
              todaysRealizedLoss: 0,
              todaysFloatingLossExposure: 0,
              highImpactNewsLockout: false,
              telemetry: { status: "live_unavailable", message: "no" },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/calls/guardian")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              current_close: 1816.2,
              generated_at: new Date().toISOString(),
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/intelligence")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              market_intelligence: null,
              evidence_summary: null,
              market_thesis: null,
              confidence_breakdown: null,
              trade_plan: null,
              risk_assessment: null,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.current_close).toBe(1816.2);
    });

    // A live R_75 tick arrives on the shared feed — the plan's displayed
    // price follows it without any Python read.
    const es = MockEventSource.instances[0];
    expect(es).toBeTruthy();
    es.emit({
      type: "tick",
      symbol: "R_75",
      // A tick strictly newer than the plan (live ticks always post-date the
      // snapshot that generated the plan; a future-dated epoch here just
      // makes the newer-than-plan guard deterministic in the test).
      tick: { epoch: Math.floor(Date.now() / 1000) + 60, price: 1820.5 },
    });

    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.current_close).toBe(1820.5);
    });
  });

  it("silently refreshes a stale plan while ticks are flowing", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    MockEventSource.instances = [];
    const runCalls: string[] = [];

    // A stale journaled plan with NO call_age_seconds (frozen-null — the
    // old mount/10-minute checks can never fire), which is exactly the
    // "plan ages between manual reads" defect this stream fixes.
    const staleGeneratedAt = new Date(Date.now() - 10 * 60_000).toISOString();

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/history")) {
        return Promise.resolve(
          new Response(JSON.stringify({ history: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/calls/latest")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              call: "stand_aside",
              alert_type: "context_update",
              trade_status: "not_valid",
              confidence: null,
              regime: "range",
              direction_bias: "none",
              why: "no clean setup yet",
              current_close: 1816.2,
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              generated_at: staleGeneratedAt,
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
      if (url.includes("/api/calls/run")) {
        runCalls.push(url);
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              call: "stand_aside",
              alert_type: "context_update",
              trade_status: "not_valid",
              confidence: null,
              regime: "range",
              direction_bias: "none",
              why: "still no clean setup",
              current_close: 1820.5,
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              generated_at: new Date().toISOString(),
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
              latest_call: "R_75 stand_aside",
              alert_count: 0,
              suppressed_context_count: 0,
              transport_event_count: 0,
              latest_transport_event: "steady",
              latest_transport_reason: "test route",
              backend_status: "live_bridge_ready",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/prop-profiles/current")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              profile: "deriv_2step_funded",
              startingBalance: 5000,
              currentBalance: 5000,
              currentEquity: 5000,
              todaysRealizedLoss: 0,
              todaysFloatingLossExposure: 0,
              highImpactNewsLockout: false,
              telemetry: { status: "live_unavailable", message: "no" },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/calls/guardian")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              guardian_state: "forming",
              guardian_reason: "Setup still forming",
              current_close: 1816.2,
              generated_at: staleGeneratedAt,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/intelligence")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              market_intelligence: null,
              evidence_summary: null,
              market_thesis: null,
              confidence_breakdown: null,
              trade_plan: null,
              risk_assessment: null,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<WorkspaceHarness />);

    // The stale plan renders instantly and — because call_age_seconds is
    // null — no refresh happens on its own (the old timers are dead).
    await waitFor(() => {
      const currentCall = JSON.parse(
        screen.getByTestId("current-call").textContent ?? "null",
      ) as Record<string, unknown> | null;
      expect(currentCall?.current_close).toBe(1816.2);
    });
    expect(runCalls.length).toBe(0);

    // A live R_75 tick arrives: the plan is 10 minutes old, so the
    // tick-driven freshness path silently re-reads the engine.
    const es = MockEventSource.instances[0];
    expect(es).toBeTruthy();
    es.emit({
      type: "tick",
      symbol: "R_75",
      tick: { epoch: Math.floor(Date.now() / 1000), price: 1820.5 },
    });

    await waitFor(() => expect(runCalls.length).toBe(1));
  });
});
