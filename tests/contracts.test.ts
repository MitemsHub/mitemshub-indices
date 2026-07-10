import { describe, expect, it } from "vitest";
import {
  accountModeSchema,
  freshCallResponseSchema,
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
});
