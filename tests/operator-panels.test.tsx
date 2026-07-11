/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PropCompliancePanel } from "../src/components/operator/prop-compliance-panel";
import { TradeInstructionPanel } from "../src/components/operator/trade-instruction-panel";

afterEach(() => {
  cleanup();
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

  it("shows execution levels only after the setup is confirmed", () => {
    render(
      <TradeInstructionPanel
        call={{
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
          guardian_reason: "Directional thesis is armed, but confirmation has not arrived yet.",
          generated_at: "2026-07-11T03:15:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
        guardianStatus={{
          symbol: "R_100",
          guardian_state: "confirmed",
          guardian_reason: "Buy confirmation received from improving short-term acceptance.",
          current_close: 459.9,
          generated_at: "2026-07-11T03:15:05.000Z",
        }}
      />,
    );

    expect(screen.getByText(/confirmed and ready/i)).toBeInTheDocument();
    expect(screen.getByText("459.6")).toBeInTheDocument();
    expect(screen.getByText("458.2")).toBeInTheDocument();
    expect(screen.getByText("462.2")).toBeInTheDocument();
    expect(
      screen.queryByText(/entry, stop, and target stay hidden until the setup is confirmed/i),
    ).not.toBeInTheDocument();
  });

  it("keeps execution levels hidden while a setup is only armed", () => {
    render(
      <TradeInstructionPanel
        call={{
          symbol: "R_100",
          call: "buy_candidate",
          alert_type: "setup_candidate",
          trade_status: "valid",
          confidence: 0.7,
          regime: "trend_up",
          direction_bias: "buy",
          why: "buyers briefly reclaimed control but the setup is not confirmed yet",
          wait_for: "wait for a clean bullish continuation close",
          decision_summary: "buy thesis present",
          entry_area: "around 459.6",
          stop_area: "below 458.2",
          target_area: "toward 462.2",
          entry: 459.6,
          stop_loss: 458.2,
          take_profit: 462.2,
          reward_risk: 2,
          current_close: 459.74,
          guardian_state: "armed",
          guardian_reason:
            "Directional thesis is armed, but persistence is still too weak for confirmation.",
          generated_at: "2026-07-11T04:10:00.000Z",
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

    expect(screen.queryByText(/^entry$/i)).not.toBeInTheDocument();
    expect(screen.getByText(/do not use the old entry levels/i)).toBeInTheDocument();
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
