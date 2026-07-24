/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PrimaryCallPanel } from "../src/components/operator/primary-call-panel";
import { PropCompliancePanel } from "../src/components/operator/prop-compliance-panel";
import { TradeInstructionPanel } from "../src/components/operator/trade-instruction-panel";
import { ConnectionStatus } from "../src/components/operator/connection-status";
import { HealthDashboard } from "../src/components/operator/health-dashboard";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TradeInstructionPanel", () => {
  it("explains that execution levels are unavailable when no trade is active", () => {
    render(
      <TradeInstructionPanel
        call={{
          symbol: "R_100",
          call: "stand_aside",
          alert_type: "context_update",
          trade_status: "not_valid",
          confidence: 0.54,
          regime: "range",
          direction_bias: "none",
          why: "current movement is active but not a clean setup yet",
          wait_for:
            "wait for confidence above threshold and cleaner directional agreement",
          decision_summary: null,
          entry_area: null,
          stop_area: null,
          target_area: null,
          entry: null,
          stop_loss: null,
          take_profit: null,
          reward_risk: null,
          current_close: 51190.5,
          guardian_state: "forming",
          guardian_reason: "Directional thesis is not yet armed.",
          generated_at: "2026-07-09T23:00:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={null}
      />,
    );

    expect(screen.getByText(/setup status/i)).toBeInTheDocument();
    expect(screen.getByText(/setup still forming/i)).toBeInTheDocument();
    expect(
      screen.getByText(/entry, stop, and target stay hidden until the setup is confirmed/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/do not enter yet\. the setup is still forming, so stay patient\./i),
    ).toBeInTheDocument();
    expect(screen.queryByText("N/A")).not.toBeInTheDocument();
  });

  it("shows execution levels for actionable setups with a caution label", () => {
    render(
      <TradeInstructionPanel
        call={{
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
          generated_at: "2026-07-11T22:00:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={null}
      />,
    );

    expect(screen.getAllByText(/actionable with caution/i).length).toBeGreaterThan(0);
    expect(screen.getByText("53,074.2")).toBeInTheDocument();
    expect(screen.getByText("53,173.2")).toBeInTheDocument();
    expect(screen.getByText("52,886.2")).toBeInTheDocument();
    expect(screen.getByText(/enter now only if/i)).toBeInTheDocument();
  });

  it("shows primary target as the main target and thesis invalidation separately", () => {
    render(
      <TradeInstructionPanel
        call={{
          symbol: "R_100",
          call: "buy_candidate",
          alert_type: "setup_candidate",
          trade_status: "valid",
          confidence: 0.72,
          regime: "trend_up",
          direction_bias: "buy",
          why: "buyers defended the intraday pullback and can press higher",
          wait_for:
            "wait for the 5m trigger to confirm, then manage toward the next-hour objective",
          decision_summary: "buy setup actionable with a realistic intraday objective",
          entry_area: "around 51,234.6",
          stop_area: "below 51,188.2",
          target_area: "toward 51,326.4",
          entry: 51234.6,
          stop_loss: 51188.2,
          take_profit: 51326.4,
          execution_stop: 51188.2,
          thesis_invalidation: 51092.8,
          primary_target: 51326.4,
          extended_target: 51382.6,
          hold_horizon_minutes: 60,
          reward_risk: 2,
          current_close: 51240.1,
          guardian_state: "actionable",
          guardian_reason: "The setup is actionable with caution.",
          invalidates_if: "a 5m close back below the reclaimed continuation shelf",
          call_age_seconds: 3,
          generated_at: "2026-07-12T12:00:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={null}
      />,
    );

    expect(screen.getByText("Target", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Primary target", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Stop", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Execution stop", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Invalidation", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Thesis invalidation")).not.toBeInTheDocument();
  });

  it("marks failing setups as stale and blocks the old execution plan", () => {
    render(
      <TradeInstructionPanel
        call={{
          symbol: "R_75",
          call: "buy_candidate",
          alert_type: "setup_candidate",
          trade_status: "valid",
          confidence: 0.7,
          regime: "trend_up",
          direction_bias: "buy",
          why: "buyers briefly reclaimed control but the setup is deteriorating",
          wait_for: "wait for a clean bullish continuation close",
          decision_summary: "buy thesis present",
          entry_area: "around 459.6",
          stop_area: "below 458.2",
          target_area: "toward 462.2",
          entry: 459.6,
          stop_loss: 458.2,
          take_profit: 462.2,
          reward_risk: 2,
          current_close: 459.1,
          guardian_state: "failing",
          guardian_reason: "The setup is deteriorating and the old plan is no longer fresh.",
          invalidates_if: "price loses the reclaimed shelf",
          call_age_seconds: 14,
          generated_at: "2026-07-11T22:04:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={null}
      />,
    );

    expect(screen.getAllByText(/plan is losing strength/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/do not use the old entry levels/i)).toBeInTheDocument();
    expect(
      screen.getByText(/do not execute the old plan until you refresh the call/i),
    ).toBeInTheDocument();
  });

  it("blocks cancelled setups from being executed", () => {
    render(
      <TradeInstructionPanel
        call={{
          symbol: "R_75",
          call: "sell_candidate",
          alert_type: "setup_candidate",
          trade_status: "valid",
          confidence: 0.61,
          regime: "range",
          direction_bias: "sell",
          why: "sellers lost control of the rejection shelf",
          wait_for: "wait for a fresh bearish continuation close",
          decision_summary: "sell thesis no longer valid",
          entry_area: "around 53074.2",
          stop_area: "above 53173.2",
          target_area: "toward 52886.2",
          entry: 53074.2,
          stop_loss: 53173.2,
          take_profit: 52886.2,
          reward_risk: 1.9,
          current_close: 53192.4,
          guardian_state: "cancelled",
          guardian_reason: "The original trade thesis is broken and should not be used.",
          invalidates_if: "price closes back above the rejection shelf",
          call_age_seconds: 19,
          generated_at: "2026-07-11T22:05:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={null}
      />,
    );

    expect(screen.getAllByText(/setup cancelled/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/do not execute this plan\. the original setup is cancelled\./i),
    ).toBeInTheDocument();
  });
});

describe("PrimaryCallPanel", () => {
  it("uses next-hour action language for intraday calls", () => {
    render(
      <PrimaryCallPanel
        call={{
          symbol: "R_100",
          call: "buy_candidate",
          alert_type: "setup_candidate",
          trade_status: "valid",
          confidence: 0.72,
          regime: "trend_up",
          direction_bias: "buy",
          why: "buyers defended the intraday pullback and can press higher",
          wait_for:
            "wait for the 5m trigger to confirm, then manage toward the next-hour objective",
          decision_summary: "buy setup actionable with a realistic intraday objective",
          entry_area: "around 51,234.6",
          stop_area: "below 51,188.2",
          target_area: "toward 51,326.4",
          entry: 51234.6,
          stop_loss: 51188.2,
          take_profit: 51326.4,
          execution_stop: 51188.2,
          thesis_invalidation: 51092.8,
          primary_target: 51326.4,
          extended_target: 51382.6,
          hold_horizon_minutes: 60,
          reward_risk: 2,
          current_close: 51240.1,
          guardian_state: "actionable",
          guardian_reason: "The setup is actionable with caution.",
          invalidates_if: "a 5m close back below the reclaimed continuation shelf",
          call_age_seconds: 3,
          generated_at: "2026-07-12T12:00:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={null}
        loading={false}
      />,
    );

    expect(screen.getByText(/next hour/i)).toBeInTheDocument();
    expect(screen.getByText(/5m close/i)).toBeInTheDocument();
  });
});

describe("PropCompliancePanel", () => {
  it("uses plain language when no prop trade is active", () => {
    render(
      <PropCompliancePanel
        profile={{
          profile: "blueberry_2step_funded",
          startingBalance: 100000,
          currentBalance: 100200,
          currentEquity: 100100,
          todaysRealizedLoss: 0,
          todaysFloatingLossExposure: 0,
          highImpactNewsLockout: false,
        }}
        call={{
          symbol: "R_100",
          call: "stand_aside",
          alert_type: "context_update",
          trade_status: "not_valid",
          confidence: 0.54,
          regime: "range",
          direction_bias: "none",
          why: "current movement is active but not a clean setup yet",
          wait_for:
            "wait for confidence above threshold and cleaner directional agreement",
          decision_summary: null,
          entry_area: null,
          stop_area: null,
          target_area: null,
          entry: null,
          stop_loss: null,
          take_profit: null,
          reward_risk: null,
          current_close: 51190.5,
          guardian_state: "forming",
          guardian_reason: "Directional thesis is not yet armed.",
          generated_at: "2026-07-09T23:00:00.000Z",
          account_mode: "prop_firm",
          prop_compliance: "allowed",
          prop_adjusted_risk: 0,
          prop_block_reason: null,
          prop_remaining_daily_buffer: 5000,
          prop_remaining_overall_buffer: 10100,
        }}
      />,
    );

    expect(screen.getByText(/no trade active/i)).toBeInTheDocument();
    expect(screen.getAllByText(/daily loss room left/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/total drawdown room left/i).length).toBeGreaterThan(0);
  });
});

describe("ConnectionStatus", () => {
  it("shows a loading indicator when no initialData is provided and no fetcher resolves", () => {
    // Never-resolving fetcher keeps the component in loading state
    const neverResolve = () => new Promise<never>(() => {});

    render(<ConnectionStatus statusFetcher={neverResolve} />);

    expect(screen.getAllByText(/loading/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/loading/i)[0].closest("div")?.textContent).toContain("Loading");
  });

  it("shows an error state when the fetcher rejects", async () => {
    const rejectingFetcher = () => Promise.reject(new Error("Network error"));

    render(<ConnectionStatus statusFetcher={rejectingFetcher} />);

    expect(await screen.findByText(/status unavailable/i)).toBeInTheDocument();
  });

  it("renders MT5 connected state with CSV ticks, warmup, and engine version via initialData", () => {
    const mockData = {
      mt5_configured: true,
      mt5_process_running: true,
      engine_root_configured: true,
      csv_ticks: { R_75: 121164, R_100: 245223 },
      last_warmup_at: new Date(Date.now() - 120000).toISOString(),
      engine_bridge_version: 1,
      engine_version: "0.1.0",
      mt5_last_error: null,
    };

    render(<ConnectionStatus initialData={mockData} />);

    expect(screen.getByText(/connected/i)).toBeInTheDocument();
    expect(screen.getAllByText(/mt5:/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/366,387 ticks/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/v75: 121,164/i)).toBeInTheDocument();
    expect(screen.getByText(/v100: 245,223/i)).toBeInTheDocument();
    expect(screen.getByText(/2m ago/i)).toBeInTheDocument();
    expect(screen.getAllByText(/v0\.1\.0/i).length).toBeGreaterThan(0);

    // Test button should be visible when MT5 is configured
    const testBtn = screen.getByRole("button", { name: /test mt5 connection/i });
    expect(testBtn).toBeInTheDocument();
    expect(testBtn).not.toBeDisabled();
  });

  it("shows MT5 Off and hides the test button when mt5 is not configured via initialData", () => {
    const mockData = {
      mt5_configured: false,
      mt5_process_running: false,
      engine_root_configured: false,
      csv_ticks: { R_75: 0, R_100: 0 },
      last_warmup_at: null,
      engine_bridge_version: 1,
      engine_version: null,
      mt5_last_error: null,
    };

    render(<ConnectionStatus initialData={mockData} />);

    expect(screen.getByText(/off/i)).toBeInTheDocument();
    expect(screen.getAllByText(/mt5:/i).length).toBeGreaterThan(0);

    // CSV should show 0 ticks
    expect(screen.getByText(/0 ticks/i)).toBeInTheDocument();

    // Warmup should read "Never" since last_warmup_at is null
    expect(screen.getByText(/never/i)).toBeInTheDocument();

    // Test button should NOT render when MT5 is not configured
    expect(
      screen.queryByRole("button", { name: /test mt5 connection/i }),
    ).not.toBeInTheDocument();
  });

  it("shows MT5 Error when configured but not running and mt5_last_error is set via initialData", () => {
    const mockData = {
      mt5_configured: true,
      mt5_process_running: false,
      engine_root_configured: true,
      csv_ticks: { R_75: 50000, R_100: 75000 },
      last_warmup_at: null,
      engine_bridge_version: 1,
      engine_version: null,
      mt5_last_error: "terminal64.exe not responding",
    };

    render(<ConnectionStatus initialData={mockData} />);

    expect(screen.getByText(/error/i)).toBeInTheDocument();
    expect(screen.getByText(/terminal64\.exe not responding/i)).toBeInTheDocument();

    // Test button still renders — credentials are configured even though process is down
    expect(
      screen.getByRole("button", { name: /test mt5 connection/i }),
    ).toBeInTheDocument();
  });

  it("shows MT5 Not running when configured but process is not detected and no error is set via initialData", () => {
    const mockData = {
      mt5_configured: true,
      mt5_process_running: false,
      engine_root_configured: true,
      csv_ticks: { R_75: 100, R_100: 200 },
      last_warmup_at: null,
      engine_bridge_version: 1,
      engine_version: null,
      mt5_last_error: null,
    };

    render(<ConnectionStatus initialData={mockData} />);

    expect(screen.getByText(/not running/i)).toBeInTheDocument();
  });

  it("renders without engine version when engine_version is null via initialData", () => {
    const mockData = {
      mt5_configured: true,
      mt5_process_running: true,
      engine_root_configured: true,
      csv_ticks: { R_75: 100, R_100: 200 },
      last_warmup_at: new Date(Date.now() + 1000).toISOString(),
      engine_bridge_version: 1,
      engine_version: null,
      mt5_last_error: null,
    };

    render(<ConnectionStatus initialData={mockData} />);

    expect(screen.getByText(/just now/i)).toBeInTheDocument();
    expect(screen.queryByText(/engine:/i)).not.toBeInTheDocument();
  });

  it("disables the Test button while a test is running via custom testFetcher", async () => {
    const mockData = {
      mt5_configured: true,
      mt5_process_running: false,
      engine_root_configured: true,
      csv_ticks: { R_75: 100, R_100: 200 },
      last_warmup_at: null,
      engine_bridge_version: 1,
      engine_version: null,
      mt5_last_error: null,
    };

    // Never-resolving test fetcher keeps testing state active
    const neverResolveTest = () => new Promise<never>(() => {});

    render(
      <ConnectionStatus
        initialData={mockData}
        testFetcher={neverResolveTest}
      />,
    );

    const testBtn = screen.getByRole("button", { name: /test mt5 connection/i });
    expect(testBtn).toBeInTheDocument();

    // Click the Test button to trigger a test
    fireEvent.click(testBtn);

    // After clicking, the button should show "Testing…" and be disabled
    expect(await screen.findByText(/testing/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /test mt5 connection/i })).toBeDisabled();
  });
});

describe("HealthDashboard", () => {
  it("shows a pulsing dot while the initial fetch is in flight", () => {
    const neverResolve = () => new Promise<never>(() => {});

    render(<HealthDashboard healthFetcher={neverResolve} />);

    expect(screen.getAllByText(/system health/i).length).toBeGreaterThan(0);
    // Expanded content should not be visible on initial render
    expect(screen.queryByText(/mt5 connection latency/i)).not.toBeInTheDocument();
  });

  it("shows a red dot when the fetch fails", async () => {
    const rejectingFetcher = () => Promise.reject(new Error("Network error"));

    render(<HealthDashboard healthFetcher={rejectingFetcher} />);

    expect(await screen.findAllByText(/system health/i)).toHaveLength(1);
  });

  it("shows a collapsed summary with MT5 timing and tick velocity via initialData", () => {
    const mockMetrics = {
      mt5_configured: true,
      mt5_server: "BlueberryMarkets-Demo",
      mt5_error: null,
      mt5_timing: { init_ms: 12, login_ms: 9, total_ms: 21, timestamp: Date.now() / 1000 },
      csv_size_bytes: 2048000,
      csv_ticks: { R_75: 180000, R_100: 186387 },
      engine_version: "0.1.0",
      timestamp: Date.now(),
      warmup_cache_hits: { R_75: 0, R_100: 0 },
      warmup_cache_misses: { R_75: 0, R_100: 0 },
      csv_cache_hit_ratio: 0.95,
      pipeline_diagnostics: {
        lastGuardianReason: null,
        lastStderr: null,
        lastRetryCount: 0,
        lastError: null,
        lastUpdatedAt: null,
        staleDataSince: null,
      },
    };

    render(<HealthDashboard initialData={mockMetrics} />);

    // The collapsed header should show system health, MT5 timing, and velocity
    expect(screen.getAllByText(/system health/i)).toHaveLength(1);
    expect(screen.getByText(/21 ms mt5/i)).toBeInTheDocument();

    // Expanded content should NOT be visible yet
    expect(screen.queryByText(/mt5 connection latency/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/csv tick pipeline/i)).not.toBeInTheDocument();
  });

  it("expands to show MT5 timing gauges, CSV pipeline, and engine info via initialData", () => {
    const mockMetrics = {
      mt5_configured: true,
      mt5_server: "BlueberryMarkets-Demo",
      mt5_error: null,
      mt5_timing: { init_ms: 15, login_ms: 10, total_ms: 25, timestamp: Date.now() / 1000 },
      csv_size_bytes: 1048576,
      csv_ticks: { R_75: 180000, R_100: 186387 },
      engine_version: "0.1.0",
      timestamp: Date.now(),
      warmup_cache_hits: { R_75: 0, R_100: 0 },
      warmup_cache_misses: { R_75: 0, R_100: 0 },
      csv_cache_hit_ratio: 0.95,
      pipeline_diagnostics: {
        lastGuardianReason: null,
        lastStderr: null,
        lastRetryCount: 0,
        lastError: null,
        lastUpdatedAt: null,
        staleDataSince: null,
      },
    };

    render(<HealthDashboard initialData={mockMetrics} />);

    // Data is rendered immediately — no async wait needed
    expect(screen.getAllByText(/system health/i)).toHaveLength(1);

    // Click the toggle button to expand
    const toggleBtn = screen.getByRole("button", { name: /toggle health dashboard/i });
    fireEvent.click(toggleBtn);

    // Expanded content should now be visible
    expect(screen.getByText(/mt5 connection latency/i)).toBeInTheDocument();
    expect(screen.getByText(/csv tick pipeline/i)).toBeInTheDocument();

    // MT5 timing gauges
    expect(screen.getAllByText(/initialize/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/login/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/total/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/15 ms/i)).toBeInTheDocument();
    expect(screen.getByText(/10 ms/i)).toBeInTheDocument();
    expect(screen.getByText(/25 ms/i)).toBeInTheDocument();

    // CSV pipeline info
    expect(screen.getAllByText(/366,387 ticks/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/1\.0 mb/i)).toBeInTheDocument();

    // Engine info
    expect(screen.getAllByText(/v0\.1\.0/i).length).toBeGreaterThan(0);
  });

  it("shows a fallback message when MT5 timing data is not yet available via initialData", () => {
    const mockMetrics = {
      mt5_configured: true,
      mt5_server: "BlueberryMarkets-Demo",
      mt5_error: null,
      mt5_timing: null,
      csv_size_bytes: 500000,
      csv_ticks: { R_75: 50000, R_100: 50000 },
      engine_version: "0.1.0",
      timestamp: Date.now(),
      warmup_cache_hits: { R_75: 0, R_100: 0 },
      warmup_cache_misses: { R_75: 0, R_100: 0 },
    };

    render(<HealthDashboard initialData={mockMetrics} />);

    expect(screen.getAllByText(/system health/i)).toHaveLength(1);

    // Click to expand
    const toggleBtn = screen.getByRole("button", { name: /toggle health dashboard/i });
    fireEvent.click(toggleBtn);

    // Should show the fallback message instead of timing gauges
    expect(
      screen.getByText(/run a manual call to populate/i),
    ).toBeInTheDocument();
  });

  it("shows MT5 error message in the expanded view when an mt5 error exists via initialData", () => {
    const mockMetrics = {
      mt5_configured: true,
      mt5_server: "BlueberryMarkets-Demo",
      mt5_error: "Connection refused",
      mt5_timing: null,
      csv_size_bytes: 100000,
      csv_ticks: { R_75: 2500, R_100: 2500 },
      engine_version: null,
      timestamp: Date.now(),
      warmup_cache_hits: { R_75: 0, R_100: 0 },
      warmup_cache_misses: { R_75: 0, R_100: 0 },
    };

    render(<HealthDashboard initialData={mockMetrics} />);

    expect(screen.getAllByText(/system health/i)).toHaveLength(1);

    // Click to expand
    const toggleBtn = screen.getByRole("button", { name: /toggle health dashboard/i });
    fireEvent.click(toggleBtn);

    // Should show the MT5 error
    expect(screen.getByText(/connection refused/i)).toBeInTheDocument();
  });

  it("shows MT5 not configured message when mt5_configured is false via initialData", () => {
    const mockMetrics = {
      mt5_configured: false,
      mt5_server: null,
      mt5_error: null,
      mt5_timing: null,
      csv_size_bytes: 0,
      csv_ticks: { R_75: 0, R_100: 0 },
      engine_version: null,
      timestamp: Date.now(),
      warmup_cache_hits: { R_75: 0, R_100: 0 },
      warmup_cache_misses: { R_75: 0, R_100: 0 },
    };

    render(<HealthDashboard initialData={mockMetrics} />);

    expect(screen.getAllByText(/system health/i)).toHaveLength(1);

    // Click to expand
    const toggleBtn = screen.getByRole("button", { name: /toggle health dashboard/i });
    fireEvent.click(toggleBtn);

    // Should show the not-configured message
    expect(screen.getByText(/mt5 is not configured/i)).toBeInTheDocument();
  });

  it("shows MT5 dash and empty velocity when no timing data is available and collapsed via initialData", () => {
    const mockMetrics = {
      mt5_configured: true,
      mt5_server: null,
      mt5_error: null,
      mt5_timing: null,
      csv_size_bytes: 0,
      csv_ticks: { R_75: 0, R_100: 0 },
      engine_version: null,
      timestamp: Date.now(),
      warmup_cache_hits: { R_75: 0, R_100: 0 },
      warmup_cache_misses: { R_75: 0, R_100: 0 },
      csv_cache_hit_ratio: 0,
      pipeline_diagnostics: {
        lastGuardianReason: null,
        lastStderr: null,
        lastRetryCount: 0,
        lastError: null,
        lastUpdatedAt: null,
        staleDataSince: null,
      },
    };

    render(<HealthDashboard initialData={mockMetrics} />);

    // The collapsed header summary should show "MT5 — · —" (no timing, no velocity)
    expect(screen.getAllByText(/system health/i)).toHaveLength(1);
    expect(screen.getByText(/mt5 —/i)).toBeInTheDocument();
  });
});
