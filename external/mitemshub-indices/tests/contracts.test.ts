import { describe, expect, it } from "vitest";
import {
  accountModeSchema,
  freshCallResponseSchema,
  guardianStateSchema,
  propComplianceSchema,
} from "../src/lib/contracts";

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
    // Inline fixture (mock-data.ts was removed in the sniper-only refactor).
    const parsed = freshCallResponseSchema.parse({
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

    expect(parsed.guardian_state).toBe("actionable");
  });

  it("accepts a fresh call response with a stage3 empirical gate block", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.62,
      regime: "range",
      direction_bias: "buy",
      why: "structure aligned",
      wait_for: "wait for confirmation",
      decision_summary: "buy setup ready",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable.",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
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
        suppressed_call: null,
        note: "24 scored outcomes; target-hit rate 62% clears 50% and the horizon verdict is calibrated.",
      },
    });

    expect(result.stage3?.state).toBe("gated");
    expect(result.stage3?.evidence_status).toBe("proven");
    expect(result.stage3?.empirical_target_hit_rate).toBe(0.62);
    expect(result.stage3?.horizon_verdict).toBe("calibrated");
  });

  it("accepts a stage3 block carrying tuned 60s p50/p90 multipliers and live bands", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.62,
      regime: "range",
      direction_bias: "buy",
      why: "structure aligned",
      wait_for: "wait for confirmation",
      decision_summary: "buy setup ready",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable.",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
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
        suppressed_call: null,
        note: "24 scored outcomes; target-hit rate 62% clears 50% and the horizon verdict is calibrated.",
        p50_mult: 1.52,
        p90_mult: 2.44,
        horizon_forecast: {
          "4h": {
            verdict: "calibrated",
            p50_mult: 1.52,
            p90_mult: 2.44,
            forecast: {
              current_close: 51240.1,
              range_p50_price: 310.5,
              range_p90_price: 820.0,
              expected_low_p50: 51090.0,
              expected_high_p50: 51400.0,
              expected_low_p90: 50820.0,
              expected_high_p90: 51660.0,
              projected_sigma_avg: 0.0041,
              confidence: 0.8,
              vol_trend: "stable",
            },
          },
          "6h": {
            verdict: "calibrated",
            p50_mult: 1.55,
            p90_mult: 2.5,
            forecast: {
              current_close: 51240.1,
              range_p50_price: 380.0,
              range_p90_price: 1000.0,
              expected_low_p50: 51050.0,
              expected_high_p50: 51430.0,
              expected_low_p90: 50740.0,
              expected_high_p90: 51740.0,
              projected_sigma_avg: 0.0041,
              confidence: 0.8,
              vol_trend: "stable",
            },
          },
        },
      },
    });

    expect(result.stage3?.p50_mult).toBe(1.52);
    expect(result.stage3?.p90_mult).toBe(2.44);
    expect(result.stage3?.horizon_forecast?.["4h"]?.forecast?.range_p50_price).toBe(310.5);
    expect(result.stage3?.horizon_forecast?.["4h"]?.forecast?.expected_high_p90).toBe(51660.0);
    expect(result.stage3?.horizon_forecast?.["6h"]?.p90_mult).toBe(2.5);
  });

  it("accepts a suppressed stage3 block (call held below the floor)", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "stand_aside",
      alert_type: "context_update",
      trade_status: "valid",
      confidence: 0.2,
      regime: "range",
      direction_bias: "buy",
      why: "suppressed by stage3",
      wait_for: null,
      decision_summary: null,
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable.",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
      stage3: {
        state: "suppressed",
        evidence_status: "suppressed",
        trigger_type: "continuation_close",
        empirical_target_hit_rate: 0.2,
        empirical_sample_count: 14,
        empirical_stop_hit_rate: 0.8,
        horizon_verdict: "calibrated",
        horizon_verdict_4h: "calibrated",
        horizon_verdict_6h: "calibrated",
        model_confidence: 0.71,
        display_confidence: 0.2,
        min_samples: 10,
        hit_rate_floor: 0.5,
        suppression_mode: "suppress",
        suppressed_call: "buy_candidate",
        note: "14 scored outcomes; target-hit rate 20% is BELOW the 50% floor — continuation_close calls are suppressed until the market-verified rate improves.",
      },
    });

    expect(result.call).toBe("stand_aside");
    expect(result.stage3?.state).toBe("suppressed");
    expect(result.stage3?.evidence_status).toBe("suppressed");
    expect(result.stage3?.suppressed_call).toBe("buy_candidate");
    expect(result.stage3?.hit_rate_floor).toBe(0.5);
    expect(result.stage3?.min_samples).toBe(10);
    expect(result.stage3?.suppression_mode).toBe("suppress");
  });

  it("accepts an annotate-mode below-floor stage3 block (call still emitted)", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.3,
      regime: "range",
      direction_bias: "buy",
      why: "below floor but annotate mode keeps it visible",
      wait_for: "wait for confirmation",
      decision_summary: null,
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable.",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
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
    });

    expect(result.call).toBe("buy_candidate");
    expect(result.stage3?.state).toBe("annotated");
    expect(result.stage3?.evidence_status).toBe("suppressed");
    expect(result.stage3?.suppression_mode).toBe("annotate");
    expect(result.stage3?.below_floor).toBe(true);
    expect(result.stage3?.sizing?.level).toBe("paper_only");
    expect(result.stage3?.suppressed_call).toBeNull();
  });

  it("accepts a stage3 block with empirical position sizing", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.62,
      regime: "range",
      direction_bias: "buy",
      why: "structure aligned",
      wait_for: "wait for confirmation",
      decision_summary: "buy setup ready",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable.",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
      size_multiplier: 0.5,
      position_sizing_empirical: "half",
      stage3: {
        state: "annotated",
        evidence_status: "proven",
        trigger_type: "continuation_close",
        empirical_target_hit_rate: 0.62,
        empirical_sample_count: 24,
        empirical_stop_hit_rate: 0.29,
        horizon_verdict: "needs_more_data_or_tuning",
        horizon_verdict_4h: "needs_more_data_or_tuning",
        horizon_verdict_6h: "needs_more_data_or_tuning",
        model_confidence: 0.71,
        display_confidence: 0.62,
        min_samples: 10,
        hit_rate_floor: 0.5,
        suppression_mode: "suppress",
        below_floor: false,
        sizing: {
          level: "half",
          multiplier: 0.5,
          basis: "annotated",
          reason: "62% hit rate clears the floor but the horizon verdict is not calibrated — half size",
        },
        suppressed_call: null,
        note: "24 scored outcomes; target-hit rate 62% clears the floor (horizon verdict not calibrated).",
      },
    });

    expect(result.stage3?.sizing?.level).toBe("half");
    expect(result.stage3?.sizing?.multiplier).toBe(0.5);
    expect(result.size_multiplier).toBe(0.5);
    expect(result.position_sizing_empirical).toBe("half");
  });

  it("accepts a still-learning stage3 block", () => {
    const result = freshCallResponseSchema.parse({
      symbol: "R_75",
      call: "buy_candidate",
      alert_type: "setup_candidate",
      trade_status: "valid",
      confidence: 0.71,
      regime: "range",
      direction_bias: "buy",
      why: "structure aligned",
      wait_for: "wait for confirmation",
      decision_summary: "buy setup ready",
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: 51234.6,
      stop_loss: 51188.2,
      take_profit: 51326.4,
      reward_risk: 2,
      current_close: 51240.1,
      guardian_state: "actionable",
      guardian_reason: "The setup is actionable.",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
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
        suppressed_call: null,
        note: "only 4/10 scored outcome(s) — the raw model confidence is shown; 6 more outcome(s) needed for an empirical verdict.",
      },
    });

    expect(result.stage3?.evidence_status).toBe("still_learning");
    expect(result.stage3?.empirical_sample_count).toBe(4);
  });

  it("rejects a stage3 block with an unknown state", () => {
    const payload = {
      symbol: "R_75",
      call: "stand_aside",
      alert_type: "context_update",
      trade_status: "not_valid",
      confidence: null,
      regime: null,
      direction_bias: null,
      why: null,
      wait_for: null,
      decision_summary: null,
      entry_area: null,
      stop_area: null,
      target_area: null,
      entry: null,
      stop_loss: null,
      take_profit: null,
      reward_risk: null,
      current_close: null,
      guardian_state: "forming",
      guardian_reason: "not armed",
      generated_at: "2026-07-12T12:00:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
      stage3: {
        state: "mystery_state",
        trigger_type: "continuation_close",
        empirical_target_hit_rate: 0.5,
        empirical_sample_count: 5,
        empirical_stop_hit_rate: 0.3,
        horizon_verdict: null,
        horizon_verdict_4h: null,
        horizon_verdict_6h: null,
        model_confidence: 0.5,
        display_confidence: 0.5,
        note: "bad state",
      },
    };

    expect(() => freshCallResponseSchema.parse(payload)).toThrow();
  });
});
