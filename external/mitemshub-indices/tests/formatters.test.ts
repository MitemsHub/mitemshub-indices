import { describe, expect, it } from "vitest";
import {
  formatActionSummary,
  formatCallAge,
  formatCallHeadline,
  formatGuardianState,
  formatMarketCopy,
  formatNextStep,
  formatSymbol,
} from "../src/lib/formatters";

describe("formatCallHeadline", () => {
  it("maps raw engine calls into trader-facing headlines", () => {
    expect(formatCallHeadline("buy_candidate")).toBe("Buy setup ready");
    expect(formatCallHeadline("sell_candidate")).toBe("Sell setup ready");
    expect(formatCallHeadline("stand_aside")).toBe("No trade yet");
  });
});

describe("formatActionSummary", () => {
  it("tells the trader to act when the setup is valid", () => {
    expect(
      formatActionSummary({
        call: "buy_candidate",
        trade_status: "valid",
        wait_for: "wait for a clean bullish continuation close",
      }),
    ).toMatch(/enter now/i);
  });

  it("tells the trader to stay out when the setup is not valid", () => {
    expect(
      formatActionSummary({
        call: "stand_aside",
        trade_status: "not_valid",
        wait_for: "wait for clearer structure and stronger confirmation",
      }),
    ).toMatch(/do not enter yet/i);
  });
});

describe("guardian wording", () => {
  it("maps live guardian states into trader-facing labels", () => {
    expect(formatGuardianState("actionable")).toBe("Actionable with caution");
    expect(formatGuardianState("failing")).toBe("Plan is losing strength");
    expect(formatGuardianState("cancelled")).toBe("Setup cancelled");
  });

  it("formats freshness metadata as call age", () => {
    expect(formatCallAge(2)).toBe("2s old");
    expect(formatCallAge(61)).toBe("1m 1s old");
  });
});

describe("formatSymbol", () => {
  it("maps R_75 to Volatility 75", () => {
    expect(formatSymbol("R_75")).toBe("Volatility 75");
  });

  it("maps R_100 to Volatility 100", () => {
    expect(formatSymbol("R_100")).toBe("Volatility 100");
  });

  it("handles null gracefully", () => {
    expect(formatSymbol(null)).toBe("Unknown");
  });

  it("handles undefined gracefully", () => {
    expect(formatSymbol(undefined)).toBe("Unknown");
  });

  it("falls through unknown symbols with a reasonable default", () => {
    expect(formatSymbol("BTC")).toBe("BTC");
  });
});

describe("plain-language market copy", () => {
  it("turns raw engine rationale into trader-facing language", () => {
    expect(
      formatMarketCopy("long setup in trend_up regime; confidence=0.635"),
    ).toBe("Buyers still have the edge in uptrend regime. Confidence is 64%");
  });

  it("explains wait conditions in normal language", () => {
    expect(formatNextStep("wait for bearish continuation below resistance")).toBe(
      "Price should reject resistance and close back lower before you enter.",
    );
  });
});
