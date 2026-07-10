/** @vitest-environment jsdom */

import React from "react";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PropCompliancePanel } from "../src/components/operator/prop-compliance-panel";
import { TradeInstructionPanel } from "../src/components/operator/trade-instruction-panel";

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
          generated_at: "2026-07-09T23:00:00.000Z",
          account_mode: "own_account",
          prop_compliance: null,
          prop_adjusted_risk: null,
          prop_block_reason: null,
          prop_remaining_daily_buffer: null,
          prop_remaining_overall_buffer: null,
        }}
      />,
    );

    expect(
      screen.getByText(/entry, stop, and target appear only when a trade is ready/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("N/A")).not.toBeInTheDocument();
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
