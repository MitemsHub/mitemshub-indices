import { describe, expect, it } from "vitest";
import {
  accountModeSchema,
  freshCallResponseSchema,
  guardianStateSchema,
  propComplianceSchema,
} from "../src/lib/contracts";
import { latestMockCall } from "../src/lib/mock-data";

describe("contracts", () => {
  it("accepts a fresh call response with prop compliance fields", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.66,
      regime: "trend_up",
      direction_bias: "buy",
      why: "trend continuation aligned with structure and regime",
      wait_for: "wait for a clean bullish continuation close",
      decision_summary:
        "buy setup valid; trend continuation aligned with structure and regime",
      entry_area: "around 51234.6",
      stop_area: "below 51188.2",
      target_area: "toward 51326.4",
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable with caution.",
      invalidates_if: "price closes back below the reclaimed shelf",
      call_age_seconds: 2,
      generated_at: "2026-07-09T12:00:00Z",
      account_mode: "prop_firm",
      prop_compliance: "allowed_with_adjustment",
      prop_adjusted_risk: 0.75,
      prop_block_reason: null,
      prop_remaining_daily_buffer: 3200,
      prop_remaining_overall_buffer: 8600,
    });

    expect(result.account_mode).toBe("prop_firm");
    expect(result.prop_compliance).toBe("allowed_with_adjustment");
  });

  it("accepts both own-account and prop-firm modes", () => {
    expect(accountModeSchema.parse("own_account")).toBe("own_account");
    expect(accountModeSchema.parse("prop_firm")).toBe("prop_firm");
  });

  it("accepts the defined prop compliance states", () => {
    expect(propComplianceSchema.parse("allowed")).toBe("allowed");
    expect(propComplianceSchema.parse("insufficient_account_state")).toBe(
      "insufficient_account_state",
    );
  });

  it("accepts the defined guardian lifecycle states", () => {
    expect(guardianStateSchema.parse("actionable")).toBe("actionable");
    expect(guardianStateSchema.parse("confirmed")).toBe("confirmed");
    expect(guardianStateSchema.parse("failing")).toBe("failing");
    expect(guardianStateSchema.parse("cancelled")).toBe("cancelled");
  });

  it("accepts actionable and failing live call states with freshness metadata", () => {
    const parsed = freshCallResponseSchema.parse({
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

    expect(parsed.guardian_state).toBe("actionable");
    expect(parsed.call_age_seconds).toBe(2);
  });

  it("accepts structure-led invalidation and decision summary fields", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.64,
      regime: "trend_up",
      direction_bias: "buy",
      why: "4H and 1H structure align bullishly",
      wait_for: "wait for a clean bullish continuation close",
      decision_summary:
        "4H bullish bias; 1H pullback held; 15m confirmed continuation",
      invalidates_if: "price closes back below the defended 1H shelf",
      entry_area: "around 53886.0",
      stop_area: "below 53779.1",
      target_area: "toward 54089.3",
      entry: 53886.0,
      stop_loss: 53779.1,
      take_profit: 54089.3,
      reward_risk: 1.9,
      current_close: 53886.0,
      guardian_state: "actionable",
      guardian_reason:
        "The setup is actionable, but live continuation still needs more persistence.",
      generated_at: new Date().toISOString(),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });

    expect(result.decision_summary).toMatch(/15m confirmed continuation/i);
    expect(result.invalidates_if).toMatch(/1H shelf/i);
  });

  it("accepts intraday execution geometry fields in the fresh call contract", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_100",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.64,
      regime: "trend_up",
      direction_bias: "buy",
      why: "4H and 1H structure align bullishly",
      wait_for: "wait for a clean bullish continuation close",
      decision_summary:
        "4H bullish bias; 1H pullback held; 15m confirmed continuation",
      invalidates_if: "price closes back below the defended 1H shelf",
      entry_area: "around 474.8",
      stop_area: "below 440.67",
      target_area: "toward 488.8",
      entry: 470.2,
      stop_loss: 474.8,
      take_profit: 488.8,
      reward_risk: 1.9,
      current_close: 475.1,
      guardian_state: "actionable",
      guardian_reason:
        "The setup is actionable, but live continuation still needs more persistence.",
      execution_stop: 474.8,
      thesis_invalidation: 440.67,
      primary_target: 488.8,
      extended_target: 493.4,
      hold_horizon_minutes: 60,
      generated_at: new Date().toISOString(),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });

    expect(result.execution_stop).toBe(474.8);
    expect(result.thesis_invalidation).toBe(440.67);
    expect(result.primary_target).toBe(488.8);
    expect(result.extended_target).toBe(493.4);
    expect(result.hold_horizon_minutes).toBe(60);
  });

  it("keeps mock call fixtures aligned with the current contract", () => {
    const parsed = freshCallResponseSchema.parse({
      ...latestMockCall("R_75"),
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });

    expect(parsed.guardian_state).toBe("actionable");
  });
});
