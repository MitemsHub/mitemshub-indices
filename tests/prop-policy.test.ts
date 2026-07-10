import { describe, expect, it } from "vitest";
import { evaluatePropCompliance } from "../src/lib/prop-policy";

describe("evaluatePropCompliance", () => {
  it("returns allowed_with_adjustment when risk exceeds the 1.5 percent trade-idea cap", () => {
    const result = evaluatePropCompliance({
      call: {
        symbol: "R_100",
        call: "buy_candidate",
        entry: 51234.6,
        stop_loss: 51188.2,
        reward_risk: 2,
      },
      accountState: {
        profile: "blueberry_2step_funded",
        startingBalance: 100000,
        currentBalance: 101200,
        currentEquity: 100800,
        todaysRealizedLoss: 0,
        todaysFloatingLossExposure: 0,
        highImpactNewsLockout: false,
      },
      proposedRiskPercent: 2,
    });

    expect(result.status).toBe("allowed_with_adjustment");
    expect(result.adjustedRiskPercent).toBe(1.5);
    expect(result.blockReason).toBeNull();
  });

  it("returns blocked when the daily loss buffer is exhausted", () => {
    const result = evaluatePropCompliance({
      call: {
        symbol: "R_75",
        call: "sell_candidate",
        entry: 320123.4,
        stop_loss: 321000.0,
        reward_risk: 1.8,
      },
      accountState: {
        profile: "blueberry_2step_funded",
        startingBalance: 100000,
        currentBalance: 96500,
        currentEquity: 95050,
        todaysRealizedLoss: 4800,
        todaysFloatingLossExposure: 250,
        highImpactNewsLockout: false,
      },
      proposedRiskPercent: 1,
    });

    expect(result.status).toBe("blocked");
    expect(result.blockReason).toContain("daily");
  });
});
