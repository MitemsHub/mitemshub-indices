/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperatorShell } from "../src/components/operator/operator-shell";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
                  generated_at: "2026-07-09T23:10:00.000Z",
                  account_mode: "own_account",
                  prop_compliance: null,
                  prop_adjusted_risk: null,
                  prop_block_reason: null,
                  prop_remaining_daily_buffer: null,
                  prop_remaining_overall_buffer: null,
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
    expect(await screen.findByText(/live bridge ready/i)).toBeInTheDocument();
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
    expect(screen.getByText(/compliance status/i)).toBeInTheDocument();
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

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect(
      await screen.findByRole("heading", {
        name: /buy setup ready|sell setup ready|no trade yet/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/what to do now/i)).toBeInTheDocument();
  });

  it("renders the main decision stage as the primary focal surface", async () => {
    const user = userEvent.setup();

    render(<OperatorShell />);

    await user.click(screen.getByRole("button", { name: /r_100/i }));

    expect(await screen.findByText(/^trade plan$/i)).toBeInTheDocument();
    expect(screen.getByText(/market picture/i)).toBeInTheDocument();
    expect(screen.getByText(/what needs to happen next/i)).toBeInTheDocument();
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
      screen.getByRole("heading", { name: /get a live trade plan/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /what to do now/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /r_75/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /r_100/i })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(
      /fetching the latest local market reading and trade plan/i,
    );

    expect(screen.getByRole("main")).toHaveAttribute("aria-busy", "true");

    resolveFetch?.({ ok: false } as Response);

    expect(
      await screen.findByRole("heading", {
        name: /buy setup ready|sell setup ready|no trade yet/i,
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
  });
});
