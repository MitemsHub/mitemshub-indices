/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperatorShell } from "../src/components/operator/operator-shell";

// JSDOM doesn't implement matchMedia — mock it so useMediaQuery("(min-width: 768px)")
// returns true (desktop viewport) across all shell tests.
// Must be beforeEach (not beforeAll) because the afterEach hook calls
// vi.restoreAllMocks(), which would restore the original matchMedia after
// the first test and break the remaining tests.
function mockDesktopMatchMedia() {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    media: "(min-width: 768px)",
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  });
}

beforeEach(() => {
  mockDesktopMatchMedia();
});

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

  if (url.includes("/api/system/pipeline-diagnostics")) {
    return Promise.resolve(
      new Response(
        JSON.stringify({
          lastGuardianReason: null,
          lastStderr: null,
          lastRetryCount: 0,
          lastError: null,
          lastUpdatedAt: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
  }

  return null;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("OperatorShell", () => {
  it("loads recent history and live status from the backend routes on startup", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);

      if (url.includes("/api/history")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              history: [
                {
                  symbol: "R_100",
                  call: "sell_candidate",
                  alert_type: "setup_candidate",
                  trade_status: "valid",
                  confidence: 0.64,
                  regime: "trend_down",
                  direction_bias: "sell",
                  why: "journal-backed sell decision",
                  wait_for: "wait for a clean bearish continuation close",
                  decision_summary: "sell setup ready",
                  entry_area: "around 450.0",
                  stop_area: "above 452.0",
                  target_area: "toward 446.0",
                  entry: 450,
                  stop_loss: 452,
                  take_profit: 446,
                  reward_risk: 2,
                  current_close: 451,
                  generated_at: "2026-07-09T23:10:00.000Z",
                  account_mode: "own_account",
                  prop_compliance: null,
                  prop_adjusted_risk: null,
                  prop_block_reason: null,
                  prop_remaining_daily_buffer: null,
                  prop_remaining_overall_buffer: null,
                  guardian_state: "actionable",
                  guardian_reason: "The setup is actionable with caution.",
                },
              ],
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
              alert_count: 1,
              suppressed_context_count: 0,
              transport_event_count: 0,
              latest_transport_event: "steady",
              latest_transport_reason: "live bridge connected",
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

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    expect(await screen.findByText(/journal-backed sell decision/i)).toBeInTheDocument();
    expect((await screen.findAllByText(/^ready$/i)).length).toBeGreaterThan(0);
  });

  it("opens the prop connection prompt before switching modes", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));

    expect(
      screen.getByRole("dialog", { name: /prop firm connection/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/leave these fields blank to use your own account connection/i),
    ).toBeInTheDocument();
  });

  it("allows blank submit and switches to prop mode using own-account fallback", async () => {
    const user = userEvent.setup();

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

      if (url.includes("/api/prop-profiles/current") && init?.method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              profile: "blueberry_2step_funded",
              startingBalance: 100000,
              currentBalance: 100200,
              currentEquity: 100150,
              todaysRealizedLoss: 0,
              todaysFloatingLossExposure: 0,
              highImpactNewsLockout: false,
              telemetry: {
                status: "own_account_fallback",
                message: "Using own-account fallback",
              },
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

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));
    await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

    expect(screen.getByText(/using own-account fallback/i)).toBeInTheDocument();
  });

  it("blocks partial manual input instead of silently falling back", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));
    await user.type(screen.getByLabelText(/server/i), "PropServer");
    await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

    expect(
      screen.getByText(/enter login and password or leave all three fields blank/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: /prop firm connection/i }),
    ).toBeInTheDocument();
  });

  it("switches to prop-firm mode and shows the compliance panel", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));
    await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

    expect(screen.getByText(/blueberry 2-step funded/i)).toBeInTheDocument();
    expect(screen.getAllByText(/compliance status/i).length).toBeGreaterThan(0);
  });

  it("reveals a formal prop policy overlay in prop mode", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));
    await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

    expect(screen.getByText(/prop protection/i)).toBeInTheDocument();
    expect(screen.getByText(/^compliance status$/i)).toBeInTheDocument();
    expect(screen.getAllByText(/daily loss room left/i).length).toBeGreaterThan(0);
  });

  it("runs a fresh R_100 call and shows the primary call panel", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/history")) {
        return Promise.resolve(new Response(JSON.stringify({ history: [] }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url.includes("/api/system/status")) {
        return Promise.resolve(new Response(JSON.stringify({ latest_call: "R_100 stand_aside", alert_count: 0, suppressed_context_count: 0, transport_event_count: 0, latest_transport_event: "steady", latest_transport_reason: "test route", backend_status: "live_bridge_ready", journal_status: "fresh" }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url.includes("/api/calls/run") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({
          symbol: "R_100", call: "buy_candidate", alert_type: "setup_candidate", trade_status: "valid",
          confidence: 0.72, regime: "trend_up", direction_bias: "buy",
          why: "buyers defended the pullback", wait_for: "wait for a clean bullish close",
          decision_summary: "buy setup ready", entry_area: "around 460", stop_area: "below 458", target_area: "toward 463",
          entry: 460, stop_loss: 458, take_profit: 463, reward_risk: 1.5,
          current_close: 460, guardian_state: "actionable", guardian_reason: "Setup is actionable with caution.",
          generated_at: "2026-07-11T04:00:00.000Z", account_mode: "own_account",
          prop_compliance: null, prop_adjusted_risk: null, prop_block_reason: null,
          prop_remaining_daily_buffer: null, prop_remaining_overall_buffer: null,
        }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect(
      await screen.findByRole("heading", {
        name: /buy setup ready|sell setup ready|no trade yet/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/what to do now/i).length).toBeGreaterThan(0);
  });

  it("renders the main decision stage as the primary focal surface", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/history")) {
        return Promise.resolve(new Response(JSON.stringify({ history: [] }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url.includes("/api/system/status")) {
        return Promise.resolve(new Response(JSON.stringify({ latest_call: "R_100 stand_aside", alert_count: 0, suppressed_context_count: 0, transport_event_count: 0, latest_transport_event: "steady", latest_transport_reason: "test route", backend_status: "live_bridge_ready", journal_status: "fresh" }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url.includes("/api/calls/run") && init?.method === "POST") {
        return Promise.resolve(new Response(JSON.stringify({
          symbol: "R_100", call: "sell_candidate", alert_type: "setup_candidate", trade_status: "valid",
          confidence: 0.62, regime: "range", direction_bias: "sell",
          why: "sellers still in control", wait_for: "a fresh bearish close",
          decision_summary: "sell setup actionable", entry_area: "around 450", stop_area: "above 452", target_area: "toward 446",
          entry: 450, stop_loss: 452, take_profit: 446, reward_risk: 2,
          current_close: 450, guardian_state: "actionable", guardian_reason: "Setup is actionable with caution.",
          generated_at: "2026-07-11T04:00:00.000Z", account_mode: "own_account",
          prop_compliance: null, prop_adjusted_risk: null, prop_block_reason: null,
          prop_remaining_daily_buffer: null, prop_remaining_overall_buffer: null,
        }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect((await screen.findAllByText(/^trade plan$/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/market picture/i)).toBeInTheDocument();
    expect(screen.getAllByText(/what needs to happen next/i).length).toBeGreaterThan(0);
  });

  it("shows an elapsed seconds counter while pulling a live market plan", async () => {
    vi.useFakeTimers();

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const supportResponse = buildSupportResponse(url);

      if (supportResponse) {
        return supportResponse;
      }

      if (url.includes("/api/calls/run") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          setTimeout(() => {
            resolve(
              new Response(
                JSON.stringify({
                  symbol: "R_100",
                  call: "stand_aside",
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
                  current_close: null,
                  guardian_state: "unavailable",
                  guardian_reason:
                    "Live market read unavailable. The app could not confirm a fresh price from the bridge.",
                  generated_at: "2026-07-11T04:30:00.000Z",
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
          }, 2200);
        });
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    fireEvent.click(screen.getByRole("button", { name: /r_100/i }));
    await Promise.resolve();

    expect(screen.getAllByText(/Pulling data|Analyzing market/i).length).toBeGreaterThan(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(screen.getByText("01s")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.getAllByText(/^ready$/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("01s")).not.toBeInTheDocument();
  });

  it("shows an explicit live-read unavailable message instead of fake execution levels", async () => {
    const user = userEvent.setup();

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

      if (url.includes("/api/calls/run") && init?.method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_100",
              call: "stand_aside",
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
              current_close: null,
              guardian_state: "unavailable",
              guardian_reason:
                "Live market read unavailable. The app could not confirm a fresh price from the bridge.",
              generated_at: "2026-07-11T02:25:00.000Z",
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

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect((await screen.findAllByText(/live market read unavailable/i)).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/entry, stop, and target stay hidden until the setup is confirmed/i),
    ).toBeInTheDocument();
  });

  it("shows actionable execution levels and freshness metadata from a fresh live call", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "setInterval").mockImplementation((handler) => {
      if (typeof handler === "function") {
        void handler();
      }

      return 1 as unknown as ReturnType<typeof setInterval>;
    });

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const supportResponse = buildSupportResponse(url);

      if (supportResponse) {
        return supportResponse;
      }

      if (url.includes("/api/calls/run") && init?.method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              symbol: "R_75",
              call: "sell_candidate",
              alert_type: "setup_candidate",
              trade_status: "valid",
              confidence: 0.62,
              regime: "range",
              direction_bias: "sell",
              why: "sellers still control the upper rejection zone",
              wait_for: "a fresh bearish continuation close",
              decision_summary: "sell setup actionable; sellers still control the upper rejection zone",
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
              generated_at: "2026-07-11T03:15:00.000Z",
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
              symbol: "R_75",
              guardian_state: "actionable",
              guardian_reason: "The setup is actionable with caution.",
              current_close: 53074.2,
              generated_at: "2026-07-11T03:15:05.000Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_75/i }));
    expect(
      await screen.findByRole("heading", { name: /sell setup ready/i }),
    ).toBeInTheDocument();

    expect(screen.getAllByText(/actionable with caution/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/setup status/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("53,074.2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("53,173.2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("52,886.2").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Plan age|Call age/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2s old/i).length).toBeGreaterThan(0);
  });

  it("shows execution levels only after guardian state becomes confirmed", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "setInterval").mockImplementation((handler) => {
      if (typeof handler === "function") {
        void handler();
      }

      return 1 as unknown as ReturnType<typeof setInterval>;
    });

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const supportResponse = buildSupportResponse(url);

      if (supportResponse) {
        return supportResponse;
      }

      if (url.includes("/api/calls/run") && init?.method === "POST") {
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
              decision_summary: "buy thesis present",
              entry_area: "around 459.6",
              stop_area: "below 458.2",
              target_area: "toward 462.2",
              entry: 459.6,
              stop_loss: 458.2,
              take_profit: 462.2,
              reward_risk: 2,
              current_close: 459.7,
              guardian_state: "armed",
              guardian_reason:
                "Directional thesis is armed, but confirmation has not arrived yet.",
              generated_at: "2026-07-11T03:15:00.000Z",
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
              guardian_state: "confirmed",
              guardian_reason: "Buy confirmation received from improving short-term acceptance.",
              current_close: 459.9,
              generated_at: "2026-07-11T03:15:05.000Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));
    expect(
      await screen.findByRole("heading", { name: /buy setup ready/i }),
    ).toBeInTheDocument();

    expect(screen.getAllByText(/confirmed and ready/i).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/buy confirmation is in place and the setup is ready to trade/i)
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("459.6").length).toBeGreaterThan(0);
    expect(screen.getAllByText("458.2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("462.2").length).toBeGreaterThan(0);
  });

  it("reverses a confirmed setup back to failing and removes enter-now guidance", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "setInterval").mockImplementation((handler) => {
      if (typeof handler === "function") {
        void handler();
      }

      return 1 as unknown as ReturnType<typeof setInterval>;
    });

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      const supportResponse = buildSupportResponse(url);

      if (supportResponse) {
        return supportResponse;
      }

      if (url.includes("/api/calls/run") && init?.method === "POST") {
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
              decision_summary: "buy thesis present",
              entry_area: "around 459.6",
              stop_area: "below 458.2",
              target_area: "toward 462.2",
              entry: 459.6,
              stop_loss: 458.2,
              take_profit: 462.2,
              reward_risk: 2,
              current_close: 459.9,
              guardian_state: "confirmed",
              guardian_reason:
                "Buy confirmation received from improving short-term acceptance.",
              generated_at: "2026-07-11T03:15:00.000Z",
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
              guardian_state: "failing",
              guardian_reason: "The setup is deteriorating and the old plan is no longer fresh.",
              current_close: 459.3,
              generated_at: "2026-07-11T03:15:05.000Z",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));
    expect(
      await screen.findByRole("heading", { name: /buy setup ready/i }),
    ).toBeInTheDocument();

    expect(screen.getAllByText(/plan is losing strength/i).length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/the setup is deteriorating and the old plan is no longer fresh/i)
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/setup status/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/entry, stop, and target stay hidden until the setup is confirmed/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/do not use the old entry levels/i)).toBeInTheDocument();
    expect(screen.queryByText("459.6")).not.toBeInTheDocument();
    expect(screen.queryByText("458.2")).not.toBeInTheDocument();
    expect(screen.queryByText("462.2")).not.toBeInTheDocument();
    expect(
      screen.getByText(/do not execute the old plan until you refresh the call/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/enter now only if/i)).not.toBeInTheDocument();
  });

  it("sends the selected prop connection when running a symbol in prop mode", async () => {
    const user = userEvent.setup();
    let runPayload: Record<string, unknown> | null = null;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);

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
              startingBalance: 120000,
              currentBalance: 119900,
              currentEquity: 119850,
              todaysRealizedLoss: 100,
              todaysFloatingLossExposure: 50,
              highImpactNewsLockout: false,
              telemetry: {
                status: "live_confirmed",
                message: "Live prop check confirmed",
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url.includes("/api/calls/run")) {
        runPayload = JSON.parse(String(init?.body)) as Record<string, unknown>;

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
              decision_summary: "buy setup ready",
              entry_area: "around 500.0",
              stop_area: "below 496.0",
              target_area: "toward 510.0",
              entry: 500,
              stop_loss: 496,
              take_profit: 510,
              reward_risk: 2.5,
              current_close: 500,
              guardian_state: "actionable",
              guardian_reason: "The setup is actionable with caution.",
              generated_at: "2026-07-10T11:00:00.000Z",
              account_mode: "prop_firm",
              prop_compliance: "allowed",
              prop_adjusted_risk: 1,
              prop_block_reason: null,
              prop_remaining_daily_buffer: 4800,
              prop_remaining_overall_buffer: 9800,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /prop firm/i }));
    await user.type(screen.getByLabelText(/server/i), "PropServer");
    await user.type(screen.getByLabelText(/login/i), "222222");
    await user.type(screen.getByLabelText(/password/i), "prop-secret");
    await user.clear(screen.getByLabelText(/starting balance/i));
    await user.type(screen.getByLabelText(/starting balance/i), "120000");
    await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));
    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect(fetchSpy).toHaveBeenCalled();
    expect(
      await screen.findByRole("heading", { name: /buy setup ready/i }),
    ).toBeInTheDocument();
    expect(runPayload).toMatchObject({
      symbol: "R_100",
      account_mode: "prop_firm",
      prop_connection: {
        server: "PropServer",
        login: "222222",
        password: "prop-secret",
        terminalPath: null,
        startingBalance: 120000,
      },
    });
  });

  it("renders the backend-truth telemetry label above the prop panel", async () => {
    const user = userEvent.setup();

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

      if (url.includes("/api/prop-profiles/current") && init?.method === "POST") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              profile: "blueberry_2step_funded",
              startingBalance: 100000,
              currentBalance: 100200,
              currentEquity: 100150,
              todaysRealizedLoss: 0,
              todaysFloatingLossExposure: 0,
              highImpactNewsLockout: false,
              telemetry: {
                status: "own_account_fallback",
                message: "Using own-account fallback",
              },
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

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    render(<OperatorShell />);
    await user.click(screen.getByRole("button", { name: /prop firm/i }));
    await user.click(screen.getByRole("button", { name: /continue in prop mode/i }));

    expect(screen.getByText(/using own-account fallback/i)).toBeInTheDocument();
  });

  it("keeps symbol controls deterministic while a fresh call is pending in the redesigned shell", async () => {
    const user = userEvent.setup();
    let resolveFetch: ((value: Response) => void) | undefined;

    vi.spyOn(globalThis, "fetch").mockImplementation(
      (input) => {
        const url = String(input);

        if (url.includes("/api/calls/run")) {
          return new Promise<Response>((resolve) => {
            resolveFetch = resolve;
          });
        }

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
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
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
              }),
              {
                status: 200,
                headers: { "Content-Type": "application/json" },
              },
            ),
          );
        }

        return Promise.reject(new Error(`Unexpected fetch: ${url}`));
      },
    );

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_75/i }));

    expect(
      screen.getByRole("heading", { name: /live trade intelligence|get a live trade plan/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /what to do now/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /r_75/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /r_100/i })).toBeDisabled();
    expect(
      screen.getByText(/fetching the latest local market reading and trade plan/i),
    ).toBeInTheDocument();

    expect(screen.getByRole("main")).toHaveAttribute("aria-busy", "true");

    resolveFetch?.({ ok: false } as Response);

    expect(
      await screen.findByRole("heading", {
        name: /buy setup ready|sell setup ready|no trade yet/i,
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByText(/fetching the latest local market reading and trade plan/i),
      ).not.toBeInTheDocument(),
    );
  });
});
