import type { FreshCallResponse } from "./contracts";

export function formatConfidence(confidence: number | null): string {
  if (confidence === null) {
    return "Pending";
  }

  return `${Math.round(confidence * 100)}%`;
}

export function formatPrice(value: number | null): string {
  if (value === null) {
    return "N/A";
  }

  return value.toLocaleString("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

export function formatLabel(value: string | null): string {
  if (!value) {
    return "Unavailable";
  }

  if (value === "allowed_with_adjustment") {
    return "Allowed with adjustment";
  }

  if (value === "insufficient_account_state") {
    return "More account details needed";
  }

  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatCallHeadline(call: FreshCallResponse["call"]): string {
  if (call === "buy_candidate") {
    return "Buy setup ready";
  }

  if (call === "sell_candidate") {
    return "Sell setup ready";
  }

  return "No trade yet";
}

export function formatGuardianState(
  state: FreshCallResponse["guardian_state"] | null | undefined,
): string {
  if (!state) {
    return "Live read unavailable";
  }

  switch (state) {
    case "forming":
      return "Setup still forming";
    case "armed":
      return "Waiting for confirmation";
    case "confirmed":
      return "Confirmed and ready";
    case "weakening":
      return "Confirmation fading";
    case "invalidated":
      return "Setup invalidated";
    case "unavailable":
    default:
      return "Live read unavailable";
  }
}

export function formatGuardianReason(value: string | null | undefined): string {
  if (!value) {
    return "The live confirmation update is unavailable right now.";
  }

  const normalized = value.trim();
  const lower = normalized.toLowerCase();

  if (lower.includes("not yet armed")) {
    return "The setup is still forming, so stay patient.";
  }

  if (lower.includes("confirmation has not arrived yet")) {
    return "The setup is close, but confirmation has not arrived yet.";
  }

  if (lower.includes("confirmation received")) {
    if (lower.startsWith("buy confirmation")) {
      return "Buy confirmation is in place and the setup is ready to trade.";
    }

    if (lower.startsWith("sell confirmation")) {
      return "Sell confirmation is in place and the setup is ready to trade.";
    }

    return "Confirmation is in place and the setup is ready to trade.";
  }

  if (lower.includes("weakening") && lower.includes("clean entry")) {
    return "Momentum is fading, so do not treat this as a clean entry.";
  }

  if (lower.includes("unavailable")) {
    return "The live confirmation update is unavailable right now.";
  }

  return sentenceCase(normalized) ?? "The live confirmation update is unavailable right now.";
}

function sentenceCase(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim().replace(/^wait for\s+/i, "");
  if (!trimmed) {
    return null;
  }

  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

export function formatMarketCopy(value: string | null): string {
  if (!value) {
    return "Waiting for a fresh market reading.";
  }

  const normalized = value
    .replace(/long setup/gi, "buyers still have the edge")
    .replace(/short setup/gi, "sellers still have the edge")
    .replace(/trend_up/gi, "uptrend")
    .replace(/trend_down/gi, "downtrend")
    .replace(/trend_sideways/gi, "sideways market")
    .replace(/confidence=([0-9.]+)/gi, (_, confidence: string) => {
      const numeric = Number(confidence);
      if (!Number.isFinite(numeric)) {
        return "confidence is improving";
      }

      return `confidence is ${Math.round(numeric * 100)}%`;
    })
    .replace(/\s*;\s*/g, ". ")
    .replace(/\s+/g, " ")
    .replace(/\.\s*\./g, ".")
    .trim();

  return normalized
    .split(". ")
    .map((part) => part.replace(/^[a-z]/, (char) => char.toUpperCase()))
    .join(". ");
}

function translateWaitFor(waitFor: string | null): string | null {
  if (!waitFor) {
    return null;
  }

  const normalized = waitFor.trim().toLowerCase();

  if (normalized.includes("clean bullish continuation close")) {
    return "The next candle should close higher before you enter.";
  }

  if (normalized.includes("clean bearish continuation close")) {
    return "The next candle should close lower before you enter.";
  }

  if (normalized.includes("bearish continuation below resistance")) {
    return "Price should reject resistance and close back lower before you enter.";
  }

  if (normalized.includes("confidence above threshold")) {
    return "Stay out until the direction is clearer and the setup becomes stronger.";
  }

  if (normalized.includes("clearer structure")) {
    return "Stay out until price forms a cleaner structure.";
  }

  return sentenceCase(waitFor);
}

export function formatActionSummary({
  call,
  trade_status,
  wait_for,
}: Pick<FreshCallResponse, "call" | "trade_status" | "wait_for">): string {
  if (trade_status === "valid" && call !== "stand_aside") {
    const continuation = translateWaitFor(wait_for);

    return continuation
      ? `Enter now only if that confirmation has already printed and price is still near the planned entry. ${continuation} If price has already run, refresh the call before trading.`
      : "Enter now only if price is still close to the planned entry. If price has already run, refresh the call before trading.";
  }

  const missingCondition = translateWaitFor(wait_for);

  return missingCondition
    ? `Do not enter yet. ${missingCondition}`
    : "Do not enter yet. Wait for the next clean setup.";
}

export function formatNextStep(waitFor: string | null): string {
  const normalized = translateWaitFor(waitFor);
  return normalized ?? "Pull a fresh live reading before making a trade decision.";
}

export function formatPropProfile(value: string): string {
  return value
    .split("_")
    .map((part) => {
      if (/^\d/.test(part)) {
        return part.replace("step", "-Step");
      }

      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(" ");
}

export function formatPercent(value: number | null): string {
  return value === null ? "N/A" : `${value.toFixed(2)}%`;
}

export function formatTimestamp(value: string): string {
  return new Date(value).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
